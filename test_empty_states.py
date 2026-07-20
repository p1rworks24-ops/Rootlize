"""Home / Images empty-state guidance for zero-image libraries."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from app.i18n import set_locale, t
from app.services.metadata_service import MetadataService
from app.ui.pages.home_page import HomePage
from app.ui.pages.images_page import ImagesPage
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


def _make_home(root: Path, *, with_image: bool = False) -> HomePage:
    shots = root / "screenshots" / "Capture"
    shots.mkdir(parents=True)
    if with_image:
        _write_png(shots / "shot.png")
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "home_stats_mode": "folder",
    }
    page = HomePage(
        config,
        MetadataService(),
        ThumbnailCache(size=64),
        root,
    )
    page.refresh()
    return page


def _make_images(root: Path, folder: str = "Capture") -> ImagesPage:
    (root / "screenshots" / folder).mkdir(parents=True, exist_ok=True)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": folder,
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    page = ImagesPage(
        config,
        MetadataService(),
        ThumbnailCache(size=64),
        root,
    )
    page.refresh()
    return page


def test_home_empty_hint_shown_when_zero_images():
    _ensure_app()
    set_locale("en")
    with tempfile.TemporaryDirectory() as tmp:
        page = _make_home(Path(tmp), with_image=False)
        assert not page._empty_hint.isHidden()
        titles = [
            lab.text()
            for lab in page._empty_hint.findChildren(QLabel)
            if lab.objectName() == "emptyHintTitle"
        ]
        assert titles == [t("home.empty_title")]


def test_home_empty_hint_hidden_when_images_exist():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page = _make_home(Path(tmp), with_image=True)
        assert page._empty_hint.isHidden()


def test_images_empty_hint_for_empty_folder():
    app = _ensure_app()
    set_locale("en")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        page = _make_images(root, "Capture")
        app.processEvents()
        assert page._list_stack.currentIndex() == 1
        assert page._list_empty_title.text() == t("images.empty_title")


def test_images_empty_hint_hidden_when_folder_has_images():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "Capture"
        folder.mkdir(parents=True)
        _write_png(folder / "a.png")
        page = _make_images(root, "Capture")
        app.processEvents()
        assert page._list_stack.currentIndex() == 0


def test_images_empty_hint_updates_on_folder_switch():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        empty = root / "screenshots" / "Empty"
        filled = root / "screenshots" / "Filled"
        empty.mkdir(parents=True)
        filled.mkdir(parents=True)
        _write_png(filled / "b.png")

        page = _make_images(root, "Empty")
        app.processEvents()
        assert page._list_stack.currentIndex() == 1

        page._config["current_folder"] = "Filled"
        page.on_folder_changed()
        app.processEvents()
        assert page._list_stack.currentIndex() == 0

        page._config["current_folder"] = "Empty"
        page.on_folder_changed()
        app.processEvents()
        assert page._list_stack.currentIndex() == 1


def test_empty_state_i18n_ja():
    set_locale("ja")
    assert t("home.empty_title") == "まだスクリーンショットがありません"
    assert "Capture" in t("home.empty_body")
    assert t("images.empty_title") == "このフォルダには画像がありません。"
    set_locale("en")
    assert t("home.empty_title") == "No screenshots yet"


def test_empty_hint_card_object_name():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page = _make_home(Path(tmp))
        assert isinstance(page._empty_hint, QFrame)
        assert page._empty_hint.objectName() == "emptyHintCard"
