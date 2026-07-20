"""Shared page header geometry across main pages."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.ui.page_header import (
    PAGE_HEADER_MARGINS,
    PAGE_HEADER_TITLE_SPACING,
    make_page_header,
)


def test_make_page_header_geometry():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    header = make_page_header(
        root, "Title", "Subtitle", margins=PAGE_HEADER_MARGINS
    )
    assert header.objectName() == "pageHeader"
    layout = header.layout()
    assert layout is not None
    assert layout.contentsMargins().left() == PAGE_HEADER_MARGINS[0]
    assert layout.contentsMargins().top() == PAGE_HEADER_MARGINS[1]
    assert layout.spacing() == PAGE_HEADER_TITLE_SPACING
    labels = header.findChildren(QLabel)
    names = {lab.objectName() for lab in labels}
    assert "pageTitle" in names
    assert "pageSubtitle" in names
    _ = app
