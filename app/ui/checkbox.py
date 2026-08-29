"""Capixe checkbox: empty square OFF, checked square ON. Not the OS control."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QStyle, QStyleOptionButton

from app.ui.design_tokens import (
    CHECKBOX_BORDER,
    CHECKBOX_BORDER_CHECKED,
    CHECKBOX_BORDER_HOVER,
    CHECKBOX_BORDER_PRESSED,
    CHECKBOX_CHECK,
    CHECKBOX_FILL,
    CHECKBOX_FILL_PRESSED,
    CHECKBOX_FOCUS,
    CHECKBOX_RADIUS,
    CHECKBOX_SIZE,
    COLORS,
    CONTROL_COMPACT,
    SPACE_2,
)


def paint_checkbox_indicator(
    painter: QPainter,
    dest: QRect,
    *,
    checked: bool,
    hovered: bool = False,
    pressed: bool = False,
    enabled: bool = True,
    focused: bool = False,
) -> None:
    """Draw □ when OFF and ☑ when ON, using Capixe tokens."""
    if dest.width() < 8 or dest.height() < 8:
        return
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    box = QRectF(dest).adjusted(0.5, 0.5, -0.5, -0.5)
    if pressed:
        fill = QColor(CHECKBOX_FILL_PRESSED)
        border = QColor(CHECKBOX_BORDER_PRESSED)
    elif checked:
        fill = QColor(CHECKBOX_FILL)
        border = QColor(CHECKBOX_BORDER_CHECKED)
    elif hovered:
        fill = QColor(CHECKBOX_FILL)
        border = QColor(CHECKBOX_BORDER_HOVER)
    else:
        fill = QColor(CHECKBOX_FILL)
        border = QColor(CHECKBOX_BORDER)
    if not enabled:
        fill.setAlpha(180)
        border.setAlpha(140)
    painter.setPen(QPen(border, 1.5))
    painter.setBrush(fill)
    painter.drawRoundedRect(box, CHECKBOX_RADIUS, CHECKBOX_RADIUS)
    if focused:
        painter.setPen(QPen(QColor(CHECKBOX_FOCUS), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box.adjusted(-2, -2, 2, 2), CHECKBOX_RADIUS + 1, CHECKBOX_RADIUS + 1)
    if checked:
        check = QColor(CHECKBOX_CHECK)
        if not enabled:
            check.setAlpha(160)
        painter.setPen(
            QPen(check, max(1.6, dest.width() * 0.13), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        x, y, w, h = box.x(), box.y(), box.width(), box.height()
        path.moveTo(x + w * 0.22, y + h * 0.52)
        path.lineTo(x + w * 0.42, y + h * 0.72)
        path.lineTo(x + w * 0.78, y + h * 0.28)
        painter.drawPath(path)
    painter.restore()


class CapixeCheckBox(QCheckBox):
    """QCheckBox with a Capixe-drawn indicator so ON/OFF is a visible ☑ / □."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"QCheckBox {{ background: transparent; color: {COLORS.text_secondary}; "
            "border: none; padding: 0; spacing: 0; }"
            "QCheckBox::indicator { width: 0; height: 0; border: none; }"
        )

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(self.text()) if self.text() else 0
        width = CHECKBOX_SIZE + (SPACE_2 + text_w if self.text() else 0)
        height = max(CONTROL_COMPACT, CHECKBOX_SIZE, metrics.height())
        return QSize(width + 2, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _indicator_rect(self) -> QRect:
        top = (self.height() - CHECKBOX_SIZE) // 2
        return QRect(1, top, CHECKBOX_SIZE, CHECKBOX_SIZE)

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
                max(1, self.width() - text_left),
                self.height(),
            )
            painter.setPen(QColor(COLORS.text_secondary if enabled else COLORS.text_faint))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()
