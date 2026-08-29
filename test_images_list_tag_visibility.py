"""Settings-driven tag visibility for Images list cards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox

from app.config import DEFAULT_CONFIG
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import ROLE_CAPTION_TAGS
from app.ui.pages.images_page import ImagesPage, TAG_CAPTION_ROW_HEIGHT
from app.ui.pages.settings_page import SettingsPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


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
        "developer_search_mode": "text",
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


def test_missing_setting_defaults_to_tags_hidden(tmp_path: Path):
    page = _make_page(tmp_path, show_tags=None)
    assert DEFAULT_CONFIG["show_tags_in_image_list"] is False
    assert page._caption_delegate._show_tags is False
    assert gallery_image_items(page._list_widget)[0].data(ROLE_CAPTION_TAGS) == "#important"
    assert "#important" not in gallery_image_items(page._list_widget)[0].toolTip()


def test_images_checkbox_autosaves_and_restores_value(tmp_path: Path):
    app = _ensure_app()
    page = _make_page(tmp_path / "initial", show_tags=True)
    assert page._show_tags_checkbox.isChecked()
    from app.ui.checkbox import CapixeCheckBox

    assert isinstance(page._show_tags_checkbox, CapixeCheckBox)
    assert page._show_tags_checkbox.text().strip().upper() not in {"ON", "OFF"}
    assert page._show_tags_checkbox.isCheckable()

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
    visible_item = gallery_image_items(visible._list_widget)[0]
    hidden_item = gallery_image_items(hidden._list_widget)[0]

    assert visible._caption_delegate._show_tags is True
    assert hidden._caption_delegate._show_tags is False
    assert hidden_item.sizeHint().height() == (
        visible_item.sizeHint().height() - TAG_CAPTION_ROW_HEIGHT
    )
    assert hidden_item.data(ROLE_CAPTION_TAGS) == "#important"
    assert "#important" not in hidden_item.toolTip()

    hidden._search_input.setText("important")
    hidden._on_search()
    for _ in range(50):
        if not hidden._search_tasks:
            break
        QTest.qWait(20)
    assert len(gallery_image_items(hidden._list_widget)) == 1

    item = gallery_image_items(hidden._list_widget)[0]
    hidden._list_widget.setCurrentItem(item)
    item.setSelected(True)
    _ensure_app().processEvents()
    assert hidden._tags_card.isEnabled()


def test_show_tags_checkbox_paints_empty_and_checked_boxes():
    from PySide6.QtGui import QColor, QImage, QPainter

    from app.ui.checkbox import CapixeCheckBox, paint_checkbox_indicator
    from app.ui.design_tokens import CHECKBOX_CHECK, CHECKBOX_SIZE

    _ensure_app()
    box = CapixeCheckBox("Show Tags")
    box.setObjectName("imagesShowTagsCheckBox")
    assert box.sizeHint().height() >= 28

    def _render(*, checked: bool) -> QImage:
        image = QImage(CHECKBOX_SIZE, CHECKBOX_SIZE, QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        paint_checkbox_indicator(
            painter,
            image.rect(),
            checked=checked,
            hovered=False,
            pressed=False,
        )
        painter.end()
        return image

    empty = _render(checked=False)
    checked = _render(checked=True)
    check_color = QColor(CHECKBOX_CHECK)
    def _check_pixels(image: QImage) -> int:
        count = 0
        for x in range(image.width()):
            for y in range(image.height()):
                pixel = QColor(image.pixel(x, y))
                if abs(pixel.hue() - check_color.hue()) < 20 and pixel.saturation() > 20:
                    count += 1
                elif pixel.red() < 120 and pixel.green() < 120 and pixel.blue() < 140:
                    if 3 < x < image.width() - 3 and 3 < y < image.height() - 3:
                        count += 1
        return count

    assert _check_pixels(checked) > _check_pixels(empty)
    # Unchecked interior stays light — an empty square, not a filled switch.
    interior = QColor(empty.pixel(CHECKBOX_SIZE // 2, CHECKBOX_SIZE // 2))
    assert interior.lightness() > 200
