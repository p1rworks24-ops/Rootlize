"""Capture Panel: 150×150 always-on-top, draggable, with capture + settings."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.ui.capture_panel_window import (
    PANEL_SIZE,
    SETTINGS_MAX_SIZE,
    SETTINGS_MIN_SIZE,
    CapturePanelWindow,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_capture_panel_is_square_always_on_top():
    app = _ensure_app()
    win = CapturePanelWindow()
    assert win.width() == PANEL_SIZE
    assert win.height() == PANEL_SIZE
    assert PANEL_SIZE == 150
    assert bool(win.windowFlags() & Qt.WindowStaysOnTopHint)
    assert win.parent() is None
    assert win._capture_btn is not None
    assert win._cycle_btn is not None
    assert win._settings_btn is not None
    assert win._close_btn.width() == win._close_btn.height()
    # Settings sits in the capture page side column (under mode), not the title bar
    assert win._settings_btn.parentWidget() is not None
    assert win._settings_btn.parentWidget().objectName() == "capturePanelSideCol"

    closed = []
    win.closed.connect(lambda: closed.append(True))
    win.show_panel()
    app.processEvents()
    assert win.isVisible()
    win.close()
    app.processEvents()
    assert closed
    assert not win.isVisible()


def test_capture_panel_keeps_position_while_session_open():
    """Drag + hide_for_capture/show keeps position; ✕ close resets to bottom-right."""
    from PySide6.QtTest import QTest

    app = _ensure_app()
    win = CapturePanelWindow()
    win.show_panel()
    QTest.qWait(280)
    app.processEvents()
    win.move(win.pos() + QPoint(-40, -30))
    dragged = win.pos()
    win.hide_for_capture()
    win.show_panel()
    QTest.qWait(280)
    app.processEvents()
    assert win.pos() == dragged


def test_capture_panel_reopens_bottom_right_after_close():
    from PySide6.QtTest import QTest

    app = _ensure_app()
    win = CapturePanelWindow()
    win.show_panel()
    QTest.qWait(280)
    app.processEvents()
    win.move(win.pos() + QPoint(-80, -60))
    win.close()
    app.processEvents()

    win.show_panel()
    QTest.qWait(280)
    app.processEvents()

    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    geo = screen.availableGeometry()
    expected_x = max(geo.left() + win.MARGIN, geo.right() - PANEL_SIZE - win.MARGIN)
    expected_y = max(geo.top() + win.MARGIN, geo.bottom() - PANEL_SIZE - win.MARGIN)
    assert win.pos().x() == expected_x
    assert win.pos().y() == expected_y


def test_capture_panel_settings_page_expands():
    from PySide6.QtTest import QTest

    app = _ensure_app()
    win = CapturePanelWindow()
    win.show_panel()
    QTest.qWait(280)
    app.processEvents()
    win.show_settings_page()
    QTest.qWait(360)
    app.processEvents()
    assert SETTINGS_MIN_SIZE.width() <= win.width() <= SETTINGS_MAX_SIZE.width()
    assert SETTINGS_MIN_SIZE.height() <= win.height() <= SETTINGS_MAX_SIZE.height()
    assert win._folder_combo is not None
    assert win._filename_combo is not None
    assert win._back_btn.isVisible()
    assert not win._close_btn.isVisible()
    win.show_capture_page()
    QTest.qWait(360)
    app.processEvents()
    assert win.width() == PANEL_SIZE
    assert win.height() == PANEL_SIZE
    assert win._close_btn.isVisible()
    assert not win._back_btn.isVisible()


def test_capture_panel_shot_label_matches_app_style():
    from app.i18n import t

    app = _ensure_app()
    win = CapturePanelWindow()
    assert win.capture_btn_opacity_effect is not None
    win.apply_mode("region")
    assert "Region" in win._capture_btn.text()
    assert "Capture" in win._capture_btn.text().replace("\n", " ")
    win.apply_mode("fullscreen")
    assert "Full" in win._capture_btn.text()
    assert t("shell.capture.fullscreen")


def test_capture_panel_hide_for_capture_does_not_emit_closed():
    app = _ensure_app()
    win = CapturePanelWindow()
    win.show_panel()
    app.processEvents()
    closed = []
    win.closed.connect(lambda: closed.append(True))
    win.hide_for_capture()
    app.processEvents()
    assert not win.isVisible()
    assert not closed


def test_capture_panel_button_label_has_no_arrow():
    from app.i18n import t

    assert "↗" not in t("shell.capture_panel.button")
    assert t("shell.capture_panel.hint")
    assert t("shell.capture_panel.settings")
