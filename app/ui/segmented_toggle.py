"""Reusable segmented toggle (Explorer / Win11 style)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedToggle(QWidget):
    """Mutually exclusive segment buttons for in-card view switching."""

    changed = Signal(int)

    def __init__(
        self,
        labels: list[str],
        parent=None,
        *,
        icons: list[QIcon] | None = None,
        icon_size: int = 16,
    ):
        super().__init__(parent)
        self.setObjectName("segmentedToggle")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []

        for i, label in enumerate(labels):
            icon = icons[i] if icons and i < len(icons) else QIcon()
            btn = QPushButton("" if not icon.isNull() else label, self)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(icon_size, icon_size))
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
