from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.relevance.openai_provider import DEFAULT_MODEL
from app.semantic.catalog import MODEL_IDS, OPENCLIP_MODEL_KEY
from app.semantic.embedding import EMBEDDING_FORMAT_VERSION
from app.semantic.models import SourceSnapshot
from app.semantic_index.schema import INDEX_PROMPT_VERSION, INDEX_SCHEMA_VERSION

INDEX_EMBEDDING_DIMENSION = 512


class SemanticIndexState(str, Enum):
    DELETED = "deleted"
    PENDING = "pending"
    FAILED = "failed"
    CORRUPT = "corrupt"
    STALE = "stale"
    FRESH = "fresh"

    @property
    def needs_indexing(self) -> bool:
        return self in {
            SemanticIndexState.PENDING,
            SemanticIndexState.FAILED,
            SemanticIndexState.CORRUPT,
            SemanticIndexState.STALE,
        }


@dataclass(frozen=True)
class SemanticIndexIdentity:
    vision_model: str
    prompt_version: str = INDEX_PROMPT_VERSION
    schema_version: str = INDEX_SCHEMA_VERSION
    embedding_model_id: str = MODEL_IDS[OPENCLIP_MODEL_KEY]
    embedding_dimension: int = INDEX_EMBEDDING_DIMENSION
    embedding_format_version: int = EMBEDDING_FORMAT_VERSION


def default_index_identity(*, vision_model: str | None = None) -> SemanticIndexIdentity:
    return SemanticIndexIdentity(vision_model=vision_model or DEFAULT_MODEL)


@dataclass(frozen=True)
class SemanticIndexMetadata:
    image_id: int
    metadata: dict
    embedding_dimension: int
    embedding_format_version: int
    vision_model: str
    prompt_version: str
    schema_version: str
    embedding_model_id: str
    source_size_bytes: int
    source_mtime_ns: int
    source_quick_fingerprint: str | None
    created_at: str
    updated_at: str

    @property
    def identity(self) -> SemanticIndexIdentity:
        return SemanticIndexIdentity(
            self.vision_model,
            self.prompt_version,
            self.schema_version,
            self.embedding_model_id,
            self.embedding_dimension,
            self.embedding_format_version,
        )

    @property
    def source_snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(
            self.source_size_bytes,
            self.source_mtime_ns,
            self.source_quick_fingerprint,
        )


@dataclass(frozen=True)
class SemanticIndexRecord(SemanticIndexMetadata):
    text_embedding: bytes


@dataclass(frozen=True)
class SemanticIndexFailureRecord:
    image_id: int
    error_code: str
    retryable: bool
    attempt_count: int
    last_attempt_at: str


@dataclass(frozen=True)
class SemanticIndexJobResult:
    processed: int
    succeeded: int
    failed: int
    skipped: int
    failed_image_ids: tuple[int, ...] = ()
