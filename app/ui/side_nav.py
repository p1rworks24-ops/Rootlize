"""Hover-expanding left navigation (Fluent / Windows 11 inspired)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property, Signal, QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from app.branding import APP_NAME_SIDEBAR
from app.ui.app_icon import app_mark_pixmap


class SideNav(QFrame):
    """Hover-expanding left navigation (Fluent / Windows 11 inspired)."""

    page_selected = Signal(int)

    COLLAPSED_WIDTH = 56
    EXPANDED_WIDTH = 176
    ANIM_MS = 180
    _BRAND_ICON_PX = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._expanded = False
        self._animating = False
        self._nav_buttons: dict[int, QPushButton] = {}
        self._placeholder_buttons: list[QPushButton] = []
        self._label_keys: dict[int, str] = {}
        self._width = self.COLLAPSED_WIDTH

        self.setFixedWidth(self.COLLAPSED_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 14, 8, 14)
        self._layout.setSpacing(4)

        brand_wrap = QWidget(self)
        brand_wrap.setObjectName("sidebarBrandWrap")
        brand_lay = QHBoxLayout(brand_wrap)
        brand_lay.setContentsMargins(6, 6, 8, 6)
        brand_lay.setSpacing(8)
        brand_lay.setAlignment(Qt.AlignVCenter)

        self._brand_icon = QLabel(brand_wrap)
        self._brand_icon.setObjectName("sidebarBrandIcon")
        self._brand_icon.setAlignment(Qt.AlignCenter)
        self._brand_icon.setFixedSize(self._BRAND_ICON_PX, self._BRAND_ICON_PX)
        self._brand_icon.setPixmap(app_mark_pixmap(self._BRAND_ICON_PX))
        brand_lay.addWidget(self._brand_icon, 0, Qt.AlignVCenter)

        self._brand = QLabel(APP_NAME_SIDEBAR, brand_wrap)
        self._brand.setObjectName("sidebarBrand")
        self._brand.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._brand.setVisible(False)
        brand_lay.addWidget(self._brand, 1, Qt.AlignVCenter)

        self._layout.addWidget(brand_wrap)
        self._layout.addSpacing(10)

        self._anim = QPropertyAnimation(self, b"navWidth", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)

    def get_nav_width(self) -> int:
        return self._width

    def set_nav_width(self, value: int) -> None:
        self._width = int(value)
        self.setFixedWidth(self._width)

    navWidth = Property(int, get_nav_width, set_nav_width)

    def add_nav_item(
        self,
        page_id: int,
        label: str,
        icon,
        *,
        label_key: str = "",
        accent: str = "",
    ) -> QPushButton:
        btn = QPushButton(self)
        btn.setObjectName("navButton")
        btn.setIcon(icon)
        btn.setIconSize(QSize(20, 20))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setToolTip(label)
        btn.setProperty("navLabel", label)
        if accent:
            btn.setProperty("navAccent", accent)
        btn.clicked.connect(
            lambda checked=False, pid=page_id: self.page_selected.emit(pid)
        )
        self._layout.addWidget(btn)
        self._nav_buttons[page_id] = btn
        self._label_keys[page_id] = label_key or label
        self._apply_button_labels()
        self._polish(btn)
        return btn

    def add_placeholder_item(
        self,
        label: str,
        icon,
        *,
        tooltip: str = "",
        accent: str = "ai",
    ) -> QPushButton:
        """
        Non-navigating nav row (e.g. future AI).

        Visible and hoverable for tooltip, but not checkable and emits no page change.
        """
        btn = QPushButton(self)
        btn.setObjectName("navButtonPlaceholder")
        btn.setIcon(icon)
        btn.setIconSize(QSize(20, 20))
        btn.setCursor(Qt.ArrowCursor)
        btn.setCheckable(False)
        btn.setEnabled(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip(tooltip or label)
        btn.setProperty("navLabel", label)
        if accent:
            btn.setProperty("navAccent", accent)
        # Swallow clicks — no page_selected emission
        btn.clicked.connect(lambda checked=False: None)
        self._layout.addWidget(btn)
        self._placeholder_buttons.append(btn)
        self._apply_button_labels()
        self._polish(btn)
        return btn

    @staticmethod
    def _polish(widget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def add_stretch(self) -> None:
        self._layout.addStretch()

    def set_current_page(self, page_id: int) -> None:
        for pid, btn in self._nav_buttons.items():
            btn.setChecked(pid == page_id)
        # Placeholders never enter a selected/checked state
        for btn in self._placeholder_buttons:
            btn.setChecked(False)

    def enterEvent(self, event) -> None:
        self._animate_to(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_to(False)
        super().leaveEvent(event)

    def _animate_to(self, expanded: bool) -> None:
        if self._expanded == expanded and not self._animating:
            target = self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
            if self.width() == target:
                return
        self._expanded = expanded
        self._animating = True
        self._anim.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(
            self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
        )
        if expanded:
            self._apply_button_labels(force_expanded=True)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        self._animating = False
        self._apply_button_labels()

    def _apply_button_labels(self, *, force_expanded: bool | None = None) -> None:
        expanded = (
            self._expanded if force_expanded is None else force_expanded
        )
        # Icon left + Capixe name right (name only when the rail is open)
        self._brand_icon.setPixmap(app_mark_pixmap(self._BRAND_ICON_PX))
        self._brand.setText(APP_NAME_SIDEBAR)
        self._brand.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._brand.setVisible(expanded)

        buttons = list(self._nav_buttons.values()) + self._placeholder_buttons
        for btn in buttons:
            label = btn.property("navLabel") or ""
            if expanded:
                btn.setText(str(label))
            else:
                btn.setText("")
