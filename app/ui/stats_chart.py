"""Reusable horizontal bar chart for Home stats (Qt-only, no extra deps)."""

from __future__ import annotations

import hashlib

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.utils.workspace_stats import StatBar, format_bytes

# Leave headroom so the longest bar never fills the track (easier comparison)
_MAX_BAR_RATIO = 0.72
# Segoe MDL2 / Fluent folder glyph (same as app folder icons)
_FOLDER_GLYPH = "\uE8B7"

# Distinct, readable accents — one stable color per label (folder / tag)
_CHART_PALETTE = (
    "#2563eb",  # blue
    "#059669",  # emerald
    "#d97706",  # amber
    "#db2777",  # pink
    "#7c3aed",  # violet
    "#0891b2",  # cyan
    "#ea580c",  # orange
    "#4f46e5",  # indigo
    "#16a34a",  # green
    "#e11d48",  # rose
    "#0d9488",  # teal
    "#9333ea",  # purple
)


def color_for_label(label: str) -> QColor:
    """Stable per-label color so the same folder/tag always matches."""
    key = (label or "").strip().casefold().encode("utf-8")
    digest = hashlib.md5(key).hexdigest()
    index = int(digest[:8], 16) % len(_CHART_PALETTE)
    return QColor(_CHART_PALETTE[index])


class HorizontalBarChart(QWidget):
    """Horizontal bars with a color swatch matching each bar."""

    BAR_HEIGHT = 12
    ROW_GAP = 16
    LABEL_HEIGHT = 18
    META_HEIGHT = 16
    LEFT_PAD = 4
    RIGHT_PAD = 8
    SWATCH_SIZE = 10
    SWATCH_GAP = 8
    TRACK = QColor("#e5e7eb")
    LABEL = QColor("#111827")
    META = QColor("#6b7280")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[StatBar] = []
        self._label_prefix = ""
        self._leading = "swatch"  # "swatch" | "folder"
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_rows(
        self,
        rows: list[StatBar],
        *,
        label_prefix: str = "",
        leading: str = "swatch",
    ) -> None:
        self._rows = list(rows)
        self._label_prefix = label_prefix
        self._leading = leading if leading in ("swatch", "folder") else "swatch"
        content_h = self.sizeHint().height()
        self.setMinimumHeight(content_h)
        self.setFixedHeight(content_h)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        if not self._rows:
            return QSize(320, 80)
        h = 16 + len(self._rows) * (
            self.LABEL_HEIGHT + self.BAR_HEIGHT + self.META_HEIGHT + self.ROW_GAP
        )
        return QSize(320, max(80, h))

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
        y = 4.0

        label_font = QFont(painter.font())
        label_font.setWeight(QFont.Weight.DemiBold)
        label_font.setPointSize(max(label_font.pointSize(), 10))
        meta_font = QFont(painter.font())
        meta_font.setPointSize(max(meta_font.pointSize() - 1, 8))

        for row in self._rows:
            accent = (
                QColor(row.accent)
                if row.accent
                else color_for_label(row.label)
            )
            label = (
                f"{self._label_prefix}{row.label}"
                if self._label_prefix and row.apply_prefix
                else row.label
            )

            lead_w = float(self.SWATCH_SIZE)
            swatch_y = y + (self.LABEL_HEIGHT - self.SWATCH_SIZE) / 2.0
            if self._leading == "folder":
                # Folder icon before folder name (Fluent glyph)
                icon_font = QFont("Segoe Fluent Icons")
                if not icon_font.exactMatch():
                    icon_font = QFont("Segoe MDL2 Assets")
                icon_font.setPixelSize(self.SWATCH_SIZE + 4)
                painter.setFont(icon_font)
                painter.setPen(accent)
                painter.drawText(
                    QRectF(
                        self.LEFT_PAD,
                        y,
                        self.SWATCH_SIZE + 4,
                        self.LABEL_HEIGHT,
                    ),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    _FOLDER_GLYPH,
                )
                lead_w = float(self.SWATCH_SIZE + 4)
            else:
                # Color swatch before the name (same hue as the bar)
                painter.setPen(Qt.NoPen)
                painter.setBrush(accent)
                painter.drawRoundedRect(
                    QRectF(self.LEFT_PAD, swatch_y, self.SWATCH_SIZE, self.SWATCH_SIZE),
                    3,
                    3,
                )

            text_x = self.LEFT_PAD + lead_w + self.SWATCH_GAP
            painter.setFont(label_font)
            painter.setPen(self.LABEL)
            painter.drawText(
                QRectF(
                    text_x,
                    y,
                    max(20.0, width - (text_x - self.LEFT_PAD)),
                    self.LABEL_HEIGHT,
                ),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )
            y += self.LABEL_HEIGHT + 2

            track = QRectF(self.LEFT_PAD, y, width, self.BAR_HEIGHT)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.TRACK)
            painter.drawRoundedRect(track, 4, 4)

            frac = (row.count / max_count) * _MAX_BAR_RATIO if max_count else 0.0
            bar_w = max(6.0, width * frac) if row.count else 0.0
            if bar_w:
                painter.setBrush(accent)
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
    """
    Chart host for Home (and future AI/OCR stats).

    Grows with the number of rows; scrolling is left to the page, not the chart.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statsChartPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._chart = HorizontalBarChart(self)
        layout.addWidget(self._chart)

    def set_rows(
        self,
        rows: list[StatBar],
        *,
        label_prefix: str = "",
        leading: str = "swatch",
    ) -> None:
        self._chart.set_rows(rows, label_prefix=label_prefix, leading=leading)
        self.updateGeometry()
