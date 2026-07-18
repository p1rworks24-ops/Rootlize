"""Information architecture: nav rename, AI placeholder, page subtitles."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from app.i18n import t
from app.ui.main_window import (
    PAGE_HOME,
    PAGE_IMAGES,
    PAGE_ORGANIZE,
    PAGE_SETTINGS,
    PAGE_TAGS,
    MainWindow,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_window() -> MainWindow:
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Default",
        "save_folder": "Default",
        "window_width": 1000,
        "window_height": 700,
        "window_title": "Screenshot Manager",
    }
    return MainWindow(config)


def _find_page_subtitle(page) -> str | None:
    for label in page.findChildren(QLabel):
        if label.objectName() == "pageSubtitle":
            return label.text()
    return None


def test_nav_order_organize_and_ai_placeholder():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    assert PAGE_ORGANIZE in nav._nav_buttons
    assert nav._nav_buttons[PAGE_ORGANIZE].property("navLabel") == t("nav.organize")
    assert len(nav._placeholder_buttons) == 1
    ai = nav._placeholder_buttons[0]
    assert ai.objectName() == "navButtonPlaceholder"
    assert ai.property("navLabel") == t("nav.ai")
    assert ai.toolTip() == t("nav.ai_tooltip")
    assert not ai.isCheckable()

    # AI click must not change page
    before = window._stack.currentIndex()
    ai.click()
    app.processEvents()
    assert window._stack.currentIndex() == before


def test_page_subtitles_present():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    assert _find_page_subtitle(window._home_page) == t("home.subtitle")
    assert _find_page_subtitle(window._images_page) == t("images.subtitle")
    assert _find_page_subtitle(window._work_page) == t("work.subtitle")
    assert _find_page_subtitle(window._tags_page) == t("tags.subtitle")
    assert _find_page_subtitle(window._settings_page) == t("settings.subtitle")


def test_organize_page_navigable_and_selectable():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    window._show_page(PAGE_ORGANIZE)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ORGANIZE
    assert window._side_nav._nav_buttons[PAGE_ORGANIZE].isChecked()
    assert not window._side_nav._placeholder_buttons[0].isChecked()

    for page_id in (PAGE_HOME, PAGE_IMAGES, PAGE_TAGS, PAGE_SETTINGS):
        window._show_page(page_id)
        app.processEvents()
        assert window._stack.currentIndex() == page_id
        assert window._side_nav._nav_buttons[page_id].isChecked()
        assert not window._side_nav._placeholder_buttons[0].isChecked()
