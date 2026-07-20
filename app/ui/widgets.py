"""List / tree widgets for Images page (Explorer-like DnD)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QEvent,
    QItemSelectionModel,
    QMimeData,
    QObject,
    QPoint,
    QRect,
    QTimer,
    Signal,
    QByteArray,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDrag,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRubberBand,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from app.ui.caption_delegate import CARD_INSET, ROLE_DRAG_DIMMED

MIME_IMAGE_PATHS = "application/x-sstool-image-paths"

_SIMPLE_DROP_SIZE = 36


def encode_image_paths(paths: list[Path]) -> QByteArray:
    text = "\n".join(str(p.resolve()) for p in paths)
    return QByteArray(text.encode("utf-8"))


def decode_image_paths(data: QByteArray | bytes) -> list[Path]:
    raw = bytes(data).decode("utf-8", errors="ignore")
    paths: list[Path] = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            paths.append(Path(line))
    return paths


def build_folder_drop_pixmap(
    *,
    count: int = 1,
    copy_mode: bool = False,
    device_pixel_ratio: float = 1.0,
) -> QPixmap:
    """
    Compact ■ / ■+ badge used for the entire drag (no large card ghost).

    Keeps folder names readable while choosing a drop target.
    """
    dpr = max(float(device_pixel_ratio), 1.0)
    size = _SIMPLE_DROP_SIZE
    canvas = QPixmap(int(size * dpr), int(size * dpr))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(Qt.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)

    body = QRect(2, 2, size - 4, size - 4)
    painter.setPen(QPen(QColor("#1d4ed8"), 1.5))
    painter.setBrush(QColor("#eff6ff"))
    painter.drawRoundedRect(body, 6, 6)

    inner = QRect(9, 9, size - 18, size - 18)
    painter.setPen(QPen(QColor("#2563eb"), 1.2))
    painter.setBrush(QColor("#dbeafe"))
    painter.drawRoundedRect(inner, 3, 3)

    if copy_mode:
        plus = QRect(size - 16, size - 16, 14, 14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2563eb"))
        painter.drawEllipse(plus)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        cx, cy = plus.center().x(), plus.center().y()
        painter.drawLine(cx - 3, cy, cx + 3, cy)
        painter.drawLine(cx, cy - 3, cx, cy + 3)
    else:
        painter.setPen(QPen(QColor("#1d4ed8"), 2))
        painter.drawLine(12, 18, 22, 18)
        painter.drawLine(18, 14, 22, 18)
        painter.drawLine(18, 22, 22, 18)

    if count > 1:
        badge_text = str(count) if count < 100 else "99+"
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(7)
        painter.setFont(font)
        badge = QRect(size - 15, 1, 14, 14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2563eb"))
        painter.drawEllipse(badge)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(badge, Qt.AlignCenter, badge_text)

    painter.end()
    return canvas


class _DragBadgeOverlay(QLabel):
    """Compact cursor badge (move / Ctrl+copy). Never shows the card ghost."""

    def __init__(
        self,
        simple_move: QPixmap,
        simple_copy: QPixmap,
        parent=None,
    ):
        super().__init__(
            parent,
            Qt.ToolTip
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._simple_move = simple_move
        self._simple_copy = simple_copy
        self._hotspot = QPoint(_SIMPLE_DROP_SIZE // 2, _SIMPLE_DROP_SIZE // 2)
        self._copy_mode = False
        self.setPixmap(simple_move)
        self.adjustSize()
        self.show()

    def set_copy_mode(self, copy_mode: bool) -> None:
        if copy_mode == self._copy_mode:
            return
        self._copy_mode = copy_mode
        self.setPixmap(self._simple_copy if copy_mode else self._simple_move)
        self.adjustSize()

    def follow_cursor(self) -> None:
        self.move(QCursor.pos() - self._hotspot)


class ListPanelMarqueeBridge(QObject):
    """
    Start rubber-band selection from empty chrome around the list
    (panel padding / gaps outside the list frame).
    """

    def __init__(self, panel: QWidget, list_widget: "ScreenshotListWidget", parent=None):
        super().__init__(parent)
        self._panel = panel
        self._list = list_widget
        self._active = False
        panel.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._panel:
            return False
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            if not isinstance(event, QMouseEvent) or event.button() != Qt.LeftButton:
                return False
            if not self._is_empty_chrome(event.position().toPoint()):
                return False
            self._active = True
            self._panel.grabMouse()
            self._list.begin_marquee_from_parent(
                event.globalPosition().toPoint(),
                additive=bool(event.modifiers() & Qt.ControlModifier),
            )
            return True
        if et == QEvent.Type.MouseMove and self._active:
            if isinstance(event, QMouseEvent) and event.buttons() & Qt.LeftButton:
                self._list.update_marquee_from_parent(event.globalPosition().toPoint())
                return True
        if et == QEvent.Type.MouseButtonRelease and self._active:
            if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
                self._list.end_marquee_from_parent(event.globalPosition().toPoint())
                self._panel.releaseMouse()
                self._active = False
                return True
        return False

    def _is_empty_chrome(self, pos: QPoint) -> bool:
        """True for panel padding / layout gaps (not toolbar, search, or list)."""
        child = self._panel.childAt(pos)
        return child is None


class ScreenshotListWidget(QListWidget):
    """Thumbnail list: Explorer-like selection + optional drag-to-folder."""

    WHEEL_ROWS_PER_NOTCH = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_dimmed_paths: list[str] = []
        self._drag_overlay: _DragBadgeOverlay | None = None
        self._drag_timer: QTimer | None = None
        self._marquee_origin: QPoint | None = None
        self._marquee_band: QRubberBand | None = None
        self._marquee_additive = False
        self._marquee_active = False
        self._marquee_base: set[int] = set()
        self.configure_explorer_selection()
        self.configure_drag_export_only()

    def configure_explorer_selection(self) -> None:
        """Windows Explorer-style multi-select (Shift/Ctrl + rubber-band)."""
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionRectVisible(True)

    def configure_drag_export_only(self) -> None:
        """
        Drag images out to folders; never reorder inside the list.

        Call again after setViewMode / setMovement — Qt resets DnD flags there.
        """
        self.setMovement(QListWidget.Static)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(False)

    def _card_rect(self, item: QListWidgetItem) -> QRect:
        """Visible card frame (matches CaptionIconDelegate painting)."""
        return self.visualItemRect(item).adjusted(
            CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET
        )

    def _selectable_item_at(self, pos: QPoint) -> QListWidgetItem | None:
        """Item only if the cursor is inside the painted card, not cell padding."""
        item = self.itemAt(pos)
        if item is None:
            return None
        if not (item.flags() & Qt.ItemIsSelectable):
            return None
        if not self._card_rect(item).contains(pos):
            return None
        return item

    def _cleanup_marquee(self) -> None:
        self._marquee_origin = None
        self._marquee_active = False
        self._marquee_additive = False
        self._marquee_base.clear()
        if self._marquee_band is not None:
            self._marquee_band.hide()
            self._marquee_band.deleteLater()
            self._marquee_band = None

    def _apply_marquee_selection(self, rect: QRect) -> None:
        """Select items whose card frame intersects the marquee (viewport coords)."""
        keep = self._marquee_base if self._marquee_additive else set()
        first: QListWidgetItem | None = None
        self.blockSignals(True)
        try:
            for i in range(self.count()):
                item = self.item(i)
                if item is None or not (item.flags() & Qt.ItemIsSelectable):
                    continue
                hit = self._card_rect(item).intersects(rect)
                selected = hit or (i in keep)
                item.setSelected(selected)
                if hit and first is None:
                    first = item
        finally:
            self.blockSignals(False)
        if first is not None:
            # NoUpdate: keep multi-select; SelectCurrent would collapse it
            self.setCurrentItem(first, QItemSelectionModel.NoUpdate)
        self.itemSelectionChanged.emit()

    def begin_marquee_from_parent(self, global_pos: QPoint, *, additive: bool) -> None:
        """Start rubber-band from a press outside this list (parent panel padding)."""
        origin = self.viewport().mapFromGlobal(global_pos)
        self._cleanup_marquee()
        self._marquee_origin = origin
        self._marquee_additive = additive
        self._marquee_active = False
        if additive:
            self._marquee_base = {
                i
                for i in range(self.count())
                if (it := self.item(i)) is not None and it.isSelected()
            }
        else:
            self._marquee_base.clear()
            self.clearSelection()
            self.setCurrentItem(None)

    def update_marquee_from_parent(self, global_pos: QPoint) -> None:
        if self._marquee_origin is None:
            return
        pos = self.viewport().mapFromGlobal(global_pos)
        dist = (pos - self._marquee_origin).manhattanLength()
        if not self._marquee_active:
            if dist < QApplication.startDragDistance():
                return
            self._marquee_active = True
            self._marquee_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
        rect = QRect(self._marquee_origin, pos).normalized()
        assert self._marquee_band is not None
        self._marquee_band.setGeometry(rect)
        self._marquee_band.show()
        self._apply_marquee_selection(rect)

    def end_marquee_from_parent(self, global_pos: QPoint) -> None:
        if self._marquee_origin is None:
            return
        if self._marquee_active:
            pos = self.viewport().mapFromGlobal(global_pos)
            self._apply_marquee_selection(
                QRect(self._marquee_origin, pos).normalized()
            )
        self._cleanup_marquee()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            item = self._selectable_item_at(pos)
            if item is None:
                # Empty / non-selectable (group header): start Explorer rubber-band
                mods = event.modifiers()
                self._marquee_origin = pos
                self._marquee_additive = bool(mods & Qt.ControlModifier)
                self._marquee_active = False
                if self._marquee_additive:
                    self._marquee_base = {
                        i
                        for i in range(self.count())
                        if (it := self.item(i)) is not None and it.isSelected()
                    }
                else:
                    self._marquee_base.clear()
                    if not (mods & Qt.ShiftModifier):
                        self.clearSelection()
                        self.setCurrentItem(None)
                event.accept()
                return
            self._cleanup_marquee()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._marquee_origin is not None and event.buttons() & Qt.LeftButton:
            pos = event.position().toPoint()
            dist = (pos - self._marquee_origin).manhattanLength()
            if not self._marquee_active:
                if dist < QApplication.startDragDistance():
                    event.accept()
                    return
                self._marquee_active = True
                self._marquee_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
            rect = QRect(self._marquee_origin, pos).normalized()
            assert self._marquee_band is not None
            self._marquee_band.setGeometry(rect)
            self._marquee_band.show()
            self._apply_marquee_selection(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._marquee_origin is not None:
            if self._marquee_active:
                pos = event.position().toPoint()
                rect = QRect(self._marquee_origin, pos).normalized()
                self._apply_marquee_selection(rect)
            self._cleanup_marquee()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        dy = event.angleDelta().y()
        dx = event.angleDelta().x()

        if dy == 0 and dx == 0:
            pixel = event.pixelDelta()
            if pixel.y() or pixel.x():
                if pixel.y():
                    vbar = self.verticalScrollBar()
                    vbar.setValue(vbar.value() - int(pixel.y() * 1.2))
                if pixel.x():
                    hbar = self.horizontalScrollBar()
                    hbar.setValue(hbar.value() - int(pixel.x() * 1.2))
                event.accept()
                return
            super().wheelEvent(event)
            return

        row_h = self._scroll_row_height()
        if dy:
            notches = dy / 120.0
            delta = int(notches * row_h * self.WHEEL_ROWS_PER_NOTCH)
            if delta == 0:
                delta = 1 if dy > 0 else -1
            vbar = self.verticalScrollBar()
            vbar.setValue(vbar.value() - delta)
        if dx:
            notches = dx / 120.0
            delta = int(notches * max(row_h // 2, 24) * self.WHEEL_ROWS_PER_NOTCH)
            if delta == 0:
                delta = 1 if dx > 0 else -1
            hbar = self.horizontalScrollBar()
            hbar.setValue(hbar.value() - delta)
        event.accept()

    def _scroll_row_height(self) -> int:
        grid = self.gridSize()
        if grid.height() > 1:
            return grid.height() + self.spacing()
        icon_h = self.iconSize().height()
        return max(icon_h + 28 + self.spacing(), 72)

    def _drag_image_items(self) -> list[QListWidgetItem]:
        items: list[QListWidgetItem] = []
        seen: set[str] = set()
        for item in self.selectedItems():
            path_str = item.data(Qt.UserRole)
            if not path_str:
                continue
            key = str(Path(str(path_str)).resolve())
            if key in seen:
                continue
            path = Path(key)
            if path.exists():
                seen.add(key)
                items.append(item)
        return items

    def _item_for_path(self, path_str: str) -> QListWidgetItem | None:
        want = str(Path(path_str).resolve())
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            raw = item.data(Qt.UserRole)
            if not raw:
                continue
            if str(Path(str(raw)).resolve()) == want:
                return item
        return None

    def _set_drag_sources_dimmed(
        self, items: list[QListWidgetItem] | None, dimmed: bool
    ) -> None:
        """
        Fade source cards while dragging.

        Paths are stored (not item pointers) so a mid-drag list reload after
        move/drop cannot touch deleted QListWidgetItems.
        """
        if dimmed:
            self._drag_dimmed_paths = []
            for item in items or []:
                path_str = item.data(Qt.UserRole)
                if not path_str:
                    continue
                key = str(Path(str(path_str)).resolve())
                self._drag_dimmed_paths.append(key)
                try:
                    item.setData(ROLE_DRAG_DIMMED, True)
                except RuntimeError:
                    pass
        else:
            for path_str in self._drag_dimmed_paths:
                item = self._item_for_path(path_str)
                if item is None:
                    continue
                try:
                    item.setData(ROLE_DRAG_DIMMED, False)
                except RuntimeError:
                    pass
            self._drag_dimmed_paths = []
        try:
            self.viewport().update()
        except RuntimeError:
            pass

    def _update_drag_overlay(self) -> None:
        overlay = self._drag_overlay
        if overlay is None:
            return
        copy_mode = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        overlay.set_copy_mode(copy_mode)
        overlay.follow_cursor()

    def _cleanup_drag_overlay(self) -> None:
        if self._drag_timer is not None:
            self._drag_timer.stop()
            self._drag_timer.deleteLater()
            self._drag_timer = None
        if self._drag_overlay is not None:
            self._drag_overlay.hide()
            self._drag_overlay.deleteLater()
            self._drag_overlay = None

    def startDrag(self, supportedActions) -> None:
        items = self._drag_image_items()
        if not items:
            return

        paths = [Path(str(item.data(Qt.UserRole))) for item in items]
        mime = QMimeData()
        mime.setData(MIME_IMAGE_PATHS, encode_image_paths(paths))
        mime.setText("\n".join(str(p) for p in paths))

        dpr = self.devicePixelRatioF()
        simple_move = build_folder_drop_pixmap(
            count=len(items), copy_mode=False, device_pixel_ratio=dpr
        )
        simple_copy = build_folder_drop_pixmap(
            count=len(items), copy_mode=True, device_pixel_ratio=dpr
        )

        # Native drag image empty — overlay shows only the compact badge
        empty = QPixmap(1, 1)
        empty.fill(Qt.transparent)

        drag = QDrag(self)
        drag.setPixmap(empty)
        drag.setHotSpot(QPoint(0, 0))
        drag.setMimeData(mime)

        actions = supportedActions & (Qt.MoveAction | Qt.CopyAction)
        if not actions:
            actions = Qt.MoveAction | Qt.CopyAction

        self._drag_overlay = _DragBadgeOverlay(simple_move, simple_copy)
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(16)
        self._drag_timer.timeout.connect(self._update_drag_overlay)
        self._drag_timer.start()
        self._update_drag_overlay()

        self._set_drag_sources_dimmed(items, True)
        try:
            drag.exec(actions, Qt.MoveAction)
        finally:
            self._cleanup_drag_overlay()
            self._set_drag_sources_dimmed(None, False)


class ProjectTreeWidget(QTreeWidget):
    """Folder tree that accepts image path drops (move / Ctrl+copy)."""

    paths_dropped = Signal(str, list, bool)  # folder_name, paths, copy_mode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(False)
        self._drop_highlight: QTreeWidgetItem | None = None
        self._saved_current: QTreeWidgetItem | None = None
        self._drop_session = False
        self._leave_clear_timer = QTimer(self)
        self._leave_clear_timer.setSingleShot(True)
        self._leave_clear_timer.setInterval(40)
        self._leave_clear_timer.timeout.connect(self._clear_drop_if_outside)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_IMAGE_PATHS):
            self._begin_drop_session()
            if event.modifiers() & Qt.ControlModifier:
                event.setDropAction(Qt.CopyAction)
            else:
                event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(MIME_IMAGE_PATHS):
            event.ignore()
            return
        self._leave_clear_timer.stop()
        self._begin_drop_session()
        item = self.itemAt(event.position().toPoint())
        project = item.data(0, Qt.UserRole) if item is not None else None
        if project:
            self._set_drop_highlight(item)
            if event.modifiers() & Qt.ControlModifier:
                event.setDropAction(Qt.CopyAction)
            else:
                event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            self._clear_drop_highlight(restore_current=False)
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        # Defer clear — Qt often fires leave when crossing item boundaries
        self._leave_clear_timer.start()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._leave_clear_timer.stop()
        item = self.itemAt(event.position().toPoint())
        self._end_drop_session()
        if item is None:
            event.ignore()
            return
        project = item.data(0, Qt.UserRole)
        if not project:
            event.ignore()
            return

        paths = decode_image_paths(event.mimeData().data(MIME_IMAGE_PATHS))
        paths = [p for p in paths if p.exists()]
        if not paths:
            event.ignore()
            return

        copy_mode = bool(event.modifiers() & Qt.ControlModifier) or (
            event.dropAction() == Qt.CopyAction
        )
        self.paths_dropped.emit(str(project), paths, copy_mode)
        event.setDropAction(Qt.CopyAction if copy_mode else Qt.MoveAction)
        event.accept()

    def _begin_drop_session(self) -> None:
        if self._drop_session:
            return
        self._drop_session = True
        self._saved_current = self.currentItem()
        self.setProperty("dropping", True)
        self.style().unpolish(self)
        self.style().polish(self)

    def _end_drop_session(self) -> None:
        self._leave_clear_timer.stop()
        self._clear_drop_highlight(restore_current=True)
        if not self._drop_session:
            return
        self._drop_session = False
        self.setProperty("dropping", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self._saved_current = None

    def _clear_drop_if_outside(self) -> None:
        pos = self.mapFromGlobal(QCursor.pos())
        if self.viewport().rect().contains(pos):
            return
        self._end_drop_session()

    def _set_drop_highlight(self, item: QTreeWidgetItem) -> None:
        if self._drop_highlight is item:
            return
        self._clear_drop_highlight(restore_current=False)
        self._drop_highlight = item
        # Select the drop target so QSS [dropping] selected style paints blue
        self.blockSignals(True)
        self.setCurrentItem(item)
        item.setSelected(True)
        self.blockSignals(False)

    def _clear_drop_highlight(self, *, restore_current: bool) -> None:
        if self._drop_highlight is not None:
            try:
                self._drop_highlight.setSelected(False)
            except RuntimeError:
                pass
            self._drop_highlight = None
        if restore_current and self._saved_current is not None:
            try:
                self.blockSignals(True)
                self.setCurrentItem(self._saved_current)
                self._saved_current.setSelected(True)
                self.blockSignals(False)
            except RuntimeError:
                self.blockSignals(False)
