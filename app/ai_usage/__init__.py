"""Local measurement of product AI API consumption."""

from .models import (
    KIND_SEARCH_TEXT,
    KIND_VISION,
    OPERATION_FACTS_GENERATE,
    OPERATION_MEANING_SEARCH,
    REASON_FACTS_VERSION,
    REASON_FIRST,
    REASON_REPARSE,
    AiUsageEvent,
    AiUsageTotals,
)
from .recorder import (
    AiUsageRecorder,
    get_usage_recorder,
    reset_usage_recorder_for_tests,
    set_usage_recorder,
)
from .repository import AiUsageRepository, USAGE_FILE_NAME

__all__ = [
    "KIND_SEARCH_TEXT",
    "KIND_VISION",
    "OPERATION_FACTS_GENERATE",
    "OPERATION_MEANING_SEARCH",
    "REASON_FACTS_VERSION",
    "REASON_FIRST",
    "REASON_REPARSE",
    "AiUsageEvent",
    "AiUsageRecorder",
    "AiUsageRepository",
    "AiUsageTotals",
    "USAGE_FILE_NAME",
    "get_usage_recorder",
    "reset_usage_recorder_for_tests",
    "set_usage_recorder",
]
