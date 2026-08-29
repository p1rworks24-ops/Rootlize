from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.relevance.openai_provider import DEFAULT_MODEL
from app.semantic.models import SourceSnapshot
from app.image_facts.schema import FACTS_SCHEMA_VERSION, FACTS_VERSION


class ImageFactsState(str, Enum):
    DELETED = "deleted"
    PENDING = "pending"
    FAILED = "failed"
    CORRUPT = "corrupt"
    STALE = "stale"
    FRESH = "fresh"

    @property
    def needs_generation(self) -> bool:
        return self in {
            ImageFactsState.PENDING,
            ImageFactsState.FAILED,
            ImageFactsState.CORRUPT,
            ImageFactsState.STALE,
        }


@dataclass(frozen=True)
class ImageFactsIdentity:
    vision_model: str
    prompt_version: str = FACTS_VERSION
    schema_version: str = FACTS_SCHEMA_VERSION
    facts_version: str = FACTS_VERSION


def default_facts_identity(*, vision_model: str | None = None) -> ImageFactsIdentity:
    return ImageFactsIdentity(vision_model=vision_model or DEFAULT_MODEL)


@dataclass(frozen=True)
class ImageFactsMetadata:
    image_id: int
    facts: dict
    vision_model: str
    prompt_version: str
    schema_version: str
    facts_version: str
    source_size_bytes: int
    source_mtime_ns: int
    source_quick_fingerprint: str | None
    created_at: str
    updated_at: str

    @property
    def identity(self) -> ImageFactsIdentity:
        return ImageFactsIdentity(
            self.vision_model,
            self.prompt_version,
            self.schema_version,
            self.facts_version,
        )

    @property
    def source_snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(
            self.source_size_bytes,
            self.source_mtime_ns,
            self.source_quick_fingerprint,
        )


@dataclass(frozen=True)
class ImageFactsFailureRecord:
    image_id: int
    error_code: str
    retryable: bool
    attempt_count: int
    last_attempt_at: str


@dataclass(frozen=True)
class ImageFactsJobResult:
    processed: int
    succeeded: int
    failed: int
    skipped: int
    failed_image_ids: tuple[int, ...] = ()
    request_count: int = 0
