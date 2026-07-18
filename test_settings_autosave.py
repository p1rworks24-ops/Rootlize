"""Settings page autosaves on edit / browse without a Save button."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QPushButton

from app.ui.pages.settings_page import SettingsPage
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_settings_page_has_no_save_button():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1100,
            "window_height": 720,
            "filename_template": DEFAULT_FILENAME_TEMPLATE,
            "current_folder": "Default",
            "save_folder": "Default",
        }
        page = SettingsPage(config, root)
        page.show()
        app.processEvents()

        save_buttons = [
            b
            for b in page.findChildren(QPushButton)
            if "save" in (b.text() or "").lower()
        ]
        assert save_buttons == []
        from PySide6.QtWidgets import QLabel
        from app.i18n import t

        hints = [
            lab.text()
            for lab in page.findChildren(QLabel)
            if lab.objectName() == "settingsAutosaveHint"
        ]
        assert hints == [t("settings.autosave_hint")]


def test_filename_rule_row_marks_selected():
    app = _ensure_app()
    from app.ui.filename_rule_panel import FilenameRulePanel, _RULE_ROW_WIDTH

    panel = FilenameRulePanel()
    panel.set_template("Screenshot_{num}")
    app.processEvents()
    assert panel._rows["sequential"].property("selected") is True
    assert panel._marker_labels["sequential"].text() == "●"
    assert panel._rows["datetime"].property("selected") is False
    assert panel._marker_labels["datetime"].text() == ""
    panel._radios["datetime"].setChecked(True)
    app.processEvents()
    assert panel._rows["datetime"].property("selected") is True
    assert panel._marker_labels["datetime"].text() == "●"
    assert panel._rows["sequential"].property("selected") is False
    assert panel._marker_labels["sequential"].text() == ""
    widths = {row.width() for row in panel._rows.values()}
    assert widths == {_RULE_ROW_WIDTH}


def test_window_size_autosaves_on_editing_finished():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1100,
            "window_height": 720,
            "filename_template": DEFAULT_FILENAME_TEMPLATE,
            "current_folder": "Default",
            "save_folder": "Default",
        }
        page = SettingsPage(config, root)
        saved = []
        page.settings_saved.connect(lambda: saved.append(True))

        with patch("app.ui.pages.settings_page.save_config") as mock_save:
            page._width_edit.setText("1280")
            page._height_edit.setText("800")
            page._autosave_window_size()
            assert config["window_width"] == 1280
            assert config["window_height"] == 800
            mock_save.assert_called()
            assert saved


def test_filename_rule_autosaves():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1100,
            "window_height": 720,
            "filename_template": DEFAULT_FILENAME_TEMPLATE,
            "current_folder": "Default",
            "save_folder": "Default",
        }
        page = SettingsPage(config, root)
        with patch("app.ui.pages.settings_page.save_config") as mock_save:
            page._on_filename_changed("Screenshot_{num}")
            assert config["filename_template"] == "Screenshot_{num}"
            mock_save.assert_called()


def test_custom_rule_stays_custom_and_emits_non_preset():
    """Selecting Custom must not snap back to Datetime ({date}_{time})."""
    app = _ensure_app()
    from app.ui.filename_rule_panel import (
        CUSTOM_STARTER_TEMPLATE,
        FilenameRulePanel,
        rule_id_for_template,
    )

    panel = FilenameRulePanel()
    panel.set_template("{date}_{time}")
    app.processEvents()

    emitted: list[str] = []
    panel.template_changed.connect(emitted.append)
    panel._radios["custom"].setChecked(True)
    app.processEvents()

    assert panel._radios["custom"].isChecked()
    assert emitted
    assert rule_id_for_template(emitted[-1]) == "custom"
    assert emitted[-1] == CUSTOM_STARTER_TEMPLATE
    # Simulate autosave refresh with the emitted template
    panel.set_template(emitted[-1])
    app.processEvents()
    assert panel._radios["custom"].isChecked()
