"""Official Rootlize application icon loading (window / taskbar / UI marks).

On-disk names stay capixe.ico / capixe_app_icon_*.png for internal compatibility.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

from app.paths import get_resource_root

# Relative to resource root (source tree or PyInstaller _MEIPASS)
_ICON_DIR = Path("resources") / "icons"
_ICO_NAME = "capixe.ico"
# Prefer largest masters for crisp downscales in UI
_MASTER_PNGS = (
    "capixe_app_icon_1024.png",
    "capixe_app_icon_512.png",
    "capixe_app_icon_256.png",
    "capixe_icon.png",
)


def app_icons_dir() -> Path:
    return get_resource_root() / _ICON_DIR


def app_ico_path() -> Path:
    return app_icons_dir() / _ICO_NAME


def app_png_path(size: int | None = None) -> Path:
    """Prefer an exact PNG size when available; else best high-res mark."""
    folder = app_icons_dir()
    if size is not None:
        exact = folder / f"capixe_app_icon_{int(size)}.png"
        if exact.is_file():
            return exact
    for name in _MASTER_PNGS:
        path = folder / name
        if path.is_file():
            return path
    return folder / "capixe_app_icon_256.png"


@lru_cache(maxsize=1)
def load_app_icon() -> QIcon:
    """Multi-resolution QIcon for window + taskbar."""
    icon = QIcon()
    ico = app_ico_path()
    if ico.is_file():
        icon.addFile(str(ico))
    # Ensure crisp UI pixmaps even if the shell picks a single ICO entry
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        png = app_icons_dir() / f"capixe_app_icon_{size}.png"
        if png.is_file():
            icon.addFile(str(png), QSize(size, size))
    if icon.isNull():
        png = app_png_path()
        if png.is_file():
            icon.addFile(str(png))
    return icon


def _device_pixel_ratio() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    if screen is None:
        return 1.0
    return max(float(screen.devicePixelRatio()), 1.0)


@lru_cache(maxsize=4)
def _load_master_pixmap() -> QPixmap:
    """Load the highest-resolution mark available (never a tiny pre-scaled PNG)."""
    folder = app_icons_dir()
    for name in _MASTER_PNGS:
        path = folder / name
        if path.is_file():
            pix = QPixmap(str(path))
            if not pix.isNull():
                return pix
    ico = app_ico_path()
    if ico.is_file():
        return QIcon(str(ico)).pixmap(256, 256)
    return QPixmap()


def app_mark_pixmap(size: int = 64) -> QPixmap:
    """
    Square brand mark for splash / About / sidebar.

    Always downscales from a high-res master and respects devicePixelRatio so
    HiDPI displays stay sharp (avoids loading 16–32px assets for UI marks).
    """
    side = max(12, int(size))
    master = _load_master_pixmap()
    if master.isNull():
        return master

    dpr = _device_pixel_ratio()
    pixel_side = max(side, int(round(side * dpr)))
    # Never upscale a smaller master beyond 2× its width (keep edges clean)
    if master.width() > 0 and pixel_side > master.width() * 2:
        pixel_side = master.width()

    pix = master.scaled(
        pixel_side,
        pixel_side,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    pix.setDevicePixelRatio(dpr)
    return pix
