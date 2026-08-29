"""High-quality Images preview, bounded zoom, fit, and open behavior."""

from __future__ import annotations

from pathlib import Path
import re
import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage, PreviewImageView
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_image(path: Path, width: int, height: int, *, alpha: bool = False) -> None:
    image_format = QImage.Format_ARGB32 if alpha else QImage.Format_RGB32
    image = QImage(width, height, image_format)
    image.fill(QColor(20, 120, 220, 120) if alpha else QColor("#1478dc"))
    assert image.save(str(path), "PNG")


def _make_page(tmp_path: Path) -> tuple[ImagesPage, Path]:
    app = _ensure_app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    _write_image(folder / "large.png", 1600, 900)
    _write_image(folder / "small.png", 48, 32)
    _write_image(folder / "portrait.png", 500, 1400)
    _write_image(folder / "transparent.png", 800, 500, alpha=True)
    (folder / "broken.png").write_bytes(b"not a png")
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=48), tmp_path)
    page.resize(1050, 700)
    page._right_panel.show()
    page._preview_card.show()
    page._information_card.show()
    page.show()
    page.refresh()
    app.processEvents()
    page._preview_view.resize(420, 280)
    return page, folder


def _item_for(page: ImagesPage, name: str):
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        path = item.data(Qt.UserRole)
        if path and Path(path).name == name:
            return item
    raise AssertionError(f"Missing list item: {name}")


def test_preview_uses_source_image_and_fits_without_upscaling(tmp_path: Path):
    page, _folder = _make_page(tmp_path)
    page._show_image(_item_for(page, "large.png"))
    assert page._preview_view._source.size().width() == 1600
    assert page._preview_view._source.size().height() == 900
    assert page._preview_view.scale_factor < 1.0
    shown = page._preview_label.pixmap()
    assert shown is not None and not shown.isNull()
    assert abs((shown.width() / shown.height()) - (1600 / 900)) < 0.02

    page._show_image(_item_for(page, "small.png"))
    assert page._preview_view.scale_factor == 1.0
    assert page._preview_label.pixmap().size().width() == 48


def test_wheel_zoom_is_bounded_scrollable_and_fit_resets(tmp_path: Path):
    app = _ensure_app()
    page, _folder = _make_page(tmp_path)
    page._show_image(_item_for(page, "large.png"))
    view = page._preview_view
    fit_scale = view.scale_factor

    wheel_up = QWheelEvent(
        QPointF(60, 60), QPointF(60, 60), QPoint(), QPoint(0, 120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    app.sendEvent(view.viewport(), wheel_up)
    assert view.scale_factor > fit_scale

    wheel_down = QWheelEvent(
        QPointF(60, 60), QPointF(60, 60), QPoint(), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
    )
    app.sendEvent(view.viewport(), wheel_down)
    assert view.scale_factor == pytest.approx(fit_scale)

    view.zoom_by_steps(100)
    assert view.scale_factor == PreviewImageView.MAX_SCALE
    assert view.horizontalScrollBar().maximum() > 0
    assert view.verticalScrollBar().maximum() > 0

    view.zoom_by_steps(-100)
    assert view.scale_factor == fit_scale
    view.zoom_by_steps(8)
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().maximum())
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    page._preview_view.fit_to_preview()
    assert view.scale_factor == view._fit_scale
    assert view.horizontalScrollBar().value() == 0
    assert view.verticalScrollBar().value() == 0
    assert not hasattr(page, "_preview_fit_btn")


def test_switch_resets_zoom_and_handles_transparent_broken_deleted(tmp_path: Path):
    page, folder = _make_page(tmp_path)
    page._show_image(_item_for(page, "large.png"))
    page._preview_view.zoom_by_steps(8)
    assert page._preview_view.scale_factor > page._preview_view._fit_scale

    page._show_image(_item_for(page, "portrait.png"))
    assert page._preview_view.scale_factor == page._preview_view._fit_scale
    assert page._preview_view.horizontalScrollBar().value() == 0
    assert page._preview_view.verticalScrollBar().value() == 0

    page._show_image(_item_for(page, "transparent.png"))
    assert page._preview_view._source.hasAlphaChannel()

    page._show_image(_item_for(page, "broken.png"))
    assert not page._preview_view.has_image()
    assert page._preview_label.text() == "Failed to load image"

    deleted_item = _item_for(page, "small.png")
    (folder / "small.png").unlink()
    page._show_image(deleted_item)
    assert not page._preview_view.has_image()


def test_preview_open_signal_keeps_existing_open_path(tmp_path: Path, monkeypatch):
    page, folder = _make_page(tmp_path)
    item = _item_for(page, "large.png")
    page._list_widget.setCurrentItem(item)
    item.setSelected(True)
    page._show_image(item)
    opened: list[Path] = []
    previewed: list[Path] = []
    monkeypatch.setattr(page, "_open_image_path", lambda path: opened.append(path))
    monkeypatch.setattr(
        page, "_open_quick_preview", lambda path, large=False: previewed.append(path)
    )

    QTest.mouseDClick(page._preview_view.viewport(), Qt.LeftButton)
    assert opened == [folder / "large.png"]
    assert previewed == []

    page._on_item_double_clicked(item)
    assert opened == [folder / "large.png", folder / "large.png"]
    assert previewed == []


def test_information_and_tags_cards_share_layout_and_show_required_values(
    tmp_path: Path
):
    page, folder = _make_page(tmp_path)
    item = _item_for(page, "large.png")
    page._show_image(item)
    _ensure_app().processEvents()

    assert page._file_info_label.toolTip() == "large.png"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", page._modified_info_label.toolTip())
    assert page._folder_info_label.toolTip() == str(folder)
    assert page._information_card.parentWidget() is page._preview_card
    assert page._information_card.objectName() == "previewInfoSection"
    assert page._tags_card.objectName() == "previewCard"
    assert page._preview_card.objectName() == "previewCard"
    assert abs(page._tag_combo.height() - page._tag_assign_btn.height()) <= 2
