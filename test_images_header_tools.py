"""Images Sort/Group/View tools stay fully visible (Organize-style chip)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QHBoxLayout

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import HEADER_TOOLS_INLINE_MIN_WIDTH, ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_page() -> ImagesPage:
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Capture").mkdir(parents=True)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    return ImagesPage(config, MetadataService(), ThumbnailCache(), root)


def _force_list_width(page: ImagesPage, list_width: int) -> None:
    """Pin splitter sizes so the Screenshots column has a known width."""
    page._splitter.setStretchFactor(0, 0)
    page._splitter.setStretchFactor(1, 0)
    page._splitter.setStretchFactor(2, 0)
    folder_w = 180
    right_w = 240
    page.resize(folder_w + list_width + right_w + 40, 640)
    page._splitter.setSizes([folder_w, list_width, right_w])
    QApplication.instance().processEvents()


def test_header_tools_always_on_dedicated_row():
    """Tools live under the title so the 28px title row never clips them."""
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()

    _force_list_width(page, HEADER_TOOLS_INLINE_MIN_WIDTH + 40)
    page._apply_header_tools_layout(force=True)
    assert page._header_tools_inline is False
    assert not page._header_tools_row.isHidden()
    assert page._header_tools.isVisible()
    # Chip must be taller than the compressed title-row height
    assert page._header_tools.height() >= 28

    _force_list_width(page, HEADER_TOOLS_INLINE_MIN_WIDTH - 100)
    page._apply_header_tools_layout(force=True)
    assert page._header_tools_inline is False
    assert not page._header_tools_row.isHidden()
    assert page._header_tools.isVisible()


def test_header_tools_horizontal_fields_like_organize():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()
    # Label and combo share a horizontal field (not stacked vertically)
    sort_field = page._sort_combo.parentWidget()
    assert sort_field is not None
    assert isinstance(sort_field.layout(), QHBoxLayout)


def test_header_tools_inline_threshold_constant():
    assert HEADER_TOOLS_INLINE_MIN_WIDTH >= 480
