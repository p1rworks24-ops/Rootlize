"""Windows Fluent / Segoe MDL2 style icons for navigation and chrome."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRect, QPointF
from PySide6.QtGui import (
    QIcon,
    QPixmap,
    QPainter,
    QFont,
    QColor,
    QFontInfo,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QStyle

from app.ui.design_tokens import (
    FAVORITE_STAR_CHECKED,
    FAVORITE_STAR_CHECKED_SOFT,
    FAVORITE_STAR_UNCHECKED,
    FAVORITE_STAR_UNCHECKED_HOVER,
)

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
_GLYPH_PLAY = "\uE768"
_GLYPH_WORK = "\uE8FD"  # alias for Organize
_GLYPH_AI = "\uE99A"  # Robot / AI-like glyph (Fluent)
_GLYPH_RECENT = "\uE81C"
_GLYPH_CONTACT = "\uE77B"  # Person / account
_GLYPH_NOTIFICATION = "\uEA8F"  # Ringer
_GLYPH_CHEVRON_DOWN = "\uE70D"
_GLYPH_CHEVRON_UP = "\uE70E"
_GLYPH_CHEVRON_LEFT = "\uE76B"
_GLYPH_CHEVRON_RIGHT = "\uE76C"
_GLYPH_UP = "\uE74A"
_GLYPH_BACK = "\uE72B"
_GLYPH_EDIT = "\uE70F"
_GLYPH_RENAME = "\uE8AC"
_GLYPH_TRASH = "\uE74D"
_GLYPH_CLOCK = "\uE823"
_GLYPH_LIGHTNING = "\uEA6C"
_GLYPH_REMOVE = "\uE738"
_GLYPH_PIN = "\uE718"
_GLYPH_PIN_FILL = "\uE840"
_GLYPH_MOVE = "\uE8DE"
_GLYPH_STAR = "\uE734"
_GLYPH_STAR_FILL = "\uE735"
_GLYPH_POWER = "\uE7E8"
_GLYPH_CALENDAR = "\uE787"
_GLYPH_DOCUMENT = "\uE8A5"
_GLYPH_COPY = "\uE8C8"
_GLYPH_COLOR = "\uE790"
_GLYPH_CHECK = "\uE73E"
_GLYPH_FULLSCREEN = "\uE740"
_GLYPH_SHARE = "\uE72D"
_GLYPH_ZIP = "\uE88B"
_GLYPH_SWITCH = "\uE8AB"
_GLYPH_WARNING = "\uE7BA"
_GLYPH_INFO_GLYPH = "\uE946"


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


# Nav glyphs share one charcoal ink. Selected state is the surface, not the icon.
NAV_INK = "#3d4450"
NAV_COLOR_HOME = NAV_INK
NAV_COLOR_IMAGES = NAV_INK
NAV_COLOR_FAVORITES = "#5c6470"
NAV_COLOR_RECENT = NAV_INK
NAV_COLOR_ORGANIZE = NAV_INK
NAV_COLOR_TAGS = NAV_INK
NAV_COLOR_SETTINGS = NAV_INK
NAV_COLOR_AUTOMATION = NAV_INK
NAV_COLOR_ABOUT = NAV_INK
NAV_COLOR_AI = "#6b7280"


def icon_home() -> QIcon:
    return fluent_icon(_GLYPH_HOME, color=NAV_COLOR_HOME)


def icon_images() -> QIcon:
    return fluent_icon(_GLYPH_IMAGE, color=NAV_COLOR_IMAGES)


def icon_search_nav() -> QIcon:
    return fluent_icon(_GLYPH_SEARCH, color=NAV_COLOR_IMAGES)


FAVORITE_STAR_GOLD = QColor(FAVORITE_STAR_CHECKED)
FAVORITE_STAR_GOLD_SOFT = QColor(*FAVORITE_STAR_CHECKED_SOFT)
FAVORITE_STAR_OUTLINE = QColor(FAVORITE_STAR_UNCHECKED)
FAVORITE_STAR_OUTLINE_HOVER = QColor(FAVORITE_STAR_UNCHECKED_HOVER)
FAVORITE_STAR_FILL = FAVORITE_STAR_GOLD


def paint_favorite_star(
    painter: QPainter,
    dest: QRect,
    *,
    filled: bool = True,
    hovered: bool = False,
    with_plate: bool = False,
) -> None:
    """Gold fill when favorited; muted outline when not. Shared by Grid and List."""
    if dest.width() < 8 or dest.height() < 8:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    side = min(dest.width(), dest.height())
    cx = dest.x() + dest.width() / 2
    cy = dest.y() + dest.height() / 2 + side * 0.04
    if with_plate and filled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(FAVORITE_STAR_GOLD_SOFT)
        radius = max(8, int(side * 0.62))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
    path = _star_path(cx, cy, side * 0.42, side * 0.18)
    if filled:
        painter.setPen(Qt.NoPen)
        painter.setBrush(FAVORITE_STAR_GOLD)
    else:
        outline = FAVORITE_STAR_OUTLINE_HOVER if hovered else FAVORITE_STAR_OUTLINE
        painter.setPen(
            QPen(
                outline,
                max(1.2, side * 0.09),
                Qt.SolidLine,
                Qt.RoundCap,
                Qt.RoundJoin,
            )
        )
        painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def favorite_star_pixmap(*, size: int = 16, filled: bool = True) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    paint_favorite_star(painter, QRect(0, 0, size, size), filled=filled)
    painter.end()
    return pix


def icon_favorite(*, filled: bool = False, color: str | None = None) -> QIcon:
    del color
    return QIcon(favorite_star_pixmap(size=16, filled=filled))


PIN_INK = QColor("#3d4450")
PIN_MUTED = QColor("#94a3b8")
PIN_ACTIVE = QColor("#3b5bdb")


def pin_pixmap(*, size: int = 16, filled: bool = True) -> QPixmap:
    side = max(12, int(size))
    color = PIN_ACTIVE if filled else PIN_MUTED
    glyph = _GLYPH_PIN_FILL if filled else _GLYPH_PIN
    return fluent_icon(glyph, size=side, color=color).pixmap(side, side)


def icon_pin(*, filled: bool = False, size: int = 16, color: str | None = None) -> QIcon:
    if color:
        glyph = _GLYPH_PIN_FILL if filled else _GLYPH_PIN
        return fluent_icon(glyph, size=size, color=color)
    return QIcon(pin_pixmap(size=size, filled=filled))


def _star_path(cx: float, cy: float, outer_r: float, inner_r: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = outer_r if i % 2 == 0 else inner_r
        point = QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        if i == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def icon_recent() -> QIcon:
    return fluent_icon(_GLYPH_RECENT, color=NAV_COLOR_RECENT)


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
    """AI glyph. Active actions use charcoal; placeholders stay muted."""
    color = NAV_COLOR_AI if muted else "#1c1f26"
    return fluent_icon(_GLYPH_AI, color=color)


def icon_find_images(*, size: int = 20, color: str = "#3b6ea8") -> QIcon:
    """Image + magnifying glass, using the same Fluent glyphs as Search."""
    side = max(16, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    image = fluent_icon(_GLYPH_IMAGE, size=max(12, int(side * 0.78)), color=color)
    search = fluent_icon(_GLYPH_SEARCH, size=max(11, int(side * 0.62)), color=color)
    image_pix = image.pixmap(max(12, int(side * 0.78)), max(12, int(side * 0.78)))
    search_pix = search.pixmap(max(11, int(side * 0.62)), max(11, int(side * 0.62)))
    painter.drawPixmap(0, side - image_pix.height(), image_pix)
    painter.drawPixmap(side - search_pix.width(), 0, search_pix)
    painter.end()
    return QIcon(pix)


def icon_organize_images(*, size: int = 20, color: str = "#6f84a3") -> QIcon:
    """Folder + image, using the same Fluent glyphs as Folders / Images."""
    side = max(16, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    folder = fluent_icon(_GLYPH_FOLDER, size=side, color=color)
    image = fluent_icon(_GLYPH_IMAGE, size=max(8, int(side * 0.46)), color=color)
    folder_pix = folder.pixmap(side, side)
    image_pix = image.pixmap(max(8, int(side * 0.46)), max(8, int(side * 0.46)))
    painter.drawPixmap(0, 0, folder_pix)
    painter.drawPixmap(side - image_pix.width() - 1, side - image_pix.height() - 1, image_pix)
    painter.end()
    return QIcon(pix)


def icon_ai_sparkle(*, size: int = 14, color: str = "#f8f9fb") -> QIcon:
    """Small four-point sparkle for Ask AI — quiet, not a purple badge."""
    from PySide6.QtGui import QPainterPath

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    ink = QColor(color)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    cx = size / 2
    cy = size / 2
    major = size * 0.42
    minor = size * 0.14

    def spark(cx_, cy_, major_, minor_):
        path = QPainterPath()
        path.moveTo(cx_, cy_ - major_)
        path.lineTo(cx_ + minor_, cy_)
        path.lineTo(cx_, cy_ + major_)
        path.lineTo(cx_ - minor_, cy_)
        path.closeSubpath()
        path.moveTo(cx_ - major_, cy_)
        path.lineTo(cx_, cy_ - minor_)
        path.lineTo(cx_ + major_, cy_)
        path.lineTo(cx_, cy_ + minor_)
        path.closeSubpath()
        painter.drawPath(path)

    spark(cx - size * 0.08, cy, major, minor)
    painter.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 170))
    spark(cx + size * 0.28, cy - size * 0.22, major * 0.42, minor * 0.42)
    painter.end()
    return QIcon(pix)


def icon_analyze() -> QIcon:
    """Image-analysis action glyph."""
    return fluent_icon(_GLYPH_AI, size=16, color="#1c1f26")


def icon_automation() -> QIcon:
    return fluent_icon(_GLYPH_PLAY, color=NAV_COLOR_AUTOMATION)


def icon_settings() -> QIcon:
    return fluent_icon(_GLYPH_SETTINGS, color=NAV_COLOR_SETTINGS)


def icon_about() -> QIcon:
    return fluent_icon(_GLYPH_INFO, color=NAV_COLOR_ABOUT)


def icon_test_user() -> QIcon:
    """Prototype account avatar used by the local test-user footer."""
    return fluent_icon(_GLYPH_CONTACT, size=24, color="#3d4450")


def icon_notification(*, size: int = 18) -> QIcon:
    return fluent_icon(_GLYPH_NOTIFICATION, size=size, color=NAV_INK)


def icon_capture_nav(*, size: int = 18) -> QIcon:
    """Camera glyph for the Capture utility nav action."""
    return fluent_icon(_GLYPH_CAMERA, size=size, color=NAV_INK)


def icon_user(*, size: int = 18) -> QIcon:
    return fluent_icon(_GLYPH_CONTACT, size=size, color=NAV_INK)


def icon_collapse_capture() -> QIcon:
    return fluent_icon(_GLYPH_CHEVRON_DOWN, size=14, color="#475569")


def icon_expand_capture() -> QIcon:
    return fluent_icon(_GLYPH_CHEVRON_UP, size=14, color="#475569")


def icon_collapse_nav() -> QIcon:
    return fluent_icon(_GLYPH_CHEVRON_LEFT, size=16, color="#475569")


def icon_expand_nav() -> QIcon:
    return fluent_icon(_GLYPH_CHEVRON_RIGHT, size=16, color="#475569")


def icon_disclosure(*, expanded: bool, size: int = 12, color: str = "#6B7280") -> QIcon:
    """Small chevron for nested nav sections (favorites under Images)."""
    glyph = _GLYPH_CHEVRON_DOWN if expanded else _GLYPH_CHEVRON_RIGHT
    return fluent_icon(glyph, size=size, color=color)


def icon_screenshot() -> QIcon:
    return fluent_icon(_GLYPH_CAMERA, size=18, color="#ffffff")


def icon_refresh() -> QIcon:
    return fluent_icon(_GLYPH_REFRESH, size=16)


def icon_search() -> QIcon:
    return fluent_icon(_GLYPH_SEARCH, size=16)


def icon_clear() -> QIcon:
    return fluent_icon(_GLYPH_CLEAR, size=16)


def icon_send_up(*, size: int = 16, color: str = "#f8f9fb") -> QIcon:
    """Up-arrow send glyph for the Ask AI composer."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.6, size * 0.14))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    cx = size / 2
    top = size * 0.20
    bot = size * 0.80
    painter.drawLine(QPointF(cx, bot), QPointF(cx, top))
    head = size * 0.24
    path = QPainterPath()
    path.moveTo(cx - head, top + head)
    path.lineTo(cx, top)
    path.lineTo(cx + head, top + head)
    painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def icon_edit(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_EDIT, size=size, color=color)


