"""Tests for Explorer-like image drag-and-drop into folders."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListWidget

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.ui.widgets import (
    MIME_IMAGE_PATHS,
    build_folder_drop_pixmap,
    decode_image_paths,
    encode_image_paths,
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


def _make_page(root: Path, folder: str = "A") -> ImagesPage:
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": folder,
        "window_width": 900,
        "window_height": 700,
        "images_folder_tree_expanded": True,
    }
    service = MetadataService()
    page = ImagesPage(config, service, ThumbnailCache(size=32), root)
    page.refresh()
    return page


def test_encode_decode_image_paths_roundtrip():
    paths = [Path("C:/shots/a.png").resolve(), Path("C:/shots/b.png").resolve()]
    raw = encode_image_paths(paths)
    decoded = decode_image_paths(raw)
    assert decoded == paths


def test_build_folder_drop_pixmap_is_compact():
    _ensure_app()
    move_pix = build_folder_drop_pixmap(count=2, copy_mode=False)
    copy_pix = build_folder_drop_pixmap(count=2, copy_mode=True)
    assert not move_pix.isNull()
    assert not copy_pix.isNull()
    assert move_pix.width() <= 48
    assert copy_pix.width() <= 48


def test_undim_after_list_clear_does_not_raise():
    """Drop/move reloads the list; undim must not touch deleted items."""
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "A"
        folder.mkdir(parents=True)
        _write_png(folder / "one.png")
        service = MetadataService()
        service.ensure_sstool(folder)
        service.save_metadata(folder, {"images": {"one.png": {"tags": []}}})

        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        lw = page._list_widget
        items = [lw.item(i) for i in range(lw.count()) if lw.item(i).data(Qt.UserRole)]
        assert items
        lw._set_drag_sources_dimmed(items, True)
        lw.clear()  # simulates reload during/after drop
        lw._set_drag_sources_dimmed(None, False)  # must not raise


def test_screenshot_list_is_drag_only_no_reorder():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "A"
        folder.mkdir(parents=True)
        _write_png(folder / "one.png")
        service = MetadataService()
        service.ensure_sstool(folder)
        service.save_metadata(folder, {"images": {"one.png": {"tags": []}}})

        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        lw = page._list_widget
        assert lw.dragDropMode() == QAbstractItemView.DragOnly
        assert lw.movement() == QListWidget.Static
        assert not lw.acceptDrops()

        row = page._find_list_row(folder / "one.png")
        assert row >= 0
        item = lw.item(row)
        flags = item.flags()
        assert flags & Qt.ItemIsDragEnabled
        assert not (flags & Qt.ItemIsDropEnabled)


def test_drop_on_folder_moves_image_and_tags():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_dir = root / "screenshots" / "A"
        dst_dir = root / "screenshots" / "B"
        src_dir.mkdir(parents=True)
        dst_dir.mkdir(parents=True)
        src_png = src_dir / "drag_me.png"
        _write_png(src_png)

        service = MetadataService()
        service.ensure_sstool(src_dir)
        service.ensure_sstool(dst_dir)
        service.save_metadata(
            src_dir, {"images": {"drag_me.png": {"tags": ["Moved"]}}}
        )
        service.save_metadata(dst_dir, {"images": {}})

        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        page._on_paths_dropped_on_folder("B", [src_png], False)
        app.processEvents()

        dest = dst_dir / "drag_me.png"
        assert dest.exists()
        assert not src_png.exists()
        assert page._metadata_service.get_image_tags(dst_dir, "drag_me.png") == [
            "Moved"
        ]
        assert page._find_list_row(src_png) < 0


def test_drop_on_folder_ctrl_copy_keeps_source():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_dir = root / "screenshots" / "A"
        dst_dir = root / "screenshots" / "B"
        src_dir.mkdir(parents=True)
        dst_dir.mkdir(parents=True)
        src_png = src_dir / "copy_me.png"
        _write_png(src_png)

        service = MetadataService()
        service.ensure_sstool(src_dir)
        service.ensure_sstool(dst_dir)
        service.save_metadata(
            src_dir, {"images": {"copy_me.png": {"tags": ["Keep"]}}}
        )
        service.save_metadata(dst_dir, {"images": {}})

        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        page._on_paths_dropped_on_folder("B", [src_png], True)
        app.processEvents()

        dest = dst_dir / "copy_me.png"
        assert dest.exists()
        assert src_png.exists()
        assert page._metadata_service.get_image_tags(dst_dir, "copy_me.png") == [
            "Keep"
        ]


def test_folder_tree_accepts_image_mime():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "A"
        folder.mkdir(parents=True)
        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        tree = page._folder_tree
        assert tree.acceptDrops()
        assert tree.dragDropMode() == QAbstractItemView.DropOnly
        assert MIME_IMAGE_PATHS


def test_folder_tree_drop_highlight_selects_target():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("A", "B"):
            d = root / "screenshots" / name
            d.mkdir(parents=True)
        page = _make_page(root, "A")
        page.show()
        app.processEvents()

        tree = page._folder_tree
        target = None
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == "B":
                target = item
                break
        assert target is not None

        tree._begin_drop_session()
        tree._set_drop_highlight(target)
        assert tree.property("dropping") is True
        assert tree.currentItem() is target
        assert target.isSelected()

        tree._end_drop_session()
        assert tree.property("dropping") in (False, None)
        assert tree.currentItem() is not None
        assert tree.currentItem().data(0, Qt.UserRole) == "A"


if __name__ == "__main__":
    test_encode_decode_image_paths_roundtrip()
    test_build_explorer_drag_pixmap_has_size_and_badge_room()
    test_screenshot_list_is_drag_only_no_reorder()
    test_drop_on_folder_moves_image_and_tags()
    test_drop_on_folder_ctrl_copy_keeps_source()
    test_folder_tree_accepts_image_mime()
    print("All DnD tests passed.")
