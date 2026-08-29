"""Welcome, completion, and short feedback cards for the prototype tour."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from app.branding import SUPPORTING_MESSAGE, TAGLINE
from app.i18n import t
from app.prototype_tour.models import (
    EASIER_CHOICES,
    MOST_USEFUL_CHOICES,
    PAYMENT_CHOICES,
    WOULD_USE_CHOICES,
    GuideView,
)
from app.ui.checkbox import paint_checkbox_indicator
from app.ui.design_tokens import (
    CHECKBOX_SIZE,
    COLORS,
    CONTROL_COMPACT,
    SPACE_2,
    apply_card_shadow,
)


class TourWelcomeCard(QFrame):
    start_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourWelcomeCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        apply_card_shadow(self, role="floating")
        self.setFixedWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        self._title = QLabel(t("tour.welcome.title"), self)
        self._title.setObjectName("tourWelcomeTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._tagline = QLabel(TAGLINE, self)
        self._tagline.setObjectName("tourWelcomeTagline")
        self._tagline.setWordWrap(True)
        layout.addWidget(self._tagline)
        self._body = QLabel(SUPPORTING_MESSAGE, self)
        self._body.setObjectName("tourWelcomeBody")
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._body)
        items_box = QVBoxLayout()
        items_box.setContentsMargins(0, 4, 0, 4)
        items_box.setSpacing(8)
        self._items: list[QLabel] = []
        for key in ("find", "meaning", "tags", "automation"):
            item = QLabel(f"• {t(f'tour.welcome.item.{key}')}", self)
            item.setObjectName("tourWelcomeItem")
            item.setWordWrap(True)
            items_box.addWidget(item)
            self._items.append(item)
        layout.addLayout(items_box)
        actions = QHBoxLayout()
        actions.addStretch(1)
        skip = QPushButton(t("tour.skip"), self)
        skip.setObjectName("tourSkipButton")
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(self.skip_clicked.emit)
        self._start = QPushButton(t("tour.start"), self)
        self._start.setObjectName("tourStartButton")
        self._start.setCursor(Qt.PointingHandCursor)
        self._start.clicked.connect(self.start_clicked.emit)
        actions.addWidget(skip)
        actions.addWidget(self._start)
        layout.addLayout(actions)

    def apply(self, guide: GuideView) -> None:
        self._title.setText(guide.title or t("tour.welcome.title"))
        self._body.setText(guide.body or t("tour.welcome.body"))
        if guide.mode == "auth":
            self._start.setText(t("tour.auth.sign_in"))
        else:
            self._start.setText(t("tour.start"))


class TourCompleteCard(QFrame):
    continue_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourWelcomeCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        apply_card_shadow(self, role="floating")
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        title = QLabel(t("tour.complete.title"), self)
        title.setObjectName("tourWelcomeTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        for key in ("find", "ask_ai", "automation"):
            row = QLabel(t(f"tour.complete.item.{key}"), self)
            row.setObjectName("tourCompleteItem")
            layout.addWidget(row)
        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton(t("tour.skip"), self)
        close.setObjectName("tourSkipButton")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close_clicked.emit)
        nxt = QPushButton(t("tour.feedback.continue"), self)
        nxt.setObjectName("tourStartButton")
        nxt.setCursor(Qt.PointingHandCursor)
        nxt.clicked.connect(self.continue_clicked.emit)
        actions.addWidget(close)
        actions.addWidget(nxt)
        layout.addLayout(actions)


class TourThanksCard(QFrame):
    continue_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourWelcomeCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        apply_card_shadow(self, role="floating")
        self.setFixedWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title = QLabel(t("tour.thanks.title"), self)
        title.setObjectName("tourWelcomeTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        actions = QHBoxLayout()
        actions.addStretch(1)
        nxt = QPushButton(t("tour.thanks.continue"), self)
        nxt.setObjectName("tourStartButton")
        nxt.setCursor(Qt.PointingHandCursor)
        nxt.clicked.connect(self.continue_clicked.emit)
        actions.addWidget(nxt)
        layout.addLayout(actions)


class TourFeedbackRadio(QRadioButton):
    """Exclusive choice with a visible checkmark when selected."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("tourFeedbackRadio")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumHeight(max(28, CONTROL_COMPACT))
        self.toggled.connect(self._sync_selected)
        self._sync_selected(self.isChecked())

    def _sync_selected(self, checked: bool) -> None:
        self.setProperty("selected", bool(checked))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(self.text()) if self.text() else 0
        width = CHECKBOX_SIZE + SPACE_2 + text_w + 16
        height = max(28, CONTROL_COMPACT, metrics.height() + 8)
        return QSize(width, height)

    def _indicator_rect(self) -> QRect:
        top = (self.height() - CHECKBOX_SIZE) // 2
        return QRect(8, top, CHECKBOX_SIZE, CHECKBOX_SIZE)

    def paintEvent(self, event) -> None:
        del event
        option = QStyleOptionButton()
        self.initStyleOption(option)
        hovered = bool(option.state & QStyle.State_MouseOver)
        pressed = bool(option.state & QStyle.State_Sunken)
        enabled = bool(option.state & QStyle.State_Enabled)
        focused = self.hasFocus() and not hovered
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if self.isChecked():
            painter.setPen(QColor(COLORS.target))
            painter.setBrush(QColor(COLORS.target_soft))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        indicator = self._indicator_rect()
        paint_checkbox_indicator(
            painter,
            indicator,
            checked=self.isChecked(),
            hovered=hovered,
            pressed=pressed,
            enabled=enabled,
            focused=focused,
        )
        if self.text():
            text_left = indicator.right() + 1 + SPACE_2
            text_rect = QRect(
                text_left,
                0,
                max(1, self.width() - text_left - 8),
                self.height(),
            )
            color = COLORS.text_strong if self.isChecked() else COLORS.text
            if not enabled:
                color = COLORS.text_faint
            painter.setPen(QColor(color))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


