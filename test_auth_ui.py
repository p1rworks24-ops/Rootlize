"""Account UI exists and does not talk to Supabase directly."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QLineEdit
from PySide6.QtTest import QTest

from app.auth import AuthService, AuthStatus, MemoryCredentialStore
from app.auth.config import AuthClientConfig
from app.auth.device import DeviceService
from app.auth.http import HttpResponse
from app.i18n import t
from app.ui.main_window import PAGE_ACCOUNT, MainWindow
from app.ui.pages.account_page import AccountPage
from test_auth import FakeHttp, _user_payload


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_account_page_has_sign_in_controls():
    _ensure_app()
    page = AccountPage()
    assert page.findChild(QPushButton, "accountGoogleButton").text() == t("account.continue_google")
    assert page.findChild(QPushButton, "accountGitHubButton").text() == t("account.continue_github")
    assert page.findChild(QLineEdit, "accountEmailInput") is not None
    assert page.findChild(QLineEdit, "accountPasswordInput") is not None
    assert page.findChild(QPushButton, "accountSignInButton").text() == t("account.sign_in")
    assert page.findChild(QPushButton, "accountCreateButton") is not None
    assert "Supabase" not in page.findChild(QPushButton, "accountGoogleButton").text()
    page.close()


def test_main_window_starts_without_supabase_env(monkeypatch):
    app = _ensure_app()
    monkeypatch.delenv("CAPIXE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1000,
            "window_height": 700,
            "window_title": "Capixe",
        }
    )
    window.show()
    app.processEvents()
    assert window.isVisible()
    assert window._account_controller.service.configured is False
    QTest.mouseClick(window._side_nav._account_control, Qt.LeftButton)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ACCOUNT
    window.close()


def test_main_window_starts_when_provider_secret_is_rejected(monkeypatch):
    app = _ensure_app()
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1000,
            "window_height": 700,
            "window_title": "Capixe",
        }
    )
    window.show()
    app.processEvents()
    assert window.isVisible()
    assert window._account_page is not None
    assert window._account_controller.service.configured is False
    QTest.mouseClick(window._side_nav._account_control, Qt.LeftButton)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ACCOUNT
    window.close()


def test_main_window_opens_account_page_from_nav():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Default").mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "save_folder": "Default",
            "window_width": 1000,
            "window_height": 700,
            "window_title": "Capixe",
        }
    )
    window.show()
    app.processEvents()
    assert window._account_page.findChild(QPushButton, "accountGoogleButton") is not None
    QTest.mouseClick(window._side_nav._account_control, Qt.LeftButton)
    app.processEvents()
    assert window._stack.currentIndex() == PAGE_ACCOUNT
    window.close()


def test_signed_in_account_shows_email_and_sign_out(tmp_path):
    app = _ensure_app()
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = AuthService(
        AuthClientConfig("https://example.supabase.co", "anon-public"),
        store=MemoryCredentialStore(),
        devices=DeviceService(tmp_path / "device.json"),
        http=http,
        open_url=lambda _url: None,
    )
    session = service.sign_in_email("ada@example.com", "secret")
    assert session.status == AuthStatus.SIGNED_IN
    page = AccountPage()
    page.apply_session(session)
    app.processEvents()
    assert "ada@example.com" in page._signed_email.text()
    assert t("account.plan.prototype") in page._plan.text()
    assert "Free" not in page._plan.text()
    assert page._sign_out.isVisibleTo(page)
    assert not page._google.isVisibleTo(page)
    from app.budget.calc import usage_status

    page.apply_usage(usage_status(budget_micros=100, used_micros=63))
    assert "63%" in page._usage_used.text()
    assert "37%" in page._usage_remaining.text()
    assert not page._usage_reset.isVisibleTo(page)
    assert "$" not in page._usage_used.text()
    page.close()


def test_anonymous_account_keeps_optional_sign_in_and_hides_uuid():
    _ensure_app()
    from app.auth.models import AccountSession, AuthUser, Entitlement

    page = AccountPage()
    page.apply_session(
        AccountSession(
            status=AuthStatus.SIGNED_IN,
            user=AuthUser(
                user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                email="",
                is_anonymous=True,
            ),
            entitlement=Entitlement(plan="prototype"),
        )
    )
    assert t("account.guest_identity") in page._signed_email.text()
    assert "aaaaaaaa" not in page._signed_email.text()
    assert t("account.plan.prototype") in page._plan.text()
    assert page._google.isVisibleTo(page)
    assert page._primary.isVisibleTo(page)
    assert not page._sign_out.isVisibleTo(page)
    page.close()
