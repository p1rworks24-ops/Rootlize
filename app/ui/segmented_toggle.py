"""Reusable segmented toggle (Explorer / Win11 style)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedToggle(QWidget):
    """Mutually exclusive segment buttons for in-card view switching."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("segmentedToggle")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []

        for i, label in enumerate(labels):
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            if i == 0:
                btn.setObjectName("segmentButtonLeft")
            elif i == len(labels) - 1:
                btn.setObjectName("segmentButtonRight")
            else:
                btn.setObjectName("segmentButtonMid")
            self._group.addButton(btn, i)
            layout.addWidget(btn)
            self._buttons.append(btn)

        self._group.idToggled.connect(self._on_toggled)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def current(self) -> int:
        return self._group.checkedId()

    def _on_toggled(self, button_id: int, checked: bool) -> None:
        if checked:
            self.changed.emit(button_id)
