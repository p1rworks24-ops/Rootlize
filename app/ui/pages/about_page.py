"""About page — brand, version, GitHub, feedback links, legal footer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.branding import (
    APP_COPYRIGHT,
    APP_GITHUB_URL,
    APP_LICENSE,
    APP_NAME,
    DISPLAY_VERSION,
    TAGLINE,
    resolve_feedback_url,
)
from app.i18n import t
from app.ui.app_icon import app_mark_pixmap
from app.ui.icons import fluent_icon
from app.ui.scroll_page import make_page_scroll
from app.utils.logger import setup_logger

_log = setup_logger()

# Fluent glyphs for feedback rows (no emoji)
_GLYPH_FEEDBACK = "\uE8BD"  # Message
_GLYPH_BUG = "\uEBE8"  # Bug
_GLYPH_FEATURE = "\uEA80"  # Lightbulb
_GLYPH_OPEN = "\uE8A7"  # Open


@dataclass(frozen=True)
class FeedbackItemSpec:
    """One feedback action — add entries here to extend the Feedback section."""

    item_id: str
    title_key: str
    description_key: str
    glyph: str
    # Key passed to resolve_feedback_url()
    url_kind: str


# Ordered registry — append without restructuring the page
FEEDBACK_ITEM_SPECS: tuple[FeedbackItemSpec, ...] = (
    FeedbackItemSpec(
        "feedback",
        "about.link_feedback",
        "about.feedback_desc",
        _GLYPH_FEEDBACK,
        "feedback",
    ),
    FeedbackItemSpec(
        "bug",
        "about.link_bug",
        "about.bug_desc",
        _GLYPH_BUG,
        "bug",
    ),
    FeedbackItemSpec(
        "feature",
        "about.link_feature",
        "about.feature_desc",
        _GLYPH_FEATURE,
        "feature",
    ),
)


def open_external_url(url: str, *, parent: QWidget | None = None) -> bool:
    """Open ``url`` in the default browser; never raise to the caller."""
    target = (url or "").strip()
    if not target:
        if parent is not None:
            QMessageBox.warning(
                parent,
                APP_NAME,
                t("about.link_open_failed"),
            )
        return False
    try:
        ok = bool(QDesktopServices.openUrl(QUrl(target)))
    except Exception:
        _log.exception("Failed to open external URL: %s", target)
        ok = False
    if not ok and parent is not None:
        QMessageBox.warning(
            parent,
            APP_NAME,
            t("about.link_open_failed"),
        )
    return ok


class AboutFeedbackRow(QFrame):
    """Clickable feedback row: icon + title + description."""

    clicked = Signal()

    def __init__(
        self,
        *,
        title: str,
        description: str,
        glyph: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("aboutFeedbackRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        icon_lbl = QLabel(self)
        icon_lbl.setObjectName("aboutFeedbackIcon")
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setPixmap(
            fluent_icon(glyph, size=20, color="#0f766e").pixmap(20, 20)
        )
        icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        root.addWidget(icon_lbl, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_lbl = QLabel(title, self)
        title_lbl.setObjectName("aboutFeedbackTitle")
        title_lbl.setWordWrap(True)
        title_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_col.addWidget(title_lbl)

        desc_lbl = QLabel(description, self)
        desc_lbl.setObjectName("aboutFeedbackDesc")
        desc_lbl.setWordWrap(True)
        desc_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text_col.addWidget(desc_lbl)

        root.addLayout(text_col, stretch=1)

        chevron = QLabel(self)
        chevron.setObjectName("aboutFeedbackChevron")
        chevron.setFixedSize(20, 20)
        chevron.setAlignment(Qt.AlignCenter)
        chevron.setPixmap(
            fluent_icon(_GLYPH_OPEN, size=14, color="#9ca3af").pixmap(14, 14)
        )
        chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        root.addWidget(chevron, 0, Qt.AlignVCenter)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AboutPage(QWidget):
    """
    Capixe About surface: brand hero, GitHub, feedback rows, legal footer.

    Extra cards can be registered via ``_append_section_card`` later without
    changing the outer layout grid.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._section_host: QVBoxLayout | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        content.setObjectName("aboutContentColumn")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self._section_host = layout

        self._append_brand_card(content)
        self._append_github_card(content)
        self._append_feedback_card(content)

        layout.addStretch(1)
        self._append_legal_footer(content)

    def _make_card(self, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("aboutCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)
        return card, card_layout

    def _append_brand_card(self, parent: QWidget) -> None:
        card, card_layout = self._make_card(parent)
        card.setObjectName("aboutBrandCard")
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(14)

        mark = QLabel(card)
        mark.setObjectName("aboutBrandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(120, 120)
        mark.setPixmap(app_mark_pixmap(112))
        card_layout.addWidget(mark, 0, Qt.AlignHCenter)

        title = QLabel(APP_NAME, card)
        title.setObjectName("aboutBrandTitle")
        title.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(title)

        tagline = QLabel(TAGLINE, card)
        tagline.setObjectName("aboutTagline")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        card_layout.addWidget(tagline)

        version = QLabel(DISPLAY_VERSION, card)
        version.setObjectName("aboutVersionBadge")
        version.setAlignment(Qt.AlignCenter)
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 4, 0, 0)
        badge_row.addStretch(1)
        badge_row.addWidget(version, 0, Qt.AlignCenter)
        badge_row.addStretch(1)
        card_layout.addLayout(badge_row)

        assert self._section_host is not None
        self._section_host.addWidget(card)

    def _append_github_card(self, parent: QWidget) -> None:
        card, card_layout = self._make_card(parent)

        heading = QLabel(t("about.github_heading"), card)
        heading.setObjectName("aboutSectionHeading")
        card_layout.addWidget(heading)

        hint = QLabel(t("about.github_hint"), card)
        hint.setObjectName("aboutSectionHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        btn = QPushButton(t("about.link_github"), card)
        btn.setObjectName("aboutLinkButton")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(40)
        btn.clicked.connect(self._on_github_clicked)
        card_layout.addWidget(btn)

        assert self._section_host is not None
        self._section_host.addWidget(card)

    def _append_feedback_card(self, parent: QWidget) -> None:
        card, card_layout = self._make_card(parent)

        heading = QLabel(t("about.feedback_heading"), card)
        heading.setObjectName("aboutSectionHeading")
        card_layout.addWidget(heading)

        hint = QLabel(t("about.feedback_hint"), card)
        hint.setObjectName("aboutSectionHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(8)

        for spec in FEEDBACK_ITEM_SPECS:
            row = AboutFeedbackRow(
                title=t(spec.title_key),
                description=t(spec.description_key),
                glyph=spec.glyph,
                parent=card,
            )
            row.setProperty("feedbackId", spec.item_id)
            row.clicked.connect(
                lambda s=spec: self._on_feedback_clicked(s)
            )
            list_layout.addWidget(row)

        card_layout.addLayout(list_layout)
        assert self._section_host is not None
        self._section_host.addWidget(card)

    def _append_legal_footer(self, parent: QWidget) -> None:
        footer = QFrame(parent)
        footer.setObjectName("aboutLegalFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(8, 4, 8, 4)
        footer_layout.setSpacing(2)

        license_label = QLabel(APP_LICENSE, footer)
        license_label.setObjectName("aboutLegalText")
        license_label.setWordWrap(True)
        footer_layout.addWidget(license_label)

        copyright_label = QLabel(APP_COPYRIGHT, footer)
        copyright_label.setObjectName("aboutLegalText")
        footer_layout.addWidget(copyright_label)

        assert self._section_host is not None
        self._section_host.addWidget(footer)

    def _append_section_card(
        self,
        parent: QWidget,
        *,
        heading_key: str,
        hint_key: str = "",
        build: Callable[[QFrame, QVBoxLayout], None] | None = None,
    ) -> QFrame:
        """Public extension hook for future About sections."""
        card, card_layout = self._make_card(parent)
        heading = QLabel(t(heading_key), card)
        heading.setObjectName("aboutSectionHeading")
        card_layout.addWidget(heading)
        if hint_key:
            hint = QLabel(t(hint_key), card)
            hint.setObjectName("aboutSectionHint")
            hint.setWordWrap(True)
            card_layout.addWidget(hint)
        if build is not None:
            build(card, card_layout)
        assert self._section_host is not None
        self._section_host.insertWidget(max(0, self._section_host.count() - 2), card)
        return card

    def _on_github_clicked(self) -> None:
        open_external_url(APP_GITHUB_URL, parent=self)

    def _on_feedback_clicked(self, spec: FeedbackItemSpec) -> None:
        open_external_url(resolve_feedback_url(spec.url_kind), parent=self)
