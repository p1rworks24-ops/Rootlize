"""Centered searching state for the Images grid stack."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.i18n import t
from app.ui.design_tokens import COLORS
from app.ui.images_analysis import format_count


def format_searching_status(
    *,
    matches: int,
    checked: int | None = None,
    total: int | None = None,
) -> str:
    """Compact Meaning/Text search progress. Distinct from library preparation."""
    count = max(0, int(matches))
    if checked is not None and total is not None and int(total) > 0:
        return t(
            "images.search.status.progress",
            checked=format_count(checked),
            total=format_count(total),
            count=format_count(count),
        )
    if count:
        return t("images.search.status.searching_matches", count=format_count(count))
    return t("images.searching")


class SearchBusySpinner(QWidget):
    """Small charcoal arc spinner. Stops the timer when hidden."""

    def __init__(self, parent=None, *, size: int = 28) -> None:
        super().__init__(parent)
        self.setObjectName("searchBusySpinner")
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inset = 3
        rect = QRect(inset, inset, self.width() - inset * 2, self.height() - inset * 2)
        track = QPen(QColor(COLORS.border), 2.2)
        track.setCapStyle(Qt.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)
        arc = QPen(QColor(COLORS.text_muted), 2.2)
        arc.setCapStyle(Qt.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, int(self._angle * 16), 110 * 16)


class SearchBusyCard(QFrame):
    """Grid-area searching placeholder. Reuses empty-state typography."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("emptyHintCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(10)
        layout.addStretch(1)
        self._spinner = SearchBusySpinner(self)
        layout.addWidget(self._spinner, 0, Qt.AlignHCenter)
        self._title = QLabel(self)
        self._title.setObjectName("emptyHintTitle")
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)
        layout.addStretch(1)

    def set_message(self, text: str) -> None:
        self._title.setText(text)
