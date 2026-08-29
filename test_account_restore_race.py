"""Account session restore must not touch UI after MainWindow teardown."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from app.auth import AccountSession, AuthService, AuthStatus, MemoryCredentialStore
from app.auth.config import AuthClientConfig
from app.auth.device import DeviceService
from app.auth.models import AuthUser, StoredSession
from app.ui.account_controller import AccountController, _qobject_alive
from app.ui.main_window import MainWindow
from test_auth import FakeHttp, _user_payload


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pump(app: QApplication, seconds: float = 0.4) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(20)


def _blocked_restore_service(tmp_path: Path, release: threading.Event):
    store = MemoryCredentialStore()
    store.save(
        StoredSession(
            access_token="old-access",
            refresh_token="refresh-token-value",
            user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com"),
        )
    )
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = AuthService(
        AuthClientConfig("https://example.supabase.co", "anon-public"),
        store=store,
        devices=DeviceService(tmp_path / "device.json"),
        http=http,
        open_url=lambda _url: None,
    )
    original = service.restore_session

    def blocked():
        release.wait(5)
        return original()

    service.restore_session = blocked
    return service


def _wait_until_thread(controller: AccountController, app: QApplication) -> None:
    deadline = time.monotonic() + 2
    while controller._thread is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert controller._thread is not None


def test_shutdown_drops_late_session_restore(tmp_path):
    app = _ensure_app()
    release = threading.Event()
    service = _blocked_restore_service(tmp_path, release)
    controller = AccountController(service=service)
    received: list[object] = []
    controller.session_changed.connect(received.append)
    try:
        controller.restore_in_background()
        _wait_until_thread(controller, app)
        threading.Timer(0.05, release.set).start()
        controller.shutdown()
        _pump(app, 0.4)
        assert controller._shutting_down is True
        assert received == []
    finally:
        release.set()
        if not controller._shutting_down:
            controller.shutdown()


def test_late_restore_does_not_touch_deleted_receiver(tmp_path):
    app = _ensure_app()
    release = threading.Event()
    service = _blocked_restore_service(tmp_path, release)
    controller = AccountController(service=service)

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def on_session(self, _session):
            if not _qobject_alive(self):
                raise AssertionError("late restore reached a deleted QObject")
            self.calls += 1

    receiver = Receiver()
    controller.session_changed.connect(receiver.on_session)
    try:
        controller.restore_in_background()
        _wait_until_thread(controller, app)
        receiver.deleteLater()
        app.processEvents()
        threading.Timer(0.05, release.set).start()
        controller.shutdown()
        _pump(app, 0.4)
        assert not _qobject_alive(receiver) or receiver.calls == 0
    finally:
        release.set()
        if not controller._shutting_down:
            controller.shutdown()


def test_main_window_close_during_restore_does_not_crash(monkeypatch):
    app = _ensure_app()
    started = threading.Event()
    release = threading.Event()

    def slow_restore(self):
        started.set()
        release.wait(5)
        return AccountSession(status=AuthStatus.SIGNED_OUT)

    monkeypatch.setattr(AuthService, "restore_session", slow_restore)
    monkeypatch.setattr(AuthService, "has_stored_session", lambda self: True)

    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1000,
            "window_height": 700,
            "window_title": "Rootlize",
        }
    )
    try:
        window.show()
        _pump(app, 0.8)
        assert started.wait(3)
        window._prototype_tour = None
        threading.Timer(0.05, release.set).start()
        window.close()
        _pump(app, 0.8)
        assert window._account_controller._shutting_down is True
    finally:
        release.set()
        controller = getattr(window, "_account_controller", None)
        if controller is not None and not controller._shutting_down:
            controller.shutdown()
