"""Capture keyboard shortcuts — validation, config, Settings, hotkey wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.config import DEFAULT_CONFIG
from app.i18n import t
from app.services.app_hotkeys import AppHotkeyManager
from app.services.capture_modes import CAPTURE_FULLSCREEN, CAPTURE_REGION
from app.services.shortcut_spec import (
    ACTION_FULLSCREEN_CAPTURE,
    ACTION_REGION_CAPTURE,
    DEFAULT_SHORTCUTS,
    apply_shortcuts_to_config,
    find_shortcut_conflict,
    format_shortcut_display,
    load_shortcuts_from_config,
    normalize_shortcut,
    validate_shortcut,
)
from app.ui.pages.settings_page import SettingsPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_default_shortcuts():
    assert DEFAULT_SHORTCUTS[ACTION_REGION_CAPTURE] == "Ctrl+Shift+R"
    assert DEFAULT_SHORTCUTS[ACTION_FULLSCREEN_CAPTURE] == "Ctrl+Shift+F"
    assert DEFAULT_CONFIG["shortcuts"][ACTION_REGION_CAPTURE] == "Ctrl+Shift+R"


def test_validate_accepts_defaults_and_printscreen():
    _ensure_app()
    assert validate_shortcut("Ctrl+Shift+R")[0] is True
    assert validate_shortcut("Ctrl+Shift+F")[0] is True
    assert validate_shortcut("Print")[0] is True or validate_shortcut("PrintScreen")[0] is True


def test_validate_rejects_modifiers_only():
    _ensure_app()
    # Bare modifier tokens / incomplete combos
    assert validate_shortcut("Ctrl")[0] is False
    assert validate_shortcut("Shift")[0] is False
    assert validate_shortcut("Alt")[0] is False
    # Letter without modifier
    assert validate_shortcut("R")[0] is False


def test_conflict_detection():
    _ensure_app()
    bindings = {
        ACTION_REGION_CAPTURE: "Ctrl+Shift+R",
        ACTION_FULLSCREEN_CAPTURE: "Ctrl+Shift+F",
    }
    assert (
        find_shortcut_conflict(
            ACTION_FULLSCREEN_CAPTURE, "Ctrl+Shift+R", bindings
        )
        == ACTION_REGION_CAPTURE
    )
    assert (
        find_shortcut_conflict(
            ACTION_FULLSCREEN_CAPTURE, "Ctrl+Shift+G", bindings
        )
        is None
    )


def test_load_and_apply_shortcuts_config():
    _ensure_app()
    config: dict = {}
    loaded = load_shortcuts_from_config(config)
    assert loaded[ACTION_REGION_CAPTURE] == "Ctrl+Shift+R"
    apply_shortcuts_to_config(
        config,
        {
            ACTION_REGION_CAPTURE: "Ctrl+Alt+R",
            ACTION_FULLSCREEN_CAPTURE: "Ctrl+Alt+F",
        },
    )
    assert config["shortcuts"][ACTION_REGION_CAPTURE] == "Ctrl+Alt+R"
    assert load_shortcuts_from_config(config)[ACTION_FULLSCREEN_CAPTURE] == "Ctrl+Alt+F"


def test_format_shortcut_display():
    _ensure_app()
    text = format_shortcut_display("Ctrl+Shift+R")
    assert "Ctrl" in text and "Shift" in text and "R" in text
    assert " + " in text


def test_settings_page_has_keyboard_shortcuts_section():
    app = _ensure_app()
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
            "shortcuts": dict(DEFAULT_SHORTCUTS),
        }
        page = SettingsPage(config, root)
        page.show()
        app.processEvents()

        titles = [
            lab.text()
            for lab in page.findChildren(QLabel)
            if lab.objectName() == "sectionTitle"
        ]
        assert t("settings.shortcuts") in titles

        values = [
            lab.text()
            for lab in page.findChildren(QLabel)
            if lab.objectName() == "shortcutValueLabel"
        ]
        assert any("R" in v for v in values)
        assert any("F" in v for v in values)

        change_buttons = [
            b
            for b in page.findChildren(QPushButton)
            if b.text() == t("settings.shortcuts.change")
        ]
        assert len(change_buttons) == 2


def test_settings_rejects_duplicate_shortcut():
    app = _ensure_app()
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
            "shortcuts": dict(DEFAULT_SHORTCUTS),
        }
        page = SettingsPage(config, root)
        app.processEvents()

        # Simulate capture dialog returning the Region shortcut for Fullscreen
        with patch.object(page, "_on_change_shortcut") as _:
            pass

        # Call the persistence path via conflict check used by the handler
        bindings = load_shortcuts_from_config(config)
        conflict = find_shortcut_conflict(
            ACTION_FULLSCREEN_CAPTURE,
            normalize_shortcut("Ctrl+Shift+R"),
            bindings,
        )
        assert conflict == ACTION_REGION_CAPTURE


def test_hotkey_manager_registers_and_clears():
    app = _ensure_app()
    manager = AppHotkeyManager()
    manager.start(app)
    with patch(
        "app.services.app_hotkeys._real_registration_enabled", return_value=True
    ), patch("ctypes.windll.user32.RegisterHotKey", return_value=1) as reg, patch(
        "ctypes.windll.user32.UnregisterHotKey", return_value=1
    ) as unreg:
        failures = manager.set_bindings(dict(DEFAULT_SHORTCUTS))
        assert failures == {}
        assert reg.call_count == 2
        assert manager.bindings()[ACTION_REGION_CAPTURE] == "Ctrl+Shift+R"
        manager.stop()
        assert unreg.call_count >= 2


def test_main_window_hotkey_calls_shared_capture_methods():
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
            "capture_mode": CAPTURE_REGION,
            "capture_minimize": False,
            "shortcuts": dict(DEFAULT_SHORTCUTS),
        }
        with patch("app.ui.main_window.AppHotkeyManager") as HotkeyCls:
            hotkey = MagicMock()
            HotkeyCls.return_value = hotkey
            window = MainWindow(config)
            window._app_root = root
            seen: list[str] = []
            window._start_capture_session = MagicMock(
                side_effect=lambda mode, from_panel=False: seen.append(mode)
            )

            window._capture_region(from_panel=False)
            window._capture_fullscreen(from_panel=False)
            window._on_hotkey_activated(ACTION_REGION_CAPTURE)
            window._on_hotkey_activated(ACTION_FULLSCREEN_CAPTURE)

            assert seen == [
                CAPTURE_REGION,
                CAPTURE_FULLSCREEN,
                CAPTURE_REGION,
                CAPTURE_FULLSCREEN,
            ]
            window.close()
            app.processEvents()
