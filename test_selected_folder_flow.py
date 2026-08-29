"""T1 selected-folder behavior shared by Images, Organize, Home, and Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from app.services.metadata_service import MetadataService
from app.ui.pages.home_page import HomePage
from app.ui.pages.images_page import ImagesPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.work_page import WorkPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(12, 12, QImage.Format_RGB32)
    image.fill(Qt.darkGreen)
    assert image.save(str(path), "PNG")


def _wait_for_image_search(page: ImagesPage) -> None:
    for _ in range(500):
        if not page._search_tasks:
            return
        QTest.qWait(20)
    assert not page._search_tasks


def _config(folder: Path) -> dict:
    return {
        "selected_folder": str(folder),
        "screenshot_dir": str(folder.parent / "legacy-root"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
        "developer_search_mode": "text",
    }


def test_images_and_organize_share_direct_selected_folder(tmp_path: Path):
    _ensure_app()
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_png(selected / "one.png")
    nested = selected / "Nested"
    nested.mkdir()
    _write_png(nested / "ignored.png")

    config = _config(selected)
    service = MetadataService()
    service.add_image_tag(selected, "one.png", "findme")
    cache = ThumbnailCache(size=64)
    images = ImagesPage(config, service, cache, tmp_path)
    organize = WorkPage(config, service, cache, tmp_path)
    images.refresh()
    organize.refresh()

    assert images._get_folder_dir() == selected.resolve()
    assert organize._get_folder_dir() == selected.resolve()
    assert len(gallery_image_items(images._list_widget)) == 1
    assert organize._list.count() == 1

    images._search_input.setText("findme")
    images._on_search()
    _wait_for_image_search(images)
    assert images._list_widget.count() == 1
    images._search_input.setText("missing")
    images._on_search()
    _wait_for_image_search(images)
    assert images._list_widget.count() == 0


def test_home_reports_selected_folder_direct_totals(tmp_path: Path):
    _ensure_app()
    selected = tmp_path / "Selected"
    selected.mkdir()
    _write_png(selected / "one.png")
    nested = selected / "Nested"
    nested.mkdir()
    _write_png(nested / "ignored.png")
    page = HomePage(
        _config(selected), MetadataService(), ThumbnailCache(size=64), tmp_path
    )
    page.refresh()
    assert page._folder_path.text() == str(selected.resolve())
    assert page._total_value.text() == "1"


def test_settings_has_no_root_folder_control(tmp_path: Path):
    _ensure_app()
    page = SettingsPage(_config(tmp_path), tmp_path)
    visible_text = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "Root Folder" not in visible_text
    assert not hasattr(page, "_path_edit")
