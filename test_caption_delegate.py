"""Smoke tests for caption roles and icon modes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem

from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import (
    ITEM_KIND_HEADER,
    ITEM_KIND_ROLE,
    ITEM_KIND_IMAGE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    CaptionIconDelegate,
)
from app.ui.pages.images_page import ImagesPage
from app.utils.group_by import GROUP_BY_TAG
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_icon_mode_sets_caption_roles():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "screenshots" / "Capture"
        folder.mkdir(parents=True)
        png = folder / "demo_shot.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "window_width": 900,
            "window_height": 700,
        }
        service = MetadataService()
        service.ensure_sstool(folder)
        service.register_image(folder, png.name)
        service.add_image_tag(folder, png.name, "ui")
        service.add_image_tag(folder, png.name, "#debug")

        page = ImagesPage(config, service, ThumbnailCache(), root)
        page.show()
        page._thumbnail_mode = "large"
        page._apply_thumbnail_mode()
        page.refresh()
        app.processEvents()

        assert page._list_widget.count() == 1
        item = page._list_widget.item(0)
        assert page._caption_delegate is not None
        name = item.data(ROLE_CAPTION_NAME)
        tags = item.data(ROLE_CAPTION_TAGS)
        date = item.data(ROLE_CAPTION_DATE)
        assert "demo_shot.png" in str(name).replace("\u200b", "")
        assert "#ui" in str(tags)
        assert "#debug" in str(tags)
        assert date

        page._thumbnail_mode = "medium"
        page._apply_thumbnail_mode()
        page.refresh()
        app.processEvents()
        item = page._list_widget.item(0)
        assert "#ui" in str(item.data(ROLE_CAPTION_TAGS))
        assert item.data(ROLE_CAPTION_DATE)

        page._thumbnail_mode = "small"
        page._apply_thumbnail_mode()
        page.refresh()
        app.processEvents()
        assert page._list_widget.viewMode() == QListWidget.IconMode
        item = page._list_widget.item(0)
        assert "#ui" in str(item.data(ROLE_CAPTION_TAGS))

        page._group_combo.setCurrentIndex(page._group_combo.findData(GROUP_BY_TAG))
        app.processEvents()
        assert page._group_by == GROUP_BY_TAG
        assert page._list_widget.viewMode() == QListWidget.IconMode
        assert page._list_widget.count() >= 2
        # Grouped mode must clear fixed grid so headers can span a full row
        assert page._list_widget.gridSize().width() <= 1
        headers = [
            page._list_widget.item(i)
            for i in range(page._list_widget.count())
            if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
        ]
        assert headers
        assert headers[0].sizeHint().width() >= page._list_widget.viewport().width() - 16


def test_long_filename_expands_card_height_for_full_caption():
    app = _ensure_app()
    widget = QListWidget()
    delegate = CaptionIconDelegate(icon_size=64, cell_width=100, cell_height=128)
    option = QStyleOptionViewItem()
    option.font = widget.font()

    short_item = QListWidgetItem()
    short_item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
    short_item.setData(ROLE_CAPTION_NAME, "short.png")
    widget.addItem(short_item)

    long_item = QListWidgetItem()
    long_item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
    long_item.setData(
        ROLE_CAPTION_NAME,
        "this_is_a_very_long_capture_filename_that_must_be_visible_in_full.png",
    )
    widget.addItem(long_item)
    app.processEvents()

    short_size = delegate.sizeHint(option, widget.model().index(0, 0))
    long_size = delegate.sizeHint(option, widget.model().index(1, 0))
    assert short_size.height() >= 128
    assert long_size.height() > short_size.height()


if __name__ == "__main__":
    test_icon_mode_sets_caption_roles()
    print("ok")
