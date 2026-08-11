"""T4-5 Organize filtering, selection status, and batch-action tabs."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.i18n import set_locale
from app.services.metadata_service import MetadataService
from app.ui.pages.work_page import (
    OP_MOVE,
    OP_RENAME,
    OP_TAGS,
    WorkPage,
    _ACTION_COLOR_ROLE,
)
from app.utils.thumbnail_cache import ThumbnailCache


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path, date_text: str) -> None:
    image = QImage(20, 12, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")
    stamp = datetime.strptime(date_text, "%Y-%m-%d").timestamp()
    os.utime(path, (stamp, stamp))


def _page(tmp_path: Path) -> WorkPage:
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir(parents=True)
    _png(folder / "alpha.png", "2026-07-01")
    _png(folder / "beta.png", "2026-07-10")
    _png(folder / "gamma.png", "2026-07-20")
    service = MetadataService()
    service.add_image_tag(folder, "alpha.png", "research")
    service.add_image_tag(folder, "beta.png", "research")
    service.add_image_tag(folder, "beta.png", "shared")
    service.ensure_global_tag(tmp_path, "research")
    service.ensure_global_tag(tmp_path, "shared")
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(folder),
        "current_folder": "Capture",
        "save_folder": "Capture",
    }
    page = WorkPage(config, service, ThumbnailCache(size=48), tmp_path)
    page.refresh()
    page.show()
    app.processEvents()
    return page


def test_search_date_filters_and_result_count(tmp_path: Path):
    page = _page(tmp_path)
    assert page._result_count == 3

    page._search_input.setText("research")
    page._on_search()
    assert page._result_count == 2

    page._date_from.setDate(QDate(2026, 7, 5))
    assert page._result_count == 1
    page._date_to.setDate(QDate(2026, 7, 15))
    assert page._result_count == 1

    page._on_clear_search()
    assert page._result_count == 1
    page._clear_date_filter()
    assert page._result_count == 3


def test_from_only_to_only_and_invalid_range(tmp_path: Path):
    page = _page(tmp_path)
    page._date_from.setDate(QDate(2026, 7, 10))
    assert page._result_count == 2
    page._clear_date_filter()

    page._date_to.setDate(QDate(2026, 7, 10))
    assert page._result_count == 2
    page._date_from.setDate(QDate(2026, 7, 20))
    assert not page._date_error_label.isHidden()
    assert "From date" in page._date_error_label.text()


def test_date_filter_calendar_uses_english_locale(tmp_path: Path):
    page = _page(tmp_path)
    for edit in (page._date_from, page._date_to):
        assert edit.locale().language() == QLocale.Language.English
        assert edit.calendarWidget().locale().language() == QLocale.Language.English


def test_show_tags_defaults_on_and_compacts_organize_cards(tmp_path: Path, monkeypatch):
    saved: list[dict] = []
    monkeypatch.setattr(
        "app.ui.pages.work_page.save_config", lambda config: saved.append(dict(config))
    )
    page = _page(tmp_path)
    original_height = page._caption_delegate._cell_height
    assert page._show_tags_checkbox.isChecked()
    assert page._caption_delegate._show_tags is True

    page._show_tags_checkbox.setChecked(False)
    assert page._config["show_tags_in_organize_list"] is False
    assert saved[-1]["show_tags_in_organize_list"] is False
    assert page._caption_delegate._show_tags is False
    assert page._caption_delegate._cell_height == original_height - 16


def test_select_results_clear_selection_and_status(tmp_path: Path):
    page = _page(tmp_path)
    page._search_input.setText("research")
    page._on_search()
    page._select_results_btn.click()
    assert len(page._selected_paths()) == 2
    assert page._selected_count_label.text() == "2 results  |  2 selected"
    assert not page._select_results_btn.isEnabled()
    assert page._clear_selection_btn.isEnabled()

    page._clear_selection_btn.click()
    assert page._selected_paths() == []
    assert page._active_search_query == "research"
    assert page._result_count == 2


def test_group_by_tag_keeps_each_physical_image_once(tmp_path: Path):
    page = _page(tmp_path)
    index = page._group_combo.findData("tag")
    page._group_combo.setCurrentIndex(index)
    paths = [
        page._list.item(row).data(Qt.UserRole)
        for row in range(page._list.count())
        if page._list.item(row).data(Qt.UserRole)
    ]
    assert len(paths) == len(set(paths)) == 3
    page._select_all()
    assert len(page._selected_paths()) == 3


def test_batch_action_dropdown_and_selection_enabled_state(tmp_path: Path):
    page = _page(tmp_path)
    assert not page._op_stack.isEnabled()
    assert not page._no_selection_hint.isHidden()
    assert page._batch_action_controls.isHidden()
    assert page._ops_nav_stack.isHidden()
    assert not page._empty_state_holder.isHidden()
    assert page._batch_selected_count.isHidden()
    assert page._tag_add_combo.currentData() == ""
    assert page._tag_add_combo.currentText() == "Choose a tag..."
    assert page._tag_add_combo.count() == 3
    assert page._tag_add_combo.itemData(1, Qt.ToolTipRole)
    assert page._splitter.orientation() == Qt.Horizontal
    assert page._splitter.sizes()[0] > page._splitter.sizes()[1]
    assert not page._ops_panel.isAncestorOf(page._selected_count_label)
    assert not page._ops_panel.isAncestorOf(page._select_results_btn)
    assert not page._ops_panel.isAncestorOf(page._clear_selection_btn)
    assert page._selection_row.parentWidget() is page._list_column
    selection_right = page._selection_row.mapTo(
        page, page._selection_row.rect().topRight()
    ).x()
    list_right = page._list.mapTo(page, page._list.rect().topRight()).x()
    assert abs(selection_right - list_right) <= 2
    expected_control_width = page._list_column.width()
    assert page._folder_bar.maximumWidth() == expected_control_width
    assert page._search_row.maximumWidth() == expected_control_width

    page._list.item(0).setSelected(True)
    _app().processEvents()
    assert page._op_stack.isEnabled()
    assert page._no_selection_hint.isHidden()
    assert page._empty_state_holder.isHidden()
    assert not page._batch_selected_count.isHidden()
    assert page._batch_selected_count.text() == "1 screenshot selected"
    assert not page._batch_action_controls.isHidden()
    assert page._batch_action_combo.currentData() is None
    assert page._batch_action_combo.parentWidget().findChild(
        type(page._batch_selected_count), "organizeBulkSectionLabel"
    ).text() == "Action"
    assert page._batch_action_controls.property("actionId") == "none"
    assert page._batch_action_summary.isHidden()
    assert page._ops_nav_stack.isHidden()

    expected_descriptions = {
        OP_TAGS: "Add or remove tags from selected screenshots.",
        OP_RENAME: "Rename selected screenshots.",
        OP_MOVE: "Move selected screenshots.",
    }
    for op_id in (OP_TAGS, OP_RENAME, OP_MOVE):
        page._batch_action_combo.setCurrentIndex(
            page._batch_action_combo.findData(op_id)
        )
        _app().processEvents()
        assert page._batch_action_combo.currentData() == op_id
        assert page._batch_action_controls.property("actionId") == op_id
        assert page._batch_action_desc.text() == expected_descriptions[op_id]
        assert not page._batch_action_summary.isHidden()
        assert page._batch_action_combo.currentData(_ACTION_COLOR_ROLE)
        assert not page._batch_action_combo.itemIcon(
            page._batch_action_combo.currentIndex()
        ).isNull()
        assert page._batch_action_combo.property("actionId") == op_id
        assert page._op_stack.currentIndex() == page._operations[op_id]
        assert not page._ops_nav_stack.isHidden()


def test_narrow_layout_and_japanese_copy(tmp_path: Path):
    page = _page(tmp_path)
    page.resize(640, 600)
    _app().processEvents()
    assert page._splitter.orientation() == Qt.Horizontal
    assert page._root_folder_value.toolTip().endswith("Selected")

    try:
        set_locale("ja")
        ja_page = _page(tmp_path / "ja")
        assert ja_page._select_results_btn.text() == "結果をすべて選択"
        move_index = ja_page._batch_action_combo.findData(OP_MOVE)
        assert ja_page._batch_action_combo.itemText(move_index) == "ファイル移動"
    finally:
        set_locale("en")
