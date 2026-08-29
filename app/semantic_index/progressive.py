"""Background Semantic Index generation after the first Ask AI send.

Does not start on consent or folder selection. Search reads completed
fresh indexes without waiting for this job. Folder auto-prep must not
call this.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from app.ocr.diff_service import OCRDiffService
from app.ocr.repository import OCRRepository
from app.semantic_index.service import SemanticIndexService
from app.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_CHUNK_SIZE = 8


class _IndexJob:
    def __init__(self, generation: int, folder: Path):
        self.generation = generation
        self.folder = folder
        self.cancel = threading.Event()

    def cancelled(self) -> bool:
        return self.cancel.is_set()


class ProgressiveSemanticIndexer:
    """Index only pending/stale images, in chunks, off the UI thread."""

    def __init__(
        self,
        service: SemanticIndexService | None = None,
        image_repository: OCRRepository | None = None,
        *,
        service_factory: Callable[[], tuple[SemanticIndexService, OCRRepository] | None] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        reconcile: bool = True,
        on_close: Callable[[], None] | None = None,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if service is None and service_factory is None:
            raise ValueError("A Semantic Index service or factory is required.")
        self.service = service
        self.image_repository = image_repository
        self._service_factory = service_factory
        self.chunk_size = chunk_size
        self._reconcile = reconcile
        self._on_close = on_close
        self._lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._generation = 0
        self._job: _IndexJob | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self.started_folders: list[Path] = []

    def start(self, folder: Path | str, *, consented: bool) -> bool:
        if not consented or self._closed:
            return False
        resolved = Path(folder).resolve()
        if not resolved.exists() or not resolved.is_dir():
            return False
        with self._lock:
            if self._closed:
                return False
            current = self._job
            thread = self._thread
            if (
                current is not None
                and thread is not None
                and thread.is_alive()
                and current.folder == resolved
                and not current.cancel.is_set()
            ):
                return True
            if current is not None:
                current.cancel.set()
            self._generation += 1
            job = _IndexJob(self._generation, resolved)
            self._job = job
            self.started_folders.append(resolved)
            self._thread = threading.Thread(
                target=self._run,
                args=(job,),
                name="CapixeSemanticIndex",
                daemon=True,
            )
            self._thread.start()
        return True

    def cancel(self) -> None:
        with self._lock:
            if self._job is not None:
                self._job.cancel.set()

    def close(self, timeout: float = 2.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._job is not None:
                self._job.cancel.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                logger.warning("semantic-index close-resource-failure", exc_info=False)

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def running_folder(self) -> Path | None:
        job = self._job
        if job is None or job.cancel.is_set():
            return None
        if not self.is_running():
            return None
        return job.folder

    def _resolve_service(self) -> tuple[SemanticIndexService, OCRRepository] | None:
        if self.service is not None and self.image_repository is not None:
            return self.service, self.image_repository
        if self._service_factory is None:
            return None
        resolved = self._service_factory()
        if resolved is None:
            return None
        self.service, self.image_repository = resolved
        return resolved

    def _folder_image_ids(self, folder: Path, repository: OCRRepository) -> list[int]:
        if self._reconcile:
            OCRDiffService(repository).reconcile(folder, dry_run=False)
        return [
            image.image_id
            for image in repository.list_images(folder_path=folder, file_state="present")
        ]

    def _obsolete(self, job: _IndexJob) -> bool:
        return job.cancel.is_set() or job.generation != self._generation or self._closed

    def _run(self, job: _IndexJob) -> None:
        with self._job_lock:
            if self._obsolete(job):
                return
            try:
                resolved = self._resolve_service()
                if resolved is None or self._obsolete(job):
                    return
                service, repository = resolved
                while not self._obsolete(job):
                    ids = self._folder_image_ids(job.folder, repository)
                    if self._obsolete(job):
                        return
                    needed = service.needed_image_ids(ids)
                    if not needed:
                        return
                    chunk = needed[: self.chunk_size]
                    logger.info(
                        "semantic-index chunk folder=%s needed=%d chunk=%d",
                        job.folder,
                        len(needed),
                        len(chunk),
                    )
                    service.index_images(chunk, cancelled=job.cancelled)
            except Exception:
                logger.warning(
                    "semantic-index job-failure folder=%s", job.folder, exc_info=False
                )


def make_product_progressive_indexer(config: dict | None = None) -> ProgressiveSemanticIndexer:
    """Lazy product indexer. Opens DB/embedder on the first consented start."""
    owned: dict = {}

    def factory() -> tuple[SemanticIndexService, OCRRepository] | None:
        if "service" in owned:
            return owned["service"], owned["images"]
        from app.ocr.database import OCRDatabase
        from app.semantic.catalog import DEFAULT_MODEL_KEY, normalize_model_key
        from app.semantic.installer import resolve_semantic_bundle
        from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig
        from app.semantic_index.provider import make_index_provider
        from app.semantic_index.repository import SemanticIndexRepository
        from app.semantic_index.service import make_index_service

        settings = config if config is not None else {}
        model_key = normalize_model_key(settings.get("developer_semantic_model", DEFAULT_MODEL_KEY))
        bundle = resolve_semantic_bundle(model_key)
        if bundle is None:
            logger.info("semantic-index skip reason=bundle_unavailable")
            return None
        database = OCRDatabase().open()
        images = OCRRepository(database)
        indexes = SemanticIndexRepository(database)
        worker = SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=bundle.root))
        vision = make_index_provider()
        service = make_index_service(
            indexes,
            images,
            _WorkerTextEmbedder(worker),
            vision=vision,
        )
        owned["database"] = database
        owned["worker"] = worker
        owned["service"] = service
        owned["images"] = images
        return service, images

    def on_close() -> None:
        worker = owned.pop("worker", None)
        if worker is not None:
            shutdown = getattr(worker, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    terminate = getattr(worker, "terminate", None)
                    if callable(terminate):
                        terminate()
            else:
                terminate = getattr(worker, "terminate", None)
                if callable(terminate):
                    terminate()
        database = owned.pop("database", None)
        if database is not None:
            database.close()
        owned.clear()

    return ProgressiveSemanticIndexer(service_factory=factory, on_close=on_close)


class _WorkerTextEmbedder:
    def __init__(self, worker):
        self._worker = worker

    def embed_text(self, text: str) -> bytes:
        blob, _identity = self._worker.embed_text(text)
        return blob
