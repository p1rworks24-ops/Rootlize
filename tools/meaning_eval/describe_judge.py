"""Eval-only Describe → Judge Vision structure.

Stage 1 writes a query-independent visual description.
Candidate A Stage 2 judges from that evidence plus the image and query.
Candidate B Stage 2 judges from the query and description only; it does
not resend the original image. Product search is unchanged; this module
must not be imported by app/.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import math
import time

from app.relevance import RelevanceImage, RelevanceResult, rank_relevant_ids
from app.relevance.openai_provider import (
    OpenAIImageRelevanceProvider,
    SCHEMA_VERSION,
    SYSTEM_PROMPT,
    _BatchResult,
    _diagnostics_logger,
    _is_cancelled,
    _provider_error_reason,
    _unknown_result,
    relevance_schema,
)
from app.relevance.provider import RelevanceProviderError
from app.ui.images_search import vision_candidate_chunk_sizes
from tools.meaning_eval.pipeline import CHUNK, FIRST_CHUNK, _result_map

DESCRIBE_PROMPT_VERSION = "vision-describe-v1"
DESCRIBE_SCHEMA_VERSION = "image-description-v1"
DESCRIBE_JUDGE_VERSION = "vision-describe-judge-v1"
TEXT_JUDGE_VERSION = "vision-describe-text-judge-v1"
TEXT_JUDGE_SCHEMA_VERSION = "description-relevance-v1"
JUDGE_SCHEMA_VERSION = SCHEMA_VERSION
RESULT_DECISION_INCLUDE = "include_in_results"
RESULT_DECISION_EXCLUDE = "exclude_from_results"
RESULT_DECISIONS = (RESULT_DECISION_INCLUDE, RESULT_DECISION_EXCLUDE)

# gpt-5.4-mini list prices used only to estimate eval cost.
INPUT_USD_PER_MILLION = 0.75
OUTPUT_USD_PER_MILLION = 4.50

DESCRIPTION_FIELDS = (
    "primary_subject",
    "visual_contents",
    "presentation",
    "prominent_elements",
    "primary_vs_background",
)

DESCRIBE_PROMPT = """You describe images for a later generic image-search judge.

For every supplied image, write an objective visual description of what is
visible. Do not infer a user query. Do not guess what a user wanted.
Do not decide whether the image would be a useful search result.

Describe only visible evidence:

- primary_subject: the main thing the image is of, as a whole
- visual_contents: the main visible contents
- presentation: how the image is presented, such as a photograph,
  illustration, captured computer screen, program window, desktop
  environment, mixed, or another visible form. This is presentation, not
  a search type.
- prominent_elements: notable scene, objects, or on-screen UI that occupy
  attention
- primary_vs_background: what is primary versus background, surrounding
  chrome, or incidental

If the image shows a captured screen, describe the capture presentation and
the main content on that screen as distinct facts. Do not treat surrounding
chrome as the subject unless it is the main thing shown.

Use the same description standard for every image. Do not classify unseen
queries, and do not apply special-case rules for particular words.

Describe the visible image itself. Do not use filenames or assumed metadata.
Return exactly one result for every supplied image_id."""

DESCRIBE_USER_PREFIX = (
    "Describe every following image. Do not infer a user query or judge "
    "relevance."
)

EVIDENCE_USER_INSTRUCTIONS = (
    "A query-independent visual description is provided for each image. "
    "Use that evidence to keep the image's actual primary subject distinct "
    "from capture medium, surrounding chrome, and incidental elements. "
    "Verify the evidence against the image. Do not let the query rewrite "
    "what the image is primarily of."
)

TEXT_JUDGE_PROMPT = """You are a generic image-search result judge.

A user searched their own image library with the given query.
You will not see the original pixels. You will see a query-independent
visual description of the image. Judge only from the query and that
description.

For every supplied image, judge how reasonable it would be to show that
image as a search result for this query.

Judge search-result usefulness / image-query relevance, not mere object
presence. Ask: if the user ran this query, how appropriate would this
image be in the result list?

Consider the described image as a whole: its primary subject, type, style,
scene, and state. A match that is only incidental, tiny, background,
peripheral, or a small element inside UI or chrome is much less useful
than an image whose overall content is what the user asked for. Do not
score those incidental matches as highly as a primary match.

