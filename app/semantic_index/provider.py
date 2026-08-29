"""Query-free Vision Semantic Index provider. Does not run product Meaning Search."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import json
import time

from app.relevance import RelevanceImage, RelevanceProviderError
from app.relevance.openai_provider import (
    OpenAIImageRelevanceProvider,
    _BatchResult,
    _diagnostics_logger,
    _is_cancelled,
    _provider_error_reason,
)
from app.semantic_index.schema import (
    INDEX_PROMPT,
    INDEX_PROMPT_VERSION,
    INDEX_USER_PREFIX,
    index_schema,
    unknown_index_record,
    validate_index_payload,
)


@dataclass(frozen=True)
class IndexRun:
    results: tuple[dict, ...]
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


class SemanticIndexProvider(OpenAIImageRelevanceProvider):
    """Query-free semantic index. Product search still uses vision-meaning-v1."""

    budget_operation = "other"
    budget_kind = "vision"

    def classify(self, query, images, *, cancelled=None):
        raise RuntimeError(
            "SemanticIndexProvider.index() must be used; classify() would send a query."
        )

    def index(
        self,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> IndexRun:
        if not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        images_by_id = {item.image_id: item for item in images}
        judged: dict[int, dict] = {}
        unknown: dict[int, str] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        logger = _diagnostics_logger()

        def absorb(batch: _BatchResult, parsed: tuple[dict, ...]) -> None:
            nonlocal request_count
            request_count += 1
            completed.append(batch)
            for item in parsed:
                image_id = int(item["image_id"])
                if item.get("unknown_reason"):
                    if image_id not in judged:
                        unknown[image_id] = item["unknown_reason"]
                else:
                    judged[image_id] = item
                    unknown.pop(image_id, None)
            unknown_ids = tuple(
                int(item["image_id"]) for item in parsed if item.get("unknown_reason")
            )
            if unknown_ids:
                reasons = sorted({
                    str(item.get("unknown_reason") or "unknown")
                    for item in parsed
                    if item.get("unknown_reason")
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
                    pool.submit(self._index_batch, batch): batch
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
                            "semantic-index batch-failure reason=api_failure image_ids=%s error=%s",
                            [item.image_id for item in batch], message,
                        )
                        raw_batch = self._unknown_batch(
                            tuple(item.image_id for item in batch), "api_failure",
                        )
                        absorb(
                            raw_batch,
                            tuple(
                                unknown_index_record(item.image_id, "api_failure")
                                for item in batch
                            ),
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
                    raw_batch, parsed = self._index_batch(retry_batch)
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
                            unknown_index_record(item.image_id, "api_failure")
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
                judged.setdefault(image_id, unknown_index_record(image_id, reason or prior))
            unknown.clear()

        for item in images:
            judged.setdefault(item.image_id, unknown_index_record(item.image_id, "unknown"))
        ordered = tuple(judged[item.image_id] for item in images)
        failed_ids = tuple(
            int(item["image_id"]) for item in ordered if item.get("unknown_reason")
        )
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return IndexRun(
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

    def _index_batch(
        self, batch: Sequence[RelevanceImage]
    ) -> tuple[_BatchResult, tuple[dict, ...]]:
        ids = tuple(item.image_id for item in batch)
        resize_started = time.perf_counter()
        resize_seconds = 0.0
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            encoded = list(zip(batch, self._prepare_images([item.path for item in batch])))
            resize_seconds = time.perf_counter() - resize_started
            content: list[dict] = [{"type": "text", "text": INDEX_USER_PREFIX}]
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
                        "name": "image_semantic_index",
                        "strict": True,
                        "schema": index_schema(ids),
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
            parsed = validate_index_payload(parsed_payload, ids)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            omitted = [item["image_id"] for item in parsed if item.get("unknown_reason") == "omitted"]
            malformed = [item["image_id"] for item in parsed if item.get("unknown_reason") == "malformed"]
            if omitted:
                logger.warning(
                    "semantic-index batch-omitted image_ids=%s omitted_ids=%s",
                    list(ids), omitted,
                )
            if malformed:
                logger.warning(
                    "semantic-index batch-malformed image_ids=%s malformed_ids=%s",
                    list(ids), malformed,
                )
            batch_result = _BatchResult(
                results=(),
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
                "semantic-index batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return (
                self._unknown_batch(ids, reason, resize_seconds, api_seconds),
                tuple(unknown_index_record(image_id, reason) for image_id in ids),
            )
        except json.JSONDecodeError:
            logger.warning(
                "semantic-index batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return (
                self._unknown_batch(ids, "malformed", resize_seconds, api_seconds),
                tuple(unknown_index_record(image_id, "malformed") for image_id in ids),
            )


def make_index_provider() -> SemanticIndexProvider:
    return SemanticIndexProvider(
        max_edge=512,
        image_detail="low",
        temperature=0,
        batch_size=8,
        system_prompt=INDEX_PROMPT,
        prompt_version=INDEX_PROMPT_VERSION,
        include_relevance_score=False,
    )
