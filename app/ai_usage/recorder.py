"""Record product AI usage without storing query text or image content."""

from __future__ import annotations

from collections.abc import Mapping

from app.ai_usage.models import (
    KIND_SEARCH_TEXT,
    KIND_VISION,
    OPERATION_FACTS_GENERATE,
    OPERATION_MEANING_SEARCH,
    REASON_FACTS_VERSION,
    REASON_FIRST,
    REASON_REPARSE,
    AiUsageEvent,
)
from app.ai_usage.repository import AiUsageRepository
from app.utils.logger import setup_logger

logger = setup_logger()

_recorder: "AiUsageRecorder | None" = None


class AiUsageRecorder:
    def __init__(self, repository: AiUsageRepository | None = None):
        self.repository = repository or AiUsageRepository()

    def record_vision(
        self,
        *,
        model: str = "",
        request_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasons: Mapping[str, int] | None = None,
    ) -> AiUsageEvent | None:
        counts = dict(reasons or {})
        first = int(counts.get(REASON_FIRST, 0))
        reparse = int(counts.get(REASON_REPARSE, 0))
        version = int(counts.get(REASON_FACTS_VERSION, 0))
        image_count = first + reparse + version
        if request_count <= 0 and image_count <= 0:
            return None
        return self._record(
            kind=KIND_VISION,
            operation=OPERATION_FACTS_GENERATE,
            model=model,
            request_count=request_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_count=image_count,
            first_image_count=first,
            reparse_count=reparse,
            facts_version_regen_count=version,
        )

    def record_search(
        self,
        *,
        model: str = "",
        request_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        candidate_count: int = 0,
        batch_count: int = 0,
        matcher_image_count: int = 0,
        query_count: int = 1,
    ) -> AiUsageEvent | None:
        return self._record(
            kind=KIND_SEARCH_TEXT,
            operation=OPERATION_MEANING_SEARCH,
            model=model,
            request_count=request_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            query_count=query_count,
            candidate_count=candidate_count,
            batch_count=batch_count,
            matcher_image_count=matcher_image_count,
        )

    def _record(self, **payload) -> AiUsageEvent | None:
        try:
            return self.repository.record(**payload)
        except Exception:
            logger.warning("ai-usage record-failure", exc_info=False)
            return None


def get_usage_recorder() -> AiUsageRecorder:
    global _recorder
    if _recorder is None:
        _recorder = AiUsageRecorder()
    return _recorder


def set_usage_recorder(recorder: AiUsageRecorder | None) -> None:
    global _recorder
    _recorder = recorder


def reset_usage_recorder_for_tests() -> None:
    set_usage_recorder(None)
