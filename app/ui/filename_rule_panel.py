"""Beginner-friendly save-filename rule picker with live preview."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal, QEvent, QObject
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
)

from app.i18n import t
from app.utils.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    preview_filename,
)

# (rule_id, template or None for custom)
FILENAME_RULES: list[tuple[str, str | None]] = [
    ("datetime", "{date}_{time}"),
    ("sequential", "Screenshot_{num}"),
    ("datetime_num", "{date}_{time}_{num}"),
    ("custom", None),
]

# Shared chip width so every rule row is the same length
_RULE_ROW_WIDTH = 460

# Must NOT match any preset — otherwise selecting Custom snaps back to Datetime
CUSTOM_STARTER_TEMPLATE = "Capture_{date}_{time}"


def rule_id_for_template(template: str) -> str:
    tpl = (template or "").strip() or DEFAULT_FILENAME_TEMPLATE
    for rule_id, preset in FILENAME_RULES:
        if preset is not None and preset == tpl:
            return rule_id
    return "custom"


class FilenameRulePanel(QFrame):
    """
    Compact rule chips — gray box hugs [●][name][example] with even side padding:
      ● Datetime  20260716_123456.png
    Emits template_changed(str) when the user picks a rule / edits custom.
    """

    template_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder = "Capture"
        self._when = datetime.now()
        self._updating = False
        self._custom_draft = CUSTOM_STARTER_TEMPLATE
        self.setObjectName("filenameRulePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel(t("shell.save_filename_title"), self)
        title.setObjectName("filenameRuleTitle")
        layout.addWidget(title)

        self._group = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        self._example_labels: dict[str, QLabel] = {}
        self._marker_labels: dict[str, QLabel] = {}
        self._rows: dict[str, QFrame] = {}

        for rule_id, _preset in FILENAME_RULES:
            row = QFrame(self)
            row.setObjectName("filenameRuleRow")
            row.setProperty("selected", False)
            row.setCursor(Qt.PointingHandCursor)
            # Fixed width — all rule chips share the same length
            row.setFixedWidth(_RULE_ROW_WIDTH)
            row.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            row_layout = QHBoxLayout(row)
            # Equal left / right inset around ● + name + example
            row_layout.setContentsMargins(14, 8, 14, 8)
            row_layout.setSpacing(10)

            marker = QLabel("", row)
            marker.setObjectName("filenameRuleMarker")
            marker.setFixedWidth(14)
            marker.setAlignment(Qt.AlignCenter)
            self._marker_labels[rule_id] = marker
            row_layout.addWidget(marker)

            radio = QRadioButton(t(f"shell.rule.{rule_id}"), row)
            radio.setObjectName("filenameRuleRadio")
            radio.setCursor(Qt.PointingHandCursor)
            radio.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self._group.addButton(radio)
            self._radios[rule_id] = radio
            row_layout.addWidget(radio)

            example = QLabel("", row)
            example.setObjectName("filenameRuleExample")
            example.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            example.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._example_labels[rule_id] = example
            row_layout.addWidget(example, stretch=1)

            self._rows[rule_id] = row
            layout.addWidget(row, alignment=Qt.AlignLeft)
            radio.toggled.connect(self._on_radio_toggled)
            row.installEventFilter(self)

        self._custom_edit = QLineEdit(self)
        self._custom_edit.setPlaceholderText(t("shell.rule.custom_placeholder"))
        self._custom_edit.setObjectName("filenameRuleCustomEdit")
        self._custom_edit.setMaximumWidth(360)
        self._custom_edit.textEdited.connect(self._on_custom_edited)
        self._custom_edit.hide()
        layout.addWidget(self._custom_edit, alignment=Qt.AlignLeft)

        divider = QFrame(self)
        divider.setObjectName("sectionDivider")
        divider.setFixedHeight(1)
        divider.setFrameShape(QFrame.HLine)
        layout.addWidget(divider)

        self._preview = QLabel("", self)
        self._preview.setObjectName("filenameRulePreview")
        layout.addWidget(self._preview)

        self._refresh_examples()
        self._refresh_selection_chrome()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            for rule_id, row in self._rows.items():
                if obj is row:
                    radio = self._radios[rule_id]
                    if not radio.isChecked():
                        radio.setChecked(True)
                    return False
        return super().eventFilter(obj, event)

    def set_folder(self, folder: str) -> None:
        self._folder = folder or "Capture"
        self._refresh_examples()
        self._update_preview()

    def set_template(self, template: str) -> None:
        self._updating = True
        tpl = (template or "").strip() or DEFAULT_FILENAME_TEMPLATE
        rule = rule_id_for_template(tpl)
        radio = self._radios.get(rule)
        if radio:
            radio.setChecked(True)
        if rule == "custom":
            self._custom_draft = tpl
            self._custom_edit.setText(tpl)
            self._custom_edit.show()
        else:
            self._custom_edit.hide()
        self._updating = False
        self._refresh_selection_chrome()
        self._update_preview()

    def current_template(self) -> str:
        for rule_id, radio in self._radios.items():
            if radio.isChecked():
                if rule_id == "custom":
                    text = self._custom_edit.text().strip()
                    if text:
                        self._custom_draft = text
                        return text
                    return self._custom_draft or CUSTOM_STARTER_TEMPLATE
                for rid, preset in FILENAME_RULES:
                    if rid == rule_id and preset:
                        return preset
        return DEFAULT_FILENAME_TEMPLATE

    def _refresh_selection_chrome(self) -> None:
        """Highlight the checked rule chip; show leading ● when selected."""
        for rule_id, row in self._rows.items():
            selected = bool(self._radios[rule_id].isChecked())
            row.setProperty("selected", selected)
            self._marker_labels[rule_id].setText("●" if selected else "")
            style = row.style()
            style.unpolish(row)
            style.polish(row)
            row.update()

    def _on_radio_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._refresh_selection_chrome()
        if self._updating:
            return
        custom = self._radios["custom"].isChecked()
        self._custom_edit.setVisible(custom)
        if custom:
            # Never seed Custom with a preset template (e.g. {date}_{time}) —
            # that remaps to Datetime after autosave/refresh.
            text = self._custom_edit.text().strip()
            if not text or rule_id_for_template(text) != "custom":
                seed = self._custom_draft
                if rule_id_for_template(seed) != "custom":
                    seed = CUSTOM_STARTER_TEMPLATE
                self._custom_edit.setText(seed)
                self._custom_draft = seed
        self._emit()

    def _on_custom_edited(self, text: str) -> None:
        if self._updating:
            return
        if not self._radios["custom"].isChecked():
            self._radios["custom"].setChecked(True)
        self._custom_draft = (text or "").strip() or CUSTOM_STARTER_TEMPLATE
        self._emit()

    def _emit(self) -> None:
        self._update_preview()
        self.template_changed.emit(self.current_template())

    def _refresh_examples(self) -> None:
        for rule_id, preset in FILENAME_RULES:
            label = self._example_labels.get(rule_id)
            if label is None:
                continue
            if preset is None:
                label.setText(t("shell.rule.custom_hint"))
            else:
                label.setText(
                    preview_filename(preset, folder=self._folder, when=self._when)
                )

    def _update_preview(self) -> None:
        name = preview_filename(
            self.current_template(), folder=self._folder, when=self._when
        )
        self._preview.setText(t("shell.filename_preview_line", name=name))
