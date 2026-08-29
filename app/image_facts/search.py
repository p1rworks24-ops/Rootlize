"""Text-only matching of stored image facts against a user query."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
import time

from app.ai_budget import (
    KIND_TEXT_LLM,
    OPERATION_MEANING_SEARCH,
    AiBudgetExceeded,
    AiRequestIntent,
    check_ai_budget,
)
from app.ai_proxy import invoke_ai_proxy
from app.ai_proxy.errors import AiProxyError
from app.image_facts.contracts import apply_facts_contracts
from app.image_facts.format import format_fact_record, prepare_facts_record
from app.image_facts.schema import (
    FACTS_FIRST_CHUNK_SIZE,
    FACTS_SEARCH_BATCH_SIZE,
    SEARCH_PROMPT,
    SEARCH_PROMPT_VERSION,
    SEARCH_SCHEMA_VERSION,
    SEARCH_USER_PREFIX,
    search_schema,
)
from app.relevance import RelevanceResult, RelevanceRun
from app.relevance.openai_provider import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    OpenAIImageRelevanceProvider,
    _BatchResult,
    _diagnostics_logger,
    _is_cancelled,
)
from app.relevance.provider import RelevanceProviderError


class ImageFactsSearchMatcher(OpenAIImageRelevanceProvider):
    """Match an OpenCLIP shortlist against stored facts. Sends no images."""

    budget_operation = OPERATION_MEANING_SEARCH
    budget_kind = KIND_TEXT_LLM

    def __init__(self, **kwargs):
        kwargs.setdefault("system_prompt", SEARCH_PROMPT)
        kwargs.setdefault("prompt_version", SEARCH_PROMPT_VERSION)
        kwargs.setdefault("batch_size", max(FACTS_SEARCH_BATCH_SIZE, FACTS_FIRST_CHUNK_SIZE))
        kwargs.setdefault("max_workers", 1)
        kwargs.setdefault("unknown_retries", 0)
        kwargs.setdefault("include_relevance_score", False)
        kwargs.setdefault("temperature", 0)
        super().__init__(**kwargs)

    def classify(self, query, images, *, cancelled=None):
        raise RuntimeError(
            "ImageFactsSearchMatcher.match_records() must be used; classify() would send images."
        )

    def match_records(
        self,
        query: str,
        records: Sequence[dict],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RelevanceRun:
        if self._requires_local_api_key() and not self.api_key:
            raise RelevanceProviderError(
                "Vision relevance requires OPENAI_API_KEY. The key is read from the environment and is never logged."
            )
        started = time.perf_counter()
        with self._request_stats_lock:
            self._request_attempt_count = 0
            self._retry_count = 0
        prepared = [
            {**prepare_facts_record(dict(item)), "image_id": int(item["image_id"])}
            for item in records
        ]
        by_id = {int(item["image_id"]): item for item in prepared}
        judged: dict[int, RelevanceResult] = {}
        completed: list[_BatchResult] = []
        errors: list[str] = []
        request_count = 0
        first_relevant_seconds = None
        first_result_seconds = None
        logger = _diagnostics_logger()
        chunks = [
            prepared[index:index + self.batch_size]
            for index in range(0, len(prepared), self.batch_size)
        ]
        for chunk in chunks:
            if _is_cancelled(cancelled):
                break
            try:
                batch, parsed = self._match_batch(query, chunk)
                request_count += 1
                completed.append(batch)
                if first_result_seconds is None:
                    first_result_seconds = time.perf_counter() - started
                for item in parsed:
                    image_id = int(item["image_id"])
                    decided = apply_facts_contracts(item, query=query, record=by_id[image_id])
                    relevant = bool(decided.get("relevant"))
                    judged[image_id] = RelevanceResult(
                        image_id=image_id,
                        relevant=relevant,
                        confidence=1.0 if relevant else 0.0,
                        reason=str(decided.get("reason") or ""),
                        relevance_score=1.0 if relevant else 0.0,
                    )
                    if relevant and first_relevant_seconds is None:
                        first_relevant_seconds = time.perf_counter() - started
            except (AiBudgetExceeded, AiProxyError):
                raise
            except Exception as exc:
                message = self._safe_error(exc)
                errors.append(message)
                logger.warning(
                    "image-facts-search batch-failure image_ids=%s error=%s",
                    [item["image_id"] for item in chunk], message,
                )
                for item in chunk:
                    judged.setdefault(
                        int(item["image_id"]),
                        RelevanceResult(
                            image_id=int(item["image_id"]),
                            relevant=None,
                            confidence=0.0,
                            reason="",
                            unknown_reason="api_failure",
                        ),
                    )
        ordered = tuple(
            judged.get(
                int(item["image_id"]),
                RelevanceResult(
                    image_id=int(item["image_id"]),
                    relevant=None,
                    confidence=0.0,
                    unknown_reason="omitted",
                ),
            )
            for item in prepared
        )
        failed_ids = tuple(item.image_id for item in ordered if item.relevant is None)
        with self._request_stats_lock:
            request_attempt_count = self._request_attempt_count
            retry_count = self._retry_count
        return RelevanceRun(
            results=ordered,
            failed_image_ids=failed_ids,
            request_count=request_count,
            sent_image_count=0,
            resize_seconds=0.0,
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

    def _match_batch(self, query: str, records: Sequence[dict]) -> tuple[_BatchResult, tuple[dict, ...]]:
        image_ids = [int(item["image_id"]) for item in records]
        docs = "\n\n".join(format_fact_record(item) for item in records)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": f"Query: {query}\n\n{SEARCH_USER_PREFIX}\n\n{docs}",
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "db_sot_relevance",
                    "strict": True,
                    "schema": search_schema(image_ids),
                },
            },
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        api_started = time.perf_counter()
        if self._transport_via_legacy_post():
            response = self._post_with_retry(
                payload,
                image_diagnostics=tuple({"image_id": image_id, "facts": True} for image_id in image_ids),
            )
            api_seconds = time.perf_counter() - api_started
            try:
                raw_content = response["choices"][0]["message"]["content"]
                parsed_payload = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RelevanceProviderError("Facts search returned an invalid structured result.") from exc
        else:
            check_ai_budget(
                AiRequestIntent(
                    operation=self.budget_operation,
                    kind=self.budget_kind,
                    model="",
                    request_count=1,
                )
            )
            envelope = invoke_ai_proxy(
                OPERATION_MEANING_SEARCH,
                {
                    "query": query,
                    "items": [
                        {"image_id": int(item["image_id"]), "document": format_fact_record(item)}
                        for item in records
                    ],
                },
            )
            api_seconds = time.perf_counter() - api_started
            parsed_payload = envelope.result if isinstance(envelope.result, dict) else {}
            response = {"usage": {}}
        results = parsed_payload.get("results") if isinstance(parsed_payload, dict) else None
        if not isinstance(results, list):
            raise RelevanceProviderError("Facts search returned an invalid structured result.")
        by_id = {
            int(item["image_id"]): item
            for item in results
            if isinstance(item, dict) and "image_id" in item
        }
        parsed = tuple(by_id[image_id] for image_id in image_ids if image_id in by_id)
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        return (
            _BatchResult(
                results=(),
                image_ids=tuple(image_ids),
                resize_seconds=0.0,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            ),
            parsed,
        )


def make_facts_search_matcher() -> ImageFactsSearchMatcher:
    return ImageFactsSearchMatcher(
        endpoint=DEFAULT_ENDPOINT,
        model=DEFAULT_MODEL,
    )
