from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import random
import threading
import time
from collections.abc import Callable, Sequence
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from app.ai_budget import (
    KIND_VISION,
    OPERATION_OTHER,
    AiRequestIntent,
    check_ai_budget,
    finalize_ai_usage,
    release_ai_reservation,
)
from app.paths import get_local_app_data_dir
from app.utils.logger import setup_logger

from .models import RelevanceImage, RelevanceResult, RelevanceRun
from .provider import RelevanceProviderError

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_UNKNOWN_RETRIES = 2
DEFAULT_RETRY_BATCH_SIZE = 1
PROMPT_VERSION = "vision-meaning-v1"
SCHEMA_VERSION = "image-relevance-v2"
SEMANTIC_SEARCH_LOG = get_local_app_data_dir() / "semantic-search.log"

SYSTEM_PROMPT = """You are a generic image-search result judge.

A user searched their own image library with the given query.
For every supplied image, decide whether that image matches the query.

Judge confirmability of what the query specified, not typicality,
centrality, or whether the image is mainly about the query.
Ask: can a human reasonably confirm, in the visible image, the content,
attributes, states, and relations named by the query?

Interpret the query as meaning, not as a bag of words.
A noun phrase, proper name, or compound concept is one condition, even
when it contains several words. Do not split those phrases into separate
word-by-word AND requirements.
Independent conditions are only the extra constraints the user actually
added: attributes, states, additional targets, an environment, or a
relation. A single named concept is one condition.

relevant is true only when every condition specified by the query is
reasonably identifiable in the image.
relevant is false when any specified condition cannot be reasonably
confirmed.
Those conditions are the query's independent meaning units, not its
individual words.

If the query names only a target or concept, that target or concept
being reasonably identifiable is enough. It does not have to be the
primary subject, the largest object, the foreground, or the most
important thing shown. A match may be in the background, behind another
window, nested inside another app, shown as a thumbnail or preview, or
sharing the frame with unrelated content.

If the query adds attributes, states, multiple targets, an environment,
or a relation, every added independent condition must also be true in
the same image. Satisfying only some of the specified independent
conditions is false.

Do not invent extra requirements the query did not state, such as
importance, uniqueness, typical appearance, or that other content must
not share the frame.
Do not treat a mark that only suggests the target, without the target
itself being identifiable, as confirmation. If a human cannot reasonably
identify the specified content, relevant is false.

Use the same confirmability standard for every query. Do not classify
the query into types, and do not apply special-case rules for particular
words.

relevance_score is a number from 0 to 1 for how completely and clearly
the specified conditions are confirmed. Higher means clearer confirmation
of all specified conditions, not greater centrality.
confidence is how sure you are of this judgement. confidence is not
relevance_score.

Judge the visible image itself. Do not use similarity scores, filenames,
ranking, or assumed metadata.
Return exactly one result for every supplied image_id."""


def _diagnostics_logger() -> logging.Logger:
    logger = setup_logger()
    resolved = SEMANTIC_SEARCH_LOG.resolve()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == resolved:
            return logger
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    return logger


def relevance_schema(
    image_ids: Sequence[int], *, include_relevance_score: bool = True
) -> dict:
    properties = {
        "image_id": {"type": "integer", "enum": list(image_ids)},
        "relevant": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 160},
    }
    required = ["image_id", "relevant", "confidence", "reason"]
    if include_relevance_score:
        properties["relevance_score"] = {"type": "number", "minimum": 0, "maximum": 1}
        required = ["image_id", "relevant", "confidence", "relevance_score", "reason"]
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


@dataclass(frozen=True)
class _BatchResult:
    results: tuple[RelevanceResult, ...]
    image_ids: tuple[int, ...]
    resize_seconds: float
    api_seconds: float
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class _EncodedImage:
    data_url: str
    sha256: str
    width: int
    height: int


