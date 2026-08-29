"""Temporary in-app image preview (Space)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QVBoxLayout

from app.ui.page_motion import AnimatedDialog
from app.ui.pages.images_page import PreviewImageView


class QuickPreviewDialog(AnimatedDialog):
    def __init__(self, parent=None, *, large: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("quickPreviewDialog")
        self.setWindowTitle("Preview")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = PreviewImageView(self)
        layout.addWidget(self._view)
        if large:
            self.resize(1100, 780)
        else:
            self.resize(760, 540)

    def load_path(self, path: Path) -> bool:
        return self._view.load_path(path)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Escape, Qt.Key_Space):
            self.accept()
            return
        super().keyPressEvent(event)
