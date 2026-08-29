"""Empty gallery background: context menu New Folder under the current folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMenu

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import ITEM_KIND_FOLDER, ITEM_KIND_ROLE, ROLE_CAPTION_NAME
from app.ui.image_list_menu import populate_image_list_context_menu
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path) -> None:
    image = QImage(12, 12, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _page(tmp_path: Path, selected: Path | None = None) -> ImagesPage:
    _app()
    config = {
        "screenshot_dir": str(tmp_path / "legacy-root"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "favorite_folders": [],
        "recent_folders": [],
    }
    config["selected_folder"] = "" if selected is None else str(selected)
    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=48), tmp_path)
    page.refresh()
    return page


def _layout(page: ImagesPage) -> None:
    app = _app()
    page.resize(1100, 720)
    page.show()
    app.processEvents()


def _menu_texts(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions() if action.text()]


def _empty_widget_pos(page: ImagesPage):
    viewport = page._list_widget.viewport()
    pos = viewport.rect().adjusted(8, 8, -12, -12).bottomRight()
    assert page._list_widget._selectable_item_at(pos) is None
    return page._list_widget.viewport().mapTo(page._list_widget, pos)


def _image_card_widget_pos(page: ImagesPage):
    item = gallery_image_items(page._list_widget)[0]
    center = page._list_widget._card_rect(item).center()
    assert page._list_widget._selectable_item_at(center) is item
    return page._list_widget.viewport().mapTo(page._list_widget, center)


def _folder_names(page: ImagesPage) -> list[str]:
    names = []
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        if item is not None and item.data(ITEM_KIND_ROLE) == ITEM_KIND_FOLDER:
            names.append(str(item.data(ROLE_CAPTION_NAME) or ""))
    return names


def test_empty_space_context_menu_has_new_folder(tmp_path: Path):
    selected = tmp_path / "Pictures"
    selected.mkdir()
    _png(selected / "shot.png")
    page = _page(tmp_path, selected)
    _layout(page)

    assert page._gallery_context_kind(_empty_widget_pos(page)) == "empty"
    menu = page._empty_gallery_menu()
    texts = _menu_texts(menu)
    assert t("images.folder.new_folder") in texts
    assert t("images.open") not in texts
    action = next(a for a in menu.actions() if a.text() == t("images.folder.new_folder"))
    assert action.isEnabled() is True
    assert not action.icon().isNull()


def test_list_empty_space_context_menu_has_new_folder(tmp_path: Path):
    selected = tmp_path / "Pictures"
    selected.mkdir()
    _png(selected / "shot.png")
    page = _page(tmp_path, selected)
    _layout(page)
    page._set_gallery_layout("list")
    _app().processEvents()

    assert page._gallery_context_kind(_empty_widget_pos(page)) == "empty"
    assert t("images.folder.new_folder") in _menu_texts(page._empty_gallery_menu())


def test_image_card_context_menu_is_not_new_folder_menu(tmp_path: Path):
    selected = tmp_path / "Pictures"
    selected.mkdir()
    _png(selected / "shot.png")
    page = _page(tmp_path, selected)
    _layout(page)

    assert page._gallery_context_kind(_image_card_widget_pos(page)) == "image"
    menu = QMenu(page)
    populate_image_list_context_menu(
        menu,
        page,
        thumbnail_mode=page._thumbnail_mode,
        selected_count=1,
        has_clipboard=False,
        on_set_thumbnail_mode=None,
        on_open=lambda: None,
        on_copy=lambda: None,
        on_cut=lambda: None,
        on_paste=lambda: None,
        on_rename=lambda: None,
        on_delete=lambda: None,
        on_explorer=lambda: None,
    )
    texts = _menu_texts(menu)
    assert t("images.open") in texts
    assert t("images.folder.new_folder") not in texts


def test_new_folder_disabled_when_folder_unselected(tmp_path: Path):
    page = _page(tmp_path, None)
    assert page._can_create_child_folder() is False
    menu = page._empty_gallery_menu()
    action = next(a for a in menu.actions() if a.text() == t("images.folder.new_folder"))
    assert action.isEnabled() is False


def test_create_child_folder_under_current_folder(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.ui.pages.images_page.QMessageBox.warning", lambda *args, **kwargs: None
    )
    selected = tmp_path / "Screenshots"
    selected.mkdir()
    _png(selected / "shot.png")
    page = _page(tmp_path, selected)
    items = gallery_image_items(page._list_widget)
    items[0].setSelected(True)
    selected_path = Path(items[0].data(Qt.UserRole))

    created = page._create_child_folder_named("Dogs")
    assert created == selected / "Dogs"
    assert created.is_dir()
    assert page._config["selected_folder"] == str(selected.resolve())
    assert "Dogs" in _folder_names(page)
    assert Path(page._get_selected_path()) == selected_path.resolve()


def test_create_child_folder_rejects_duplicate_and_invalid(tmp_path: Path, monkeypatch):
    warnings: list[str] = []

    def fake_warning(_parent, _title, text):
        warnings.append(text)

    monkeypatch.setattr("app.ui.pages.images_page.QMessageBox.warning", fake_warning)
    selected = tmp_path / "Screenshots"
    selected.mkdir()
    page = _page(tmp_path, selected)

    assert page._create_child_folder_named("Dogs") is not None
    assert page._create_child_folder_named("Dogs") is None
    assert t("images.folder.exists") in warnings
    assert page._create_child_folder_named("bad:name") is None
    assert t("images.folder.name_invalid") in warnings
    assert page._create_child_folder_named("   ") is None
    assert t("images.folder.name_required") in warnings
    assert list((selected / "Dogs").iterdir()) == []


def test_create_child_folder_does_not_reset_ask_ai_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.ui.pages.images_page.QMessageBox.warning", lambda *args, **kwargs: None
    )
    selected = tmp_path / "Screenshots"
    selected.mkdir()
    page = _page(tmp_path, selected)
    page._ask_ai_grid_active = True
    page._ask_ai_grid_query = "a dog"
    page._ask_ai_grid_paths = []

    created = page._create_child_folder_named("Dogs")
    assert created == selected / "Dogs"
    assert page._ask_ai_grid_active is True
    assert page._ask_ai_grid_query == "a dog"
    assert page._config["selected_folder"] == str(selected.resolve())
