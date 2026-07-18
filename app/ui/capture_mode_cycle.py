"""Animated capture-mode cycle control."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.i18n import t
from app.ui.icons import icon_capture_mode_cycle


class CaptureModeCycleButton(QWidget):
    """
    Compact cycle control: label above a spinning icon button.

    Emits clicked when the user wants the next capture mode.
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("captureModeCycle")
        self._angle = 0.0
        self._base_icon = icon_capture_mode_cycle()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignHCenter)

        self._label = QLabel(t("shell.capture.cycle_label"), self)
        self._label.setObjectName("captureModeCycleLabel")
        self._label.setAlignment(Qt.AlignHCenter)
        layout.addWidget(self._label)

        self._btn = QPushButton(self)
        self._btn.setObjectName("captureModeCycleButton")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setToolTip(t("shell.capture.cycle_tooltip"))
        self._btn.setFixedSize(32, 32)
        self._btn.setIcon(self._base_icon)
        self._btn.clicked.connect(self._on_clicked)
        layout.addWidget(self._btn, alignment=Qt.AlignHCenter)

        self._spin = QPropertyAnimation(self, b"angle", self)
        self._spin.setDuration(520)
        self._spin.setEasingCurve(QEasingCurve.InOutCubic)
        self._spin.finished.connect(self._reset_angle)

    def _on_clicked(self) -> None:
        if self._spin.state() == QPropertyAnimation.Running:
            self._spin.stop()
        start = self._angle % 360.0
        self._spin.setStartValue(start)
        self._spin.setEndValue(start + 360.0)
        self._spin.start()
        self.clicked.emit()

    def _reset_angle(self) -> None:
        self._angle = 0.0
        self._apply_icon()

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float) -> None:
        self._angle = float(value)
        self._apply_icon()

    angle = Property(float, _get_angle, _set_angle)

    def _apply_icon(self) -> None:
        pix = self._base_icon.pixmap(16, 16)
        if pix.isNull():
            return
        transform = QTransform().rotate(self._angle)
        rotated = pix.transformed(transform, Qt.SmoothTransformation)
        canvas = QPixmap(18, 18)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        x = (18 - rotated.width()) // 2
        y = (18 - rotated.height()) // 2
        painter.drawPixmap(x, y, rotated)
        painter.end()
        self._btn.setIcon(QIcon(canvas))
