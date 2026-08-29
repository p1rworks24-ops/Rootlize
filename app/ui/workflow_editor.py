"""Workflow editor: Puzzle Builder is primary, Automation AI drafts only."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.actions.models import (
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
)
from app.automation import (
    AutomationService,
    Workflow,
    WorkflowValidationError,
    draft_workflow_from_text,
    new_workflow_id,
    utc_now,
    validate_workflow,
    workflow_run_status,
    workflow_step_summary,
)
from app.automation.blocks import (
    CATALOG_CATEGORY_ORDER,
    CATEGORY_ACTION,
    CATEGORY_AI,
    CATEGORY_CONDITION,
    CATEGORY_LOGIC,
    CATEGORY_SELECT,
    CATEGORY_TARGET,
    CATEGORY_TRIGGER,
    KIND_ACT,
    KIND_FIND,
    KIND_SELECT,
    KIND_UNSUPPORTED,
    START_BLOCK_ID,
    TARGET_ALL,
    TARGET_MEANING,
    TARGET_TEXT,
    VisualBlock,
    action_label,
    add_block_catalog,
    block_can_delete,
    block_kind,
    catalog_item_is_builder_ready,
    category_style,
    compile_search_steps,
    default_target_mode,
    folder_display_name,
    make_act_step,
    make_find_step,
    make_select_step,
    origin_from_target_mode,
    primary_search_query,
    visual_blocks_for,
)
from app.automation.models import sanitize_step_parameters
from app.i18n import t
from app.ui.design_tokens import (
    COLORS,
    RADIUS_CARD,
    WORKFLOW_BOARD_BG,
    WORKFLOW_PANE_BG,
    apply_card_shadow,
    clip_rounded,
    paint_canvas,
)
from app.ui.icons import (
    catalog_icon,
    icon_add,
    icon_ai_sparkle,
    icon_align,
    icon_back,
    icon_edit,
    icon_fit,
    icon_folder,
    icon_info,
    icon_play,
    icon_refresh,
    icon_save,
    icon_trash,
)
from app.ui.workflow_canvas import WorkflowCanvas
from app.workspace.context import ORIGIN_BROWSE, ORIGIN_MEANING, SearchResultContext
from app.workspace.plan import (
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    PlanStep,
    assign_step_ids,
)


class CardClipOverlay(QWidget):
    """Paint page-bg corner spandrels so square children keep a smooth card edge."""

    def __init__(self, parent: QWidget, *, radius: int = RADIUS_CARD) -> None:
        super().__init__(parent)
        self._radius = radius
        self.setObjectName("workflowCardClip")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect())
        outer = QPainterPath()
        outer.addRect(rect)
        inner = QPainterPath()
        inner.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), float(self._radius), float(self._radius))
        painter.setPen(Qt.NoPen)
        painter.fillPath(outer.subtracted(inner), QColor(COLORS.app_bg))
        pen = QPen(QColor(COLORS.border_subtle), 1)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(inner)


class InspectorPane(QFrame):
    """Settings body inside the inspector card. Surfaces come from the rail."""

    RADIUS = RADIUS_CARD

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowInspectorPane")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)


class _HoverIconButton(QToolButton):
    def __init__(self, parent: QWidget, *, idle_icon: QIcon, hover_icon: QIcon) -> None:
        super().__init__(parent)
        self._idle_icon = idle_icon
        self._hover_icon = hover_icon
        self.setIcon(idle_icon)

    def enterEvent(self, event) -> None:
        self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(self._idle_icon)
        super().leaveEvent(event)


class WorkflowWorkspace(QFrame):
    """Board chrome: canvas fills, toolbar stays fixed while the board pans."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowWorkspace")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(WORKFLOW_BOARD_BG))
        self.setPalette(pal)
        self._inner = QWidget(self)
        self._inner.setObjectName("workflowWorkspaceInner")
        self._inner.setAttribute(Qt.WA_StyledBackground, True)
        self._inner.setAutoFillBackground(False)
        self.canvas = WorkflowCanvas(self._inner)
        inner = QVBoxLayout(self._inner)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(self.canvas, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self._inner, 1)
        self.toolbar: QWidget | None = None
        self._card_overlay = CardClipOverlay(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect() if event is not None else self.rect(), QColor(WORKFLOW_BOARD_BG))
        painter.end()

    def set_toolbar(self, toolbar: QWidget) -> None:
        self.toolbar = toolbar
        toolbar.setParent(self)
        toolbar.raise_()
        self._position_toolbar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._inner.clearMask()
        self.clearMask()
        self._card_overlay.setGeometry(self.rect())
        self._card_overlay.raise_()
        self._position_toolbar()
        self.update()

    def _position_toolbar(self) -> None:
        bar = self.toolbar
        if bar is None:
            return
        bar.adjustSize()
        scroll = 0
        bar_h = self.canvas.horizontalScrollBar()
        if bar_h is not None and bar_h.isVisible():
            scroll = bar_h.height()
        x = max(16, (self.width() - bar.width()) // 2)
        y = max(16, self.height() - bar.height() - 28 - scroll)
        bar.move(x, y)
        bar.raise_()


class WorkflowSideRail(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowSideRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(300)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(WORKFLOW_PANE_BG))
        self.setPalette(pal)
        self.inner = QWidget(self)
        self.inner.setObjectName("workflowSideRailInner")
        self.inner.setAttribute(Qt.WA_StyledBackground, True)
        self.inner.setAutoFillBackground(False)
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        root.addWidget(self.inner, 1)
        self._card_overlay = CardClipOverlay(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect() if event is not None else self.rect(), QColor(WORKFLOW_PANE_BG))
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.inner.clearMask()
        self.clearMask()
        self._card_overlay.setGeometry(self.rect())
        self._card_overlay.raise_()
        self.update()


class AddBlockMenuItem(QPushButton):
    _ICON = 24
    _H_MARGIN = 12
    _TEXT_CHROME = 8 + 8 + 24 + 10

    def __init__(self, item, parent=None) -> None:
        super().__init__(parent)
        self.item = item
        self._tour_target = False
        self.setObjectName("workflowAddBlockItem")
        self.setProperty("category", item.category)
        self.setProperty("itemId", item.item_id)
        self.setProperty("catalogEnabled", bool(item.enabled))
        self.setProperty("tourTarget", False)
        self.setFlat(True)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor if item.enabled else Qt.ArrowCursor)
        self.setEnabled(bool(item.enabled))
        self.setMinimumHeight(self._ICON + self._H_MARGIN)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        style = category_style(item.category)
        ink = style.ink if item.enabled else COLORS.text_faint
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(10)
        plate = QLabel(self)
        plate.setObjectName("workflowAddBlockGlyph")
        plate.setAlignment(Qt.AlignCenter)
        plate.setFixedSize(self._ICON, self._ICON)
        plate.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        plate.setPixmap(catalog_icon(item.icon_key, size=self._ICON, color=ink).pixmap(self._ICON, self._ICON))
        plate.setProperty("iconInk", ink)
        label = t(item.label_key)
        if item.uses_ai and item.enabled:
            label = f"{label} · {t('automation.ai_badge')}"
        name = QLabel(label, self)
        name.setObjectName("workflowAddBlockName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name.setToolTip(label.replace("\n", " "))
        name_color = COLORS.text if item.enabled else COLORS.text_faint
        name_weight = 600 if item.enabled else 500
        name.setStyleSheet(
            f"color: {name_color}; background: transparent; border: none; font-weight: {name_weight};"
        )
        root.addWidget(plate, 0, Qt.AlignVCenter)
        root.addWidget(name, 1, Qt.AlignVCenter)
        self._name = name
        self._glyph = plate
        self._apply_item_style(hovered=False)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        text_w = max(48, int(width) - self._TEXT_CHROME)
        metrics = self._name.fontMetrics()
        bounds = metrics.boundingRect(
            0,
            0,
            text_w,
            4000,
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            self._name.text(),
        )
        return max(self._ICON + self._H_MARGIN, bounds.height() + self._H_MARGIN)

    def sizeHint(self) -> QSize:
        width = self.width() if self.width() > 1 else 200
        return QSize(max(width, 160), self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return QSize(120, self._ICON + self._H_MARGIN)

    def set_tour_target(self, on: bool) -> None:
        self._tour_target = bool(on)
        self.setProperty("tourTarget", self._tour_target)
        if self._tour_target:
            glow = QGraphicsDropShadowEffect(self)
            glow.setColor(QColor(37, 99, 235, 88))
            glow.setBlurRadius(18)
            glow.setOffset(0, 0)
            self.setGraphicsEffect(glow)
        else:
            self.setGraphicsEffect(None)
        self._apply_item_style(hovered=False)

    def _apply_item_style(self, *, hovered: bool) -> None:
        if self._tour_target:
            fill = "#dbeafe" if hovered else COLORS.target_soft
            self.setStyleSheet(
                f"QPushButton#workflowAddBlockItem {{ background-color: {fill}; "
                f"border: 2px solid {COLORS.target}; border-radius: 8px; }}"
            )
            return
        if hovered and self.item.enabled:
            style = category_style(self.item.category)
            self.setStyleSheet(
                f"QPushButton#workflowAddBlockItem, QPushButton#workflowAddBlockItem:hover {{ "
                f"background-color: {style.fill}; border: 1px solid {style.ink}; }}"
            )
            return
        self.setStyleSheet(
            "QPushButton#workflowAddBlockItem, QPushButton#workflowAddBlockItem:hover, "
            "QPushButton#workflowAddBlockItem:disabled, QPushButton#workflowAddBlockItem:disabled:hover "
            "{ background: transparent; border: none; }"
        )

    def enterEvent(self, event) -> None:
        if self.item.enabled or self._tour_target:
            self._apply_item_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_item_style(hovered=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self.item.enabled:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self.item.enabled:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if not self.item.enabled:
            event.ignore()
            return
        super().keyPressEvent(event)


class AddBlockCard(QFrame):
    """Single rounded surface. The popup shell stays transparent."""

    RADIUS = RADIUS_CARD

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowAddBlockCard")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setFrameShape(QFrame.NoFrame)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, float(self.RADIUS), float(self.RADIUS))
        painter.fillPath(path, QColor(COLORS.card_bg))
        pen = QPen(QColor(COLORS.border), 1)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        clip_rounded(self, self.RADIUS)


class AddBlockPopup(QFrame):
    item_chosen = Signal(object)
    RADIUS = RADIUS_CARD
    SHADOW_PAD = 12
    TOOLBAR_GAP = 12
    COL_PREF = 216
    COL_MIN = 188
    ITEM_MIN_H = AddBlockMenuItem._ICON + AddBlockMenuItem._H_MARGIN
    _CATEGORY_TITLES = {
        CATEGORY_TRIGGER: "automation.category_trigger",
        CATEGORY_SELECT: "automation.category_select",
        CATEGORY_TARGET: "automation.category_search",
        CATEGORY_CONDITION: "automation.category_condition",
        CATEGORY_ACTION: "automation.category_action",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("workflowAddBlockPopup")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(self.SHADOW_PAD, self.SHADOW_PAD, self.SHADOW_PAD, self.SHADOW_PAD)
        shell.setSpacing(0)
        self._card = AddBlockCard(self)
        apply_card_shadow(self._card, role="floating")
        layout = QHBoxLayout(self._card)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(0)
        grouped: dict[str, list] = {}
        for item in add_block_catalog():
            grouped.setdefault(item.category, []).append(item)
        columns = []
        for category in CATALOG_CATEGORY_ORDER:
            items = grouped.get(category) or []
            items = sorted(items, key=lambda row: (not row.enabled))
            if not items:
                continue
            title = t(self._CATEGORY_TITLES.get(category, "automation.category_search"))
            columns.append((category, title, items))
        self._sections: list[tuple[QFrame | None, QWidget, QScrollArea, list[AddBlockMenuItem]]] = []
        self._allowed_ids: set[str] = set()
        self._kb_button: AddBlockMenuItem | None = None
        self._col_w = self.COL_PREF
        for index, (category, title, items) in enumerate(columns):
            divider = None
            if index:
                divider = QFrame(self._card)
                divider.setObjectName("workflowAddBlockDivider")
                divider.setFixedWidth(1)
                layout.addWidget(divider)
            column = QWidget(self._card)
            column.setObjectName("workflowAddBlockColumn")
            column.setFixedWidth(self.COL_PREF)
            col = QVBoxLayout(column)
            col.setContentsMargins(8, 0, 8, 0)
            col.setSpacing(2)
            ink = category_style(category).ink
            heading = QLabel(title, column)
            heading.setObjectName("workflowAddBlockCategory")
            heading.setStyleSheet(f"color: {ink};")
            col.addWidget(heading)
            scroll = QScrollArea(column)
            scroll.setObjectName("workflowAddBlockScroll")
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setStyleSheet("background: transparent; border: none;")
            scroll.viewport().setAutoFillBackground(False)
            scroll.viewport().setStyleSheet("background: transparent;")
            inner = QWidget(scroll)
            inner.setObjectName("workflowAddBlockColumnInner")
            inner_col = QVBoxLayout(inner)
            inner_col.setContentsMargins(0, 0, 0, 0)
            inner_col.setSpacing(1)
            buttons: list[AddBlockMenuItem] = []
            for item in items:
                button = AddBlockMenuItem(item, inner)
                if item.enabled:
                    button.clicked.connect(lambda _=False, catalog=item: self._choose(catalog))
                inner_col.addWidget(button)
                buttons.append(button)
            inner_col.addStretch(1)
            scroll.setWidget(inner)
            col.addWidget(scroll, 1)
            layout.addWidget(column)
            self._sections.append((divider, column, scroll, buttons))
        shell.addWidget(self._card)
        self._set_column_width(self.COL_PREF)
        self.adjustSize()

    def card_rect(self) -> QRect:
        return self._card.geometry()

    def set_allowed_ids(self, allowed: tuple[str, ...] | list[str] | None) -> None:
        """Keep the full catalog visible. Tour only highlights and accepts one id."""
        self._allowed_ids = {str(item) for item in (allowed or ()) if str(item).strip()}
        restrict = bool(self._allowed_ids)
        for divider, column, _scroll, buttons in self._sections:
            column.setVisible(True)
            if divider is not None:
                divider.setVisible(True)
            for button in buttons:
                button.setVisible(True)
                button.set_tour_target(restrict and str(button.item.item_id) in self._allowed_ids)
        self.adjustSize()

    def place_around(self, anchor: QWidget, avoid: QWidget | None = None) -> None:
        area = self._available_rect(anchor)
        avoid_rect = self._global_rect(avoid if avoid is not None else anchor)
        n = max(1, len(self._sections))
        outer = self.SHADOW_PAD * 2 + 16
        inner = max(n, area.width() - outer - (n - 1))
        col_w = max(64, min(self.COL_PREF, inner // n))
        self._set_column_width(col_w)
        self.setMinimumSize(0, 0)
        self.setMaximumWidth(area.width())
        self.setMaximumHeight(area.height())
        gap = self.TOOLBAR_GAP
        space_above = avoid_rect.top() - area.top() - gap
        space_below = area.bottom() - avoid_rect.bottom() - gap
        heading_chrome = 40 + self.SHADOW_PAD * 2 + 16
        needed_scroll = self._needed_scroll_height()
        needed_popup = needed_scroll + heading_chrome
        room = max(space_above, space_below)
        budget = min(area.height(), max(room, min(needed_popup, area.height())))
        self._set_scroll_height(min(needed_scroll, max(88, budget - heading_chrome)))
        self.adjustSize()
        hint = self.sizeHint()
        width = min(hint.width(), area.width())
        height = min(max(hint.height(), 120), budget, area.height())
        self.resize(width, height)
        width = min(self.width(), area.width())
        height = min(self.height(), area.height())
        x = area.x() + max(0, (area.width() - width) // 2)
        x = min(max(x, area.left()), max(area.left(), area.right() - width + 1))
        if space_above >= height:
            y = avoid_rect.top() - gap - height
        elif space_below >= height:
            y = avoid_rect.bottom() + gap
        elif space_above >= space_below:
            y = area.top()
        else:
            y = area.bottom() - height + 1
        y = min(max(y, area.top()), max(area.top(), area.bottom() - height + 1))
        self.move(x, y)

    def _available_rect(self, anchor: QWidget) -> QRect:
        center = anchor.mapToGlobal(anchor.rect().center())
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        if screen is None:
            screen_area = QRect(8, 8, 1600, 900)
        else:
            screen_area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        board = self._workspace_rect(anchor)
        if board is None:
            return screen_area
        inter = board.adjusted(8, 8, -8, -8).intersected(screen_area)
        if inter.width() < 200 or inter.height() < 120:
            return screen_area
        return inter

    def _workspace_rect(self, anchor: QWidget) -> QRect | None:
        widget: QWidget | None = anchor
        while widget is not None:
            if widget.objectName() == "workflowWorkspace":
                return self._global_rect(widget)
            widget = widget.parentWidget()
        return None

    def _global_rect(self, widget: QWidget) -> QRect:
        origin = widget.mapToGlobal(QPoint(0, 0))
        return QRect(origin, widget.size())

    def _item_width(self, column_width: int | None = None) -> int:
        width = self.COL_PREF if column_width is None else column_width
        return max(80, int(width) - 16)

    def _set_column_width(self, width: int) -> None:
        self._col_w = width
        inner = self._item_width(width)
        for _divider, column, _scroll, buttons in self._sections:
            column.setFixedWidth(width)
            for button in buttons:
                button.setMinimumHeight(max(self.ITEM_MIN_H, button.heightForWidth(inner)))

    def _column_content_height(self, buttons: list[AddBlockMenuItem]) -> int:
        inner = self._item_width(self._col_w)
        height = 0
        for index, button in enumerate(buttons):
            height += max(button.heightForWidth(inner), self.ITEM_MIN_H)
            if index:
                height += 1
        return height

    def _needed_scroll_height(self) -> int:
        tallest = 0
        for _divider, _column, _scroll, buttons in self._sections:
            tallest = max(tallest, self._column_content_height(buttons))
        return max(tallest, 1)

    def _set_scroll_height(self, height: int) -> None:
        for _divider, _column, scroll, buttons in self._sections:
            fits = self._column_content_height(buttons) <= height
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if fits else Qt.ScrollBarAsNeeded)
            scroll.setMinimumHeight(height)
            scroll.setMaximumHeight(height)

    def _enabled_buttons(self) -> list[AddBlockMenuItem]:
        buttons: list[AddBlockMenuItem] = []
        for _divider, _column, _scroll, column_buttons in self._sections:
            buttons.extend(button for button in column_buttons if button.item.enabled)
        return buttons

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
            return
        enabled = self._enabled_buttons()
        key = event.key()
        if key in {Qt.Key_Down, Qt.Key_Up, Qt.Key_Left, Qt.Key_Right, Qt.Key_Tab, Qt.Key_Backtab}:
            if enabled:
                self._move_keyboard(key, enabled)
            event.accept()
            return
        if key in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            current = self._kb_button
            if current is not None and current.item.enabled:
                self._choose(current.item)
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_keyboard(self, key: int, enabled: list[AddBlockMenuItem]) -> None:
        if not enabled:
            return
        current = self._kb_button if self._kb_button in enabled else None
        index = enabled.index(current) if current is not None else -1
        if key in {Qt.Key_Down, Qt.Key_Right, Qt.Key_Tab}:
            index = (index + 1) % len(enabled)
        else:
            index = (index - 1) % len(enabled) if index >= 0 else len(enabled) - 1
        if self._kb_button is not None:
            self._kb_button._apply_item_style(hovered=False)
        self._kb_button = enabled[index]
        self._kb_button._apply_item_style(hovered=True)

    def _choose(self, item) -> None:
        if not catalog_item_is_builder_ready(item):
            return
        if self._allowed_ids and str(getattr(item, "item_id", "") or "") not in self._allowed_ids:
            return
        self.item_chosen.emit(item)
        self.hide()


class InspectorTabs(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowInspectorTabs")
        self._index = 0
        self._titles: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar = QWidget(self)
        bar.setObjectName("workflowInspectorTabBar")
        self._bar_row = QHBoxLayout(bar)
        self._bar_row.setContentsMargins(12, 4, 12, 0)
        self._bar_row.setSpacing(0)
        self._buttons: list[QPushButton] = []
        root.addWidget(bar, 0)
        rule = QFrame(self)
        rule.setObjectName("workflowInspectorTabRule")
        rule.setFixedHeight(1)
        root.addWidget(rule)
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("workflowInspectorStack")
        root.addWidget(self._stack, 1)

    def addTab(
        self,
        widget: QWidget,
        title: str,
        *,
        icon=None,
        role: str = "settings",
        enabled: bool = True,
    ) -> int:
        button = QPushButton(self)
        button.setObjectName("workflowInspectorTab")
        button.setProperty("tabRole", role)
        button.setProperty("selected", role == "settings" and enabled)
        button.setProperty("catalogEnabled", bool(enabled))
        button.setText(title)
        button.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        button.setFlat(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setEnabled(bool(enabled))
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setFixedHeight(40)
        button.setIconSize(QSize(16, 16))
        if icon is not None:
            button.setIcon(icon)
        index = len(self._buttons)
        if enabled:
            button.clicked.connect(lambda _=False, at=index: self.setCurrentIndex(at))
        if index:
            split = QFrame(self)
            split.setObjectName("workflowInspectorTabSplit")
            split.setFixedWidth(1)
            split.setFixedHeight(18)
            self._bar_row.addWidget(split, 0, Qt.AlignVCenter)
        self._bar_row.addWidget(button, 1)
        self._buttons.append(button)
        self._titles.append(title)
        self._stack.addWidget(widget)
        button.style().unpolish(button)
        button.style().polish(button)
        return index

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < self._stack.count()):
            return
        button = self._buttons[index]
        if not button.isEnabled() or not bool(button.property("catalogEnabled")):
            return
        self._index = index
        self._stack.setCurrentIndex(index)
        for i, tab in enumerate(self._buttons):
            selected = i == index
            tab.setProperty("selected", selected)
            role = str(tab.property("tabRole") or "")
            enabled = bool(tab.property("catalogEnabled"))
            if not enabled:
                ink = COLORS.text_faint
            elif selected:
                ink = COLORS.target
            else:
                ink = COLORS.text_muted
            if role == "ai":
                tab.setIcon(icon_ai_sparkle(size=14, color=ink))
            else:
                tab.setIcon(catalog_icon("settings", size=16, color=ink))
            tab.style().unpolish(tab)
            tab.style().polish(tab)
        self.currentChanged.emit(index)

    def count(self) -> int:
        return self._stack.count()

    def tabText(self, index: int) -> str:
        if 0 <= index < len(self._titles):
            return self._titles[index]
        return ""


class FolderPickRow(QWidget):
    browse_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowFolderPick")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(4)
        self._value = QLineEdit(self)
        self._value.setObjectName("workflowFolderValue")
        self._value.setReadOnly(True)
        self._value.setCursor(Qt.PointingHandCursor)
        self._value.mousePressEvent = self._press  # type: ignore[method-assign]
        self._browse = QToolButton(self)
        self._browse.setObjectName("workflowFolderBrowse")
        self._browse.setCursor(Qt.PointingHandCursor)
        self._browse.setText("")
        self._browse.setIcon(icon_folder(color=COLORS.text_secondary, size=14))
        self._browse.setIconSize(QSize(14, 14))
        self._browse.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._browse.setFixedSize(26, 26)
        self._browse.setToolTip(t("automation.choose_folder"))
        self._browse.setAccessibleName(t("automation.choose_folder"))
        self._browse.clicked.connect(self.browse_requested.emit)
        row.addWidget(self._value, 1)
        row.addWidget(self._browse, 0, Qt.AlignVCenter)

    def set_name(self, name: str, *, tooltip: str = "") -> None:
        self._value.setText(name)
        self._value.setToolTip(tooltip or name)

    def set_browse_tooltip(self, text: str) -> None:
        self._browse.setToolTip(text)
        self._browse.setAccessibleName(text)

    def _press(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.browse_requested.emit()
            event.accept()
            return
        QLineEdit.mousePressEvent(self._value, event)


class WorkflowEditor(QWidget):
    back_requested = Signal()
    run_requested = Signal(str)
    saved = Signal()

    def __init__(self, service: AutomationService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowEditor")
        paint_canvas(self, fill=COLORS.app_bg)
        self._service = service
        self._workflow_id = ""
        self._created_at = ""
        self._origin = ORIGIN_BROWSE
        self._scope_folder: str | None = None
        self._steps: list[PlanStep] = []
        self._target_mode = TARGET_ALL
        self._selected = -1
        self._updating = False
        self._saved_fingerprint = ""
        self._identity_editing = False
        self._identity_snapshot = ("", "")
        self._tour_catalog_allow: tuple[str, ...] = ()
        self._init_ui()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect() if event is not None else self.rect(), QColor(COLORS.app_bg))
        painter.end()
        super().paintEvent(event)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        root.addWidget(self._make_header())

        body = QHBoxLayout()
        body.setSpacing(16)
        self._workspace = WorkflowWorkspace(self)
        self._canvas = self._workspace.canvas
        self._canvas.block_selected.connect(self._on_block_selected)
        self._canvas.delete_requested.connect(self.remove_block)
        self._canvas.zoom_changed.connect(lambda *_: self._refresh_zoom_label())
        self._workspace.set_toolbar(self._make_toolbar(self._workspace))
        body.addWidget(self._workspace, 1)
        body.addWidget(self._make_side_rail(), 0)
        root.addLayout(body, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("mutedLabel")
        self._status.setWordWrap(True)
        self._status.hide()
        root.addWidget(self._status)

    def _make_header(self) -> QWidget:
        header = QFrame(self)
        header.setObjectName("workflowEditorHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)

        self._back = QPushButton(t("automation.back"), header)
        self._back.setObjectName("workflowBackButton")
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.setToolTip(t("automation.back"))
        self._back.setIcon(icon_back(color=COLORS.text_secondary, size=14))
        self._back.clicked.connect(self.back_requested.emit)
        row.addWidget(self._back, 0, Qt.AlignVCenter)
        header_split = QFrame(header)
        header_split.setObjectName("workflowHeaderDivider")
        header_split.setFixedWidth(1)
        header_split.setFixedHeight(36)
        row.addWidget(header_split, 0, Qt.AlignVCenter)

        identity = QFrame(header)
        identity.setObjectName("workflowIdentity")
        identity.setAttribute(Qt.WA_StyledBackground, True)
        identity.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(12, 8, 12, 8)
        identity_layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._name_label = QLabel("", identity)
        self._name_label.setObjectName("workflowIdentityNameLabel")
        self._name_label.hide()
        self._name = QLineEdit(identity)
        self._name.setObjectName("workflowIdentityName")
        self._name.setPlaceholderText(t("automation.name_placeholder"))
        self._name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._name.setMinimumWidth(200)
        self._name.setFrame(False)
        self._name.setMinimumHeight(32)
        self._name.setMaximumHeight(32)
        self._name.setReadOnly(True)
        self._name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._name.returnPressed.connect(self._apply_identity_edit)
        title_row.addWidget(self._name, 1, Qt.AlignVCenter)

        desc_row = QHBoxLayout()
        desc_row.setContentsMargins(0, 0, 0, 0)
        desc_row.setSpacing(6)
        self._description_label = QLabel("", identity)
        self._description_label.setObjectName("workflowIdentityDescriptionLabel")
        self._description_label.hide()
        self._description = QLineEdit(identity)
        self._description.setObjectName("workflowIdentityDescription")
        self._description.setPlaceholderText(t("automation.description_quiet"))
        self._description.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._description.setMinimumWidth(220)
        self._description.setFrame(False)
        self._description.setMinimumHeight(24)
        self._description.setMaximumHeight(24)
        self._description.setReadOnly(True)
        self._description.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._description.returnPressed.connect(self._apply_identity_edit)
        self._pencil = QToolButton(identity)
        self._pencil.setObjectName("workflowIdentityPencil")
        self._pencil.setCursor(Qt.PointingHandCursor)
        self._pencil.setFixedSize(22, 22)
        self._pencil.setIcon(icon_edit(size=14, color=COLORS.text_muted))
        self._pencil.setToolTip(t("automation.edit_identity"))
        self._pencil.clicked.connect(self._on_identity_pencil)
        self._identity_cancel = QToolButton(identity)
        self._identity_cancel.setObjectName("workflowIdentityCancel")
        self._identity_cancel.setCursor(Qt.PointingHandCursor)
        self._identity_cancel.setText("✕")
        self._identity_cancel.setFixedSize(22, 22)
        self._identity_cancel.setToolTip(t("automation.identity_cancel"))
        self._identity_cancel.setAccessibleName(t("automation.identity_cancel"))
        self._identity_cancel.clicked.connect(self._cancel_identity_edit)
        self._identity_cancel.hide()
        desc_row.addWidget(self._description, 1, Qt.AlignVCenter)
        desc_row.addWidget(self._pencil, 0, Qt.AlignVCenter)
        desc_row.addWidget(self._identity_cancel, 0, Qt.AlignVCenter)
        identity_layout.addLayout(title_row)
        identity_layout.addLayout(desc_row)
        self._name.installEventFilter(self)
        self._description.installEventFilter(self)

        self._unsaved = QLabel(t("automation.unsaved"), identity)
        self._unsaved.setObjectName("workflowUnsavedLabel")
        self._unsaved.hide()
        identity_layout.addWidget(self._unsaved, 0, Qt.AlignLeft)
        row.addWidget(identity, 0, Qt.AlignVCenter)

        self._run_status = QLabel("", header)
        self._run_status.setObjectName("workflowStatusBadge")
        self._run_status.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._run_status.setWordWrap(False)
        self._save = QPushButton(t("automation.save"), header)
        self._save.setObjectName("workflowSaveButton")
        self._save.setCursor(Qt.PointingHandCursor)
        self._save.setIcon(icon_save())
        self._save.clicked.connect(self._save_document)
        self._run = QPushButton(t("automation.run"), header)
        self._run.setObjectName("automationRunButton")
        self._run.setCursor(Qt.PointingHandCursor)
        self._run.setIcon(icon_play(size=14, color="#ffffff"))
        self._run.setToolTip(t("automation.run"))
        self._run.clicked.connect(self._run_document)
        row.addWidget(self._run_status, 0, Qt.AlignVCenter)
        row.addWidget(self._save, 0, Qt.AlignVCenter)
        row.addWidget(self._run, 0, Qt.AlignVCenter)
        row.addStretch(1)
        return header

    def _make_toolbar(self, parent: QWidget) -> QWidget:
        bar = QFrame(parent)
        bar.setObjectName("workflowCanvasToolbar")
        self._toolbar = bar
        apply_card_shadow(bar, role="floating")
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        self._add_block = QToolButton(bar)
        self._add_block.setObjectName("automationAddBlockButton")
        self._add_block.setText(t("automation.add_block"))
        self._add_block.setIcon(icon_add(size=14, color=COLORS.target))
        self._add_block.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._add_block.setToolTip(t("automation.add_block"))
        self._add_block.setCursor(Qt.PointingHandCursor)
        self._add_block.clicked.connect(self._open_add_popup)
        self._sort = QToolButton(bar)
        self._sort.setObjectName("workflowSortButton")
        self._sort.setText(t("automation.sort"))
        self._sort.setIcon(icon_align(size=14, color=COLORS.text_secondary))
        self._sort.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._sort.setToolTip(t("automation.sort_hint"))
        self._sort.setCursor(Qt.PointingHandCursor)
        self._sort.setPopupMode(QToolButton.MenuButtonPopup)
        align_menu = QMenu(self._sort)
        align_menu.addAction(t("automation.sort"), self._sort_blocks)
        self._sort.setMenu(align_menu)
        self._sort.clicked.connect(self._sort_blocks)
        zoom = QFrame(bar)
        zoom.setObjectName("workflowZoomCluster")
        zoom_row = QHBoxLayout(zoom)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(0)
        self._zoom_out = QToolButton(zoom)
        self._zoom_out.setObjectName("workflowZoomButton")
        self._zoom_out.setText("−")
        self._zoom_out.setToolTip(t("automation.zoom_out"))
        self._zoom_out.setCursor(Qt.PointingHandCursor)
        self._zoom_out.clicked.connect(self._zoom_out_clicked)
        self._zoom_label = QLabel("100%", zoom)
        self._zoom_label.setObjectName("workflowZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_in = QToolButton(zoom)
        self._zoom_in.setObjectName("workflowZoomButton")
        self._zoom_in.setText("+")
        self._zoom_in.setToolTip(t("automation.zoom_in"))
        self._zoom_in.setCursor(Qt.PointingHandCursor)
        self._zoom_in.clicked.connect(self._zoom_in_clicked)
        zoom_row.addWidget(self._zoom_out)
        zoom_row.addWidget(self._zoom_label)
        zoom_row.addWidget(self._zoom_in)
        self._fit_button = QToolButton(bar)
        self._fit_button.setObjectName("workflowToolbarButton")
        self._fit_button.setText(t("automation.zoom_fit_short"))
        self._fit_button.setIcon(icon_fit(size=14, color=COLORS.text_secondary))
        self._fit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._fit_button.setToolTip(t("automation.zoom_fit"))
        self._fit_button.setCursor(Qt.PointingHandCursor)
        self._fit_button.clicked.connect(self._fit)
        self._reset_zoom_button = QToolButton(bar)
        self._reset_zoom_button.setObjectName("workflowToolbarButton")
        self._reset_zoom_button.setText(t("automation.zoom_reset_short"))
        self._reset_zoom_button.setIcon(icon_refresh())
        self._reset_zoom_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._reset_zoom_button.setToolTip(t("automation.zoom_reset"))
        self._reset_zoom_button.setCursor(Qt.PointingHandCursor)
        self._reset_zoom_button.clicked.connect(self._reset_zoom)
        row.addWidget(self._add_block)
        row.addWidget(self._sort)
        row.addWidget(zoom)
        row.addWidget(self._fit_button)
        row.addWidget(self._reset_zoom_button)
        self._add_popup = AddBlockPopup(self)
        self._add_popup.item_chosen.connect(self._apply_catalog)
        return bar

    def _make_side_rail(self) -> QWidget:
        rail = WorkflowSideRail(self)
        layout = QVBoxLayout(rail.inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._inspector_tabs = InspectorTabs(rail.inner)
        layout.addWidget(self._inspector_tabs, 1)

        settings = QWidget(self._inspector_tabs)
        settings.setObjectName("workflowInspectorSettings")
        settings.setAttribute(Qt.WA_StyledBackground, True)
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(16, 12, 16, 16)
        settings_layout.setSpacing(12)
        self._inspector_empty = QWidget(settings)
        empty_layout = QVBoxLayout(self._inspector_empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(6)
        overview_title = QLabel(t("automation.inspector_workflow"), self._inspector_empty)
        overview_title.setObjectName("sectionTitle")
        empty_layout.addWidget(overview_title)
        self._overview_summary = QLabel("", self._inspector_empty)
        self._overview_summary.setObjectName("mutedLabel")
        self._overview_summary.setWordWrap(True)
        empty_layout.addWidget(self._overview_summary)
        empty_hint = QLabel(t("automation.inspector_empty"), self._inspector_empty)
        empty_hint.setObjectName("mutedLabel")
        empty_hint.setWordWrap(True)
        empty_layout.addWidget(empty_hint)
        settings_layout.addWidget(self._inspector_empty)

        self._inspector = InspectorPane(settings)
        inspector_layout = self._inspector.layout()
        cat_row = QHBoxLayout()
        cat_row.setContentsMargins(0, 0, 0, 0)
        cat_row.setSpacing(6)
        self._kind_icon = QLabel(self._inspector)
        self._kind_icon.setObjectName("workflowInspectorCategoryIcon")
        self._kind_icon.setFixedSize(16, 16)
        self._kind_label = QLabel("", self._inspector)
        self._kind_label.setObjectName("workflowInspectorCategory")
        cat_row.addWidget(self._kind_icon, 0, Qt.AlignVCenter)
        cat_row.addWidget(self._kind_label, 0, Qt.AlignVCenter)
        cat_row.addStretch(1)
        inspector_layout.addLayout(cat_row)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._block_title = QLabel("", self._inspector)
        self._block_title.setObjectName("workflowInspectorTitle")
        self._block_title.setWordWrap(True)
        self._block_title.setMinimumHeight(32)
        self._block_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._delete_block = _HoverIconButton(
            self._inspector,
            idle_icon=icon_trash(size=18, color=COLORS.text_secondary),
            hover_icon=icon_trash(size=18, color=COLORS.error),
        )
        self._delete_block.setObjectName("workflowDeleteBlockButton")
        self._delete_block.setCursor(Qt.PointingHandCursor)
        self._delete_block.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._delete_block.setAutoRaise(False)
        self._delete_block.setIconSize(QSize(18, 18))
        self._delete_block.setFixedSize(32, 32)
        self._delete_block.setToolTip(t("automation.delete_block_hint"))
        self._delete_block.setAccessibleName(t("automation.delete_block"))
        self._delete_block.clicked.connect(self._delete_selected)
        title_row.addWidget(self._block_title, 1, Qt.AlignVCenter)
        title_row.addWidget(self._delete_block, 0, Qt.AlignTop)
        inspector_layout.addLayout(title_row)
        self._help_label = QLabel("", self._inspector)
        self._help_label.setObjectName("mutedLabel")
        self._help_label.setWordWrap(True)
        inspector_layout.addWidget(self._help_label)
        self._ai_hint = QLabel(t("automation.meaning_ai_hint"), self._inspector)
        self._ai_hint.setObjectName("mutedLabel")
        self._ai_hint.setWordWrap(True)
        inspector_layout.addWidget(self._ai_hint)
        self._folder_group = QFrame(self._inspector)
        self._folder_group.setObjectName("workflowFieldGroup")
        folder_group = QVBoxLayout(self._folder_group)
        folder_group.setContentsMargins(0, 0, 0, 0)
        folder_group.setSpacing(8)
        self._folder_label = QLabel(t("automation.param_folder_path"), self._folder_group)
        self._folder_label.setObjectName("workflowFieldLabel")
        folder_group.addWidget(self._folder_label)
        self._folder_pick = FolderPickRow(self._folder_group)
        self._folder_pick.browse_requested.connect(self._choose_folder)
        folder_group.addWidget(self._folder_pick)
        inspector_layout.addWidget(self._folder_group)
        self._folder_button = self._folder_pick._browse
        self._path_label = QLabel(t("automation.param_path"), self._inspector)
        self._path_label.setObjectName("workflowFieldLabel")
        self._path_label.hide()
        inspector_layout.addWidget(self._path_label)
        self._path = QLineEdit(self._inspector)
        self._path.setObjectName("workflowReadonlyPath")
        self._path.setReadOnly(True)
        self._path.hide()
        inspector_layout.addWidget(self._path)
        self._info_callout = QFrame(self._inspector)
        self._info_callout.setObjectName("workflowInspectorCallout")
        callout_row = QHBoxLayout(self._info_callout)
        callout_row.setContentsMargins(12, 10, 12, 10)
        callout_row.setSpacing(8)
        callout_icon = QLabel(self._info_callout)
        callout_icon.setPixmap(icon_info(size=14, color=COLORS.info).pixmap(14, 14))
        self._info_text = QLabel(t("automation.inspector_callout_folder"), self._info_callout)
        self._info_text.setObjectName("workflowInspectorCalloutText")
        self._info_text.setWordWrap(True)
        callout_row.addWidget(callout_icon, 0, Qt.AlignTop)
        callout_row.addWidget(self._info_text, 1)
        inspector_layout.addWidget(self._info_callout)
        self._choice_group = QFrame(self._inspector)
        self._choice_group.setObjectName("workflowFieldGroup")
        choice_group = QVBoxLayout(self._choice_group)
        choice_group.setContentsMargins(0, 0, 0, 0)
        choice_group.setSpacing(8)
        self._target_combo = QComboBox(self._choice_group)
        self._target_combo.setObjectName("workflowTargetCombo")
        self._target_combo.addItem(t("automation.block_all_images"), TARGET_ALL)
        self._target_combo.addItem(t("automation.block_text_search"), TARGET_TEXT)
        self._target_combo.addItem(t("automation.block_meaning_search"), TARGET_MEANING)
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        choice_group.addWidget(self._target_combo)
        self._action_combo = QComboBox(self._choice_group)
        self._action_combo.setObjectName("workflowActionCombo")
        for action_id in (ACTION_MOVE, ACTION_ADD_TAG, ACTION_REMOVE_TAG):
            self._action_combo.addItem(action_label(action_id), action_id)
        self._action_combo.currentIndexChanged.connect(self._on_action_changed)
        choice_group.addWidget(self._action_combo)
        inspector_layout.addWidget(self._choice_group)
        self._param_group = QFrame(self._inspector)
        self._param_group.setObjectName("workflowFieldGroup")
        param_group = QVBoxLayout(self._param_group)
        param_group.setContentsMargins(0, 0, 0, 0)
        param_group.setSpacing(8)
        self._param_label = QLabel(t("automation.param_query"), self._param_group)
        self._param_label.setObjectName("workflowFieldLabel")
        param_group.addWidget(self._param_label)
        self._param = QLineEdit(self._param_group)
        self._param.setObjectName("workflowParamInput")
        self._param.textChanged.connect(self._on_param_changed)
        param_group.addWidget(self._param)
        inspector_layout.addWidget(self._param_group)
        inspector_layout.addStretch(1)
        settings_layout.addWidget(self._inspector, 1)
        self._inspector.hide()
        self._ai_card = QFrame(settings)
        self._ai_card.setObjectName("workflowAiCard")
        card = QVBoxLayout(self._ai_card)
        card.setContentsMargins(12, 12, 12, 12)
        card.setSpacing(8)
        card_head = QHBoxLayout()
        card_head.setContentsMargins(0, 0, 0, 0)
        ai_name = QLabel(t("automation.draft_title"), self._ai_card)
        ai_name.setObjectName("workflowAiCardTitle")
        ai_badge = QLabel(t("automation.ai_badge"), self._ai_card)
        ai_badge.setObjectName("workflowAiBadge")
        card_head.addWidget(ai_name)
        card_head.addStretch(1)
        card_head.addWidget(ai_badge)
        card_hint = QLabel(t("automation.ai_card_hint"), self._ai_card)
        card_hint.setObjectName("mutedLabel")
        card_hint.setWordWrap(True)
        self._ai_card.setProperty("catalogEnabled", False)
        self._ai_card.setEnabled(False)
        self._open_ai = QPushButton(t("automation.open_ai"), self._ai_card)
        self._open_ai.setObjectName("workflowOpenAiButton")
        self._open_ai.setCursor(Qt.ArrowCursor)
        self._open_ai.setEnabled(False)
        card.addLayout(card_head)
        card.addWidget(card_hint)
        card.addWidget(self._open_ai)
        settings_layout.addStretch(1)
        settings_layout.addWidget(self._ai_card)
        self._ai_card.style().unpolish(self._ai_card)
        self._ai_card.style().polish(self._ai_card)

        ai = QFrame(self._inspector_tabs)
        ai.setObjectName("automationDraftComposer")
        ai_layout = QVBoxLayout(ai)
        ai_layout.setContentsMargins(24, 20, 24, 20)
        ai_layout.setSpacing(12)
        ai_title = QLabel(t("automation.draft_title"), ai)
        ai_title.setObjectName("sectionTitle")
        ai_layout.addWidget(ai_title)
        ai_hint = QLabel(t("automation.draft_hint"), ai)
        ai_hint.setObjectName("mutedLabel")
        ai_hint.setWordWrap(True)
        ai_layout.addWidget(ai_hint)
        self._draft_input = QLineEdit(ai)
        self._draft_input.setObjectName("automationDraftInput")
        self._draft_input.setPlaceholderText(t("automation.draft_placeholder"))
        self._draft_input.returnPressed.connect(self._apply_draft)
        ai_layout.addWidget(self._draft_input)
        self._draft_button = QPushButton(t("automation.draft_action"), ai)
        self._draft_button.setCursor(Qt.PointingHandCursor)
        self._draft_button.clicked.connect(self._apply_draft)
        ai_layout.addWidget(self._draft_button)
        self._draft_status = QLabel("", ai)
        self._draft_status.setObjectName("mutedLabel")
        self._draft_status.setWordWrap(True)
        ai_layout.addWidget(self._draft_status)
        ai_layout.addStretch(1)
        self._inspector_tabs.addTab(
            settings,
            t("automation.inspector_settings"),
            icon=catalog_icon("settings", size=16, color=COLORS.target),
            role="settings",
        )
        self._inspector_tabs.addTab(
            ai,
            t("automation.inspector_ai"),
            icon=icon_ai_sparkle(size=14, color=COLORS.text_faint),
            role="ai",
            enabled=False,
        )
        self._inspector_tabs.setCurrentIndex(0)
        return rail

    def load(self, workflow: Workflow | None, *, scope_folder: str | None = None) -> None:
        self._updating = True
        if workflow is None:
            self._workflow_id = new_workflow_id()
            self._created_at = utc_now()
            self._origin = ORIGIN_BROWSE
            self._scope_folder = str(scope_folder or "").strip() or None
            self._steps = []
            self._target_mode = ""
            self._name.setText(t("automation.untitled"))
            self._description.clear()
            self._set_identity_editing(False)
        else:
            self._workflow_id = workflow.id
            self._created_at = workflow.created_at or utc_now()
            self._scope_folder = workflow.scope_folder or (str(scope_folder or "").strip() or None)
            self._steps = list(workflow.steps)
            self._target_mode = default_target_mode(self._steps, workflow.origin or ORIGIN_BROWSE)
            self._origin = origin_from_target_mode(self._target_mode)
            self._name.setText(workflow.name)
            self._description.setText(workflow.description)
            self._set_identity_editing(False)
        self._sync_identity_labels()
        self._selected = 0
        self._draft_input.clear()
        self._draft_status.clear()
        self._set_editor_status("")
        self._updating = False
        self._refresh_canvas()
        self._canvas.reset_zoom()
        self._selected = 0
        self._show_settings_tab()
        self._refresh_inspector()
        if workflow is None:
            self._saved_fingerprint = ""
            self._refresh_chrome()
        else:
            self._remember_saved()

    def current_steps(self) -> tuple[PlanStep, ...]:
        return assign_step_ids(self._compiled_steps())

    def tour_snapshot(self) -> dict:
        blocks = self.visual_blocks()
        query = str(primary_search_query(self._steps) or "").strip()
        has_text_search = self._target_mode == TARGET_TEXT
        has_add_tag = False
        tag_value = ""
        for block in blocks:
            if block.category != CATEGORY_ACTION or block.step is None:
                continue
            if block.step.action_id == ACTION_ADD_TAG:
                has_add_tag = True
                tag_value = str(block.step.parameters.get("tag") or "").strip()
                break
        return {
            "has_folder": bool(str(self._scope_folder or "").strip()),
            "has_search": any(
                block.category == CATEGORY_TARGET and block.step is not None
                for block in blocks
            ),
            "has_action": any(block.category == CATEGORY_ACTION for block in blocks),
            "has_text_search": has_text_search,
            "has_search_query": has_text_search and bool(query),
            "has_add_tag": has_add_tag,
            "has_tag_value": has_add_tag and bool(tag_value),
            "block_count": len(blocks),
        }

    def set_tour_catalog_allow(self, item_ids: tuple[str, ...] | list[str] | None) -> None:
        self._tour_catalog_allow = tuple(
            str(item).strip() for item in (item_ids or ()) if str(item).strip()
        )

    def focus_tour_inspector(self, kind: str) -> None:
        if kind == "folder":
            for index, block in enumerate(self.visual_blocks()):
                if block.block_id == START_BLOCK_ID:
                    self._selected = index
                    self._show_settings_tab()
                    self._refresh_inspector()
                    return
            return
        want = CATEGORY_TARGET if kind == "search" else CATEGORY_ACTION
        for index, block in enumerate(self.visual_blocks()):
            if block.category == want:
                self._selected = index
                self._show_settings_tab()
                self._refresh_inspector()
                return

    def _notify_tour_blocks(self) -> None:
        from app.prototype_tour.events import emit_tour_event, tour_event_generation
        from app.prototype_tour.models import UI_AUTOMATION_BLOCK_CHANGED

        emit_tour_event(
            UI_AUTOMATION_BLOCK_CHANGED,
            generation=tour_event_generation(),
            **self.tour_snapshot(),
        )

    def visual_blocks(self) -> list[VisualBlock]:
        steps = self.current_steps()
        has_work = any(step.type in {STEP_FIND, STEP_NARROW, STEP_ACTION} for step in steps)
        return visual_blocks_for(
            folder=self._scope_folder,
            origin=self._origin,
            steps=steps,
            include_default_target=has_work or bool(self._target_mode),
        )

    def add_block(self, step: PlanStep, index: int | None = None) -> None:
        kind = block_kind(step)
        actions = [item for item in self._compiled_steps() if item.type == STEP_ACTION or block_kind(item) == KIND_UNSUPPORTED]
        if kind == KIND_FIND:
            self._set_target(TARGET_TEXT if self._origin == "text" else TARGET_MEANING, step.query)
            self._show_settings_tab()
            self._notify_tour_blocks()
            return
        if kind == KIND_SELECT:
            query = primary_search_query(self._steps)
            if self._target_mode == TARGET_ALL:
                self._target_mode = TARGET_MEANING
                self._origin = origin_from_target_mode(self._target_mode)
                query = step.query
            self._steps = list(
                assign_step_ids(
                    [
                        *compile_search_steps(self._target_mode, query),
                        make_select_step(step.query),
                        *actions,
                    ]
                )
            )
            self._selected = 2 if len(self.visual_blocks()) > 2 else 1
            self._refresh_canvas()
            self._show_settings_tab()
            self._notify_tour_blocks()
            return
        at = len(actions) if index is None else max(0, min(index, len(actions)))
        actions.insert(at, step)
        query = primary_search_query(self._steps)
        search = compile_search_steps(self._target_mode, query)
        extra_narrow = [item for item in self._steps if item.type == STEP_NARROW and self._target_mode != TARGET_ALL]
        self._steps = list(assign_step_ids([*search, *extra_narrow, *actions]))
        self._selected = len(self.visual_blocks()) - 1
        self._refresh_canvas()
        self._show_settings_tab()
        self._notify_tour_blocks()

    def remove_block(self, index: int) -> None:
        blocks = self.visual_blocks()
        if not (0 <= index < len(blocks)):
            return
        block = blocks[index]
        if not block_can_delete(block):
            return
        if block.step is None:
            if block.category == CATEGORY_TARGET:
                self._set_target(TARGET_ALL)
            return
        self._steps = [step for step in self.current_steps() if step.step_id != block.step.step_id]
        self._target_mode = default_target_mode(self._steps, self._origin)
        self._origin = origin_from_target_mode(self._target_mode)
        remaining = self.visual_blocks()
        self._selected = min(index, len(remaining) - 1) if remaining else -1
        self._refresh_canvas()
        self._show_settings_tab()
        self._notify_tour_blocks()

    def replace_steps(self, steps: tuple[PlanStep, ...] | list[PlanStep]) -> None:
        self._steps = list(assign_step_ids(steps))
        self._target_mode = default_target_mode(self._steps, self._origin or ORIGIN_MEANING)
        if any(step.type == STEP_FIND for step in self._steps) and self._target_mode == TARGET_ALL:
            self._target_mode = TARGET_MEANING
        self._origin = origin_from_target_mode(self._target_mode)
        self._selected = 0
        self._refresh_canvas()
        self._notify_tour_blocks()

    def build_workflow(self) -> Workflow:
        return Workflow(
            id=self._workflow_id or new_workflow_id(),
            name=self._name.text().strip() or t("automation.untitled"),
            description=self._description.text().strip(),
            created_at=self._created_at or utc_now(),
            updated_at=utc_now(),
            enabled=True,
            scope_folder=self._scope_folder,
            origin=self._origin,
            steps=self.current_steps(),
        )

    def _compiled_steps(self) -> list[PlanStep]:
        extras = [
            step
            for step in self._steps
            if step.type == STEP_ACTION or block_kind(step) == KIND_UNSUPPORTED
        ]
        extra_narrow = [
            step for step in self._steps if step.type == STEP_NARROW and self._target_mode != TARGET_ALL
        ]
        search = compile_search_steps(self._target_mode, primary_search_query(self._steps), extra_narrow)
        return list(assign_step_ids([*search, *extras]))

    def _set_target(self, mode: str, query: str = "") -> None:
        extras = [step for step in self._steps if step.type not in {STEP_FIND, STEP_NARROW}]
        kept_query = query or primary_search_query(self._steps)
        self._target_mode = mode
        self._origin = origin_from_target_mode(mode)
        self._steps = list(assign_step_ids([*compile_search_steps(mode, kept_query), *extras]))
        self._selected = 1
        self._refresh_canvas()
        self._notify_tour_blocks()

    def _refresh_canvas(self) -> None:
        self._updating = True
        blocks = self.visual_blocks()
        self._canvas.set_blocks(blocks, self._selected)
        self._refresh_inspector()
        self._refresh_zoom_label()
        self._refresh_chrome()
        self._updating = False

    def _fingerprint(self) -> str:
        workflow = self.build_workflow()
        parts = [
            workflow.name,
            workflow.description,
            workflow.scope_folder or "",
            workflow.origin,
            str([(step.type, step.query, step.action_id, dict(step.parameters)) for step in workflow.steps]),
        ]
        return "|".join(parts)

    def _remember_saved(self) -> None:
        self._saved_fingerprint = self._fingerprint()
        self._refresh_chrome()

    def _is_dirty(self) -> bool:
        return self._fingerprint() != self._saved_fingerprint

    def _refresh_chrome(self) -> None:
        dirty = self._is_dirty()
        self._unsaved.setVisible(dirty and not self._identity_editing)
        self._sync_identity_labels()
        self._run.setEnabled(not self._identity_editing)
        workflow = self.build_workflow()
        code, key = workflow_run_status(workflow)
        if code == "ready":
            self._run_status.setText(t("automation.status_ready"))
            self._run_status.setProperty("status", "ready")
        else:
            short = {
                "automation.missing_folder": "automation.status_folder_missing",
                "automation.status_need_folder": "automation.status_need_folder",
                "automation.status_need_action": "automation.status_need_action",
                "automation.status_need_query": "automation.status_need_query",
            }.get(key, key)
            self._run_status.setText(t("automation.status_cant_run", reason=t(short)))
            self._run_status.setProperty("status", "blocked")
        self._run_status.style().unpolish(self._run_status)
        self._run_status.style().polish(self._run_status)
        self._overview_summary.setText(
            workflow_step_summary(workflow.steps, folder=workflow.scope_folder, origin=workflow.origin)
        )

    def _set_editor_status(self, text: str = "") -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _sync_identity_labels(self) -> None:
        name = self._name.text().strip() or t("automation.untitled")
        description = self._description.text().strip() or t("automation.description_quiet")
        self._name_label.setText(name)
        self._description_label.setText(description)

    def _set_identity_editing(self, editing: bool) -> None:
        self._identity_editing = editing
        self._name.setReadOnly(not editing)
        self._description.setReadOnly(not editing)
        self._name.setProperty("editing", editing)
        self._description.setProperty("editing", editing)
        self._name.style().unpolish(self._name)
        self._name.style().polish(self._name)
        self._description.style().unpolish(self._description)
        self._description.style().polish(self._description)
        self._identity_cancel.setVisible(editing)
        self._pencil.setToolTip(
            t("automation.identity_apply") if editing else t("automation.edit_identity")
        )
        if hasattr(self, "_run"):
            self._run.setEnabled(not editing)
        if editing:
            self._name.setFocus()
            self._name.selectAll()

    def _on_identity_pencil(self) -> None:
        if self._identity_editing:
            self._apply_identity_edit()
            return
        self._begin_identity_edit()

    def _begin_identity_edit(self) -> None:
        self._identity_snapshot = (self._name.text(), self._description.text())
        self._set_identity_editing(True)

    def _cancel_identity_edit(self) -> None:
        name, description = self._identity_snapshot
        self._updating = True
        self._name.setText(name)
        self._description.setText(description)
        self._updating = False
        self._set_identity_editing(False)
        self._refresh_chrome()

    def _apply_identity_edit(self) -> None:
        if not self._name.text().strip():
            self._set_editor_status(t("automation.name_required"))
            self._name.setFocus()
            return
        self._set_identity_editing(False)
        self._refresh_chrome()

    def eventFilter(self, watched, event) -> bool:
        if self._identity_editing and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._cancel_identity_edit()
                return True
            if event.key() in {Qt.Key_Return, Qt.Key_Enter} and watched is self._name:
                self._apply_identity_edit()
                return True
        return super().eventFilter(watched, event)

    def _on_identity_changed(self, _text: str = "") -> None:
        if self._updating or self._identity_editing:
            return
        self._refresh_chrome()

    def _refresh_zoom_label(self) -> None:
        self._zoom_label.setText(t("automation.zoom_label", percent=round(self._canvas.zoom * 100)))
        if self._workspace is not None:
            self._workspace._position_toolbar()

    def _fit(self) -> None:
        self._canvas.fit_to_workflow()
        self._refresh_zoom_label()
        from app.prototype_tour.events import emit_tour_event, tour_event_generation
        from app.prototype_tour.models import UI_AUTOMATION_FITTED

        emit_tour_event(UI_AUTOMATION_FITTED, generation=tour_event_generation())

    def _reset_zoom(self) -> None:
        self._canvas.reset_zoom()
        self._refresh_zoom_label()

    def _zoom_in_clicked(self) -> None:
        self._canvas.zoom_in()
        self._refresh_zoom_label()

    def _zoom_out_clicked(self) -> None:
        self._canvas.zoom_out()
        self._refresh_zoom_label()

    def _on_block_selected(self, index: int) -> None:
        self._selected = index
        if not self._updating:
            self._refresh_inspector()
            self._show_settings_tab()

    def _selected_block(self) -> VisualBlock | None:
        blocks = self.visual_blocks()
        if 0 <= self._selected < len(blocks):
            return blocks[self._selected]
        return None

    def _show_settings_tab(self) -> None:
        self._inspector_tabs.setCurrentIndex(0)

    def _refresh_inspector(self) -> None:
        block = self._selected_block()
        if block is None:
            self._inspector.hide()
            self._inspector_empty.show()
            return
        self._inspector_empty.hide()
        self._inspector.show()
        category_key = {
            "select": "automation.category_select",
            "trigger": "automation.category_trigger",
            "target": "automation.category_search",
            "condition": "automation.category_condition",
            "action": "automation.category_action",
            "logic": "automation.category_logic",
            "ai": "automation.category_ai",
        }.get(block.category, "automation.category_search")
        style = category_style(block.category)
        self._kind_label.setText(t(category_key))
        self._kind_label.setStyleSheet(f"color: {style.ink};")
        self._kind_icon.setPixmap(catalog_icon(block.icon_key or style.key, size=16, color=style.ink).pixmap(16, 16))
        self._block_title.setText(block.title)
        help_text = self._help_for(block)
        self._help_label.setText(help_text)
        self._help_label.setVisible(bool(help_text))
        self._updating = True
        is_start = block.block_id == START_BLOCK_ID
        is_target = block.category == CATEGORY_TARGET
        is_action = block.category == CATEGORY_ACTION
        is_move = is_action and block.step is not None and block.step.action_id == ACTION_MOVE
        dest_path = str(block.step.parameters.get("destination_name") or "").strip() if is_move and block.step else ""
        if is_start:
            folder_name = folder_display_name(self._scope_folder) if self._scope_folder else t("automation.choose_folder")
            self._folder_label.setText(t("automation.param_folder_path"))
            self._folder_pick.set_name(folder_name, tooltip=self._scope_folder or "")
            self._folder_pick.set_browse_tooltip(t("automation.choose_folder"))
        elif is_move:
            folder_name = folder_display_name(dest_path) if dest_path else ""
            self._folder_label.setText(t("automation.param_destination"))
            self._folder_pick.set_name(
                folder_name,
                tooltip=dest_path or t("automation.choose_destination"),
            )
            self._folder_pick.set_browse_tooltip(t("automation.choose_destination"))
        self._folder_label.setVisible(is_start or is_move)
        self._folder_pick.setVisible(is_start or is_move)
        self._path_label.setVisible(False)
        self._path.setVisible(False)
        if is_start:
            self._path.setText(self._scope_folder or "")
        self._info_callout.setVisible(is_start)
        self._target_combo.setVisible(is_target)
        if is_target:
            idx = self._target_combo.findData(self._target_mode if self._target_mode in {TARGET_ALL, TARGET_TEXT, TARGET_MEANING} else TARGET_ALL)
            self._target_combo.setCurrentIndex(max(0, idx))
        self._sync_action_combo(block.step.action_id if is_action and block.step is not None else "")
        self._action_combo.setVisible(is_action)
        self._ai_hint.setVisible(block.uses_ai or (is_target and self._target_mode == TARGET_MEANING))
        show_query = is_target and self._target_mode in {TARGET_TEXT, TARGET_MEANING}
        show_param = False
        if is_start or is_move:
            self._param.clear()
            self._param.setEnabled(True)
        elif show_query:
            self._param_label.setText(t("automation.param_query"))
            self._param.setEnabled(True)
            self._param.setText(primary_search_query(self._steps))
            show_param = True
        elif is_action and block.step is not None:
            self._param_label.setText(self._param_label_for(block.step.action_id))
            self._param.setEnabled(True)
            self._param.setText(self._param_value(block.step))
            show_param = True
        elif block.visual_kind == KIND_UNSUPPORTED:
            self._param_label.setText(t("automation.block_unsupported_hint"))
            self._param.clear()
            self._param.setEnabled(False)
            show_param = True
        else:
            self._param.clear()
            self._param.setEnabled(True)
        self._param.setVisible(show_param)
        self._param_label.setVisible(show_param)
        self._folder_group.setVisible(is_start or is_move)
        self._choice_group.setVisible(is_target or is_action)
        self._param_group.setVisible(show_param)
        can_delete = block_can_delete(block)
        self._delete_block.setVisible(can_delete)
        self._delete_block.setEnabled(can_delete)
        self._updating = False

    def _help_for(self, block: VisualBlock) -> str:
        if block.block_id == START_BLOCK_ID:
            return t("automation.help_select_folder")
        if block.category == CATEGORY_TARGET:
            if block.target_mode == TARGET_TEXT:
                return t("automation.help_target_text")
            if block.target_mode == TARGET_MEANING:
                return t("automation.help_target_meaning")
            return t("automation.help_target_all")
        if block.category == CATEGORY_ACTION and block.step is not None:
            return {
                ACTION_ADD_TAG: t("automation.help_action_add_tag"),
                ACTION_REMOVE_TAG: t("automation.help_action_remove_tag"),
                ACTION_MOVE: t("automation.help_action_move"),
                ACTION_CREATE_FOLDER: t("automation.help_action_create_folder"),
                ACTION_RENAME: t("automation.help_action_rename"),
            }.get(block.step.action_id, "")
        return ""

    def _sync_action_combo(self, action_id: str) -> None:
        ids = [ACTION_MOVE, ACTION_ADD_TAG, ACTION_REMOVE_TAG]
        if action_id and action_id not in ids:
            ids.append(action_id)
        current = str(self._action_combo.currentData() or "")
        existing = [self._action_combo.itemData(index) for index in range(self._action_combo.count())]
        if existing != ids:
            self._action_combo.blockSignals(True)
            self._action_combo.clear()
            for item_id in ids:
                self._action_combo.addItem(action_label(item_id), item_id)
            self._action_combo.blockSignals(False)
        if action_id:
            idx = self._action_combo.findData(action_id)
            if idx >= 0 and action_id != current:
                self._action_combo.setCurrentIndex(idx)

    def _param_label_for(self, action_id: str) -> str:
        if action_id in {ACTION_ADD_TAG, ACTION_REMOVE_TAG}:
            return t("automation.param_tag")
        if action_id == ACTION_MOVE:
            return t("automation.param_destination")
        if action_id == ACTION_CREATE_FOLDER:
            return t("automation.param_folder_name")
        if action_id == ACTION_RENAME:
            return t("automation.param_new_name")
        return t("automation.param_query")

    def _param_value(self, step: PlanStep) -> str:
        if step.action_id in {ACTION_ADD_TAG, ACTION_REMOVE_TAG}:
            return str(step.parameters.get("tag") or "")
        if step.action_id == ACTION_MOVE:
            return str(step.parameters.get("destination_name") or "")
        if step.action_id == ACTION_CREATE_FOLDER:
            return str(step.parameters.get("name") or "")
        if step.action_id == ACTION_RENAME:
            return str(step.parameters.get("new_name") or "")
        return ""

    def _on_param_changed(self, text: str) -> None:
        if self._updating:
            return
        block = self._selected_block()
        if block is None:
            return
        if block.category == CATEGORY_TARGET:
            extras = [step for step in self._steps if step.type not in {STEP_FIND, STEP_NARROW}]
            self._steps = list(assign_step_ids([*compile_search_steps(self._target_mode, text.strip()), *extras]))
            self._canvas.set_blocks(self.visual_blocks(), self._selected)
            self._refresh_chrome()
            self._notify_tour_blocks()
            return
        if block.category != CATEGORY_ACTION or block.step is None:
            return
        step = block.step
        key = {
            ACTION_ADD_TAG: "tag",
            ACTION_REMOVE_TAG: "tag",
            ACTION_MOVE: "destination_name",
            ACTION_CREATE_FOLDER: "name",
            ACTION_RENAME: "new_name",
        }.get(step.action_id)
        parameters = dict(step.parameters)
        if key:
            parameters[key] = text.strip()
            parameters = sanitize_step_parameters(step.action_id, parameters)
        self._steps = [
            PlanStep(step_id=item.step_id, type=STEP_ACTION, action_id=item.action_id, parameters=parameters)
            if item.step_id == step.step_id
            else item
            for item in self.current_steps()
        ]
        self._canvas.set_blocks(self.visual_blocks(), self._selected)
        self._refresh_chrome()
        self._notify_tour_blocks()

    def _on_target_changed(self) -> None:
        if self._updating:
            return
        mode = str(self._target_combo.currentData() or TARGET_ALL)
        self._set_target(mode, primary_search_query(self._steps))

    def _on_action_changed(self) -> None:
        if self._updating:
            return
        block = self._selected_block()
        if block is None or block.step is None or block_kind(block.step) != KIND_ACT:
            return
        action_id = str(self._action_combo.currentData() or "")
        replacement = make_act_step(action_id)
        self._steps = [
            replacement if item.step_id == block.step.step_id else item
            for item in self.current_steps()
        ]
        self._steps = list(assign_step_ids(self._steps))
        self._refresh_canvas()
        self._notify_tour_blocks()

    def _choose_folder(self) -> None:
        block = self._selected_block()
        if block is not None and block.step is not None and block.step.action_id == ACTION_MOVE:
            self._choose_move_destination(block.step)
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            t("images.choose_folder_title"),
            self._scope_folder or "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        self._scope_folder = selected
        self._refresh_canvas()
        self._notify_tour_blocks()

    def _choose_move_destination(self, step: PlanStep) -> None:
        current = str(step.parameters.get("destination_name") or "").strip()
        start = current if Path(current).is_absolute() else (self._scope_folder or "")
        selected = QFileDialog.getExistingDirectory(
            self,
            t("automation.choose_destination"),
            start,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        self._set_action_parameter(step, "destination_name", selected)

    def _set_action_parameter(self, step: PlanStep, key: str, value: str) -> None:
        parameters = sanitize_step_parameters(step.action_id, {**dict(step.parameters), key: value})
        self._steps = [
            PlanStep(step_id=item.step_id, type=STEP_ACTION, action_id=item.action_id, parameters=parameters)
            if item.step_id == step.step_id
            else item
            for item in self.current_steps()
        ]
        self._canvas.set_blocks(self.visual_blocks(), self._selected)
        self._refresh_inspector()
        self._refresh_chrome()

    def _delete_selected(self) -> None:
        self.remove_block(self._selected)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.update()
        workspace = getattr(self, "_workspace", None)
        if workspace is not None:
            workspace.update()
            canvas = getattr(workspace, "canvas", None)
            if canvas is not None and canvas.viewport() is not None:
                canvas.viewport().update()
        if getattr(self, "_add_popup", None) is not None and self._add_popup.isVisible():
            self._place_add_popup()
            QTimer.singleShot(0, self._place_add_popup_if_open)

    def _place_add_popup_if_open(self) -> None:
        popup = getattr(self, "_add_popup", None)
        if popup is not None and popup.isVisible():
            self._place_add_popup()

    def _open_add_popup(self) -> None:
        popup = self._add_popup
        if popup.isVisible():
            popup.hide()
            return
        popup.set_allowed_ids(self._tour_catalog_allow)
        popup.show()
        popup.raise_()
        from app.ui.page_motion import fade_in_window

        fade_in_window(popup)
        self._place_add_popup()
        if self._workspace.toolbar is not None:
            self._workspace.toolbar.raise_()

    def _place_add_popup(self) -> None:
        toolbar = self._workspace.toolbar or getattr(self, "_toolbar", None)
        self._add_popup.place_around(self._add_block, avoid=toolbar)

    def _sort_blocks(self) -> None:
        self._canvas.align_blocks()
        self._refresh_zoom_label()

    def _apply_catalog(self, item) -> None:
        if not catalog_item_is_builder_ready(item):
            return
        allowed = self._tour_catalog_allow
        if allowed and str(getattr(item, "item_id", "") or "") not in allowed:
            return
        if item.category == CATEGORY_SELECT:
            self._selected = 0
            self._refresh_canvas()
            self._show_settings_tab()
            return
        if item.category == CATEGORY_TARGET:
            self._set_target(item.item_id, primary_search_query(self._steps))
            self._show_settings_tab()
            return
        self.add_block(make_act_step(item.item_id))

    def _apply_draft(self) -> None:
        text = self._draft_input.text().strip()
        outcome = draft_workflow_from_text(
            text,
            SearchResultContext(scope_folder=self._scope_folder, origin=self._origin or ORIGIN_MEANING),
            allow_ai=True,
        )
        if outcome.steps:
            if self._scope_folder is None:
                self._scope_folder = None
            self.replace_steps(outcome.steps)
            if not self._name.text().strip() or self._name.text().strip() == t("automation.untitled"):
                self._name.setText(text[:80] or t("automation.untitled"))
        if outcome.ok:
            self._draft_status.setText(t("automation.draft_applied"))
            self._set_editor_status(
                workflow_step_summary(outcome.steps, folder=self._scope_folder, origin=self._origin)
            )
            self._show_settings_tab()
            return
        key = outcome.message_key or "automation.draft_clarify"
        self._draft_status.setText(outcome.message or t(key))

    def _save_document(self) -> bool:
        workflow = self.build_workflow()
        try:
            saved = self._service.save_draft(workflow)
        except WorkflowValidationError as exc:
            self._set_editor_status(t(exc.validation.message_key or "automation.invalid"))
            return False
        self._workflow_id = saved.id
        self._created_at = saved.created_at or self._created_at
        self._set_editor_status(t("automation.saved"))
        self._remember_saved()
        self.saved.emit()
        return True

    def _run_document(self) -> None:
        if self._identity_editing:
            return
        if not self._save_document():
            return
        workflow = self.build_workflow()
        validation = validate_workflow(workflow)
        if not validation.ok:
            self._set_editor_status(t(validation.message_key or "automation.invalid"))
            return
        try:
            self._service.save(workflow)
        except WorkflowValidationError:
            self._set_editor_status(t("automation.invalid"))
            return
        self._remember_saved()
        self.run_requested.emit(workflow.id)


def current_scope_folder(folder: Path | str | None) -> str | None:
    text = str(folder or "").strip()
    return text or None
