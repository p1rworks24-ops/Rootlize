"""Images preview clears when selection is empty; Clear does not reselect."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_page_with_png() -> tuple[ImagesPage, Path]:
    root = Path(tempfile.mkdtemp())
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    png = folder / "shot.png"
    img = QImage(32, 32, QImage.Format_RGB32)
    img.fill(Qt.red)
    img.save(str(png))
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(), root)
    page._load_images()
    return page, png


def _first_image_item(page: ImagesPage):
    for i in range(page._list_widget.count()):
        candidate = page._list_widget.item(i)
        if candidate is not None and candidate.data(Qt.UserRole):
            return candidate
    return None


def test_deselect_clears_preview():
    app = _ensure_app()
    page, _png = _make_page_with_png()
    page.show()
    app.processEvents()

    item = _first_image_item(page)
    assert item is not None
    page._list_widget.setCurrentItem(item)
    item.setSelected(True)
    app.processEvents()
    assert page._preview_cache_path is not None

    page._list_widget.clearSelection()
    page._list_widget.setCurrentItem(None)
    app.processEvents()
    assert page._preview_cache_path is None
    assert page._preview_label.pixmap() is None or page._preview_label.pixmap().isNull()


def test_clear_search_does_not_reselect_after_deselect():
    app = _ensure_app()
    page, _png = _make_page_with_png()
    page.show()
    app.processEvents()

    item = _first_image_item(page)
    assert item is not None
    page._list_widget.setCurrentItem(item)
    item.setSelected(True)
    app.processEvents()
    assert page._preview_cache_path is not None

    # Background-click path: clear selection + current
    page._list_widget.clearSelection()
    page._list_widget.setCurrentItem(None)
    app.processEvents()
    assert page._get_selected_path() is None
    assert page._preview_cache_path is None

    # Stale currentItem without selection must not restore on Clear
    page._list_widget.blockSignals(True)
    page._list_widget.setCurrentItem(item)
    item.setSelected(False)
    page._list_widget.blockSignals(False)
    assert not item.isSelected()
    assert page._get_selected_path() is None

    page._on_clear_search()
    app.processEvents()
    assert page._get_selected_path() is None
    assert not page._selected_image_items()
    assert page._preview_cache_path is None
