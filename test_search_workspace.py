"""Search workspace: folder browse, favorites, breadcrumb, AI panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.design_tokens import MOTION_SLOW_MS
from app.ui.page_motion import active_page_fade, motion_preferred, stop_page_fade
from app.ui.main_window import PAGE_IMAGES, MainWindow
from app.ui.caption_delegate import ITEM_KIND_FOLDER, ITEM_KIND_ROLE
from app.ui.pages.images_page import ImagesPage
from app.utils.folder_shortcuts import (
    is_favorite_folder,
    list_child_folders,
    list_favorite_folders,
    list_recent_folders,
    remember_recent_folder,
    set_favorite_folder_order,
    toggle_favorite_folder,
)
from app.utils.image_favorite import FAVORITE_TAG, apply_favorite_filter
from app.utils.sort_order import SORT_FAVORITES_FIRST, sort_png_files
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path) -> None:
    image = QImage(12, 12, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _page(tmp_path: Path) -> tuple[ImagesPage, Path]:
    _app()
    root = tmp_path / "Pictures"
    nested = root / "Screenshots" / "2026"
    nested.mkdir(parents=True)
    _png(nested / "shot.png")
    config = {
        "selected_folder": str(root),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "favorite_folders": [],
        "recent_folders": [],
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=48), tmp_path)
    page.refresh()
    return page, root


def test_child_folders_and_breadcrumb_navigation(tmp_path: Path):
    app = _app()
    page, root = _page(tmp_path)
    page.show()
    app.processEvents()
    children = [
        page._list_widget.item(i)
        for i in range(page._list_widget.count())
        if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_FOLDER
    ]
    names = [Path(item.data(Qt.UserRole)).name for item in children]
    assert names == ["Screenshots"]
    assert not page._folder_breadcrumb.isVisible()
    assert page._selected_folder_value.isVisible()
    assert page._folder_up_btn.isEnabled()
    assert not page._child_folders.isVisible()
    assert page._folder_browser.layout().indexOf(page._child_folders) == -1
    assert page._list_stack.currentWidget() is page._list_widget
    assert page._selected_folder_value.toolTip() == str(root.resolve())
    assert page._folder_breadcrumb.path() == root.resolve()

    page._on_item_clicked(children[0])
    app.processEvents()
    assert page._folder_breadcrumb.path() == root.resolve()
    page._on_item_double_clicked(children[0])
    app.processEvents()
    assert page._folder_breadcrumb.path() == (root / "Screenshots").resolve()
    assert page._selected_folder_value.toolTip() == str((root / "Screenshots").resolve())
    page._folder_breadcrumb.folder_activated.emit(str(root.resolve()))
    app.processEvents()
    assert page._folder_breadcrumb.path() == root.resolve()
    page.open_folder(root / "Screenshots")
    app.processEvents()
    page._go_to_parent_folder()
    app.processEvents()
    assert page._folder_breadcrumb.path() == root.resolve()
    page._navigate_folder_forward()
    app.processEvents()
    assert page._folder_breadcrumb.path() == (root / "Screenshots").resolve()
    page._list_widget.setFocus(Qt.OtherFocusReason)
    page._shortcut_folder_back()
    app.processEvents()
    assert page._folder_breadcrumb.path() == root.resolve()


def test_folder_favorite_and_recent_shortcuts(tmp_path: Path):
    page, root = _page(tmp_path)
    nested = root / "Screenshots"
    page.open_folder(nested)
    assert list_recent_folders(page._config)[0] == nested.resolve()
    page._toggle_current_folder_favorite()
    assert is_favorite_folder(page._config, nested)
    assert list_favorite_folders(page._config)[0] == nested.resolve()
    assert page._favorite_folder_btn.property("favorited") is True
    page._toggle_current_folder_favorite()
    assert not is_favorite_folder(page._config, nested)
    assert page._favorite_folder_btn.property("favorited") is False


def test_image_favorite_filter_and_sort(tmp_path: Path):
    folder = tmp_path / "Library"
    folder.mkdir()
    older = folder / "older.png"
    newer = folder / "newer.png"
    _png(older)
    _png(newer)
    metadata = {
        "images": {
            "older.png": {"tags": [FAVORITE_TAG]},
            "newer.png": {"tags": []},
        }
    }
    only_fav = apply_favorite_filter([older, newer], metadata, "favorites_only")
    assert [path.name for path in only_fav] == ["older.png"]
    ranked = sort_png_files(
        [older, newer],
        SORT_FAVORITES_FIRST,
        favorite_names={"older.png"},
    )
    assert [path.name for path in ranked] == ["older.png", "newer.png"]


def test_search_is_home_and_ai_panel_toggles(tmp_path: Path):
    app = _app()
    shots = tmp_path / "screenshots" / "Default"
    shots.mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(tmp_path / "screenshots"),
            "selected_folder": str(shots),
            "current_folder": "Default",
            "save_folder": "Default",
            "favorite_folders": [str(shots)],
            "window_width": 1100,
            "window_height": 700,
            "window_title": "Capixe",
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
        }
    )
    window.show()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES
    labels = {
        btn.property("navLabel") for btn in window._side_nav._nav_buttons.values()
    }
    assert t("nav.images") in labels
    assert t("nav.home") not in labels
    assert t("nav.about") in labels
    assert t("nav.images") == "Images"
    pins = [
        label
        for label in window._side_nav.findChildren(QLabel)
        if label.objectName() == "navFolderPin"
    ]
    assert pins
    pix = pins[0].pixmap()
    assert pix is not None and not pix.isNull()
    assert pins[0].accessibleName() == t("nav.favorites")
    assert "★" not in pins[0].accessibleName()
    assert all(
        row.objectName() == "navFolderRow" for row in window._side_nav._folder_buttons
    )
    assert "Search" not in labels
    assert "AI (Coming Soon)" not in labels
    page = window._images_page
    assert page._right_panel.isVisible()
    assert page._right_stack.currentWidget() is page._preview_page
    grid_width = page._list_panel.width()
    page._toggle_ai_panel()
    app.processEvents()
    assert page._right_panel.isVisible()
    assert page._right_stack.currentWidget() is page._ai_page
    assert page._action_input.isVisible()
    page._toggle_ai_panel()
    app.processEvents()
    assert page._right_panel.isVisible()
    assert page._right_stack.currentWidget() is page._preview_page
    assert page._list_panel.width() >= grid_width - 2
    window.close()


def test_toolbar_keeps_only_primary_controls_visible(tmp_path: Path):
    page, _root = _page(tmp_path)
    page.show()
    QApplication.instance().processEvents()
    assert page._filter_combo.isHidden()
    assert page._sort_combo.isVisible()
    assert page._layout_toggle.isVisible()
    assert page._filter_label.isHidden()
    assert page._sort_label.isVisible()
    assert page._layout_label.isHidden()
    grid_btn, list_btn = page._layout_toggle._buttons
    assert not grid_btn.icon().isNull()
    assert not list_btn.icon().isNull()
    assert grid_btn.text() == ""
    assert list_btn.text() == ""
    assert not page._group_combo.isVisible()
    assert not page._view_combo.isVisible()
    assert page._view_menu_btn.isHidden()
    assert page._clear_search_btn.text() == ""
    assert page._clear_search_btn.accessibleName() == t("images.clear")
    assert page._sort_combo.itemData(0) == "date"
    assert not page._show_tags_checkbox.isVisible()
    assert page._show_tags_checkbox.parentWidget() is page._tags_display_row
    assert page._actions_tags_btn.isVisible()
    tools = page._header_tools.layout()
    assert tools.indexOf(page._actions_tags_btn) < tools.indexOf(page._layout_field)
    assert tools.indexOf(page._layout_field) == tools.count() - 1
    assert page._thumbnail_mode == "small"
    assert page.findChild(QWidget, "searchIntentControl") is None
    assert not hasattr(page, "_search_mode_toggle")
    assert not page._folder_breadcrumb.isVisible()
    assert page._selected_folder_value.isVisible()
    assert page.findChild(QWidget, "searchCaptureButton") is None
    assert page.findChild(QWidget, "searchHeaderRow") is not None
    assert page._ask_ai_btn.parentWidget() is page._preview_page
    assert page.findChild(type(page._search_row), "searchUtilityRow") is None
    assert page._search_btn.parentWidget().objectName() == "screenshotsSearchShell"
    folder = tmp_path / "root"
    (folder / "keep").mkdir(parents=True)
    (folder / ".sstool").mkdir()
    (folder / ".hidden").mkdir()
    assert [path.name for path in list_child_folders(folder)] == ["keep"]


def test_three_column_preview_and_ask_ai_switch(tmp_path: Path):
    app = _app()
    folder = tmp_path / "Library"
    folder.mkdir()
    _png(folder / "shot.png")
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
    )
    page.resize(1600, 900)
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()

    assert page._left_workspace.isVisible()
    assert page._list_panel.isVisible()
    assert page._right_panel.isVisible()
    assert page._preview_page.isVisible()
    assert page._preview_card.isVisible()
    assert page._information_card.isVisible()
    assert page._information_card.parentWidget() is page._preview_card
    assert page._information_card.objectName() == "previewInfoSection"
    assert page._preview_view.maximumHeight() == 228
    assert page._preview_view.height() <= 228
    assert page._search_row.isVisible()
    assert page._header_tools_row.isVisible()
    assert page._ask_ai_btn.text() == t("images.ai.ask")
    assert page._ask_ai_btn.parentWidget() is page._preview_page
    assert abs(page._ask_ai_btn.width() - page._preview_card.width()) <= 2
    assert page._thumbnail_mode == "small"
    assert page._list_widget.horizontalScrollBar().maximum() == 0

    item = gallery_image_items(page._list_widget)[0]
    page._list_widget.setCurrentItem(item)
    item.setSelected(True)
    page._show_image(item)
    app.processEvents()
    assert page._file_info_label.toolTip() == "shot.png"
    assert page._preview_view.has_image()

    page._ask_ai_btn.click()
    app.processEvents()
    assert page._right_stack.currentWidget() is page._ai_page
    fade = active_page_fade(page._right_stack)
    if motion_preferred():
        assert fade is not None
        assert fade["anim"].duration() == MOTION_SLOW_MS
        assert fade["overlay"].graphicsEffect() is None
        stop_page_fade(page._right_stack)
    else:
        assert fade is None
    assert page._ai_page.graphicsEffect() is None
    assert page.findChild(QWidget, "askAiPanelCard") is not None
    assert page._action_input.isVisible()
    assert page._ai_history.isVisible()
    assert page._preview_mode_btn.objectName() == "aiPanelClose"
    assert not page._preview_mode_btn.icon().isNull()
    assert page._action_preview_btn.objectName() == "aiSendButton"
    assert not page._action_preview_btn.isEnabled()
    page._action_input.setText("find screenshots")
    assert page._action_preview_btn.isEnabled()
    page._action_input.clear()
    assert not page._action_preview_btn.isEnabled()
    assert page._list_widget.currentItem() is item
    page._preview_mode_btn.click()
    app.processEvents()
    assert page._right_stack.currentWidget() is page._preview_page
    assert page._preview_card.isVisible()
    assert page._information_card.isVisible()
    assert page._list_widget.currentItem() is item
    assert page._file_info_label.toolTip() == "shot.png"
    assert page._list_widget.horizontalScrollBar().maximum() == 0


def test_remember_recent_folder_dedupes(tmp_path: Path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    config: dict = {}
    remember_recent_folder(config, first)
    remember_recent_folder(config, second)
    remember_recent_folder(config, first)
    assert [path.name for path in list_recent_folders(config)] == ["a", "b"]
    toggle_favorite_folder(config, second)
    assert list_favorite_folders(config)[0].name == "b"


def test_set_favorite_folder_order_reorders_without_dropping(tmp_path: Path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    third = tmp_path / "c"
    extra = tmp_path / "d"
    for folder in (first, second, third, extra):
        folder.mkdir()
    config = {"favorite_folders": [str(first), str(second), str(third)]}
    ordered = set_favorite_folder_order(config, [second, extra, first])
    assert [path.name for path in ordered] == ["b", "a", "c"]
    assert list_favorite_folders(config)[0].name == "b"
