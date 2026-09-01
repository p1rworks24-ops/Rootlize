"""Account / Sign-in page. Talks only to AccountController."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.auth import AccountSession, AuthStatus
from app.budget.models import AIUsageStatus
from app.i18n import t
from app.ui.design_tokens import apply_card_shadow
from app.ui.page_header import make_page_header
from app.ui.scroll_page import make_page_scroll
from app.ui.text_select import enable_label_text_selection


class AccountPage(QWidget):
    google_clicked = Signal()
    github_clicked = Signal()
    sign_in_clicked = Signal(str, str)
    sign_up_clicked = Signal(str, str)
    sign_out_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("accountPage")
        self._signup_mode = False
        self._init_ui()
        enable_label_text_selection(self)

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = make_page_scroll(self)
        outer.addWidget(scroll)
        content = QWidget(scroll)
        content.setObjectName("settingsContentColumn")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(12)
        layout.addWidget(make_page_header(content, t("account.title"), t("account.subtitle")))

        card = QFrame(content)
        card.setObjectName("infoPanel")
        apply_card_shadow(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)
        self._card_layout = card_layout

        self._welcome = QLabel(t("account.welcome"), card)
        self._welcome.setObjectName("sectionTitle")
        self._welcome.setWordWrap(True)
        card_layout.addWidget(self._welcome)

        self._status = QLabel("", card)
        self._status.setObjectName("accountStatusLabel")
        self._status.setWordWrap(True)
        card_layout.addWidget(self._status)

        self._google = QPushButton(t("account.continue_google"), card)
        self._google.setObjectName("accountGoogleButton")
        self._google.setCursor(Qt.PointingHandCursor)
        self._google.clicked.connect(self.google_clicked.emit)
        card_layout.addWidget(self._google)

        self._github = QPushButton(t("account.continue_github"), card)
        self._github.setObjectName("accountGitHubButton")
        self._github.setCursor(Qt.PointingHandCursor)
        self._github.clicked.connect(self.github_clicked.emit)
        card_layout.addWidget(self._github)

        self._email = QLineEdit(card)
        self._email.setObjectName("accountEmailInput")
        self._email.setPlaceholderText(t("account.email"))
        self._email.setTextMargins(10, 4, 10, 4)
        card_layout.addWidget(self._email)

        self._password = QLineEdit(card)
        self._password.setObjectName("accountPasswordInput")
        self._password.setPlaceholderText(t("account.password"))
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setTextMargins(10, 4, 10, 4)
        card_layout.addWidget(self._password)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._primary = QPushButton(t("account.sign_in"), card)
        self._primary.setObjectName("accountSignInButton")
        self._primary.setDefault(True)
        self._primary.clicked.connect(self._on_primary)
        actions.addWidget(self._primary)
        self._switch = QPushButton(t("account.create_account"), card)
        self._switch.setObjectName("accountCreateButton")
        self._switch.clicked.connect(self._toggle_mode)
        actions.addWidget(self._switch)
        actions.addStretch(1)
        card_layout.addLayout(actions)

        self._signed_email = QLabel("", card)
        self._signed_email.setObjectName("accountEmailLabel")
        self._signed_email.setWordWrap(True)
        card_layout.addWidget(self._signed_email)

        self._plan = QLabel("", card)
        self._plan.setObjectName("accountPlanLabel")
        card_layout.addWidget(self._plan)

        self._usage_title = QLabel(t("account.ai_usage"), card)
        self._usage_title.setObjectName("accountUsageTitle")
        card_layout.addWidget(self._usage_title)

        self._usage_bar = QProgressBar(card)
        self._usage_bar.setObjectName("accountUsageBar")
        self._usage_bar.setRange(0, 100)
        self._usage_bar.setValue(0)
        self._usage_bar.setTextVisible(False)
        self._usage_bar.setFixedHeight(8)
        card_layout.addWidget(self._usage_bar)

        self._usage_used = QLabel("", card)
        self._usage_used.setObjectName("accountUsageUsed")
        card_layout.addWidget(self._usage_used)

        self._usage_remaining = QLabel("", card)
        self._usage_remaining.setObjectName("accountUsageRemaining")
        card_layout.addWidget(self._usage_remaining)

        self._usage_reset = QLabel("", card)
        self._usage_reset.setObjectName("accountUsageReset")
        self._usage_reset.setVisible(False)
        card_layout.addWidget(self._usage_reset)

        self._usage_hint = QLabel("", card)
        self._usage_hint.setObjectName("accountUsageHint")
        self._usage_hint.setWordWrap(True)
        card_layout.addWidget(self._usage_hint)

        self._sign_out = QPushButton(t("account.sign_out"), card)
        self._sign_out.setObjectName("accountSignOutButton")
        self._sign_out.clicked.connect(self.sign_out_clicked.emit)
        card_layout.addWidget(self._sign_out)

        self._offline_hint = QLabel(t("account.local_still_works"), card)
        self._offline_hint.setObjectName("mutedLabel")
        self._offline_hint.setWordWrap(True)
        card_layout.addWidget(self._offline_hint)

        layout.addWidget(card)
        layout.addStretch(1)
        self.apply_session(AccountSession())

    def set_busy(self, busy: bool) -> None:
        enabled = not busy
        for widget in (
            self._google,
            self._github,
            self._email,
            self._password,
            self._primary,
            self._switch,
            self._sign_out,
        ):
            widget.setEnabled(enabled)

    def show_message(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def apply_session(self, session: AccountSession) -> None:
        signed_in = session.is_authenticated
        anonymous = bool(signed_in and getattr(session, "is_anonymous", False))
        named = signed_in and not anonymous
        self._welcome.setText(
            t("account.guest_title")
            if anonymous
            else t("account.signed_in_title")
            if named
            else t("account.welcome")
        )
        show_form = not named
        self._google.setVisible(show_form)
        self._github.setVisible(show_form)
        self._email.setVisible(show_form)
        self._password.setVisible(show_form)
        self._primary.setVisible(show_form)
        self._switch.setVisible(show_form)
        self._signed_email.setVisible(signed_in)
        self._plan.setVisible(signed_in)
        self._sign_out.setVisible(named)
        if signed_in:
            if anonymous:
                self._signed_email.setText(t("account.guest_identity"))
            else:
                self._signed_email.setText(session.email or session.user_id)
            self._plan.setText(t("account.plan_label", plan=session.entitlement.plan_label))
            if session.status == AuthStatus.OFFLINE_SESSION:
                self._status.setText(t("account.offline"))
                if not self._usage_used.text():
                    self.apply_usage(AIUsageStatus.unavailable_status())
            elif anonymous:
                if not self._status.text() or self._status.text() == t("account.guest_body"):
                    self._status.setText(t("account.guest_body"))
            elif self._status.text() == t("account.guest_body") or not self._status.text():
                self._status.clear()
        else:
            self._signed_email.clear()
            self._plan.clear()
            self.apply_usage(None)
        self._status.setVisible(bool(self._status.text()))
        self._offline_hint.setVisible(True)

    def apply_usage(self, status: AIUsageStatus | None) -> None:
        show = status is not None and self._signed_email.isVisibleTo(self)
        for widget in (
            self._usage_title,
            self._usage_bar,
            self._usage_used,
            self._usage_remaining,
            self._usage_hint,
        ):
            widget.setVisible(show)
        self._usage_reset.setVisible(False)
        if not show or status is None:
            self._usage_used.clear()
            self._usage_remaining.clear()
            self._usage_reset.clear()
            self._usage_hint.clear()
            return
        used = status.display_used_percent
        remaining = status.display_remaining_percent
        self._usage_bar.setValue(used)
        self._usage_bar.setProperty("usageState", status.warning_level)
        style = self._usage_bar.style()
        if style is not None:
            style.unpolish(self._usage_bar)
            style.polish(self._usage_bar)
        if status.unavailable:
            self._usage_used.setText(t("account.ai.verification_unavailable"))
            self._usage_remaining.clear()
            self._usage_hint.setText(t("account.ai.offline"))
            self._usage_hint.setVisible(True)
            return
        self._usage_used.setText(t("account.ai_used_percent", percent=used))
        self._usage_remaining.setText(t("account.ai_remaining_percent", percent=remaining))
        if status.limit_reached or used >= 100:
            self._usage_hint.setText(
                f"{t('account.ai.limit_reached')}\n{t('account.ai.limit_reached_body')}"
            )
            self._usage_hint.setVisible(True)
        elif status.used_percent >= 95:
            self._usage_hint.setText(t("account.ai_critical"))
            self._usage_hint.setVisible(True)
        elif status.used_percent >= 80:
            self._usage_hint.setText(t("account.ai_warning"))
            self._usage_hint.setVisible(True)
        else:
            self._usage_hint.clear()
            self._usage_hint.setVisible(False)

    def _toggle_mode(self) -> None:
        self._signup_mode = not self._signup_mode
        if self._signup_mode:
            self._primary.setText(t("account.create_account"))
            self._switch.setText(t("account.have_account"))
        else:
            self._primary.setText(t("account.sign_in"))
            self._switch.setText(t("account.create_account"))

    def _on_primary(self) -> None:
        email = self._email.text().strip()
        password = self._password.text()
        if self._signup_mode:
            self.sign_up_clicked.emit(email, password)
        else:
            self.sign_in_clicked.emit(email, password)
