"""Settings-driven tag visibility for Images list cards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QCheckBox

from app.config import DEFAULT_CONFIG
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import ROLE_CAPTION_TAGS
from app.ui.pages.images_page import ImagesPage, TAG_CAPTION_ROW_HEIGHT
from app.ui.pages.settings_page import SettingsPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(24, 16, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _config(folder: Path, *, show_tags: bool | None) -> dict:
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(folder),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
    }
    if show_tags is not None:
        config["show_tags_in_image_list"] = show_tags
    return config


def _make_page(tmp_path: Path, *, show_tags: bool | None) -> ImagesPage:
    app = _ensure_app()
    folder = tmp_path / "Selected"
    folder.mkdir(parents=True, exist_ok=True)
    _write_png(folder / "tagged.png")
    service = MetadataService()
    service.add_image_tag(folder, "tagged.png", "important")
    page = ImagesPage(
        _config(folder, show_tags=show_tags),
        service,
        ThumbnailCache(size=48),
        tmp_path,
    )
    page.refresh()
    page.show()
    app.processEvents()
    return page


def test_missing_setting_defaults_to_tags_visible(tmp_path: Path):
    page = _make_page(tmp_path, show_tags=None)
    assert DEFAULT_CONFIG["show_tags_in_image_list"] is True
    assert page._caption_delegate._show_tags is True
    assert page._list_widget.item(0).data(ROLE_CAPTION_TAGS) == "#important"
    assert "#important" in page._list_widget.item(0).toolTip()


def test_images_checkbox_autosaves_and_restores_value(tmp_path: Path):
    app = _ensure_app()
    page = _make_page(tmp_path / "initial", show_tags=None)
    assert page._show_tags_checkbox.isChecked()

    config_path = tmp_path / "AppData" / "Capixe" / "config.json"
    with patch("app.config.get_config_path", return_value=config_path):
        page._show_tags_checkbox.setChecked(False)
        app.processEvents()

    assert page._config["show_tags_in_image_list"] is False
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved_config["show_tags_in_image_list"] is False
    assert page._caption_delegate._show_tags is False
    restored = _make_page(tmp_path / "restored", show_tags=False)
    assert not restored._show_tags_checkbox.isChecked()
    assert restored._caption_delegate._show_tags is False


def test_settings_page_does_not_contain_image_list_tag_setting(tmp_path: Path):
    app = _ensure_app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    settings = SettingsPage(_config(folder, show_tags=True), tmp_path)
    settings.show()
    app.processEvents()

    assert all(
        checkbox.objectName() != "settingsCheckBox"
        for checkbox in settings.findChildren(QCheckBox)
    )


def test_hiding_tags_compacts_cards_without_removing_tag_data_or_search(tmp_path: Path):
    visible = _make_page(tmp_path / "visible", show_tags=True)
    hidden = _make_page(tmp_path / "hidden", show_tags=False)
    visible_item = visible._list_widget.item(0)
    hidden_item = hidden._list_widget.item(0)

    assert visible._caption_delegate._show_tags is True
    assert hidden._caption_delegate._show_tags is False
    assert hidden_item.sizeHint().height() == (
        visible_item.sizeHint().height() - TAG_CAPTION_ROW_HEIGHT
    )
    assert hidden_item.data(ROLE_CAPTION_TAGS) == "#important"
    assert "#important" not in hidden_item.toolTip()

    hidden._search_input.setText("important")
    hidden._on_search()
    assert hidden._list_widget.count() == 1

    hidden._list_widget.setCurrentRow(0)
    hidden._list_widget.item(0).setSelected(True)
    _ensure_app().processEvents()
    assert hidden._tags_card.isEnabled()
