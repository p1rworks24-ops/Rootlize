"""Eval-only Semantic Index evidence → Text AI ternary judge.

Product search, Hybrid, Vision Judge prompts, Index generation, matcher,
threshold, GT, and the query set are unchanged. This module must not be
imported by app/.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import json
import math
import re
import time

from app.relevance import RelevanceImage
from app.relevance.openai_provider import (
    DEFAULT_MODEL,
    OpenAIImageRelevanceProvider,
    _BatchResult,
    _diagnostics_logger,
    _is_cancelled,
    _provider_error_reason,
)
from app.relevance.provider import RelevanceProviderError
from app.semantic_index.schema import INDEX_FIELDS, INDEX_PROMPT_VERSION, INDEX_SCHEMA_VERSION


class QuotaExhaustedError(RelevanceProviderError):
    """OpenAI credit_balance_exhausted. Do not retry."""

PROMPT_VERSION = "evidence-text-ternary-v1"
SCHEMA_VERSION = "evidence-relevance-v1"
DECISIONS = ("relevant", "irrelevant", "insufficient_evidence")
NESTED_DOG_IMAGES = (
    "20260813_225929.png",
    "20260815_221055.png",
    "20260815_231828.png",
)
DOG_HINT_RE = re.compile(
    r"\b(dogs?|puppy|puppies|canine|hund|犬)\b",
    re.IGNORECASE,
)
ANIMAL_HINT_RE = re.compile(
    r"\b(animals?|pets?|wildlife|thumbnails? of animals?|animal photos?)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are a generic image-search result judge.

A user searched their own image library with the given query.
You will not see the original pixels. You will see query-independent
Semantic Index evidence already extracted from the image. Judge only
from the query and that evidence.

Judge confirmability of what the query specified, not typicality,
centrality, or whether the image is mainly about the query.
Ask: can a human reasonably confirm, from this evidence, the content,
attributes, states, and relations named by the query?

Interpret the query as meaning, not as a bag of words.
A noun phrase, proper name, or compound concept is one condition, even
when it contains several words. Do not split those phrases into separate
word-by-word AND requirements.
Independent conditions are only the extra constraints the user actually
added: attributes, states, additional targets, an environment, or a
relation. A single named concept is one condition.

If the query names only a target or concept, that target or concept
being reasonably identifiable is enough. It does not have to be the
primary subject, the largest object, the foreground, or the most
important thing shown. A match may be in the background, behind another
window, nested inside another app, shown as a thumbnail or preview, or
sharing the frame with unrelated content.

If the query adds attributes, states, multiple targets, an environment,
or a relation, every added independent condition must also be true in
the same image. Satisfying only some of the specified independent
conditions is not relevant.

The evidence is incomplete. It records what was already identified.
It is not a complete photograph. Use exactly one of these decisions:

- relevant: the evidence reasonably confirms every independent condition
  specified by the query. Background, nested, thumbnail, and mixed-frame
  matches are allowed when identifiable from the evidence.
- irrelevant: the evidence is enough to reasonably conclude that at least
  one specified independent condition does not hold. A missing mention is
  not a contradiction. Use irrelevant only when the evidence positively
  conflicts with, or rules out, a required condition.
- insufficient_evidence: the evidence does not confirm the query, and
  also does not reasonably rule it out. Omitted objects, weak or
  uncertain identifications, and "not written down" cases belong here.
  Prefer insufficient_evidence over irrelevant whenever you would have
  to guess.

unknown is not false. Index silence is not a negative.

Do not invent extra requirements the query did not state, such as
importance, uniqueness, typical appearance, or that other content must
not share the frame.
Do not treat a listed searchable word as confirmation unless surrounding
evidence supports that the named thing is actually present.
Do not use filenames, ranking, or assumed metadata.

confidence is how sure you are of this decision. It is not a relevance
score and must not change the decision.
short_reason is a brief evaluation note. The decision field is the
judgement; do not let the reason override it.
missing_evidence is required when decision is insufficient_evidence:
name the information that would be needed. Otherwise leave it empty.

Return exactly one result for every supplied image_id."""

USER_INSTRUCTIONS = (
    "You will not see the original image. Judge only from the query and "
    "the Semantic Index evidence. Treat noun phrases, proper names, and "
    "compound concepts as single conditions, not as separate words to AND. "
    "Absence of a mention is not a contradiction. unknown is not false."
)


