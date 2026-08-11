"""Organize page: Image List + Operations hub/detail card."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFrame, QStackedWidget

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.pages.work_page import OP_RENAME, OP_TAGS, WorkPage, _OPS_DETAIL
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_page() -> WorkPage:
    root = Path(tempfile.mkdtemp())
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    # Minimal valid 1x1 PNG
    (folder / "a.png").write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
            "7753de0000000c49444154789c63000100000500010d0a2db400000000"
            "49454e44ae426082"
        )
    )
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
    }
    page = WorkPage(config, MetadataService(), ThumbnailCache(), root)
    page.refresh()
    return page


def _panel(page: WorkPage, name: str) -> QFrame:
    for frame in page.findChildren(QFrame):
        if frame.objectName() == name:
            return frame
    raise AssertionError(f"missing panel {name}")


def test_organize_has_list_and_ops():
    _ensure_app()
    page = _make_page()
    _panel(page, "organizeListPanel")
    _panel(page, "organizeOpsPanel")
    assert page._list.count() >= 1
    assert page._op_stack.count() == 3
    assert OP_TAGS in page._operations
    assert OP_RENAME in page._operations
    assert t("work.operations") == "Operations"
    assert t("work.op_tags") == "Batch Tags"
    assert t("work.op_rename") == "Batch Rename"
    assert t("work.selected_count", count=0) == "0 Images"
    # No operation detail is shown until an action is chosen.
    assert page._ops_nav_stack.currentIndex() != _OPS_DETAIL
    assert page._batch_action_combo.currentData() is None


def test_organize_header_selected_folder_then_selected():
    app = _ensure_app()
    page = _make_page()
    page.resize(900, 600)
    page.show()
    app.processEvents()
    assert hasattr(page, "_root_folder_value")
    assert page._root_folder_value.text()
    root_chip = page._root_folder_value.parentWidget()
    sel_box = page._selected_count_label.parentWidget()
    assert root_chip is not None and sel_box is not None
    # Left → right: Root Folder chip, Folder chip, Selected banner
    assert root_chip.mapTo(page, root_chip.rect().topLeft()).y() < sel_box.mapTo(
        page, sel_box.rect().topLeft()
    ).y()
    assert page._folder_combo.parentWidget().isHidden()
    assert page._choose_folder_btn.text() == "Choose Folder"
    assert page._choose_folder_btn.icon().isNull() is False
    assert root_chip.objectName() == "folderSelectorBar"
    assert t("work.root_folder_label") == "Folder:"


def test_organize_top_controls_align_with_image_column():
    app = _ensure_app()
    page = _make_page()
    page.resize(1200, 760)
    page.show()
    app.processEvents()
    page._sync_top_control_widths()
    target = page._list_column.width()
    assert page._folder_bar.maximumWidth() == target
    assert page._search_row.maximumWidth() == target
    assert page._filter_secondary.maximumWidth() == target


def test_operation_opens_detail_inside_ops_card():
    _ensure_app()
    page = _make_page()
    assert isinstance(page._ops_nav_stack, QStackedWidget)
    assert isinstance(page._op_stack, QStackedWidget)
    page._open_operation(OP_TAGS)
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL
    assert page._op_stack.currentIndex() == page._operations[OP_TAGS]
    assert page._ops_detail_title.text() == t("work.op_tags")
    page._open_operation(OP_RENAME)
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL
    assert page._op_stack.currentIndex() == page._operations[OP_RENAME]
    assert page._ops_detail_title.text() == t("work.op_rename")


def test_operations_back_returns_to_hub():
    _ensure_app()
    page = _make_page()
    page._open_operation(OP_TAGS)
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL
    page._show_ops_hub()
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL
    assert page._batch_action_combo.currentData() == OP_TAGS


def test_selection_count_updates():
    _ensure_app()
    page = _make_page()
    page._select_all()
    assert page._selected_count_label.text() == t(
        "work.results_selected", results=1, selected=1
    )
    page._clear_selection()
    assert page._selected_count_label.text() == t(
        "work.results_selected", results=1, selected=0
    )


def test_organize_ops_panel_is_compact():
    from PySide6.QtWidgets import QLabel, QScrollArea

    _ensure_app()
    page = _make_page()
    ops = _panel(page, "organizeOpsPanel")
    assert ops.minimumWidth() <= 260
    scroll = page.findChild(QScrollArea, "organizeOpsScroll")
    assert scroll is not None
    assert page._caption_delegate._show_selection_badge is True
    tags_item = page._op_buttons[OP_TAGS]
    assert tags_item.property("opId") == OP_TAGS
    title = tags_item.findChild(QLabel, "operationMenuTitle")
    assert title is not None
    assert title.text() == t("work.op_tags")


def test_operation_menu_icon_aligns_with_title():
    """Icon should share the title row (not AlignTop against title+desc)."""
    from PySide6.QtWidgets import QLabel

    _ensure_app()
    page = _make_page()
    page.resize(1000, 700)
    page.show()
    page._apply_ops_density(force=True)
    item = page._op_buttons[OP_TAGS]
    icon = item.findChild(QLabel, "operationMenuIcon")
    title = item.findChild(QLabel, "operationMenuTitle")
    assert icon is not None and title is not None
    icon_mid = icon.geometry().center().y()
    title_mid = title.geometry().center().y()
    assert abs(icon_mid - title_mid) <= 5


def test_operations_title_is_bold_and_spelled_correctly():
    from PySide6.QtGui import QFont

    _ensure_app()
    page = _make_page()
    assert page._ops_title.text() == "Operations"
    assert "Operetions" not in page._ops_title.text()
    assert page._ops_title.font().weight() >= QFont.Weight.DemiBold
    from app.ui.organize_ops import OPS_PAD_BOTTOM, OPS_PAD_TOP, OPS_PAD_X

    margins = page._ops_panel_layout.contentsMargins()
    assert margins.left() == OPS_PAD_X
    assert margins.right() == OPS_PAD_X
    assert margins.top() == OPS_PAD_TOP
    assert margins.bottom() == OPS_PAD_BOTTOM
    assert OPS_PAD_X >= 24
    assert OPS_PAD_TOP >= 24


def test_operation_menu_card_click_anywhere_opens_once():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel

    app = _ensure_app()
    page = _make_page()
    page.resize(1000, 700)
    page.show()
    app.processEvents()

    item = page._op_buttons[OP_TAGS]
    assert item.testAttribute(Qt.WA_TransparentForMouseEvents) is False
    title = item.findChild(QLabel, "operationMenuTitle")
    desc = item.findChild(QLabel, "operationMenuDesc")
    assert title is not None and desc is not None
    assert title.testAttribute(Qt.WA_TransparentForMouseEvents) is True
    assert desc.testAttribute(Qt.WA_TransparentForMouseEvents) is True
    assert item.cursor().shape() == Qt.PointingHandCursor

    opens: list[str] = []
    item.clicked.connect(opens.append)

    # Click padding / background area of the card
    QTest.mouseClick(item, Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
    app.processEvents()
    assert opens == [OP_TAGS]

    page._show_ops_hub()
    opens.clear()
    # Click through title label position (mapped to card)
    local = title.mapTo(item, title.rect().center())
    QTest.mouseClick(item, Qt.LeftButton, Qt.NoModifier, local)
    app.processEvents()
    assert opens == [OP_TAGS]

    page._show_ops_hub()
    opens.clear()
    local = desc.mapTo(item, desc.rect().center())
    QTest.mouseClick(item, Qt.LeftButton, Qt.NoModifier, local)
    app.processEvents()
    assert opens == [OP_TAGS]
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL


def test_organize_ops_menu_selection_accent():
    _ensure_app()
    page = _make_page()
    page._open_operation(OP_TAGS)
    assert page._op_buttons[OP_TAGS].property("selected") is True
    assert page._ops_panel.property("opId") == OP_TAGS
    assert page._ops_detail_header.property("opId") == OP_TAGS
    page._open_operation(OP_RENAME)
    assert page._op_buttons[OP_RENAME].property("selected") is True
    assert page._op_buttons[OP_TAGS].property("selected") is False
    assert page._ops_panel.property("opId") == OP_RENAME
    page._show_ops_hub()
    assert page._ops_nav_stack.currentIndex() == _OPS_DETAIL
    assert page._op_buttons[OP_RENAME].property("selected") is True


def test_organize_ops_future_menu_items_present():
    _ensure_app()
    page = _make_page()
    assert "convert" in page._op_buttons
    assert "resize" in page._op_buttons
    assert "export" in page._op_buttons
    assert page._op_buttons["convert"].spec.enabled is False
    # Disabled ops do not open a detail page
    page._open_operation("convert")
    assert page._ops_nav_stack.currentIndex() != _OPS_DETAIL


def test_organize_no_nested_bulk_card():
    _ensure_app()
    page = _make_page()
    assert page._tags_settings.objectName() == "organizeOpDetailBody"
    assert page._rename_settings.objectName() == "organizeOpDetailBody"
    # Nested Bulk card chrome removed
    for frame in page.findChildren(QFrame):
        assert frame.objectName() != "organizeOpSettings"


def test_organize_ops_density_stays_compact_in_reduced_panel():
    app = _ensure_app()
    page = _make_page()
    page.resize(1000, 720)
    page.show()
    app.processEvents()
    page._ops_panel.resize(260, 300)
    page._apply_ops_density(force=True)
    assert page._ops_density in {"compact", "tight"}
    assert page._ops_hint.isVisible() is False

    page._ops_panel.resize(260, 190)
    page._apply_ops_density(force=True)
    assert page._ops_density == "tight"
    assert page._ops_hint.isVisible() is False
    # Fields shrink with density so Tags/Rename stay inside the frame
    assert page._tag_new_input.maximumHeight() <= 30


def test_organize_has_view_combo():
    _ensure_app()
    page = _make_page()
    assert hasattr(page, "_view_combo")
    assert page._view_combo.count() >= 3
    page._view_combo.setCurrentIndex(page._view_combo.findData("small"))
    assert page._thumbnail_mode == "small"


def test_bulk_tags_order_new_existing_remove():
    app = _ensure_app()
    page = _make_page()
    page.resize(900, 600)
    page.show()
    app.processEvents()
    page._open_operation(OP_TAGS)
    app.processEvents()
    assert hasattr(page, "_tag_new_input")
    assert hasattr(page, "_tag_add_combo")
    assert hasattr(page, "_tag_remove_combo")
    # Vertical order: existing-tag action, new-tag action, remove-tag action.
    assert page._tag_add_combo.parentWidget().y() < page._tag_new_input.parentWidget().y()
    assert page._tag_new_input.parentWidget().y() < page._tag_remove_combo.parentWidget().y()
    assert t("work.tag_new") == "New tag"
    assert t("work.tag_existing") == "Existing tag"


def test_bulk_create_tag_assigns_to_selection(monkeypatch):
    _ensure_app()
    page = _make_page()
    monkeypatch.setattr(
        "app.ui.pages.work_page.QMessageBox.information", lambda *a, **k: None
    )
    page._select_all()
    page._open_operation(OP_TAGS)
    page._tag_new_input.setText("batch-new")
    page._on_bulk_create_tag()
    tags = page._metadata_service.load_global_tags(page._app_root)
    assert "batch-new" in tags
    folder = page._get_folder_dir()
    meta = page._metadata_service.load_metadata(folder, force_reload=True)
    image_tags = next(iter(meta.get("images", {}).values())).get("tags", [])
    assert "batch-new" in image_tags


def test_bulk_existing_tag_add_and_remove_reuse_current_logic(monkeypatch):
    _ensure_app()
    page = _make_page()
    monkeypatch.setattr(
        "app.ui.pages.work_page.QMessageBox.information", lambda *a, **k: None
    )
    page._metadata_service.ensure_global_tag(page._app_root, "existing-tag")
    page._reload_tag_combos()
    page._select_all()

    page._tag_add_combo.setCurrentIndex(page._tag_add_combo.findData("existing-tag"))
    page._on_bulk_add_tag()
    folder = page._get_folder_dir()
    meta = page._metadata_service.load_metadata(folder, force_reload=True)
    assert "existing-tag" in next(iter(meta["images"].values()))["tags"]

    page._tag_remove_combo.setCurrentIndex(
        page._tag_remove_combo.findData("existing-tag")
    )
    page._on_bulk_remove_tag()
    meta = page._metadata_service.load_metadata(folder, force_reload=True)
    assert "existing-tag" not in next(iter(meta["images"].values()))["tags"]


def test_organize_uses_shared_page_header():
    from PySide6.QtWidgets import QLabel, QWidget

    _ensure_app()
    page = _make_page()
    header = next(
        (w for w in page.findChildren(QWidget) if w.objectName() == "pageHeader"),
        None,
    )
    assert header is not None
    titles = [
        lab.text()
        for lab in page.findChildren(QLabel)
        if lab.objectName() == "pageTitle"
    ]
    assert t("work.title") in titles
