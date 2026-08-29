"""Images selected-folder UI and empty states."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_page(tmp_path: Path, selected: str = "") -> ImagesPage:
    config = {
        "screenshot_dir": str(tmp_path / "legacy-root"),
        "selected_folder": selected,
        "current_folder": "Capture",
        "save_folder": "Capture",
    }
    return ImagesPage(config, MetadataService(), ThumbnailCache(size=64), tmp_path)


def test_images_replaces_root_tree_with_selected_folder_ui(tmp_path: Path):
    app = _ensure_app()
    selected = tmp_path / "Pictures"
    selected.mkdir()
    page = _make_page(tmp_path, str(selected))
    page.refresh()
    assert page._folder_panel.isHidden()
    assert not page._right_panel.isHidden()
    assert page._folder_breadcrumb.path() == selected.resolve()
    assert not page._selected_folder_value.isHidden()
    assert page._choose_folder_btn.text() == "Choose folder"
    assert not page._choose_folder_btn.icon().isNull()
    assert page._selected_folder_value.objectName() == "folderSelectorPath"

    page.resize(1100, 720)
    page.show()
    app.processEvents()
    page._sync_primary_control_widths()
    assert page._folder_selector.width() >= 200
    # The redesign gives the selected folder its own full-width context row.
    left_layout = page._left_workspace.layout()
    assert left_layout.indexOf(page._folder_browser) >= 0
    assert left_layout.indexOf(page._command_surface) < left_layout.indexOf(
        page._folder_browser
    )
    assert left_layout.indexOf(page._folder_browser) < left_layout.indexOf(
        page._list_panel
    )
    assert page._folder_browser.layout().indexOf(page._folder_selector) >= 0
    assert page._command_primary_layout.indexOf(page._folder_selector) == -1
    assert page._command_primary_layout.indexOf(page._search_row) >= 0
    assert abs(page._command_surface.width() - page._list_panel.width()) <= 1
    assert abs(page._folder_browser.width() - page._list_panel.width()) <= 1
    assert page._list_panel.width() >= page._command_surface.width() - 1
    command_left = page._command_surface.mapTo(page._left_workspace, page._command_surface.rect().topLeft()).x()
    folder_left = page._folder_browser.mapTo(page._left_workspace, page._folder_browser.rect().topLeft()).x()
    list_left = page._list_panel.mapTo(page._left_workspace, page._list_panel.rect().topLeft()).x()
    assert command_left == folder_left == list_left
    assert page._tags_card.isHidden()
    assert page._right_scroll_host.layout().indexOf(page._tags_card) == -1
    assert page._tags_card.parentWidget() in (page, page.window())
    assert bool(page._tags_card.windowFlags() & Qt.Tool)


def test_images_unselected_and_missing_folder_states(tmp_path: Path):
    _ensure_app()
    page = _make_page(tmp_path)
    page.refresh()
    assert page._list_empty_title.text() == "Choose a folder to get started"
    assert page._list_empty_body.text() == (
        "Select a screenshot folder, analyze your images, then search using "
        "the words you remember."
    )

    missing = tmp_path / "Removed"
    page._config["selected_folder"] = str(missing)
    page.refresh()
    assert page._list_empty_title.text() == (
        "The previously selected folder could not be found."
    )


def test_images_choose_folder_persists_and_loads_direct_pngs(
    tmp_path: Path, monkeypatch
):
    app = _ensure_app()
    selected = tmp_path / "Chosen"
    selected.mkdir()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(selected / "direct.png"), "PNG")

    page = _make_page(tmp_path)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(selected)
    )
    page._choose_selected_folder()
    app.processEvents()
    assert page._config["selected_folder"] == str(selected.resolve())
    assert page._get_folder_dir() == selected.resolve()
    assert len(gallery_image_items(page._list_widget)) == 1
