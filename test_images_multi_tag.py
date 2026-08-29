"""Images Preview tag actions only affect the active image."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_page() -> tuple[ImagesPage, Path, list[Path]]:
    root = Path(tempfile.mkdtemp())
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    paths: list[Path] = []
    for name in ("a.png", "b.png", "c.png"):
        png = folder / name
        img = QImage(16, 16, QImage.Format_RGB32)
        img.fill(Qt.red)
        img.save(str(png))
        paths.append(png)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "images_folder_tree_expanded": True,
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(), root)
    page._load_images()
    return page, root, paths


def test_assign_existing_tag_only_applies_to_preview_image():
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    app.processEvents()

    page._metadata_service.ensure_global_tag(root, "shared")
    page.reload_tag_choices()

    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)
    app.processEvents()
    assert len(page._selected_image_paths()) == 3
    active_item = next(
        page._list_widget.item(i)
        for i in range(page._list_widget.count())
        if page._list_widget.item(i).data(Qt.UserRole) == str(paths[1].resolve())
    )
    page._list_widget.setCurrentItem(active_item)
    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)

    idx = page._tag_combo.findData("shared")
    if idx < 0:
        idx = next(
            i
            for i in range(page._tag_combo.count())
            if "shared" in page._tag_combo.itemText(i).casefold()
        )
    page._tag_combo.setCurrentIndex(idx)
    page._on_assign_existing_tag()
    app.processEvents()

    assert "shared" in page._metadata_service.get_image_tags(paths[1].parent, paths[1].name)
    assert "shared" not in page._metadata_service.get_image_tags(paths[0].parent, paths[0].name)
    assert "shared" not in page._metadata_service.get_image_tags(paths[2].parent, paths[2].name)


def test_current_tag_chip_removes_only_its_tag_from_preview_image(monkeypatch):
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    app.processEvents()

    page._metadata_service.ensure_global_tag(root, "dropme")
    page._metadata_service.ensure_global_tag(root, "second")
    for path in paths:
        page._metadata_service.add_image_tag(path.parent, path.name, "dropme")
    page._metadata_service.add_image_tag(paths[1].parent, paths[1].name, "second")

    page._load_images()
    app.processEvents()
    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)
    app.processEvents()

    active_item = next(
        page._list_widget.item(i)
        for i in range(page._list_widget.count())
        if page._list_widget.item(i).data(Qt.UserRole) == str(paths[1].resolve())
    )
    page._list_widget.setCurrentItem(active_item)
    for i in range(page._list_widget.count()):
        item = page._list_widget.item(i)
        if item and item.data(Qt.UserRole):
            item.setSelected(True)
    monkeypatch.setattr(page, "_confirm_tag_removal_dialog", lambda _tag: False)
    page._confirm_remove_tag(paths[1], "dropme")
    assert all(
        "dropme" in page._metadata_service.get_image_tags(path.parent, path.name)
        for path in paths
    )

    monkeypatch.setattr(page, "_confirm_tag_removal_dialog", lambda _tag: True)
    page._confirm_remove_tag(paths[1], "dropme")
    app.processEvents()

    assert page._metadata_service.get_image_tags(paths[1].parent, paths[1].name) == ["second"]
    assert "dropme" in page._metadata_service.get_image_tags(paths[0].parent, paths[0].name)
    assert "dropme" in page._metadata_service.get_image_tags(paths[2].parent, paths[2].name)
    assert "dropme" in page._metadata_service.load_global_tags(root, force_reload=True)
    assert "second" in page._metadata_service.load_global_tags(root, force_reload=True)
    remove_buttons = [
        page._tags_layout.itemAt(index).widget().findChild(
            QPushButton, "currentTagRemoveButton"
        )
        for index in range(page._tags_layout.count())
        if page._tags_layout.itemAt(index).widget() is not None
    ]
    remove_buttons = [button for button in remove_buttons if button is not None]
    assert len(remove_buttons) == 1
    chip = page._tags_layout.itemAt(0).widget()
    label = chip.findChild(QLabel, "currentTagChipLabel")
    assert label is not None
    assert abs(label.geometry().center().y() - remove_buttons[0].geometry().center().y()) <= 1


def test_tag_picker_is_taller_and_each_tag_has_delete_button():
    app = _ensure_app()
    page, root, _paths = _make_page()
    for index in range(12):
        page._metadata_service.ensure_global_tag(root, f"tag-{index}")
    page.reload_tag_choices()
    page.show()
    app.processEvents()
    first_image = next(
        page._list_widget.item(i)
        for i in range(page._list_widget.count())
        if page._list_widget.item(i).data(Qt.UserRole)
    )
    page._list_widget.setCurrentItem(first_image)
    app.processEvents()

    page._tag_combo.showPopup()
    app.processEvents()

    assert page._tag_combo._popup_list.height() >= 10 * 28
    delete_buttons = page._tag_combo._popup_list.findChildren(
        QPushButton, "tagPickerDeleteButton"
    )
    assert len(delete_buttons) == 12
    page._tag_combo.hidePopup()


def test_chip_remove_and_global_delete_have_distinct_scope(monkeypatch):
    app = _ensure_app()
    page, root, paths = _make_page()
    page._metadata_service.ensure_global_tag(root, "shared")
    for path in paths:
        page._metadata_service.add_image_tag(path.parent, path.name, "shared")
    page._load_images()
    page.show()
    app.processEvents()

    item = next(
        page._list_widget.item(i)
        for i in range(page._list_widget.count())
        if page._list_widget.item(i).data(Qt.UserRole) == str(paths[0].resolve())
    )
    page._list_widget.setCurrentItem(item)
    monkeypatch.setattr(page, "_confirm_tag_removal_dialog", lambda _tag: True)
    page._confirm_remove_tag(paths[0], "shared")
    app.processEvents()
    assert "shared" not in page._metadata_service.get_image_tags(paths[0].parent, paths[0].name)
    assert "shared" in page._metadata_service.get_image_tags(paths[1].parent, paths[1].name)

    assert page._tag_usage_count_in_selected_folder("shared") == 2
    monkeypatch.setattr(
        page, "_confirm_global_tag_deletion_dialog", lambda _tag, count: count == 2
    )
    page._confirm_delete_global_tag("shared")
    app.processEvents()
    assert "shared" not in page._metadata_service.load_global_tags(root, force_reload=True)
    assert all(
        "shared" not in page._metadata_service.get_image_tags(path.parent, path.name)
        for path in paths
    )


def test_tags_button_lives_between_view_and_show_tags_and_opens_inline_popup():
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    app.processEvents()

    selected = {paths[0].resolve(), paths[2].resolve()}
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        if item and item.data(Qt.UserRole):
            item.setSelected(Path(item.data(Qt.UserRole)).resolve() in selected)
    app.processEvents()

    assert page._actions_tags_btn.isEnabled()
    assert not hasattr(page, "_actions_move_btn")
    tools = page._header_tools.layout()
    assert tools.indexOf(page._view_menu_btn) == -1
    assert tools.indexOf(page._actions_tags_btn) < tools.indexOf(page._layout_field)
    assert page._show_tags_checkbox.parentWidget() is page._tags_display_row
    assert not page._actions_tags_btn.icon().isNull()
    assert not hasattr(page, "_actions_row")

    page._metadata_service.ensure_global_tag(root, "batch")
    page._add_tag_to_paths(page._selected_image_paths(), "batch")
    assert all(
        "batch" in page._metadata_service.get_image_tags(path.parent, path.name)
        for path in (paths[0], paths[2])
    )
    assert "batch" not in page._metadata_service.get_image_tags(
        paths[1].parent, paths[1].name
    )

    page.resize(1200, 800)
    app.processEvents()
    list_top_before = page._list_panel.mapToGlobal(
        page._list_panel.rect().topLeft()
    ).y()
    page._show_tags_popup()
    app.processEvents()
    assert page._tags_card.isVisible()
    assert page._show_tags_checkbox.isVisible()
    assert page._tags_display_row.isVisible()
    assert page._tags_card.isWindow()
    assert bool(page._tags_card.windowFlags() & Qt.Tool)
    assert page._tags_close_btn.isVisible()
    assert page._tags_close_btn.isEnabled()
    list_top = page._list_panel.mapToGlobal(page._list_panel.rect().topLeft()).y()
    assert list_top == list_top_before
    popup = page._tags_card.frameGeometry()
    content_global = page._content.rect()
    content_global.moveTopLeft(page._content.mapToGlobal(QPoint(0, 0)))
    assert content_global.intersects(popup)
    origin = page._tags_card.pos()
    page._tags_user_placed = True
    page._tags_card.move(max(8, origin.x() - 48), max(8, origin.y() - 28))
    page._sync_tags_popup_geometry()
    assert page._tags_card.isVisible()
    assert page._tags_user_placed is True

    page._tags_close_btn.click()
    app.processEvents()
    assert page._tags_card.isHidden()
    page._show_tags_popup()
    app.processEvents()
    page._on_escape()
    app.processEvents()
    assert page._tags_card.isHidden()


def test_tag_management_is_available_without_image_selection_but_add_is_not():
    app = _ensure_app()
    page, root, paths = _make_page()
    page.show()
    page._list_widget.clearSelection()
    page._list_widget.setCurrentItem(None)
    app.processEvents()

    assert page._actions_tags_btn.isEnabled()
    page._actions_tags_btn.click()
    QTest.qWait(260)
    assert page._tags_card.isVisible()
    assert page._tag_combo.isEnabled()
    assert not page._tag_assign_btn.isEnabled()

    page._create_and_assign_tag_name("global-only")
    assert "global-only" in page._metadata_service.load_global_tags(
        root, force_reload=True
    )
    assert all(
        "global-only" not in page._metadata_service.get_image_tags(
            path.parent, path.name
        )
        for path in paths
    )


def test_filesystem_sync_loads_an_externally_added_image():
    app = _ensure_app()
    page, _root, paths = _make_page()
    page.show()
    app.processEvents()

    added = paths[0].parent / "external.png"
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(added))

    page._on_fs_change_debounced()
    app.processEvents()
    listed = {
        Path(page._list_widget.item(index).data(Qt.UserRole)).resolve()
        for index in range(page._list_widget.count())
        if page._list_widget.item(index).data(Qt.UserRole)
    }
    assert added.resolve() in listed


def test_move_selected_images_to_chosen_folder_preserves_unselected_image():
    app = _ensure_app()
    page, root, paths = _make_page()
    destination = root / "Moved"
    page.show()
    app.processEvents()

    selected = {paths[0].resolve(), paths[2].resolve()}
    for index in range(page._list_widget.count()):
        item = page._list_widget.item(index)
        if item and item.data(Qt.UserRole):
            item.setSelected(Path(item.data(Qt.UserRole)).resolve() in selected)
    page._move_selected_images_to(destination)
    app.processEvents()

    assert (destination / "a.png").exists()
    assert (destination / "c.png").exists()
    assert paths[1].exists()
    assert not paths[0].exists()
    assert not paths[2].exists()
