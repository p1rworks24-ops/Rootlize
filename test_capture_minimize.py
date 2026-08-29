"""Settings: minimize on capture (default On; On left / Off right)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_CONFIG
from app.ui.pages.settings_page import SettingsPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _enable_capture(monkeypatch):
    monkeypatch.setattr("app.ui.main_window.CAPTURE_ENABLED", True)


def test_capture_minimize_defaults_on():
    assert DEFAULT_CONFIG.get("capture_minimize") is True
    assert DEFAULT_CONFIG.get("window_width") == 1600
    assert DEFAULT_CONFIG.get("window_height") == 900


def test_capture_minimize_toggle_autosaves():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "current_folder": "Capture",
            "save_folder": "Capture",
            "capture_minimize": True,
        }
        page = SettingsPage(config, root)
        # Toggle order: On (0) | Off (1)
        assert page._minimize_toggle.current() == 0
        shell_refreshes = []
        page.settings_saved.connect(lambda: shell_refreshes.append(True))
        with patch("app.ui.pages.settings_page.save_config") as mock_save:
            page._on_minimize_changed(1)  # Off
            assert config["capture_minimize"] is False
            mock_save.assert_called()
            page._on_minimize_changed(0)  # On
            assert config["capture_minimize"] is True
        assert shell_refreshes == []


def test_capture_button_triggers_region_after_off_then_on_toggle():
    app = _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shots = root / "screenshots" / "Capture"
        shots.mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "capture_mode": "region",
            "capture_minimize": True,
            "show_save_notification": False,
        }
        with patch("app.ui.main_window.AppHotkeyManager") as hotkey_cls:
            hotkey_cls.return_value = MagicMock()
            window = MainWindow(config)
        window._show_page(1)  # Capture bar is available on Images only.
        triggered = []

        with (
            patch("app.ui.pages.settings_page.save_config"),
            patch(
                "app.ui.main_window.default_region_trigger",
                side_effect=lambda: triggered.append(True) or True,
            ),
        ):
            window._settings_page._on_minimize_changed(1)
            window._capture_btn.click()
            QTest.qWait(600)
            assert triggered == [True]
            window._screenshot_session.complete()

            window._settings_page._on_minimize_changed(0)
            window._capture_btn.click()
            QTest.qWait(600)

        assert triggered == [True, True]
        assert window._capture_btn.isEnabled()
        window._screenshot_session.complete()
        window.close()


def test_failed_region_trigger_does_not_lock_capture_button():
    _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "capture_mode": "region",
            "capture_minimize": False,
            "show_save_notification": False,
        }
        with patch("app.ui.main_window.AppHotkeyManager") as hotkey_cls:
            hotkey_cls.return_value = MagicMock()
            window = MainWindow(config)
        window._show_page(1)  # Capture bar is available on Images only.

        with patch(
            "app.ui.main_window.default_region_trigger", return_value=False
        ) as trigger:
            window._capture_btn.click()
            QTest.qWait(600)
            assert not window._screenshot_session.is_active

            window._capture_btn.click()
            QTest.qWait(600)

        assert trigger.call_count == 2
        assert not window._screenshot_session.is_active
        window.close()


def test_capture_click_replaces_stale_active_session():
    _ensure_app()
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "capture_mode": "region",
            "capture_minimize": False,
            "show_save_notification": False,
        }
        with patch("app.ui.main_window.AppHotkeyManager") as hotkey_cls:
            hotkey_cls.return_value = MagicMock()
            window = MainWindow(config)
        window._show_page(1)  # Capture bar is available on Images only.

        with patch(
            "app.ui.main_window.default_region_trigger", return_value=True
        ) as trigger:
            window._capture_btn.click()
            QTest.qWait(300)
            assert window._screenshot_session.is_active

            window._capture_btn.click()
            QTest.qWait(300)

        assert trigger.call_count == 2
        assert window._screenshot_session.is_active
        window._screenshot_session.cancel()
        window.close()


def test_capture_minimize_has_own_section():
    """Minimize on capture is not nested inside the UI Settings panel."""
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "current_folder": "Capture",
            "save_folder": "Capture",
            "capture_minimize": True,
        }
        page = SettingsPage(config, root)
        # Own infoPanel ancestor (not the UI Settings frame)
        panel = page._minimize_toggle.parent()
        while panel is not None and panel.objectName() != "infoPanel":
            panel = panel.parent()
        assert panel is not None
        assert panel.objectName() == "infoPanel"
        # UI width edit lives in a different infoPanel
        ui_panel = page._width_edit.parent()
        while ui_panel is not None and ui_panel.objectName() != "infoPanel":
            ui_panel = ui_panel.parent()
        assert ui_panel is not None
        assert ui_panel is not panel


def test_capture_bar_is_visible_only_on_images_page():
    _ensure_app()
    from app.ui.main_window import PAGE_ABOUT, PAGE_HOME, PAGE_IMAGES, PAGE_SETTINGS, MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "selected_folder": str(root / "screenshots" / "Capture"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1600,
            "window_height": 900,
            "filename_template": "{date}_{time}",
        }
        with patch("app.ui.main_window.AppHotkeyManager") as hotkey_cls:
            hotkey_cls.return_value = MagicMock()
            window = MainWindow(config)

        for page_id in (PAGE_HOME, PAGE_SETTINGS, PAGE_ABOUT):
            window._show_page(page_id)
            assert window._capture_bar_host.isHidden()

        window._show_page(PAGE_IMAGES)
        assert window._capture_bar_host.isHidden()
        window._set_capture_bar_visible(True, persist=False, animate=False)
        assert not window._capture_bar_host.isHidden()
        window.close()
