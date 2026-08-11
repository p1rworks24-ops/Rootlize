"""Asynchronous bridge from the Images page to the unified search API."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRRecordNotFoundError
from app.ocr.repository import OCRRepository

SearchCandidate = tuple[Path, tuple[str, ...]]
SearchProvider = Callable[[str, Path, Sequence[SearchCandidate]], tuple[Path, ...]]


def search_indexed_images(
    query: str,
    folder: Path,
    candidates: Sequence[SearchCandidate],
) -> tuple[Path, ...]:
    """Synchronize UI-owned filename/tag facts, then use the formal search API."""
    database = OCRDatabase().open()
    try:
        repository = OCRRepository(database)
        for path, tags in candidates:
            try:
                image = repository.get_image_by_path(path)
            except OCRRecordNotFoundError:
                stat = path.stat()
                image = repository.upsert_image(
                    path,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            repository.update_tags(image.image_id, list(tags))

        paths: list[Path] = []
        offset = 0
        while True:
            page = repository.search_images(
                query,
                folder_path=folder,
                limit=500,
                offset=offset,
            )
            paths.extend(Path(result.path) for result in page.results)
            offset += page.returned_count
            if offset >= page.total_count or not page.returned_count:
                break
        return tuple(paths)
    finally:
        database.close()


class SearchTaskSignals(QObject):
    finished = Signal(int, str, str, object, object)


class ImagesSearchTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        query: str,
        folder: Path,
        candidates: Sequence[SearchCandidate],
        provider: SearchProvider,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.query = query
        self.folder = folder
        self.candidates = tuple(candidates)
        self.provider = provider
        self.signals = SearchTaskSignals()

    def run(self) -> None:
        try:
            paths = self.provider(self.query, self.folder, self.candidates)
            self.signals.finished.emit(
                self.request_id, self.query, str(self.folder.resolve()), paths, None
            )
        except Exception as exc:  # Delivered to the UI as a generic search error.
            self.signals.finished.emit(
                self.request_id, self.query, str(self.folder.resolve()), (), exc
            )
