"""Background image-facts generation after explicit Ask AI consent.

Does not start on consent display, Cancel, or folder selection.
`Agree and use Ask AI` is the start boundary. Ask AI waits for the
first folder prep before Meaning Search; later searches read completed
fresh facts without waiting for this job. Folder auto-prep must not
call this.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ocr.diff_service import OCRDiffService
from app.ocr.repository import OCRRepository
from app.image_facts.service import ImageFactsService
from app.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_CHUNK_SIZE = 8


@dataclass(frozen=True)
class FactsPrepSnapshot:
    running: bool = False
    folder: Path | None = None
    ready: int = 0
    total: int = 0
    needed: int = 0
    last_error: BaseException | None = None


class _FactsJob:
    def __init__(self, generation: int, folder: Path):
        self.generation = generation
        self.folder = folder
        self.cancel = threading.Event()

    def cancelled(self) -> bool:
        return self.cancel.is_set()


class ProgressiveFactsIndexer:
    """Generate facts only for pending/stale images, in chunks, off the UI thread."""

    def __init__(
        self,
        service: ImageFactsService | None = None,
        image_repository: OCRRepository | None = None,
        *,
        service_factory: Callable[[], tuple[ImageFactsService, OCRRepository] | None] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        reconcile: bool = True,
        on_close: Callable[[], None] | None = None,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if service is None and service_factory is None:
            raise ValueError("An image facts service or factory is required.")
        self.service = service
        self.image_repository = image_repository
        self._service_factory = service_factory
        self.chunk_size = chunk_size
        self._reconcile = reconcile
        self._on_close = on_close
        self._lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._generation = 0
        self._job: _FactsJob | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self.started_folders: list[Path] = []
        self._last_error: BaseException | None = None
        self._snapshot = FactsPrepSnapshot()

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

        ids: list[int] = []
        needed_ids: list[int] = []
        probe_ok = False
        resolved_service = self._resolve_service()
        if resolved_service is not None and not self._closed:
            service, repository = resolved_service
            try:
                ids = self._folder_image_ids(resolved, repository)
                needed_ids = service.needed_image_ids(ids)
                probe_ok = True
            except Exception:
                logger.warning(
                    "image-facts start-probe-failure folder=%s",
                    resolved,
                    exc_info=False,
                )
        needed = len(needed_ids)
        ready = max(0, len(ids) - needed)

        with self._lock:
            if self._closed:
                return False
            if probe_ok and not needed:
                self._last_error = None
                self._snapshot = FactsPrepSnapshot(
                    running=False,
                    folder=resolved,
                    ready=ready,
                    total=len(ids),
                    needed=0,
                )
                return False
            self._generation += 1
            self._last_error = None
            job = _FactsJob(self._generation, resolved)
            self._job = job
            self.started_folders.append(resolved)
            self._snapshot = FactsPrepSnapshot(
                running=True,
                folder=resolved,
                ready=ready,
                total=len(ids),
                needed=needed,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(job,),
                name="CapixeImageFacts",
                daemon=True,
            )
            self._thread.start()
        return True

    def has_unready_images(self, folder: Path | str | None = None) -> bool:
        """True while this folder still has images that need facts."""
        snap = self.snapshot()
        if folder is not None and snap.folder is not None:
            if Path(folder).resolve() != Path(snap.folder).resolve():
                return False
        return bool(snap.running and snap.needed > 0)

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
                logger.warning("image-facts close-resource-failure", exc_info=False)

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def last_error(self) -> BaseException | None:
        """Set only after a job stops with images still needing facts."""
        with self._lock:
            if self._snapshot.needed <= 0:
                return None
            error = self._last_error
        if self.is_running():
            return None
        return error

    def snapshot(self) -> FactsPrepSnapshot:
        with self._lock:
            data = self._snapshot
            running = self.is_running()
            error = None if running or data.needed <= 0 else self._last_error
        return FactsPrepSnapshot(
            running=running,
            folder=data.folder,
            ready=data.ready,
            total=data.total,
            needed=data.needed,
            last_error=error,
        )

    def _set_snapshot(self, **fields) -> None:
        with self._lock:
            current = self._snapshot
            self._snapshot = FactsPrepSnapshot(
                running=fields.get("running", current.running),
                folder=fields.get("folder", current.folder),
                ready=int(fields.get("ready", current.ready)),
                total=int(fields.get("total", current.total)),
                needed=int(fields.get("needed", current.needed)),
            )

    def _resolve_service(self) -> tuple[ImageFactsService, OCRRepository] | None:
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

    def _obsolete(self, job: _FactsJob) -> bool:
        return job.cancel.is_set() or job.generation != self._generation or self._closed

    def _run(self, job: _FactsJob) -> None:
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
                    ready = max(0, len(ids) - len(needed))
                    self._set_snapshot(
                        running=True,
                        folder=job.folder,
                        ready=ready,
                        total=len(ids),
                        needed=len(needed),
                    )
                    if not needed:
                        return
                    chunk = needed[: self.chunk_size]
                    logger.info(
                        "image-facts chunk folder=%s needed=%d chunk=%d",
                        job.folder,
                        len(needed),
                        len(chunk),
                    )
                    service.index_images(chunk, cancelled=job.cancelled)
            except Exception as exc:
                from app.ai_proxy.errors import describe_ai_failure, proxy_runtime_flags

                self._last_error = exc
                current = self.snapshot()
                configured, authenticated = proxy_runtime_flags()
                logger.warning(
                    "image-facts job-failure folder=%s %s",
                    job.folder,
                    describe_ai_failure(
                        exc,
                        operation="facts_generate",
                        configured=configured,
                        authenticated=authenticated,
                        facts_needed=current.needed,
                        facts_generated=current.ready,
                        facts_failed=min(self.chunk_size, current.needed) if current.needed else 1,
                    ),
                    exc_info=False,
                )
            finally:
                with self._lock:
                    if self._job is job:
                        current = self._snapshot
                        self._snapshot = FactsPrepSnapshot(
                            running=False,
                            folder=current.folder,
                            ready=current.ready,
                            total=current.total,
                            needed=current.needed,
                            last_error=self._last_error,
                        )


def make_product_progressive_facts_indexer(config: dict | None = None) -> ProgressiveFactsIndexer:
    """Lazy product facts indexer. Opens DB on the first consented start."""
    owned: dict = {}

    def factory() -> tuple[ImageFactsService, OCRRepository] | None:
        if "service" in owned:
            return owned["service"], owned["images"]
        from app.ocr.database import OCRDatabase
        from app.ocr.repository import OCRRepository
        from app.image_facts.provider import make_facts_provider
        from app.image_facts.repository import ImageFactsRepository
        from app.image_facts.service import make_facts_service

        database = OCRDatabase().open()
        images = OCRRepository(database)
        facts = ImageFactsRepository(database)
        vision = make_facts_provider()
        service = make_facts_service(facts, images, vision=vision)
        owned["database"] = database
        owned["service"] = service
        owned["images"] = images
        return service, images

    def on_close() -> None:
        database = owned.pop("database", None)
        if database is not None:
            database.close()
        owned.clear()

    return ProgressiveFactsIndexer(service_factory=factory, on_close=on_close)
