"""Tests for Explorer-like Copy / Cut / Paste and image move."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import (
    CLIPBOARD_COPY,
    CLIPBOARD_CUT,
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
    image.fill(Qt.green)
    assert image.save(str(path), "PNG")


def test_copy_image_to_project_keeps_name_and_tags():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "Default"
        dst = root / "Research"
        src.mkdir()
        dst.mkdir()
        _write_png(src / "Error.png")

        service = MetadataService()
        service.ensure_sstool(src)
        service.ensure_sstool(dst)
        service.save_metadata(
            src,
            {"images": {"Error.png": {"tags": ["Debug", "Chrome"]}}},
        )
        service.save_metadata(dst, {"images": {}})

        dest_path = service.copy_image_to_project(src / "Error.png", dst)
        assert dest_path.name == "Error.png"
        assert dest_path.exists()
        assert (src / "Error.png").exists()

        dest_meta = json.loads(
            (dst / ".sstool" / "metadata.json").read_text(encoding="utf-8")
        )
        assert dest_meta["images"]["Error.png"]["tags"] == ["Debug", "Chrome"]


def test_move_image_to_project_moves_file_and_tags():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "A"
        dst = root / "B"
        src.mkdir()
        dst.mkdir()
        _write_png(src / "shot.png")

        service = MetadataService()
        service.ensure_sstool(src)
        service.ensure_sstool(dst)
        service.save_metadata(src, {"images": {"shot.png": {"tags": ["T"]}}})
        service.save_metadata(dst, {"images": {}})

        dest = service.move_image_to_project(src / "shot.png", dst)
        assert dest.name == "shot.png"
        assert dest.exists()
        assert not (src / "shot.png").exists()
        assert service.get_image_tags(dst, "shot.png") == ["T"]
        src_meta = service.load_metadata(src, force_reload=True)
        assert "shot.png" not in src_meta.get("images", {})


def test_delete_image_file_removes_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "Default"
        project.mkdir()
        _write_png(project / "x.png")
        service = MetadataService()
        service.ensure_sstool(project)
        service.save_metadata(project, {"images": {"x.png": {"tags": ["A"]}}})

        service.delete_image_file(project, "x.png")
        assert not (project / "x.png").exists()
        meta = service.load_metadata(project, force_reload=True)
        assert "x.png" not in meta.get("images", {})


def test_copy_switch_paste_into_current_folder():
    """Copy in A → switch to B → Paste duplicates PNG+tags into B."""
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_dir = root / "screenshots" / "A"
        dst_dir = root / "screenshots" / "B"
        src_dir.mkdir(parents=True)
        dst_dir.mkdir(parents=True)
        src_png = src_dir / "Error.png"
        _write_png(src_png)

        service = MetadataService()
        service.ensure_sstool(src_dir)
        service.ensure_sstool(dst_dir)
        service.save_metadata(
            src_dir,
            {"images": {"Error.png": {"tags": ["Debug"]}}},
        )
        service.save_metadata(dst_dir, {"images": {}})

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
        app.processEvents()

        assert page._clipboard_mode == CLIPBOARD_COPY
        assert page._clipboard_paths == [src_png]

        page._paste_clipboard()
        app.processEvents()

        dest = dst_dir / "Error.png"
        assert dest.exists()
        assert src_png.exists()
        assert service.get_image_tags(dst_dir, "Error.png") == ["Debug"]
        assert page._find_list_row(dest) >= 0


def test_cut_switch_paste_moves_into_current_folder():
    """Cut in A → switch to B → Paste moves PNG+tags into B."""
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_dir = root / "screenshots" / "A"
        dst_dir = root / "screenshots" / "B"
        src_dir.mkdir(parents=True)
        dst_dir.mkdir(parents=True)
        src_png = src_dir / "move_me.png"
        _write_png(src_png)

        service = MetadataService()
        service.ensure_sstool(src_dir)
        service.ensure_sstool(dst_dir)
        service.save_metadata(
            src_dir,
            {"images": {"move_me.png": {"tags": ["X"]}}},
        )
        service.save_metadata(dst_dir, {"images": {}})

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

        page._set_clipboard([src_png], CLIPBOARD_CUT)
        assert page._is_cut_path(src_png)

        with patch("app.ui.pages.images_page.save_config"):
            page._switch_folder("B")
        page._paste_clipboard()
        app.processEvents()

        dest = dst_dir / "move_me.png"
        assert dest.exists()
        assert not src_png.exists()
        assert service.get_image_tags(dst_dir, "move_me.png") == ["X"]
        assert page._clipboard_mode is None
        assert page._find_list_row(dest) >= 0


def test_sync_from_filesystem_picks_up_new_folder():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        default = root / "screenshots" / "Default"
        default.mkdir(parents=True)

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "window_width": 800,
            "window_height": 600,
            "images_folder_tree_expanded": True,
        }
        service = MetadataService()
        page = ImagesPage(config, service, ThumbnailCache(size=32), root)
        page.show()
        app.processEvents()

        assert "NewFolder" not in page._list_folder_names()
        (root / "screenshots" / "NewFolder").mkdir()
        with patch("app.ui.pages.images_page.save_config"):
            page._sync_from_filesystem()
        assert "NewFolder" in page._list_folder_names()


if __name__ == "__main__":
    test_copy_image_to_project_keeps_name_and_tags()
    test_move_image_to_project_moves_file_and_tags()
    test_delete_image_file_removes_metadata()
    test_copy_switch_paste_into_current_folder()
    test_cut_switch_paste_moves_into_current_folder()
    test_sync_from_filesystem_picks_up_new_folder()
    print("All clipboard / Explorer sync tests passed.")
