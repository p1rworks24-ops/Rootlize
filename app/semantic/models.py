from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .embedding import EMBEDDING_DIMENSION, EMBEDDING_FORMAT_VERSION


class SemanticDiffState(str, Enum):
    DELETED = "deleted"
    MISSING = "missing_embedding"
    FAILED = "failed"
    CORRUPT = "corrupt"
    MODIFIED = "modified"
    STALE_MODEL = "stale_model"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    bundle_version: str
    model_revision: str = "test"
    pipeline_version: int = 1
    embedding_format_version: int = EMBEDDING_FORMAT_VERSION
    dimension: int = EMBEDDING_DIMENSION


@dataclass(frozen=True)
class SourceSnapshot:
    size_bytes: int
    mtime_ns: int
    quick_fingerprint: str | None = None


@dataclass(frozen=True)
class SemanticEmbeddingMetadata:
    image_id: int
    dimension: int
    embedding_format_version: int
    model_id: str
    bundle_version: str
    model_revision: str
    pipeline_version: int
    source_size_bytes: int
    source_mtime_ns: int
    source_quick_fingerprint: str | None
    created_at: str
    updated_at: str

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(self.model_id, self.bundle_version, self.model_revision, self.pipeline_version, self.embedding_format_version, self.dimension)

    @property
    def source_snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(self.source_size_bytes, self.source_mtime_ns, self.source_quick_fingerprint)


@dataclass(frozen=True)
class SemanticEmbeddingRecord(SemanticEmbeddingMetadata):
    embedding: bytes


@dataclass(frozen=True)
class SemanticFailureRecord:
    image_id: int
    error_code: str
    retryable: bool
    attempt_count: int
    last_attempt_at: str


@dataclass(frozen=True)
class SemanticWorkItem:
    image_id: int
    path: str
    source_snapshot: SourceSnapshot


@dataclass(frozen=True)
class SemanticWorkerEvent:
    kind: str
    request_id: str
    processed: int
    total: int
    image_id: int | None = None
    embedding: bytes | None = None
    model_identity: ModelIdentity | None = None
    source_snapshot: SourceSnapshot | None = None
    error_code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class SemanticAnalysisResult:
    request_id: str
    state: str
    processed: int
    succeeded: int
    failed: int
    total: int


@dataclass(frozen=True)
class SemanticSearchResult:
    image_id: int
    similarity: float
