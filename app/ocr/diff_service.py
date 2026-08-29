"""Folder/DB reconciliation and reindex decisions, independent of OCR engines."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.ocr.exceptions import OCRRecordNotFoundError
from app.ocr.fingerprint import calculate_quick_fingerprint, calculate_sha256
from app.ocr.models import OCRDiffItem, OCRDiffResult, OCRDocumentRecord, OCRIndexSettings, ReindexDecision, ScannedImage
from app.ocr.repository import OCRRepository
from app.ocr.scanner import scan_folder
from app.utils.logger import setup_logger

logger = setup_logger()
DEFAULT_BATCH_SIZE = 100


def _settings_compatible(document: OCRDocumentRecord, settings: OCRIndexSettings) -> bool:
    """Unknown (None) settings must not invalidate an existing OCR result."""
    if document.pipeline_version != settings.pipeline_version:
        return False
    if (
        settings.model_sha256
        and document.model_sha256
        and document.model_sha256 != settings.model_sha256
    ):
        return False
    if (
        settings.settings_fingerprint
        and document.settings_fingerprint
        and document.settings_fingerprint != settings.settings_fingerprint
    ):
        return False
    return True


def decide_reindex(document: OCRDocumentRecord | None, settings: OCRIndexSettings, *, fingerprint_changed: bool = False, manual: bool = False) -> ReindexDecision:
    """Decide whether an existing image needs OCR without loading an engine."""
    if document is None:
        return ReindexDecision(True, "OCR state does not exist", "pending")
    if manual:
        return ReindexDecision(True, "Manual reindex requested", "pending")
    if not _settings_compatible(document, settings):
        return ReindexDecision(True, "OCR pipeline, model, or settings changed", "stale")
    if document.status == "failed":
        if fingerprint_changed or document.retry_count < settings.retry_limit:
            return ReindexDecision(True, "Failed OCR is eligible for retry", "pending")
        return ReindexDecision(False, "OCR retry limit reached", "failed")
    if document.status in {"pending", "running"}:
        return ReindexDecision(True, f"OCR state is {document.status}", document.status)
    if document.status == "stale" and not fingerprint_changed:
        return ReindexDecision(False, "OCR result is reusable", "ready")
    if document.status == "stale":
        return ReindexDecision(True, "OCR state is stale", "stale")
    return ReindexDecision(False, "OCR result is reusable", document.status)


class OCRDiffService:
    def __init__(self, repository: OCRRepository, *, settings: OCRIndexSettings | None = None, batch_size: int = DEFAULT_BATCH_SIZE):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.repository = repository
        self.settings = settings or OCRIndexSettings()
        self.batch_size = batch_size

    def reconcile(self, folder: str | Path, *, dry_run: bool = True) -> OCRDiffResult:
        """Scan, classify, and optionally apply one selected folder."""
        started = self.repository.database.clock()
        scan = scan_folder(folder)  # A folder-level failure aborts before any DB write.
        existing = self.repository.list_images(folder_path=scan.folder_path)
        by_path = {image.path_norm: image for image in existing}
        seen_paths = {item.path_norm for item in scan.items}
        items: list[OCRDiffItem] = []
        for scanned in scan.items:
            if not scanned.read_success:
                image = by_path.get(scanned.path_norm)
                items.append(OCRDiffItem(image.image_id if image else None,image.path if image else None,scanned.path,"scan_failed","Image metadata could not be read",False,None,None,None,None,None,scanned.error_type,scanned))
                continue
            image = by_path.get(scanned.path_norm)
            if image is None:
                fingerprint = self._quick(scanned)
                items.append(OCRDiffItem(None,None,scanned.path,"new","Path is not registered",True,None,"pending",scanned.size_bytes,scanned.mtime_ns,fingerprint,None,scanned))
                continue
            document = self._document(image.image_id)
            previous_status = document.status if document else None
            if image.file_state == "missing":
                fingerprint = self._quick(scanned)
                same = bool(image.quick_fingerprint and image.quick_fingerprint == fingerprint and image.size_bytes == scanned.size_bytes)
                effective_document = replace(document,status=document.previous_status) if document and document.previous_status else document
                decision = decide_reindex(effective_document, self.settings, fingerprint_changed=not same)
                restored_status = decision.next_status if decision.required else (effective_document.status if effective_document else "pending")
                items.append(OCRDiffItem(image.image_id,image.path,scanned.path,"restored","Missing image returned with identical content" if same else "Missing image returned with changed or unknown content",not same or decision.required,previous_status,restored_status if same else "stale",scanned.size_bytes,scanned.mtime_ns,fingerprint,None,scanned))
                continue
            if image.size_bytes == scanned.size_bytes and image.mtime_ns == scanned.mtime_ns:
                decision = decide_reindex(document, self.settings)
                items.append(OCRDiffItem(image.image_id,image.path,scanned.path,"unchanged","Path, size, and mtime match",decision.required,previous_status,decision.next_status,scanned.size_bytes,scanned.mtime_ns,image.quick_fingerprint,None,scanned))
                continue
            fingerprint = self._quick(scanned)
            mtime_only_same = image.size_bytes == scanned.size_bytes and bool(image.quick_fingerprint) and image.quick_fingerprint == fingerprint
            if mtime_only_same:
                decision = decide_reindex(document, self.settings)
                items.append(OCRDiffItem(image.image_id,image.path,scanned.path,"unchanged","Only mtime changed; quick fingerprint matches",decision.required,previous_status,decision.next_status,scanned.size_bytes,scanned.mtime_ns,fingerprint,None,scanned))
            else:
                items.append(OCRDiffItem(image.image_id,image.path,scanned.path,"modified","Size, mtime, or quick fingerprint changed",True,previous_status,"stale" if document else "pending",scanned.size_bytes,scanned.mtime_ns,fingerprint,None,scanned))
        for image in existing:
            if image.file_state == "present" and image.path_norm not in seen_paths:
                document = self._document(image.image_id)
                items.append(OCRDiffItem(image.image_id,image.path,None,"missing","Previously present path was not found",False,document.status if document else None,"missing",image.size_bytes,image.mtime_ns,image.quick_fingerprint))
        items = self._match_moves(items)
        result = OCRDiffResult(scan.folder_path,started,self.repository.database.clock(),len(scan.items),tuple(items),0)
        if dry_run:
            return result
        updated = self._apply(result.items)
        logger.info("OCR folder reconciliation completed: files=%d new=%d modified=%d missing=%d", result.total_files,len(result.new_items),len(result.modified_items),len(result.missing_items))
        return replace(result, database_updated_count=updated)

    def _document(self, image_id: int) -> OCRDocumentRecord | None:
        try:
            return self.repository.get_ocr_document(image_id)
        except OCRRecordNotFoundError:
            return None

    @staticmethod
    def _quick(scanned: ScannedImage) -> str:
        return calculate_quick_fingerprint(scanned.path)

    def _match_moves(self, items: list[OCRDiffItem]) -> list[OCRDiffItem]:
        new_by_key: dict[tuple[int | None,str | None],list[int]] = {}
        missing_by_key: dict[tuple[int | None,str | None],list[int]] = {}
        for index, item in enumerate(items):
            if item.classification not in {"new", "missing"}:
                continue
            key = (item.size_bytes, item.fingerprint)
            (new_by_key if item.classification == "new" else missing_by_key).setdefault(key, []).append(index)
        removed: set[int] = set()
        for key, new_indexes in new_by_key.items():
            old_indexes = missing_by_key.get(key, [])
            if key[1] and len(new_indexes) == len(old_indexes) == 1:
                new_index, old_index = new_indexes[0], old_indexes[0]
                new_item, old_item = items[new_index], items[old_index]
                items[new_index] = replace(new_item,image_id=old_item.image_id,old_path=old_item.old_path,classification="moved",reason="Unique size and quick fingerprint match",requires_ocr=False,previous_status=old_item.previous_status,next_status=old_item.previous_status)
                removed.add(old_index)
        return [item for index, item in enumerate(items) if index not in removed]

    def _apply(self, items: tuple[OCRDiffItem, ...]) -> int:
        updated = 0
        for start in range(0, len(items), self.batch_size):
            with self.repository.database.transaction():
                for item in items[start:start + self.batch_size]:
                    if self._apply_item(item): updated += 1
        return updated

    def _apply_item(self, item: OCRDiffItem) -> bool:
        scanned = item.scanned
        if item.classification == "scan_failed": return False
        if item.classification == "new" and scanned:
            image=self.repository.upsert_image(scanned.path,size_bytes=scanned.size_bytes,mtime_ns=scanned.mtime_ns,width=scanned.width,height=scanned.height,quick_fingerprint=item.fingerprint)
            self.repository.save_ocr_document(image.image_id,status="pending",pipeline_version=self.settings.pipeline_version,model_sha256=self.settings.model_sha256,settings_fingerprint=self.settings.settings_fingerprint)
        elif item.classification == "modified" and scanned:
            self.repository.update_scanned_metadata(item.image_id,size_bytes=scanned.size_bytes,mtime_ns=scanned.mtime_ns,width=scanned.width,height=scanned.height,quick_fingerprint=item.fingerprint,stale=True)
            if self._document(item.image_id) is None:
                self.repository.save_ocr_document(item.image_id,status="pending",pipeline_version=self.settings.pipeline_version,model_sha256=self.settings.model_sha256,settings_fingerprint=self.settings.settings_fingerprint)
        elif item.classification == "unchanged" and scanned:
            metadata_changed = self.repository.get_image(item.image_id).mtime_ns != scanned.mtime_ns
            document = self._document(item.image_id)
            if metadata_changed:
                self.repository.update_scanned_metadata(
                    item.image_id,
                    size_bytes=scanned.size_bytes,
                    mtime_ns=scanned.mtime_ns,
                    width=scanned.width,
                    height=scanned.height,
                    quick_fingerprint=item.fingerprint or self._quick(scanned),
                    stale=False,
                )
            if document is None:
                self.repository.save_ocr_document(item.image_id,status="pending",pipeline_version=self.settings.pipeline_version,model_sha256=self.settings.model_sha256,settings_fingerprint=self.settings.settings_fingerprint)
            elif item.next_status == "ready":
                self.repository.restore_searchable_ocr(item.image_id, ready=True)
            elif item.next_status == "stale":
                self.repository.mark_ocr_stale_keep_search(item.image_id)
                self.repository.restore_searchable_ocr(item.image_id, ready=False)
        elif item.classification == "missing":
            self.repository.mark_file_state(item.image_id,"missing")
        elif item.classification == "restored" and scanned:
            self.repository.restore_image(item.image_id,size_bytes=scanned.size_bytes,mtime_ns=scanned.mtime_ns,width=scanned.width,height=scanned.height,quick_fingerprint=item.fingerprint,content_unchanged=item.next_status != "stale")
            if self._document(item.image_id) is None:
                self.repository.save_ocr_document(item.image_id,status="pending",pipeline_version=self.settings.pipeline_version,model_sha256=self.settings.model_sha256,settings_fingerprint=self.settings.settings_fingerprint)
        elif item.classification == "moved" and scanned:
            self.repository.update_path(item.image_id,scanned.path,mtime_ns=scanned.mtime_ns)
            self.repository.update_scanned_metadata(item.image_id,size_bytes=scanned.size_bytes,mtime_ns=scanned.mtime_ns,width=scanned.width,height=scanned.height,quick_fingerprint=item.fingerprint,stale=False)
        else:
            return False
        return True

    def record_internal_rename(self, old_path: str | Path, new_path: str | Path, *, mtime_ns: int):
        image = self.repository.get_image_by_path(old_path)
        return self.repository.update_path(image.image_id,new_path,mtime_ns=mtime_ns)

    def record_internal_move(self, old_path: str | Path, new_path: str | Path, *, mtime_ns: int):
        return self.record_internal_rename(old_path,new_path,mtime_ns=mtime_ns)


__all__ = ["OCRDiffService", "decide_reindex", "calculate_sha256"]
