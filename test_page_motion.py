"""Page transitions fade an opaque snapshot, never live opacity effects."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from app.ui.design_tokens import COLORS, MOTION_NORMAL_MS
from app.ui.page_motion import (
    active_page_fade,
    crossfade_stacked,
    motion_preferred,
    opaque_grab,
)


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_crossfade_uses_snapshot_overlay_not_live_opacity():
    _ensure_app()
    shell = QWidget()
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(0, 0, 0, 0)
    stack = QStackedWidget(shell)
    first = QWidget()
    first.setStyleSheet(f"background-color: {COLORS.panel_bg};")
    second = QWidget()
    second.setStyleSheet(f"background-color: {COLORS.card_bg};")
    stack.addWidget(first)
    stack.addWidget(second)
    layout.addWidget(stack)
    shell.resize(320, 240)
    shell.show()
    QApplication.processEvents()

    crossfade_stacked(stack, second)
    QApplication.processEvents()

    assert stack.currentWidget() is second
    assert not first.isVisible()
    assert second.isVisible()
    assert first.graphicsEffect() is None
    assert second.graphicsEffect() is None
    fade = active_page_fade(stack)
    if motion_preferred():
        assert fade is not None
        assert fade["anim"].duration() == MOTION_NORMAL_MS
        overlay = fade["overlay"]
        assert overlay.graphicsEffect() is None
        assert overlay.parentWidget() is shell
        assert stack.count() == 2
        assert overlay.parentWidget() is not stack
    else:
        assert fade is None


def test_opaque_grab_fills_transparent_pixels():
    _ensure_app()
    widget = QWidget()
    widget.resize(40, 40)
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.show()
    QApplication.processEvents()

    grabbed = opaque_grab(widget)
    assert not grabbed.isNull()
    color = grabbed.toImage().pixelColor(2, 2)
    assert color.alpha() == 255
