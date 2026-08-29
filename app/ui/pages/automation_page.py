"""Automation list and Workflow editor. Execution stays in Automation v0."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.automation import (
    AutomationService,
    Workflow,
    format_list_date,
    workflow_list_status,
    workflow_run_status,
    workflow_step_summary,
)
from app.prototype_tour.events import emit_tour_event, tour_event_generation
from app.prototype_tour.models import UI_AUTOMATION_OPENED, UI_AUTOMATION_SAVED
from app.i18n import t
from app.ui.automation_save_dialog import AutomationSaveDialog
from app.ui.design_tokens import (
    AUTOMATION_LIST_HEADER_PAD,
    AUTOMATION_LIST_RUN_HEADER_PAD,
    COLORS,
    RADIUS_CARD,
    paint_canvas,
)
from app.ui.icons import icon_edit, icon_play, icon_rename, icon_trash
from app.ui.page_header import PAGE_HEADER_TITLE_SPACING
from app.ui.page_motion import crossfade_stacked
from app.ui.scroll_page import make_page_scroll
from app.ui.search_busy import SearchBusySpinner
from app.ui.text_select import enable_label_text_selection
from app.ui.workflow_editor import WorkflowEditor

_COL_RUN = 0
_COL_NAME = 1
_COL_SUMMARY = 2
_COL_STATUS = 3
_COL_CREATED = 4
_COL_LAST_RUN = 5
_COL_ACTIONS = 6
_LIST_COLUMNS = 7
_COL_RUN_WIDTH = 72
_COL_STATUS_WIDTH = 188
_COL_ACTIONS_WIDTH = 140


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


class _CardCorner(QWidget):
    """Opaque painted corner. Masks and QSS radius square off QTableWidget edges."""

    def __init__(self, parent: QWidget, corner: str) -> None:
        super().__init__(parent)
        self._corner = corner
        self.setObjectName("automationListCorner")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(RADIUS_CARD + 2, RADIUS_CARD + 2)

    def paintEvent(self, event) -> None:
        del event
        radius = float(RADIUS_CARD)
        size = float(self.width())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(COLORS.app_bg))
        if self._corner in {"tl", "tr"}:
            interior = QColor(COLORS.surface_subtle)
        else:
            interior = QColor(COLORS.card_bg)
        if self._corner == "tl":
            box = QRectF(0.5, 0.5, radius * 2, radius * 2)
        elif self._corner == "tr":
            box = QRectF(size - 0.5 - radius * 2, 0.5, radius * 2, radius * 2)
        elif self._corner == "bl":
            box = QRectF(0.5, size - 0.5 - radius * 2, radius * 2, radius * 2)
        else:
            box = QRectF(
                size - 0.5 - radius * 2,
                size - 0.5 - radius * 2,
                radius * 2,
                radius * 2,
            )
        painter.setPen(Qt.NoPen)
        painter.setBrush(interior)
        painter.drawRoundedRect(box, radius, radius)
        pen = QPen(QColor(COLORS.border_subtle), 1)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box, radius, radius)


class _AutomationListCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("automationListCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self._corners = [
            _CardCorner(self, "tl"),
            _CardCorner(self, "tr"),
            _CardCorner(self, "bl"),
            _CardCorner(self, "br"),
        ]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_corners()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_corners()

    def _place_corners(self) -> None:
        width = self.width()
        height = self.height()
        self._corners[0].move(0, 0)
        self._corners[1].move(width - self._corners[1].width(), 0)
        self._corners[2].move(0, height - self._corners[2].height())
        self._corners[3].move(
            width - self._corners[3].width(),
            height - self._corners[3].height(),
        )
        for corner in self._corners:
            corner.show()
            corner.raise_()


class _AutomationStack(QStackedWidget):
    """Fills on resize so the native HWND never shows through around the editor."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("automationStack")
        paint_canvas(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect() if event is not None else self.rect(), QColor(COLORS.app_bg))
        painter.end()
        super().paintEvent(event)


