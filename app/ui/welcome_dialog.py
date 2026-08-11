"""First-run introduction to Capixe's core Find workflow."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from app.i18n import t
from app.ui.icons import icon_analyze, icon_folder, icon_search


class WelcomeDialog(QDialog):
    """Small modal that explains Folder -> Analyze -> Search."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomeDialog")
        self.setWindowTitle(t("onboarding.title"))
        self.setModal(True)
        self.setWindowModality(Qt.WindowModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(680)
        self.setMaximumWidth(760)
        self.go_to_images = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)

        title = QLabel(t("onboarding.title"), self)
        title.setObjectName("welcomeTitle")
        outer.addWidget(title)

        subtitle = QLabel(t("onboarding.subtitle"), self)
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        steps = QHBoxLayout()
        steps.setSpacing(12)
        step_specs = (
            ("1", "choose_folder", icon_folder(color="#0891b2")),
            ("2", "analyze", icon_analyze()),
            ("3", "search", icon_search()),
        )
        for number, key, icon in step_specs:
            card = QFrame(self)
            card.setObjectName("welcomeStepCard")
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(8)

            step_header = QHBoxLayout()
            step_header.setSpacing(8)
            marker = QLabel(number, card)
            marker.setObjectName("welcomeStepNumber")
            marker.setAlignment(Qt.AlignCenter)
            step_header.addWidget(marker)
            symbol = QLabel(card)
            symbol.setObjectName("welcomeStepIcon")
            symbol.setPixmap(icon.pixmap(QSize(20, 20)))
            step_header.addWidget(symbol)
            step_header.addStretch(1)
            card_layout.addLayout(step_header)

            heading = QLabel(t(f"onboarding.step.{key}.title"), card)
            heading.setObjectName("welcomeStepTitle")
            heading.setWordWrap(True)
            card_layout.addWidget(heading)

            body = QLabel(t(f"onboarding.step.{key}.body"), card)
            body.setObjectName("welcomeStepBody")
            body.setWordWrap(True)
            body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            card_layout.addWidget(body, stretch=1)
            steps.addWidget(card, stretch=1)
        outer.addLayout(steps)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        later = QPushButton(t("onboarding.maybe_later"), self)
        later.setObjectName("secondaryButton")
        later.clicked.connect(self.reject)
        actions.addWidget(later)
        primary = QPushButton(t("onboarding.go_to_images"), self)
        primary.setObjectName("welcomePrimaryButton")
        primary.setDefault(True)
        primary.clicked.connect(self._go_to_images)
        actions.addWidget(primary)
        outer.addLayout(actions)

    def _go_to_images(self) -> None:
        self.go_to_images = True
        self.accept()
