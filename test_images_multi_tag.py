"""Images: assign / remove tags across multi-selection."""

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


def _make_page() -> tuple[ImagesPage, Path, list[Path]]:
    root = Path(tempfile.mkdtemp())
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    paths: list[Path] = []
    for name in ("a.png", "b.png", "c.png"):
        png = folder / name
        img = QImage(16, 16, QImage.Format_RGB32)
        img.fill(Qt.red)
        img.save(str(png))
        paths.append(png)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(), root)
    page._load_images()
    return page, root, paths


def test_assign_existing_tag_applies_to_all_selected():
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    app.processEvents()

    page._metadata_service.ensure_global_tag(root, "shared")
    page.reload_tag_choices()

    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)
    app.processEvents()
    assert len(page._selected_image_paths()) == 3

    idx = page._tag_combo.findData("shared")
    if idx < 0:
        idx = next(
            i
            for i in range(page._tag_combo.count())
            if "shared" in page._tag_combo.itemText(i).casefold()
        )
    page._tag_combo.setCurrentIndex(idx)
    page._on_assign_existing_tag()
    app.processEvents()

    for path in paths:
        assert "shared" in page._metadata_service.get_image_tags(
            path.parent, path.name
        )


def test_delete_tag_removes_from_all_selected():
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    app.processEvents()

    page._metadata_service.ensure_global_tag(root, "dropme")
    for path in paths:
        page._metadata_service.add_image_tag(path.parent, path.name, "dropme")

    page._load_images()
    app.processEvents()
    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)
    app.processEvents()

    page._delete_tag(paths[0], "dropme")
    app.processEvents()

    for path in paths:
        assert "dropme" not in page._metadata_service.get_image_tags(
            path.parent, path.name
        )
