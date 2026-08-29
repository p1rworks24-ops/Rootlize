"""Custom list delegate: balanced icon cards + subtle group headers."""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent, QPoint, QRect, QSize, QModelIndex, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QPainterPath, QMouseEvent
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from app.ui.design_tokens import (
    COLORS,
    FAVORITE_LIST_ACTION_WIDTH,
    FAVORITE_STAR_HIT,
    FAVORITE_STAR_VISUAL,
    RADIUS_MD,
    RADIUS_SM,
)
from app.ui.icons import paint_favorite_star
from app.utils.view_mode import THUMBNAIL_LIST_SPACING

ROLE_CAPTION_NAME = Qt.UserRole + 10
ROLE_CAPTION_TAGS = Qt.UserRole + 11
ROLE_CAPTION_DATE = Qt.UserRole + 12
ROLE_CAPTION_TAGS_MUTED = Qt.UserRole + 13
ROLE_CAPTION_FAVORITE = Qt.UserRole + 14
ROLE_DRAG_DIMMED = Qt.UserRole + 50

ITEM_KIND_ROLE = Qt.UserRole + 1
ITEM_KIND_IMAGE = "image"
ITEM_KIND_HEADER = "header"
ITEM_KIND_FOLDER = "folder"
HEADER_VARIANT_ROLE = Qt.UserRole + 2
HEADER_VARIANT_NO_TAG = "no_tag"

GROUP_HEADER_HEIGHT = 40
# Must match _paint_image outer margin — hit-testing uses the same inset
CARD_INSET = 6
CARD_RADIUS = RADIUS_MD
MEDIA_RADIUS = RADIUS_SM
MEDIA_PAD = 6
# Filename + date. Tags add CAPTION_TAG_LINE on top of this.
CAPTION_BAND_HEIGHT = 38
CAPTION_TAG_LINE = 15
FAVORITE_CAPTION_GAP = 4


def caption_tag_color(muted: bool) -> QColor:
    """Assigned tags use Brand Blue; empty `No tags` stays muted."""
    return QColor(COLORS.text_faint) if muted else QColor(COLORS.target)


def caption_band_height(show_tags: bool) -> int:
    return CAPTION_BAND_HEIGHT + (CAPTION_TAG_LINE if show_tags else 0)


def grid_favorite_slot(card_rect: QRect) -> QRect:
    """Hit target at the bottom-right of the caption band, not on the image."""
    size = FAVORITE_STAR_HIT
    margin = 4
    return QRect(
        card_rect.right() - margin - size + 1,
        card_rect.bottom() - margin - size + 1,
        size,
        size,
    )


def list_favorite_slot(row_rect: QRect) -> QRect:
    """Dedicated right-edge action column so the star never covers the thumb."""
    width = FAVORITE_LIST_ACTION_WIDTH
    return QRect(row_rect.right() - width + 1, row_rect.y(), width, row_rect.height())


LIST_ROW_RADIUS = 12
LIST_ICON_PAD = 10
LIST_TEXT_GAP = 10
LIST_DATE_GAP = 12
LIST_STAR_GAP = 8
LIST_MIN_NAME_WIDTH = 48


