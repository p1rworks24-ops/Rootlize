"""App-owned floating toast (not Windows Notification Center).

Designed for save success / failure today; future action buttons can plug into
ToastPayload.actions without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.ui.styles import APP_STYLE


class ToastKind(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ToastAction:
    """Optional future action (Open image, Reveal in Explorer, …)."""

    id: str
    label: str


@dataclass
class ToastPayload:
    kind: ToastKind
    title: str
    body_lines: list[str] = field(default_factory=list)
    actions: list[ToastAction] = field(default_factory=list)
    duration_ms: int = 3000


class FloatingToast(QWidget):
    """Single toast card — Win11-like, always-on-top, no notification history."""

    dismissed = Signal()
    action_triggered = Signal(str)

    MARGIN = 16
    TOAST_WIDTH = 320

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("floatingToast")
        # Independent overlay: must not raise / activate the main app window
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_X11DoNotAcceptFocus, True)
        self.setFixedWidth(self.TOAST_WIDTH)
        self.setCursor(Qt.PointingHandCursor)

        self._duration_ms = 3000
        self._remaining_ms = 3000
        self._paused = False
        self._closing = False

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._on_auto_timeout)

        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._on_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("floatingToastCard")
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self._accent = QFrame(self._card)
        self._accent.setObjectName("floatingToastAccent")
        self._accent.setFixedWidth(4)
        card_layout.addWidget(self._accent)

        body = QWidget(self._card)
        body.setObjectName("floatingToastBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 8, 10)
        body_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._icon_label = QLabel(body)
        self._icon_label.setObjectName("floatingToastIcon")
        title_row.addWidget(self._icon_label, 0, Qt.AlignTop)

        self._title_label = QLabel(body)
        self._title_label.setObjectName("floatingToastTitle")
        self._title_label.setWordWrap(True)
        title_row.addWidget(self._title_label, 1, Qt.AlignVCenter)

        self._close_btn = QPushButton("✕", body)
        self._close_btn.setObjectName("floatingToastClose")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.clicked.connect(self.dismiss_now)
        title_row.addWidget(self._close_btn, 0, Qt.AlignTop)
        body_layout.addLayout(title_row)

        self._lines_host = QWidget(body)
        self._lines_layout = QVBoxLayout(self._lines_host)
        self._lines_layout.setContentsMargins(22, 2, 4, 0)
        self._lines_layout.setSpacing(2)
        body_layout.addWidget(self._lines_host)

        # Slot for future action buttons
        self._actions_host = QWidget(body)
        self._actions_layout = QHBoxLayout(self._actions_host)
        self._actions_layout.setContentsMargins(22, 6, 4, 0)
        self._actions_layout.setSpacing(6)
        self._actions_host.hide()
        body_layout.addWidget(self._actions_host)

        card_layout.addWidget(body, 1)
        root.addWidget(self._card)

        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(15, 23, 42, 55))
        self._card.setGraphicsEffect(shadow)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setEasingCurve(QEasingCurve.InOutCubic)

    def apply_payload(self, payload: ToastPayload) -> None:
        self._closing = False
        self._duration_ms = max(500, int(payload.duration_ms))
        self._remaining_ms = self._duration_ms
        self._paused = False

        kind = payload.kind.value
        self._card.setProperty("kind", kind)
        self._accent.setProperty("kind", kind)
        for widget in (self._card, self._accent):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self._icon_label.setText("✔" if payload.kind == ToastKind.SUCCESS else "✖")
        self._title_label.setText(payload.title)

        while self._lines_layout.count():
            item = self._lines_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for line in payload.body_lines:
            lab = QLabel(line, self._lines_host)
            lab.setObjectName("floatingToastLine")
            lab.setWordWrap(True)
            self._lines_layout.addWidget(lab)

        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if payload.actions:
            self._actions_host.show()
            for action in payload.actions:
                btn = QPushButton(action.label, self._actions_host)
                btn.setObjectName("floatingToastAction")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, aid=action.id: self.action_triggered.emit(aid)
                )
                self._actions_layout.addWidget(btn)
            self._actions_layout.addStretch(1)
        else:
            self._actions_host.hide()

        self.adjustSize()
        self._place_bottom_right()

    def present(self) -> None:
        """Show with fade-in and start auto-dismiss timer."""
        self._closing = False
        self._fade.stop()
        self._place_bottom_right()
        # ShowWithoutActivating: toast only — never front the main window
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.show()
        self.raise_()
        self._fade.setDuration(180)
        self._fade.setStartValue(max(self._opacity.opacity(), 0.0))
        self._fade.setEndValue(0.95)
        self._fade.start()
        self._start_timers()

    def dismiss_now(self) -> None:
        """Close immediately (fade-out)."""
        if self._closing:
            return
        self._closing = True
        self._stop_timers()
        self._fade.stop()
        start = self._opacity.opacity()

        def _hide() -> None:
            if not self.isVisible():
                return
            self._opacity.setOpacity(0.0)
            self.hide()
            self.dismissed.emit()

        if start <= 0.05:
            _hide()
            return

        self._fade.setDuration(160)
        self._fade.setStartValue(start)
        self._fade.setEndValue(0.0)
        # One-shot: animation end, plus fallback for environments that skip anim
        self._fade.finished.connect(_hide, Qt.SingleShotConnection)
        self._fade.start()
        QTimer.singleShot(220, _hide)

    def _start_timers(self) -> None:
        self._stop_timers()
        self._auto_timer.start(self._remaining_ms)
        self._tick.start()

    def _stop_timers(self) -> None:
        self._auto_timer.stop()
        self._tick.stop()

    def _on_tick(self) -> None:
        if self._paused or self._closing:
            return
        self._remaining_ms = max(0, self._remaining_ms - self._tick.interval())

    def _on_auto_timeout(self) -> None:
        if not self._paused:
            self.dismiss_now()

    def _place_bottom_right(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail: QRect = screen.availableGeometry()
        self.adjustSize()
        x = avail.right() - self.width() - self.MARGIN + 1
        y = avail.bottom() - self.height() - self.MARGIN
        self.move(
            QPoint(
                max(avail.left() + self.MARGIN, x),
                max(avail.top() + self.MARGIN, y),
            )
        )

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        if self._closing:
            return
        self._paused = True
        if self._auto_timer.isActive():
            self._remaining_ms = max(self._auto_timer.remainingTime(), 0)
        self._auto_timer.stop()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        if self._closing:
            return
        self._paused = False
        if self._remaining_ms > 0:
            self._auto_timer.start(self._remaining_ms)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            local = event.position().toPoint()
            close_geo = self._close_btn.geometry()
            # Map close button rect into toast coordinates
            top_left = self._close_btn.mapTo(self, close_geo.topLeft())
            close_rect = close_geo.translated(top_left - close_geo.topLeft())
            if close_rect.contains(local):
                super().mousePressEvent(event)
                return
            self.dismiss_now()
            event.accept()
            return
        super().mousePressEvent(event)


class FloatingToastHost(QObject):
    """Owns at most one visible toast. New notifications replace the current one."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._toast = FloatingToast()
        self._toast.setStyleSheet(APP_STYLE)
        self._toast.dismissed.connect(self._on_dismissed)

    def shutdown(self) -> None:
        self._toast._stop_timers()
        self._toast.hide()
        self._toast.close()

    def show_success(
        self,
        *,
        filename: str,
        folder: str,
        duration_ms: int = 3000,
    ) -> None:
        self._show(
            ToastPayload(
                kind=ToastKind.SUCCESS,
                title=t("toast.save_success_title"),
                body_lines=[
                    filename,
                    t("toast.folder_line", name=folder),
                ],
                duration_ms=duration_ms,
            )
        )

    def show_error(self, *, message: str, duration_ms: int = 3000) -> None:
        self._show(
            ToastPayload(
                kind=ToastKind.ERROR,
                title=t("toast.save_failed_title"),
                body_lines=[message],
                duration_ms=duration_ms,
            )
        )

    def _show(self, payload: ToastPayload) -> None:
        self._toast._stop_timers()
        self._toast._fade.stop()
        self._toast.apply_payload(payload)
        self._toast.present()

    def _on_dismissed(self) -> None:
        return
