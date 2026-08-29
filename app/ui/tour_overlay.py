"""Highlight the live tour target. The rest of the UI stays undimmed."""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPoint, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QFrame, QWidget

from app.prototype_tour.anchors import AnchorRegistry, widget_rect_in
from app.prototype_tour.models import GuideView, TourView
from app.ui.design_tokens import COLORS, MOTION_SLOW_MS, RADIUS_MD
from app.ui.tour_popover import TourPopover, popover_position

RING = QColor(COLORS.target)
GLOW = QColor(37, 99, 235, 56)
HALO = QColor(37, 99, 235, 32)
INNER = QColor("#ffffff")
HOLE_PAD = 8


def spotlight_cutout_path(bounds: QRect, hole: QRect) -> QPainterPath:
    """Region outside the target. Used by tests; paint no longer fills this."""
    outside = QPainterPath()
    outside.addRect(QRectF(bounds))
    if hole.isEmpty():
        return outside
    cut = QPainterPath()
    cut.addRoundedRect(QRectF(hole), float(RADIUS_MD), float(RADIUS_MD))
    return outside.subtracted(cut)


def _halo_path(hole: QRect, spread: int) -> QPainterPath:
    outer = QPainterPath()
    outer.addRoundedRect(
        QRectF(hole).adjusted(-spread, -spread, spread, spread),
        float(RADIUS_MD + spread),
        float(RADIUS_MD + spread),
    )
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(hole), float(RADIUS_MD), float(RADIUS_MD))
    return outer.subtracted(inner)


def paint_tour_overlay(painter: QPainter, bounds: QRect, hole: QRect, pulse: float = 0.0) -> None:
    del bounds
    painter.setRenderHint(QPainter.Antialiasing, True)
    if hole.isEmpty():
        return
    wave = 0.5 + 0.5 * math.sin(pulse * 2 * math.pi)
    halo = QColor(HALO)
    halo.setAlpha(int(32 + 20 * wave))
    glow = QColor(GLOW)
    glow.setAlpha(int(56 + 28 * wave))
    spread = 8 + int(3 * wave)
    painter.setPen(Qt.NoPen)
    painter.setBrush(halo)
    painter.drawPath(_halo_path(hole, spread))
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(glow, 4))
    painter.drawRoundedRect(hole.adjusted(-3, -3, 3, 3), RADIUS_MD + 3, RADIUS_MD + 3)
    painter.setPen(QPen(RING, 2.5))
    painter.drawRoundedRect(hole, RADIUS_MD, RADIUS_MD)
    painter.setPen(QPen(INNER, 1.25))
    painter.drawRoundedRect(hole.adjusted(2, 2, -2, -2), max(4.0, RADIUS_MD - 2), max(4.0, RADIUS_MD - 2))


def click_block_region(bounds: QRect, hole: QRect, popover: QRect | None = None) -> QRegion:
    """Hit-test region that swallows clicks: backdrop minus hole minus guide card."""
    region = QRegion(bounds)
    if not hole.isEmpty():
        region = region.subtracted(QRegion(hole))
    if popover is not None and not popover.isEmpty():
        region = region.subtracted(QRegion(popover))
    return region


