"""Shared scrollable page chrome for small window sizes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

from app.ui.design_tokens import paint_canvas


def make_page_scroll(parent: QWidget | None = None) -> QScrollArea:
    """
    Vertical + horizontal scroll area for page content.

    Prefer scrolling over shrinking UI when the window is small.
    """
    scroll = QScrollArea(parent)
    scroll.setObjectName("pageScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    paint_canvas(scroll)
    viewport = scroll.viewport()
    if viewport is not None:
        paint_canvas(viewport)
    return scroll
