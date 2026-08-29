"""Favorite folder rows: whole-row click, drag-select name without opening."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.main_window import PAGE_IMAGES, MainWindow
from app.ui.side_nav import NavFavoriteRow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _window(favorite: Path) -> MainWindow:
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    return MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "selected_folder": str(favorite),
            "current_folder": "Default",
            "save_folder": "Default",
            "favorite_folders": [str(favorite)],
            "window_width": 1100,
            "window_height": 700,
            "window_title": "Capixe",
        }
    )


def test_favorite_row_uses_pointer_cursor_on_name():
    app = _app()
    folder = Path(tempfile.mkdtemp()) / "Alpha"
    folder.mkdir()
    window = _window(folder)
    window.show()
    app.processEvents()
    row = window._side_nav._folder_buttons[0]
    assert isinstance(row, NavFavoriteRow)
    assert row.cursor().shape() == Qt.PointingHandCursor
    assert row._name.cursor().shape() == Qt.PointingHandCursor
    window.close()


def test_favorite_row_click_on_name_opens_folder():
    app = _app()
    folder = Path(tempfile.mkdtemp()) / "ProjectA"
    folder.mkdir()
    window = _window(folder)
    window.show()
    app.processEvents()
    opened: list[str] = []
    window._side_nav.folder_opened.connect(opened.append)
    row = window._side_nav._folder_buttons[0]
    QTest.mouseClick(row._name, Qt.LeftButton)
    app.processEvents()
    assert opened == [str(folder)]
    window.close()


def test_favorite_row_click_on_padding_opens_folder():
    app = _app()
    folder = Path(tempfile.mkdtemp()) / "ProjectB"
    folder.mkdir()
    window = _window(folder)
    window.show()
    app.processEvents()
    opened: list[str] = []
    window._side_nav.folder_opened.connect(opened.append)
    row = window._side_nav._folder_buttons[0]
    QTest.mouseClick(row, Qt.LeftButton, pos=QPoint(2, 14))
    app.processEvents()
    assert opened == [str(folder)]
    window.close()


def test_favorite_row_drag_selects_text_without_opening():
    app = _app()
    folder = Path(tempfile.mkdtemp()) / "SelectableFolder"
    folder.mkdir()
    window = _window(folder)
    window.show()
    app.processEvents()
    opened: list[str] = []
    window._side_nav.folder_opened.connect(opened.append)
    row = window._side_nav._folder_buttons[0]
    name = row._name
    QTest.mousePress(name, Qt.LeftButton, pos=QPoint(2, 8))
    QTest.mouseMove(name, QPoint(80, 8))
    QTest.mouseRelease(name, Qt.LeftButton, pos=QPoint(80, 8))
    app.processEvents()
    assert opened == []
    assert name.selectedText()
    QTest.mouseClick(name, Qt.LeftButton, pos=QPoint(12, 8))
    app.processEvents()
    assert opened == []
    window.close()


def test_favorite_rows_can_be_reordered():
    app = _app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    first = root / "Alpha"
    second = root / "Beta"
    first.mkdir()
    second.mkdir()
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "selected_folder": str(first),
            "current_folder": "Default",
            "save_folder": "Default",
            "favorite_folders": [str(first), str(second)],
            "window_width": 1100,
            "window_height": 700,
            "window_title": "Capixe",
        }
    )
    window.show()
    app.processEvents()
    nav = window._side_nav
    received: list[list[str]] = []
    nav.favorites_reordered.connect(received.append)
    nav.reorder_favorites(str(first), str(second), True)
    app.processEvents()
    assert [path.name for path in nav._favorite_paths] == ["Beta", "Alpha"]
    assert [row.folder_path() for row in nav._folder_buttons] == [
        str(second),
        str(first),
    ]
    assert received == [[str(second), str(first)]]
    assert window._config["favorite_folders"] == [str(second), str(first)]
    window.close()
