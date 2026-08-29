"""Generate and persist query-independent image facts.

This is storage and differential generation. Meaning Search reads fresh
facts; this service does not run search. Folder auto-prep must not call
this. Progressive generation starts from an explicit send boundary
(Prototype Tour Start preparing, or the first Ask AI send if not already started).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol

from app.ai_usage.recorder import AiUsageRecorder, get_usage_recorder
from app.ocr.exceptions import OCRInvalidRecordError, OCRRecordNotFoundError
from app.ocr.repository import OCRRepository
from app.relevance import RelevanceImage
from app.semantic.models import SourceSnapshot
from app.image_facts.models import (
    ImageFactsIdentity,
    ImageFactsJobResult,
    ImageFactsState,
    default_facts_identity,
)
from app.image_facts.provider import FactsRun, ImageFactsProvider, make_facts_provider
from app.image_facts.repository import ImageFactsRepository
from app.utils.logger import setup_logger

logger = setup_logger()


class ImageFactsVision(Protocol):
    model: str

    def index(
        self,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> FactsRun:
        ...


class ImageFactsService:
    def __init__(
        self,
        repository: ImageFactsRepository,
        image_repository: OCRRepository,
        *,
        vision: ImageFactsVision | None = None,
        identity: ImageFactsIdentity | None = None,
        usage: AiUsageRecorder | None = None,
    ):
        self.repository = repository
        self.image_repository = image_repository
        self.vision = vision
        self.identity = identity or default_facts_identity(
            vision_model=getattr(vision, "model", None)
        )
        self.usage = usage

    def classify(self, image_ids: Iterable[int]) -> dict[int, ImageFactsState]:
        return self.repository.classify(image_ids, self.identity)

    def needed_image_ids(self, image_ids: Iterable[int]) -> list[int]:
        return self.repository.needed_image_ids(image_ids, self.identity)

    def index_images(
        self,
        image_ids: Iterable[int],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> ImageFactsJobResult:
        ids = tuple(int(value) for value in image_ids)
        if not ids:
            return ImageFactsJobResult(0, 0, 0, 0)
        needed = self.needed_image_ids(ids)
        skipped = len(ids) - len(needed)
        if not needed:
            return ImageFactsJobResult(0, 0, 0, skipped)
        reasons = self.repository.generation_reasons(needed, self.identity)
        if self.vision is None:
            raise RuntimeError("Image facts generation requires a Vision provider.")
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
            return ImageFactsJobResult(len(needed), 0, len(failed), skipped, tuple(failed))
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
                self.repository.upsert_facts(
                    item.image_id,
                    record,
                    self.identity,
                    snapshots[item.image_id],
                )
                succeeded += 1
            except (OCRInvalidRecordError, OCRRecordNotFoundError, ValueError, TypeError) as exc:
                logger.warning(
                    "image-facts save-failure image_id=%s error=%s",
                    item.image_id, type(exc).__name__,
                )
                self.repository.record_failure(item.image_id, "save_failed", retryable=True)
                failed.append(item.image_id)
        self._record_usage(run, reasons)
        return ImageFactsJobResult(
            processed=len(needed),
            succeeded=succeeded,
            failed=len(failed),
            skipped=skipped,
            failed_image_ids=tuple(failed),
            request_count=getattr(run, "request_count", succeeded + len(failed)),
        )

    def _record_usage(self, run: FactsRun, reasons: dict[int, str]) -> None:
        recorder = self.usage if self.usage is not None else get_usage_recorder()
        counts: dict[str, int] = {}
        for reason in reasons.values():
            counts[reason] = counts.get(reason, 0) + 1
        recorder.record_vision(
            model=str(getattr(self.vision, "model", "") or self.identity.vision_model),
            request_count=int(getattr(run, "request_count", 0) or 0),
            input_tokens=int(getattr(run, "input_tokens", 0) or 0),
            output_tokens=int(getattr(run, "output_tokens", 0) or 0),
            reasons=counts,
        )


def make_facts_service(
    repository: ImageFactsRepository,
    image_repository: OCRRepository,
    *,
    vision: ImageFactsVision | None = None,
    identity: ImageFactsIdentity | None = None,
    usage: AiUsageRecorder | None = None,
) -> ImageFactsService:
    provider = vision or make_facts_provider()
    return ImageFactsService(
        repository,
        image_repository,
        vision=provider,
        identity=identity or default_facts_identity(vision_model=provider.model),
        usage=usage,
    )
