"""Reusable horizontal bar chart for Home stats (Qt-only, no extra deps)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from app.utils.workspace_stats import StatBar, format_bytes

# Leave headroom so the longest bar never fills the track (easier comparison)
_MAX_BAR_RATIO = 0.72


class HorizontalBarChart(QWidget):
    """Simple Notion/Explorer-like horizontal bars with readable proportions."""

    BAR_HEIGHT = 12
    ROW_GAP = 16
    LABEL_HEIGHT = 18
    META_HEIGHT = 16
    LEFT_PAD = 4
    RIGHT_PAD = 8
    ACCENT = QColor("#2563eb")
    TRACK = QColor("#e5e7eb")
    LABEL = QColor("#111827")
    META = QColor("#6b7280")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[StatBar] = []
        self._label_prefix = ""
        self.setMinimumHeight(120)
        # Preferred height = content height so the parent scroll area can clip
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_rows(self, rows: list[StatBar], *, label_prefix: str = "") -> None:
        self._rows = list(rows)
        self._label_prefix = label_prefix
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        h = 24 + len(self._rows) * (
            self.LABEL_HEIGHT + self.BAR_HEIGHT + self.META_HEIGHT + self.ROW_GAP
        )
        return QSize(320, max(160, h))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self._rows:
            painter.setPen(self.META)
            painter.drawText(self.rect(), Qt.AlignCenter, "—")
            painter.end()
            return

        max_count = max((r.count for r in self._rows), default=1) or 1
        width = max(40.0, self.width() - self.LEFT_PAD - self.RIGHT_PAD)
        y = 8.0

        label_font = QFont(painter.font())
        label_font.setBold(True)
        label_font.setPointSize(max(label_font.pointSize(), 10))
        meta_font = QFont(painter.font())
        meta_font.setPointSize(max(meta_font.pointSize() - 1, 8))

        for row in self._rows:
            label = (
                f"{self._label_prefix}{row.label}"
                if self._label_prefix
                else row.label
            )
            painter.setFont(label_font)
            painter.setPen(self.LABEL)
            painter.drawText(
                QRectF(self.LEFT_PAD, y, width, self.LABEL_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )
            y += self.LABEL_HEIGHT + 2

            track = QRectF(self.LEFT_PAD, y, width, self.BAR_HEIGHT)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.TRACK)
            painter.drawRoundedRect(track, 4, 4)

            # Scale against max with headroom so differences stay visible
            frac = (row.count / max_count) * _MAX_BAR_RATIO if max_count else 0.0
            bar_w = max(6.0, width * frac) if row.count else 0.0
            if bar_w:
                painter.setBrush(self.ACCENT)
                painter.drawRoundedRect(
                    QRectF(self.LEFT_PAD, y, bar_w, self.BAR_HEIGHT), 4, 4
                )
            y += self.BAR_HEIGHT + 2

            painter.setFont(meta_font)
            painter.setPen(self.META)
            meta = f"{row.count} images  ·  {format_bytes(row.bytes_total)}"
            painter.drawText(
                QRectF(self.LEFT_PAD, y, width, self.META_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                meta,
            )
            y += self.META_HEIGHT + self.ROW_GAP

        painter.end()


class StatsChartPanel(QWidget):
    """Scrollable chart host used by Home (and future AI/OCR stats)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statsChartPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._chart = HorizontalBarChart(self._scroll)
        self._scroll.setWidget(self._chart)
        layout.addWidget(self._scroll)

    def set_rows(self, rows: list[StatBar], *, label_prefix: str = "") -> None:
        self._chart.set_rows(rows, label_prefix=label_prefix)
        # Lock content height so the viewport scrolls instead of clipping rows
        content_h = self._chart.sizeHint().height()
        self._chart.setMinimumHeight(content_h)
        self._chart.updateGeometry()
        self._scroll.updateGeometry()
