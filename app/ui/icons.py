"""Windows Fluent / Segoe MDL2 style icons for navigation and chrome."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor, QFontInfo
from PySide6.QtWidgets import QApplication, QStyle

# Segoe Fluent Icons / MDL2 Assets code points (Windows)
_GLYPH_HOME = "\uE80F"
_GLYPH_IMAGE = "\uEB9F"
_GLYPH_TAG = "\uE8EC"
_GLYPH_SETTINGS = "\uE713"
_GLYPH_FOLDER = "\uE8B7"
_GLYPH_CAMERA = "\uE722"
_GLYPH_SAVE = "\uE74E"
_GLYPH_REFRESH = "\uE72C"
_GLYPH_SEARCH = "\uE721"
_GLYPH_CLEAR = "\uE711"
_GLYPH_NEW_FOLDER = "\uE8F4"
_GLYPH_OPEN = "\uE8A7"
_GLYPH_ADD = "\uE710"
_GLYPH_ACTION = "\uE8FD"  # Switch / organize
_GLYPH_WORK = "\uE8FD"  # alias for Organize
_GLYPH_AI = "\uE99A"  # Robot / AI-like glyph (Fluent)


def _fluent_font(pixel_size: int) -> QFont:
    for family in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        font = QFont(family)
        font.setPixelSize(pixel_size)
        if QFontInfo(font).family() == family:
            return font
    font = QFont()
    font.setPixelSize(pixel_size)
    return font


def fluent_icon(
    glyph: str,
    *,
    size: int = 20,
    color: str | QColor = "#374151",
) -> QIcon:
    """Render a Fluent glyph into a QIcon (falls back to empty if font missing)."""
    if isinstance(color, str):
        color = QColor(color)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setFont(_fluent_font(max(size - 2, 12)))
    painter.setPen(color)
    painter.drawText(pix.rect(), Qt.AlignCenter, glyph)
    painter.end()
    return QIcon(pix)


def std_icon(pixmap: QStyle.StandardPixmap) -> QIcon:
    style = QApplication.style()
    if style is None:
        return QIcon()
    return style.standardIcon(pixmap)


def icon_home() -> QIcon:
    return fluent_icon(_GLYPH_HOME, color="#2563eb")


def icon_images() -> QIcon:
    return fluent_icon(_GLYPH_IMAGE, color="#2563eb")


def icon_work() -> QIcon:
    return icon_action()


def icon_action() -> QIcon:
    """Organize page — modern flash / switch glyph."""
    return fluent_icon(_GLYPH_ACTION, color="#2563eb")


def icon_organize() -> QIcon:
    return icon_action()


def icon_tags() -> QIcon:
    return fluent_icon(_GLYPH_TAG, color="#2563eb")


def icon_ai(*, muted: bool = True) -> QIcon:
    """AI nav placeholder — muted until the feature ships."""
    color = "#9ca3af" if muted else "#2563eb"
    return fluent_icon(_GLYPH_AI, color=color)


def icon_settings() -> QIcon:
    return fluent_icon(_GLYPH_SETTINGS, color="#2563eb")


def icon_screenshot() -> QIcon:
    return fluent_icon(_GLYPH_CAMERA, size=18, color="#ffffff")


def icon_refresh() -> QIcon:
    return fluent_icon(_GLYPH_REFRESH, size=16)


def icon_search() -> QIcon:
    return fluent_icon(_GLYPH_SEARCH, size=16)


def icon_clear() -> QIcon:
    return fluent_icon(_GLYPH_CLEAR, size=16)


def icon_new_folder() -> QIcon:
    """
    Win11 / Fluent-style 'new folder' (folder + plus badge).

    Qt's SP_FileDialogNewFolder often looks dated, so we paint a modern glyph.
    """
    size = 16
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # Folder glyph
    painter.setPen(QColor("#475569"))
    painter.setFont(_fluent_font(13))
    painter.drawText(QRect(0, 0, 12, size), Qt.AlignCenter, _GLYPH_FOLDER)

    # Small plus badge (Fluent accent)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(8, 8, 8, 8)
    painter.setPen(QColor("#ffffff"))
    plus_font = QFont()
    plus_font.setPixelSize(8)
    plus_font.setBold(True)
    painter.setFont(plus_font)
    painter.drawText(QRect(8, 8, 8, 8), Qt.AlignCenter, "+")
    painter.end()
    return QIcon(pix)


def icon_folder() -> QIcon:
    return fluent_icon(_GLYPH_FOLDER, size=16, color="#6b7280")


def icon_region_capture() -> QIcon:
    """Region / crop-style capture (white on green button)."""
    return fluent_icon(_GLYPH_IMAGE, size=16, color="#ffffff")


def icon_fullscreen_capture() -> QIcon:
    """Full-screen capture (white on blue button)."""
    return fluent_icon(_GLYPH_CAMERA, size=16, color="#ffffff")


def icon_capture_mode_cycle() -> QIcon:
    """Cycle / switch capture mode (refresh-style arrows)."""
    return fluent_icon(_GLYPH_REFRESH, size=16, color="#475569")


def icon_save_folder_star(*, size: int = 14) -> QIcon:
    """Blue star marking the Screenshot save-folder target."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QColor("#2563eb"))
    font = QFont()
    font.setPixelSize(max(size - 1, 10))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "★")
    painter.end()
    return QIcon(pix)


def icon_preview() -> QIcon:
    return fluent_icon(_GLYPH_IMAGE, size=14)


def icon_save() -> QIcon:
    return fluent_icon(_GLYPH_SAVE, size=16)


def icon_add() -> QIcon:
    return fluent_icon(_GLYPH_ADD, size=16)


def icon_open() -> QIcon:
    return fluent_icon(_GLYPH_OPEN, size=16)


def icon_project() -> QIcon:
    """Project (work unit) — blue folder accent."""
    return fluent_icon(_GLYPH_FOLDER, size=16, color="#1d4ed8")


def project_tree_icon(*, selected: bool) -> QIcon:
    """Composite '▶ + folder' icon for a Folder Tree row under the current Project."""
    width, height = 34, 16
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)

    marker_color = QColor("#047857") if selected else QColor("#9ca3af")
    painter.setPen(marker_color)
    marker_font = QFont()
    marker_font.setPixelSize(10)
    marker_font.setBold(True)
    painter.setFont(marker_font)
    marker = "▶" if selected else "·"
    painter.drawText(QRect(0, 0, 12, height), Qt.AlignCenter, marker)

    folder = fluent_icon(
        _GLYPH_FOLDER,
        size=14,
        color="#047857" if selected else "#6b7280",
    ).pixmap(14, 14)
    painter.drawPixmap(14, 1, folder)
    painter.end()
    return QIcon(pix)
