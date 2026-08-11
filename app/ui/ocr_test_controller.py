"""Owner and Qt-safe boundary for the development-only OCR validation UI."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.ocr.database import DB_FILE_NAME, OCRDatabase
from app.ocr.diff_service import OCRDiffService
from app.ocr.index_service import OCRIndexService
from app.ocr.repository import OCRRepository
from app.ocr.worker_client import OCRWorkerClient, OCRWorkerConfig
from app.paths import get_local_app_data_dir, get_resource_root, is_frozen

REQUIRED_MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "PP-OCRv6_rec_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
)


class ImageAnalysisController(QObject):
    """Application owner for the shared repository, worker, and index service."""

    preview_finished = Signal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service: OCRIndexService | None = None
        self._repository: OCRRepository | None = None
        self._closed = False
        self._preview_running = False

    def environment_status(self) -> dict[str, str | bool]:
        python_value = os.environ.get("CAPIXE_OCR_PYTHON", "").strip()
        model_value = os.environ.get("CAPIXE_OCR_MODEL_DIR", "").strip()
        python_path = Path(python_value) if python_value else (
            Path(sys.executable) if is_frozen() else None
        )
        model_path = Path(model_value) if model_value else (
            get_resource_root() / "resources" / "ocr_models" if is_frozen() else None
        )
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
        }

    def _ensure_service(self) -> OCRIndexService:
        if self._closed:
            raise RuntimeError("OCR controller is closed.")
        if self._service is not None:
            return self._service
        python_path = os.environ.get("CAPIXE_OCR_PYTHON", "").strip()
        model_path = os.environ.get("CAPIXE_OCR_MODEL_DIR", "").strip()
        if python_path:
            command = (python_path, "-m", "app.ocr.worker_entry")
        elif is_frozen():
            command = (sys.executable, "--ocr-worker")
        else:
            command = None
        database = OCRDatabase().open()
        self._repository = OCRRepository(database)
        worker = OCRWorkerClient(
            OCRWorkerConfig(
                model_dir=(
                    Path(model_path)
                    if model_path
                    else get_resource_root() / "resources" / "ocr_models"
                    if is_frozen()
                    else None
                ),
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

    def status(self):
        return self._service.get_status() if self._service else None

    def is_running(self) -> bool:
        """True until the index thread has completely finished its cleanup."""
        return bool(self._service and self._service.is_running())

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


# Compatibility name retained for the Settings development panel and its tests.
OCRTestController = ImageAnalysisController
