"""Local API-usage records. No query text, paths, or image content."""

from __future__ import annotations

from dataclasses import dataclass


KIND_VISION = "vision"
KIND_SEARCH_TEXT = "search_text"
OPERATION_FACTS_GENERATE = "facts_generate"
OPERATION_MEANING_SEARCH = "meaning_search"

REASON_FIRST = "first"
REASON_REPARSE = "reparse"
REASON_FACTS_VERSION = "facts_version"


@dataclass(frozen=True)
class AiUsageEvent:
    event_id: int
    occurred_at: str
    kind: str
    operation: str
    model: str = ""
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    image_count: int = 0
    first_image_count: int = 0
    reparse_count: int = 0
    facts_version_regen_count: int = 0
    query_count: int = 0
    candidate_count: int = 0
    batch_count: int = 0
    matcher_image_count: int = 0


@dataclass(frozen=True)
class AiUsageTotals:
    vision_facts_image_count: int = 0
    vision_request_count: int = 0
    vision_reparse_count: int = 0
    vision_facts_version_regen_count: int = 0
    search_query_count: int = 0
    search_candidate_count: int = 0
    search_text_llm_request_count: int = 0
    search_batch_count: int = 0
    search_matcher_image_count: int = 0
