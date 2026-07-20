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
_GLYPH_INFO = "\uE946"
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
    # Logical pixel size only — do not force HiDPI upscaling (clips in tight buttons).
    side = max(12, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    # Leave a little inset so MDL2 glyphs are not clipped at the edges.
    painter.setFont(_fluent_font(max(side - 4, 10)))
    painter.setPen(color)
    painter.drawText(pix.rect(), Qt.AlignCenter, glyph)
    painter.end()
    return QIcon(pix)


def std_icon(pixmap: QStyle.StandardPixmap) -> QIcon:
    style = QApplication.style()
    if style is None:
        return QIcon()
    return style.standardIcon(pixmap)


# Nav accent colors (associative, not all-blue)
NAV_COLOR_HOME = "#ea580c"  # warm home / dashboard
NAV_COLOR_IMAGES = "#0891b2"  # photos / media
NAV_COLOR_ORGANIZE = "#2563eb"  # select & act
NAV_COLOR_TAGS = "#db2777"  # labels
NAV_COLOR_SETTINGS = "#64748b"  # tools
NAV_COLOR_ABOUT = "#0f766e"  # brand / about
NAV_COLOR_AI = "#9ca3af"  # coming soon


def icon_home() -> QIcon:
    return fluent_icon(_GLYPH_HOME, color=NAV_COLOR_HOME)


def icon_images() -> QIcon:
    return fluent_icon(_GLYPH_IMAGE, color=NAV_COLOR_IMAGES)


def icon_work() -> QIcon:
    return icon_action()


def icon_action() -> QIcon:
    """Organize page — modern flash / switch glyph."""
    return fluent_icon(_GLYPH_ACTION, color=NAV_COLOR_ORGANIZE)


def icon_organize() -> QIcon:
    return icon_action()


def icon_tags() -> QIcon:
    return fluent_icon(_GLYPH_TAG, color=NAV_COLOR_TAGS)


def icon_ai(*, muted: bool = True) -> QIcon:
    """AI nav placeholder — muted until the feature ships."""
    color = NAV_COLOR_AI if muted else "#7c3aed"
    return fluent_icon(_GLYPH_AI, color=color)


def icon_settings() -> QIcon:
    return fluent_icon(_GLYPH_SETTINGS, color=NAV_COLOR_SETTINGS)


def icon_about() -> QIcon:
    return fluent_icon(_GLYPH_INFO, color=NAV_COLOR_ABOUT)


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


def icon_capture_mode_cycle(*, size: int = 16, color: str = "#334155") -> QIcon:
    """Modern mode-switch glyph: two opposing chevrons (swap)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPen, QBrush

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.6, size * 0.12))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    m = size * 0.18
    mid_y = size * 0.5
    top = size * 0.32
    painter.drawLine(QPointF(m, top), QPointF(size - m, top))
    path_r = QPainterPath()
    path_r.moveTo(size - m - size * 0.18, top - size * 0.14)
    path_r.lineTo(size - m, top)
    path_r.lineTo(size - m - size * 0.18, top + size * 0.14)
    painter.drawPath(path_r)
    bot = size * 0.68
    painter.drawLine(QPointF(size - m, bot), QPointF(m, bot))
    path_l = QPainterPath()
    path_l.moveTo(m + size * 0.18, bot - size * 0.14)
    path_l.lineTo(m, bot)
    path_l.lineTo(m + size * 0.18, bot + size * 0.14)
    painter.drawPath(path_l)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(color)))
    r = max(1.2, size * 0.07)
    painter.drawEllipse(QPointF(size * 0.5, mid_y), r, r)
    painter.end()
    return QIcon(pix)


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
