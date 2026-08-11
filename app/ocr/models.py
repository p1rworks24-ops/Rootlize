from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemaInfo:
    schema_version: int
    normalization_version: int
    search_schema_version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ImageRecord:
    image_id: int
    path: str
    path_norm: str
    folder_path: str
    folder_path_norm: str
    filename: str
    filename_norm: str
    size_bytes: int
    mtime_ns: int
    width: int | None
    height: int | None
    quick_fingerprint: str | None
    content_sha256: str | None
    file_state: str
    discovered_at: str
    last_seen_at: str
    missing_since: str | None


@dataclass(frozen=True)
class OCRDocumentRecord:
    image_id: int
    ocr_text: str | None
    ocr_text_norm: str
    ocr_text_compact_norm: str
    average_confidence: float | None
    status: str
    previous_status: str | None
    error_type: str | None
    error_message_safe: str | None
    retry_count: int
    indexed_at: str | None
    engine_name: str | None
    engine_version: str | None
    model_name: str | None
    model_sha256: str | None
    pipeline_version: int
    normalization_version: int
    settings_fingerprint: str | None
    claimed_at: str | None
    worker_id: str | None
    last_attempt_at: str | None
    next_retry_at: str | None


@dataclass(frozen=True)
class SearchDocumentRecord:
    image_id: int
    filename_norm: str
    tags_norm: str
    ocr_norm: str
    ocr_compact_norm: str


@dataclass(frozen=True)
class SearchResult:
    image_id: int
    path: str
    mtime_ns: int
    matched_filename: bool
    matched_tags: bool
    matched_ocr: bool
    rank: float


@dataclass(frozen=True)
class ImageFingerprint:
    quick_fingerprint: str
    content_sha256: str | None = None


@dataclass(frozen=True)
class ScannedImage:
    path: str
    path_norm: str
    folder_path: str
    folder_path_norm: str
    filename: str
    filename_norm: str
    size_bytes: int | None
    mtime_ns: int | None
    width: int | None
    height: int | None
    read_success: bool
    error_type: str | None = None


@dataclass(frozen=True)
class OCRIndexSettings:
    pipeline_version: int = 1
    model_sha256: str | None = None
    settings_fingerprint: str | None = None
    retry_limit: int = 3


@dataclass(frozen=True)
class ReindexDecision:
    required: bool
    reason: str
    next_status: str | None


@dataclass(frozen=True)
class OCRDiffItem:
    image_id: int | None
    old_path: str | None
    new_path: str | None
    classification: str
    reason: str
    requires_ocr: bool
    previous_status: str | None
    next_status: str | None
    size_bytes: int | None
    mtime_ns: int | None
    fingerprint: str | None = None
    error_type: str | None = None
    scanned: ScannedImage | None = None


@dataclass(frozen=True)
class OCRDiffResult:
    folder_path: str
    scan_started_at: str
    scan_finished_at: str
    total_files: int
    items: tuple[OCRDiffItem, ...]
    database_updated_count: int = 0

    def classified(self, name: str) -> tuple[OCRDiffItem, ...]:
        return tuple(item for item in self.items if item.classification == name)

    @property
    def reindex_required_count(self) -> int:
        return sum(item.requires_ocr for item in self.items)

    @property
    def new_items(self): return self.classified("new")
    @property
    def unchanged_items(self): return self.classified("unchanged")
    @property
    def modified_items(self): return self.classified("modified")
    @property
    def missing_items(self): return self.classified("missing")
    @property
    def restored_items(self): return self.classified("restored")
    @property
    def moved_items(self): return self.classified("moved")
    @property
    def scan_failed_items(self): return self.classified("scan_failed")
