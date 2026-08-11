"""Typed public models for Capixe's unified image search API."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnifiedSearchResult:
    image_id: int
    path: str
    filename: str
    mtime_ns: int
    matched_filename: bool
    matched_tags: bool
    matched_ocr: bool
    matched_fields: tuple[str, ...]
    score: int
    filename_match_type: str
    tag_match_type: str
    ocr_match_type: str
    ocr_snippet: str | None
    ocr_status: str


@dataclass(frozen=True)
class SearchPage:
    query: str
    normalized_query: str
    total_count: int
    returned_count: int
    limit: int
    offset: int
    results: tuple[UnifiedSearchResult, ...]
    elapsed_ms: float
    query_mode: str
