"""Labels support click-drag text selection."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.ui.text_select import enable_label_text_selection


def test_enable_label_text_selection():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    label = QLabel("Hello selectable", root)
    section = QLabel("Save folder", root)
    section.setObjectName("sectionTitle")
    enable_label_text_selection(root)
    flags = label.textInteractionFlags()
    assert flags & Qt.TextSelectableByMouse
    assert flags & Qt.TextSelectableByKeyboard
    section_flags = section.textInteractionFlags()
    assert section_flags & Qt.TextSelectableByMouse
    assert section_flags & Qt.TextSelectableByKeyboard
    _ = app
