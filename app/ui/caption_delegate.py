"""Custom list delegate: balanced icon cards + subtle group headers."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize, QModelIndex
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

ROLE_CAPTION_NAME = Qt.UserRole + 10
ROLE_CAPTION_TAGS = Qt.UserRole + 11
ROLE_CAPTION_DATE = Qt.UserRole + 12
ROLE_CAPTION_TAGS_MUTED = Qt.UserRole + 13
ROLE_DRAG_DIMMED = Qt.UserRole + 50

ITEM_KIND_ROLE = Qt.UserRole + 1
ITEM_KIND_IMAGE = "image"
ITEM_KIND_HEADER = "header"
HEADER_VARIANT_ROLE = Qt.UserRole + 2
HEADER_VARIANT_NO_TAG = "no_tag"

GROUP_HEADER_HEIGHT = 40


class CaptionIconDelegate(QStyledItemDelegate):
    """Paint compact thumbnail cards; group headers are subtle section labels."""

    def __init__(
        self,
        *,
        icon_size: int = 120,
        cell_width: int = 156,
        cell_height: int = 240,
        list_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._icon_size = icon_size
        self._cell_width = cell_width
        self._cell_height = cell_height
        self._list_mode = list_mode

    @property
    def cell_width(self) -> int:
        return self._cell_width

    def set_geometry(self, icon_size: int, cell_width: int, cell_height: int) -> None:
        self._icon_size = icon_size
        self._cell_width = cell_width
        self._cell_height = cell_height

    def set_list_mode(self, enabled: bool) -> None:
        # Kept for API compatibility; all modes use icon cards now.
        self._list_mode = enabled

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if index.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            widget = option.widget
            viewport_w = widget.viewport().width() if widget is not None else 400
            # Full row: forces header alone on a line, images wrap underneath
            return QSize(max(viewport_w - 8, self._cell_width * 2), GROUP_HEADER_HEIGHT)
        return QSize(self._cell_width, self._cell_height)

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        if index.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            self._paint_header(painter, option, index)
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
            painter.setPen(QColor("#6b7280"))
        else:
            font.setWeight(QFont.Weight.DemiBold)
            font.setPointSize(max(font.pointSize() + 1, 11))
            painter.setPen(QColor("#4b5563"))
        painter.setFont(font)
        text_rect = rect.adjusted(8, 0, -8, -6)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, title)

        # Light divider under the category (images start on the next row)
        line_y = rect.bottom() - 1
        painter.setPen(QPen(QColor("#e5e7eb"), 1))
        painter.drawLine(rect.left() + 4, line_y, rect.right() - 4, line_y)
        painter.restore()

    def _paint_image(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # Explorer-like afterimage: source cards fade while the drag ghost moves
        if index.data(ROLE_DRAG_DIMMED):
            painter.setOpacity(0.35)

        # Balanced outer margin
        rect = option.rect.adjusted(4, 4, -4, -4)

        if option.state & QStyle.State_Selected:
            bg = QColor("#eff6ff")
            border = QColor("#2563eb")
            border_w = 2
        elif option.state & QStyle.State_MouseOver:
            bg = QColor("#f8fafc")
            border = QColor("#bfdbfe")
            border_w = 1
        else:
            bg = QColor("#ffffff")
            border = QColor("#e5e7eb")
            border_w = 1

        painter.setPen(QPen(border, border_w))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

        icon = index.data(Qt.DecorationRole)
        name = index.data(ROLE_CAPTION_NAME) or index.data(Qt.DisplayRole) or ""
        tags = index.data(ROLE_CAPTION_TAGS) or ""
        date = index.data(ROLE_CAPTION_DATE) or ""

        pad = 6
        icon_box = QRect(
            rect.x() + (rect.width() - self._icon_size) // 2,
            rect.y() + pad,
            self._icon_size,
            self._icon_size,
        )
        if icon is not None and hasattr(icon, "pixmap"):
            pix = icon.pixmap(self._icon_size, self._icon_size)
            if not pix.isNull():
                painter.drawPixmap(icon_box, pix)

        text_top = icon_box.bottom() + 4
        text_rect = QRect(
            rect.x() + 6,
            text_top,
            rect.width() - 12,
            max(rect.bottom() - text_top - 4, 0),
        )

        name_font = QFont(option.font)
        name_font.setPointSize(max(name_font.pointSize(), 8))
        name_font.setBold(True)
        meta_font = QFont(option.font)
        meta_font.setPointSize(max(meta_font.pointSize() - 1, 7))

        fm_name = QFontMetrics(name_font)
        fm_meta = QFontMetrics(meta_font)
        meta_line = fm_meta.height()
        name_budget = min(
            fm_name.height() * 2 + 2,
            max(text_rect.height() - meta_line * 2 - 4, fm_name.height()),
        )

        y = text_rect.y()
        painter.setPen(QColor("#111827"))
        painter.setFont(name_font)
        name_h = fm_name.boundingRect(
            QRect(0, 0, text_rect.width(), 10_000),
            Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop,
            str(name),
        ).height()
        name_h = min(name_h, name_budget)
        name_area = QRect(text_rect.x(), y, text_rect.width(), name_h)
        painter.drawText(
            name_area,
            Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop | Qt.TextWrapAnywhere,
            str(name),
        )
        y = name_area.bottom() + 2

        painter.setFont(meta_font)
        if tags and y < text_rect.bottom():
            muted = bool(index.data(ROLE_CAPTION_TAGS_MUTED))
            # Real tags: accent blue. Untagged state: muted gray helper text.
            painter.setPen(QColor("#9ca3af") if muted else QColor("#2563eb"))
            tags_area = QRect(text_rect.x(), y, text_rect.width(), meta_line)
            painter.drawText(
                tags_area,
                Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextSingleLine,
                fm_meta.elidedText(str(tags), Qt.ElideRight, text_rect.width()),
            )
            y += meta_line + 1

        if date and y < text_rect.bottom():
            painter.setPen(QColor("#6b7280"))
            date_area = QRect(text_rect.x(), y, text_rect.width(), meta_line)
            painter.drawText(
                date_area,
                Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextSingleLine,
                fm_meta.elidedText(str(date), Qt.ElideRight, text_rect.width()),
            )

        painter.restore()
