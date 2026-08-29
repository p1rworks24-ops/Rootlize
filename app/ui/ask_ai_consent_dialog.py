"""First-use Ask AI explanation and consent.

Agreeing records consent and is the start boundary for external AI use.
Cancel does not persist consent and does not start analysis.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.ui.page_motion import AnimatedDialog

_CAPABILITY_SECTIONS = (
    ("meaning", ("example1", "example2")),
    ("action", ("example1", "example2")),
)


class AskAiConsentDialog(AnimatedDialog):
    """One-screen Ask AI explanation. Does not start analysis until accepted."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("askAiConsentDialog")
        self.setWindowTitle(t("images.ai.consent.title"))
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        self.setMaximumWidth(640)
        self.setMinimumHeight(420)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(12)

        title = QLabel(t("images.ai.consent.title"), self)
        title.setObjectName("askAiConsentTitle")
        outer.addWidget(title)

        subtitle = QLabel(t("images.ai.consent.subtitle"), self)
        subtitle.setObjectName("askAiConsentSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        scroll = QScrollArea(self)
        scroll.setObjectName("askAiConsentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget(scroll)
        body.setObjectName("askAiConsentBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 8, 0)
        body_layout.setSpacing(12)

        capabilities = QLabel(t("images.ai.consent.capabilities"), body)
        capabilities.setObjectName("askAiConsentSectionTitle")
        capabilities.setWordWrap(True)
        body_layout.addWidget(capabilities)

        for key, examples in _CAPABILITY_SECTIONS:
            body_layout.addWidget(self._capability_card(body, key, examples))

        external = QFrame(body)
        external.setObjectName("askAiConsentFactCard")
        external_layout = QVBoxLayout(external)
        external_layout.setContentsMargins(16, 12, 16, 12)
        external_layout.setSpacing(4)
        external_title = QLabel(t("images.ai.consent.external.title"), external)
        external_title.setObjectName("askAiConsentFactTitle")
        external_title.setWordWrap(True)
        external_layout.addWidget(external_title)
        external_body = QLabel(t("images.ai.consent.external.body"), external)
        external_body.setObjectName("askAiConsentFactBody")
        external_body.setWordWrap(True)
        external_layout.addWidget(external_body)
        body_layout.addWidget(external)

        folder_size = QFrame(body)
        folder_size.setObjectName("askAiConsentFactCard")
        folder_layout = QVBoxLayout(folder_size)
        folder_layout.setContentsMargins(16, 12, 16, 12)
        folder_layout.setSpacing(4)
        folder_title = QLabel(t("images.ai.consent.folder_size.title"), folder_size)
        folder_title.setObjectName("askAiConsentFactTitle")
        folder_title.setWordWrap(True)
        folder_layout.addWidget(folder_title)
        folder_body = QLabel(t("images.ai.consent.folder_size.body"), folder_size)
        folder_body.setObjectName("askAiConsentFactBody")
        folder_body.setWordWrap(True)
        folder_layout.addWidget(folder_body)
        body_layout.addWidget(folder_size)

        footnote = QLabel(t("images.ai.consent.footnote"), body)
        footnote.setObjectName("askAiConsentFootnote")
        footnote.setWordWrap(True)
        body_layout.addWidget(footnote)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = QPushButton(t("images.ai.consent.cancel"), self)
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        agree = QPushButton(t("images.ai.consent.agree"), self)
        agree.setObjectName("askAiConsentPrimaryButton")
        agree.setDefault(True)
        agree.clicked.connect(self.accept)
        actions.addWidget(agree)
        outer.addLayout(actions)

    def _capability_card(
        self, parent: QWidget, key: str, examples: tuple[str, ...]
    ) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("askAiConsentFactCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        heading = QLabel(t(f"images.ai.consent.{key}.title"), card)
        heading.setObjectName("askAiConsentFactTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        body = QLabel(t(f"images.ai.consent.{key}.body"), card)
        body.setObjectName("askAiConsentFactBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        for example_key in examples:
            example = QLabel(t(f"images.ai.consent.{key}.{example_key}"), card)
            example.setObjectName("askAiConsentExample")
            example.setWordWrap(True)
            example.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(example)
        return card
