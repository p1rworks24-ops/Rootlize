"""Startup splash overlay — brand screen on top of the main window."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.branding import APP_NAME, DISPLAY_VERSION, RELEASE_CHANNEL, TAGLINE
from app.config import DEFAULT_CONFIG
from app.ui.app_icon import app_mark_pixmap

# Visible long enough to read brand + preview badge
SPLASH_MIN_MS = 2000

SPLASH_DEFAULT_WIDTH = int(DEFAULT_CONFIG["window_width"])
SPLASH_DEFAULT_HEIGHT = int(DEFAULT_CONFIG["window_height"])
SPLASH_SIZE = (SPLASH_DEFAULT_WIDTH, SPLASH_DEFAULT_HEIGHT)

# Large mark so the new icon reads clearly on HiDPI
_SPLASH_MARK_PX = 168


class SplashScreen(QWidget):
    """
    Full-client overlay on the main window (not a separate top-level window).

    Parent should be MainWindow.centralWidget() so splash and app share one
    native window footprint.
    """

    finished = Signal()

    def __init__(self, host: QWidget, parent=None):
        super().__init__(parent or host)
        self._host = host
        self.setObjectName("splashScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._ready = False
        self._min_elapsed = False
        self._closing = False
        self._dot_index = 0
        self._dot_timer: QTimer | None = None
        self._finish_timer: QTimer | None = None

        self._build_ui()
        self._sync_to_host()
        host.installEventFilter(self)
        self.raise_()
        self.show()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("splashCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(48, 40, 48, 40)
        lay.setSpacing(0)
        lay.addStretch(2)

        logo = QLabel(card)
        logo.setObjectName("splashLogo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(_SPLASH_MARK_PX + 8, _SPLASH_MARK_PX + 8)
        logo.setPixmap(app_mark_pixmap(_SPLASH_MARK_PX))
        lay.addWidget(logo, 0, Qt.AlignHCenter)

        lay.addSpacing(22)

        title = QLabel(APP_NAME, card)
        title.setObjectName("splashTitle")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont(title.font())
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        lay.addWidget(title)

        lay.addSpacing(8)
        tagline = QLabel(TAGLINE, card)
        tagline.setObjectName("splashTagline")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        lay.addWidget(tagline)

        lay.addSpacing(18)
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        badge_row.addStretch(1)
        channel = QLabel(RELEASE_CHANNEL, card)
        channel.setObjectName("splashChannel")
        channel.setAlignment(Qt.AlignCenter)
        badge_row.addWidget(channel)
        badge = QLabel(DISPLAY_VERSION, card)
        badge.setObjectName("splashBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        lay.addLayout(badge_row)

        lay.addSpacing(32)
        dots_row = QHBoxLayout()
        dots_row.setSpacing(8)
        dots_row.addStretch(1)
        self._dots: list[QLabel] = []
        for _ in range(3):
            dot = QLabel(card)
            dot.setObjectName("splashDot")
            dot.setFixedSize(8, 8)
            dots_row.addWidget(dot)
            self._dots.append(dot)
        dots_row.addStretch(1)
        lay.addLayout(dots_row)
        lay.addStretch(3)
        root.addWidget(card)

        self.setStyleSheet(
            """
            QWidget#splashScreen {
                background-color: #f5f6f8;
            }
            QFrame#splashCard {
                background-color: #f5f6f8;
                border: none;
            }
            QLabel#splashLogo {
                background: transparent;
                border: none;
            }
            QLabel#splashTitle {
                color: #111827;
                letter-spacing: -0.4px;
            }
            QLabel#splashTagline {
                color: #1d4ed8;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#splashChannel {
                color: #1e40af;
                background-color: #eff6ff;
                border: 1px solid #bfdbfe;
                border-radius: 10px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#splashBadge {
                color: #0f766e;
                background-color: #f0fdfa;
                border: 1px solid #99f6e4;
                border-radius: 10px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#splashDot {
                background-color: #dbeafe;
                border-radius: 4px;
            }
            QLabel#splashDot[on="true"] {
                background-color: #2563eb;
            }
            """
        )

    def eventFilter(self, obj, event) -> bool:
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self._sync_to_host()
        return super().eventFilter(obj, event)

    def _sync_to_host(self) -> None:
        if self._host is None:
            return
        self.setGeometry(self._host.rect())
        self.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_to_host()
        if self._dot_timer is None:
            self._dot_timer = QTimer(self)
            self._dot_timer.setInterval(380)
            self._dot_timer.timeout.connect(self._tick_dots)
            self._dot_timer.start()
        QTimer.singleShot(SPLASH_MIN_MS, self._on_min_elapsed)

    def _tick_dots(self) -> None:
        for i, dot in enumerate(self._dots):
            on = i == self._dot_index % len(self._dots)
            dot.setProperty("on", on)
            style = dot.style()
            if style is not None:
                style.unpolish(dot)
                style.polish(dot)
        self._dot_index += 1

    def notify_ready(self) -> None:
        self._ready = True
        self._try_finish()

    def _on_min_elapsed(self) -> None:
        self._min_elapsed = True
        self._try_finish()

    def _try_finish(self) -> None:
        if self._closing or not (self._ready and self._min_elapsed):
            return
        self._closing = True
        self._begin_exit()

    def _begin_exit(self) -> None:
        self._stop_dot_timer()
        # Brief pause so the last frame is readable, then reveal the app
        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.timeout.connect(self._emit_finished)
        self._finish_timer.start(180)

    def _emit_finished(self) -> None:
        self._stop_dot_timer()
        if self._finish_timer is not None:
            self._finish_timer.stop()
            self._finish_timer = None
        host = self._host
        if host is not None:
            host.removeEventFilter(self)
        self._host = None
        self.finished.emit()
        self.hide()
        # Do not deleteLater here — parent teardown owns lifetime in app;
        # tests call close() explicitly.

    def _stop_dot_timer(self) -> None:
        if self._dot_timer is not None:
            self._dot_timer.stop()
            self._dot_timer = None

    def closeEvent(self, event) -> None:
        self._closing = True
        self._stop_dot_timer()
        if self._finish_timer is not None:
            self._finish_timer.stop()
            self._finish_timer = None
        if self._host is not None:
            self._host.removeEventFilter(self)
            self._host = None
        super().closeEvent(event)
