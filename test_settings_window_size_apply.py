"""Window size applies only when width/height settings change."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.ui.main_window import (
    MainWindow,
    _WINDOW_MIN_HEIGHT,
    _WINDOW_MIN_WIDTH,
)
from app.ui.pages.settings_page import SettingsPage
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_honors_configured_size_and_soft_minimum():
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 900,
            "window_height": 560,
            "filename_template": DEFAULT_FILENAME_TEMPLATE,
            "capture_minimize": True,
            "shortcuts": {
                "region_capture": "Ctrl+Shift+R",
                "fullscreen_capture": "Ctrl+Shift+F",
            },
        }
        window = MainWindow(config)
        window._app_root = root
        window.show()
        app.processEvents()
        assert window.width() == 900
        assert window.height() == 560
        assert window.minimumWidth() == _WINDOW_MIN_WIDTH
        assert window.minimumHeight() == _WINDOW_MIN_HEIGHT
        # Soft floor is below the configured default so the user can shrink
        assert window.minimumWidth() < 1050
        window.close()
        app.processEvents()


def test_window_size_changed_only_on_size_edit():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": DEFAULT_FILENAME_TEMPLATE,
            "current_folder": "Capture",
            "save_folder": "Capture",
            "capture_minimize": True,
        }
        page = SettingsPage(config, root)
        size_events: list[bool] = []
        saved_events: list[bool] = []
        page.window_size_changed.connect(lambda: size_events.append(True))
        page.settings_saved.connect(lambda: saved_events.append(True))

        with patch("app.ui.pages.settings_page.save_config"):
            page._on_minimize_changed(1)  # Off — not a window-size edit
            assert not saved_events
            assert not size_events

            page._width_edit.setText("1200")
            page._height_edit.setText("700")
            page._autosave_window_size()
            assert saved_events
            assert size_events
            assert config["window_width"] == 1200
