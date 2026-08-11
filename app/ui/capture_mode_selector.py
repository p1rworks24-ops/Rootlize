"""Compact, explicit selector for the active screenshot capture mode."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.services.capture_modes import (
    CAPTURE_FULLSCREEN,
    CAPTURE_REGION,
    normalize_capture_mode,
)
from app.ui.design_tokens import (
    CAPTURE_FIELD_HEIGHT,
    CAPTURE_FIELD_TITLE_HEIGHT,
    CAPTURE_MODE_FULLSCREEN_WIDTH,
    CAPTURE_MODE_REGION_WIDTH,
    CAPTURE_MODE_SELECTOR_WIDTH,
)


class CaptureModeSelector(QWidget):
    """Segmented Region / Fullscreen selector; it never starts a capture."""

    mode_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("captureModeSelector")
        self.setFixedWidth(CAPTURE_MODE_SELECTOR_WIDTH)
        self.setFixedHeight(CAPTURE_FIELD_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(t("shell.capture.cycle_label"), self)
        label.setObjectName("captureModeSelectorLabel")
        label.setFixedHeight(CAPTURE_FIELD_TITLE_HEIGHT)
        self.label = label
        layout.addWidget(label)

        segments = QFrame(self)
        segments.setObjectName("captureModeSegments")
        segments.setFixedHeight(32)
        segment_layout = QHBoxLayout(segments)
        # QFrame's 1px border otherwise places the 28px segments one pixel
        # low inside the 32px shell. Compensate so top/bottom insets match.
        segment_layout.setContentsMargins(2, 1, 2, 3)
        segment_layout.setSpacing(0)
        segment_layout.setAlignment(Qt.AlignVCenter)

        self.region_button = self._make_button(
            t("shell.capture.mode_region"),
            CAPTURE_REGION,
            CAPTURE_MODE_REGION_WIDTH,
            segments,
        )
        self.fullscreen_button = self._make_button(
            t("shell.capture.mode_fullscreen"),
            CAPTURE_FULLSCREEN,
            CAPTURE_MODE_FULLSCREEN_WIDTH,
            segments,
        )

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.addButton(self.region_button)
        self._group.addButton(self.fullscreen_button)
        self.region_button.clicked.connect(
            lambda checked: self._emit_mode(CAPTURE_REGION, checked)
        )
        self.fullscreen_button.clicked.connect(
            lambda checked: self._emit_mode(CAPTURE_FULLSCREEN, checked)
        )

        segment_layout.addWidget(self.region_button)
        segment_layout.addWidget(self.fullscreen_button)
        layout.addWidget(segments)

        self.set_mode(CAPTURE_REGION)

    @staticmethod
    def _make_button(
        text: str, mode: str, width: int, parent: QWidget
    ) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("captureModeSegment")
        button.setProperty("captureMode", mode)
        button.setCheckable(True)
        button.setFixedWidth(width)
        button.setFixedHeight(28)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(
            t(
                "shell.capture.region_tooltip"
                if mode == CAPTURE_REGION
                else "shell.capture.fullscreen_tooltip"
            )
        )
        return button

    def _emit_mode(self, mode: str, checked: bool) -> None:
        if checked:
            self.mode_selected.emit(mode)

    def set_mode(self, mode: str) -> None:
        normalized = normalize_capture_mode(mode)
        self.region_button.setChecked(normalized == CAPTURE_REGION)
        self.fullscreen_button.setChecked(normalized == CAPTURE_FULLSCREEN)

    def mode(self) -> str:
        if self.fullscreen_button.isChecked():
            return CAPTURE_FULLSCREEN
        return CAPTURE_REGION
