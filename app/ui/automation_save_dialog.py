"""Name / description dialog for saving or renaming an Automation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.ui.page_motion import AnimatedDialog


class AutomationSaveDialog(AnimatedDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "",
        name: str = "",
        description: str = "",
        confirm_label: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("automationSaveDialog")
        self.setWindowTitle(title or t("automation.save_title"))
        self.setModal(True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        heading = QLabel(title or t("automation.save_title"), self)
        heading.setObjectName("dialogTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        hint = QLabel(t("automation.save_hint"), self)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._name = QLineEdit(self)
        self._name.setObjectName("automationNameInput")
        self._name.setPlaceholderText(t("automation.name_placeholder"))
        self._name.setText(name)
        self._name.setTextMargins(10, 4, 10, 4)
        layout.addWidget(self._name)

        self._description = QLineEdit(self)
        self._description.setObjectName("automationDescriptionInput")
        self._description.setPlaceholderText(t("automation.description_placeholder"))
        self._description.setText(description)
        self._description.setTextMargins(10, 4, 10, 4)
        layout.addWidget(self._description)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = QPushButton(t("common.cancel"), self)
        cancel.setObjectName("secondaryButton")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(confirm_label or t("automation.save"), self)
        confirm.setObjectName("automationSaveConfirm")
        confirm.setCursor(Qt.PointingHandCursor)
        confirm.clicked.connect(self._accept_if_named)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        self._name.setFocus()
        self._name.selectAll()

    def workflow_name(self) -> str:
        return self._name.text().strip()

    def workflow_description(self) -> str:
        return self._description.text().strip()

    def _accept_if_named(self) -> None:
        if not self.workflow_name():
            self._name.setFocus()
            return
        self.accept()
