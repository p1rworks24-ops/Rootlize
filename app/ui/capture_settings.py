"""Compact toolbar controls for screenshot settings (destination / name / tags)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication, QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.filename_rule_panel import (
    CUSTOM_STARTER_TEMPLATE,
    FILENAME_RULES,
    rule_id_for_template,
)
from app.utils.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    preview_filename,
)
from app.utils.tag_format import format_tag, normalize_tag

_NONE_TAG = "__none__"
_CUSTOM_RULE = "custom"


def _combo_popup_frame(combo: QComboBox) -> QWidget | None:
    """Resolve the floating popup container that holds the item view."""
    view = combo.view()
    if view is None:
        return None
    popup = view.parentWidget()
    if popup is not None and popup is not combo and popup is not combo.window():
        return popup
    win = view.window()
    if win is not None and win is not combo and win is not combo.window():
        return win
    for child in combo.findChildren(QWidget):
        if not child.isVisible() or child is view:
            continue
        if child.windowFlags() & Qt.Popup:
            return child
    return None


def show_combo_popup_above(combo: QComboBox) -> None:
    """Open a combo popup anchored above the field (footer / panel friendly)."""
    # Call the QComboBox implementation directly (avoid subclass recursion)
    QComboBox.showPopup(combo)

    def _place() -> None:
        try:
            popup = _combo_popup_frame(combo)
            if popup is None:
                return

            view = combo.view()
            popup.ensurePolished()
            rows = min(max(combo.count(), 1), combo.maxVisibleItems())
            row_h = 22
            if view is not None and combo.count() > 0:
                hinted = view.sizeHintForRow(0)
                if hinted > 0:
                    row_h = hinted
            want_h = min(rows * row_h + 8, 220)
            want_w = max(popup.width(), combo.width(), 120)
            if popup.height() < want_h * 0.6:
                popup.resize(want_w, want_h)
            else:
                popup.resize(max(popup.width(), want_w), popup.height())

            origin = combo.mapToGlobal(QPoint(0, 0))
            x = origin.x()
            y = origin.y() - popup.height()
            screen = QGuiApplication.screenAt(origin)
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                # Prefer above the field; only fall below if there is no room above
                if (
                    y < avail.top()
                    and origin.y() + combo.height() + popup.height() <= avail.bottom()
                ):
                    y = origin.y() + combo.height()
                else:
                    y = max(avail.top(), y)
                x = min(
                    max(x, avail.left()),
                    max(avail.left(), avail.right() - popup.width()),
                )
            popup.move(x, y)
            popup.raise_()
        except RuntimeError:
            # Combo may already be deleted when a deferred timer fires
            return

    QTimer.singleShot(0, _place)
    QTimer.singleShot(16, _place)


class UpwardComboBox(QComboBox):
    """QComboBox whose popup opens upward when space allows."""

    def showPopup(self) -> None:  # noqa: N802 — Qt API
        show_combo_popup_above(self)


class CompactField(QWidget):
    """
    Label above a value row — shared chrome for toolbar settings.

    Value row is a single framed control (optional leading icon + combo + ▼)
    so all fields share the same background treatment.
    """

    def __init__(
        self,
        label_text: str,
        control: QWidget,
        parent=None,
        *,
        hint: str | None = None,
        leading_icon: QIcon | None = None,
        show_dropdown_mark: bool = True,
        wrap_hint: bool = False,
        expandable_value: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("compactField")
        self._wrap_hint = wrap_hint
        self._expandable_value = expandable_value
        self.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Minimum if (wrap_hint or expandable_value) else QSizePolicy.Fixed,
        )
        self._control = control
        self._chevron: QLabel | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(label_text, self)
        label.setObjectName("compactFieldLabel")
        layout.addWidget(label)

        value_row = QFrame(self)
        value_row.setObjectName(
            "compactSettingValueRowExpandable"
            if expandable_value
            else "compactSettingValueRow"
        )
        value_row.setCursor(Qt.PointingHandCursor)
        self._value_row = value_row
        row_layout = QHBoxLayout(value_row)
        row_layout.setContentsMargins(
            6, 4 if expandable_value else 0, 6, 4 if expandable_value else 0
        )
        row_layout.setSpacing(4)

        if leading_icon is not None and not leading_icon.isNull():
            star = QLabel(value_row)
            star.setObjectName("saveFolderStar")
            star.setPixmap(leading_icon.pixmap(12, 12))
            star.setAlignment(Qt.AlignCenter)
            star.setFixedWidth(14)
            row_layout.addWidget(star, 0, Qt.AlignVCenter)

        control.setObjectName("compactSettingCombo")
        control.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum if expandable_value else QSizePolicy.Fixed,
        )
        control.setCursor(Qt.PointingHandCursor)
        row_layout.addWidget(control, stretch=1)

        if show_dropdown_mark:
            chevron = QLabel("▼", value_row)
            chevron.setObjectName("compactFieldChevron")
            chevron.setAlignment(Qt.AlignCenter)
            chevron.setCursor(Qt.PointingHandCursor)
            # Match the combo's single-line height so ▼ sits on the text baseline
            chevron.setFixedHeight(22)
            self._chevron = chevron
            row_layout.addWidget(chevron, 0, Qt.AlignVCenter)

        layout.addWidget(value_row)

        # Open on normal click (release). Do not filter the combo itself —
        # intercepting press on the combo required a long-press on Windows.
        value_row.installEventFilter(self)
        if self._chevron is not None:
            self._chevron.installEventFilter(self)

        self._hint_label = QLabel(self)
        self._hint_label.setObjectName("compactFieldHint")
        self._hint_label.setWordWrap(wrap_hint)
        self._hint_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        if wrap_hint:
            self._hint_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        else:
            hint_h = max(QFontMetrics(self._hint_label.font()).height() - 2, 10)
            self._hint_label.setFixedHeight(hint_h)
        layout.addWidget(self._hint_label)
        self.set_hint(hint or "")

        if isinstance(control, QComboBox):
            control.currentTextChanged.connect(self._on_value_text_changed)

    def set_hint(self, text: str) -> None:
        value = (text or "").strip()
        self._hint_label.setText(value)
        # Toolbar fields keep a fixed hint row so Save folder / filename / tags
        # stay vertically aligned even when the hint is empty.
        if self._wrap_hint:
            self._hint_label.setVisible(bool(value))
            self._hint_label.setMaximumHeight(16777215)
            self.updateGeometry()
        else:
            self._hint_label.show()

    def _on_value_text_changed(self, text: str) -> None:
        if not self._expandable_value:
            return
        self._relayout_expandable_value(text)

    def _relayout_expandable_value(self, text: str | None = None) -> None:
        if not self._expandable_value:
            return
        value = (text if text is not None else self._control.currentText()).strip()
        fm = QFontMetrics(self._control.font())
        chrome = 28
        if self._chevron is not None:
            chrome += 16
        avail = max(self._value_row.width() - chrome, 80)
        bounds = fm.boundingRect(0, 0, avail, 2000, int(Qt.TextWordWrap), value)
        line_h = max(fm.height(), 14)
        needed = max(26, min(bounds.height() + 10, line_h * 4 + 10))
        self._value_row.setMinimumHeight(needed)
        self._value_row.updateGeometry()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._expandable_value:
            self._relayout_expandable_value()

    def _open_popup(self) -> None:
        if isinstance(self._control, QComboBox):
            show_combo_popup_above(self._control)

    def eventFilter(self, obj, event) -> bool:
        if obj not in (self._value_row, self._chevron):
            return False
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        if not isinstance(event, QMouseEvent) or event.button() != Qt.LeftButton:
            return False
        if not isinstance(self._control, QComboBox):
            return False
        QTimer.singleShot(0, self._open_popup)
        return True


def field_separator(parent: QWidget | None = None) -> QFrame:
    """Thin vertical divider between compact settings fields."""
    sep = QFrame(parent)
    sep.setObjectName("compactFieldSep")
    sep.setFrameShape(QFrame.VLine)
    sep.setFrameShadow(QFrame.Plain)
    sep.setFixedWidth(1)
    return sep


class FilenameRuleCombo(UpwardComboBox):
    """Dropdown: Datetime / Sequential / Datetime+number / Custom."""

    template_changed = Signal(str)
    preview_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder = "Capture"
        self._when = datetime.now()
        self._updating = False
        self._custom_template = CUSTOM_STARTER_TEMPLATE
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(110)

        for rule_id, preset in FILENAME_RULES:
            self.addItem(t(f"shell.rule.{rule_id}"), rule_id)

        self.activated.connect(self._on_activated)

    def set_folder(self, folder: str) -> None:
        self._folder = folder or "Capture"
        self._refresh_preview()

    def set_template(self, template: str) -> None:
        self._updating = True
        tpl = (template or "").strip() or DEFAULT_FILENAME_TEMPLATE
        rule = rule_id_for_template(tpl)
        if rule == _CUSTOM_RULE:
            self._custom_template = tpl
        index = self.findData(rule)
        if index >= 0:
            self.setCurrentIndex(index)
        self._updating = False
        self._refresh_preview()

    def current_template(self) -> str:
        rule = self.currentData()
        if rule == _CUSTOM_RULE:
            return self._custom_template or CUSTOM_STARTER_TEMPLATE
        for rule_id, preset in FILENAME_RULES:
            if rule_id == rule and preset:
                return preset
        return DEFAULT_FILENAME_TEMPLATE

    def preview_text(self) -> str:
        name = preview_filename(
            self.current_template(), folder=self._folder, when=self._when
        )
        return t("shell.filename_preview_example", name=name)

    def _on_activated(self, _index: int) -> None:
        if self._updating:
            return
        if self.currentData() == _CUSTOM_RULE:
            text, ok = QInputDialog.getText(
                self,
                t("shell.filename_custom_title"),
                t("shell.filename_custom_prompt"),
                text=self._custom_template,
            )
            if ok:
                cleaned = (text or "").strip() or CUSTOM_STARTER_TEMPLATE
                # Keep Custom even if the typed pattern matches a preset label
                self._custom_template = cleaned
            else:
                self.set_template(self._custom_template)
                return
        self._refresh_preview()
        self.template_changed.emit(self.current_template())

    def _refresh_preview(self) -> None:
        text = self.preview_text()
        self.setToolTip(text)
        self.preview_changed.emit(text)


class CaptureTagCombo(UpwardComboBox):
    """
    Single-tag dropdown for capture-time tagging.
    Config stays list[str] so multi-tag UI can plug in later.
    """

    tags_changed = Signal(list)

    def __init__(
        self,
        metadata_service: MetadataService,
        app_root: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._metadata_service = metadata_service
        self._app_root = app_root
        self._updating = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(100)
        self.setToolTip(t("shell.capture_tags_tooltip"))
        self.activated.connect(self._on_activated)

    def reload_choices(self, selected: list[str] | None = None) -> None:
        current = ""
        if selected:
            current = normalize_tag(str(selected[0]))
        elif self.currentData() and self.currentData() != _NONE_TAG:
            current = normalize_tag(str(self.currentData()))

        self._updating = True
        self.clear()
        self.addItem(t("shell.capture_tags_none"), _NONE_TAG)
        for tag in self._metadata_service.load_global_tags(
            self._app_root, force_reload=True
        ):
            self.addItem(format_tag(tag), tag)
        index = self.findData(current) if current else 0
        self.setCurrentIndex(index if index >= 0 else 0)
        self._updating = False

    def set_tags(self, tags: list[str]) -> None:
        self.reload_choices(tags)

    def tags(self) -> list[str]:
        data = self.currentData()
        if not data or data == _NONE_TAG:
            return []
        tag = normalize_tag(str(data))
        return [tag] if tag else []

    def _on_activated(self, _index: int) -> None:
        if self._updating:
            return
        self.tags_changed.emit(self.tags())
