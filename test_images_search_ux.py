"""Find-first search behavior for the Images page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.i18n import set_locale
from app.ui.pages.images_page import ImagesPage, SEARCH_DEBOUNCE_MS
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _make_page(tmp_path: Path) -> ImagesPage:
    app = _ensure_app()
    folder = tmp_path / "Selected"
    folder.mkdir(parents=True)
    _write_png(folder / "pricing.png")
    _write_png(folder / "dashboard.png")
    _write_png(folder / "notes.png")
    service = MetadataService()
    service.add_image_tag(folder, "dashboard.png", "customer")
    database = OCRDatabase(tmp_path / "ocr-index.sqlite3").open()
    repository = OCRRepository(database)
    for path in folder.glob("*.png"):
        stat = path.stat()
        image = repository.upsert_image(
            path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns
        )
        repository.update_tags(
            image.image_id, service.get_image_tags(folder, path.name)
        )
        repository.save_ocr_document(
            image.image_id,
            status="ready",
            ocr_text="quarterly revenue forecast" if path.name == "notes.png" else "",
        )

    def search_provider(query, selected_folder, _candidates):
        page = repository.search_images(query, folder_path=selected_folder, limit=500)
        return tuple(Path(result.path) for result in page.results)
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
    }
    page = ImagesPage(
        config,
        service,
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=search_provider,
    )
    page._test_search_database = database
    page.show()
    app.processEvents()
    return page


def _wait_for_search(page: ImagesPage) -> None:
    deadline_ms = 3000
    elapsed = 0
    while page._search_tasks and elapsed < deadline_ms:
        QTest.qWait(20)
        elapsed += 20
    assert not page._search_tasks


def _activate_shortcut(page: ImagesPage, sequence: QKeySequence) -> None:
    shortcut = next(
        item
        for item in page.findChildren(QShortcut)
        if item.key().matches(sequence) == QKeySequence.ExactMatch
    )
    shortcut.activated.emit()
    _ensure_app().processEvents()


def test_incremental_search_is_debounced_and_empty_query_restores_all(
    tmp_path: Path, monkeypatch
):
    page = _make_page(tmp_path)
    load_calls = 0
    search_calls = 0
    original_load = page._load_images
    original_search = page._start_unified_search

    def counted_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return original_load(*args, **kwargs)

    def counted_search(*args, **kwargs):
        nonlocal search_calls
        search_calls += 1
        return original_search(*args, **kwargs)

    monkeypatch.setattr(page, "_load_images", counted_load)
    monkeypatch.setattr(page, "_start_unified_search", counted_search)
    page._search_input.setText("p")
    page._search_input.setText("pr")
    page._search_input.setText("pricing")
    assert page._search_debounce.isSingleShot()
    assert page._search_debounce.interval() == SEARCH_DEBOUNCE_MS
    assert page._search_debounce.isActive()
    QTest.qWait(SEARCH_DEBOUNCE_MS + 60)
    _wait_for_search(page)
    assert search_calls == 1
    assert load_calls == 0
    assert page._active_search_query == "pricing"
    assert page._list_widget.count() == 1

    page._search_input.clear()
    assert page._search_debounce.isActive()
    QTest.qWait(SEARCH_DEBOUNCE_MS + 60)
    _wait_for_search(page)
    assert search_calls == 1
    assert load_calls == 1
    assert page._active_search_query == ""
    assert page._list_widget.count() == 3


def test_enter_and_search_button_apply_immediately(tmp_path: Path):
    page = _make_page(tmp_path)
    page._search_input.setText("pricing")
    page._search_input.returnPressed.emit()
    _wait_for_search(page)
    assert not page._search_debounce.isActive()
    assert page._active_search_query == "pricing"
    assert page._list_widget.count() == 1

    page._search_input.setText("dashboard")
    page._search_btn.click()
    _wait_for_search(page)
    assert not page._search_debounce.isActive()
    assert page._active_search_query == "dashboard"
    assert page._list_widget.count() == 1


def test_ctrl_f_focuses_search_and_escape_clears_without_resetting_display(
    tmp_path: Path
):
    page = _make_page(tmp_path)
    page._search_input.setText("pricing")
    page._on_search()
    _wait_for_search(page)
    sort_mode = page._sort_combo.currentData()
    group_mode = page._group_combo.currentData()
    view_mode = page._view_combo.currentData()

    page._list_widget.setFocus()
    _activate_shortcut(page, QKeySequence.Find)
    assert page._search_input.hasFocus()

    _activate_shortcut(page, QKeySequence(Qt.Key_Escape))
    assert page._search_input.text() == ""
    assert page._active_search_query == ""
    assert page._list_widget.count() == 3
    assert page._sort_combo.currentData() == sort_mode
    assert page._group_combo.currentData() == group_mode
    assert page._view_combo.currentData() == view_mode


def test_result_feedback_filename_tag_no_results_and_clear(tmp_path: Path):
    page = _make_page(tmp_path)
    page._search_input.setText("pricing")
    page._on_search()
    _wait_for_search(page)
    assert page._search_result_label.text() == '1 result for "pricing"'
    assert not page._search_result_label.isHidden()

    page._search_input.setText("customer")
    page._on_search()
    _wait_for_search(page)
    assert page._list_widget.count() == 1
    assert page._search_result_label.text() == '1 result for "customer"'

    page._search_input.setText("missing")
    page._on_search()
    _wait_for_search(page)
    assert page._list_stack.currentWidget() is page._list_empty
    assert page._list_empty_title.text() == "No screenshots found."
    assert page._list_empty_body.text() == (
        "Try another filename, tag, or phrase from an image."
    )
    assert page._empty_choose_folder_btn.isHidden()

    page._clear_search_btn.click()
    assert page._active_search_query == ""
    assert page._list_widget.count() == 3
    assert page._search_result_label.isHidden()


def test_search_copy_is_localized_and_empty_states_stay_distinct(tmp_path: Path):
    try:
        set_locale("en")
        page = _make_page(tmp_path)
        assert page._search_input.placeholderText() == (
            "Search filenames, tags, or text in images..."
        )
        page._search_input.setText("missing")
        page._on_search()
        _wait_for_search(page)
        assert page._list_empty_title.text() == "No screenshots found."
        assert page._list_empty_body.text() == (
            "Try another filename, tag, or phrase from an image."
        )

        page._on_clear_search()
        assert page._list_empty_title.text() != "No screenshots found."

        set_locale("ja")
        ja_page = _make_page(tmp_path / "ja")
        assert ja_page._search_input.placeholderText() == (
            "ファイル名、タグ、画像内の文字を検索..."
        )
        ja_page._search_input.setText("missing")
        ja_page._on_search()
        _wait_for_search(ja_page)
        assert ja_page._list_empty_title.text() == (
            "スクリーンショットが見つかりませんでした。"
        )
        assert ja_page._list_empty_body.text() == (
            "別のファイル名、タグ、または画像内の言葉を試してください。"
        )
    finally:
        set_locale("en")


def test_ocr_text_match_uses_unified_search_and_clear_restores_all(tmp_path: Path):
    page = _make_page(tmp_path)
    page._search_input.setText("revenue")
    page._on_search()
    assert page._search_result_label.text() == "Searching…"
    _wait_for_search(page)
    assert page._list_widget.count() == 1
    assert Path(page._list_widget.item(0).data(Qt.UserRole)).name == "notes.png"

    page._on_clear_search()
    assert page._list_widget.count() == 3
