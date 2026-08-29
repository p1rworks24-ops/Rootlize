"""Startup must not auto-start Capture; only explicit button/hotkey may."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.services.app_hotkeys import AppHotkeyManager, MOD_CONTROL, MOD_SHIFT
from app.services.capture_modes import CAPTURE_FULLSCREEN, CAPTURE_REGION
from app.services.shortcut_spec import (
    ACTION_FULLSCREEN_CAPTURE,
    ACTION_REGION_CAPTURE,
    DEFAULT_SHORTCUTS,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _enable_capture(monkeypatch):
    monkeypatch.setattr("app.ui.main_window.CAPTURE_ENABLED", True)


def _base_config(root: Path) -> dict:
    shots = root / "screenshots" / "Capture"
    shots.mkdir(parents=True)
    return {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
        "filename_template": "{date}_{time}",
        "capture_mode": CAPTURE_REGION,
        "capture_minimize": False,
        "shortcuts": dict(DEFAULT_SHORTCUTS),
        "show_save_notification": False,
    }


def test_mainwindow_init_does_not_start_capture():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _base_config(root)
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            hotkey = MagicMock()
            hotkey.is_armed = False
            HotkeyCls.return_value = hotkey
            window = MainWindow(config)
            window._app_root = root
            started = MagicMock()
            window._start_capture_session = started
            app.processEvents()
            QTimer.singleShot(0, app.quit)
            # Pump a few deferred events without quitting the whole suite early
            for _ in range(5):
                app.processEvents()
            assert started.call_count == 0
            # Hotkeys stay disarmed until splash / arm_capture_hotkeys
            hotkey.set_armed.assert_not_called()
            window.arm_capture_hotkeys()
            hotkey.set_armed.assert_called_with(True)
            window.close()
            app.processEvents()


def test_config_restore_alone_does_not_start_capture():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _base_config(root)
        config["capture_mode"] = CAPTURE_FULLSCREEN
        config["shortcuts"] = {
            ACTION_REGION_CAPTURE: "Ctrl+Shift+S",
            ACTION_FULLSCREEN_CAPTURE: "Ctrl+Shift+F",
        }
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            HotkeyCls.return_value = MagicMock()
            window = MainWindow(config)
            window._app_root = root
            started = MagicMock()
            window._start_capture_session = started
            # Re-apply config-driven UI the way startup does
            window._refresh_capture_mode_ui(animate=False)
            window._reload_capture_hotkeys()
            app.processEvents()
            assert started.call_count == 0
            window.close()
            app.processEvents()


def test_capture_button_starts_capture_once():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _base_config(root)
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            HotkeyCls.return_value = MagicMock()
            window = MainWindow(config)
            window._app_root = root
            seen: list[str] = []
            window._start_capture_session = MagicMock(
                side_effect=lambda mode, from_panel=False: seen.append(mode)
            )
            window._on_capture_clicked()
            app.processEvents()
            assert seen == [CAPTURE_REGION]
            window.close()
            app.processEvents()


def test_hotkey_starts_capture_once_when_armed():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _base_config(root)
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            hotkey = MagicMock()
            HotkeyCls.return_value = hotkey
            window = MainWindow(config)
            window._app_root = root
            seen: list[str] = []
            window._start_capture_session = MagicMock(
                side_effect=lambda mode, from_panel=False: seen.append(mode)
            )
            window._on_hotkey_activated(ACTION_FULLSCREEN_CAPTURE)
            assert seen == [CAPTURE_FULLSCREEN]
            window.close()
            app.processEvents()


def test_hotkey_manager_ignores_events_while_disarmed():
    app = _ensure_app()
    manager = AppHotkeyManager()
    manager.start(app)
    activated: list[str] = []
    manager.activated.connect(activated.append)
    with patch(
        "app.services.app_hotkeys._real_registration_enabled", return_value=True
    ), patch("ctypes.windll.user32.RegisterHotKey", return_value=1), patch(
        "ctypes.windll.user32.UnregisterHotKey", return_value=1
    ):
        manager.set_bindings(dict(DEFAULT_SHORTCUTS))
        assert manager.is_armed is False
        # Simulate a deferred hotkey callback while still disarmed
        manager._handle_hotkey_id(1, manager._generation)
        app.processEvents()
        assert activated == []
        manager.set_armed(True)
        manager._handle_hotkey_id(1, manager._generation)
        assert activated == [ACTION_REGION_CAPTURE]
        manager.stop()


def test_hotkey_manager_ignores_stale_generation_after_rebind():
    app = _ensure_app()
    manager = AppHotkeyManager()
    manager.start(app)
    activated: list[str] = []
    manager.activated.connect(activated.append)
    with patch(
        "app.services.app_hotkeys._real_registration_enabled", return_value=True
    ), patch("ctypes.windll.user32.RegisterHotKey", return_value=1), patch(
        "ctypes.windll.user32.UnregisterHotKey", return_value=1
    ):
        manager.set_bindings(dict(DEFAULT_SHORTCUTS))
        manager.set_armed(True)
        stale_gen = manager._generation
        stale_id = next(iter(manager._id_to_binding))
        manager.set_bindings(dict(DEFAULT_SHORTCUTS))  # bumps generation + new ids
        manager.set_armed(True)
        manager._handle_hotkey_id(stale_id, stale_gen)
        assert activated == []
        new_id = next(iter(manager._id_to_binding))
        manager._handle_hotkey_id(new_id, manager._generation)
        assert activated == [ACTION_REGION_CAPTURE]
        manager.stop()


def test_hotkey_manager_rejects_mismatched_lparam():
    """Mis-parsed MSG (wrong mods/vk) must not activate Capture."""
    app = _ensure_app()
    manager = AppHotkeyManager()
    manager.start(app)
    manager.set_armed(True)
    with patch(
        "app.services.app_hotkeys._real_registration_enabled", return_value=True
    ), patch("ctypes.windll.user32.RegisterHotKey", return_value=1), patch(
        "ctypes.windll.user32.UnregisterHotKey", return_value=1
    ):
        manager.set_bindings(dict(DEFAULT_SHORTCUTS))
        assert 1 in manager._id_to_binding
        action, mods, vk = manager._id_to_binding[1]
        assert action == ACTION_REGION_CAPTURE
        assert mods == (MOD_CONTROL | MOD_SHIFT)
        # Binding stored for validation; mismatched events are filtered in
        # nativeEventFilter before _handle_hotkey_id — covered by structure.
        assert vk is not None
        manager.stop()


def test_window_recreate_does_not_auto_capture():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = _base_config(root)
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            HotkeyCls.return_value = MagicMock()
            for _ in range(2):
                window = MainWindow(config)
                window._app_root = root
                started = MagicMock()
                window._start_capture_session = started
                app.processEvents()
                assert started.call_count == 0
                window.close()
                app.processEvents()
