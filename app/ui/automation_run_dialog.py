"""Confirm an Automation run without leaving the Automation page."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.automation import Workflow, workflow_run_status
from app.automation.blocks import block_summary, block_title, folder_display_name
from app.i18n import t
from app.ui.page_motion import AnimatedDialog
from app.workspace.plan import STEP_ACTION, STEP_FIND, STEP_NARROW


class AutomationRunDialog(AnimatedDialog):
    """Simple review popup: show the planned steps, then Run or Cancel."""

    def __init__(self, parent: QWidget | None = None, *, workflow: Workflow) -> None:
        super().__init__(parent)
        self._workflow = workflow
        self.setObjectName("automationRunDialog")
        self.setWindowTitle(t("automation.run_title"))
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(400)
        self.setMaximumWidth(480)

        status_code, status_key = workflow_run_status(workflow)
        self._can_run = status_code == "ready"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(12)

        title = QLabel(t("automation.run_title"), self)
        title.setObjectName("automationRunTitle")
        outer.addWidget(title)

        heading = QLabel(t("automation.run_heading", name=workflow.name), self)
        heading.setObjectName("automationRunHeading")
        heading.setWordWrap(True)
        outer.addWidget(heading)

        hint = QLabel(
            t(status_key) if not self._can_run else t("automation.run_hint"),
            self,
        )
        hint.setObjectName("automationRunHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        card = QFrame(self)
        card.setObjectName("automationRunSummaryCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        caption = QLabel(t("automation.run_behavior"), card)
        caption.setObjectName("automationRunCaption")
        card_layout.addWidget(caption)

        self._rows = self._behavior_rows()
        for label, body in self._rows:
            row = QWidget(card)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(1)
            heading_row = QLabel(label, row)
            heading_row.setObjectName("automationRunStepLabel")
            heading_row.setWordWrap(True)
            body_row = QLabel(body, row)
            body_row.setObjectName("automationRunStepBody")
            body_row.setWordWrap(True)
            row_layout.addWidget(heading_row)
            row_layout.addWidget(body_row)
            card_layout.addWidget(row)
        outer.addWidget(card)

        footnote = QLabel(t("automation.run_footnote"), self)
        footnote.setObjectName("automationRunFootnote")
        footnote.setWordWrap(True)
        outer.addWidget(footnote)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = QPushButton(
            t("common.close") if not self._can_run else t("common.cancel"),
            self,
        )
        cancel.setObjectName("automationRunCancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        confirm = QPushButton(t("automation.run_execute"), self)
        confirm.setObjectName("automationRunConfirm")
        confirm.setCursor(Qt.PointingHandCursor)
        confirm.setDefault(True)
        confirm.setEnabled(self._can_run)
        confirm.clicked.connect(self.accept)
        actions.addWidget(confirm)
        self._confirm = confirm
        outer.addLayout(actions)

    @property
    def can_run(self) -> bool:
        return self._can_run

    @property
    def behavior_text(self) -> str:
        return " · ".join(body for _label, body in self._rows)

    def _behavior_rows(self) -> list[tuple[str, str]]:
        workflow = self._workflow
        rows: list[tuple[str, str]] = [
            (
                t("automation.trigger_folder"),
                folder_display_name(workflow.scope_folder),
            )
        ]
        search = [step for step in workflow.steps if step.type in {STEP_FIND, STEP_NARROW}]
        if not search:
            rows.append(
                (t("automation.category_search"), t("automation.block_all_images"))
            )
        for step in search:
            rows.append(
                (
                    block_title(step, origin=workflow.origin),
                    block_summary(step, origin=workflow.origin),
                )
            )
        for step in workflow.steps:
            if step.type != STEP_ACTION:
                continue
            rows.append(
                (
                    block_title(step, origin=workflow.origin),
                    block_summary(step, origin=workflow.origin),
                )
            )
        return rows
