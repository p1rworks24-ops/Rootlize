"""Screenshot capture modes — shared save path, pluggable triggers."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap


# Stable mode ids (extend later: active_window, scrolling, …)
CAPTURE_REGION = "region"
CAPTURE_FULLSCREEN = "fullscreen"


@dataclass(frozen=True)
class CaptureModeInfo:
    """Descriptor for a capture mode (single-button toolbar cycles these)."""

    mode_id: str
    label_key: str
    tooltip_key: str
    description_key: str
    # Object name applied to the single capture button for mode-colored styling
    button_object_name: str


# Registry order = cycle order. Add future modes here.
CAPTURE_MODES: tuple[CaptureModeInfo, ...] = (
    CaptureModeInfo(
        CAPTURE_REGION,
        "shell.capture.region",
        "shell.capture.region_tooltip",
        "shell.capture.region_desc",
        "regionCaptureButton",
    ),
    CaptureModeInfo(
        CAPTURE_FULLSCREEN,
        "shell.capture.fullscreen",
        "shell.capture.fullscreen_tooltip",
        "shell.capture.fullscreen_desc",
        "fullScreenCaptureButton",
    ),
)

_MODE_BY_ID = {m.mode_id: m for m in CAPTURE_MODES}


def normalize_capture_mode(mode: str | None) -> str:
    if mode and mode in _MODE_BY_ID:
        return mode
    return CAPTURE_MODES[0].mode_id


def capture_mode_info(mode: str | None) -> CaptureModeInfo:
    return _MODE_BY_ID[normalize_capture_mode(mode)]


def next_capture_mode(current: str | None) -> str:
    """Cycle to the next registered capture mode (wraps around)."""
    ids = [m.mode_id for m in CAPTURE_MODES]
    cur = normalize_capture_mode(current)
    return ids[(ids.index(cur) + 1) % len(ids)]


def grab_fullscreen_image() -> QImage | None:
    """
    Capture the virtual desktop (all monitors) as a QImage.

    Used by Full Screen Capture; Region Capture uses the OS snipping UI instead.
    """
    screens = QGuiApplication.screens()
    if not screens:
        return None

    if len(screens) == 1:
        pixmap = screens[0].grabWindow(0)
        if pixmap.isNull():
            return None
        return pixmap.toImage()

    left = min(s.geometry().x() for s in screens)
    top = min(s.geometry().y() for s in screens)
    right = max(s.geometry().x() + s.geometry().width() for s in screens)
    bottom = max(s.geometry().y() + s.geometry().height() for s in screens)
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return None

    canvas = QPixmap(width, height)
    canvas.fill(Qt.black)
    painter = QPainter(canvas)
    try:
        for screen in screens:
            part = screen.grabWindow(0)
            if part.isNull():
                continue
            geo = screen.geometry()
            painter.drawPixmap(geo.x() - left, geo.y() - top, part)
    finally:
        painter.end()

    if canvas.isNull():
        return None
    return canvas.toImage()


def default_region_trigger() -> bool:
    """Open Windows region snipping (Win+Shift+S)."""
    from app.utils.windows_hotkey import send_win_shift_s

    return send_win_shift_s()
