"""Short guide card placed near a spotlight target."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.prototype_tour.models import GuideView
from app.ui.design_tokens import apply_card_shadow

GUIDE_CARD_WIDTH = 380
GUIDE_CARD_MARGIN = 16


def clamp_rect(rect: QRect, bounds: QRect) -> QRect:
    moved = QRect(rect)
    if moved.right() > bounds.right():
        moved.moveRight(bounds.right())
    if moved.left() < bounds.left():
        moved.moveLeft(bounds.left())
    if moved.bottom() > bounds.bottom():
        moved.moveBottom(bounds.bottom())
    if moved.top() < bounds.top():
        moved.moveTop(bounds.top())
    return moved


def _shifted_below(hole: QRect, size: QSize, bounds: QRect, gap: int) -> QRect:
    card = QRect(hole.left(), hole.bottom() + gap, size.width(), size.height())
    if card.right() > bounds.right():
        card.moveRight(bounds.right())
    if card.left() < bounds.left():
        card.moveLeft(bounds.left())
    return card


def _shifted_left(hole: QRect, size: QSize, bounds: QRect, gap: int) -> QRect:
    card = QRect(hole.left() - gap - size.width(), hole.top(), size.width(), size.height())
    if card.top() < bounds.top():
        card.moveTop(bounds.top())
    if card.left() < bounds.left():
        card.moveLeft(bounds.left())
        if card.right() > hole.left() - gap:
            card.moveRight(max(bounds.left() + size.width(), hole.left() - gap))
            if card.left() < bounds.left():
                card.moveLeft(bounds.left())
    if card.bottom() > bounds.bottom() and card.top() > bounds.top():
        # Keep the card top-aligned so it does not slide over a bottom chat input.
        overflow = card.bottom() - bounds.bottom()
        card.translate(0, -min(overflow, card.top() - bounds.top()))
    return card


def _card_avoids_hole(card: QRect, hole: QRect | None) -> bool:
    return hole is None or hole.isEmpty() or not card.intersects(hole)


def _overlap_area(card: QRect, hole: QRect | None) -> int:
    if hole is None or hole.isEmpty() or not card.intersects(hole):
        return 0
    overlap = card.intersected(hole)
    return overlap.width() * overlap.height()


def popover_position(
    hole: QRect | None,
    size: QSize,
    bounds: QRect,
    *,
    gap: int = 14,
    placement: str = "",
) -> QPoint:
    card = QRect(0, 0, size.width(), size.height())
    if hole is None or hole.isEmpty():
        card.moveCenter(bounds.center())
        return clamp_rect(card, bounds).topLeft()
    below = _shifted_below(hole, size, bounds, gap)
    left = _shifted_left(hole, size, bounds, gap)
    right = QRect(hole.right() + gap, hole.top(), size.width(), size.height())
    above = QRect(hole.left(), hole.top() - gap - size.height(), size.width(), size.height())
    prefer_below = placement == "below" or (
        placement not in {"left", "above"} and hole.center().y() <= bounds.top() + 120
    )
    prefer_left = placement == "left" or (
        placement != "below"
        and hole.width() >= size.width()
        and hole.center().x() >= bounds.center().x()
    )
    ordered: list[QRect] = []
    if prefer_left:
        ordered.append(left)
        ordered.append(above)
    if prefer_below:
        ordered.append(below)
    if placement != "left":
        ordered.extend((right, below, left, above))
    else:
        ordered.extend((left, above, right))
    unique: list[QRect] = []
    seen: set[tuple[int, int, int, int]] = set()
    for candidate in ordered:
        key = (candidate.x(), candidate.y(), candidate.width(), candidate.height())
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if bounds.contains(candidate) and _card_avoids_hole(candidate, hole):
            return candidate.topLeft()
    best: QRect | None = None
    best_overlap: int | None = None
    for candidate in unique:
        clamped = clamp_rect(QRect(candidate), bounds)
        if _card_avoids_hole(clamped, hole):
            return clamped.topLeft()
        overlap = _overlap_area(clamped, hole)
        if best is None or overlap < best_overlap:
            best = clamped
            best_overlap = overlap
    return (best or clamp_rect(left if prefer_left else below, bounds)).topLeft()


def wrapped_text_height(label: QLabel, width: int) -> int:
    """Height needed to show every wrapped line. Does not clip to a fixed size."""
    if width <= 0:
        return 0
    text = label.text()
    if not text:
        return 0
    metrics = label.fontMetrics()
    flags = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop
    return metrics.boundingRect(0, 0, width, 10_000, flags, text).height()


class TourPopover(QFrame):
    back_clicked = Signal()
    next_clicked = Signal()
    skip_clicked = Signal()
    close_clicked = Signal()
    action_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        apply_card_shadow(self, role="floating")
        self.setFixedWidth(GUIDE_CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            GUIDE_CARD_MARGIN, 14, GUIDE_CARD_MARGIN, 14
        )
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._progress = QLabel(self)
        self._progress.setObjectName("tourProgress")
        header.addWidget(self._progress)
        header.addStretch(1)
        self._close = QPushButton("✕", self)
        self._close.setObjectName("tourCloseButton")
        self._close.setFixedSize(22, 22)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setToolTip(t("tour.skip"))
        self._close.setAutoDefault(False)
        self._close.setDefault(False)
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.clicked.connect(self._on_close_clicked)
        header.addWidget(self._close)
        layout.addLayout(header)

        self._dots = QLabel(self)
        self._dots.setObjectName("tourDots")
        layout.addWidget(self._dots)

        self._title = QLabel(self)
        self._title.setObjectName("tourTitle")
        self._title.setWordWrap(True)
        self._title.setTextFormat(Qt.PlainText)
        self._title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._title)

        self._body = QLabel(self)
        self._body.setObjectName("tourBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.PlainText)
        self._body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._body)

        self._hint = QLabel(self)
        self._hint.setObjectName("tourHint")
        self._hint.setWordWrap(True)
        self._hint.setTextFormat(Qt.PlainText)
        self._hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._hint)

        self._status = QLabel(self)
        self._status.setObjectName("tourStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.PlainText)
        self._status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self._status)

        for label in (self._title, self._body, self._hint, self._status):
            policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            label.setMinimumWidth(0)

        self._choice_box = QVBoxLayout()
        self._choice_box.setContentsMargins(0, 4, 0, 0)
        self._choice_box.setSpacing(8)
        layout.addLayout(self._choice_box)
        self._choice_buttons: list[QPushButton] = []

        self._nav_row = QWidget(self)
        nav = QHBoxLayout(self._nav_row)
        nav.setContentsMargins(0, 4, 0, 0)
        nav.setSpacing(8)
        self._skip = QPushButton(t("tour.skip"), self._nav_row)
        self._skip.setObjectName("tourSkipButton")
        self._skip.setCursor(Qt.PointingHandCursor)
        self._skip.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._skip.clicked.connect(self.skip_clicked.emit)
        self._back = QPushButton(t("tour.back"), self._nav_row)
        self._back.setObjectName("tourBackButton")
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.hide()
        self._next = QPushButton(t("tour.next"), self._nav_row)
        self._next.setObjectName("tourNextButton")
        self._next.setCursor(Qt.PointingHandCursor)
        self._next.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._next.clicked.connect(self.next_clicked.emit)
        nav.addWidget(self._skip)
        nav.addStretch(1)
        nav.addWidget(self._next)
        layout.addWidget(self._nav_row)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)

    def _on_close_clicked(self) -> None:
        self.close_clicked.emit()

    def content_width(self) -> int:
        margins = self.layout().contentsMargins()
        width = self.width() if self.width() > 0 else GUIDE_CARD_WIDTH
        return max(1, width - margins.left() - margins.right())

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        layout = self.layout()
        if layout is None:
            return super().sizeHint().height()
        inner = max(1, width - layout.contentsMargins().left() - layout.contentsMargins().right())
        self._constrain_wrap_width(inner)
        hinted = layout.heightForWidth(width)
        measured = self._measured_height(width)
        return max(hinted, measured)

    def sizeHint(self) -> QSize:
        width = self.width() if self.width() >= GUIDE_CARD_WIDTH else GUIDE_CARD_WIDTH
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def apply(self, guide: GuideView) -> None:
        if guide.phase:
            self._progress.setText(t(f"tour.phase.{guide.phase}"))
            self._progress.show()
            if guide.chapter_break or guide.total <= 1:
                self._dots.hide()
            else:
                self._dots.setText(_dot_text(guide.index, guide.total))
                self._dots.show()
        elif guide.index and guide.total:
            self._progress.setText(t("tour.progress", current=guide.index, total=guide.total))
            self._dots.setText(_dot_text(guide.index, guide.total))
            self._progress.show()
            self._dots.show()
        else:
            self._progress.hide()
            self._dots.hide()
        self._title.setText(guide.title)
        self._title.setVisible(bool(guide.title))
        self._body.setText(guide.body)
        self._body.setVisible(bool(guide.body))
        self._hint.setText(guide.hint)
        self._hint.setVisible(bool(guide.hint))
        self._status.setText(guide.status)
        self._status.setVisible(bool(guide.status))
        self._back.hide()
        self._next.setVisible(guide.show_next)
        self._next.setText(guide.next_label or t("tour.next"))
        next_text = self._next.text()
        next_width = self._next.fontMetrics().horizontalAdvance(next_text) + 36
        self._next.setMinimumWidth(next_width if guide.show_next else 0)
        self._skip.setVisible(guide.show_skip)
        self._nav_row.setVisible(guide.show_skip or guide.show_next)
        self._set_actions(guide.actions)
        self._fit_width_to_actions(guide)
        self._constrain_wrap_width(self.content_width())
        self.setMinimumHeight(0)
        self.updateGeometry()
        hint = self.sizeHint()
        self.setMinimumHeight(hint.height())
        self.resize(hint)

    def _fit_width_to_actions(self, guide: GuideView) -> None:
        skip_w = self._skip.sizeHint().width() if guide.show_skip else 0
        next_w = self._next.minimumWidth() if guide.show_next else 0
        row = skip_w + next_w + (8 if skip_w and next_w else 0)
        action_w = 0
        for button in self._choice_buttons:
            action_w = max(action_w, button.sizeHint().width())
        inner = max(row, action_w, 280)
        margins = self.layout().contentsMargins() if self.layout() is not None else None
        extra = (margins.left() + margins.right()) if margins is not None else 32
        self.setFixedWidth(max(GUIDE_CARD_WIDTH, inner + extra))

    def body_shows_full_text(self) -> bool:
        if not self._body.isVisible() or not self._body.text():
            return True
        needed = wrapped_text_height(self._body, self._body.width() or self.content_width())
        return self._body.height() >= needed

    def _is_shown(self, widget: QWidget) -> bool:
        return widget.isVisibleTo(self)

    def _measured_height(self, width: int) -> int:
        layout = self.layout()
        if layout is None:
            return 0
        margins = layout.contentsMargins()
        inner = max(1, width - margins.left() - margins.right())
        spacing = layout.spacing()
        height = margins.top() + margins.bottom()
        sections = 0
        if self._is_shown(self._progress) or self._is_shown(self._close):
            height += max(self._progress.sizeHint().height(), self._close.sizeHint().height())
            sections += 1
        if self._is_shown(self._dots):
            height += self._dots.sizeHint().height()
            sections += 1
        for label in (self._title, self._body, self._hint, self._status):
            if not self._is_shown(label):
                continue
            height += max(label.sizeHint().height(), wrapped_text_height(label, inner))
            sections += 1
        for button in self._choice_buttons:
            if self._is_shown(button):
                height += button.sizeHint().height()
                sections += 1
        if self._choice_buttons:
            height += 4
        if self._is_shown(self._nav_row) and (
            self._is_shown(self._skip) or self._is_shown(self._next)
        ):
            height += max(
                self._skip.sizeHint().height() if self._is_shown(self._skip) else 0,
                self._next.sizeHint().height() if self._is_shown(self._next) else 0,
                self._next.minimumSizeHint().height() if self._is_shown(self._next) else 0,
            ) + 4
            sections += 1
        if sections:
            height += spacing * max(0, sections - 1)
        return height

    def _constrain_wrap_width(self, inner: int) -> None:
        for label in (self._title, self._body, self._hint, self._status):
            label.setMaximumWidth(inner)
            if self._is_shown(label) and label.text():
                needed = wrapped_text_height(label, inner)
                label.setMinimumHeight(needed)
            else:
                label.setMinimumHeight(0)

    def _set_actions(self, actions: tuple[tuple[str, str], ...]) -> None:
        for button in self._choice_buttons:
            self._choice_box.removeWidget(button)
            button.deleteLater()
        self._choice_buttons = []
        single = len(actions) == 1
        for action_id, label in actions:
            button = QPushButton(label, self)
            button.setObjectName("tourNextButton" if single else "tourChoiceButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            button.clicked.connect(
                lambda checked=False, value=action_id: self.action_clicked.emit(value)
            )
            self._choice_box.addWidget(button)
            self._choice_buttons.append(button)


def _dot_text(index: int, total: int) -> str:
    parts = []
    for i in range(1, total + 1):
        parts.append("●" if i == index else "○")
    return "  ".join(parts)
