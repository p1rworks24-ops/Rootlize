"""About page: brand, GitHub, feedback rows, legal footer."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.branding import (
    APP_COPYRIGHT,
    APP_GITHUB_URL,
    APP_LICENSE,
    APP_NAME,
    APP_URL_REPORT_BUG,
    DISPLAY_VERSION,
    TAGLINE,
    github_issues_url,
    resolve_feedback_url,
)
from app.i18n import t
from app.ui.main_window import PAGE_ABOUT, PAGE_SETTINGS, MainWindow
from app.ui.pages.about_page import (
    FEEDBACK_ITEM_SPECS,
    AboutFeedbackRow,
    AboutPage,
    open_external_url,
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
        "window_width": 1050,
        "window_height": 600,
        "window_title": "Capixe",
    }
    return MainWindow(config)


def test_about_page_content():
    _ensure_app()
    page = AboutPage()

    titles = [
        lbl.text()
        for lbl in page.findChildren(QLabel)
        if lbl.objectName() == "aboutBrandTitle"
    ]
    assert titles == [APP_NAME]

    taglines = [
        lbl.text()
        for lbl in page.findChildren(QLabel)
        if lbl.objectName() == "aboutTagline"
    ]
    assert taglines == [TAGLINE]

    versions = [
        lbl.text()
        for lbl in page.findChildren(QLabel)
        if lbl.objectName() == "aboutVersionBadge"
    ]
    assert versions == [DISPLAY_VERSION]

    legal = {
        lbl.text()
        for lbl in page.findChildren(QLabel)
        if lbl.objectName() == "aboutLegalText"
    }
    assert APP_LICENSE in legal
    assert APP_COPYRIGHT in legal

    github_buttons = [
        btn.text()
        for btn in page.findChildren(QPushButton)
        if btn.objectName() == "aboutLinkButton"
    ]
    assert github_buttons == [t("about.link_github")]

    rows = page.findChildren(AboutFeedbackRow)
    assert len(rows) == 3
    assert [r.property("feedbackId") for r in rows] == [
        s.item_id for s in FEEDBACK_ITEM_SPECS
    ]

    headings = {
        lbl.text()
        for lbl in page.findChildren(QLabel)
        if lbl.objectName() == "aboutSectionHeading"
    }
    assert t("about.github_heading") in headings
    assert t("about.feedback_heading") in headings

    # Title + description present for each feedback item
    all_text = " ".join(
        lbl.text() for lbl in page.findChildren(QLabel)
    )
    assert t("about.link_feedback") in all_text
    assert t("about.feedback_desc") in all_text
    assert t("about.link_bug") in all_text
    assert t("about.bug_desc") in all_text
    assert t("about.link_feature") in all_text
    assert t("about.feature_desc") in all_text


def test_about_nav_and_stack():
    app = _ensure_app()
    window = _make_window()
    window.show()
    app.processEvents()

    assert PAGE_ABOUT in window._side_nav._nav_buttons
    assert window._side_nav._nav_buttons[PAGE_ABOUT].property("navLabel") == t(
        "nav.about"
    )
    assert window._side_nav._nav_buttons[PAGE_ABOUT].property("navAccent") == "about"

    window._show_page(PAGE_ABOUT)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ABOUT
    assert window._side_nav._nav_buttons[PAGE_ABOUT].isChecked()
    assert not window._side_nav._nav_buttons[PAGE_SETTINGS].isChecked()


def test_feedback_urls_centralized():
    assert APP_GITHUB_URL.startswith("https://")
    assert resolve_feedback_url("feedback") == github_issues_url()
    assert resolve_feedback_url("bug") == github_issues_url()
    assert resolve_feedback_url("feature") == github_issues_url()
    assert APP_URL_REPORT_BUG is None  # override slot ready for templates


def test_open_external_url_never_raises():
    _ensure_app()
    with patch(
        "app.ui.pages.about_page.QDesktopServices.openUrl",
        side_effect=RuntimeError("boom"),
    ):
        assert open_external_url("https://example.com") is False

    with patch(
        "app.ui.pages.about_page.QDesktopServices.openUrl",
        return_value=False,
    ):
        assert open_external_url("https://example.com") is False

    assert open_external_url("") is False


def test_github_and_feedback_click_open_urls():
    _ensure_app()
    page = AboutPage()
    opened: list[str] = []

    def _capture(url):
        opened.append(url.toString())
        return True

    with patch(
        "app.ui.pages.about_page.QDesktopServices.openUrl",
        side_effect=_capture,
    ):
        github_btn = next(
            btn
            for btn in page.findChildren(QPushButton)
            if btn.objectName() == "aboutLinkButton"
        )
        github_btn.click()
        for row in page.findChildren(AboutFeedbackRow):
            row.clicked.emit()

    assert opened[0] == APP_GITHUB_URL or opened[0].rstrip("/") == APP_GITHUB_URL.rstrip(
        "/"
    )
    assert len(opened) == 1 + len(FEEDBACK_ITEM_SPECS)
    for url in opened[1:]:
        assert url == github_issues_url() or url.rstrip("/") == github_issues_url().rstrip(
            "/"
        )


def test_about_fits_default_window_with_scroll():
    app = _ensure_app()
    window = _make_window()
    window.resize(1050, 600)
    window.show()
    window._show_page(PAGE_ABOUT)
    app.processEvents()

    page = window._about_page
    assert page.width() > 0
    # Brand + GitHub + Feedback sections present (scroll handles overflow)
    assert len(page.findChildren(AboutFeedbackRow)) == 3
    assert any(
        btn.objectName() == "aboutLinkButton"
        for btn in page.findChildren(QPushButton)
    )
