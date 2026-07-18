"""Organize page: Image List + Operations panel structure."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFrame, QStackedWidget

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.pages.work_page import OP_RENAME, OP_TAGS, WorkPage
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
    assert page._op_stack.count() == 2
    assert OP_TAGS in page._operations
    assert OP_RENAME in page._operations
    assert t("work.operations") == "Operations"
    assert t("work.selected_count", count=0) == "0 Images"


def test_operation_switch_only_changes_stack():
    _ensure_app()
    page = _make_page()
    assert isinstance(page._op_stack, QStackedWidget)
    page._select_operation(OP_TAGS)
    assert page._op_stack.currentIndex() == page._operations[OP_TAGS]
    page._select_operation(OP_RENAME)
    assert page._op_stack.currentIndex() == page._operations[OP_RENAME]
    page._select_operation(OP_TAGS)
    assert page._op_stack.currentIndex() == page._operations[OP_TAGS]


def test_selection_count_updates():
    _ensure_app()
    page = _make_page()
    page._select_all()
    assert page._selected_count_label.text() == t("work.selected_count", count=1)
    page._clear_selection()
    assert page._selected_count_label.text() == t("work.selected_count", count=0)
