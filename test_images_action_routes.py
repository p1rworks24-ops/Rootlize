"""Images UI routes Create Folder / Move / Rename / Tags through app.actions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from app.actions import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ActionService,
)
from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import CLIPBOARD_CUT, ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path, color=Qt.blue) -> Path:
    image = QImage(12, 12, QImage.Format_RGB32)
    image.fill(color)
    assert image.save(str(path), "PNG")
    return path


def test_images_page_actions_share_registry_and_keep_image_id(tmp_path: Path, monkeypatch):
    app = _app()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    selected = tmp_path / "Pictures"
    dest = tmp_path / "Archive"
    selected.mkdir()
    dest.mkdir()
    one = _png(selected / "one.png")
    two = _png(selected / "two.png", Qt.red)

    database = OCRDatabase(tmp_path / "ocr.sqlite3").open()
    ocr = OCRRepository(database)
    records = []
    for path in (one, two):
        fingerprint = calculate_quick_fingerprint(path)
        record = ocr.upsert_image(
            path,
            size_bytes=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,
            quick_fingerprint=fingerprint,
        )
        ocr.save_ocr_document(record.image_id, status="ready", ocr_text=f"ocr-{path.stem}")
        records.append(record)
    first_id, second_id = records[0].image_id, records[1].image_id

    page = ImagesPage(
        {
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "selected_folder": str(selected),
            "favorite_folders": [],
            "recent_folders": [],
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
    )
    page._action_ocr = lambda: (ocr, None)
    page.refresh()
    page.show()
    app.processEvents()

    seen: list[str] = []
    original = ActionService.execute

    def wrapped(self, request, *, confirmed=False):
        seen.append(request.action_id)
        return original(self, request, confirmed=confirmed)

    monkeypatch.setattr(ActionService, "execute", wrapped)

    created = page._create_child_folder_named("Dogs")
    assert created == selected / "Dogs"
    assert created.is_dir()

    page._add_tag_to_paths([one, two], "work")
    page._add_tag_to_paths([one], "work")
    page._remove_tag_from_paths([two], "missing")
    page._remove_tag_from_paths([one, two], "work")

    page._set_paths_favorite([one, two], True)
    page._set_paths_favorite([one], True)
    page._set_paths_favorite([two], False)

    page._select_path_in_list(one)
    with patch("app.ui.pages.images_page.QInputDialog.getText", return_value=("renamed", True)):
        page._rename_selected_image()
    renamed = selected / "renamed.png"
    assert renamed.exists()
    assert not one.exists()

    page._move_selected_images_to(dest, [renamed, two])
    app.processEvents()
    assert (dest / "renamed.png").exists()
    assert (dest / "two.png").exists()

    assert seen == [
        ACTION_CREATE_FOLDER,
        ACTION_ADD_TAG,
        ACTION_ADD_TAG,
        ACTION_REMOVE_TAG,
        ACTION_REMOVE_TAG,
        ACTION_ADD_FAVORITE,
        ACTION_ADD_FAVORITE,
        ACTION_REMOVE_FAVORITE,
        ACTION_RENAME,
        ACTION_MOVE,
    ]
    assert ocr.get_image(first_id).image_id == first_id
    assert Path(ocr.get_image(first_id).path).resolve() == (dest / "renamed.png").resolve()
    assert ocr.get_ocr_document(first_id).ocr_text == "ocr-one"
    assert ocr.get_ocr_document(second_id).ocr_text == "ocr-two"
    assert page._metadata_service.get_image_tags(dest, "renamed.png") == []
    assert page._metadata_service.is_image_favorite(dest, "renamed.png") is True
    assert page._metadata_service.is_image_favorite(dest, "two.png") is False
    page.close()
    database.close()


def test_dnd_and_cut_paste_use_move_action(tmp_path: Path, monkeypatch):
    app = _app()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)

    root = tmp_path / "screenshots"
    source = root / "A"
    dest = root / "B"
    source.mkdir(parents=True)
    dest.mkdir()
    src = _png(source / "drag.png")
    cut_src = _png(source / "cut.png", Qt.green)

    page = ImagesPage(
        {
            "screenshot_dir": str(root),
            "current_folder": "A",
            "save_folder": "A",
            "window_width": 800,
            "window_height": 600,
            "images_folder_tree_expanded": True,
        },
        MetadataService(),
        ThumbnailCache(size=32),
        tmp_path,
    )
    page.show()
    app.processEvents()

    seen: list[str] = []
    original = ActionService.execute

    def wrapped(self, request, *, confirmed=False):
        seen.append(request.action_id)
        return original(self, request, confirmed=confirmed)

    monkeypatch.setattr(ActionService, "execute", wrapped)
    page._on_paths_dropped_on_folder("B", [src], False)
    app.processEvents()
    assert (dest / "drag.png").exists()
    assert not src.exists()

    page._set_clipboard([cut_src], CLIPBOARD_CUT)
    with patch("app.ui.pages.images_page.save_config"):
        page._switch_folder("B")
    app.processEvents()
    page._paste_clipboard()
    app.processEvents()
    assert (dest / "cut.png").exists()
    assert not cut_src.exists()
    assert seen == [ACTION_MOVE, ACTION_MOVE]
    page.close()
