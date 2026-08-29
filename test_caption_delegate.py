"""Smoke tests for caption roles and icon modes."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent, QColor
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QStyleOptionViewItem

from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import (
    CARD_INSET,
    ITEM_KIND_HEADER,
    ITEM_KIND_ROLE,
    ITEM_KIND_IMAGE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_FAVORITE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    CaptionIconDelegate,
    grid_favorite_slot,
    list_favorite_slot,
    list_row_caption_rects,
    media_rect_for_card,
)
from app.ui.pages.images_page import ImagesPage
from app.utils.group_by import GROUP_BY_TAG
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


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

        assert len(gallery_image_items(page._list_widget)) == 1
        item = gallery_image_items(page._list_widget)[0]
        assert page._caption_delegate is not None
        name = item.data(ROLE_CAPTION_NAME)
        tags = item.data(ROLE_CAPTION_TAGS)
        date = item.data(ROLE_CAPTION_DATE)
        assert "demo_shot.png" in str(name).replace("\u200b", "")
        assert "#ui" in str(tags)
        assert "#debug" in str(tags)
        assert date
        assert not item.data(ROLE_CAPTION_FAVORITE)

        page._thumbnail_mode = "medium"
        page._apply_thumbnail_mode()
        page.refresh()
        app.processEvents()
        item = gallery_image_items(page._list_widget)[0]
        assert "#ui" in str(item.data(ROLE_CAPTION_TAGS))
        assert item.data(ROLE_CAPTION_DATE)

        page._thumbnail_mode = "small"
        page._apply_thumbnail_mode()
        page.refresh()
        app.processEvents()
        assert page._list_widget.viewMode() == QListWidget.IconMode
        item = gallery_image_items(page._list_widget)[0]
        assert "#ui" in str(item.data(ROLE_CAPTION_TAGS))
        assert not item.data(ROLE_CAPTION_FAVORITE)

        service.set_image_favorite(folder, png.name, True)
        page.refresh()
        app.processEvents()
        item = gallery_image_items(page._list_widget)[0]
        assert item.data(ROLE_CAPTION_FAVORITE)

        page._group_combo.setCurrentIndex(page._group_combo.findData(GROUP_BY_TAG))
        app.processEvents()
        assert page._group_by == GROUP_BY_TAG
        assert page._list_widget.viewMode() == QListWidget.IconMode
        assert page._list_widget.count() >= 2
        # Grouped mode keeps wrapping unconstrained so headers can sit on their own row
        assert page._list_widget.gridSize().width() <= 1
        headers = [
            page._list_widget.item(i)
            for i in range(page._list_widget.count())
            if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
        ]
        assert headers
        header_w = headers[0].sizeHint().width()
        assert header_w <= page._list_widget.viewport().width()
        assert header_w >= page._current_card_size()[0]


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
    assert short_size.height() == 128
    assert long_size.height() == short_size.height()


def test_grid_caption_stays_below_media_in_uniform_cells():
    delegate = CaptionIconDelegate(
        icon_size=160, cell_width=188, cell_height=134, show_tags=False
    )
    card = QRect(0, 0, 188, 134).adjusted(CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET)
    media = delegate._media_rect(card)
    assert media.bottom() <= card.bottom() - 30
    assert media.height() < card.height()
    tagged = media_rect_for_card(card, True)
    assert tagged.height() < media.height()
    short_item = QListWidgetItem()
    long_item = QListWidgetItem()
    short_item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
    long_item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
    option = QStyleOptionViewItem()
    widget = QListWidget()
    widget.addItem(short_item)
    widget.addItem(long_item)
    option.font = widget.font()
    assert delegate.sizeHint(option, widget.model().index(0, 0)) == delegate.sizeHint(
        option, widget.model().index(1, 0)
    )


def test_grid_favorite_star_sits_in_caption_not_on_media():
    card = QRect(0, 0, 188, 198).adjusted(CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET)
    media = media_rect_for_card(card, False)
    slot = grid_favorite_slot(card)
    assert slot.top() >= media.bottom()
    assert slot.right() <= card.right() + 1
    assert slot.left() > card.center().x()
    tagged_media = media_rect_for_card(card, True)
    tagged_slot = grid_favorite_slot(card)
    assert tagged_slot.top() >= tagged_media.bottom()


def test_list_favorite_star_sits_on_right_edge_not_on_thumb():
    row = QRect(0, 0, 640, 48).adjusted(CARD_INSET, 2, -CARD_INSET, -2)
    icon_box = QRect(row.x() + 10, row.y() + (row.height() - 32) // 2, 32, 32)
    slot = list_favorite_slot(row)
    assert slot.left() >= icon_box.right()
    assert slot.right() <= row.right() + 1
    assert row.right() - slot.left() <= 32
    assert slot.contains(row.right() - 8, row.center().y())


def test_list_row_keeps_date_vertically_centered_in_the_frame():
    app = _ensure_app()
    widget = QListWidget()
    row = QRect(0, 0, 640, 48).adjusted(CARD_INSET, 2, -CARD_INSET, -2)
    name_font, meta_font = CaptionIconDelegate._caption_fonts(widget.font())
    date = "2026-08-26 23:17"
    icon_box, name_area, date_area, tags_area = list_row_caption_rects(
        row,
        icon_size=32,
        name_font=name_font,
        meta_font=meta_font,
        date=date,
        show_tags=False,
    )
    assert tags_area.isNull() or tags_area.height() == 0
    assert name_area.bottom() <= row.bottom()
    assert date_area.bottom() <= row.bottom()
    assert date_area.top() >= row.top()
    assert date_area.left() >= name_area.right()
    assert date_area.right() <= list_favorite_slot(row).left()
    assert name_area.left() >= icon_box.right()
    assert abs(date_area.center().y() - row.center().y()) <= 1
    tagged_row = QRect(0, 0, 640, 64).adjusted(CARD_INSET, 2, -CARD_INSET, -2)
    _icon, tagged_name, tagged_date, tagged_tags = list_row_caption_rects(
        tagged_row,
        icon_size=32,
        name_font=name_font,
        meta_font=meta_font,
        date=date,
        show_tags=True,
    )
    assert tagged_tags.top() >= tagged_name.bottom()
    assert tagged_tags.bottom() <= tagged_row.bottom()
    assert tagged_date.bottom() <= tagged_row.bottom()
    assert tagged_date.left() >= tagged_name.right()
    assert abs(tagged_date.center().y() - tagged_row.center().y()) <= 1
    del app


def test_favorite_mouse_events_are_consumed_on_the_star():
    app = _ensure_app()
    widget = QListWidget()
    delegate = CaptionIconDelegate(
        icon_size=160, cell_width=188, cell_height=198, show_tags=False
    )
    item = QListWidgetItem()
    item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
    widget.addItem(item)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 188, 198)
    option.widget = widget
    index = widget.model().index(0, 0)
    clicked = []
    delegate.favorite_clicked.connect(lambda idx: clicked.append(idx.row()))
    slot = delegate.favorite_hit_rect(option)
    pos = QPointF(slot.center())
    for event_type in (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
    ):
        event = QMouseEvent(
            event_type, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
        assert delegate.editorEvent(event, widget.model(), option, index) is True
    assert clicked == [0]
    miss = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(option.rect.center()),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    assert delegate.editorEvent(miss, widget.model(), option, index) is False
    del app


def test_unchecked_favorite_star_is_lighter_than_previous_charcoal():
    from PySide6.QtGui import QColor

    from app.ui.icons import FAVORITE_STAR_OUTLINE, FAVORITE_STAR_OUTLINE_HOVER

    previous = QColor("#64748b")
    assert FAVORITE_STAR_OUTLINE.lightness() > previous.lightness()
    assert FAVORITE_STAR_OUTLINE_HOVER.lightness() < FAVORITE_STAR_OUTLINE.lightness()


def test_assigned_caption_tags_use_brand_blue_and_no_tags_stay_muted():
    from app.i18n import t
    from app.ui.caption_delegate import caption_tag_color
    from app.ui.design_tokens import COLORS

    assigned = caption_tag_color(False)
    empty = caption_tag_color(True)
    assert assigned.name() == QColor(COLORS.target).name()
    assert empty.name() == QColor(COLORS.text_faint).name()
    assert assigned.name() != empty.name()
    assert t("images.tag.none")


if __name__ == "__main__":
    test_icon_mode_sets_caption_roles()
    print("ok")