def list_row_caption_rects(
    row_rect: QRect,
    *,
    icon_size: int,
    name_font: QFont,
    meta_font: QFont,
    date: str,
    show_tags: bool,
) -> tuple[QRect, QRect, QRect, QRect]:
    """Lay out a compact list row: thumb, filename, trailing date, optional tags.

    Returns (icon_box, name_area, date_area, tags_area). Filename stays in the
    left column; date is a right column vertically centered in the row frame
    so it cannot stack under the name and overflow onto the next row.
    """
    fm_name = QFontMetrics(name_font)
    fm_meta = QFontMetrics(meta_font)
    name_h = fm_name.height()
    meta_h = fm_meta.height()
    icon_box = QRect(
        row_rect.x() + LIST_ICON_PAD,
        row_rect.y() + max(0, (row_rect.height() - icon_size) // 2),
        icon_size,
        icon_size,
    )
    star_slot = list_favorite_slot(row_rect)
    text_left = icon_box.right() + LIST_TEXT_GAP
    text_right = star_slot.left() - LIST_STAR_GAP
    available = max(1, text_right - text_left)

    date_area = QRect()
    date_text = str(date or "")
    if date_text:
        natural = fm_meta.horizontalAdvance(date_text)
        reserved = min(natural, max(available - LIST_MIN_NAME_WIDTH - LIST_DATE_GAP, available // 3))
        date_w = max(1, reserved)
        date_area = QRect(
            text_right - date_w,
            row_rect.y() + max(0, (row_rect.height() - meta_h) // 2),
            date_w,
            meta_h,
        )

    name_right = date_area.left() - LIST_DATE_GAP if date_text else text_right
    name_w = max(1, name_right - text_left)
    name_top = row_rect.y() + 8
    name_area = QRect(text_left, name_top, name_w, name_h)
    tags_area = QRect()
    if show_tags:
        tags_area = QRect(text_left, name_area.bottom() + 2, name_w, meta_h)
        overflow = tags_area.bottom() - (row_rect.bottom() - 4)
        if overflow > 0:
            name_area.translate(0, -overflow)
            tags_area.translate(0, -overflow)
            if name_area.y() < row_rect.y() + 4:
                name_area.moveTop(row_rect.y() + 4)
                tags_area.moveTop(name_area.bottom() + 2)
    return icon_box, name_area, date_area, tags_area


def favorite_star_visual_rect(slot: QRect) -> QRect:
    size = min(FAVORITE_STAR_VISUAL, max(16, slot.height() - 4))
    return QRect(
        slot.center().x() - size // 2,
        slot.center().y() - size // 2,
        size,
        size,
    )


def media_rect_for_card(card_rect: QRect, show_tags: bool) -> QRect:
    """Image box inside the already-inset card; caption always sits below it."""
    reserve = caption_band_height(show_tags)
    width = max(card_rect.width() - (MEDIA_PAD * 2), 1)
    height = max(card_rect.height() - MEDIA_PAD - reserve, 48)
    return QRect(
        card_rect.x() + MEDIA_PAD,
        card_rect.y() + MEDIA_PAD,
        width,
        height,
    )


class CaptionIconDelegate(QStyledItemDelegate):
    """Paint compact thumbnail cards; group headers are subtle section labels."""

    favorite_clicked = Signal(object)

    def __init__(
        self,
        *,
        icon_size: int = 120,
        cell_width: int = 156,
        cell_height: int = 240,
        list_mode: bool = False,
        show_selection_badge: bool = True,
        show_tags: bool = True,
        pastel_emphasis: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._icon_size = icon_size
        self._cell_width = cell_width
        self._cell_height = cell_height
        self._list_mode = list_mode
        self._show_selection_badge = show_selection_badge
        self._show_tags = show_tags
        self._pastel_emphasis = bool(pastel_emphasis)
        self._header_width = 0

    @property
    def cell_width(self) -> int:
        return self._cell_width

    def set_geometry(
        self,
        icon_size: int,
        cell_width: int,
        cell_height: int,
        header_width: int | None = None,
    ) -> None:
        self._icon_size = icon_size
        self._cell_width = cell_width
        self._cell_height = cell_height
        if header_width is not None:
            self._header_width = max(1, int(header_width))

    def set_list_mode(self, enabled: bool) -> None:
        self._list_mode = enabled

    def set_show_tags(self, enabled: bool) -> None:
        self._show_tags = bool(enabled)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if index.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            if self._header_width > 0:
                return QSize(self._header_width, GROUP_HEADER_HEIGHT)
            widget = option.widget
            viewport_w = widget.viewport().width() if widget is not None else self._cell_width
            return QSize(
                max(1, viewport_w - 2 * THUMBNAIL_LIST_SPACING),
                GROUP_HEADER_HEIGHT,
            )
        return QSize(self._cell_width, self._cell_height)

    def _media_rect(self, card_rect: QRect) -> QRect:
        return media_rect_for_card(card_rect, self._show_tags)

    @staticmethod
    def _draw_cover_pixmap(painter: QPainter, icon, dest: QRect) -> None:
        """Paint a cached thumbnail into dest without upscaling on HiDPI."""
        if icon is None or not hasattr(icon, "pixmap") or dest.width() < 1 or dest.height() < 1:
            return
        device = painter.device()
        dpr = max(1.0, float(device.devicePixelRatioF()) if device is not None else 1.0)
        pixel_w = max(1, int(round(dest.width() * dpr)))
        pixel_h = max(1, int(round(dest.height() * dpr)))
        sizes = icon.availableSizes() if hasattr(icon, "availableSizes") else []
        if sizes:
            best = max(sizes, key=lambda size: size.width() * size.height())
            pix = icon.pixmap(best)
        else:
            pix = icon.pixmap(pixel_w, pixel_h)
        if pix.isNull():
            return
        if pix.width() != pixel_w or pix.height() != pixel_h:
            pix = pix.scaled(
                pixel_w,
                pixel_h,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = max(0, (pix.width() - pixel_w) // 2)
            y = max(0, (pix.height() - pixel_h) // 2)
            pix = pix.copy(x, y, pixel_w, pixel_h)
        pix.setDevicePixelRatio(dpr)
        painter.drawPixmap(dest, pix)

    @staticmethod
    def _caption_fonts(base_font: QFont) -> tuple[QFont, QFont]:
        name_font = QFont(base_font)
        name_font.setPointSize(max(name_font.pointSize() - 1, 9))
        name_font.setWeight(QFont.Weight.DemiBold)
        meta_font = QFont(base_font)
        meta_font.setPointSize(max(meta_font.pointSize() - 2, 8))
        meta_font.setWeight(QFont.Weight.Normal)
        return name_font, meta_font

    @staticmethod
    def _wrapped_name_height(font: QFont, width: int, name: str) -> int:
        metrics = QFontMetrics(font)
        return max(
            metrics.height(),
            metrics.boundingRect(
                QRect(0, 0, max(width, 1), 100_000),
                Qt.TextWordWrap | Qt.TextWrapAnywhere | Qt.AlignLeft | Qt.AlignTop,
                name,
            ).height(),
        )

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        kind = index.data(ITEM_KIND_ROLE)
        if kind == ITEM_KIND_HEADER:
            self._paint_header(painter, option, index)
            return
        if kind == ITEM_KIND_FOLDER:
            if self._list_mode:
                self._paint_folder_list_row(painter, option, index)
            else:
                self._paint_folder_card(painter, option, index)
            return
        self._paint_image(painter, option, index)

    def _paint_header(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        """Subtle section label: category above images, calm and non-flashy."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = option.rect.adjusted(4, 2, -4, -2)
        title = str(index.data(Qt.DisplayRole) or "")
        is_no_tag = index.data(HEADER_VARIANT_ROLE) == HEADER_VARIANT_NO_TAG

        font = QFont(option.font)
        if is_no_tag:
            # Untagged state — muted helper text, not a tag chip look
            font.setWeight(QFont.Weight.Normal)
            font.setItalic(True)
            font.setPointSize(max(font.pointSize(), 10))
            painter.setPen(QColor(COLORS.text_muted))
        else:
            font.setWeight(QFont.Weight.DemiBold)
            font.setPointSize(max(font.pointSize() + 1, 11))
            painter.setPen(QColor(COLORS.text_secondary))
        painter.setFont(font)
        text_rect = rect.adjusted(8, 0, -8, -6)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, title)

        # Light divider under the category (images start on the next row)
        line_y = rect.bottom() - 1
        painter.setPen(QPen(QColor(COLORS.border), 1))
        painter.drawLine(rect.left() + 4, line_y, rect.right() - 4, line_y)
        painter.restore()

    def _paint_image(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        if self._list_mode:
            self._paint_list_row(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # Explorer-like afterimage: source cards fade while the drag ghost moves
        if index.data(ROLE_DRAG_DIMMED):
            painter.setOpacity(0.35)

        # Balanced outer margin (keep in sync with CARD_INSET / list hit-testing)
        rect = option.rect.adjusted(CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        self._paint_card_chrome(painter, rect, selected=selected, hovered=hovered)

        icon = index.data(Qt.DecorationRole)
        name = index.data(ROLE_CAPTION_NAME) or index.data(Qt.DisplayRole) or ""
        tags = index.data(ROLE_CAPTION_TAGS) or ""
        date = index.data(ROLE_CAPTION_DATE) or ""

        icon_box = self._media_rect(rect)
        self._paint_media_shadow(painter, icon_box)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS.surface_sunken))
        painter.drawRoundedRect(icon_box, MEDIA_RADIUS, MEDIA_RADIUS)
        if icon is not None:
            painter.save()
            clip_path = QPainterPath()
            clip_path.addRoundedRect(icon_box, MEDIA_RADIUS, MEDIA_RADIUS)
            painter.setClipPath(clip_path)
            self._draw_cover_pixmap(painter, icon, icon_box)
            painter.restore()

        if self._show_selection_badge and (option.state & QStyle.State_Selected):
            self._paint_selection_badge(painter, rect)

        star_slot = grid_favorite_slot(rect)
        self._paint_favorite_star(
            painter,
            star_slot,
            filled=bool(index.data(ROLE_CAPTION_FAVORITE)),
            hovered=hovered,
        )

        text_top = icon_box.bottom() + 5
        text_rect = QRect(
            rect.x() + 8,
            text_top,
            rect.width() - 16,
            max(rect.bottom() - text_top - 4, 0),
        )
        date_right = min(text_rect.right(), star_slot.left() - FAVORITE_CAPTION_GAP)

        def line_width(top: int, height: int) -> int:
            line = QRect(text_rect.x(), top, text_rect.width(), height)
            if line.intersects(star_slot):
                return max(1, date_right - text_rect.x())
            return text_rect.width()

        name_font, meta_font = self._caption_fonts(option.font)

        fm_name = QFontMetrics(name_font)
        fm_meta = QFontMetrics(meta_font)
        meta_line = fm_meta.height()
        y = text_rect.y()
        painter.setPen(QColor(COLORS.text_strong))
        painter.setFont(name_font)
        name_h = fm_name.height()
        name_w = line_width(y, name_h)
        name_area = QRect(text_rect.x(), y, name_w, name_h)
        painter.drawText(
            name_area,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            fm_name.elidedText(str(name), Qt.ElideMiddle, name_w),
        )
        y = name_area.bottom() + 1

        painter.setFont(meta_font)
        if self._show_tags and tags and y < text_rect.bottom():
            muted = bool(index.data(ROLE_CAPTION_TAGS_MUTED))
            painter.setPen(caption_tag_color(muted))
            tags_w = line_width(y, meta_line)
            tags_area = QRect(text_rect.x(), y, tags_w, meta_line)
            painter.drawText(
                tags_area,
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                fm_meta.elidedText(str(tags), Qt.ElideRight, tags_w),
            )
            y += meta_line + 1

        if date and y < text_rect.bottom():
            painter.setPen(QColor(COLORS.text_faint))
            date_width = line_width(y, meta_line)
            date_area = QRect(text_rect.x(), y, date_width, meta_line)
            painter.drawText(
                date_area,
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                fm_meta.elidedText(str(date), Qt.ElideRight, date_width),
            )

        painter.restore()

    def _paint_list_row(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if index.data(ROLE_DRAG_DIMMED):
            painter.setOpacity(0.35)
        rect = option.rect.adjusted(CARD_INSET, 2, -CARD_INSET, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        self._paint_card_chrome(
            painter,
            rect,
            selected=selected,
            hovered=hovered,
            radius=LIST_ROW_RADIUS,
            fill=QColor(COLORS.accent_soft)
            if selected
            else QColor(COLORS.surface_hover)
            if hovered
            else QColor(COLORS.card_bg),
        )
        icon = index.data(Qt.DecorationRole)
        name = index.data(ROLE_CAPTION_NAME) or index.data(Qt.DisplayRole) or ""
        date = index.data(ROLE_CAPTION_DATE) or ""
        name_font, meta_font = self._caption_fonts(option.font)
        icon_box, name_area, date_area, tags_area = list_row_caption_rects(
            rect,
            icon_size=self._icon_size,
            name_font=name_font,
            meta_font=meta_font,
            date=str(date),
            show_tags=self._show_tags,
        )
        clip = QPainterPath()
        clip.addRoundedRect(rect, LIST_ROW_RADIUS, LIST_ROW_RADIUS)
        painter.setClipPath(clip)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS.surface_sunken))
        painter.drawRoundedRect(icon_box, 6, 6)
        if icon is not None:
            painter.save()
            thumb_clip = QPainterPath()
            thumb_clip.addRoundedRect(icon_box, 6, 6)
            painter.setClipPath(thumb_clip)
            self._draw_cover_pixmap(painter, icon, icon_box)
            painter.restore()
        star_slot = list_favorite_slot(rect)
        self._paint_favorite_star(
            painter,
            star_slot,
            filled=bool(index.data(ROLE_CAPTION_FAVORITE)),
            hovered=hovered,
        )
        painter.setPen(QColor(COLORS.text_strong))
        painter.setFont(name_font)
        painter.drawText(
            name_area,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            QFontMetrics(name_font).elidedText(
                str(name), Qt.ElideMiddle, name_area.width()
            ),
        )
        if self._show_tags:
            tags = index.data(ROLE_CAPTION_TAGS) or ""
            if tags:
                muted = bool(index.data(ROLE_CAPTION_TAGS_MUTED))
                painter.setPen(caption_tag_color(muted))
                painter.setFont(meta_font)
                painter.drawText(
                    tags_area,
                    Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                    QFontMetrics(meta_font).elidedText(
                        str(tags), Qt.ElideRight, tags_area.width()
                    ),
                )
        if date and date_area.isValid() and date_area.width() > 0:
            painter.setPen(QColor(COLORS.text_muted))
            painter.setFont(meta_font)
            painter.drawText(
                date_area,
                Qt.AlignRight | Qt.AlignVCenter | Qt.TextSingleLine,
                QFontMetrics(meta_font).elidedText(
                    str(date), Qt.ElideRight, date_area.width()
                ),
            )
        painter.restore()

    def _paint_card_chrome(
        self,
        painter: QPainter,
        rect: QRect,
        *,
        selected: bool,
        hovered: bool,
        radius: int | None = None,
        fill: QColor | None = None,
    ) -> None:
        card_radius = CARD_RADIUS if radius is None else radius
        if selected:
            border = QColor(COLORS.accent)
            border_w = 1.5
        elif hovered:
            border = QColor(COLORS.accent)
            border_w = 1
        else:
            border = QColor(COLORS.border)
            border_w = 1
        self._paint_card_shadow(painter, rect, card_radius)
        painter.setPen(QPen(border, border_w))
        if fill is None:
            if hovered and not selected:
                fill = QColor(COLORS.surface_hover)
            else:
                fill = QColor(COLORS.card_bg)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, card_radius, card_radius)

    @staticmethod
    def _paint_card_shadow(painter: QPainter, rect: QRect, radius: int) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(15, 23, 42, 16))
        painter.drawRoundedRect(rect.adjusted(1, 2, 1, 3), radius, radius)

    @staticmethod
    def _paint_media_shadow(painter: QPainter, rect: QRect) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(15, 23, 42, 28))
        painter.drawRoundedRect(
            rect.adjusted(1, 2, 1, 3), MEDIA_RADIUS, MEDIA_RADIUS
        )

    @staticmethod
    def _paint_emoji(painter: QPainter, dest: QRect, emoji: str) -> None:
        painter.save()
        font = QFont()
        families = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Symbol"]
        if hasattr(font, "setFamilies"):
            font.setFamilies(families)
        else:
            font.setFamily(families[0])
        font.setPixelSize(max(12, int(min(dest.width(), dest.height()) * 0.86)))
        painter.setFont(font)
        painter.setPen(QColor(COLORS.text_strong))
        painter.drawText(dest, Qt.AlignCenter, emoji)
        painter.restore()

    def _inner_card_rect(self, option: QStyleOptionViewItem) -> QRect:
        if self._list_mode:
            return option.rect.adjusted(CARD_INSET, 2, -CARD_INSET, -2)
        return option.rect.adjusted(CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET)

    def favorite_hit_rect(self, option: QStyleOptionViewItem) -> QRect:
        card = self._inner_card_rect(option)
        if self._list_mode:
            return list_favorite_slot(card)
        return grid_favorite_slot(card)

    @staticmethod
    def favorite_star_rect(origin: QRect) -> QRect:
        """Visual star inside a caption/action slot. Kept for tests and callers."""
        return favorite_star_visual_rect(origin)

    @staticmethod
    def _paint_favorite_star(
        painter: QPainter, slot: QRect, *, filled: bool, hovered: bool
    ) -> None:
        star = favorite_star_visual_rect(slot)
        paint_favorite_star(
            painter, star, filled=filled, hovered=hovered, with_plate=False
        )

    def editorEvent(self, event, model, option, index) -> bool:
        if index.data(ITEM_KIND_ROLE) != ITEM_KIND_IMAGE:
            return super().editorEvent(event, model, option, index)
        if not isinstance(event, QMouseEvent):
            return super().editorEvent(event, model, option, index)
        star = self.favorite_hit_rect(option)
        if event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseButtonRelease,
        ) and event.button() == Qt.LeftButton:
            if star.contains(event.position().toPoint()):
                if event.type() == QEvent.Type.MouseButtonPress:
                    self.favorite_clicked.emit(index)
                return True
        return super().editorEvent(event, model, option, index)

    @staticmethod
    def _paint_explorer_folder(painter: QPainter, dest: QRect) -> None:
        CaptionIconDelegate._paint_emoji(painter, dest, "📁")

    def _paint_folder_card(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = option.rect.adjusted(CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        self._paint_card_chrome(painter, rect, selected=selected, hovered=hovered)
        icon_box = self._media_rect(rect)
        side = max(36, min(icon_box.width(), icon_box.height()) * 3 // 5)
        glyph = QRect(
            icon_box.center().x() - side // 2,
            icon_box.y() + max(8, (icon_box.height() - side) // 2 - 4),
            side,
            side,
        )
        self._paint_explorer_folder(painter, glyph)
        name = index.data(ROLE_CAPTION_NAME) or index.data(Qt.DisplayRole) or ""
        name_font, _meta_font = self._caption_fonts(option.font)
        painter.setPen(QColor(COLORS.text_strong))
        painter.setFont(name_font)
        text_rect = QRect(
            rect.x() + 8,
            icon_box.bottom() + 5,
            rect.width() - 16,
            max(rect.bottom() - icon_box.bottom() - 8, 0),
        )
        metrics = QFontMetrics(name_font)
        painter.drawText(
            text_rect,
            Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextSingleLine,
            metrics.elidedText(str(name), Qt.ElideMiddle, text_rect.width()),
        )
        painter.restore()

    def _paint_folder_list_row(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = option.rect.adjusted(CARD_INSET, 2, -CARD_INSET, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        self._paint_card_chrome(
            painter,
            rect,
            selected=selected,
            hovered=hovered,
            radius=LIST_ROW_RADIUS,
            fill=QColor(COLORS.accent_soft)
            if selected
            else QColor(COLORS.surface_hover)
            if hovered
            else QColor(COLORS.card_bg),
        )
        icon_side = max(20, min(32, self._icon_size))
        icon_box = QRect(
            rect.x() + 10,
            rect.y() + (rect.height() - icon_side) // 2,
            icon_side,
            icon_side,
        )
        self._paint_explorer_folder(painter, icon_box)
        name = index.data(ROLE_CAPTION_NAME) or index.data(Qt.DisplayRole) or ""
        name_font, _meta_font = self._caption_fonts(option.font)
        painter.setPen(QColor(COLORS.text_strong))
        painter.setFont(name_font)
        name_area = QRect(
            icon_box.right() + 10,
            rect.y() + 8,
            rect.right() - icon_box.right() - 20,
            rect.height() - 16,
        )
        painter.drawText(
            name_area,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
            QFontMetrics(name_font).elidedText(
                str(name), Qt.ElideMiddle, name_area.width()
            ),
        )
        painter.restore()

    @staticmethod
    def _draw_contain_pixmap(painter: QPainter, icon, dest: QRect) -> None:
        if icon is None or not hasattr(icon, "pixmap") or dest.width() < 1 or dest.height() < 1:
            return
        device = painter.device()
        dpr = max(1.0, float(device.devicePixelRatioF()) if device is not None else 1.0)
        pixel_w = max(1, int(round(dest.width() * dpr)))
        pixel_h = max(1, int(round(dest.height() * dpr)))
        pix = icon.pixmap(pixel_w, pixel_h)
        if pix.isNull():
            return
        pix = pix.scaled(
            pixel_w,
            pixel_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        pix.setDevicePixelRatio(dpr)
        x = dest.x() + (dest.width() - int(pix.width() / dpr)) // 2
        y = dest.y() + (dest.height() - int(pix.height() / dpr)) // 2
        painter.drawPixmap(x, y, pix)

    def _paint_selection_badge(self, painter: QPainter, card_rect: QRect) -> None:
        """Blue circle with white check — selected state cue for Organize."""
        size = 18
        margin = 5
        cx = card_rect.right() - margin - size // 2
        cy = card_rect.top() + margin + size // 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS.primary))
        painter.drawEllipse(QPoint(cx, cy), size // 2, size // 2)
        # Soft white ring
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPoint(cx, cy), size // 2 - 1, size // 2 - 1)
        # Check mark
        painter.setPen(
            QPen(QColor("#ffffff"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawLine(cx - 4, cy, cx - 1, cy + 3)
        painter.drawLine(cx - 1, cy + 3, cx + 5, cy - 3)
