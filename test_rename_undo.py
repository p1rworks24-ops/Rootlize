"""Tests for rename and single-level undo."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import (
    CLIPBOARD_COPY,
    ImagesPage,
)
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_png(path: Path) -> None:
    image = QImage(24, 24, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def test_rename_image_updates_file_and_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "Default"
        project.mkdir()
        _write_png(project / "old.png")
        service = MetadataService()
        service.ensure_sstool(project)
        service.save_metadata(project, {"images": {"old.png": {"tags": ["A"]}}})

        dest = service.rename_image(project, "old.png", "new.png")
        assert dest.name == "new.png"
        assert dest.exists()
        assert not (project / "old.png").exists()
        assert service.get_image_tags(project, "new.png") == ["A"]


def test_undo_paste_copy_removes_created_file():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "screenshots" / "A"
        dst = root / "screenshots" / "B"
        src.mkdir(parents=True)
        dst.mkdir(parents=True)
        src_png = src / "shot.png"
        _write_png(src_png)

        service = MetadataService()
        service.ensure_sstool(src)
        service.ensure_sstool(dst)
        service.save_metadata(src, {"images": {"shot.png": {"tags": ["T"]}}})
        service.save_metadata(dst, {"images": {}})

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "A",
            "window_width": 800,
            "window_height": 600,
            "images_folder_tree_expanded": True,
        }
        page = ImagesPage(config, service, ThumbnailCache(size=32), root)
        page.show()
        app.processEvents()

        page._set_clipboard([src_png], CLIPBOARD_COPY)
        with patch("app.ui.pages.images_page.save_config"):
            page._switch_folder("B")
        page._paste_clipboard()
        app.processEvents()

        pasted = dst / "shot.png"
        assert pasted.exists()
        page._undo_last_action()
        app.processEvents()
        assert not pasted.exists()


def test_undo_rename_restores_name():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "screenshots" / "Default"
        project.mkdir(parents=True)
        _write_png(project / "alpha.png")

        service = MetadataService()
        service.ensure_sstool(project)
        service.save_metadata(project, {"images": {"alpha.png": {"tags": []}}})

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "window_width": 800,
            "window_height": 600,
            "images_folder_tree_expanded": True,
        }
        page = ImagesPage(config, service, ThumbnailCache(size=32), root)
        page.show()
        app.processEvents()
        page._load_images(force_reload_metadata=True)
        app.processEvents()

        src = project / "alpha.png"
        assert page._find_list_row(src) >= 0
        page._select_path_in_list(src)

        with patch(
            "app.ui.pages.images_page.QInputDialog.getText",
            return_value=("beta", True),
        ):
            page._rename_selected_image()
        app.processEvents()

        assert (project / "beta.png").exists()
        assert not (project / "alpha.png").exists()

        page._undo_last_action()
        app.processEvents()
        assert (project / "alpha.png").exists()
        assert not (project / "beta.png").exists()


if __name__ == "__main__":
    test_rename_image_updates_file_and_metadata()
    test_undo_paste_copy_removes_created_file()
    test_undo_rename_restores_name()
    print("All rename/undo tests passed.")
