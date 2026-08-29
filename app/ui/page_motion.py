"""Page and stack transitions. Index changes stay synchronous for tests."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Property, QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QStackedWidget, QWidget

from app.ui.design_tokens import COLORS, MOTION_NORMAL_MS

_FADE_ATTR = "_capixe_page_fade"
_WINDOW_FADE_ATTR = "_capixe_window_fade"


def motion_preferred() -> bool:
    """Honor OS / env reduced-motion. Default is to animate."""
    if "pytest" in sys.modules:
        return True
    flag = str(os.environ.get("CAPIXE_REDUCED_MOTION", "")).strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
        return bool(enabled.value)
    except Exception:
        return True


def _skip_window_fade() -> bool:
    return (not motion_preferred()) or ("pytest" in sys.modules)


def opaque_grab(widget: QWidget, fill: str | None = None) -> QPixmap:
    """Grab a widget with transparent holes filled with the canvas color."""
    snap = widget.grab()
    if snap.isNull():
        return snap
    painted = QPixmap(snap.size())
    painted.setDevicePixelRatio(snap.devicePixelRatio())
    painted.fill(QColor(fill or COLORS.app_bg))
    painter = QPainter(painted)
    painter.drawPixmap(0, 0, snap)
    painter.end()
    return painted


def stop_page_fade(host: QWidget) -> None:
    previous = getattr(host, _FADE_ATTR, None)
    if not isinstance(previous, dict):
        return
    anim = previous.get("anim")
    overlay = previous.get("overlay")
    if anim is not None:
        anim.stop()
    if overlay is not None:
        overlay.hide()
        overlay.deleteLater()
    setattr(host, _FADE_ATTR, None)


def active_page_fade(host: QWidget) -> dict | None:
    held = getattr(host, _FADE_ATTR, None)
    return held if isinstance(held, dict) else None


class _SnapshotOverlay(QWidget):
    """Opaque canvas + fading pixmap. Avoids QGraphicsOpacityEffect on Windows."""

    def __init__(self, host: QWidget, snapshot: QPixmap, fill: str) -> None:
        super().__init__(host)
        self._snapshot = snapshot
        self._fill = QColor(fill)
        self._opacity = 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

    def getFade(self) -> float:
        return self._opacity

    def setFade(self, value: float) -> None:
        self._opacity = max(0.0, min(1.0, float(value)))
        self.update()

    fade = Property(float, getFade, setFade)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self._fill)
        if not self._snapshot.isNull() and self._opacity > 0:
            painter.setOpacity(self._opacity)
            painter.drawPixmap(self.rect(), self._snapshot)


def _overlay_host(widget: QWidget) -> tuple[QWidget, QRect]:
    """Do not parent overlays to QStackedWidget — Qt promotes children into pages."""
    parent = widget.parentWidget()
    while isinstance(parent, QStackedWidget):
        parent = parent.parentWidget()
    if parent is None:
        return widget, widget.rect()
    origin = widget.mapTo(parent, QPoint(0, 0))
    return parent, QRect(origin, widget.size())


def fade_outgoing_snapshot(
    host: QWidget,
    snapshot: QPixmap | None,
    *,
    duration_ms: int = MOTION_NORMAL_MS,
) -> None:
    """Cover *host* with an opaque snapshot, then fade it to the page underneath."""
    if (
        snapshot is None
        or snapshot.isNull()
        or not host.isVisible()
        or host.width() <= 1
        or host.height() <= 1
        or not motion_preferred()
        or host.parentWidget() is None
    ):
        return
    stop_page_fade(host)
    parent, geometry = _overlay_host(host)
    if isinstance(parent, QStackedWidget):
        return
    overlay = _SnapshotOverlay(parent, snapshot, COLORS.app_bg)
    overlay.setGeometry(geometry)
    overlay.show()
    overlay.raise_()

    fade_out = QPropertyAnimation(overlay, b"fade", host)
    fade_out.setDuration(int(duration_ms))
    fade_out.setStartValue(1.0)
    fade_out.setEndValue(0.0)
    fade_out.setEasingCurve(QEasingCurve.OutCubic)

    payload = {"anim": fade_out, "overlay": overlay}
    setattr(host, _FADE_ATTR, payload)

    def _finish() -> None:
        held = getattr(host, _FADE_ATTR, None)
        if held is not payload:
            return
        overlay.hide()
        overlay.deleteLater()
        setattr(host, _FADE_ATTR, None)

    fade_out.finished.connect(_finish)
    fade_out.start()


def show_only_stack_page(stack: QStackedWidget, target: QWidget) -> None:
    stack.setCurrentWidget(target)
    for index in range(stack.count()):
        page = stack.widget(index)
        if page is None:
            continue
        page.setVisible(page is target)
    if target is not None:
        target.raise_()
        target.update()


def crossfade_stacked(
    stack: QStackedWidget,
    target: QWidget,
    *,
    duration_ms: int = MOTION_NORMAL_MS,
) -> None:
    """Switch immediately under an outgoing snapshot fade. Live pages stay opaque."""
    current = stack.currentWidget()
    if current is target:
        show_only_stack_page(stack, target)
        return
    animate = (
        motion_preferred()
        and current is not None
        and stack.isVisible()
        and target is not None
        and stack.width() > 1
        and stack.height() > 1
        and stack.parentWidget() is not None
    )
    snapshot = opaque_grab(current) if animate else None
    if animate:
        fade_outgoing_snapshot(stack, snapshot, duration_ms=duration_ms)
    show_only_stack_page(stack, target)


def fade_in_window(
    window: QWidget,
    *,
    duration_ms: int = MOTION_NORMAL_MS,
) -> None:
    """Fade a top-level dialog or popup via windowOpacity (safe on Windows)."""
    if _skip_window_fade() or window is None:
        return
    previous = getattr(window, _WINDOW_FADE_ATTR, None)
    if previous is not None:
        previous.stop()
    window.setWindowOpacity(0.0)
    anim = QPropertyAnimation(window, b"windowOpacity", window)
    anim.setDuration(int(duration_ms))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    setattr(window, _WINDOW_FADE_ATTR, anim)

    def _finish() -> None:
        window.setWindowOpacity(1.0)
        setattr(window, _WINDOW_FADE_ATTR, None)

    anim.finished.connect(_finish)
    anim.start()


class AnimatedDialog(QDialog):
    """Modal dialog that eases in without QGraphicsOpacityEffect."""

    def showEvent(self, event) -> None:
        super().showEvent(event)
        fade_in_window(self)
