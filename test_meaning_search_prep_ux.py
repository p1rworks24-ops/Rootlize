"""Meaning-search preparation and progressive search status UX."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton

from app.i18n import set_locale, t
from app.ui.pages.settings_page import SettingsPage
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.ui.search_busy import format_searching_status
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


def _app():
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(path), "PNG")


def _page(tmp_path: Path, count: int = 3, *, mode: str = "vision_relevance") -> ImagesPage:
    folder = tmp_path / "Selected"
    folder.mkdir(parents=True)
    for index in range(1, count + 1):
        _write_png(folder / f"{index}.png")
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "developer_search_mode": mode,
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=32),
        tmp_path,
        search_provider=lambda *_args: (),
        semantic_search_provider=lambda *_args: (),
    )
    page._load_images()
    return page


def test_searching_status_copy_keeps_progress_and_match_count():
    set_locale("en")
    assert format_searching_status(matches=0) == "Searching…"
    assert format_searching_status(matches=4) == "Searching… · 4 matches"
    assert format_searching_status(
        matches=4, checked=48, total=119
    ) == "Searching… 48 / 119 · 4 matches"


def test_progressive_batches_show_searching_then_complete(tmp_path):
    app = _app()
    set_locale("en")
    page = _page(tmp_path, 5)
    folder = Path(page._config["selected_folder"])
    paths = [folder / f"{index}.png" for index in range(1, 6)]
    page.show()
    app.processEvents()
    page._active_search_query = "dog"
    page._search_request_id = 7
    page._progressive_visible_paths[7] = []
    page._list_widget.clear()

    page._progress_unified_search(7, "dog", str(folder.resolve()), (paths[0],), 2, 5)
    assert page._search_status_spinner.isVisible()
    assert page._search_result_label.text() == "Searching… 2 / 5 · 1 matches"
    assert page._list_stack.currentWidget() is page._list_widget
    assert page._library_prep_label.isHidden() or "Searching" not in page._library_prep_label.text()

    page._progress_unified_search(
        7, "dog", str(folder.resolve()), (paths[0], paths[2]), 5, 5
    )
    assert page._search_status_spinner.isVisible()
    assert "Searching" in page._search_result_label.text()
    assert page._list_widget.count() == 2

    page._finish_unified_search(7, "dog", str(folder.resolve()), (paths[0], paths[2]), None)
    assert not page._search_status_spinner.isVisible()
    assert page._search_result_label.text() == '2 results for "dog"'
    page.close()


def test_zero_matches_still_shows_search_complete(tmp_path):
    app = _app()
    set_locale("en")
    page = _page(tmp_path, 3)
    folder = Path(page._config["selected_folder"])
    page.show()
    app.processEvents()
    page._active_search_query = "nothing"
    page._search_request_id = 4
    page._progressive_visible_paths[4] = []
    page._list_widget.clear()
    page._set_search_status(t("images.searching"), searching=True)
    page._finish_unified_search(4, "nothing", str(folder.resolve()), (), None)
    assert page._list_stack.currentWidget() is page._list_empty
    assert "0 results" in page._search_result_label.text()
    assert not page._search_status_spinner.isVisible()
    page.close()


def test_cancel_stops_searching_indicator_and_ignores_stale_progress(tmp_path):
    app = _app()
    set_locale("en")
    page = _page(tmp_path, 4)
    folder = Path(page._config["selected_folder"])
    paths = [folder / f"{index}.png" for index in range(1, 5)]
    page.show()
    app.processEvents()
    page._active_search_query = "dog"
    page._search_request_id = 9
    page._progressive_visible_paths[9] = []

    class _CancelledTask:
        mode = "vision_relevance"

        class _Flag:
            def is_set(self):
                return True

        _cancelled = _Flag()

    page._search_tasks[9] = _CancelledTask()
    page._progress_unified_search(9, "dog", str(folder.resolve()), (paths[0],), 2, 4)
    page._finish_unified_search(9, "dog", str(folder.resolve()), (paths[0], paths[1]), None)
    assert not page._search_status_spinner.isVisible()
    assert page._list_widget.count() == 1

    page._search_request_id = 10
    page._progress_unified_search(9, "dog", str(folder.resolve()), (paths[3],), 4, 4)
    assert page._list_widget.count() == 1
    page.close()


def test_text_search_still_finds_filename_matches(tmp_path):
    app = _app()
    set_locale("en")
    page = _page(tmp_path, 1, mode="text")
    folder = Path(page._config["selected_folder"])
    page.show()
    app.processEvents()
    page._search_input.setText("1")
    page._on_search()
    while page._search_tasks:
        app.processEvents()
    names = [
        Path(page._list_widget.item(row).data(Qt.UserRole)).name
        for row in range(page._list_widget.count())
    ]
    assert names == ["1.png"]
    assert gallery_image_items(page._list_widget)
    page.close()
    del folder


def test_in_progress_search_keeps_grid_visible_without_overlay(tmp_path):
    app = _app()
    set_locale("en")
    page = _page(tmp_path, 3)
    release = threading.Event()

    def slow_provider(_query, _folder, _candidates):
        release.wait(2.0)
        return ()

    page._owned_vision_search_provider = slow_provider
    page.show()
    app.processEvents()
    page._active_search_query = "scene"
    page._start_unified_search("scene")
    assert page._search_tasks
    assert page._list_stack.currentWidget() is page._list_widget
    assert page._search_status_spinner.isVisible()
    assert page._search_result_label.text() == t("images.searching")
    release.set()
    while page._search_tasks:
        app.processEvents()
    page.close()


def test_settings_keeps_reanalyze_library_maintenance_action(tmp_path):
    _app()
    set_locale("en")
    page = SettingsPage(
        {
            "window_width": 1600,
            "window_height": 900,
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        tmp_path,
    )
    buttons = [button.text() for button in page.findChildren(QPushButton)]
    assert t("settings.maintenance.reanalyze") in buttons
    assert t("images.analysis.action") not in buttons
