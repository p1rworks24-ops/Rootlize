"""Compact toolbar controls for screenshot settings (destination / name / tags)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon
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
    ):
        super().__init__(parent)
        self.setObjectName("compactField")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(label_text, self)
        label.setObjectName("compactFieldLabel")
        layout.addWidget(label)

        value_row = QFrame(self)
        value_row.setObjectName("compactSettingValueRow")
        row_layout = QHBoxLayout(value_row)
        row_layout.setContentsMargins(6, 0, 6, 0)
        row_layout.setSpacing(4)

        if leading_icon is not None and not leading_icon.isNull():
            star = QLabel(value_row)
            star.setObjectName("saveFolderStar")
            star.setPixmap(leading_icon.pixmap(12, 12))
            star.setAlignment(Qt.AlignCenter)
            star.setFixedWidth(14)
            row_layout.addWidget(star, 0, Qt.AlignVCenter)

        control.setObjectName("compactSettingCombo")
        control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row_layout.addWidget(control, stretch=1)

        if show_dropdown_mark:
            chevron = QLabel("▼", value_row)
            chevron.setObjectName("compactFieldChevron")
            chevron.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(chevron, 0, Qt.AlignVCenter)

        layout.addWidget(value_row)

        self._hint_label = QLabel(self)
        self._hint_label.setObjectName("compactFieldHint")
        self._hint_label.setWordWrap(False)
        self._hint_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hint_h = max(QFontMetrics(self._hint_label.font()).height() - 2, 10)
        self._hint_label.setFixedHeight(hint_h)
        layout.addWidget(self._hint_label)
        self.set_hint(hint or "")

    def set_hint(self, text: str) -> None:
        value = (text or "").strip()
        self._hint_label.setText(value)
        self._hint_label.show()


def field_separator(parent: QWidget | None = None) -> QFrame:
    """Thin vertical divider between compact settings fields."""
    sep = QFrame(parent)
    sep.setObjectName("compactFieldSep")
    sep.setFrameShape(QFrame.VLine)
    sep.setFrameShadow(QFrame.Plain)
    sep.setFixedWidth(1)
    return sep


class FilenameRuleCombo(QComboBox):
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


class CaptureTagCombo(QComboBox):
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
