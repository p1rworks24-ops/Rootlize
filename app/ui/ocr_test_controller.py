"""Owner and Qt-safe boundary for the development-only OCR validation UI."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.ocr.database import DB_FILE_NAME, OCRDatabase
from app.ocr.diff_service import OCRDiffService
from app.ocr.index_service import OCRIndexService
from app.ocr.repository import OCRRepository
from app.ocr.worker_client import OCRWorkerClient, OCRWorkerConfig
from app.ocr.job_models import OCRIndexProgress
from app.paths import get_local_app_data_dir, get_resource_root, is_frozen
from app.semantic.catalog import DEFAULT_MODEL_KEY, normalize_model_key
from app.semantic.installer import resolve_semantic_bundle
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticAnalysisService
from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig

REQUIRED_MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)


class ImageAnalysisController(QObject):
    """Application owner for the shared repository, worker, and index service."""

    preview_finished = Signal(object, object)

    def __init__(self, parent: QObject | None = None, *, config: dict | None = None) -> None:
        super().__init__(parent)
        self._service: OCRIndexService | None = None
        self._repository: OCRRepository | None = None
        self._closed = False
        self._preview_running = False
        self._semantic_thread: threading.Thread | None = None
        self._semantic_progress: OCRIndexProgress | None = None
        self._semantic_worker: SemanticWorkerClient | None = None
        self._semantic_service: SemanticAnalysisService | None = None
        self._semantic_terminal_reported = False
        self._semantic_bundle_cache = None
        self._semantic_pending_by_folder: dict[str, set[str]] = {}
        self._analysis_details_by_folder: dict[str, dict[str, dict]] = {}
        self._semantic_retry_after_ocr: tuple[Path, ...] = ()
        self._semantic_lock = threading.RLock()
        self._config = config if config is not None else {}
        self._semantic_model_key = normalize_model_key(self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY))

    def sync_semantic_model_from_config(self) -> bool:
        key = normalize_model_key(self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY))
        if key == self._semantic_model_key:
            return False
        if self._semantic_worker is not None:
            self._semantic_worker.terminate()
        with self._semantic_lock:
            self._semantic_model_key = key
            self._semantic_bundle_cache = None
            self._semantic_pending_by_folder.clear()
            self._analysis_details_by_folder.clear()
        return True

    def _semantic_bundle(self):
        with self._semantic_lock:
            if self._semantic_bundle_cache is not None:
                return self._semantic_bundle_cache
        bundle = resolve_semantic_bundle(self._semantic_model_key)
        with self._semantic_lock:
            self._semantic_bundle_cache = bundle
        return bundle

    def semantic_available(self) -> bool:
        """True when preview already found an installed OpenCLIP bundle."""
        with self._semantic_lock:
            return self._semantic_bundle_cache is not None

    def _ocr_runtime_paths(self) -> tuple[Path | None, Path | None]:
        """Resolve OCR runtime/model paths. Frozen builds always use the bundle."""
        if is_frozen():
            return Path(sys.executable), get_resource_root() / "resources" / "ocr_models"
        python_value = os.environ.get("CAPIXE_OCR_PYTHON", "").strip()
        model_value = os.environ.get("CAPIXE_OCR_MODEL_DIR", "").strip()
        return (
            Path(python_value) if python_value else None,
            Path(model_value) if model_value else None,
        )

    def environment_status(self) -> dict[str, str | bool]:
        python_path, model_path = self._ocr_runtime_paths()
        runtime_ok = bool(python_path and python_path.is_file())
        models_ok = bool(
            model_path
            and model_path.is_dir()
            and all((model_path / name).is_file() for name in REQUIRED_MODEL_FILES)
        )
        worker_state = self._service.worker.state if self._service else "stopped"
        return {
            "runtime": "available" if runtime_ok else "not_configured",
            "models": "ready" if models_ok else "not_configured",
            "worker": worker_state,
            "database": "ready" if self._repository is not None else "not_opened",
            "usable": runtime_ok and models_ok,
            "semantic": (
                "ready" if self._semantic_bundle_cache is not None else "not_loaded"
            ),
        }

    def semantic_pending_names(self, folder: Path) -> set[str]:
        """Return the latest background-computed Semantic diff without I/O."""
        key = str(folder.resolve())
        with self._semantic_lock:
            return set(self._semantic_pending_by_folder.get(key, set()))

    def analysis_details(self, folder: Path) -> dict[str, dict]:
        """Latest per-image OCR/Semantic identity and failure diagnostics."""
        key = str(folder.resolve())
        with self._semantic_lock:
            return {name: dict(value) for name, value in self._analysis_details_by_folder.get(key, {}).items()}

    def _compute_semantic_pending_names(self, folder: Path) -> set[str]:
        """Validate the bundle and inspect embeddings off the UI thread."""
        bundle = self._semantic_bundle()
        database_path = get_local_app_data_dir() / DB_FILE_NAME
        if bundle is None or not database_path.is_file():
            return set()
        database = OCRDatabase(database_path).open()
        try:
            images = OCRRepository(database)
            records = images.list_images(folder_path=folder, file_state="present")
            states = SemanticRepository(database).classify_embeddings(
                (image.image_id for image in records), bundle.identity
            )
            semantic = SemanticRepository(database)
            details = {}
            for image in records:
                state = states.get(image.image_id)
                metadata = semantic.get_embedding_metadata(image.image_id)
                failure = semantic.get_failure(image.image_id)
                ocr = database.connection.execute(
                    "SELECT status,error_type,error_message_safe FROM ocr_documents WHERE image_id=?",
                    (image.image_id,),
                ).fetchone()
                semantic_status = getattr(state, "value", "missing_embedding")
                ocr_status = str(ocr[0]) if ocr is not None else "missing"
                if ocr_status in {"running", "processing", "claimed"}:
                    display_status = "processing"
                elif semantic_status in {"failed", "corrupt"}:
                    display_status = "semantic_failed"
                elif ocr_status in {"failed", "error"}:
                    display_status = "ocr_issue"
                elif semantic_status in {"missing_embedding", "stale_model", "modified"}:
                    display_status = "missing_embedding"
                elif ocr_status != "ready":
                    display_status = "ocr_pending"
                else:
                    display_status = "unchanged"
                semantic_reason = ""
                ocr_reason = ""
                if failure is not None:
                    semantic_reason = failure.error_code
                if ocr is not None and ocr_status != "ready":
                    ocr_reason = str(ocr[2] or ocr[1] or ocr_status)
                if not semantic_reason and semantic_status == "stale_model" and metadata is not None:
                    semantic_reason = f"stored model {metadata.model_id} does not match active model {bundle.identity.model_id}"
                elif not semantic_reason and semantic_status == "modified":
                    semantic_reason = "image changed after the embedding was created"
                elif not semantic_reason and semantic_status == "missing_embedding":
                    semantic_reason = "no embedding for the active model"
                details[image.filename] = {
                    "filename": image.filename,
                    "path": image.path,
                    "ocr_status": ocr_status,
                    "semantic_status": semantic_status,
                    "display_status": display_status,
                    "model_id": metadata.model_id if metadata else bundle.identity.model_id,
                    "bundle_version": metadata.bundle_version if metadata else bundle.identity.bundle_version,
                    "revision": metadata.model_revision if metadata else bundle.identity.model_revision,
                    "dimension": metadata.dimension if metadata else bundle.identity.dimension,
                    "ocr_failure_reason": ocr_reason,
                    "semantic_failure_reason": semantic_reason,
                    "failure_reason": semantic_reason or ocr_reason,
                }
            pending = {
                image.filename for image in records
                if getattr(states.get(image.image_id), "value", None) != "unchanged"
            }
            with self._semantic_lock:
                self._semantic_pending_by_folder[str(folder.resolve())] = pending
                self._analysis_details_by_folder[str(folder.resolve())] = details
            return pending
        finally:
            database.close()

    def start_semantic(self, folder: Path, image_paths=None) -> bool:
        """Generate missing/stale Semantic embeddings without rerunning OCR."""
        if self._closed or self._semantic_thread is not None and self._semantic_thread.is_alive():
            return False
        bundle = self._semantic_bundle()
        if bundle is None:
            return False
        if image_paths is None and self._semantic_retry_after_ocr:
            image_paths = self._semantic_retry_after_ocr
            self._semantic_retry_after_ocr = ()
        pending_names = self.semantic_pending_names(folder)
        # Worker protocol validates request IDs as canonical UUID strings.
        # Worker protocol validates request IDs as canonical UUID strings.
        run_id = str(uuid.uuid4())
        self._semantic_progress = OCRIndexProgress(
            run_id=run_id, folder_path=str(folder.resolve()), state="initializing_worker",
            total_discovered=len(pending_names),
            total_requires_ocr=max(1, len(pending_names)),
            pending=max(1, len(pending_names)),
        )
        self._semantic_terminal_reported = False

        def on_progress(event) -> None:
            if event.kind != "progress" or self._semantic_progress is None:
                return
            completed = min(event.processed, self._semantic_progress.total_requires_ocr)
            self._semantic_progress = replace(
                self._semantic_progress, state="running", completed=completed,
                pending=max(0, self._semantic_progress.total_requires_ocr - completed),
            )

        def run() -> None:
            database = OCRDatabase().open()
            worker = SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=bundle.root))
            self._semantic_worker = worker
            ids: list[int] = []
            try:
                images = OCRRepository(database)
                records = images.list_images(folder_path=folder, file_state="present")
                repository = SemanticRepository(database)
                states = repository.classify_embeddings(
                    (image.image_id for image in records), bundle.identity
                )
                selected = {str(Path(path).resolve()).lower() for path in image_paths or ()}
                ids = [
                    image.image_id for image in records
                    if getattr(states.get(image.image_id), "value", None) != "unchanged"
                    and (not selected or str(Path(image.path).resolve()).lower() in selected)
                ]
                total = len(ids)
                self._semantic_progress = replace(
                    self._semantic_progress, state="initializing_worker",
                    total_discovered=total, total_requires_ocr=total, pending=total,
                )
                service = SemanticAnalysisService(repository, images, worker, on_progress=on_progress)
                self._semantic_service = service
                result = service.analyze(ids, bundle.identity, request_id=run_id)
                self._semantic_progress = replace(
                    self._semantic_progress, state=result.state,
                    completed=result.processed, succeeded=result.succeeded,
                    failed=result.failed, pending=max(0, result.total-result.processed),
                )
                final_states = repository.classify_embeddings(
                    (image.image_id for image in records), bundle.identity
                )
                with self._semantic_lock:
                    self._semantic_pending_by_folder[str(folder.resolve())] = {
                        image.filename for image in records
                        if getattr(final_states.get(image.image_id), "value", None)
                        != "unchanged"
                    }
            except Exception as exc:
                error_code = getattr(exc, "code", None) or type(exc).__name__.upper()
                repository = SemanticRepository(database)
                for image_id in ids:
                    try:
                        repository.record_failure(
                            image_id, f"BATCH_{error_code}"[:100], True
                        )
                    except Exception:
                        pass
                self._semantic_progress = replace(
                    self._semantic_progress, state="failed",
                    last_error_type=type(exc).__name__,
                )
            finally:
                worker.shutdown()
                self._semantic_worker = None
                self._semantic_service = None
                database.close()

        self._semantic_thread = threading.Thread(
            target=run, name="CapixeSemanticAnalysis", daemon=True
        )
        self._semantic_thread.start()
        return True

    def retry_semantic_paths(self, paths) -> bool:
        paths = tuple(Path(path) for path in paths)
        if not paths:
            return False
        return self.start_semantic(paths[0].parent, paths)

    def retry_analysis_paths(self, paths) -> bool:
        """Retry only failed/pending components for the selected images."""
        paths = tuple(Path(path) for path in paths)
        if not paths or self.is_running():
            return False
        folder = paths[0].parent
        details = self.analysis_details(folder)
        ocr_paths = tuple(
            path for path in paths
            if str(details.get(path.name, {}).get("ocr_status", "missing")) != "ready"
        )
        semantic_paths = tuple(
            path for path in paths
            if str(details.get(path.name, {}).get("semantic_status", "missing_embedding"))
            not in {"unchanged", "ready"}
        )
        if ocr_paths:
            service = self._ensure_service()
            image_ids = []
            for path in ocr_paths:
                try:
                    image_ids.append(service.repository.get_image_by_path(path).image_id)
                except Exception:
                    continue
            if image_ids:
                service.repository.queue_ocr_retry(image_ids)
                self._semantic_retry_after_ocr = semantic_paths
                service.start_indexing(folder, image_ids=image_ids)
                return True
            # Unregistered files are not in the DB yet. Differential start
            # registers them and processes only OCR candidates.
            if self.environment_status()["usable"]:
                self._semantic_retry_after_ocr = semantic_paths
                service.start_indexing(folder)
                return True
            return False
        if semantic_paths:
            return self.start_semantic(folder, semantic_paths)
        return False

    @property
    def ocr_repository(self):
        """Shared OCR index, if the analysis service has already opened it."""
        return self._repository

    def _ensure_service(self) -> OCRIndexService:
        if self._closed:
            raise RuntimeError("OCR controller is closed.")
        if self._service is not None:
            return self._service
        python_path, model_path = self._ocr_runtime_paths()
        if is_frozen():
            command = (sys.executable, "--ocr-worker")
        elif python_path is not None:
            command = (str(python_path), "-m", "app.ocr.worker_entry")
        else:
            command = None
        database = OCRDatabase().open()
        self._repository = OCRRepository(database)
        worker = OCRWorkerClient(
            OCRWorkerConfig(
                model_dir=model_path,
                command=command,
            )
        )
        self._service = OCRIndexService(self._repository, worker)
        return self._service

    def preview(self, folder: Path) -> bool:
        if self._preview_running or self._closed:
            return False
        self._preview_running = True

        def run() -> None:
            result = error = None
            try:
                persistent_db = get_local_app_data_dir() / DB_FILE_NAME
                if self._service is not None or persistent_db.exists():
                    result = self._ensure_service().preview_indexing(folder)
                else:
                    # An initial Preview must not create the real OCR index.
                    with tempfile.TemporaryDirectory(prefix="capixe-ocr-preview-") as temp:
                        database = OCRDatabase(Path(temp) / DB_FILE_NAME).open()
                        try:
                            result = OCRDiffService(OCRRepository(database)).reconcile(
                                folder, dry_run=True
                            )
                        finally:
                            database.close()
                # Bundle hashing and the full embedding-state scan are part of
                # preview preparation, but must never run in the Qt UI thread.
                try:
                    self._compute_semantic_pending_names(folder)
                except Exception:
                    with self._semantic_lock:
                        self._semantic_pending_by_folder[str(folder.resolve())] = set()
            except Exception as exc:  # UI receives only the exception category.
                error = exc
            finally:
                self._preview_running = False
                if not self._closed:
                    self.preview_finished.emit(result, error)

        threading.Thread(target=run, name="CapixeOCRPreview", daemon=True).start()
        return True

    def start(self, folder: Path) -> str:
        if not self.environment_status()["usable"]:
            raise RuntimeError("OCR environment unavailable")
        return self._ensure_service().start_indexing(folder)

    def pause(self) -> None:
        if self._service:
            self._service.pause()

    def resume(self) -> None:
        if self._service:
            self._service.resume()

    def cancel(self) -> None:
        if self._service:
            self._service.cancel()
        if self._semantic_service is not None:
            self._semantic_service.cancel()

    def status(self):
        if self._semantic_thread is not None and self._semantic_thread.is_alive():
            return self._semantic_progress
        if (
            self._semantic_progress is not None
            and self._semantic_progress.state in {"completed", "failed", "cancelled"}
            and not self._semantic_terminal_reported
        ):
            self._semantic_terminal_reported = True
            return self._semantic_progress
        return self._service.get_status() if self._service else None

    def is_running(self) -> bool:
        """True until the index thread has completely finished its cleanup."""
        return bool(
            self._service and self._service.is_running()
            or self._semantic_thread and self._semantic_thread.is_alive()
        )

    def search(self, query: str, folder: Path, limit: int = 50):
        self._ensure_service()
        assert self._repository is not None
        return self._repository.search(query, folder_path=folder)[:limit]

    def close(self, timeout: float = 3.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self._service is not None:
            self._service.close(timeout=timeout)
        if self._semantic_worker is not None:
            self._semantic_worker.terminate()
        if self._semantic_thread is not None:
            self._semantic_thread.join(timeout)


# Compatibility name retained for the Settings development panel and its tests.
OCRTestController = ImageAnalysisController
