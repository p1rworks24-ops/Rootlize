"""Dedicated first-launch sign-in page. Not a tour overlay step."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_NAME, SUPPORTING_MESSAGE, TAGLINE
from app.i18n import t
from app.ui.design_tokens import apply_card_shadow
from app.ui.text_select import enable_label_text_selection


class SignInGatePage(QWidget):
    google_clicked = Signal()
    github_clicked = Signal()
    sign_in_clicked = Signal(str, str)
    sign_up_clicked = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("signInGatePage")
        self._signup_mode = False
        self._init_ui()
        enable_label_text_selection(self)

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.addStretch(1)

        card = QFrame(self)
        card.setObjectName("infoPanel")
        apply_card_shadow(card, role="floating")
        card.setMaximumWidth(440)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        brand = QLabel(APP_NAME, card)
        brand.setObjectName("tourWelcomeTitle")
        layout.addWidget(brand)
        tagline = QLabel(TAGLINE, card)
        tagline.setObjectName("signInTagline")
        tagline.setWordWrap(True)
        layout.addWidget(tagline)
        supporting = QLabel(SUPPORTING_MESSAGE, card)
        supporting.setObjectName("mutedLabel")
        supporting.setWordWrap(True)
        layout.addWidget(supporting)

        self._title = QLabel(t("tour.gate.title"), card)
        self._title.setObjectName("sectionTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._body = QLabel(t("tour.gate.body"), card)
        self._body.setObjectName("mutedLabel")
        self._body.setWordWrap(True)
        layout.addWidget(self._body)

        self._status = QLabel("", card)
        self._status.setObjectName("accountStatusLabel")
        self._status.setWordWrap(True)
        self._status.hide()
        layout.addWidget(self._status)

        self._google = QPushButton(t("account.continue_google"), card)
        self._google.setObjectName("accountGoogleButton")
        self._google.setCursor(Qt.PointingHandCursor)
        self._google.clicked.connect(self.google_clicked.emit)
        layout.addWidget(self._google)

        self._github = QPushButton(t("account.continue_github"), card)
        self._github.setObjectName("accountGitHubButton")
        self._github.setCursor(Qt.PointingHandCursor)
        self._github.clicked.connect(self.github_clicked.emit)
        layout.addWidget(self._github)

        self._email = QLineEdit(card)
        self._email.setObjectName("accountEmailInput")
        self._email.setPlaceholderText(t("account.email"))
        self._email.setTextMargins(10, 4, 10, 4)
        layout.addWidget(self._email)

        self._password = QLineEdit(card)
        self._password.setObjectName("accountPasswordInput")
        self._password.setPlaceholderText(t("account.password"))
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setTextMargins(10, 4, 10, 4)
        layout.addWidget(self._password)

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
        layout.addLayout(actions)

        hint = QLabel(t("account.local_still_works"), card)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def set_busy(self, busy: bool) -> None:
        enabled = not busy
        for widget in (
            self._google,
            self._github,
            self._email,
            self._password,
            self._primary,
            self._switch,
        ):
            widget.setEnabled(enabled)

    def show_message(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def show_not_configured(self) -> None:
        self.show_message(t("account.error.not_configured"))

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
