"""Simple wrapping flow layout for tag chips and similar controls."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Left-to-right flow that wraps to the next line when space runs out."""

    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        # Prefer height-for-current-width so show/hide of chips relayouts cleanly
        width = self.geometry().width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        if width <= 0:
            width = 200
        height = self.heightForWidth(width)
        m = self.contentsMargins()
        # Also keep a floor from the largest chip so empty/narrow cases don't collapse
        floor = QSize()
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            floor = floor.expandedTo(item.minimumSize())
        return QSize(
            max(floor.width(), 40) + m.left() + m.right(),
            max(height, floor.height() + m.top() + m.bottom()),
        )

    def spacing(self) -> int:
        return self._spacing

    def invalidate(self) -> None:
        super().invalidate()
        parent = self.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        space = self._spacing
        placed = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if placed > 0 and next_x - space > effective.right() and effective.width() > 0:
                x = effective.x()
                y = y + line_height + space
                next_x = x + hint.width() + space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
            placed += 1

        if placed == 0:
            return m.top() + m.bottom()
        return y + line_height - rect.y() + m.bottom()
