"""Information architecture: nav rename, AI placeholder, page subtitles."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.i18n import t
from app.ui.main_window import (
    PAGE_ABOUT,
    PAGE_HOME,
    PAGE_IMAGES,
    PAGE_ORGANIZE,
    PAGE_SETTINGS,
    PAGE_TAGS,
    MANAGEMENT_PAGES_ENABLED,
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
        "window_title": "Capixe",
    }
    return MainWindow(config)


def _find_page_subtitle(page) -> str | None:
    for label in page.findChildren(QLabel):
        if label.objectName() == "pageSubtitle":
            return label.text()
    return None


def test_retired_management_pages_are_hidden_from_navigation():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    assert not MANAGEMENT_PAGES_ENABLED
    assert PAGE_ORGANIZE not in nav._nav_buttons
    assert PAGE_TAGS not in nav._nav_buttons
    home_actions = {
        button.text() for button in window._home_page.findChildren(QPushButton)
    }
    assert t("nav.organize") not in home_actions
    assert t("nav.tags") not in home_actions
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


def test_navigation_footer_shows_prototype_user_and_account_info():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    user = nav._prototype_user_button
    assert user.objectName() == "sidebarPrototypeUser"
    assert user.text() == "Prototype"
    assert user.toolTip() == "Test user"
    assert not user.icon().isNull()
    assert user.geometry().top() > max(
        button.geometry().bottom() for button in nav._nav_buttons.values()
    )

    user.click()
    app.processEvents()
    assert [action.text() for action in nav._user_menu.actions()] == [
        "Prototype",
        "Capixe@example.com",
    ]
    nav._user_menu.close()
    window.close()


def test_retired_management_page_requests_return_to_images():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    window._show_page(PAGE_ORGANIZE)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES
    assert window._side_nav._nav_buttons[PAGE_IMAGES].isChecked()
    assert not window._side_nav._placeholder_buttons[0].isChecked()

    window._show_page(PAGE_TAGS)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES

    for page_id in (PAGE_HOME, PAGE_IMAGES, PAGE_SETTINGS, PAGE_ABOUT):
        window._show_page(page_id)
        app.processEvents()
        assert window._stack.currentIndex() == page_id
        assert window._side_nav._nav_buttons[page_id].isChecked()
        assert not window._side_nav._placeholder_buttons[0].isChecked()


def test_navigation_density_starts_collapsed_and_leave_collapses_again():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    nav.set_responsive_compact(False)
    assert nav.width() == nav.COLLAPSED_WIDTH
    assert not nav._expanded

    nav._animate_to(True)
    nav._anim.setCurrentTime(nav.ANIM_MS)
    assert nav.width() == nav.EXPANDED_WIDTH
    assert nav._expanded

    nav._animate_to(False)
    nav._anim.setCurrentTime(nav.ANIM_MS)
    assert nav.width() == nav.COLLAPSED_WIDTH
    assert not nav._expanded
