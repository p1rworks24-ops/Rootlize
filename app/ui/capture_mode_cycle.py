"""Capture-mode cycle control (compact icon button)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.i18n import t
from app.ui.icons import icon_capture_mode_cycle


class CaptureModeCycleButton(QWidget):
    """
    Compact cycle control: optional label above a mode-switch icon button.

    Emits clicked when the user wants the next capture mode.
    """

    clicked = Signal()

    def __init__(
        self,
        parent=None,
        *,
        show_label: bool = True,
        button_size: int = 36,
        icon_size: int = 16,
        fixed_width: int | None = None,
        button_object_name: str = "captureModeCycleButton",
        icon_color: str = "#334155",
    ):
        super().__init__(parent)
        self.setObjectName("captureModeCycle")
        self._icon_px = max(10, int(icon_size))
        self._base_icon = icon_capture_mode_cycle(size=self._icon_px, color=icon_color)

        side = max(18, int(button_size))
        width = fixed_width if fixed_width is not None else max(side + 4, 52)
        self.setFixedWidth(width)
        if not show_label:
            # Outer box can be wider than the button so borders are not clipped
            self.setFixedHeight(side)

        layout = QVBoxLayout(self)
        # Pad horizontally when the host is wider than the painted button
        h_pad = max((width - side) // 2, 0)
        layout.setContentsMargins(h_pad, 0, h_pad, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        self._label = QLabel(t("shell.capture.cycle_label"), self)
        self._label.setObjectName("captureModeCycleLabel")
        self._label.setAlignment(Qt.AlignHCenter)
        if show_label:
            layout.addWidget(self._label)
        else:
            self._label.hide()

        self._btn = QPushButton(self)
        self._btn.setObjectName(button_object_name)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setToolTip(t("shell.capture.cycle_tooltip"))
        self._btn.setFixedSize(side, side)
        self._btn.setIcon(self._base_icon)
        self._btn.setIconSize(QSize(self._icon_px, self._icon_px))
        self._btn.clicked.connect(self.clicked.emit)
        layout.addWidget(self._btn, alignment=Qt.AlignHCenter)
