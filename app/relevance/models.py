from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RelevanceImage:
    image_id: int
    path: Path


@dataclass(frozen=True)
class RelevanceResult:
    image_id: int
    relevant: bool | None
    confidence: float
    reason: str = ""
    unknown_reason: str | None = None
    relevance_score: float | None = None


@dataclass(frozen=True)
class RelevanceRun:
    results: tuple[RelevanceResult, ...]
    failed_image_ids: tuple[int, ...] = ()
    request_count: int = 0
    sent_image_count: int = 0
    resize_seconds: float = 0.0
    api_seconds: float = 0.0
    first_relevant_seconds: float | None = None
    first_result_seconds: float | None = None
    total_seconds: float = 0.0
    retry_count: int = 0
    request_attempt_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