def icon_rename(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_RENAME, size=size, color=color)


def icon_clock(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_CLOCK, size=size, color=color)


def icon_lightning(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_LIGHTNING, size=size, color=color)


def icon_move(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_MOVE, size=size, color=color)


def icon_stacked_folders(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    back = fluent_icon(_GLYPH_FOLDER, size=max(11, int(side * 0.78)), color=QColor(color).lighter(130).name())
    front = fluent_icon(_GLYPH_FOLDER, size=max(12, int(side * 0.82)), color=color)
    back_pix = back.pixmap(max(11, int(side * 0.78)), max(11, int(side * 0.78)))
    front_pix = front.pixmap(max(12, int(side * 0.82)), max(12, int(side * 0.82)))
    painter.drawPixmap(2, 0, back_pix)
    painter.drawPixmap(0, side - front_pix.height(), front_pix)
    painter.end()
    return QIcon(pix)


def icon_current_folder(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    folder = fluent_icon(_GLYPH_FOLDER, size=side, color=color)
    pin = fluent_icon(_GLYPH_PIN, size=max(8, int(side * 0.52)), color=color)
    painter.drawPixmap(0, 0, folder.pixmap(side, side))
    pin_pix = pin.pixmap(max(8, int(side * 0.52)), max(8, int(side * 0.52)))
    painter.drawPixmap(side - pin_pix.width(), 0, pin_pix)
    painter.end()
    return QIcon(pix)


def icon_meaning_search(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    search = fluent_icon(_GLYPH_SEARCH, size=max(12, int(side * 0.82)), color=color)
    painter.drawPixmap(0, side - search.pixmap(side, side).height(), search.pixmap(max(12, int(side * 0.82)), max(12, int(side * 0.82))))
    spark = icon_ai_sparkle(size=max(7, int(side * 0.46)), color=color)
    spark_pix = spark.pixmap(max(7, int(side * 0.46)), max(7, int(side * 0.46)))
    painter.drawPixmap(side - spark_pix.width(), 0, spark_pix)
    painter.end()
    return QIcon(pix)


def icon_folder_move(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    folder = fluent_icon(_GLYPH_FOLDER, size=max(12, int(side * 0.78)), color=color)
    folder_pix = folder.pixmap(max(12, int(side * 0.78)), max(12, int(side * 0.78)))
    painter.drawPixmap(0, max(0, (side - folder_pix.height()) // 2), folder_pix)
    pen = QPen(QColor(color), max(1.3, side * 0.10))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    y = side * 0.52
    painter.drawLine(QPointF(side * 0.42, y), QPointF(side * 0.92, y))
    head = side * 0.16
    path = QPainterPath()
    path.moveTo(side * 0.92 - head, y - head * 0.7)
    path.lineTo(side * 0.92, y)
    path.lineTo(side * 0.92 - head, y + head * 0.7)
    painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def icon_tag_plus(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return _icon_tag_badge(size=size, color=color, mark="+")


def icon_tag_minus(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return _icon_tag_badge(size=size, color=color, mark="-")


def _icon_tag_badge(*, size: int, color: str, mark: str) -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    tag = fluent_icon(_GLYPH_TAG, size=max(12, int(side * 0.82)), color=color)
    painter.drawPixmap(0, max(0, (side - tag.pixmap(side, side).height()) // 2), tag.pixmap(max(12, int(side * 0.82)), max(12, int(side * 0.82))))
    badge = max(7, int(side * 0.46))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(side - badge, side - badge, badge, badge)
    painter.setPen(QColor("#ffffff"))
    mark_font = QFont()
    mark_font.setPixelSize(max(7, badge - 1))
    mark_font.setBold(True)
    painter.setFont(mark_font)
    painter.drawText(QRect(side - badge, side - badge, badge, badge), Qt.AlignCenter, mark)
    painter.end()
    return QIcon(pix)


def _icon_with_corner(base: QIcon, badge: QIcon, *, size: int) -> QIcon:
    side = max(14, int(size))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)
    base_pix = base.pixmap(max(12, int(side * 0.82)), max(12, int(side * 0.82)))
    painter.drawPixmap(0, max(0, (side - base_pix.height()) // 2), base_pix)
    badge_side = max(7, int(side * 0.48))
    badge_pix = badge.pixmap(badge_side, badge_side)
    painter.drawPixmap(side - badge_pix.width(), side - badge_pix.height(), badge_pix)
    painter.end()
    return QIcon(pix)


def catalog_icon(icon_key: str, *, size: int = 16, color: str = "#6b7280") -> QIcon:
    """Function-first icons for Add Block and Inspector. No emoji."""
    key = str(icon_key or "").strip()
    if key == "folder":
        return icon_folder(color=color, size=size)
    if key == "folders":
        return icon_stacked_folders(size=size, color=color)
    if key == "current_folder":
        return icon_current_folder(size=size, color=color)
    if key == "images":
        return fluent_icon(_GLYPH_IMAGE, size=size, color=color)
    if key == "text_search":
        return icon_text_glyph(size=size, color=color)
    if key == "meaning_search":
        return icon_meaning_search(size=size, color=color)
    if key == "move":
        return icon_folder_move(size=size, color=color)
    if key == "rename":
        return icon_edit(size=size, color=color)
    if key == "add_tag":
        return icon_tag_plus(size=size, color=color)
    if key == "remove_tag":
        return icon_tag_minus(size=size, color=color)
    if key == "create_folder":
        return fluent_icon(_GLYPH_NEW_FOLDER, size=size, color=color)
    if key == "event":
        return icon_lightning(size=size, color=color)
    if key == "time" or key == "clock":
        return icon_clock(size=size, color=color)
    if key == "logic":
        return fluent_icon(_GLYPH_ACTION, size=size, color=color)
    if key == "ai":
        return fluent_icon(_GLYPH_AI, size=size, color=color)
    if key == "settings":
        return fluent_icon(_GLYPH_SETTINGS, size=size, color=color)
    if key == "play":
        return fluent_icon(_GLYPH_PLAY, size=size, color=color)
    if key == "power":
        return fluent_icon(_GLYPH_POWER, size=size, color=color)
    if key == "calendar":
        return fluent_icon(_GLYPH_CALENDAR, size=size, color=color)
    if key == "calendar_range":
        return _icon_with_corner(
            fluent_icon(_GLYPH_CALENDAR, size=size, color=color),
            fluent_icon(_GLYPH_CALENDAR, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "file":
        return fluent_icon(_GLYPH_DOCUMENT, size=size, color=color)
    if key == "file_plus":
        return _icon_with_corner(
            fluent_icon(_GLYPH_DOCUMENT, size=size, color=color),
            fluent_icon(_GLYPH_ADD, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "folder_refresh":
        return _icon_with_corner(
            fluent_icon(_GLYPH_FOLDER, size=size, color=color),
            fluent_icon(_GLYPH_REFRESH, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "star":
        return fluent_icon(_GLYPH_STAR_FILL, size=size, color=color)
    if key == "star_off":
        return fluent_icon(_GLYPH_STAR, size=size, color=color)
    if key == "tag":
        return fluent_icon(_GLYPH_TAG, size=size, color=color)
    if key == "clock_plus":
        return _icon_with_corner(
            icon_clock(size=size, color=color),
            fluent_icon(_GLYPH_ADD, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "clock_edit":
        return _icon_with_corner(
            icon_clock(size=size, color=color),
            icon_edit(size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "dimensions":
        return fluent_icon(_GLYPH_FULLSCREEN, size=size, color=color)
    if key == "unorganized":
        return _icon_with_corner(
            fluent_icon(_GLYPH_IMAGE, size=size, color=color),
            fluent_icon(_GLYPH_WARNING, size=max(8, int(size * 0.48)), color=color),
            size=size,
        )
    if key == "copy":
        return fluent_icon(_GLYPH_COPY, size=size, color=color)
    if key == "similar":
        return _icon_with_corner(
            fluent_icon(_GLYPH_IMAGE, size=size, color=color),
            fluent_icon(_GLYPH_SEARCH, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "color":
        return fluent_icon(_GLYPH_COLOR, size=size, color=color)
    if key == "metadata":
        return fluent_icon(_GLYPH_INFO_GLYPH, size=size, color=color)
    if key == "ai_check":
        return _icon_with_corner(
            fluent_icon(_GLYPH_AI, size=size, color=color),
            fluent_icon(_GLYPH_CHECK, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "count":
        return _icon_with_corner(
            fluent_icon(_GLYPH_IMAGE, size=size, color=color),
            fluent_icon(_GLYPH_ADD, size=max(8, int(size * 0.5)), color=color),
            size=size,
        )
    if key == "export":
        return fluent_icon(_GLYPH_SHARE, size=size, color=color)
    if key == "delete":
        return icon_trash(size=size, color=color)
    if key == "compress":
        return fluent_icon(_GLYPH_ZIP, size=size, color=color)
    if key == "convert":
        return fluent_icon(_GLYPH_SWITCH, size=size, color=color)
    if key == "tag_ai":
        return _icon_with_corner(
            fluent_icon(_GLYPH_TAG, size=size, color=color),
            icon_ai_sparkle(size=max(7, int(size * 0.46)), color=color),
            size=size,
        )
    if key == "edit_ai":
        return _icon_with_corner(
            icon_edit(size=size, color=color),
            icon_ai_sparkle(size=max(7, int(size * 0.46)), color=color),
            size=size,
        )
    return fluent_icon(_GLYPH_FOLDER, size=size, color=color)


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
    painter.setPen(QColor("#3d4450"))
    painter.setFont(_fluent_font(13))
    painter.drawText(QRect(0, 0, 12, size), Qt.AlignCenter, _GLYPH_FOLDER)

    # Small plus badge (Fluent accent)
    painter.setBrush(QColor("#1c1f26"))
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


def icon_folder(*, color: str = "#6b7280", size: int = 16) -> QIcon:
    return fluent_icon(_GLYPH_FOLDER, size=size, color=color)


def paint_folder_glyph(painter: QPainter, dest: QRect) -> None:
    """Clean slate-blue folder used in the image grid (not a yellow Explorer glyph)."""
    if dest.width() < 8 or dest.height() < 8:
        return
    size = min(dest.width(), dest.height())
    box = QRect(
        dest.center().x() - size // 2,
        dest.center().y() - size // 2,
        size,
        size,
    )
    radius = max(2.0, size * 0.10)
    tab = QRect(
        box.x() + int(size * 0.12),
        box.y() + int(size * 0.14),
        max(6, int(size * 0.40)),
        max(4, int(size * 0.22)),
    )
    body = QRect(
        box.x() + int(size * 0.08),
        box.y() + int(size * 0.26),
        max(8, int(size * 0.84)),
        max(6, int(size * 0.58)),
    )
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(70, 82, 104, 36))
    painter.drawRoundedRect(body.adjusted(1, 2, 1, 2), radius, radius)
    painter.setBrush(QColor("#8ea0bc"))
    painter.drawRoundedRect(tab, radius * 0.7, radius * 0.7)
    painter.setBrush(QColor("#6f84a3"))
    painter.drawRoundedRect(body, radius, radius)
    inner = body.adjusted(
        max(2, int(size * 0.08)),
        max(2, int(size * 0.12)),
        -max(2, int(size * 0.08)),
        -max(2, int(size * 0.10)),
    )
    if inner.width() > 4 and inner.height() > 4:
        painter.setBrush(QColor("#e7edf5"))
        painter.drawRoundedRect(inner, max(1.4, radius * 0.45), max(1.4, radius * 0.45))


def icon_folder_fill(*, size: int = 16, color: str | None = None) -> QIcon:
    """Filled folder for gallery items. `color` is ignored; the glyph is painted."""
    del color
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    paint_folder_glyph(painter, QRect(0, 0, size, size))
    painter.end()
    return QIcon(pix)


def icon_folder_up(*, color: str = "#4a5160", size: int = 16) -> QIcon:
    """Parent-folder control used at the top of the image grid."""
    return fluent_icon(_GLYPH_UP, size=size, color=color)


def icon_back(*, color: str = "#4a5160", size: int = 16) -> QIcon:
    """Explorer-style back chevron for folder history."""
    return fluent_icon(_GLYPH_BACK, size=size, color=color)


def icon_region_capture(*, color: str = "#ffffff") -> QIcon:
    """Region / crop-style capture with context-appropriate foreground."""
    return fluent_icon(_GLYPH_IMAGE, size=16, color=color)


def icon_fullscreen_capture(*, color: str = "#ffffff") -> QIcon:
    """Full-screen camera glyph with context-appropriate foreground."""
    return fluent_icon(_GLYPH_CAMERA, size=16, color=color)


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
    painter.setPen(QColor("#1c1f26"))
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


def icon_add(*, size: int = 16, color: str = "#2563eb") -> QIcon:
    return fluent_icon(_GLYPH_ADD, size=size, color=color)


def icon_play(*, size: int = 16, color: str = "#ffffff") -> QIcon:
    return fluent_icon(_GLYPH_PLAY, size=size, color=color)


def icon_delete(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_REMOVE, size=size, color=color)


def icon_trash(*, size: int = 16, color: str = "#6b7280") -> QIcon:
    return fluent_icon(_GLYPH_TRASH, size=size, color=color)


def icon_info(*, size: int = 16, color: str = "#6d28d9") -> QIcon:
    return fluent_icon(_GLYPH_INFO, size=size, color=color)


def icon_align(*, size: int = 16, color: str = "#4a5160") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), max(1.4, size * 0.12))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    left = size * 0.18
    for y_ratio, right_ratio in ((0.28, 0.82), (0.5, 0.68), (0.72, 0.82)):
        painter.drawLine(QPointF(left, size * y_ratio), QPointF(size * right_ratio, size * y_ratio))
    painter.end()
    return QIcon(pix)


def icon_fit(*, size: int = 16, color: str = "#4a5160") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), max(1.3, size * 0.11))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    m = size * 0.22
    arm = size * 0.22
    for x, y, dx, dy in (
        (m, m, arm, 0),
        (m, m, 0, arm),
        (size - m, m, -arm, 0),
        (size - m, m, 0, arm),
        (m, size - m, arm, 0),
        (m, size - m, 0, -arm),
        (size - m, size - m, -arm, 0),
        (size - m, size - m, 0, -arm),
    ):
        painter.drawLine(QPointF(x, y), QPointF(x + dx, y + dy))
    painter.end()
    return QIcon(pix)


def icon_text_glyph(*, size: int = 16, color: str = "#2563eb") -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    font = QFont("Segoe UI")
    font.setPixelSize(max(11, size - 3))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pix.rect(), Qt.AlignCenter, "T")
    painter.end()
    return QIcon(pix)


def icon_open() -> QIcon:
    return fluent_icon(_GLYPH_OPEN, size=16)


def icon_layout_grid(*, size: int = 16, color: str = "#3d4450") -> QIcon:
    """2x2 tile glyph for Grid view."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    gap = max(2, size // 6)
    tile = max(3, (size - gap - 4) // 2)
    origin = 2
    for row in range(2):
        for col in range(2):
            painter.drawRoundedRect(
                origin + col * (tile + gap),
                origin + row * (tile + gap),
                tile,
                tile,
                1.5,
                1.5,
            )
    painter.end()
    return QIcon(pix)


def icon_layout_list(*, size: int = 16, color: str = "#3d4450") -> QIcon:
    """Three-line glyph for List view."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    from PySide6.QtGui import QPen

    pen = QPen(QColor(color), max(1.4, size * 0.12))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    left = 2
    right = size - 3
    for y_ratio in (0.28, 0.5, 0.72):
        y = int(size * y_ratio)
        painter.drawLine(left, y, right, y)
    painter.end()
    return QIcon(pix)


def icon_capture_panel() -> QIcon:
    """Pop-up window glyph for opening the floating Capture Panel."""
    return fluent_icon(_GLYPH_OPEN, size=20, color="#1c1f26")


def icon_project() -> QIcon:
    """Project (work unit) — blue folder accent."""
    return fluent_icon(_GLYPH_FOLDER, size=16, color="#3d4450")


def project_tree_icon(*, selected: bool) -> QIcon:
    """Composite '▶ + folder' icon for a Folder Tree row under the current Project."""
    width, height = 34, 16
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.Antialiasing, True)

    marker_color = QColor("#1c1f26") if selected else QColor("#9aa0a8")
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
        color="#1c1f26" if selected else "#6b7280",
    ).pixmap(14, 14)
    painter.drawPixmap(14, 1, folder)
    painter.end()
    return QIcon(pix)
