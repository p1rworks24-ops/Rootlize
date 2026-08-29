"""Explorer-like rubber-band selection on ScreenshotListWidget."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QListWidgetItem,
)

from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import ITEM_KIND_HEADER, ITEM_KIND_IMAGE, ITEM_KIND_ROLE
from app.ui.pages.images_page import ImagesPage
from app.ui.pages.work_page import WorkPage
from app.ui.widgets import ScreenshotListWidget
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import THUMBNAIL_MODE_SIZES


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _png(folder: Path, name: str) -> Path:
    path = folder / name
    img = QImage(16, 16, QImage.Format_RGB32)
    img.fill(Qt.blue)
    img.save(str(path))
    return path


def test_images_select_all_includes_the_final_image_and_skips_headers():
    _ensure_app()
    list_w = ScreenshotListWidget()
    list_w.configure_explorer_selection()

    for index in range(3):
        item = QListWidgetItem(f"image-{index}")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        item.setData(Qt.UserRole, f"C:/images/{index}.png")
        list_w.addItem(item)
        if index == 0:
            header = QListWidgetItem("Group")
            header.setFlags(Qt.ItemIsEnabled)
            header.setData(ITEM_KIND_ROLE, ITEM_KIND_HEADER)
            list_w.addItem(header)

    page = SimpleNamespace(_list_widget=list_w)
    ImagesPage._select_all_images(page)

    selected = ImagesPage._selected_image_items(page)
    assert len(selected) == 3
    assert selected[-1].data(Qt.UserRole) == "C:/images/2.png"
    assert list_w.item(list_w.count() - 1).isSelected()


def test_marquee_from_empty_selects_items():
    app = _ensure_app()
    list_w = ScreenshotListWidget()
    list_w.setViewMode(QListWidget.IconMode)
    list_w.configure_explorer_selection()
    list_w.setDragEnabled(False)
    list_w.setGridSize(QSize(80, 80))
    list_w.resize(400, 300)
    list_w.show()
    app.processEvents()

    for i in range(3):
        item = QListWidgetItem(f"item-{i}")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setSizeHint(QSize(80, 80))
        list_w.addItem(item)

    app.processEvents()
    union = QRect()
    for i in range(list_w.count()):
        union = union.united(list_w.visualItemRect(list_w.item(i)))
    assert not union.isEmpty()
    list_w._apply_marquee_selection(union.adjusted(-1, -1, 1, 1))
    assert len(list_w.selectedItems()) == list_w.count()
    list_w.close()


def test_marquee_keeps_scrolled_out_items_selected():
    """Selection uses stable content coordinates while the viewport scrolls."""
    app = _ensure_app()
    list_w = ScreenshotListWidget()
    list_w.setViewMode(QListWidget.ListMode)
    list_w.configure_explorer_selection()
    list_w.setDragEnabled(False)
    list_w.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    list_w.resize(240, 120)
    list_w.show()

    for i in range(12):
        item = QListWidgetItem(f"item-{i}")
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setSizeHint(QSize(200, 36))
        list_w.addItem(item)
    app.processEvents()

    origin = list_w._content_pos(QPoint(2, 2))
    first_card = list_w._content_card_rect(list_w.item(0))
    list_w.verticalScrollBar().setValue(180)
    app.processEvents()
    last_card = list_w._content_card_rect(list_w.item(8))
    selection = QRect(origin, last_card.bottomRight()).normalized()
    list_w._apply_marquee_selection(selection)

    assert not list_w.visualItemRect(list_w.item(0)).intersects(list_w.viewport().rect())
    assert list_w.item(0).isSelected()
    assert list_w.item(8).isSelected()
    list_w.close()


def test_click_outside_card_frame_starts_marquee_not_select():
    """Cell padding around a card must not select; it starts rubber-band instead."""
    from app.ui.caption_delegate import CARD_INSET

    app = _ensure_app()
    list_w = ScreenshotListWidget()
    list_w.setViewMode(QListWidget.IconMode)
    list_w.configure_explorer_selection()
    list_w.setDragEnabled(False)
    list_w.setGridSize(QSize(100, 100))
    list_w.setSpacing(8)
    list_w.resize(400, 300)
    list_w.show()
    app.processEvents()

    item = QListWidgetItem("card")
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    item.setSizeHint(QSize(100, 100))
    list_w.addItem(item)
    app.processEvents()

    cell = list_w.visualItemRect(item)
    # Corner of the cell is outside the painted card (CARD_INSET)
    pad = QPointF(cell.left() + 1, cell.top() + 1)
    assert not list_w._card_rect(item).contains(pad.toPoint())

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pad,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    list_w.mousePressEvent(press)
    assert list_w._marquee_origin is not None
    assert not item.isSelected()
    assert CARD_INSET >= 4
    list_w.close()


def test_empty_click_clears_without_blocking_marquee_state():
    app = _ensure_app()
    list_w = ScreenshotListWidget()
    list_w.configure_explorer_selection()
    list_w.resize(300, 200)
    item = QListWidgetItem("a")
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    list_w.addItem(item)
    item.setSelected(True)
    list_w.setCurrentItem(item)
    app.processEvents()

    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(280, 180),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    list_w.mousePressEvent(press)
    assert list_w._marquee_origin is not None
    assert len(list_w.selectedItems()) == 0

    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(280, 180),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    list_w.mouseReleaseEvent(release)
    assert list_w._marquee_origin is None
    list_w.close()


def test_images_and_organize_keep_selection_across_view_sizes():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    for name in ("a.png", "b.png", "c.png"):
        _png(folder, name)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    images = ImagesPage(config, MetadataService(), ThumbnailCache(), root)
    work = WorkPage(config, MetadataService(), ThumbnailCache(), root)
    work.refresh()
    images._load_images()
    app.processEvents()

    for mode in THUMBNAIL_MODE_SIZES:
        images._set_thumbnail_mode(mode)
        idx = work._view_combo.findData(mode)
        if idx >= 0:
            work._view_combo.setCurrentIndex(idx)
        else:
            work._thumbnail_mode = mode
            work._apply_thumbnail_mode()
        app.processEvents()
        assert (
            images._list_widget.selectionMode()
            == QAbstractItemView.ExtendedSelection
        )
        assert images._list_widget.isSelectionRectVisible() is True
        assert work._list.selectionMode() == QAbstractItemView.ExtendedSelection
        assert work._list.isSelectionRectVisible() is True
    images.close()
    work.close()
    app.processEvents()
