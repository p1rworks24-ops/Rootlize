"""Settings: minimize on capture (default On; On left / Off right)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.config import DEFAULT_CONFIG
from app.ui.pages.settings_page import SettingsPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_capture_minimize_defaults_on():
    assert DEFAULT_CONFIG.get("capture_minimize") is True
    assert DEFAULT_CONFIG.get("window_width") == 1050
    assert DEFAULT_CONFIG.get("window_height") == 600


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
        with patch("app.ui.pages.settings_page.save_config") as mock_save:
            page._on_minimize_changed(1)  # Off
            assert config["capture_minimize"] is False
            mock_save.assert_called()
            page._on_minimize_changed(0)  # On
            assert config["capture_minimize"] is True


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
