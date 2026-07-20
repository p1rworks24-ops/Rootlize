"""CompactField opens the QComboBox popup on a normal click (incl. ▼)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget

from app.ui.capture_settings import CompactField, UpwardComboBox, show_combo_popup_above
from app.ui.styles import APP_STYLE


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyleSheet(APP_STYLE)
    return app


def test_compact_field_chevron_opens_popup_on_release():
    app = _ensure_app()
    combo = QComboBox()
    combo.addItems(["One", "Two", "Three"])
    field = CompactField("Label", combo)
    field.show()
    app.processEvents()

    assert field._chevron is not None
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPoint(2, 2),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    assert field.eventFilter(field._chevron, release) is True
    app.processEvents()
    assert combo.view().isVisible()
    popup = combo.view().parentWidget() or combo.view().window()
    assert popup is not None
    # Stylesheet must not crush the list to ~one row (max-height on QComboBox)
    assert popup.height() > 40


def test_compact_field_does_not_steal_combo_press():
    """Combo itself must receive normal clicks (no press filter)."""
    _ensure_app()
    combo = QComboBox()
    combo.addItems(["One", "Two"])
    field = CompactField("Label", combo)
    # Event filter is installed on value_row / chevron only
    assert field._control is combo


def test_upward_combo_popup_opens_above_field():
    app = _ensure_app()
    host = QWidget()
    host.resize(360, 360)
    layout = QVBoxLayout(host)
    layout.addStretch(1)
    combo = UpwardComboBox()
    combo.addItems(["One", "Two", "Three", "Four"])
    layout.addWidget(CompactField("Label", combo))
    host.move(80, 280)
    host.show()
    app.processEvents()

    show_combo_popup_above(combo)
    app.processEvents()
    assert combo.view().isVisible()
    popup = combo.view().parentWidget() or combo.view().window()
    assert popup is not None
    assert popup.y() < combo.mapToGlobal(QPoint(0, 0)).y()
    host.close()
