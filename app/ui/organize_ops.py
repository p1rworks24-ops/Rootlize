"""Organize Operations: shared layout tokens, accents, and menu item widgets."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from app.ui.icons import fluent_icon

# ----- Shared inset / spacing (Operations card chrome) -----
OPS_PAD_X = 28
OPS_PAD_TOP = 28
OPS_PAD_BOTTOM = 24
OPS_TITLE_TO_HINT = 10
OPS_HINT_TO_LIST = 18
OPS_ITEM_GAP = 10
OPS_SECTION_GAP = 14
OPS_ITEM_PAD_X = 14
OPS_ITEM_PAD_Y = 12
OPS_ITEM_ICON = 22
OPS_ITEM_MIN_H = 68
OPS_DETAIL_HEADER_PAD = 10

# Back-compat alias (symmetric callers)
OPS_PAD_Y = OPS_PAD_TOP

# Fluent glyphs
_GLYPH_TAG = "\uE8EC"
_GLYPH_RENAME = "\uE8AC"
_GLYPH_CONVERT = "\uE8AB"
_GLYPH_RESIZE = "\uE799"
_GLYPH_EXPORT = "\uEDE1"


@dataclass(frozen=True)
class OpAccent:
    """Soft accent used for hub selection + detail chrome."""

    fg: str
    bg: str
    border: str
    hover_bg: str
    button: str


@dataclass(frozen=True)
class OpSpec:
    op_id: str
    title_key: str
    desc_key: str
    hint_key: str
    accent: OpAccent
    icon_glyph: str
    enabled: bool = True
    status_key: str | None = None  # e.g. coming soon


OP_TAGS = "tags"
OP_RENAME = "rename"
OP_CONVERT = "convert"
OP_RESIZE = "resize"
OP_EXPORT = "export"

ACCENT_TAGS = OpAccent(
    fg="#5b21b6",
    bg="#f5f3ff",
    border="#c4b5fd",
    hover_bg="#ede9fe",
    button="#7c3aed",
)
ACCENT_RENAME = OpAccent(
    fg="#c2410c",
    bg="#fff7ed",
    border="#fdba74",
    hover_bg="#ffedd5",
    button="#ea580c",
)
ACCENT_CONVERT = OpAccent(
    fg="#6d28d9",
    bg="#faf5ff",
    border="#d8b4fe",
    hover_bg="#f3e8ff",
    button="#9333ea",
)
ACCENT_RESIZE = OpAccent(
    fg="#047857",
    bg="#ecfdf5",
    border="#6ee7b7",
    hover_bg="#d1fae5",
    button="#059669",
)
ACCENT_EXPORT = OpAccent(
    fg="#0f766e",
    bg="#f0fdfa",
    border="#5eead4",
    hover_bg="#ccfbf1",
    button="#0d9488",
)

# Registry order = hub list order (enabled first, then coming-soon)
OPERATION_SPECS: tuple[OpSpec, ...] = (
    OpSpec(
        OP_TAGS,
        "work.op_tags",
        "work.op_tags_desc",
        "work.bulk_tags_hint",
        ACCENT_TAGS,
        _GLYPH_TAG,
    ),
    OpSpec(
        OP_RENAME,
        "work.op_rename",
        "work.op_rename_desc",
        "work.bulk_rename_hint",
        ACCENT_RENAME,
        _GLYPH_RENAME,
    ),
    OpSpec(
        OP_CONVERT,
        "work.op_convert",
        "work.op_convert_desc",
        "work.op_coming_soon_hint",
        ACCENT_CONVERT,
        _GLYPH_CONVERT,
        enabled=False,
        status_key="work.op_status_soon",
    ),
    OpSpec(
        OP_RESIZE,
        "work.op_resize",
        "work.op_resize_desc",
        "work.op_coming_soon_hint",
        ACCENT_RESIZE,
        _GLYPH_RESIZE,
        enabled=False,
        status_key="work.op_status_soon",
    ),
    OpSpec(
        OP_EXPORT,
        "work.op_export",
        "work.op_export_desc",
        "work.op_coming_soon_hint",
        ACCENT_EXPORT,
        _GLYPH_EXPORT,
        enabled=False,
        status_key="work.op_status_soon",
    ),
)


def op_spec(op_id: str) -> OpSpec | None:
    for spec in OPERATION_SPECS:
        if spec.op_id == op_id:
            return spec
    return None


def op_icon(spec: OpSpec, *, size: int = OPS_ITEM_ICON, selected: bool = False) -> QIcon:
    color = spec.accent.fg if selected or spec.enabled else "#9ca3af"
    return fluent_icon(spec.icon_glyph, size=size, color=color)


class OperationMenuItem(QFrame):
    """
    Hub list card: entire frame is one click target.

    Child labels are mouse-transparent so icon / title / description / padding
    all activate the same handler exactly once (on left-button release).
    """

    clicked = Signal(str)

    def __init__(self, spec: OpSpec, title: str, description: str, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._press_active = False
        self._emit_guard = False
        self.setObjectName("operationMenuItem")
        self.setProperty("opId", spec.op_id)
        self.setProperty("selected", False)
        self.setProperty("hovered", False)
        self.setProperty("enabledOp", spec.enabled)
        self.setCursor(Qt.PointingHandCursor if spec.enabled else Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus if spec.enabled else Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(OPS_ITEM_MIN_H)
        self._icon_size = OPS_ITEM_ICON

        # Icon sits on the title row (VCenter) so it lines up with the title,
        # not AlignTop against the full title+description column.
        col = QVBoxLayout(self)
        col.setContentsMargins(OPS_ITEM_PAD_X, OPS_ITEM_PAD_Y, OPS_ITEM_PAD_X, OPS_ITEM_PAD_Y)
        col.setSpacing(2)
        self._row_layout = col

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        self._icon = QLabel(self)
        self._icon.setObjectName("operationMenuIcon")
        self._icon.setFixedSize(OPS_ITEM_ICON + 4, OPS_ITEM_ICON + 4)
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setPixmap(op_icon(spec).pixmap(OPS_ITEM_ICON, OPS_ITEM_ICON))
        title_row.addWidget(self._icon, 0, Qt.AlignVCenter)

        self._title = QLabel(title, self)
        self._title.setObjectName("operationMenuTitle")
        title_row.addWidget(self._title, 0, Qt.AlignVCenter)
        self._status: QLabel | None = None
        if spec.status_key:
            from app.i18n import t

            self._status = QLabel(t(spec.status_key), self)
            self._status.setObjectName("operationMenuStatus")
            title_row.addWidget(self._status, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        col.addLayout(title_row)

        self._desc = QLabel(description, self)
        self._desc.setObjectName("operationMenuDesc")
        self._desc.setWordWrap(True)
        col.addWidget(self._desc)

        self._make_children_pass_clicks()
        self._refresh_enabled_chrome()

    def apply_density(
        self,
        *,
        min_height: int,
        pad_x: int,
        pad_y: int,
        icon_size: int,
        show_desc: bool,
        title_pt: int,
        desc_pt: int,
    ) -> None:
        """Scale card chrome to fit the Operations panel height."""
        self.setMinimumHeight(min_height)
        # Allow slight growth for wrapped title when roomy; cap when compact
        self.setMaximumHeight(min_height + (24 if show_desc else 8))
        self._row_layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        self._icon_size = icon_size
        self._icon.setFixedSize(icon_size + 4, icon_size + 4)
        self._icon.setPixmap(
            op_icon(
                self._spec,
                size=icon_size,
                selected=bool(self.property("selected")),
            ).pixmap(icon_size, icon_size)
        )
        self._desc.setVisible(show_desc)
        for label, pt, bold in (
            (self._title, title_pt, True),
            (self._desc, desc_pt, False),
        ):
            font = label.font()
            font.setPointSize(pt)
            font.setWeight(
                QFont.Weight.DemiBold if bold else QFont.Weight.Normal
            )
            label.setFont(font)
        if self._status is not None:
            font = self._status.font()
            font.setPointSize(max(9, desc_pt))
            self._status.setFont(font)

    def _make_children_pass_clicks(self) -> None:
        """Route all pointer events to this card; avoid per-label handlers."""
        labels = [self._icon, self._title, self._desc]
        if self._status is not None:
            labels.append(self._status)
        for label in labels:
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setTextInteractionFlags(Qt.NoTextInteraction)
            label.setFocusPolicy(Qt.NoFocus)
            label.setCursor(Qt.PointingHandCursor if self._spec.enabled else Qt.ArrowCursor)

    @property
    def op_id(self) -> str:
        return self._spec.op_id

    @property
    def spec(self) -> OpSpec:
        return self._spec

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        size = getattr(self, "_icon_size", OPS_ITEM_ICON)
        self._icon.setPixmap(
            op_icon(self._spec, size=size, selected=selected and self._spec.enabled).pixmap(
                size, size
            )
        )
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()

    def _refresh_enabled_chrome(self) -> None:
        if not self._spec.enabled:
            self._title.setStyleSheet("color: #9ca3af;")
            self._desc.setStyleSheet("color: #9ca3af;")

    def _activate(self) -> None:
        if not self._spec.enabled or self._emit_guard:
            return
        self._emit_guard = True
        try:
            self.clicked.emit(self._spec.op_id)
        finally:
            self._emit_guard = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._spec.enabled and event.button() == Qt.LeftButton:
            self._press_active = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_active
            and self._spec.enabled
            and event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self._press_active = False
            self._activate()
            event.accept()
            return
        self._press_active = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._spec.enabled and event.key() in (
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Space,
        ):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        if self._spec.enabled:
            self.setProperty("hovered", True)
            style = self.style()
            if style is not None:
                style.unpolish(self)
                style.polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._press_active = False
        self.setProperty("hovered", False)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.setProperty("hovered", True)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        if not self.property("selected"):
            self.setProperty("hovered", False)
            style = self.style()
            if style is not None:
                style.unpolish(self)
                style.polish(self)
        super().focusOutEvent(event)