class TourClickShield(QWidget):
    """Blocks clicks outside the target. The hole and guide card are not in its mask."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tourClickShield")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def set_pass_through(self, hole: QRect, popover: QRect | None) -> None:
        self.setMask(click_block_region(self.rect(), hole, popover))

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()


class TourOverlay(QWidget):
    """Paint-only target highlight. Spotlight targets keep native mouse and keyboard input."""

    def __init__(self, parent: QWidget, anchors: AnchorRegistry) -> None:
        super().__init__(parent)
        self.setObjectName("tourOverlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)
        self._anchors = anchors
        self._hole = QRect()
        self._hole_target = QRect()
        self._spot_holes: list[QRect] = []
        self._pulse = 0.0
        self._view = TourView()
        self._shield = TourClickShield(parent)
        self._popover = TourPopover(parent)
        self._refresh_anchors = None
        self._follow = QTimer(self)
        self._follow.setInterval(80)
        self._follow.timeout.connect(self.refresh_geometry)
        self._hole_anim = QVariantAnimation(self)
        self._hole_anim.setDuration(MOTION_SLOW_MS)
        self._hole_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hole_anim.valueChanged.connect(self._on_hole_anim)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._on_pulse)
        parent.installEventFilter(self)
        self.hide()

    @property
    def popover(self) -> TourPopover:
        return self._popover

    @property
    def shield(self) -> TourClickShield:
        return self._shield

    def apply(self, view: TourView) -> None:
        self._view = view
        guide = view.guide
        if not view.active or not guide.visible or guide.mode != "guide":
            self._follow.stop()
            self._pulse_timer.stop()
            self._hole_anim.stop()
            self._popover.hide()
            self._shield.hide()
            self.hide()
            return
        self._popover.apply(guide)
        self._popover.show()
        self.show()
        self.raise_()
        self.refresh_geometry()
        if not self._follow.isActive():
            self._follow.start()
        if not self._pulse_timer.isActive():
            self._pulse_timer.start()

    def hole_rect(self) -> QRect:
        return QRect(self._hole_target if not self._hole_target.isEmpty() else self._hole)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parent() and event.type() in {QEvent.Resize, QEvent.Move}:
            self._sync_geometry()
            if self.isVisible():
                self.refresh_geometry()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_geometry()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_geometry()
        self._update_shield()
        self._restack()

    def hideEvent(self, event) -> None:
        self._follow.stop()
        self._pulse_timer.stop()
        self._hole_anim.stop()
        try:
            self._shield.hide()
        except RuntimeError:
            pass
        try:
            self._popover.hide()
        except RuntimeError:
            pass
        super().hideEvent(event)

    def raise_(self) -> None:
        super().raise_()
        if self.isVisible():
            self._restack()

    def refresh_geometry(self) -> None:
        self._sync_geometry()
        if callable(self._refresh_anchors):
            self._refresh_anchors()
        self._spot_holes = self._resolve_holes(self._view.guide)
        union = QRect()
        for rect in self._spot_holes:
            union = rect if union.isEmpty() else union.united(rect)
        self._set_hole_target(union)
        self._place_popover()
        self._update_shield()
        self.update()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        if self.geometry() != parent.rect():
            self.setGeometry(parent.rect())
        if self._shield.geometry() != parent.rect():
            self._shield.setGeometry(parent.rect())

    def _resolve_holes(self, guide: GuideView) -> list[QRect]:
        if getattr(guide, "highlight_all", False):
            found = self._anchors.visible_all(guide.anchors)
        else:
            first = self._anchors.first_visible(guide.anchors)
            found = [first] if first is not None else []
        rects: list[QRect] = []
        for _key, widget in found:
            rect = widget_rect_in(self, widget, pad=HOLE_PAD)
            if not rect.isEmpty():
                rects.append(rect)
        return rects

    def _resolve_hole(self, guide: GuideView) -> QRect:
        rects = self._resolve_holes(guide)
        if not rects:
            return QRect()
        union = QRect(rects[0])
        for rect in rects[1:]:
            union = union.united(rect)
        return union

    def _place_popover(self) -> None:
        hint = self._popover.sizeHint()
        self._popover.resize(hint)
        bounds = self.rect().adjusted(16, 16, -16, -16)
        target = self._hole_target if not self._hole_target.isEmpty() else self._hole
        hole = target if not target.isEmpty() else None
        origin = popover_position(
            hole,
            self._popover.size(),
            bounds,
            placement=getattr(self._view.guide, "placement", "") or "",
        )
        self._popover.move(origin)

    def _update_shield(self) -> None:
        guide = self._view.guide
        active = (
            self.isVisible()
            and self._view.active
            and guide.visible
            and guide.mode == "guide"
            and getattr(guide, "blocking", True)
        )
        if not active:
            self._shield.hide()
            return
        self._shield.show()
        popover = self._popover.geometry() if self._popover.isVisible() else None
        hole = self._hole_target if not self._hole_target.isEmpty() else self._hole
        self._shield.set_pass_through(hole, popover)

    def _set_hole_target(self, target: QRect) -> None:
        target = QRect(target)
        if target == self._hole_target:
            if self._hole_anim.state() != QAbstractAnimation.Running:
                self._hole = QRect(target)
            return
        previous = QRect(self._hole)
        self._hole_target = target
        far = (
            not previous.isEmpty()
            and not target.isEmpty()
            and (
                (previous.topLeft() - target.topLeft()).manhattanLength() > 8
                or abs(previous.width() - target.width()) > 8
                or abs(previous.height() - target.height()) > 8
            )
        )
        if not far or not self.isVisible():
            self._hole_anim.stop()
            self._hole = QRect(target)
            return
        self._hole_anim.stop()
        self._hole_anim.setStartValue(previous)
        self._hole_anim.setEndValue(target)
        self._hole_anim.start()

    def _on_hole_anim(self, value) -> None:
        if isinstance(value, QRect):
            self._hole = QRect(value)
            self.update()

    def _on_pulse(self) -> None:
        self._pulse = (self._pulse + 0.045) % 1.0
        if not self._hole.isEmpty() or self._spot_holes:
            self.update()

    def _restack(self) -> None:
        self._shield.raise_()
        self._popover.raise_()
        parent = self.parentWidget()
        if parent is None:
            return
        for popup in parent.findChildren(QFrame, "workflowAddBlockPopup"):
            if popup.isVisible():
                popup.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if len(self._spot_holes) > 1:
            holes = self._spot_holes
        elif not self._hole.isEmpty():
            holes = [self._hole]
        else:
            holes = self._spot_holes
        for hole in holes:
            paint_tour_overlay(painter, self.rect(), hole, self._pulse)

    def _in_hole(self, pos: QPoint) -> bool:
        for hole in self._spot_holes:
            if hole.contains(pos):
                return True
        hole = self._hole_target if not self._hole_target.isEmpty() else self._hole
        return not hole.isEmpty() and hole.contains(pos)

    def _in_popover(self, pos: QPoint) -> bool:
        return self._popover.isVisible() and self._popover.geometry().contains(pos)
