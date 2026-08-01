"""Splash overlay: brand animation on the main window."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.branding import APP_NAME, DISPLAY_VERSION, RELEASE_CHANNEL, TAGLINE
from app.ui.splash_screen import SPLASH_MIN_MS, SplashScreen


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_host() -> QWidget:
    host = QWidget()
    host.resize(1050, 600)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel("app body", host))
    return host


def test_splash_is_overlay_on_host_window():
    app = _ensure_app()
    host = _make_host()
    host.show()
    app.processEvents()

    splash = SplashScreen(host)
    app.processEvents()

    assert splash.parent() is host
    assert splash.width() == host.width()
    assert splash.height() == host.height()
    assert splash.isWindow() is False

    titles = [
        lab.text()
        for lab in splash.findChildren(QLabel)
        if lab.objectName() == "splashTitle"
    ]
    taglines = [
        lab.text()
        for lab in splash.findChildren(QLabel)
        if lab.objectName() == "splashTagline"
    ]
    channels = [
        lab.text()
        for lab in splash.findChildren(QLabel)
        if lab.objectName() == "splashChannel"
    ]
    badges = [
        lab.text()
        for lab in splash.findChildren(QLabel)
        if lab.objectName() == "splashBadge"
    ]
    logos = [
        lab
        for lab in splash.findChildren(QLabel)
        if lab.objectName() == "splashLogo"
    ]
    assert titles == [APP_NAME]
    assert taglines == [TAGLINE]
    assert channels == [RELEASE_CHANNEL]
    assert badges == [DISPLAY_VERSION]
    assert DISPLAY_VERSION == "v0.1.0-preview"
    assert "0.1.0" in DISPLAY_VERSION
    assert SPLASH_MIN_MS >= 2000
    assert splash.findChild(QWidget, "splashNavRail") is None
    assert logos and not logos[0].pixmap().isNull()
    assert logos[0].pixmap().width() >= 96

    splash._closing = True
    splash.close()
    host.close()
    app.processEvents()


def test_splash_finished_after_ready_and_min_time():
    from PySide6.QtTest import QTest

    app = _ensure_app()
    host = _make_host()
    host.resize(800, 500)
    host.show()
    app.processEvents()

    splash = SplashScreen(host)
    seen: list[bool] = []
    splash.finished.connect(lambda: seen.append(True))

    splash._min_elapsed = True
    splash.notify_ready()
    QTest.qWait(300)
    app.processEvents()
    assert seen, "finished should emit after ready + min elapsed"
    splash.close()
    host.close()
    app.processEvents()
