"""Public result models for hybrid text and semantic search."""
from __future__ import annotations

from dataclasses import dataclass

from app.ocr.search_models import UnifiedSearchResult


@dataclass(frozen=True)
class HybridSearchResult:
    image_id: int
    path: str
    filename: str
    score: float
    text_rank: int | None
    semantic_rank: int | None
    text_result: UnifiedSearchResult | None
    semantic_similarity: float | None


@dataclass(frozen=True)
class HybridSearchPage:
    query: str
    top_k: int
    total_count: int
    returned_count: int
    results: tuple[HybridSearchResult, ...]
    semantic_failed: bool = False