Treat the description's primary_subject, presentation, and
primary_vs_background as given facts. Do not rewrite the described
subject into a different match merely because the presentation is a
photographed scene, a captured computer screen, a program window, or
another medium.

Use the same usefulness standard for every query. Do not classify the
query into types, and do not apply special-case rules for particular
words.

These output fields are one judgement and must agree:
- result_decision is include_in_results only when a typical user would
  reasonably expect this image in the result list. Otherwise it is
  exclude_from_results.
- If the reason says the image is mainly something else, not what was
  asked for, only related, or only a fragment, result_decision must be
  exclude_from_results and relevance_score must be low.
- relevance_score is a number from 0 to 1 for how useful the image is as
  a result for this query. Higher means a more primary, intended match.
  include_in_results goes with a higher score. exclude_from_results goes
  with a lower score.
- confidence is how sure you are of this judgement. confidence is not
  relevance_score and is not result_decision.

Judge the described image itself. Do not use similarity scores, filenames,
ranking, or assumed metadata.
Return exactly one result for every supplied image_id."""

TEXT_JUDGE_USER_INSTRUCTIONS = (
    "A query-independent visual description is provided for each image. "
    "Judge only from the query and that description. The original image is "
    "not attached. Use the description's primary subject, presentation, and "
    "primary-versus-background split as written. Do not rewrite the described "
    "subject into a different match merely because the presentation is a "
    "captured screen, photograph, or other medium."
)


def description_schema(image_ids: Sequence[int]) -> dict:
    properties = {
        "image_id": {"type": "integer", "enum": list(image_ids)},
    }
    for name in DESCRIPTION_FIELDS:
        properties[name] = {"type": "string", "maxLength": 400}
    required = ["image_id", *DESCRIPTION_FIELDS]
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def format_evidence(description: dict) -> str:
    lines = ["Query-independent visual evidence:"]
    for name in DESCRIPTION_FIELDS:
        lines.append(f"- {name}: {description.get(name) or ''}")
    return "\n".join(lines)


def text_judge_schema(image_ids: Sequence[int]) -> dict:
    """Structured Output for description-only judging.

    result_decision is the include/exclude contract. relevant is derived
    from that enum in code so a low score and a 'not this subject' reason
    cannot independently vote true. This is not a score-threshold filter.
    """
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_id": {"type": "integer", "enum": list(image_ids)},
                        "result_decision": {
                            "type": "string",
                            "enum": list(RESULT_DECISIONS),
                        },
                        "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string", "maxLength": 160},
                    },
                    "required": [
                        "image_id",
                        "result_decision",
                        "relevance_score",
                        "confidence",
                        "reason",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def validate_text_judge_results(
    payload: dict, expected_ids: Sequence[int]
) -> tuple[RelevanceResult, ...]:
    expected = list(expected_ids)
    expected_set = set(expected)
    judged: dict[int, RelevanceResult] = {}
    unknown: dict[int, str] = {}
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return tuple(_unknown_result(image_id, "malformed") for image_id in expected)
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        try:
            image_id = int(raw["image_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if image_id not in expected_set or image_id in judged or image_id in unknown:
            continue
        decision = raw.get("result_decision")
        if decision not in RESULT_DECISIONS:
            unknown[image_id] = "malformed"
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if "relevance_score" not in raw:
            unknown[image_id] = "malformed"
            continue
        try:
            relevance_score = float(raw["relevance_score"])
        except (TypeError, ValueError):
            unknown[image_id] = "malformed"
            continue
        if not math.isfinite(relevance_score):
            unknown[image_id] = "malformed"
            continue
        relevance_score = max(0.0, min(1.0, relevance_score))
        judged[image_id] = RelevanceResult(
            image_id=image_id,
            relevant=(decision == RESULT_DECISION_INCLUDE),
            confidence=confidence,
            reason=str(raw.get("reason", ""))[:160],
            relevance_score=relevance_score,
        )
    for image_id in expected:
        if image_id not in judged and image_id not in unknown:
            unknown[image_id] = "omitted"
    by_id = dict(judged)
    for image_id, reason in unknown.items():
        by_id[image_id] = _unknown_result(image_id, reason)
    return tuple(by_id[image_id] for image_id in expected)


def empty_usage() -> dict:
    return {
        "request_count": 0,
        "request_attempt_count": 0,
        "retry_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "api_seconds": 0.0,
        "total_seconds": 0.0,
        "sent_image_count": 0,
    }


def add_usage(total: dict, extra: dict | None) -> dict:
    if not extra:
        return total
    for key in (
        "request_count",
        "request_attempt_count",
        "retry_count",
        "input_tokens",
        "output_tokens",
        "sent_image_count",
    ):
        total[key] = int(total.get(key, 0)) + int(extra.get(key, 0) or 0)
    for key in ("api_seconds", "total_seconds"):
        total[key] = float(total.get(key, 0.0)) + float(extra.get(key, 0.0) or 0.0)
    return total


def usage_from_run(run) -> dict:
    return {
        "request_count": int(getattr(run, "request_count", 0) or 0),
        "request_attempt_count": int(getattr(run, "request_attempt_count", 0) or 0),
        "retry_count": int(getattr(run, "retry_count", 0) or 0),
        "input_tokens": int(getattr(run, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(run, "output_tokens", 0) or 0),
        "api_seconds": float(getattr(run, "api_seconds", 0.0) or 0.0),
        "total_seconds": float(getattr(run, "total_seconds", 0.0) or 0.0),
        "sent_image_count": int(getattr(run, "sent_image_count", 0) or 0),
    }


def estimate_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * INPUT_USD_PER_MILLION
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MILLION
    )


def description_record(
    *,
    primary_subject: str = "",
    visual_contents: str = "",
    presentation: str = "",
    prominent_elements: str = "",
    primary_vs_background: str = "",
    unknown_reason: str | None = None,
) -> dict:
    return {
        "primary_subject": primary_subject,
        "visual_contents": visual_contents,
        "presentation": presentation,
        "prominent_elements": prominent_elements,
        "primary_vs_background": primary_vs_background,
        "unknown_reason": unknown_reason,
    }


@dataclass(frozen=True)
class ImageDescription:
    image_id: int
    primary_subject: str = ""
    visual_contents: str = ""
    presentation: str = ""
    prominent_elements: str = ""
    primary_vs_background: str = ""
    unknown_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.unknown_reason is None

    def to_record(self) -> dict:
        return description_record(
            primary_subject=self.primary_subject,
            visual_contents=self.visual_contents,
            presentation=self.presentation,
            prominent_elements=self.prominent_elements,
            primary_vs_background=self.primary_vs_background,
            unknown_reason=self.unknown_reason,
        )


@dataclass(frozen=True)
class DescriptionRun:
    results: tuple[ImageDescription, ...]
    failed_image_ids: tuple[int, ...] = ()
    request_count: int = 0
    sent_image_count: int = 0
    resize_seconds: float = 0.0
    api_seconds: float = 0.0
    total_seconds: float = 0.0
    retry_count: int = 0
    request_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


def _unknown_description(image_id: int, reason: str) -> ImageDescription:
    return ImageDescription(image_id=image_id, unknown_reason=reason)


def _clip(value: object, limit: int = 400) -> str:
    return str(value or "")[:limit]


def _validate_descriptions(
    payload: dict, expected_ids: Sequence[int]
) -> tuple[ImageDescription, ...]:
    expected = list(expected_ids)
    expected_set = set(expected)
    judged: dict[int, ImageDescription] = {}
    unknown: dict[int, str] = {}
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return tuple(_unknown_description(image_id, "malformed") for image_id in expected)
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        try:
            image_id = int(raw["image_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if image_id not in expected_set or image_id in judged or image_id in unknown:
            continue
        missing = [name for name in DESCRIPTION_FIELDS if name not in raw]
        if missing:
            unknown[image_id] = "malformed"
            continue
        judged[image_id] = ImageDescription(
            image_id=image_id,
            primary_subject=_clip(raw.get("primary_subject")),
            visual_contents=_clip(raw.get("visual_contents")),
            presentation=_clip(raw.get("presentation")),
            prominent_elements=_clip(raw.get("prominent_elements")),
            primary_vs_background=_clip(raw.get("primary_vs_background")),
        )
    for image_id in expected:
        if image_id not in judged and image_id not in unknown:
            unknown[image_id] = "omitted"
    by_id = dict(judged)
    for image_id, reason in unknown.items():
        by_id[image_id] = _unknown_description(image_id, reason)
    return tuple(by_id[image_id] for image_id in expected)


class VisualDescribeProvider(OpenAIImageRelevanceProvider):
    """Query-free visual description. Eval-only; not used by product search."""

    def classify(self, query, images, *, cancelled=None):
        raise RuntimeError("VisualDescribeProvider.describe() must be used; classify() would send a query.")

    def describe(
        self,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> DescriptionRun:
        if not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        images_by_id = {item.image_id: item for item in images}
        judged: dict[int, ImageDescription] = {}
        unknown: dict[int, str] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        logger = _diagnostics_logger()

        def absorb(batch: _BatchResult, parsed: tuple[ImageDescription, ...]) -> None:
            nonlocal request_count
            request_count += 1
            completed.append(batch)
            for item in parsed:
                if item.unknown_reason:
                    if item.image_id not in judged:
                        unknown[item.image_id] = item.unknown_reason
                else:
                    judged[item.image_id] = item
                    unknown.pop(item.image_id, None)
            unknown_ids = tuple(item.image_id for item in parsed if item.unknown_reason)
            if unknown_ids:
                reasons = sorted({
                    item.unknown_reason or "unknown"
                    for item in parsed
                    if item.unknown_reason
                })
                errors.append(
                    f"Vision API left {len(unknown_ids)} image(s) unknown ({', '.join(reasons)})."
                )

        batches = [
            tuple(images[index:index + self.batch_size])
            for index in range(0, len(images), self.batch_size)
        ]
        if batches:
            workers = min(self.max_workers, max(1, len(batches)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending = {
                    pool.submit(self._describe_batch, batch): batch
                    for batch in batches
                }
                for future in as_completed(pending):
                    batch = pending[future]
                    if _is_cancelled(cancelled):
                        for item in batch:
                            unknown.setdefault(item.image_id, "cancelled")
                        continue
                    try:
                        raw_batch, parsed = future.result()
                        absorb(raw_batch, parsed)
                    except Exception as exc:
                        message = self._safe_error(exc)
                        errors.append(message)
                        logger.warning(
                            "Vision-describe batch-failure reason=api_failure image_ids=%s error=%s",
                            [item.image_id for item in batch], message,
                        )
                        raw_batch = self._unknown_batch(
                            tuple(item.image_id for item in batch), "api_failure",
                        )
                        absorb(
                            raw_batch,
                            tuple(_unknown_description(item.image_id, "api_failure") for item in batch),
                        )

        retry_round = 0
        while unknown and retry_round < self.unknown_retries:
            if _is_cancelled(cancelled):
                break
            retry_round += 1
            remaining = tuple(
                images_by_id[image_id]
                for image_id in images_by_id
                if image_id in unknown
            )
            retry_batches = [
                remaining[index:index + self.retry_batch_size]
                for index in range(0, len(remaining), self.retry_batch_size)
            ]
            for retry_batch in retry_batches:
                if _is_cancelled(cancelled):
                    break
                with self._request_stats_lock:
                    self._retry_count += 1
                try:
                    raw_batch, parsed = self._describe_batch(retry_batch)
                    absorb(raw_batch, parsed)
                except Exception as exc:
                    message = self._safe_error(exc)
                    errors.append(message)
                    raw_batch = self._unknown_batch(
                        tuple(item.image_id for item in retry_batch), "api_failure",
                    )
                    absorb(
                        raw_batch,
                        tuple(
                            _unknown_description(item.image_id, "api_failure")
                            for item in retry_batch
                        ),
                    )

        if unknown:
            exhausted = (
                not _is_cancelled(cancelled)
                and retry_round >= self.unknown_retries > 0
            )
            reason = "retry_exhausted" if exhausted else None
            for image_id, prior in list(unknown.items()):
                judged.setdefault(
                    image_id,
                    _unknown_description(image_id, reason or prior),
                )
            unknown.clear()

        for item in images:
            judged.setdefault(item.image_id, _unknown_description(item.image_id, "unknown"))
        ordered = tuple(judged[item.image_id] for item in images)
        failed_ids = tuple(item.image_id for item in ordered if item.unknown_reason)
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return DescriptionRun(
            results=ordered,
            failed_image_ids=failed_ids,
            request_count=request_count,
            sent_image_count=len(images),
            resize_seconds=sum(batch.resize_seconds for batch in completed),
            api_seconds=sum(batch.api_seconds for batch in completed),
            total_seconds=time.perf_counter() - started,
            retry_count=retry_count,
            request_attempt_count=request_attempt_count,
            input_tokens=sum(batch.input_tokens for batch in completed),
            output_tokens=sum(batch.output_tokens for batch in completed),
            errors=tuple(errors),
        )

    def _describe_batch(
        self, batch: Sequence[RelevanceImage]
    ) -> tuple[_BatchResult, tuple[ImageDescription, ...]]:
        ids = tuple(item.image_id for item in batch)
        resize_started = time.perf_counter()
        resize_seconds = 0.0
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            encoded = list(zip(batch, self._prepare_images([item.path for item in batch])))
            resize_seconds = time.perf_counter() - resize_started
            content: list[dict] = [{"type": "text", "text": DESCRIBE_USER_PREFIX}]
            for item, encoded_image in encoded:
                content.append({"type": "text", "text": f"image_id: {item.image_id}"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": encoded_image.data_url, "detail": self.image_detail},
                })
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "image_description",
                        "strict": True,
                        "schema": description_schema(ids),
                    },
                },
            }
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            diagnostics = tuple(
                {
                    "image_id": item.image_id,
                    "jpeg_sha256": encoded_image.sha256,
                    "jpeg_width": encoded_image.width,
                    "jpeg_height": encoded_image.height,
                }
                for item, encoded_image in encoded
            )
            api_started = time.perf_counter()
            response = self._post_with_retry(payload, image_diagnostics=diagnostics)
            api_seconds = time.perf_counter() - api_started
            try:
                raw_content = response["choices"][0]["message"]["content"]
                parsed_payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RelevanceProviderError("Vision API returned an invalid structured result.") from exc
            parsed = _validate_descriptions(parsed_payload, ids)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            omitted = [item.image_id for item in parsed if item.unknown_reason == "omitted"]
            malformed = [item.image_id for item in parsed if item.unknown_reason == "malformed"]
            if omitted:
                logger.warning(
                    "Vision-describe batch-omitted image_ids=%s omitted_ids=%s",
                    list(ids), omitted,
                )
            if malformed:
                logger.warning(
                    "Vision-describe batch-malformed image_ids=%s malformed_ids=%s",
                    list(ids), malformed,
                )
            batch_result = _BatchResult(
                results=tuple(_unknown_result(item.image_id, item.unknown_reason or "ok") for item in parsed),
                image_ids=ids,
                resize_seconds=resize_seconds,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
            return batch_result, parsed
        except RelevanceProviderError as exc:
            reason = _provider_error_reason(exc)
            logger.warning(
                "Vision-describe batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return (
                self._unknown_batch(ids, reason, resize_seconds, api_seconds),
                tuple(_unknown_description(image_id, reason) for image_id in ids),
            )
        except json.JSONDecodeError:
            logger.warning(
                "Vision-describe batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return (
                self._unknown_batch(ids, "malformed", resize_seconds, api_seconds),
                tuple(_unknown_description(image_id, "malformed") for image_id in ids),
            )


class EvidenceJudgeProvider(OpenAIImageRelevanceProvider):
    """Product usefulness judge with query-independent visual evidence injected."""

    def __init__(self, *, evidence_by_image_id: dict[int, dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.evidence_by_image_id = dict(evidence_by_image_id or {})

    def _classify_batch(self, query: str, batch: Sequence[RelevanceImage]) -> _BatchResult:
        ids = tuple(item.image_id for item in batch)
        resize_started = time.perf_counter()
        resize_seconds = 0.0
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            encoded = list(zip(batch, self._prepare_images([item.path for item in batch])))
            resize_seconds = time.perf_counter() - resize_started
            content: list[dict] = [{"type": "text", "text": (
                f"Search query: {query!r}\n"
                "Judge every following image as a search result for this query.\n"
                f"{EVIDENCE_USER_INSTRUCTIONS}"
            )}]
            for item, encoded_image in encoded:
                evidence = self.evidence_by_image_id.get(item.image_id) or {}
                content.append({"type": "text", "text": f"image_id: {item.image_id}"})
                content.append({"type": "text", "text": format_evidence(evidence)})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": encoded_image.data_url, "detail": self.image_detail},
                })
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "image_relevance",
                        "strict": True,
                        "schema": relevance_schema(
                            ids,
                            include_relevance_score=self.include_relevance_score,
                        ),
                    },
                },
            }
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            diagnostics = tuple(
                {
                    "image_id": item.image_id,
                    "jpeg_sha256": encoded_image.sha256,
                    "jpeg_width": encoded_image.width,
                    "jpeg_height": encoded_image.height,
                }
                for item, encoded_image in encoded
            )
            api_started = time.perf_counter()
            response = self._post_with_retry(payload, image_diagnostics=diagnostics)
            api_seconds = time.perf_counter() - api_started
            results = self._results_from_response(response, ids)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            self._log_partial_batch(logger, ids, results)
            return _BatchResult(
                results=results,
                image_ids=ids,
                resize_seconds=resize_seconds,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
        except RelevanceProviderError as exc:
            reason = _provider_error_reason(exc)
            logger.warning(
                "Vision-relevance batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return self._unknown_batch(ids, reason, resize_seconds, api_seconds)
        except json.JSONDecodeError:
            logger.warning(
                "Vision-relevance batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return self._unknown_batch(ids, "malformed", resize_seconds, api_seconds)


class DescriptionOnlyJudgeProvider(OpenAIImageRelevanceProvider):
    """Stage 2 judge that sees query + description only. No original image."""

    def __init__(self, *, evidence_by_image_id: dict[int, dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.evidence_by_image_id = dict(evidence_by_image_id or {})

    def classify(self, query, images, *, cancelled=None):
        run = super().classify(query, images, cancelled=cancelled)
        return replace(run, sent_image_count=0, resize_seconds=0.0)

    def _results_from_response(self, response: dict, expected_ids: Sequence[int]):
        try:
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RelevanceProviderError("Vision API returned an invalid structured result.") from exc
        if not isinstance(parsed, dict):
            raise RelevanceProviderError("Vision API returned an invalid structured result.")
        return validate_text_judge_results(parsed, expected_ids)

    def _classify_batch(self, query: str, batch: Sequence[RelevanceImage]) -> _BatchResult:
        ids = tuple(item.image_id for item in batch)
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            content: list[dict] = [{"type": "text", "text": (
                f"Search query: {query!r}\n"
                "Judge every following image as a search result for this query.\n"
                f"{TEXT_JUDGE_USER_INSTRUCTIONS}"
            )}]
            for item in batch:
                evidence = self.evidence_by_image_id.get(item.image_id) or {}
                content.append({"type": "text", "text": f"image_id: {item.image_id}"})
                content.append({"type": "text", "text": format_evidence(evidence)})
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "description_relevance",
                        "strict": True,
                        "schema": text_judge_schema(ids),
                    },
                },
            }
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            api_started = time.perf_counter()
            response = self._post_with_retry(payload, image_diagnostics=())
            api_seconds = time.perf_counter() - api_started
            results = self._results_from_response(response, ids)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            self._log_partial_batch(logger, ids, results)
            return _BatchResult(
                results=results,
                image_ids=ids,
                resize_seconds=0.0,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
        except RelevanceProviderError as exc:
            reason = _provider_error_reason(exc)
            logger.warning(
                "Vision-relevance batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return self._unknown_batch(ids, reason, 0.0, api_seconds)
        except json.JSONDecodeError:
            logger.warning(
                "Vision-relevance batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return self._unknown_batch(ids, "malformed", 0.0, api_seconds)


def make_describe_provider() -> VisualDescribeProvider:
    return VisualDescribeProvider(
        max_edge=512,
        image_detail="low",
        temperature=0,
        system_prompt=DESCRIBE_PROMPT,
        prompt_version=DESCRIBE_PROMPT_VERSION,
        include_relevance_score=False,
    )


def make_evidence_judge_provider(
    evidence_by_image_id: dict[int, dict] | None = None,
) -> EvidenceJudgeProvider:
    return EvidenceJudgeProvider(
        evidence_by_image_id=evidence_by_image_id,
        max_edge=2048,
        image_detail="high",
        temperature=0,
        system_prompt=SYSTEM_PROMPT,
        prompt_version=DESCRIBE_JUDGE_VERSION,
    )


def make_text_judge_provider(
    evidence_by_image_id: dict[int, dict] | None = None,
) -> DescriptionOnlyJudgeProvider:
    return DescriptionOnlyJudgeProvider(
        evidence_by_image_id=evidence_by_image_id,
        max_edge=512,
        image_detail="low",
        temperature=0,
        system_prompt=TEXT_JUDGE_PROMPT,
        prompt_version=TEXT_JUDGE_VERSION,
    )


def describe_paths(
    paths: Sequence[Path],
    provider: VisualDescribeProvider,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[dict[str, dict], dict]:
    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    run = provider.describe(images, cancelled=cancelled)
    by_name = {}
    for item, result in zip(images, run.results):
        record = result.to_record()
        record["image_id"] = item.image_id
        by_name[item.path.name] = record
    return by_name, usage_from_run(run)


def load_description_cache(path: Path) -> tuple[dict[str, dict], dict] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != DESCRIBE_PROMPT_VERSION:
        return None
    if payload.get("schema_version") != DESCRIBE_SCHEMA_VERSION:
        return None
    by_name = payload.get("by_name")
    if not isinstance(by_name, dict):
        return None
    return by_name, dict(payload.get("usage") or empty_usage())


def save_description_cache(
    path: Path, by_name: dict[str, dict], usage: dict
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt_version": DESCRIBE_PROMPT_VERSION,
                "schema_version": DESCRIBE_SCHEMA_VERSION,
                "usage": usage,
                "by_name": by_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def load_or_describe_paths(
    paths: Sequence[Path],
    cache_path: Path,
    *,
    provider: VisualDescribeProvider | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[dict[str, dict], dict]:
    cached = load_description_cache(cache_path)
    needed = {path.name for path in paths}
    if cached is not None:
        by_name, usage = cached
        if needed <= set(by_name):
            return by_name, usage
    provider = provider or make_describe_provider()
    by_name, usage = describe_paths(paths, provider, cancelled=cancelled)
    save_description_cache(cache_path, by_name, usage)
    return by_name, usage


def judge_ranked_paths_described(
    query: str,
    ranked_paths: Sequence[Path],
    descriptions_by_name: dict[str, dict],
    *,
    cancelled: Callable[[], bool] | None = None,
    judge_provider: OpenAIImageRelevanceProvider | None = None,
    text_only: bool = False,
) -> dict:
    """Describe-then-judge. Stage 1 is evidence, not a relevance gate.

    text_only=True is Candidate B: Stage 2 sees query + description only.
    """
    relevance_images = [
        RelevanceImage(index, path) for index, path in enumerate(ranked_paths, 1)
    ]
    names_by_id = {item.image_id: item.path.name for item in relevance_images}
    embedding_ranks = {item.image_id: item.image_id for item in relevance_images}
    descriptions_by_id = {}
    for item in relevance_images:
        record = descriptions_by_name.get(item.path.name)
        if record:
            descriptions_by_id[item.image_id] = record
    if judge_provider is not None:
        provider = judge_provider
    elif text_only:
        provider = make_text_judge_provider(descriptions_by_id)
    else:
        provider = make_evidence_judge_provider(descriptions_by_id)
    if hasattr(provider, "evidence_by_image_id"):
        provider.evidence_by_image_id = descriptions_by_id
    high_by_id = {}
    high_skipped = {}
    relevant_ids: set[int] = set()
    unknown_ids: set[int] = set()
    failed_ids: set[int] = set()
    cancelled_run = False
    usage = empty_usage()
    offset = 0
    for chunk_size in vision_candidate_chunk_sizes(
        len(relevance_images), first_size=FIRST_CHUNK, chunk_size=CHUNK
    ):
        if cancelled is not None and cancelled():
            cancelled_run = True
            break
        chunk = relevance_images[offset:offset + chunk_size]
        offset += chunk_size
        judge_chunk = []
        for item in chunk:
            record = descriptions_by_id.get(item.image_id)
            if record is None or record.get("unknown_reason"):
                unknown_ids.add(item.image_id)
                high_skipped[item.image_id] = "describe_unknown"
                if record is not None and record.get("unknown_reason") == "api_failure":
                    failed_ids.add(item.image_id)
            else:
                judge_chunk.append(item)
        if cancelled is not None and cancelled():
            cancelled_run = True
            for item in judge_chunk:
                high_skipped[item.image_id] = "search_cancelled_before_high"
            break
        if not judge_chunk:
            continue
        high_run = provider.classify(query, judge_chunk, cancelled=cancelled)
        add_usage(usage, usage_from_run(high_run))
        failed_ids.update(high_run.failed_image_ids)
        if cancelled is not None and cancelled():
            cancelled_run = True
            for item in judge_chunk:
                high_skipped[item.image_id] = "search_cancelled_after_high"
            break
        high_by_id.update(_result_map(high_run))
        high_unknown = set(high_run.failed_image_ids) | {
            item.image_id for item in high_run.results if item.relevant is None
        }
        unknown_ids.update(high_unknown)
        for image_id in high_unknown:
            high_skipped[image_id] = "high_unknown"
        for item in high_run.results:
            if item.relevant is True:
                relevant_ids.add(item.image_id)
                unknown_ids.discard(item.image_id)
            elif item.relevant is False:
                unknown_ids.discard(item.image_id)

    scores = {}
    for image_id in relevant_ids:
        high_result = high_by_id.get(image_id)
        scores[image_id] = None if high_result is None else high_result.relevance_score
    ordered_ids = rank_relevant_ids(
        [item.image_id for item in relevance_images],
        relevant_ids=relevant_ids,
        relevance_scores=scores,
        embedding_ranks=embedding_ranks,
    )
    judgements = {}
    for item in relevance_images:
        image_id = item.image_id
        name = names_by_id[image_id]
        high_result = high_by_id.get(image_id)
        description = descriptions_by_id.get(image_id)
        if image_id in relevant_ids:
            final = True
        elif image_id in unknown_ids:
            final = None
        elif high_result is None:
            final = None
        else:
            final = False
        unknown_reason = None
        if final is None:
            if high_result is not None and high_result.unknown_reason:
                unknown_reason = high_result.unknown_reason
            elif description and description.get("unknown_reason"):
                unknown_reason = description.get("unknown_reason")
            else:
                unknown_reason = high_skipped.get(image_id)
        judgements[name] = {
            "relevant": final,
            "low_relevant": None,
            "high_relevant": None if high_result is None else high_result.relevant,
            "relevance_score": None if high_result is None else high_result.relevance_score,
            "low_relevance_score": None,
            "high_relevance_score": None if high_result is None else high_result.relevance_score,
            "confidence": None if high_result is None else high_result.confidence,
            "reason": (
                None if high_result is None else high_result.reason
            ) or high_skipped.get(image_id),
            "unknown_reason": unknown_reason,
            "high_skipped_reason": high_skipped.get(image_id),
            "retrieval_rank": embedding_ranks[image_id],
            "description": None if description is None else {
                name: description.get(name) for name in DESCRIPTION_FIELDS
            },
            "describe_unknown_reason": None if description is None else description.get("unknown_reason"),
        }
    predicted = [names_by_id[image_id] for image_id in ordered_ids]
    return {
        "predicted": predicted,
        "judgements": judgements,
        "cancelled": cancelled_run,
        "failed_names": sorted(names_by_id[image_id] for image_id in failed_ids if image_id in names_by_id),
        "unjudged_names": [
            item.path.name for item in relevance_images
            if item.image_id not in high_by_id and item.image_id not in unknown_ids
        ],
        "usage": usage,
    }