class OpenAIImageRelevanceProvider:
    """OpenAI Vision prototype with strict JSON Schema output and partial recovery."""

    budget_operation = OPERATION_OTHER
    budget_kind = KIND_VISION

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        batch_size: int = 20,
        max_workers: int = 2,
        max_edge: int = 512,
        image_detail: str = "low",
        temperature: float | None = DEFAULT_TEMPERATURE,
        timeout_seconds: float = 90,
        retries: int = 2,
        unknown_retries: int = DEFAULT_UNKNOWN_RETRIES,
        retry_batch_size: int = DEFAULT_RETRY_BATCH_SIZE,
        system_prompt: str | None = None,
        prompt_version: str | None = None,
        include_relevance_score: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("CAPIXE_VISION_MODEL", DEFAULT_MODEL)
        self.endpoint = endpoint
        self.batch_size = max(1, min(int(batch_size), 20))
        self.max_workers = max(1, min(int(max_workers), 4))
        self.max_edge = max(64, int(max_edge))
        self.image_detail = image_detail
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, int(retries))
        self.unknown_retries = max(0, int(unknown_retries))
        self.retry_batch_size = max(1, min(int(retry_batch_size), 4))
        self.system_prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt
        self.prompt_version = prompt_version or PROMPT_VERSION
        self.include_relevance_score = bool(include_relevance_score)
        self._request_stats_lock = threading.Lock()
        self._request_attempt_count = 0
        self._retry_count = 0

    def _requires_local_api_key(self) -> bool:
        from app.ai_proxy.config import use_direct_ai_provider

        return use_direct_ai_provider() or self._transport_via_legacy_post()

    def _transport_via_legacy_post(self) -> bool:
        from app.ai_proxy.config import use_direct_ai_provider

        if use_direct_ai_provider():
            return True
        return "_post_with_retry" in type(self).__dict__

    def classify(
        self,
        query: str,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RelevanceRun:
        if not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        images_by_id = {item.image_id: item for item in images}
        judged: dict[int, RelevanceResult] = {}
        unknown: dict[int, str] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        first_relevant_seconds = None
        first_result_seconds = None
        logger = _diagnostics_logger()

        def note_timing(batch: _BatchResult) -> None:
            nonlocal first_result_seconds, first_relevant_seconds
            if first_result_seconds is None:
                first_result_seconds = time.perf_counter() - started
            if first_relevant_seconds is None and any(
                item.relevant is True for item in batch.results
            ):
                first_relevant_seconds = time.perf_counter() - started

        def absorb(batch: _BatchResult) -> None:
            nonlocal request_count
            request_count += 1
            completed.append(batch)
            note_timing(batch)
            for item in batch.results:
                if item.relevant is None:
                    if item.image_id not in judged:
                        unknown[item.image_id] = item.unknown_reason or "unknown"
                else:
                    judged[item.image_id] = item
                    unknown.pop(item.image_id, None)
            unknown_ids = tuple(
                item.image_id for item in batch.results if item.relevant is None
            )
            if unknown_ids:
                reasons = sorted({
                    item.unknown_reason or "unknown"
                    for item in batch.results
                    if item.relevant is None
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
                    pool.submit(self._classify_batch, query, batch): batch
                    for batch in batches
                }
                for future in as_completed(pending):
                    batch = pending[future]
                    try:
                        absorb(future.result())
                    except Exception as exc:
                        message = self._safe_error(exc)
                        errors.append(message)
                        logger.warning(
                            "Vision-relevance batch-failure reason=api_failure image_ids=%s error=%s",
                            [item.image_id for item in batch], message,
                        )
                        absorb(self._unknown_batch(
                            tuple(item.image_id for item in batch), "api_failure",
                        ))

        retry_round = 0
        while unknown and retry_round < self.unknown_retries:
            if _is_cancelled(cancelled):
                logger.info(
                    "Vision-relevance retry skipped image_ids=%s reason=cancelled",
                    list(unknown),
                )
                break
            retry_round += 1
            remaining = tuple(
                images_by_id[image_id]
                for image_id in images_by_id
                if image_id in unknown
            )
            logger.info(
                "Vision-relevance retry image_ids=%s attempt=%d remaining=%d",
                [item.image_id for item in remaining], retry_round, len(remaining),
            )
            retry_batches = [
                remaining[index:index + self.retry_batch_size]
                for index in range(0, len(remaining), self.retry_batch_size)
            ]
            for retry_batch in retry_batches:
                if _is_cancelled(cancelled):
                    logger.info(
                        "Vision-relevance retry stopped image_ids=%s reason=cancelled",
                        [item.image_id for item in retry_batch],
                    )
                    break
                with self._request_stats_lock:
                    self._retry_count += 1
                try:
                    absorb(self._classify_batch(query, retry_batch))
                except Exception as exc:
                    message = self._safe_error(exc)
                    errors.append(message)
                    logger.warning(
                        "Vision-relevance batch-failure reason=api_failure image_ids=%s error=%s",
                        [item.image_id for item in retry_batch], message,
                    )
                    absorb(self._unknown_batch(
                        tuple(item.image_id for item in retry_batch), "api_failure",
                    ))

        if unknown:
            exhausted = (
                not _is_cancelled(cancelled)
                and retry_round >= self.unknown_retries > 0
            )
            if exhausted:
                logger.warning(
                    "Vision-relevance retry-exhausted image_ids=%s prior_reasons=%s",
                    list(unknown), dict(unknown),
                )
                for image_id in unknown:
                    judged[image_id] = _unknown_result(image_id, "retry_exhausted")
            else:
                for image_id, reason in unknown.items():
                    judged.setdefault(image_id, _unknown_result(image_id, reason))
                    logger.info(
                        "Vision-relevance unknown image_id=%s reason=%s",
                        image_id, reason,
                    )
            unknown.clear()

        for item in images:
            judged.setdefault(item.image_id, _unknown_result(item.image_id, "unknown"))
        ordered = tuple(judged[item.image_id] for item in images)
        failed_ids = tuple(
            item.image_id for item in ordered if item.relevant is None
        )
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return RelevanceRun(
            results=ordered,
            failed_image_ids=failed_ids,
            request_count=request_count,
            sent_image_count=len(images),
            resize_seconds=sum(batch.resize_seconds for batch in completed),
            api_seconds=sum(batch.api_seconds for batch in completed),
            first_relevant_seconds=first_relevant_seconds,
            first_result_seconds=first_result_seconds,
            total_seconds=time.perf_counter() - started,
            retry_count=retry_count,
            request_attempt_count=request_attempt_count,
            input_tokens=sum(batch.input_tokens for batch in completed),
            output_tokens=sum(batch.output_tokens for batch in completed),
            errors=tuple(errors),
        )

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
                "For every following image, decide whether every independent "
                "condition specified by this query can be reasonably confirmed "
                "in the visible image. Treat noun phrases, proper names, and "
                "compound concepts as single conditions, not as separate words "
                "to AND."
            )}]
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

    def _post_with_retry(self, payload: dict, *, image_diagnostics: Sequence[dict] = ()) -> dict:
        operation = str(getattr(self, "budget_operation", OPERATION_OTHER) or OPERATION_OTHER)
        kind = str(getattr(self, "budget_kind", KIND_VISION) or KIND_VISION)
        model = str(payload.get("model") or self.model or "")
        check_ai_budget(
            AiRequestIntent(
                operation=operation,
                kind=kind,
                model=model,
                request_count=1,
            )
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        logger = _diagnostics_logger()
        client_request_id = uuid.uuid4().hex
        try:
            return self._post_reserved(payload, body, logger, client_request_id, image_diagnostics, model, kind)
        except Exception:
            release_ai_reservation()
            raise

    def _post_reserved(
        self,
        payload: dict,
        body: bytes,
        logger,
        client_request_id: str,
        image_diagnostics: Sequence[dict],
        model: str,
        kind: str,
    ) -> dict:
        for attempt in range(self.retries + 1):
            with self._request_stats_lock:
                self._request_attempt_count += 1
                if attempt:
                    self._retry_count += 1
            request = Request(
                self.endpoint,
                data=body,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            logger.info(
                "Vision-relevance request-sent client_request_id=%s request_model=%s "
                "temperature=%s image_detail=%s image_ids=%s jpeg_images=%s "
                "prompt_version=%s schema_version=%s attempt=%d",
                client_request_id, payload.get("model"), payload.get("temperature", "omitted"),
                self.image_detail, [item.get("image_id") for item in image_diagnostics],
                list(image_diagnostics), self.prompt_version, SCHEMA_VERSION, attempt + 1,
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                    headers = response.headers
                    request_id = (
                        headers.get("x-request-id")
                        or headers.get("request-id")
                        or headers.get("openai-request-id")
                    )
                    usage = response_payload.get("usage") or {}
                    finalize_ai_usage(usage=usage if isinstance(usage, dict) else {}, model=model, kind=kind)
                    logger.info(
                        "Vision-relevance response client_request_id=%s request_model=%s "
                        "response_model=%s temperature=%s "
                        "image_detail=%s image_ids=%s jpeg_images=%s prompt_version=%s "
                        "schema_version=%s system_fingerprint=%s request_id=%s attempt=%d "
                        "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                        client_request_id, payload.get("model"), response_payload.get("model"),
                        payload.get("temperature", "omitted"), self.image_detail,
                        [item.get("image_id") for item in image_diagnostics],
                        list(image_diagnostics), self.prompt_version, SCHEMA_VERSION,
                        response_payload.get("system_fingerprint"), request_id, attempt + 1,
                        usage.get("prompt_tokens"), usage.get("completion_tokens"),
                        usage.get("total_tokens"),
                    )
                    return response_payload
            except HTTPError as exc:
                request_id = (
                    exc.headers.get("x-request-id")
                    or exc.headers.get("request-id")
                    or exc.headers.get("openai-request-id")
                ) if exc.headers is not None else None
                logger.warning(
                    "Vision-relevance response-error client_request_id=%s request_model=%s "
                    "temperature=%s image_detail=%s image_ids=%s request_id=%s "
                    "http_status=%s attempt=%d",
                    client_request_id, payload.get("model"),
                    payload.get("temperature", "omitted"), self.image_detail,
                    [item.get("image_id") for item in image_diagnostics], request_id,
                    exc.code, attempt + 1,
                )
                retryable = exc.code in {408, 409, 429} or exc.code >= 500
                if not retryable or attempt >= self.retries:
                    detail = exc.read(500).decode("utf-8", errors="replace")
                    raise RelevanceProviderError(f"Vision API HTTP {exc.code}: {detail}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt >= self.retries:
                    raise RelevanceProviderError("Vision API request timed out or could not connect.") from exc
            time.sleep((2 ** attempt) + random.random() * 0.25)
        raise AssertionError("unreachable")

    def _prepare_images(self, paths: Sequence[Path]) -> list[_EncodedImage]:
        if len(paths) <= 1:
            return [self._prepare_image(path) for path in paths]
        workers = min(4, len(paths))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._prepare_image, paths))

    def _prepare_image(self, path: Path) -> _EncodedImage:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((self.max_edge, self.max_edge), Image.Resampling.LANCZOS)
            width, height = image.size
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
        jpeg = output.getvalue()
        encoded = base64.b64encode(jpeg).decode("ascii")
        return _EncodedImage(
            data_url=f"data:image/jpeg;base64,{encoded}",
            sha256=hashlib.sha256(jpeg).hexdigest(),
            width=width,
            height=height,
        )

    def _encode_image(self, path: Path) -> str:
        return self._prepare_image(path).data_url

    def _results_from_response(
        self, response: dict, expected_ids: Sequence[int]
    ) -> tuple[RelevanceResult, ...]:
        try:
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RelevanceProviderError("Vision API returned an invalid structured result.") from exc
        if not isinstance(parsed, dict):
            raise RelevanceProviderError("Vision API returned an invalid structured result.")
        return self._validate_results(
            parsed,
            expected_ids,
            require_relevance_score=self.include_relevance_score,
        )

    def _log_partial_batch(
        self,
        logger: logging.Logger,
        expected_ids: Sequence[int],
        results: Sequence[RelevanceResult],
    ) -> None:
        kept = [item.image_id for item in results if item.relevant is not None]
        omitted = [item.image_id for item in results if item.unknown_reason == "omitted"]
        malformed = [item.image_id for item in results if item.unknown_reason == "malformed"]
        if omitted:
            logger.warning(
                "Vision-relevance batch-omitted image_ids=%s kept_ids=%s omitted_ids=%s",
                list(expected_ids), kept, omitted,
            )
        if malformed:
            logger.warning(
                "Vision-relevance batch-malformed image_ids=%s kept_ids=%s malformed_ids=%s",
                list(expected_ids), kept, malformed,
            )
        for item in results:
            if item.relevant is None:
                logger.info(
                    "Vision-relevance unknown image_id=%s reason=%s",
                    item.image_id, item.unknown_reason or "unknown",
                )

    def _unknown_batch(
        self,
        ids: Sequence[int],
        reason: str,
        resize_seconds: float = 0.0,
        api_seconds: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> _BatchResult:
        return _BatchResult(
            results=tuple(_unknown_result(image_id, reason) for image_id in ids),
            image_ids=tuple(ids),
            resize_seconds=resize_seconds,
            api_seconds=api_seconds,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _validate_results(
        payload: dict,
        expected_ids: Sequence[int],
        *,
        require_relevance_score: bool = True,
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
            relevant_value = raw.get("relevant")
            if not isinstance(relevant_value, bool):
                unknown[image_id] = "malformed"
                continue
            try:
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            relevance_score = None
            if require_relevance_score:
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
                relevant=relevant_value,
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

    def _safe_error(self, exc: Exception) -> str:
        message = str(exc)
        if self.api_key:
            message = message.replace(self.api_key, "[redacted]")
        return message[:500]


def _unknown_result(image_id: int, reason: str) -> RelevanceResult:
    return RelevanceResult(
        image_id=image_id,
        relevant=None,
        confidence=0.0,
        reason="",
        unknown_reason=reason,
        relevance_score=None,
    )


def _is_cancelled(cancelled: Callable[[], bool] | None) -> bool:
    return callable(cancelled) and bool(cancelled())


def _provider_error_reason(exc: RelevanceProviderError) -> str:
    message = str(exc).lower()
    if "timed out" in message or "could not connect" in message:
        return "timeout"
    if "invalid structured" in message:
        return "malformed"
    return "api_failure"
