"""Organize image list: Images-like context menu and clipboard shortcuts."""

from __future__ import annotations

import tempfile
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.work_page import CLIPBOARD_COPY, WorkPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(20, 20, QImage.Format_RGB32)
    image.fill(Qt.red)
    assert image.save(str(path), "PNG")


def _make_page(tmp: str) -> tuple[WorkPage, Path]:
    root = Path(tmp)
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    png = folder / "a.png"
    _write_png(png)
    config = {
        "screenshot_dir": "screenshots",
        "current_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
        "filename_template": "{date}_{time}",
    }
    page = WorkPage(config, MetadataService(), ThumbnailCache(size=64), root)
    page.refresh()
    return page, png


def test_organize_context_menu_has_images_actions():
    from PySide6.QtWidgets import QMenu

    from app.i18n import t
    from app.ui.image_list_menu import populate_image_list_context_menu

    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page, _png = _make_page(tmp)
        page.show()
        app.processEvents()
        assert page._list.count() >= 1
        page._list.item(0).setSelected(True)
        assert page._list.contextMenuPolicy() == Qt.CustomContextMenu

        menu = QMenu(page)
        populate_image_list_context_menu(
            menu,
            page,
            thumbnail_mode=page._thumbnail_mode,
            selected_count=1,
            has_clipboard=False,
            on_set_thumbnail_mode=lambda _m: None,
            on_open=lambda: None,
            on_copy=lambda: None,
            on_cut=lambda: None,
            on_paste=lambda: None,
            on_rename=lambda: None,
            on_delete=lambda: None,
            on_explorer=lambda: None,
        )
        texts = [a.text() for a in menu.actions() if a.text()]
        assert t("images.open") in texts
        assert t("common.copy") in texts
        assert t("common.cut") in texts
        assert t("common.paste") in texts
        assert t("images.rename_title") in texts
        page.close()
    _ = app


def test_organize_copy_publishes_system_clipboard_urls():
    from unittest.mock import patch

    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page, png = _make_page(tmp)
        page._list.item(0).setSelected(True)
        with patch(
            "app.ui.pages.work_page.set_files_on_clipboard"
        ) as mock_set:
            page._copy_selected_images()
            mock_set.assert_called_once()
            args, kwargs = mock_set.call_args
            assert kwargs.get("cut") is False
            assert any(Path(p).resolve() == png.resolve() for p in args[0])
        assert page._clipboard_mode == CLIPBOARD_COPY
        page.close()
    _ = app


def test_organize_has_standard_edit_shortcuts():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page, _png = _make_page(tmp)
        shortcuts = page.findChildren(QShortcut)
        assert any(
            s.key().matches(QKeySequence.Copy) == QKeySequence.ExactMatch
            for s in shortcuts
        )
        assert any(
            s.key().matches(QKeySequence.Cut) == QKeySequence.ExactMatch
            for s in shortcuts
        )
        assert any(
            s.key().matches(QKeySequence.Paste) == QKeySequence.ExactMatch
            for s in shortcuts
        )
        page.close()
    _ = app