class TourFeedbackCard(QFrame):
    submitted = Signal(dict)
    skip_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourWelcomeCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        apply_card_shadow(self, role="floating")
        self.setFixedWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title = QLabel(t("tour.feedback.title"), self)
        title.setObjectName("tourWelcomeTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        self._useful_buttons: dict[str, QRadioButton] = {}
        self._useful = self._choice_group(
            layout, "tour.feedback.q1", MOST_USEFUL_CHOICES, "tour.feedback.useful",
            store=self._useful_buttons,
        )
        self._would = self._choice_group(
            layout, "tour.feedback.q2", WOULD_USE_CHOICES, "tour.feedback.would"
        )
        self._easier = self._choice_group(
            layout, "tour.feedback.q3", EASIER_CHOICES, "tour.feedback.easier"
        )
        confusing_label = QLabel(t("tour.feedback.q4"), self)
        confusing_label.setWordWrap(True)
        layout.addWidget(confusing_label)
        self._confusing = QLineEdit(self)
        self._confusing.setObjectName("tourFeedbackInput")
        self._confusing.setPlaceholderText(t("tour.feedback.q4.hint"))
        layout.addWidget(self._confusing)
        self._pay = self._choice_group(
            layout, "tour.feedback.q5", PAYMENT_CHOICES, "tour.feedback.pay"
        )

        actions = QHBoxLayout()
        skip = QPushButton(t("tour.feedback.exit"), self)
        skip.setObjectName("tourSkipButton")
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(self.skip_clicked.emit)
        send = QPushButton(t("tour.feedback.submit"), self)
        send.setObjectName("tourStartButton")
        send.setCursor(Qt.PointingHandCursor)
        send.clicked.connect(self._submit)
        actions.addWidget(skip)
        actions.addStretch(1)
        actions.addWidget(send)
        layout.addLayout(actions)

    def _choice_group(
        self,
        layout: QVBoxLayout,
        question_key: str,
        values: tuple[str, ...],
        label_prefix: str,
        store: dict[str, QRadioButton] | None = None,
    ) -> QButtonGroup:
        question = QLabel(t(question_key), self)
        question.setWordWrap(True)
        layout.addWidget(question)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, value in enumerate(values):
            button = TourFeedbackRadio(t(f"{label_prefix}.{value}"), self)
            button.setProperty("tourValue", value)
            group.addButton(button)
            grid.addWidget(button, index // 2, index % 2)
            if store is not None:
                store[value] = button
        layout.addLayout(grid)
        return group

    def apply(self, guide: GuideView) -> None:
        hidden = set(guide.hidden_feedback_choices)
        for value, button in self._useful_buttons.items():
            visible = value not in hidden
            button.setVisible(visible)
            if not visible and button.isChecked():
                button.setAutoExclusive(False)
                button.setChecked(False)
                button.setAutoExclusive(True)

    def _selected(self, group: QButtonGroup) -> str:
        button = group.checkedButton()
        if button is None:
            return ""
        return str(button.property("tourValue") or "")

    def _submit(self) -> None:
        self.submitted.emit(
            {
                "most_useful": self._selected(self._useful),
                "would_use": self._selected(self._would),
                "easier_than_current": self._selected(self._easier),
                "willingness_to_pay": self._selected(self._pay),
                "confusing_text": self._confusing.text(),
            }
        )


class TourChrome(QWidget):
    """Centered card host used for welcome / complete / feedback / thanks."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourChrome")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        self._welcome = TourWelcomeCard(self)
        self._complete = TourCompleteCard(self)
        self._feedback = TourFeedbackCard(self)
        self._feedback_scroll = QScrollArea(self)
        self._feedback_scroll.setObjectName("tourFeedbackScroll")
        self._feedback_scroll.setWidget(self._feedback)
        self._feedback_scroll.setWidgetResizable(True)
        self._feedback_scroll.setFrameShape(QFrame.NoFrame)
        self._feedback_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._feedback_scroll.setMaximumWidth(520)
        self._feedback_scroll.setAttribute(Qt.WA_StyledBackground, True)
        self._feedback_scroll.viewport().setAutoFillBackground(False)
        self._thanks = TourThanksCard(self)
        for card in (self._welcome, self._complete, self._feedback_scroll, self._thanks):
            layout.addWidget(card, 0, Qt.AlignHCenter)
            card.hide()
        layout.addStretch(1)
        parent.installEventFilter(self) if parent is not None else None
        self.hide()

    @property
    def welcome(self) -> TourWelcomeCard:
        return self._welcome

    @property
    def complete(self) -> TourCompleteCard:
        return self._complete

    @property
    def feedback(self) -> TourFeedbackCard:
        return self._feedback

    @property
    def thanks(self) -> TourThanksCard:
        return self._thanks

    def apply(self, guide: GuideView) -> None:
        mode = guide.mode
        cards = {
            "auth": self._welcome,
            "welcome": self._welcome,
            "complete": self._complete,
            "feedback": self._feedback_scroll,
            "thanks": self._thanks,
        }
        if mode not in cards:
            self.hide()
            return
        if mode in {"auth", "welcome"}:
            self._welcome.apply(guide)
        if mode == "feedback":
            self._feedback.apply(guide)
        shown = cards[mode]
        for card in (self._welcome, self._complete, self._feedback_scroll, self._thanks):
            card.setVisible(card is shown)
        self.show()
        self.raise_()
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            if mode == "feedback":
                available = max(240, parent.height() - 48)
                hint = self._feedback.sizeHint()
                self._feedback_scroll.setFixedWidth(min(520, max(hint.width(), 480)))
                self._feedback_scroll.setFixedHeight(min(hint.height() + 8, available))

    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent

        if watched is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(watched, event)
