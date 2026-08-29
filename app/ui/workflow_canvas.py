"""Left-to-right Puzzle canvas with built-in connectors and live wires."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontInfo,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from app.automation.blocks import VisualBlock, block_can_delete, category_style
from app.i18n import t
from app.ui.design_tokens import COLORS, RADIUS_MD, WORKFLOW_BLOCK_LINE, WORKFLOW_BOARD_BG, WORKFLOW_CARD_LINE
from app.ui.icons import catalog_icon

BLOCK_WIDTH = 268
BLOCK_HEIGHT = 124
BLOCK_GAP = 52
CANVAS_PAD_X = 40
CANVAS_PAD_Y = 56
GROUP_PAD_X = 20
GROUP_PAD_Y = 20
GROUP_PAD = GROUP_PAD_X
CONNECTOR_R = 11
BLOCK_RADIUS = 11
ICON_COL_W = 56
BLOCK_TITLE_PX = 14
BLOCK_ICON_SIZE = 32  # ~2.3× title, matches canvas icon-to-type ratio
MIN_ZOOM = 0.4
MAX_ZOOM = 2.0
DEFAULT_ZOOM = 1.0
ZOOM_STEP = 1.12
DRAG_THRESHOLD = 6
TRASH_SIZE = 28
TRASH_GLYPH = "\uE74D"
GRID_STEP = 22


def _fluent_font(pixel_size: int) -> QFont:
    for family in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        font = QFont(family)
        font.setPixelSize(pixel_size)
        if QFontInfo(font).family() == family:
            return font
    font = QFont()
    font.setPixelSize(pixel_size)
    return font


def puzzle_path(has_left: bool, has_right: bool, width: float = BLOCK_WIDTH, height: float = BLOCK_HEIGHT) -> QPainterPath:
    """Rounded body + built-in tab / notch as one outline for fill and selection."""
    r = float(BLOCK_RADIUS)
    cr = float(CONNECTOR_R)
    w = float(width)
    h = float(height)
    cy = h / 2.0
    body = QPainterPath()
    body.addRoundedRect(QRectF(0.0, 0.0, w, h), r, r)
    if has_right:
        tab = QPainterPath()
        tab.addEllipse(QRectF(w - cr, cy - cr, cr * 2.0, cr * 2.0))
        body = body.united(tab)
    if has_left:
        notch = QPainterPath()
        notch.addEllipse(QRectF(-cr, cy - cr, cr * 2.0, cr * 2.0))
        body = body.subtracted(notch)
    return body


def _uses_value_chip(block: VisualBlock) -> bool:
    if block.category == "trigger":
        return False
    text = (block.summary or "").strip()
    if not text:
        return False
    if "\n" in text or len(text) > 28:
        return False
    if block.visual_kind == "unsupported":
        return False
    if block.visual_kind == "all":
        return False
    return True


class WorkflowBlockItem(QGraphicsObject):
    def __init__(self, block: VisualBlock, index: int, parent=None) -> None:
        super().__init__(parent)
        self.block = block
        self.index = index
        self._selected = False
        self._hover = False
        self._press = QPointF()
        self._dragging = False
        self._trash_pressed = False
        self._trash_hover = False
        self._has_left = False
        self._has_right = True
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(3)
        self.setToolTip(self._tooltip())

    def block_id(self) -> str:
        return self.block.block_id

    def set_connectors(self, *, has_left: bool, has_right: bool) -> None:
        if self._has_left == has_left and self._has_right == has_right:
            return
        self.prepareGeometryChange()
        self._has_left = has_left
        self._has_right = has_right
        self.update()

    def has_left_connector(self) -> bool:
        return self._has_left

    def has_right_connector(self) -> bool:
        return self._has_right

    def puzzle_path(self) -> QPainterPath:
        return puzzle_path(self._has_left, self._has_right)

    def boundingRect(self) -> QRectF:
        extra = CONNECTOR_R + 6
        return QRectF(-extra, -6, BLOCK_WIDTH + extra * 2, BLOCK_HEIGHT + 12)

    def shape(self) -> QPainterPath:
        return self.puzzle_path()

    def can_delete(self) -> bool:
        return block_can_delete(self.block)

    def trash_visible(self) -> bool:
        return self.can_delete() and (self._hover or self._selected)

    def trash_rect(self) -> QRectF:
        return QRectF(BLOCK_WIDTH - TRASH_SIZE - 10, 8, TRASH_SIZE, TRASH_SIZE)

    def connector_out_local(self) -> QPointF:
        return QPointF(BLOCK_WIDTH + (CONNECTOR_R if self._has_right else 0), BLOCK_HEIGHT / 2.0)

    def connector_in_local(self) -> QPointF:
        return QPointF(0.0, BLOCK_HEIGHT / 2.0)

    def connector_out_scene(self) -> QPointF:
        return self.mapToScene(self.connector_out_local())

    def connector_in_scene(self) -> QPointF:
        return self.mapToScene(self.connector_in_local())

    def _tooltip(self) -> str:
        label = t(category_style(self.block.category).label_key)
        extra = t("automation.uses_ai") if self.block.uses_ai else ""
        parts = [f"{label} · {self.block.title}", self.block.summary]
        if extra:
            parts.append(extra)
        return " · ".join(part for part in parts if part)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        style = category_style(self.block.category)
        path = self.puzzle_path()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        if self._dragging or self._selected:
            glow = QColor(style.ink)
            glow.setAlpha(36 if self._selected else 28)
            painter.save()
            painter.translate(0, 2 if self._dragging else 1)
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawPath(path)
            painter.restore()

        fill = QColor(COLORS.card_bg)
        border = QColor(WORKFLOW_BLOCK_LINE)
        width = 1.6
        if self._hover:
            border = QColor(style.ink)
            border.setAlpha(200)
        if self._selected:
            border = QColor(style.ink)
            width = 2.2
        if self._dragging:
            width = max(width, 1.8)

        shade = QColor(17, 24, 39, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(shade)
        painter.save()
        painter.translate(0, 1.4)
        painter.drawPath(path)
        painter.restore()
        painter.setBrush(QBrush(fill))
        painter.drawPath(path)

        painter.save()
        painter.setClipPath(path)
        icon_col = QRectF(0, 0, ICON_COL_W, BLOCK_HEIGHT)
        painter.fillRect(icon_col, QColor(style.fill))
        painter.restore()

        painter.setPen(QPen(border, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        icon_size = BLOCK_ICON_SIZE
        left_inset = float(CONNECTOR_R) if self._has_left else 0.0
        icon_x = left_inset + (ICON_COL_W - left_inset - icon_size) / 2.0
        icon_y = (BLOCK_HEIGHT - icon_size) / 2.0
        icon_key = self.block.icon_key or style.key
        icon = catalog_icon(icon_key, size=icon_size, color=style.ink)
        pix = icon.pixmap(icon_size, icon_size)
        icon_rect = QRect(int(round(icon_x)), int(round(icon_y)), icon_size, icon_size)
        painter.drawPixmap(icon_rect, pix)

        text_left = ICON_COL_W + 10
        text_right = BLOCK_WIDTH - (TRASH_SIZE + 18 if self.trash_visible() else 14)
        text_width = max(80, text_right - text_left)

        cat_font = QFont("Segoe UI")
        cat_font.setPixelSize(10)
        cat_font.setWeight(QFont.DemiBold)
        cat_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        painter.setFont(cat_font)
        painter.setPen(QColor(style.ink))
        cat_rect = QRectF(text_left, 12, text_width, 14)
        painter.drawText(cat_rect, Qt.AlignVCenter | Qt.AlignLeft, t(style.label_key).upper())

        title_font = QFont("Segoe UI")
        title_font.setPixelSize(14)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS.text_strong))
        title_rect = QRectF(text_left, 30, text_width, 22)
        metrics = QFontMetrics(title_font)
        title = metrics.elidedText(self.block.title, Qt.ElideRight, int(text_width))
        painter.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, title)

        detail_top = 58
        if _uses_value_chip(self.block):
            chip_font = QFont("Segoe UI")
            chip_font.setPixelSize(11)
            painter.setFont(chip_font)
            chip_text = self.block.summary.strip()
            chip_w = min(text_width, QFontMetrics(chip_font).horizontalAdvance(chip_text) + 16)
            chip = QRectF(text_left, detail_top, chip_w, 22)
            chip_bg = QColor(style.fill)
            painter.setPen(Qt.NoPen)
            painter.setBrush(chip_bg)
            painter.drawRoundedRect(chip, 8, 8)
            painter.setPen(QColor(style.ink))
            painter.drawText(chip.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, chip_text)
        else:
            body_font = QFont("Segoe UI")
            body_font.setPixelSize(12)
            painter.setFont(body_font)
            painter.setPen(QColor(COLORS.text_muted))
            summary_rect = QRectF(text_left, detail_top, text_width, 50)
            painter.drawText(
                summary_rect,
                Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap,
                self.block.summary,
            )

        if self.block.uses_ai:
            badge_right = BLOCK_WIDTH - (TRASH_SIZE + 14 if self.trash_visible() else 12)
            badge = QRectF(badge_right - 28, 10, 28, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS.ai_soft))
            painter.drawRoundedRect(badge, 8, 8)
            ai_font = QFont("Segoe UI")
            ai_font.setPixelSize(9)
            ai_font.setWeight(QFont.DemiBold)
            painter.setFont(ai_font)
            painter.setPen(QColor(COLORS.ai))
            painter.drawText(badge, Qt.AlignCenter, t("automation.ai_badge"))
        if self.block.visual_kind == "unsupported":
            mark = QRectF(BLOCK_WIDTH - 18, 40, 8, 8)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS.warning))
            painter.drawEllipse(mark)
        if self.trash_visible():
            trash = self.trash_rect()
            pressed = self._trash_pressed or self._trash_hover
            painter.setPen(QPen(QColor(COLORS.error if pressed else COLORS.border), 1))
            painter.setBrush(QColor(COLORS.error_soft if pressed else COLORS.card_bg))
            painter.drawRoundedRect(trash, 8, 8)
            painter.setPen(QColor(COLORS.error if pressed else COLORS.text_muted))
            painter.setFont(_fluent_font(13))
            painter.drawText(trash, Qt.AlignCenter, TRASH_GLYPH)

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def itemChange(self, change, value):
        canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if change == QGraphicsItem.ItemPositionHasChanged and isinstance(canvas, WorkflowCanvas):
            canvas._on_block_moved(self)
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event) -> None:
        over = self.trash_visible() and self.trash_rect().contains(event.pos())
        if over != self._trash_hover:
            self._trash_hover = over
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self._trash_hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self.trash_visible() and self.trash_rect().contains(event.pos()):
                self._trash_pressed = True
                self.update()
                event.accept()
                return
            self._press = event.scenePos()
            self._dragging = False
            self.setCursor(Qt.ClosedHandCursor)
            canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
            if isinstance(canvas, WorkflowCanvas):
                canvas.select_index(self.index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._trash_pressed:
            event.accept()
            return
        if event.buttons() & Qt.LeftButton:
            delta = event.scenePos() - self._press
            if not self._dragging and (abs(delta.x()) + abs(delta.y())) >= DRAG_THRESHOLD:
                self._dragging = True
                self.setZValue(8)
                self.update()
            if self._dragging:
                self.setPos(self.pos() + (event.scenePos() - self._press))
                self._press = event.scenePos()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._trash_pressed:
            hit = self.trash_visible() and self.trash_rect().contains(event.pos())
            self._trash_pressed = False
            self.update()
            if hit:
                canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
                if isinstance(canvas, WorkflowCanvas):
                    canvas.delete_requested.emit(self.index)
            event.accept()
            return
        self.setCursor(Qt.OpenHandCursor)
        if self._dragging:
            self._dragging = False
            self.setZValue(3)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WorkflowGroupItem(QGraphicsObject):
    shows_label = False

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rect = QRectF()
        self.setZValue(0)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip(t("automation.flow_group_hint"))

    def set_rect(self, rect: QRectF) -> None:
        self.prepareGeometryChange()
        self._rect = QRectF(rect)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-2, -2, 2, 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        if self._rect.isEmpty():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        border = QColor(WORKFLOW_CARD_LINE)
        border.setAlpha(150)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(self._rect, 16, 16)

    def mousePressEvent(self, event) -> None:
        canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if isinstance(canvas, WorkflowCanvas) and event.button() == Qt.LeftButton:
            canvas._begin_group_drag(event.scenePos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if isinstance(canvas, WorkflowCanvas) and event.buttons() & Qt.LeftButton:
            canvas._continue_group_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        canvas = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if isinstance(canvas, WorkflowCanvas):
            canvas._end_group_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WorkflowCanvas(QGraphicsView):
    block_selected = Signal(int)
    delete_requested = Signal(int)
    zoom_changed = Signal(float)

    MIN_ZOOM = MIN_ZOOM
    MAX_ZOOM = MAX_ZOOM
    DEFAULT_ZOOM = DEFAULT_ZOOM

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowCanvas")
        self.setFrameStyle(0)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.setBackgroundBrush(QBrush(QColor(WORKFLOW_BOARD_BG)))
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(WORKFLOW_BOARD_BG))
        pal.setColor(QPalette.ColorRole.Base, QColor(WORKFLOW_BOARD_BG))
        self.setPalette(pal)
        viewport = self.viewport()
        viewport.setAutoFillBackground(True)
        viewport.setAttribute(Qt.WA_OpaquePaintEvent, True)
        viewport.setAttribute(Qt.WA_StyledBackground, True)
        viewport.setPalette(pal)
        self._zoom = DEFAULT_ZOOM
        self._panning = False
        self._pan_start = QPointF()
        self._space_down = False
        self._blocks: list[WorkflowBlockItem] = []
        self._connectors: list[QGraphicsPathItem] = []
        self._group = WorkflowGroupItem()
        self.scene().addItem(self._group)
        self._selected_index = -1
        self._empty_visible = True
        self._group_drag = False
        self._group_anchor = QPointF()
        self._group_origins: list[QPointF] = []
        self._updating = False
        self._positions: dict[str, QPointF] = {}

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def selected_index(self) -> int:
        return self._selected_index

    def block_count(self) -> int:
        return len(self._blocks)

    def block_scene_x(self, index: int) -> float:
        if 0 <= index < len(self._blocks):
            return self._blocks[index].pos().x()
        return 0.0

    def block_position(self, index: int) -> QPointF:
        if 0 <= index < len(self._blocks):
            return QPointF(self._blocks[index].pos())
        return QPointF()

    def set_steps(self, steps, selected_index: int = -1) -> None:
        from app.automation.blocks import visual_blocks_for

        self.set_blocks(visual_blocks_for(folder=None, origin="", steps=steps), selected_index)

    def set_blocks(self, blocks: list[VisualBlock], selected_index: int = -1) -> None:
        self._rebuild(list(blocks), selected_index)

    def select_index(self, index: int) -> None:
        self._selected_index = index if 0 <= index < len(self._blocks) else -1
        for item in self._blocks:
            item.set_selected(item.index == self._selected_index)
        if self._selected_index >= 0:
            self.block_selected.emit(self._selected_index)

    def set_zoom(self, value: float) -> None:
        target = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(value)))
        if abs(target - self._zoom) < 0.0001:
            return
        factor = target / self._zoom
        self._zoom = target
        self.scale(factor, factor)
        self.zoom_changed.emit(self._zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = DEFAULT_ZOOM
        self._center_content()
        self.zoom_changed.emit(self._zoom)

    def align_blocks(self) -> None:
        self._updating = True
        for index, item in enumerate(self._blocks):
            pos = self._default_pos(index)
            item.setPos(pos)
            self._positions[item.block_id()] = QPointF(pos)
        self._updating = False
        self._refresh_wires()
        self._ensure_scene_rect()
        self._center_content()

    def connector_is_straight(self, index: int = 0) -> bool:
        if not (0 <= index < len(self._connectors)):
            return False
        path = self._connectors[index].path()
        if path.elementCount() < 2:
            return False
        curve = getattr(QPainterPath, "CurveToElement", None)
        if curve is None:
            curve = QPainterPath.ElementType.CurveToElement
        return all(path.elementAt(i).type != curve for i in range(path.elementCount()))

    def fit_to_workflow(self) -> None:
        rect = self._content_rect()
        view = self.viewport().rect()
        if rect.isEmpty() or view.width() < 40 or view.height() < 40:
            self.reset_zoom()
            return
        pad = 48
        toolbar = 88
        sx = (view.width() - pad) / max(rect.width(), 1)
        sy = (view.height() - pad - toolbar) / max(rect.height(), 1)
        needed = min(sx, sy)
        self.resetTransform()
        self._zoom = DEFAULT_ZOOM
        if needed >= 0.96:
            self._center_content()
            self.zoom_changed.emit(self._zoom)
            return
        self.set_zoom(min(max(needed, self.MIN_ZOOM), self.MAX_ZOOM))
        self._center_content()

    def _default_pos(self, index: int) -> QPointF:
        return QPointF(CANVAS_PAD_X + index * (BLOCK_WIDTH + BLOCK_GAP), CANVAS_PAD_Y)

    def _rebuild(self, blocks: list[VisualBlock], selected_index: int = -1) -> None:
        self._updating = True
        kept = {item.block_id(): item.pos() for item in self._blocks}
        kept.update(self._positions)
        scene = self.scene()
        for item in list(self._blocks):
            scene.removeItem(item)
        for item in list(self._connectors):
            scene.removeItem(item)
        self._blocks = []
        self._connectors = []
        if self._group.scene() is None:
            scene.addItem(self._group)
        if not blocks:
            self._empty_visible = True
            self._group.set_rect(QRectF())
        else:
            self._empty_visible = False
            last = len(blocks) - 1
            for index, block in enumerate(blocks):
                item = WorkflowBlockItem(block, index)
                item.set_connectors(has_left=index > 0, has_right=index < last)
                pos = kept.get(block.block_id) or self._default_pos(index)
                item.setPos(pos)
                scene.addItem(item)
                self._blocks.append(item)
                self._positions[block.block_id] = QPointF(pos)
            for _ in range(max(0, len(self._blocks) - 1)):
                connector = QGraphicsPathItem()
                connector.setZValue(2)
                connector.setPen(
                    QPen(QColor(COLORS.text_faint), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                )
                scene.addItem(connector)
                self._connectors.append(connector)
            self._refresh_wires()
        self._ensure_scene_rect()
        self._updating = False
        self.select_index(selected_index)

    def _on_block_moved(self, item: WorkflowBlockItem) -> None:
        if self._updating:
            return
        self._positions[item.block_id()] = QPointF(item.pos())
        self._refresh_wires()
        self._ensure_scene_rect()

    def _refresh_wires(self) -> None:
        for index, connector in enumerate(self._connectors):
            if index + 1 >= len(self._blocks):
                continue
            left = self._blocks[index]
            right = self._blocks[index + 1]
            start = left.connector_out_scene()
            end = right.connector_in_scene()
            path = QPainterPath(start)
            path.lineTo(end)
            angle = end - start
            length = max((angle.x() ** 2 + angle.y() ** 2) ** 0.5, 1)
            ux, uy = angle.x() / length, angle.y() / length
            head = 6.0
            wing = 3.6
            left_pt = QPointF(end.x() - ux * head + uy * wing, end.y() - uy * head - ux * wing)
            right_pt = QPointF(end.x() - ux * head - uy * wing, end.y() - uy * head + ux * wing)
            path.moveTo(left_pt)
            path.lineTo(end)
            path.lineTo(right_pt)
            connector.setPath(path)
        self._refresh_group()

    def _block_scene_bounds(self, item: WorkflowBlockItem) -> QRectF:
        return item.mapRectToScene(item.puzzle_path().boundingRect())

    def connected_blocks_rect(self) -> QRectF:
        if not self._blocks:
            return QRectF()
        rect = self._block_scene_bounds(self._blocks[0])
        for item in self._blocks[1:]:
            rect = rect.united(self._block_scene_bounds(item))
        return rect

    def flow_group_rect(self) -> QRectF:
        return QRectF(self._group._rect)

    def _refresh_group(self) -> None:
        if not self._blocks:
            self._group.set_rect(QRectF())
            return
        rect = self.connected_blocks_rect()
        self._group.set_rect(rect.adjusted(-GROUP_PAD_X, -GROUP_PAD_Y, GROUP_PAD_X, GROUP_PAD_Y))

    def _begin_group_drag(self, scene_pos: QPointF) -> None:
        self._group_drag = True
        self._group_anchor = QPointF(scene_pos)
        self._group_origins = [QPointF(item.pos()) for item in self._blocks]
        self.setCursor(Qt.ClosedHandCursor)

    def _continue_group_drag(self, scene_pos: QPointF) -> None:
        if not self._group_drag:
            return
        delta = scene_pos - self._group_anchor
        self._updating = True
        for item, origin in zip(self._blocks, self._group_origins):
            item.setPos(origin + delta)
        self._updating = False
        self._refresh_wires()

    def _end_group_drag(self) -> None:
        if self._group_drag:
            for item in self._blocks:
                self._positions[item.block_id()] = QPointF(item.pos())
        self._group_drag = False
        self.unsetCursor()
        self._refresh_wires()
        self._ensure_scene_rect()

    def _content_rect(self) -> QRectF:
        if self._blocks:
            return self.connected_blocks_rect().adjusted(-24, -24, 24, 24)
        return QRectF(CANVAS_PAD_X, CANVAS_PAD_Y, 280, 80)

    def _center_content(self) -> None:
        self.centerOn(self._content_rect().center())

    def _ensure_scene_rect(self) -> None:
        content = self._content_rect()
        view = self.mapToScene(self.viewport().rect()).boundingRect()
        if view.width() < 8 or view.height() < 8:
            self.scene().setSceneRect(content.adjusted(-80, -60, 80, 80))
            return
        extra_x = 96 if content.width() > view.width() else 48
        extra_y = 80 if content.height() > view.height() else 40
        room = content.united(view).adjusted(-extra_x, -extra_y, extra_x, extra_y)
        self.scene().setSceneRect(room)

    def _item_at(self, pos) -> QGraphicsItem | None:
        return self.itemAt(pos)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(WORKFLOW_BOARD_BG))
        painter.setRenderHint(QPainter.Antialiasing, False)
        dot = QColor(COLORS.border_strong)
        dot.setAlpha(210)
        painter.setPen(QPen(dot, 1.35))
        left = int(rect.left()) - (int(rect.left()) % GRID_STEP)
        top = int(rect.top()) - (int(rect.top()) % GRID_STEP)
        x = left
        while x <= rect.right() + 1:
            y = top
            while y <= rect.bottom() + 1:
                painter.drawPoint(x, y)
                y += GRID_STEP
            x += GRID_STEP

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            event.accept()
            return
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event) -> None:
        item = self._item_at(event.position().toPoint())
        if isinstance(item, (WorkflowBlockItem, WorkflowGroupItem)):
            super().mousePressEvent(event)
            return
        if event.button() in {Qt.MiddleButton, Qt.RightButton} or (
            event.button() == Qt.LeftButton and (self._space_down or item is None)
        ):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if event.key() in {Qt.Key_Plus, Qt.Key_Equal}:
            self.zoom_in()
            event.accept()
            return
        if event.key() in {Qt.Key_Minus, Qt.Key_Underscore}:
            self.zoom_out()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.select_index(-1)
            event.accept()
            return
        if event.key() in {Qt.Key_Left, Qt.Key_Right} and self._blocks:
            step = -1 if event.key() == Qt.Key_Left else 1
            current = self._selected_index if self._selected_index >= 0 else 0
            self.select_index(max(0, min(len(self._blocks) - 1, current + step)))
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self._space_down = False
            if not self._panning:
                self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect() if event is not None else self.rect(), QColor(WORKFLOW_BOARD_BG))
        painter.end()
        super().paintEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()
        self.update()
        self._ensure_scene_rect()
        if self._empty_visible and not self._blocks:
            self._center_content()
