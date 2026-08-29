"""Generate and persist query-independent Semantic Indexes.

This is storage and differential generation. Product Meaning Search reads
fresh rows through the Hybrid gate; this service does not run search.
Folder auto-prep must not call this service. Progressive generation starts
from the first consented Ask AI send, not from consent or folder selection.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol

from app.ocr.exceptions import OCRInvalidRecordError, OCRRecordNotFoundError
from app.ocr.repository import OCRRepository
from app.relevance import RelevanceImage
from app.semantic.models import SourceSnapshot
from app.semantic_index.models import (
    SemanticIndexIdentity,
    SemanticIndexJobResult,
    SemanticIndexState,
    default_index_identity,
)
from app.semantic_index.provider import IndexRun, SemanticIndexProvider, make_index_provider
from app.semantic_index.repository import SemanticIndexRepository
from app.semantic_index.schema import clip_index_text
from app.utils.logger import setup_logger

logger = setup_logger()


class SemanticIndexVision(Protocol):
    model: str

    def index(
        self,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> IndexRun:
        ...


class SemanticIndexTextEmbedder(Protocol):
    def embed_text(self, text: str) -> bytes:
        ...


class SemanticIndexService:
    def __init__(
        self,
        repository: SemanticIndexRepository,
        image_repository: OCRRepository,
        *,
        vision: SemanticIndexVision | None = None,
        embedder: SemanticIndexTextEmbedder | None = None,
        identity: SemanticIndexIdentity | None = None,
    ):
        self.repository = repository
        self.image_repository = image_repository
        self.vision = vision
        self.embedder = embedder
        self.identity = identity or default_index_identity(
            vision_model=getattr(vision, "model", None)
        )

    def classify(self, image_ids: Iterable[int]) -> dict[int, SemanticIndexState]:
        return self.repository.classify(image_ids, self.identity)

    def needed_image_ids(self, image_ids: Iterable[int]) -> list[int]:
        return self.repository.needed_image_ids(image_ids, self.identity)

    def index_images(
        self,
        image_ids: Iterable[int],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> SemanticIndexJobResult:
        ids = tuple(int(value) for value in image_ids)
        if not ids:
            return SemanticIndexJobResult(0, 0, 0, 0)
        needed = self.needed_image_ids(ids)
        skipped = len(ids) - len(needed)
        if not needed:
            return SemanticIndexJobResult(0, 0, 0, skipped)
        if self.vision is None or self.embedder is None:
            raise RuntimeError("Semantic index generation requires a Vision provider and text embedder.")
        targets: list[RelevanceImage] = []
        snapshots: dict[int, SourceSnapshot] = {}
        failed: list[int] = []
        for image_id in needed:
            try:
                image = self.image_repository.get_image(image_id)
            except OCRRecordNotFoundError:
                failed.append(image_id)
                continue
            if image.file_state != "present":
                failed.append(image_id)
                continue
            snapshots[image_id] = SourceSnapshot(
                image.size_bytes, image.mtime_ns, image.quick_fingerprint
            )
            targets.append(RelevanceImage(image_id, Path(image.path)))
        if not targets:
            return SemanticIndexJobResult(len(needed), 0, len(failed), skipped, tuple(failed))
        run = self.vision.index(targets, cancelled=cancelled)
        succeeded = 0
        by_id = {int(item["image_id"]): item for item in run.results}
        stopping = bool(cancelled is not None and cancelled())
        for item in targets:
            record = by_id.get(item.image_id) or {}
            reason = str(record.get("unknown_reason") or "")
            if reason == "cancelled" or (stopping and not record):
                continue
            if reason:
                self.repository.record_failure(item.image_id, reason, retryable=True)
                failed.append(item.image_id)
                continue
            try:
                embedding = self.embedder.embed_text(clip_index_text(record))
                self.repository.upsert_index(
                    item.image_id,
                    record,
                    embedding,
                    self.identity,
                    snapshots[item.image_id],
                )
                succeeded += 1
            except (OCRInvalidRecordError, OCRRecordNotFoundError, ValueError, TypeError) as exc:
                logger.warning(
                    "semantic-index save-failure image_id=%s error=%s",
                    item.image_id, type(exc).__name__,
                )
                self.repository.record_failure(item.image_id, "save_failed", retryable=True)
                failed.append(item.image_id)
        return SemanticIndexJobResult(
            processed=len(needed),
            succeeded=succeeded,
            failed=len(failed),
            skipped=skipped,
            failed_image_ids=tuple(failed),
        )


def make_index_service(
    repository: SemanticIndexRepository,
    image_repository: OCRRepository,
    embedder: SemanticIndexTextEmbedder,
    *,
    vision: SemanticIndexVision | None = None,
    identity: SemanticIndexIdentity | None = None,
) -> SemanticIndexService:
    provider = vision or make_index_provider()
    return SemanticIndexService(
        repository,
        image_repository,
        vision=provider,
        embedder=embedder,
        identity=identity or default_index_identity(vision_model=provider.model),
    )