class AutomationPage(QWidget):
    run_requested = Signal(str)

    def __init__(
        self,
        service: AutomationService | None = None,
        parent=None,
        *,
        scope_folder_provider: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("automationPage")
        self._service = service or AutomationService()
        self._scope_folder_provider = scope_folder_provider
        self._cards: list[QWidget] = []
        self._running_ids: set[str] = set()
        self._aligning_icons = False
        self._init_ui()
        enable_label_text_selection(self)

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = _AutomationStack(self)
        outer.addWidget(self._stack)
        self._list_page = self._make_list_page()
        self._editor = WorkflowEditor(self._service, self)
        self._editor.setObjectName("workflowEditor")
        self._editor.back_requested.connect(self._show_list)
        self._editor.run_requested.connect(self.run_requested.emit)
        self._editor.saved.connect(self._on_editor_saved)
        self._stack.addWidget(self._list_page)
        self._stack.addWidget(self._editor)
        paint_canvas(self._list_page)
        paint_canvas(self._editor)

    def _make_list_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("automationListPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = make_page_scroll(page)
        outer.addWidget(scroll)
        content = QWidget(scroll)
        content.setObjectName("settingsContentColumn")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(12)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)
        title = QLabel(t("automation.title"), content)
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        new_btn = QPushButton(t("automation.new"), content)
        new_btn.setObjectName("automationNewButton")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._new_workflow)
        self._new_button = new_btn
        title_row.addWidget(title, 1, Qt.AlignVCenter)
        title_row.addWidget(new_btn, 0, Qt.AlignVCenter)
        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(PAGE_HEADER_TITLE_SPACING)
        heading.addLayout(title_row)
        subtitle = QLabel(t("automation.subtitle"), content)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        heading.addWidget(subtitle)
        layout.addLayout(heading)
        hint = QLabel(t("automation.hint"), content)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(hint)
        self._table = QTableWidget(0, _LIST_COLUMNS, content)
        self._table.setObjectName("automationWorkflowTable")
        self._table.setHorizontalHeaderLabels(
            [
                t("automation.run"),
                t("automation.list_name"),
                t("automation.list_summary"),
                t("automation.list_status"),
                t("automation.list_created"),
                t("automation.list_last_run"),
                t("automation.list_actions"),
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setDefaultSectionSize(64)
        header = self._table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(_COL_RUN, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(_COL_SUMMARY, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_STATUS, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_CREATED, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_LAST_RUN, QHeaderView.Fixed)
        header.setSectionResizeMode(_COL_ACTIONS, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_RUN, _COL_RUN_WIDTH)
        self._table.setColumnWidth(_COL_NAME, 176)
        self._table.setColumnWidth(_COL_STATUS, _COL_STATUS_WIDTH)
        self._table.setColumnWidth(_COL_CREATED, 148)
        self._table.setColumnWidth(_COL_LAST_RUN, 148)
        self._table.setColumnWidth(_COL_ACTIONS, _COL_ACTIONS_WIDTH)
        self._table.setMinimumHeight(280)
        self._table.setFrameShape(QFrame.NoFrame)
        self._table.setAttribute(Qt.WA_StyledBackground, True)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        list_card = _AutomationListCard(content)
        list_card_layout = QVBoxLayout(list_card)
        list_card_layout.setContentsMargins(0, 0, 0, 0)
        list_card_layout.setSpacing(0)
        list_card_layout.addWidget(self._table)
        layout.addWidget(list_card, 1)
        self._list_card = list_card
        list_card._place_corners()
        self._empty = QLabel(t("automation.empty"), self._table.viewport())
        self._empty.setObjectName("automationEmptyHint")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._aligning_icons = False
        self._table.viewport().installEventFilter(self)
        self._table.horizontalHeader().installEventFilter(self)
        self._list_host = self._table
        self._list_header = self._table.horizontalHeader()
        return page

    def refresh(self) -> None:
        self._show_list()

    def is_editing(self) -> bool:
        return self._stack.currentWidget() is self._editor

    def set_running(self, workflow_id: str, running: bool) -> None:
        workflow_id = str(workflow_id or "")
        if not workflow_id:
            return
        if running:
            self._running_ids.add(workflow_id)
            self._show_list()
            return
        self._running_ids.discard(workflow_id)
        self._reload_cards()

    def _show_list(self) -> None:
        self._reload_cards()
        crossfade_stacked(self._stack, self._list_page)

    def tour_list_run_button(self) -> QPushButton | None:
        first = None
        for row in range(self._table.rowCount()):
            host = self._table.cellWidget(row, _COL_RUN)
            if host is None:
                continue
            run = host.findChild(QPushButton, "automationListRunButton")
            if run is None:
                continue
            if first is None:
                first = run
            if run.isEnabled():
                return run
        return first

    def _reload_cards(self) -> None:
        self._cards.clear()
        self._table.setRowCount(0)
        workflows = self._service.list_workflows()
        self._empty.setVisible(not workflows)
        self._table.setRowCount(len(workflows))
        for row, workflow in enumerate(workflows):
            self._fill_row(row, workflow)
        self._table.resizeColumnToContents(_COL_STATUS)
        self._table.setColumnWidth(
            _COL_STATUS, max(self._table.columnWidth(_COL_STATUS), _COL_STATUS_WIDTH)
        )
        self._place_empty_hint()
        if hasattr(self, "_list_card"):
            self._list_card._place_corners()
        QTimer.singleShot(0, self._align_icon_columns_to_headers)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Resize:
            if watched is self._table.viewport():
                self._place_empty_hint()
            if watched in {self._table.viewport(), self._table.horizontalHeader()}:
                self._align_icon_columns_to_headers()
        return super().eventFilter(watched, event)

    def _header_label_left(self, column: int) -> int:
        header = self._table.horizontalHeader()
        origin = QPoint(header.sectionViewportPosition(column), 0)
        pad = AUTOMATION_LIST_RUN_HEADER_PAD if column == _COL_RUN else AUTOMATION_LIST_HEADER_PAD
        return header.mapTo(self._table, origin).x() + pad

    def _align_control_to_header(self, column: int, control: QWidget) -> None:
        host = control.parentWidget()
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            return
        header_left = self._header_label_left(column)
        control_left = control.mapTo(self._table, QPoint(0, 0)).x()
        delta = header_left - control_left
        if delta == 0:
            return
        margins = layout.contentsMargins()
        layout.setContentsMargins(max(0, margins.left() + delta), margins.top(), margins.right(), margins.bottom())

    def _align_icon_columns_to_headers(self) -> None:
        table = getattr(self, "_table", None)
        if self._aligning_icons or table is None:
            return
        try:
            visible = table.isVisible()
        except RuntimeError:
            return
        if not visible:
            return
        self._aligning_icons = True
        try:
            for row in range(table.rowCount()):
                run_host = table.cellWidget(row, _COL_RUN)
                if run_host is not None:
                    run = run_host.findChild(QPushButton, "automationListRunButton")
                    if run is not None:
                        self._align_control_to_header(_COL_RUN, run)
                status_host = table.cellWidget(row, _COL_STATUS)
                if status_host is not None:
                    badge = status_host.findChild(QLabel, "automationStatusBadge")
                    if badge is not None:
                        self._align_control_to_header(_COL_STATUS, badge)
                action_host = table.cellWidget(row, _COL_ACTIONS)
                if action_host is not None:
                    first = action_host.findChild(QToolButton, "automationRowIconButton")
                    if first is not None:
                        self._align_control_to_header(_COL_ACTIONS, first)
        except RuntimeError:
            return
        finally:
            self._aligning_icons = False

    def _place_empty_hint(self) -> None:
        viewport = self._table.viewport()
        self._empty.setGeometry(viewport.rect().adjusted(24, 16, -24, -16))
        self._empty.raise_()

    def _scope_folder(self) -> str | None:
        if self._scope_folder_provider is None:
            return None
        try:
            value = self._scope_folder_provider()
        except Exception:
            return None
        text = str(value or "").strip()
        return text or None

    def _new_workflow(self) -> None:
        self.open_draft(None)

    def open_draft(self, workflow: Workflow | None = None) -> None:
        self._editor.load(workflow, scope_folder=getattr(workflow, "scope_folder", None) or self._scope_folder())
        crossfade_stacked(self._stack, self._editor)
        emit_tour_event(UI_AUTOMATION_OPENED, generation=tour_event_generation())

    def _on_editor_saved(self) -> None:
        self._reload_cards()
        emit_tour_event(UI_AUTOMATION_SAVED, generation=tour_event_generation())

    def _edit_workflow(self, workflow_id: str) -> None:
        workflow = self._service.get(workflow_id)
        if workflow is None:
            return
        self.open_draft(workflow)

    def _fill_row(self, row: int, workflow: Workflow) -> None:
        run_code, run_key = workflow_run_status(workflow)
        can_run = run_code == "ready"
        self._table.setCellWidget(row, _COL_RUN, self._make_run_cell(workflow, can_run, run_key))

        name = QTableWidgetItem(workflow.name)
        name_font = QFont(name.font())
        name_font.setWeight(QFont.DemiBold)
        name_font.setPixelSize(13)
        name.setFont(name_font)
        name.setForeground(QColor(COLORS.text_strong))
        name.setToolTip(workflow.description or workflow.name)
        summary_text = workflow_step_summary(
            workflow.steps, folder=workflow.scope_folder, origin=workflow.origin
        )
        cell_font = QFont(name.font())
        cell_font.setWeight(QFont.Normal)
        cell_font.setPixelSize(13)
        summary = QTableWidgetItem(summary_text)
        summary.setFont(cell_font)
        summary.setForeground(QColor(COLORS.text_muted))
        summary.setToolTip(summary_text)
        created_text = format_list_date(workflow.created_at, with_time=True) or "—"
        created = QTableWidgetItem(created_text)
        created.setFont(cell_font)
        created.setForeground(QColor(COLORS.text_secondary))
        created.setToolTip(created_text)
        last_run_text = format_list_date(workflow.last_run_at, with_time=True) or t(
            "automation.last_run_none"
        )
        last_run = QTableWidgetItem(last_run_text)
        last_run.setFont(cell_font)
        last_run.setForeground(QColor(COLORS.text_secondary))
        last_run.setToolTip(last_run_text)
        for item in (name, summary, created, last_run):
            item.setFlags(Qt.ItemIsEnabled)
        self._table.setItem(row, _COL_NAME, name)
        self._table.setItem(row, _COL_SUMMARY, summary)
        self._table.setCellWidget(row, _COL_STATUS, self._make_status_cell(workflow))
        self._table.setItem(row, _COL_CREATED, created)
        self._table.setItem(row, _COL_LAST_RUN, last_run)
        actions = self._make_actions_cell(workflow)
        self._table.setCellWidget(row, _COL_ACTIONS, actions)
        self._cards.append(actions)

    def _make_run_cell(self, workflow: Workflow, can_run: bool, run_key: str) -> QWidget:
        running = workflow.id in self._running_ids
        can_run = can_run and not running
        host = QWidget(self._table)
        host.setObjectName("automationRowRun")
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(0)
        run = QPushButton(host)
        run.setObjectName("automationListRunButton")
        run.setCursor(Qt.PointingHandCursor if can_run else Qt.ArrowCursor)
        run.setIcon(
            icon_play(size=14, color="#ffffff" if can_run else COLORS.text_faint)
        )
        run.setIconSize(QSize(14, 14))
        run.setFixedSize(32, 32)
        run.setEnabled(can_run)
        if running:
            run.setToolTip(t("automation.status_running"))
        else:
            run.setToolTip(t("automation.run") if can_run else t(run_key))
        run.setAccessibleName(t("automation.run"))
        run.clicked.connect(lambda: self.run_requested.emit(workflow.id))
        row.addWidget(run, 0, Qt.AlignVCenter)
        row.addStretch(1)
        return host

    def _make_status_cell(self, workflow: Workflow) -> QWidget:
        running = workflow.id in self._running_ids
        if running:
            kind, label_key, hint_key = (
                "running",
                "automation.status_running",
                "automation.status_running_hint",
            )
        else:
            kind, label_key, hint_key = workflow_list_status(workflow)
        host = QWidget(self._table)
        host.setObjectName("automationStatusCell")
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(8 if running else 0)
        badge = QLabel(t(label_key), host)
        badge.setObjectName("automationStatusBadge")
        badge.setProperty("status", kind)
        badge.setAlignment(Qt.AlignCenter)
        badge.setWordWrap(False)
        badge.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        badge.setToolTip(t(hint_key))
        badge.setTextInteractionFlags(Qt.NoTextInteraction)
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        badge.adjustSize()
        row.addWidget(badge, 0, Qt.AlignVCenter)
        if running:
            spinner = SearchBusySpinner(host, size=16)
            spinner.setObjectName("automationStatusSpinner")
            row.addWidget(spinner, 0, Qt.AlignVCenter)
        row.addStretch(1)
        return host

    def _make_actions_cell(self, workflow: Workflow) -> QWidget:
        actions = QWidget(self._table)
        actions.setObjectName("automationRowActions")
        actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        action_row = QHBoxLayout(actions)
        action_row.setContentsMargins(0, 0, 8, 0)
        action_row.setSpacing(4)
        edit = self._icon_action_button(
            actions,
            tooltip=t("automation.edit"),
            icon=icon_edit(size=18, color=COLORS.text_secondary),
            object_name="automationRowIconButton",
        )
        edit.clicked.connect(lambda: self._edit_workflow(workflow.id))
        rename = self._icon_action_button(
            actions,
            tooltip=t("automation.rename"),
            icon=icon_rename(size=18, color=COLORS.text_secondary),
            object_name="automationRowIconButton",
        )
        rename.clicked.connect(lambda: self._rename(workflow.id))
        delete = self._icon_action_button(
            actions,
            tooltip=t("automation.delete"),
            icon=icon_trash(size=18, color=COLORS.text_secondary),
            object_name="automationRowDeleteButton",
            hover_icon=icon_trash(size=18, color=COLORS.error),
        )
        delete.clicked.connect(lambda: self._delete(workflow.id))
        action_row.addWidget(edit)
        action_row.addWidget(rename)
        action_row.addWidget(delete)
        action_row.addStretch(1)
        return actions

    def _icon_action_button(
        self,
        parent: QWidget,
        *,
        tooltip: str,
        icon,
        object_name: str,
        hover_icon=None,
    ) -> QToolButton:
        if hover_icon is not None:
            button = _HoverIconButton(parent, idle_icon=icon, hover_icon=hover_icon)
        else:
            button = QToolButton(parent)
            button.setIcon(icon)
        button.setObjectName(object_name)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(False)
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(32, 32)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        return button

    def _rename(self, workflow_id: str) -> None:
        current = self._service.get(workflow_id)
        if current is None:
            return
        dialog = AutomationSaveDialog(
            self,
            title=t("automation.rename_title"),
            name=current.name,
            description=current.description,
            confirm_label=t("automation.rename"),
        )
        if dialog.exec() != dialog.Accepted:
            return
        self._service.rename(
            workflow_id, dialog.workflow_name(), description=dialog.workflow_description()
        )
        self._reload_cards()

    def _delete(self, workflow_id: str) -> None:
        current = self._service.get(workflow_id)
        if current is None:
            return
        reply = QMessageBox.question(
            self,
            t("common.confirm_delete"),
            t("automation.delete_confirm", name=current.name),
        )
        if reply != QMessageBox.Yes:
            return
        self._service.delete(workflow_id)
        self._reload_cards()
