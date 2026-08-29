"""Find-first search behavior for the Images page."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.i18n import set_locale, t
from app.ui.pages.images_page import (
    ImagesPage,
    SEARCH_DEBOUNCE_MS,
    VISION_SEARCH_DEBOUNCE_MS,
)
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


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
    page._owned_vision_search_provider = search_provider
    page._test_search_database = database
    page.refresh()
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
    matches = [
        item
        for item in page.findChildren(QShortcut)
        if item.key().matches(sequence) == QKeySequence.ExactMatch
    ]
    shortcut = next((item for item in matches if item.parent() is page), matches[0])
    shortcut.activated.emit()
    _ensure_app().processEvents()


def test_typing_does_not_start_search_until_button_or_enter(
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
    assert not page._search_debounce.isActive()
    QTest.qWait(VISION_SEARCH_DEBOUNCE_MS + 60)
    _wait_for_search(page)
    assert search_calls == 0
    assert load_calls == 0
    assert page._active_search_query == ""
    assert len(gallery_image_items(page._list_widget)) == 3

    page._search_btn.click()
    _wait_for_search(page)
    assert search_calls == 1
    assert page._active_search_query == "pricing"
    assert page._list_widget.count() == 1

    page._clear_search_btn.click()
    _wait_for_search(page)
    assert load_calls == 1
    assert page._active_search_query == ""
    assert len(gallery_image_items(page._list_widget)) == 3


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


def test_explicit_submit_during_in_progress_search_is_accepted_and_shows_searching(
    tmp_path: Path,
):
    page = _make_page(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def slow_provider(_query, _folder, _candidates):
        entered.set()
        release.wait(2.0)
        return ()

    page._search_provider = slow_provider
    page._owned_vision_search_provider = slow_provider
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData("vision_relevance")
    )
    page._search_input.setText("an impossible scene")
    QTest.qWait(VISION_SEARCH_DEBOUNCE_MS + 60)
    assert not entered.is_set()
    assert not page._search_tasks
    assert len(gallery_image_items(page._list_widget)) == 3

    page._search_btn.click()
    assert entered.wait(1.0)
    assert page._search_tasks
    assert page._list_stack.currentWidget() is page._list_widget
    assert page._search_status_spinner.isVisible()
    assert page._search_result_label.text() == t("images.searching")

    page._search_result_label.hide()
    page._search_btn.click()

    assert page._search_result_label.isVisible()
    assert page._search_result_label.text() == t("images.searching")
    assert page._search_status_spinner.isVisible()
    assert len(page._search_tasks) == 1
    assert page._list_stack.currentWidget() is page._list_widget
    release.set()
    _wait_for_search(page)
    assert page._list_stack.currentWidget() is page._list_empty
    assert "0 results" in page._search_result_label.text()


def test_search_task_remains_page_owned_until_queued_completion(tmp_path: Path):
    page = _make_page(tmp_path)
    release = threading.Event()

    def slow_provider(_query, _folder, _candidates):
        release.wait(2.0)
        return ()

    page._search_provider = slow_provider
    page._owned_vision_search_provider = slow_provider
    page._search_input.setText("owned task")
    page._on_search()
    task = next(iter(page._search_tasks.values()))

    assert task.autoDelete() is False
    release.set()
    _wait_for_search(page)
    assert page._search_tasks == {}


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
    assert len(gallery_image_items(page._list_widget)) == 3
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
    assert "0 results" in page._search_result_label.text()
    assert not page._search_status_spinner.isVisible()

    page._clear_search_btn.click()
    assert page._active_search_query == ""
    assert len(gallery_image_items(page._list_widget)) == 3
    assert page._search_result_label.isHidden()


def test_meaning_search_keeps_filename_and_tag_matches(tmp_path: Path):
    page = _make_page(tmp_path)
    page._owned_vision_search_provider = lambda *_args: ()
    page._search_input.setText("pricing")
    page._on_search()
    _wait_for_search(page)
    assert [
        Path(page._list_widget.item(index).data(Qt.UserRole)).name
        for index in range(page._list_widget.count())
        if page._list_widget.item(index).data(Qt.UserRole)
    ] == ["pricing.png"]

    page._search_input.setText("customer")
    page._on_search()
    _wait_for_search(page)
    assert [
        Path(page._list_widget.item(index).data(Qt.UserRole)).name
        for index in range(page._list_widget.count())
        if page._list_widget.item(index).data(Qt.UserRole)
    ] == ["dashboard.png"]


def test_meaning_search_error_still_shows_filename_matches(tmp_path: Path):
    def boom(*_args):
        raise RuntimeError("vision unavailable")

    page = _make_page(tmp_path)
    page._owned_vision_search_provider = boom
    page._search_input.setText("pricing")
    page._on_search()
    _wait_for_search(page)
    assert Path(page._list_widget.item(0).data(Qt.UserRole)).name == "pricing.png"
    assert page._list_stack.currentWidget() is not page._list_empty


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


def test_ocr_text_match_uses_unified_search_and_clear_restores_all(
    tmp_path: Path, monkeypatch
):
    page = _make_page(tmp_path)
    monkeypatch.setattr(
        "app.ui.pages.images_page.search_indexed_images",
        page._search_provider,
    )
    page._search_input.setText("revenue")
    page._on_search()
    assert page._search_result_label.text() == "Searching…"
    _wait_for_search(page)
    assert page._list_widget.count() == 1
    assert Path(page._list_widget.item(0).data(Qt.UserRole)).name == "notes.png"

    page._on_clear_search()
    assert len(gallery_image_items(page._list_widget)) == 3


def test_single_search_box_uses_hybrid_order_ahead_of_sort_and_group(tmp_path: Path):
    page = _make_page(tmp_path)
    folder = Path(page._config["selected_folder"])

    def hybrid_provider(_query, _selected_folder, _candidates):
        return (folder / "notes.png", folder / "dashboard.png", folder / "pricing.png")

    page._search_provider = hybrid_provider
    page._owned_vision_search_provider = hybrid_provider
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData("vision_relevance")
    )
    assert page._active_search_mode == "vision_relevance"
    assert page._search_mode_combo.isHidden()
    page._sort_combo.setCurrentIndex(page._sort_combo.count() - 1)
    page._group_combo.setCurrentIndex(page._group_combo.count() - 1)
    page._search_input.setText("find my image")
    page._on_search()
    _wait_for_search(page)

    assert [
        Path(page._list_widget.item(index).data(Qt.UserRole)).name
        for index in range(page._list_widget.count())
    ] == ["notes.png", "dashboard.png", "pricing.png"]


def test_semantic_bundle_validation_is_deferred_off_page_construction(
    tmp_path: Path, monkeypatch
):
    import app.ui.images_search as images_search

    calls = []
    monkeypatch.setattr(
        images_search, "_installed_semantic_bundle",
        lambda: calls.append("validated") or None,
    )
    provider = images_search.HybridImagesSearchProvider()
    assert calls == []
    provider.close()


def test_semantic_mode_preserves_provider_top_k_order_and_skips_unanalyzed(tmp_path: Path):
    page = _make_page(tmp_path)
    folder = Path(page._config["selected_folder"])
    calls: list[str] = []

    def semantic_provider(query, selected_folder, _candidates):
        calls.append(query)
        assert selected_folder.resolve() == folder.resolve()
        # notes.png intentionally represents the only analyzed matches; the
        # remaining folder image is allowed to have no embedding.
        return (folder / "notes.png", folder / "pricing.png")

    page._semantic_search_provider = semantic_provider
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData("semantic")
    )
    page._search_input.setText("a chart about future revenue")
    page._on_search()
    _wait_for_search(page)

    assert calls == ["a chart about future revenue"]
    assert [
        Path(page._list_widget.item(index).data(Qt.UserRole)).name
        for index in range(page._list_widget.count())
    ] == ["notes.png", "pricing.png"]


def test_semantic_zero_results_and_worker_error_can_be_retried(tmp_path: Path):
    page = _make_page(tmp_path)
    folder = Path(page._config["selected_folder"])
    attempts = 0

    def semantic_provider(_query, _selected_folder, _candidates):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("worker unavailable")
        return ()

    page._semantic_search_provider = semantic_provider
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData("semantic")
    )
    page._search_input.setText("an impossible scene")
    page._on_search()
    _wait_for_search(page)
    assert page._list_empty_title.text() == "Search is temporarily unavailable."

    page._on_search()
    _wait_for_search(page)
    assert attempts == 2
    assert page._list_empty_title.text() == "No screenshots found."

    page._clear_search_btn.click()
    assert len(gallery_image_items(page._list_widget)) == 3


def test_cancelled_search_task_does_not_emit_error(tmp_path: Path):
    """Closing during an in-flight search must not surface Search error."""
    from app.ui.images_search import ImagesSearchTask

    app = _ensure_app()
    finished = []

    def provider(_query, _folder, _candidates):
        raise RuntimeError("worker stopped during shutdown")

    task = ImagesSearchTask(
        1, "chrome", tmp_path, (), provider, mode="vision_relevance"
    )
    task.signals.finished.connect(
        lambda *args: finished.append(args)
    )
    task.cancel()
    task.run()
    app.processEvents()
    assert len(finished) == 1
    assert finished[0][4] is None