def evidence_schema(image_ids: Sequence[int]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_id": {"type": "integer", "enum": list(image_ids)},
                        "decision": {"type": "string", "enum": list(DECISIONS)},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "short_reason": {"type": "string", "maxLength": 160},
                        "missing_evidence": {"type": "string", "maxLength": 160},
                    },
                    "required": [
                        "image_id",
                        "decision",
                        "confidence",
                        "short_reason",
                        "missing_evidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def _join_list(value: object) -> str:
    if not value:
        return "(none recorded; this does not prove absence)"
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return "(none recorded; this does not prove absence)"
        return "; ".join(items)
    text = str(value).strip()
    return text or "(none recorded; this does not prove absence)"


def format_index_evidence(record: dict) -> str:
    """Compact, reproducible evidence. Keeps Index meaning; not a raw dump."""
    identities = record.get("identities") or []
    identity_lines = []
    if identities:
        for item in identities:
            if not isinstance(item, dict):
                continue
            identity_lines.append(
                "  - {name} (kind={kind}, importance={importance}, "
                "confidence={confidence}): {evidence}".format(
                    name=str(item.get("name") or "").strip() or "(unnamed)",
                    kind=str(item.get("kind") or "").strip() or "other",
                    importance=str(item.get("importance") or "").strip() or "unspecified",
                    confidence=str(item.get("confidence") or "").strip() or "unspecified",
                    evidence=str(item.get("evidence") or "").strip() or "(no evidence phrase)",
                )
            )
    else:
        identity_lines.append(
            "  - (none recorded; this does not prove absence)"
        )
    lines = [
        "Semantic Index evidence (query-independent; not the original image):",
        f"- summary: {_join_list(record.get('visual_summary'))}",
        f"- media_type: {_join_list(record.get('media_type'))}",
        f"- scene_environment: {_join_list(record.get('scene_environment'))}",
        "- identities:",
        *identity_lines,
        f"- objects_entities: {_join_list(record.get('objects_entities'))}",
        f"- ui_interface_concepts: {_join_list(record.get('ui_interface_concepts'))}",
        f"- visible_activities: {_join_list(record.get('visible_activities'))}",
        f"- visual_attributes: {_join_list(record.get('visual_attributes'))}",
        f"- searchable_concepts: {_join_list(record.get('searchable_concepts'))}",
        f"- incidental_notes: {_join_list(record.get('incidental_notes'))}",
    ]
    return "\n".join(lines)


def flatten_index_text(record: dict) -> str:
    parts: list[str] = []
    for name in INDEX_FIELDS:
        value = record.get(name)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.extend(str(item.get(key) or "") for key in item)
                else:
                    parts.append(str(item or ""))
        else:
            parts.append(str(value or ""))
    return "\n".join(part for part in parts if part)


def classify_nested_dog_index(record: dict | None) -> dict:
    if not record:
        return {
            "index_class": "missing_index",
            "dog_mention": False,
            "animal_mention": False,
            "excerpt": "",
        }
    text = flatten_index_text(record)
    dog_mention = bool(DOG_HINT_RE.search(text))
    animal_mention = bool(ANIMAL_HINT_RE.search(text))
    if dog_mention:
        index_class = "index_has_dog"
    elif animal_mention:
        index_class = "index_has_animal_not_dog"
    else:
        index_class = "index_missing_dog"
    return {
        "index_class": index_class,
        "dog_mention": dog_mention,
        "animal_mention": animal_mention,
        "excerpt": {
            "visual_summary": record.get("visual_summary") or "",
            "objects_entities": list(record.get("objects_entities") or []),
            "incidental_notes": record.get("incidental_notes") or "",
            "identities": list(record.get("identities") or []),
        },
    }


def classify_nested_dog_outcome(index_class: str, decision: str) -> str:
    if index_class == "index_has_dog":
        if decision == "relevant":
            return "evidence_present_and_text_ok"
        if decision == "insufficient_evidence":
            return "evidence_present_but_text_uncertain"
        return "evidence_present_text_failed"
    if decision == "irrelevant":
        return "evidence_gap_treated_as_negative"
    if decision == "relevant":
        return "text_inferred_without_dog_evidence"
    return "insufficient_index"


@dataclass(frozen=True)
class TernaryResult:
    image_id: int
    decision: str
    confidence: float
    short_reason: str = ""
    missing_evidence: str = ""
    unknown_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.unknown_reason is None and self.decision in DECISIONS


@dataclass(frozen=True)
class TernaryRun:
    results: tuple[TernaryResult, ...]
    failed_image_ids: tuple[int, ...] = ()
    request_count: int = 0
    sent_image_count: int = 0
    api_seconds: float = 0.0
    total_seconds: float = 0.0
    retry_count: int = 0
    request_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
    model: str = DEFAULT_MODEL
    temperature: float | None = 0.0


def _unknown_ternary(image_id: int, reason: str) -> TernaryResult:
    return TernaryResult(
        image_id=image_id,
        decision="insufficient_evidence",
        confidence=0.0,
        short_reason="Text judge did not return a usable decision.",
        missing_evidence="text_judge_failed",
        unknown_reason=reason,
    )


def validate_ternary_results(
    payload: dict, expected_ids: Sequence[int]
) -> tuple[TernaryResult, ...]:
    expected = list(expected_ids)
    expected_set = set(expected)
    judged: dict[int, TernaryResult] = {}
    unknown: dict[int, str] = {}
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return tuple(_unknown_ternary(image_id, "malformed") for image_id in expected)
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        try:
            image_id = int(raw["image_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if image_id not in expected_set or image_id in judged or image_id in unknown:
            continue
        decision = raw.get("decision")
        if decision not in DECISIONS:
            unknown[image_id] = "malformed"
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if not math.isfinite(confidence):
            unknown[image_id] = "malformed"
            continue
        missing = str(raw.get("missing_evidence") or "")[:160]
        if decision == "insufficient_evidence" and not missing.strip():
            missing = "unspecified"
        if decision != "insufficient_evidence":
            missing = ""
        judged[image_id] = TernaryResult(
            image_id=image_id,
            decision=str(decision),
            confidence=confidence,
            short_reason=str(raw.get("short_reason") or "")[:160],
            missing_evidence=missing,
        )
    for image_id in expected:
        if image_id not in judged and image_id not in unknown:
            unknown[image_id] = "omitted"
    by_id = dict(judged)
    for image_id, reason in unknown.items():
        by_id[image_id] = _unknown_ternary(image_id, reason)
    return tuple(by_id[image_id] for image_id in expected)


class EvidenceTextJudgeProvider(OpenAIImageRelevanceProvider):
    """Text-only ternary judge over Semantic Index evidence. No image bytes."""

    def __init__(self, *, evidence_by_image_id: dict[int, dict] | None = None, **kwargs):
        kwargs.setdefault("system_prompt", SYSTEM_PROMPT)
        kwargs.setdefault("prompt_version", PROMPT_VERSION)
        kwargs.setdefault("temperature", 0)
        kwargs.setdefault("max_edge", 512)
        kwargs.setdefault("image_detail", "low")
        kwargs.setdefault("timeout_seconds", 120)
        super().__init__(**kwargs)
        self.evidence_by_image_id = dict(evidence_by_image_id or {})

    def _post_with_retry(self, payload: dict, *, image_diagnostics=()):
        try:
            return super()._post_with_retry(payload, image_diagnostics=image_diagnostics)
        except RelevanceProviderError as exc:
            text = str(exc)
            if "insufficient_quota" in text or "credit_balance_exhausted" in text:
                raise QuotaExhaustedError(text) from exc
            raise

    def judge(
        self,
        query: str,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> TernaryRun:
        if not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        images_by_id = {item.image_id: item for item in images}
        judged: dict[int, TernaryResult] = {}
        unknown: dict[int, str] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        logger = _diagnostics_logger()

        def absorb(batch: _BatchResult) -> None:
            nonlocal request_count
            request_count += 1
            completed.append(batch)
            for item in batch.results:
                if not isinstance(item, TernaryResult):
                    unknown[item.image_id] = "malformed"
                    continue
                if item.unknown_reason:
                    if item.image_id not in judged:
                        unknown[item.image_id] = item.unknown_reason
                else:
                    judged[item.image_id] = item
                    unknown.pop(item.image_id, None)

        batches = [
            tuple(images[index:index + self.batch_size])
            for index in range(0, len(images), self.batch_size)
        ]
        if batches:
            workers = min(self.max_workers, max(1, len(batches)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending = {
                    pool.submit(self._classify_batch, query, batch): batch
                    for batch in batches
                }
                for future in as_completed(pending):
                    batch = pending[future]
                    try:
                        absorb(future.result())
                    except QuotaExhaustedError:
                        raise
                    except Exception as exc:
                        message = self._safe_error(exc)
                        errors.append(message)
                        logger.warning(
                            "Evidence-text batch-failure reason=api_failure image_ids=%s error=%s",
                            [item.image_id for item in batch], message,
                        )
                        absorb(self._unknown_ternary_batch(
                            tuple(item.image_id for item in batch), "api_failure",
                        ))

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
                    absorb(self._classify_batch(query, retry_batch))
                except QuotaExhaustedError:
                    raise
                except Exception as exc:
                    message = self._safe_error(exc)
                    errors.append(message)
                    absorb(self._unknown_ternary_batch(
                        tuple(item.image_id for item in retry_batch), "api_failure",
                    ))

        if unknown:
            for image_id, reason in unknown.items():
                judged.setdefault(image_id, _unknown_ternary(image_id, reason))
            unknown.clear()
        for item in images:
            judged.setdefault(item.image_id, _unknown_ternary(item.image_id, "unknown"))
        ordered = tuple(judged[item.image_id] for item in images)
        failed_ids = tuple(
            item.image_id for item in ordered if item.unknown_reason
        )
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return TernaryRun(
            results=ordered,
            failed_image_ids=failed_ids,
            request_count=request_count,
            sent_image_count=0,
            api_seconds=sum(batch.api_seconds for batch in completed),
            total_seconds=time.perf_counter() - started,
            retry_count=retry_count,
            request_attempt_count=request_attempt_count,
            input_tokens=sum(batch.input_tokens for batch in completed),
            output_tokens=sum(batch.output_tokens for batch in completed),
            errors=tuple(errors),
            model=self.model,
            temperature=self.temperature,
        )

    def _unknown_ternary_batch(
        self,
        ids: Sequence[int],
        reason: str,
        api_seconds: float = 0.0,
    ) -> _BatchResult:
        return _BatchResult(
            results=tuple(_unknown_ternary(image_id, reason) for image_id in ids),
            image_ids=tuple(ids),
            resize_seconds=0.0,
            api_seconds=api_seconds,
            input_tokens=0,
            output_tokens=0,
        )

    def _results_from_response(self, response: dict, expected_ids: Sequence[int]):
        try:
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RelevanceProviderError("Vision API returned an invalid structured result.") from exc
        if not isinstance(parsed, dict):
            raise RelevanceProviderError("Vision API returned an invalid structured result.")
        return validate_ternary_results(parsed, expected_ids)

    def _classify_batch(self, query: str, batch: Sequence[RelevanceImage]) -> _BatchResult:
        ids = tuple(item.image_id for item in batch)
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            content: list[dict] = [{"type": "text", "text": (
                f"Search query: {query!r}\n"
                "For every following image, decide relevant, irrelevant, or "
                "insufficient_evidence from the Semantic Index evidence.\n"
                f"{USER_INSTRUCTIONS}"
            )}]
            for item in batch:
                evidence = self.evidence_by_image_id.get(item.image_id) or {}
                content.append({"type": "text", "text": f"image_id: {item.image_id}"})
                content.append({"type": "text", "text": format_index_evidence(evidence)})
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "evidence_relevance",
                        "strict": True,
                        "schema": evidence_schema(ids),
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
            kept = [item.image_id for item in results if item.unknown_reason is None]
            omitted = [item.image_id for item in results if item.unknown_reason == "omitted"]
            malformed = [item.image_id for item in results if item.unknown_reason == "malformed"]
            if omitted or malformed:
                logger.warning(
                    "Evidence-text batch-partial image_ids=%s kept=%s omitted=%s malformed=%s",
                    list(ids), kept, omitted, malformed,
                )
            return _BatchResult(
                results=results,
                image_ids=ids,
                resize_seconds=0.0,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
        except QuotaExhaustedError:
            raise
        except RelevanceProviderError as exc:
            reason = _provider_error_reason(exc)
            logger.warning(
                "Evidence-text batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return self._unknown_ternary_batch(ids, reason, api_seconds)
        except json.JSONDecodeError:
            logger.warning(
                "Evidence-text batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return self._unknown_ternary_batch(ids, "malformed", api_seconds)
