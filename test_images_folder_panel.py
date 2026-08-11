"""Images selected-folder UI and empty states."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog

from app.services.metadata_service import MetadataService
from app.ui.design_tokens import (
    IMAGES_FOLDER_LOCATOR_MAX_WIDTH,
    IMAGES_FOLDER_LOCATOR_MIN_WIDTH,
)
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


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
    assert page._selected_folder_value.toolTip() == str(selected.resolve())
    assert page._choose_folder_btn.text() == "Choose Folder"
    assert not page._choose_folder_btn.icon().isNull()
    assert page._selected_folder_value.objectName() == "folderSelectorPath"

    page.resize(1100, 720)
    page.show()
    app.processEvents()
    page._sync_primary_control_widths()
    assert IMAGES_FOLDER_LOCATOR_MIN_WIDTH <= page._folder_selector.width()
    assert page._folder_selector.maximumWidth() <= IMAGES_FOLDER_LOCATOR_MAX_WIDTH
    # The redesign gives the selected folder its own full-width context row.
    left_layout = page._left_workspace.layout()
    assert left_layout.indexOf(page._folder_selector) >= 0
    assert left_layout.indexOf(page._folder_selector) < left_layout.indexOf(
        page._command_surface
    )
    assert page._command_primary_layout.indexOf(page._folder_selector) == -1
    assert page._command_primary_layout.indexOf(page._search_row) >= 0
    assert abs(page._command_surface.width() - page._list_panel.width()) <= 1
    folder_top = page._folder_selector.mapToGlobal(
        page._folder_selector.rect().topLeft()
    ).y()
    preview_top = page._preview_card.mapToGlobal(
        page._preview_card.rect().topLeft()
    ).y()
    assert abs(folder_top - preview_top) <= 1
    assert page._tags_card.isHidden()
    assert page._right_scroll_host.layout().indexOf(page._tags_card) == -1
    assert page._tags_card.parentWidget() is page._content


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
    assert page._list_widget.count() == 1
