"""Information architecture: nav rename, AI placeholder, page subtitles."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtTest import QTest

from app.i18n import t
from app.ui.design_tokens import navigation_icon, navigation_icon_size
from app.ui.icons import icon_images, icon_search_nav
from app.ui.main_window import (
    PAGE_ABOUT,
    PAGE_ACCOUNT,
    PAGE_AUTOMATION,
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
    assert nav._placeholder_buttons == []
    assert PAGE_IMAGES in nav._nav_buttons
    assert PAGE_AUTOMATION in nav._nav_buttons
    assert nav._nav_buttons[PAGE_IMAGES].property("navLabel") == t("nav.images")
    assert nav._nav_buttons[PAGE_AUTOMATION].property("navLabel") == t("nav.automation")
    icon_size = navigation_icon_size()
    images_icon = nav._nav_buttons[PAGE_IMAGES].icon().pixmap(icon_size, icon_size).toImage()

    def _fingerprint(image) -> tuple:
        step = 4
        return tuple(
            image.pixel(x, y)
            for x in range(0, image.width(), step)
            for y in range(0, image.height(), step)
        )

    assert _fingerprint(images_icon) == _fingerprint(
        navigation_icon(icon_images(), "images").pixmap(icon_size, icon_size).toImage()
    )
    assert _fingerprint(images_icon) != _fingerprint(
        navigation_icon(icon_search_nav(), "images").pixmap(icon_size, icon_size).toImage()
    )
    assert "nav.favorites" == nav._favorites_toggle.property("labelKey")
    assert nav._favorites_toggle.isVisible()
    assert nav._favorites_branch is not None
    images_y = nav._nav_buttons[PAGE_IMAGES].mapTo(nav, nav._nav_buttons[PAGE_IMAGES].rect().bottomLeft()).y()
    branch_y = nav._favorites_branch.mapTo(nav, nav._favorites_branch.rect().topLeft()).y()
    auto_y = nav._nav_buttons[PAGE_AUTOMATION].mapTo(nav, nav._nav_buttons[PAGE_AUTOMATION].rect().topLeft()).y()
    assert images_y <= branch_y <= auto_y
    assert nav._recents_header.isHidden()
    assert nav._recents_host.isHidden()
    assert nav._capture_button is not None
    assert nav._notification_button is not None
    assert nav._user_button is not None
    assert nav._capture_button.objectName() == "navUtilityButton"
    assert nav._notification_button.objectName() == "navUtilityButton"
    from app.ui.styles import APP_STYLE

    utility_block = APP_STYLE.split("QPushButton#navUtilityButton")[1]
    assert "text-align: left;" in utility_block.split("}")[0]
    assert nav._capture_button not in nav._nav_buttons.values()
    assert nav._notification_item is not nav._account_control
    assert nav._account_control._name.text() == t("nav.account.name")
    assert nav._account_control._plan.text() == t("nav.account.plan")
    window.close()


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
    assert _find_page_subtitle(window._about_page) == t("about.subtitle")
    assert _find_page_subtitle(window._automation_page) == t("automation.subtitle")
    window.close()


def test_navigation_footer_shows_product_version_not_prototype():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    assert not hasattr(nav, "_prototype_user_button")
    version = nav.findChild(QLabel, "sidebarVersionLabel")
    assert version is not None
    assert "Prototype" not in version.text()
    assert "Rootlize" in version.text()
    window.close()


def test_account_unchecks_images_so_images_nav_returns():
    """Account is off-rail; Images must uncheck so a second click can return."""
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    images = window._side_nav._nav_buttons[PAGE_IMAGES]
    assert window._stack.currentIndex() == PAGE_IMAGES
    assert images.isChecked()

    window._side_nav._account_control.click()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ACCOUNT
    assert not images.isChecked()

    images.click()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES
    assert images.isChecked()

    settings = window._side_nav._nav_buttons[PAGE_SETTINGS]
    settings.click()
    app.processEvents()
    window._side_nav._account_control.click()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ACCOUNT
    assert not settings.isChecked()
    settings.click()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_SETTINGS
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

    window._show_page(PAGE_TAGS)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES

    for page_id in (PAGE_HOME, PAGE_IMAGES, PAGE_SETTINGS, PAGE_ABOUT):
        window._show_page(page_id)
        app.processEvents()
        assert window._stack.currentIndex() == page_id
        if page_id in window._side_nav._nav_buttons:
            assert window._side_nav._nav_buttons[page_id].isChecked()
    window.close()


def test_repeated_images_home_navigation_never_waits_for_semantic_preview(monkeypatch):
    app = _ensure_app()
    entered = threading.Event()
    release = threading.Event()

    def slow_semantic_preview(_controller, _folder):
        entered.set()
        release.wait(2.0)
        return set()

    monkeypatch.setattr(
        "app.ui.ocr_test_controller.ImageAnalysisController._compute_semantic_pending_names",
        slow_semantic_preview,
    )
    window = _make_window()
    window.show()
    app.processEvents()
    window._images_page._refresh_analysis_preview()
    assert entered.wait(1.0)
    preview_threads = lambda: sum(
        thread.name == "CapixeOCRPreview" for thread in threading.enumerate()
    )
    existing = preview_threads()

    started = time.perf_counter()
    for _ in range(10):
        window._show_page(PAGE_HOME)
        window._show_page(PAGE_IMAGES)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert window._stack.currentIndex() == PAGE_IMAGES
    assert preview_threads() == existing
    release.set()
    window.close()


def test_navigation_sidebar_stays_labeled():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    nav.set_responsive_compact(False)
    assert nav.width() == nav.EXPANDED_WIDTH
    assert nav._expanded
    assert nav._nav_buttons[PAGE_IMAGES].text() == t("nav.images")
    assert PAGE_HOME not in nav._nav_buttons
    assert PAGE_ABOUT in nav._nav_buttons
    assert nav._nav_buttons[PAGE_ABOUT].property("navLabel") == t("nav.about")
    assert PAGE_SETTINGS in nav._nav_buttons

    nav.set_responsive_compact(True)
    assert nav.width() == nav.EXPANDED_WIDTH
    assert nav._expanded
    assert nav._nav_buttons[PAGE_IMAGES].text() == t("nav.images")
    window.close()


def test_navigation_sidebar_can_collapse_and_restore():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    page = window._images_page
    page._search_input.setText("keep-query")
    window._show_page(PAGE_SETTINGS)
    app.processEvents()
    content_width = window._stack.width()

    nav._collapse_btn.click()
    QTest.qWait(nav.ANIM_MS + 40)
    app.processEvents()
    assert not nav._expanded
    assert nav.width() == nav.COLLAPSED_WIDTH
    assert window._nav_restore_wrap.isHidden()
    assert nav._nav_buttons[PAGE_IMAGES].isVisible()
    assert nav._nav_buttons[PAGE_IMAGES].text() == ""
    assert nav._nav_buttons[PAGE_IMAGES].toolTip() == t("nav.images")
    assert nav._nav_buttons[PAGE_SETTINGS].isVisible()
    assert nav._favorites_rail_button.isVisible()
    assert nav._favorites_rail_button.toolTip() == t("nav.favorites")
    assert nav._notification_button.isHidden()
    assert nav._notification_button.toolTip() == t("nav.notifications")
    assert nav._capture_button.isHidden()
    assert nav._account_control._avatar.isVisible()
    assert not nav._account_control._name.isVisible()
    assert not nav._account_control._plan.isVisible()
    assert window._stack.currentIndex() == PAGE_SETTINGS
    assert page._search_input.text() == "keep-query"
    assert window._stack.width() >= content_width

    nav._nav_buttons[PAGE_IMAGES].click()
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_IMAGES

    nav._collapse_btn.click()
    QTest.qWait(nav.ANIM_MS + 40)
    app.processEvents()
    assert nav._expanded
    assert nav.width() == nav.EXPANDED_WIDTH
    assert window._nav_restore_wrap.isHidden()
    assert nav._nav_buttons[PAGE_IMAGES].text() == t("nav.images")
    assert nav._favorites_rail_button.isHidden()
    assert nav._account_control._name.isVisible()
    assert nav._account_control._name.text() == t("nav.account.name")
    assert nav._account_control._plan.text() == t("nav.account.plan")
    assert window._stack.currentIndex() == PAGE_IMAGES
    assert page._search_input.text() == "keep-query"
    assert nav._nav_buttons[PAGE_IMAGES].isChecked()
    window.close()


def test_navigation_resize_does_not_reopen_collapsed_sidebar():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    nav.set_expanded(False, animate=False)
    app.processEvents()
    window.resize(1280, 800)
    app.processEvents()
    assert not nav._expanded
    assert nav.width() == nav.COLLAPSED_WIDTH
    window.close()


def test_navigation_collapse_keeps_ask_ai_open():
    app = _ensure_app()
    window = _make_window()
    window._config["ask_ai_external_processing_consented"] = True
    window._config["ask_ai_consent_notice_version"] = 2
    window.show()
    app.processEvents()

    page = window._images_page
    page._show_ai_panel()
    app.processEvents()
    assert page._ai_panel_expanded

    nav = window._side_nav
    nav.set_expanded(False, animate=False)
    app.processEvents()
    assert page._ai_panel_expanded
    assert nav._nav_buttons[PAGE_IMAGES].isChecked()

    nav.set_expanded(True, animate=False)
    app.processEvents()
    assert page._ai_panel_expanded
    assert nav._nav_buttons[PAGE_IMAGES].isChecked()
    window.close()


def test_capture_and_notifications_are_utility_actions_not_pages():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    from app.ui.main_window import CAPTURE_ENABLED

    assert nav._capture_button.objectName() == nav._notification_button.objectName()
    assert nav._account_control.objectName() == "sidebarAccountControl"
    assert window._capture_bar.isHidden()
    assert nav._nav_buttons[PAGE_IMAGES].isChecked()
    assert nav._notification_button.isHidden()
    if CAPTURE_ENABLED:
        assert nav._capture_button.isVisible()
        nav._capture_button.click()
        app.processEvents()
        assert not window._capture_bar.isHidden()
    else:
        assert nav._capture_button.isHidden()
        nav._capture_button.click()
        app.processEvents()
        assert window._capture_bar.isHidden()
        assert window._capture_bar_visible is False
    window.close()


def test_account_control_keeps_email_and_plan_readable():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()
    control = window._side_nav._account_control
    control.set_identity("p1rworks24", "Free", tooltip="p1rworks24@gmail.com")
    app.processEvents()
    assert control.height() >= 48
    assert control._name.isVisible()
    assert control._plan.isVisible()
    assert control._plan.text() == "Free"
    assert "p1rworks24" in control._name.text()
    assert "@" not in control._name.text()
    assert control._name.geometry().bottom() <= control._plan.geometry().top() + 2
    assert "gmail.com" in control.toolTip()
    window.close()


def test_email_account_name_uses_local_part_before_at() -> None:
    from app.auth import email_account_name

    assert email_account_name("p1rworks24@gmail.com") == "p1rworks24"
    assert email_account_name("user.name+tag@example.com") == "user.name+tag"
    assert email_account_name("no-at", fallback="id-1") == "no-at"
    assert email_account_name("", fallback="id-1") == "id-1"


def test_about_nav_sits_above_account_footer():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    about = nav._nav_buttons[PAGE_ABOUT]
    settings = nav._nav_buttons[PAGE_SETTINGS]
    account = nav._account_control
    assert about.isVisible()
    assert nav._notification_button.isHidden()
    settings_bottom = settings.mapTo(nav, settings.rect().bottomLeft()).y()
    about_top = about.mapTo(nav, about.rect().topLeft()).y()
    about_bottom = about.mapTo(nav, about.rect().bottomLeft()).y()
    account_top = account.mapTo(nav, account.rect().topLeft()).y()
    assert settings_bottom <= about_top
    assert about_bottom <= account_top
    window.close()


def test_favorite_folders_nest_under_images_and_can_collapse():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    images = nav._nav_buttons[PAGE_IMAGES]
    auto = nav._nav_buttons[PAGE_AUTOMATION]
    settings = nav._nav_buttons[PAGE_SETTINGS]
    assert nav._favorites_toggle.isVisible()
    assert nav._favorites_toggle.text() == t("nav.favorites")
    assert nav._folder_scroll.isVisible()
    assert images.mapTo(nav, images.rect().bottomLeft()).y() <= nav._favorites_branch.mapTo(
        nav, nav._favorites_branch.rect().topLeft()
    ).y()
    open_auto_y = auto.mapTo(nav, auto.rect().topLeft()).y()
    open_settings_y = settings.mapTo(nav, settings.rect().topLeft()).y()
    nav.set_favorites_expanded(False)
    app.processEvents()
    assert nav._folder_scroll.isHidden()
    assert nav._favorites_toggle.isVisible()
    closed_auto_y = auto.mapTo(nav, auto.rect().topLeft()).y()
    closed_settings_y = settings.mapTo(nav, settings.rect().topLeft()).y()
    assert closed_auto_y < open_auto_y
    assert closed_settings_y < open_settings_y
    assert closed_auto_y < closed_settings_y
    nav.set_favorites_expanded(True)
    app.processEvents()
    assert nav._folder_scroll.isVisible()
    window.close()


def test_rootlize_brand_is_header_not_nav_item():
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel

    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    nav = window._side_nav
    brand = nav.findChild(QLabel, "sidebarBrand")
    images = nav._nav_buttons[PAGE_IMAGES]
    assert brand is not None
    assert brand.text() == "Rootlize"
    assert brand.font().pixelSize() >= 16
    assert int(brand.font().weight()) >= int(QFont.Weight.DemiBold)
    images_top = images.mapTo(nav, images.rect().topLeft()).y()
    brand_bottom = nav._brand_block.mapTo(
        nav, nav._brand_block.rect().bottomLeft()
    ).y()
    assert images_top - brand_bottom >= 8
    assert brand is not images
    assert PAGE_IMAGES in nav._nav_buttons
    nav.set_expanded(False, animate=False)
    app.processEvents()
    assert not brand.isVisible()
    assert nav._brand_icon.isVisible()
    assert nav.width() == nav.COLLAPSED_WIDTH
    icon_left = nav._brand_icon.mapTo(nav, nav._brand_icon.rect().topLeft()).x()
    icon_right = nav.width() - icon_left - nav._brand_icon.width()
    assert abs(icon_left - icon_right) <= 1
    nav.set_expanded(True, animate=False)
    app.processEvents()
    assert brand.isVisible()
    assert brand.width() >= 40
    window.close()

