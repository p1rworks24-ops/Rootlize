"""Images Viewing folder panel: collapse chrome and expand-on-click."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import FOLDER_PANEL_COLLAPSED_WIDTH, ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_page(tmp: str) -> ImagesPage:
    root = Path(tmp)
    (root / "screenshots").mkdir()
    config = {
        "screenshot_dir": "screenshots",
        "window_width": 1050,
        "window_height": 600,
        "filename_template": "{date}_{time}",
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    return ImagesPage(config, MetadataService(), ThumbnailCache(size=64), root)


def test_images_splitter_has_no_gray_handle_style_object():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page = _make_page(tmp)
        assert page._splitter.objectName() == "imagesSplitter"
        assert page._folder_panel.layout().contentsMargins().left() == 10
        page.close()


def test_viewing_folder_starts_expanded_even_if_config_says_collapsed():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "images_folder_tree_expanded": False,
        }
        page = ImagesPage(config, MetadataService(), ThumbnailCache(size=64), root)
        assert page._folder_tree_expanded is True
        assert not page._folder_header.isHidden()
        assert not page._folder_body.isHidden()
        assert page._folder_expand_glyph.isHidden()
        assert config["images_folder_tree_expanded"] is True
        page.close()


def test_collapsed_folder_panel_expands_on_frame_click():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        page = _make_page(tmp)
        page.show()
        app.processEvents()
        page._apply_folder_tree_expanded(False, persist=False)
        app.processEvents()
        assert page._folder_tree_expanded is False
        assert page._folder_panel.maximumWidth() == FOLDER_PANEL_COLLAPSED_WIDTH
        assert page._folder_panel.cursor().shape() == Qt.PointingHandCursor
        assert page._folder_expand_glyph.isVisible()
        assert page._folder_expand_glyph.text() == "▶"
        assert not page._folder_collapse_btn.isVisible()
        assert not page._folder_header.isVisible()

        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPoint(8, 20),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        app.sendEvent(page._folder_panel, release)
        app.processEvents()
        assert page._folder_tree_expanded is True
        assert not page._folder_expand_glyph.isVisible()
        assert page._folder_collapse_btn.isVisible()
        assert page._folder_header.isVisible()
        assert page._folder_body.isVisible()
        assert "Viewing" in (page._folder_header_title.text() if page._folder_header_title else "")
        page.close()
