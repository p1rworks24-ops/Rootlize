"""Images search and display controls preserve their visual priority."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from app.services.metadata_service import MetadataService
from app.ui.design_tokens import (
    IMAGES_LEFT_CARD_PAD_X,
    IMAGES_LEFT_CARD_PAD_Y,
    SPACE_2,
    WORKSPACE_PANEL_PADDING,
)
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
    assert page._header_tools.height() >= 28

    _force_list_width(page, HEADER_TOOLS_INLINE_MIN_WIDTH - 100)
    page._apply_header_tools_layout(force=True)
    assert page._header_tools_inline is False
    assert not page._header_tools_row.isHidden()
    assert page._header_tools.isVisible()


def test_search_precedes_tools_and_refresh_is_removed():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()

    content_layout = page._command_surface.parentWidget().layout()
    assert content_layout.indexOf(page._command_surface) < content_layout.indexOf(
        page._folder_browser
    )
    assert content_layout.indexOf(page._folder_browser) < content_layout.indexOf(
        page._list_panel
    )
    assert page._command_surface.layout().indexOf(page._command_primary_row) >= 0
    assert page._header_tools_row.parentWidget() is page._list_panel
    assert not hasattr(page, "_refresh_btn")
    assert page._fs_watcher.directories()


def test_folder_locator_heading_matches_library_typography():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()

    library_title = page._gallery_header.findChild(QLabel, "sectionTitle")
    assert library_title is not None
    assert page._folder_selector_title.font().pointSize() == library_title.font().pointSize()
    assert page._folder_selector_title.font().weight() == library_title.font().weight()


def test_long_folder_path_is_elided_but_available_as_tooltip():
    app = _ensure_app()
    page = _make_page()
    long_path = str(Path(tempfile.mkdtemp()) / ("very-long-folder-name-" * 8))
    page._selected_folder_value.setFixedWidth(100)
    page._selected_folder_value.setPath(long_path)
    page.show()
    app.processEvents()

    assert page._selected_folder_value.toolTip() == long_path
    assert page._selected_folder_value.text() != long_path
    assert "…" in page._selected_folder_value.text()


def test_header_tools_horizontal_fields_like_organize():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()
    # Label and combo share a horizontal field (not stacked vertically)
    sort_field = page._sort_combo.parentWidget()
    assert sort_field is not None
    assert isinstance(sort_field.layout(), QHBoxLayout)


def test_display_controls_and_panel_headers_have_balanced_insets():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()

    tools_margins = page._header_tools.layout().contentsMargins()
    assert tools_margins.left() == tools_margins.right() == 4

    list_layout = page._list_panel.layout()
    screenshots_header = page._gallery_header
    preview_header = page._preview_card.layout().itemAt(0).widget()
    preview_margins = preview_header.layout().contentsMargins()
    assert preview_margins.left() == preview_margins.right() == 0
    preview_card_margins = page._preview_card.layout().contentsMargins()
    assert preview_card_margins.left() == preview_card_margins.right() == (
        WORKSPACE_PANEL_PADDING
    )
    assert screenshots_header.findChild(QWidget, "sectionHeaderTitleRow") is not None
    assert preview_header.findChild(QWidget, "sectionHeaderTitleRow").height() == 28


def test_header_tools_inline_threshold_constant():
    assert HEADER_TOOLS_INLINE_MIN_WIDTH >= 480


def test_top_controls_are_not_coupled_to_screenshots_panel_width():
    app = _ensure_app()
    page = _make_page()
    page.resize(1200, 760)
    page.show()
    app.processEvents()
    page._sync_primary_control_widths()
    assert page._header_tools.isVisible()
    assert page._search_row.isVisible()


def test_gallery_header_is_full_bleed_under_rounded_panel():
    app = _ensure_app()
    page = _make_page()
    page.show()
    app.processEvents()

    list_margins = page._list_panel.layout().contentsMargins()
    assert list_margins.left() == 0
    assert list_margins.top() == 0
    assert list_margins.right() == 0
    header_margins = page._header_tools_row.layout().contentsMargins()
    assert header_margins.left() == IMAGES_LEFT_CARD_PAD_X + 8
    assert header_margins.top() == IMAGES_LEFT_CARD_PAD_Y
    assert header_margins.bottom() == SPACE_2
    assert page._header_tools_row.testAttribute(Qt.WA_StyledBackground)
    assert page._search_input.hasFrame() is False
    assert page._search_input.autoFillBackground() is False
    base = page._search_input.palette().color(QPalette.ColorRole.Base)
    assert base.alpha() == 0
