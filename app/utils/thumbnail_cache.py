from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor

THUMBNAIL_SIZE = 128


class ThumbnailCache:
    """Cache thumbnail icons by file path, size, and modification time."""

    def __init__(self, size: int = THUMBNAIL_SIZE):
        self._size = size
        # key: "path::size" -> (mtime, QIcon)
        self._cache: dict[str, tuple[float, QIcon]] = {}

    def get_icon(self, file_path: Path, size: int | None = None) -> QIcon:
        """
        Return a cached thumbnail icon.

        Always paints into a fixed size×size canvas so QListWidget cells stay
        aligned. Aspect ratio is preserved (letterboxed / pillarboxed).
        """
        icon_size = size if size is not None else self._size
        path_str = str(file_path.resolve())
        cache_key = f"{path_str}::{icon_size}"
        mtime = file_path.stat().st_mtime

        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            icon = QIcon(self._empty_canvas(icon_size))
        else:
            icon = QIcon(self._fit_to_square(pixmap, icon_size))

        self._cache[cache_key] = (mtime, icon)
        return icon

    @staticmethod
    def _empty_canvas(size: int) -> QPixmap:
        canvas = QPixmap(size, size)
        canvas.fill(Qt.transparent)
        return canvas

    @staticmethod
    def _fit_to_square(pixmap: QPixmap, size: int) -> QPixmap:
        """Scale pixmap to fit inside size×size without cropping; pad to square."""
        scaled = pixmap.scaled(
            size,
            size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        canvas = QPixmap(size, size)
        canvas.fill(QColor(243, 244, 246))  # light gray letterbox like Explorer
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        x = (size - scaled.width()) // 2
        y = (size - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return canvas

    def invalidate(self, file_path: Path) -> None:
        """Remove all cached sizes for one file."""
        path_str = str(file_path.resolve())
        prefix = f"{path_str}::"
        for key in list(self._cache.keys()):
            if key.startswith(prefix):
                self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached thumbnails (used when switching folders)."""
        self._cache.clear()
