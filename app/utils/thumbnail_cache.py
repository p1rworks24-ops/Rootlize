from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage, QImageReader, QPixmap

THUMBNAIL_SIZE = 128


class ThumbnailCache:
    """Cache thumbnail icons by file path, size, and modification time."""

    def __init__(self, size: int = THUMBNAIL_SIZE):
        self._size = size
        # key: "path::size" -> (mtime, QIcon)
        self._cache: dict[str, tuple[float, QIcon]] = {}

    def get_icon(
        self,
        file_path: Path,
        size: int | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> QIcon:
        """
        Return a cached thumbnail icon.

        Cover-crops into the requested canvas so mixed screenshot ratios stay aligned.
        Pass width/height (device pixels) to match the painted media box.
        """
        if width is not None and height is not None:
            canvas_w = max(1, int(width))
            canvas_h = max(1, int(height))
        else:
            icon_size = size if size is not None else self._size
            canvas_w = max(1, int(icon_size))
            canvas_h = max(1, int(icon_size * 3 / 4))
        path_str = str(file_path.resolve())
        cache_key = f"{path_str}::{canvas_w}x{canvas_h}"
        mtime = file_path.stat().st_mtime

        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        image = self._read_image(file_path)
        if image.isNull():
            icon = QIcon(self._empty_canvas(canvas_w, canvas_h))
        else:
            icon = QIcon(QPixmap.fromImage(self._cover_crop(image, canvas_w, canvas_h)))

        self._cache[cache_key] = (mtime, icon)
        return icon

    @staticmethod
    def _read_image(file_path: Path) -> QImage:
        reader = QImageReader(str(file_path))
        reader.setAutoTransform(True)
        return reader.read()

    @staticmethod
    def _empty_canvas(width: int, height: int | None = None) -> QPixmap:
        canvas = QPixmap(width, height if height is not None else width)
        canvas.fill(QColor(241, 245, 249))
        return canvas

    @staticmethod
    def _cover_crop(image: QImage, width: int, height: int) -> QImage:
        """Fill width×height by scaling up and cropping the overflow."""
        scaled = image.scaled(
            width,
            height,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = max(0, (scaled.width() - width) // 2)
        y = max(0, (scaled.height() - height) // 2)
        return scaled.copy(x, y, width, height)

    @staticmethod
    def _fit_to_square(pixmap: QPixmap, size: int) -> QPixmap:
        image = pixmap.toImage()
        return QPixmap.fromImage(ThumbnailCache._cover_crop(image, size, size))

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
