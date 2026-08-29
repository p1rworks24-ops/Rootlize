"""Search workspace layout: intent cards, responsive grid, no h-scroll."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from app.services.metadata_service import MetadataService
from app.ui.main_window import MainWindow
from app.ui.pages.images_page import ITEM_KIND_HEADER, ITEM_KIND_ROLE, ImagesPage
from app.ui.styles import APP_STYLE
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import GRID_CARD_MIN_WIDTH, THUMBNAIL_MODE_SIZES

from conftest import gallery_image_items


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLE)
    return app


def _png(path: Path) -> None:
    image = QImage(12, 12, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _page_with_shots(tmp_path: Path, count: int = 8) -> ImagesPage:
    root = tmp_path / "Library"
    root.mkdir()
    for index in range(count):
        _png(root / f"shot-{index:02d}.png")
    config = {
        "selected_folder": str(root),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1600,
        "window_height": 900,
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=48), tmp_path)
    page.setStyleSheet(APP_STYLE)
    return page


def test_search_intent_toggle_is_removed_and_search_sits_above_folder_bar(tmp_path: Path):
    app = _app()
    page = _page_with_shots(tmp_path, count=1)
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    assert page.findChild(QWidget, "searchIntentControl") is None
    search_bottom = page._search_row.mapTo(page, page._search_row.rect().bottomLeft()).y()
    folder_top = page._folder_browser.mapTo(page, page._folder_browser.rect().topLeft()).y()
    assert search_bottom <= folder_top
    page.close()


def test_image_grid_fits_viewport_and_reflows(tmp_path: Path):
    app = _app()
    page = _page_with_shots(tmp_path, count=8)
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    page._set_gallery_layout("grid")
    page._thumbnail_mode = "large"
    page._apply_thumbnail_mode()
    app.processEvents()

    def assert_no_hscroll() -> int:
        viewport = page._list_widget.viewport().width()
        hbar = page._list_widget.horizontalScrollBar()
        assert page._list_widget.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert hbar.maximum() == 0
        columns, card_w, header_w = page._responsive_grid_metrics()
        assert columns >= 1
        assert card_w * columns <= viewport
        assert header_w <= viewport
        for i in range(page._list_widget.count()):
            item = page._list_widget.item(i)
            assert item.sizeHint().width() <= viewport
        return columns

    wide_cols = assert_no_hscroll()
    min_card = THUMBNAIL_MODE_SIZES["large"][1]
    assert wide_cols == page._responsive_grid_metrics()[0]
    card_w, card_h = page._current_card_size()
    media_w, media_h = page._grid_media_logical_size()
    assert card_h >= 180
    assert media_h >= int(media_w * 0.6)

    page.resize(1100, 900)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    mid_cols = assert_no_hscroll()

    page.resize(720, 900)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    narrow_cols = assert_no_hscroll()

    assert wide_cols >= mid_cols >= narrow_cols
    assert wide_cols > narrow_cols or min_card >= GRID_CARD_MIN_WIDTH


def test_main_window_1600x900_default_groups_by_date(tmp_path: Path):
    app = _app()
    shots = tmp_path / "shots"
    shots.mkdir()
    _png(shots / "a.png")
    _png(shots / "b.png")
    window = MainWindow(
        {
            "screenshot_dir": str(tmp_path / "screenshots"),
            "selected_folder": str(shots),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1600,
            "window_height": 900,
            "window_title": "Capixe",
        }
    )
    window.show()
    app.processEvents()
    window.resize(1600, 900)
    app.processEvents()
    page = window._images_page
    page.refresh()
    app.processEvents()
    assert window.width() == 1600
    assert window.height() == 900
    assert page._group_by == "date"
    assert page._list_widget.horizontalScrollBar().maximum() == 0
    window.close()


def test_list_layout_shows_multiple_rows(tmp_path: Path):
    app = _app()
    page = _page_with_shots(tmp_path, count=8)
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    page._set_gallery_layout("list")
    app.processEvents()
    assert len(gallery_image_items(page._list_widget)) == 8
    assert page._list_widget.flow() == QListWidget.TopToBottom
    assert page._list_widget.isWrapping() is False
    assert page._list_widget.horizontalScrollBar().maximum() == 0
    visible = 0
    viewport = page._list_widget.viewport().rect()
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        rect = page._list_widget.visualItemRect(item)
        if viewport.intersects(rect):
            visible += 1
    assert visible >= 4


def _open_grid_window(tmp_path: Path, width: int, height: int) -> tuple[MainWindow, ImagesPage]:
    shots = tmp_path / "shots"
    if not shots.exists():
        shots.mkdir()
        for index in range(24):
            _png(shots / f"shot-{index:02d}.png")
    window = MainWindow(
        {
            "screenshot_dir": str(tmp_path / "screenshots"),
            "selected_folder": str(shots),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": width,
            "window_height": height,
            "window_title": "Capixe",
            "capture_bar_visible": False,
        }
    )
    window.show()
    QApplication.instance().processEvents()
    window.resize(width, height)
    QApplication.instance().processEvents()
    page = window._images_page
    page.refresh()
    page._set_gallery_layout("grid")
    page._thumbnail_mode = "large"
    page._apply_thumbnail_mode()
    QApplication.instance().processEvents()
    return window, page


def test_main_window_1600x900_grid_keeps_readable_cards(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.ui.main_window.save_config", lambda config: None)
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    app = _app()
    window, page = _open_grid_window(tmp_path, 1600, 900)
    columns, card_w, _header_w = page._responsive_grid_metrics()
    assert columns >= 4
    assert card_w >= GRID_CARD_MIN_WIDTH
    viewport = page._list_widget.viewport().rect()
    visible_rows = set()
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        rect = page._list_widget.visualItemRect(item)
        if viewport.intersects(rect):
            visible_rows.add(rect.top())
    assert len(visible_rows) >= 3
    assert page._list_widget.horizontalScrollBar().maximum() == 0
    window.close()


def test_standard_desktop_grid_is_five_columns_and_can_grow(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.ui.main_window.save_config", lambda config: None)
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    app = _app()
    window, page = _open_grid_window(tmp_path, 1920, 1080)
    columns, card_w, _header_w = page._responsive_grid_metrics()
    assert columns == 5
    assert card_w >= GRID_CARD_MIN_WIDTH

    window._side_nav.set_expanded(False, animate=False)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    collapsed_cols, collapsed_w, _header_w = page._responsive_grid_metrics()
    assert collapsed_cols >= 6
    assert collapsed_w >= GRID_CARD_MIN_WIDTH

    sizes = list(page._splitter.sizes())
    sizes[2] = max(200, sizes[2] - 120)
    page._splitter.setSizes(sizes)
    app.processEvents()
    page._relayout_gallery_grid()
    app.processEvents()
    wide_cols, wide_w, _header_w = page._responsive_grid_metrics()
    assert wide_cols >= collapsed_cols
    assert wide_w >= GRID_CARD_MIN_WIDTH
    assert page._list_widget.horizontalScrollBar().maximum() == 0
    window.close()
