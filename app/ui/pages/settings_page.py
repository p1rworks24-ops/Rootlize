from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFrame,
    QComboBox,
)

from app.config import save_config
from app.i18n import t
from app.services.shortcut_spec import (
    ACTION_LABEL_KEYS,
    SHORTCUT_ACTIONS,
    apply_shortcuts_to_config,
    find_shortcut_conflict,
    format_shortcut_display,
    load_shortcuts_from_config,
    validate_shortcut,
)
from app.ui.design_tokens import apply_card_shadow
from app.ui.scroll_page import make_page_scroll
from app.ui.segmented_toggle import SegmentedToggle
from app.ui.shortcut_capture_dialog import ShortcutCaptureDialog
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.logger import setup_logger
from app.utils.workspace import resolve_save_folder

logger = setup_logger()


def _capture_settings_enabled() -> bool:
    from app.ui.main_window import CAPTURE_ENABLED

    return bool(CAPTURE_ENABLED)


class SettingsPage(QWidget):
    """In-app settings page — changes autosave on select / edit commit."""

    settings_saved = Signal()
    # Emitted only when Window width/height are saved (triggers shell resize)
    window_size_changed = Signal()
    # Emitted when capture shortcuts change (shell re-registers hotkeys)
    shortcuts_changed = Signal()
    reanalyze_requested = Signal()
    replay_tour_requested = Signal()
    replay_ai_tour_requested = Signal()
    replay_automation_tour_requested = Signal()
    ask_ai_explanation_requested = Signal()
    feedback_requested = Signal()

    def __init__(self, config: dict, app_root: Path, parent=None, *, ocr_controller=None):
        super().__init__(parent)
        self._config = config
        self._app_root = app_root
        self._loading = False
        self._ocr_controller = ocr_controller
        self._shortcut_value_labels: dict[str, QLabel] = {}
        self._status_clear_timer = QTimer(self)
        self._status_clear_timer.setSingleShot(True)
        self._status_clear_timer.setInterval(2200)
        self._status_clear_timer.timeout.connect(self._clear_status)
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        content.setObjectName("settingsContentColumn")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(16)

        from app.ui.page_header import make_page_header

        layout.addWidget(
            make_page_header(content, t("settings.title"), t("settings.subtitle"))
        )

        autosave_hint = QLabel(t("settings.autosave_hint"), content)
        autosave_hint.setObjectName("settingsAutosaveHint")
        autosave_hint.setWordWrap(True)
        layout.addWidget(autosave_hint)

        capture_on = _capture_settings_enabled()
        if capture_on:
            from app.ui.filename_rule_panel import FilenameRulePanel

            name_section, name_layout = self._make_card(content)
            self._filename_panel = FilenameRulePanel(name_section)
            self._filename_panel.set_template(
                self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
            )
            self._filename_panel.set_folder(resolve_save_folder(self._config))
            self._filename_panel.template_changed.connect(self._on_filename_changed)
            name_layout.addWidget(self._filename_panel)
            layout.addWidget(name_section)

            capture_section, capture_layout = self._make_card(
                content,
                t("settings.capture_minimize"),
                t("settings.capture_minimize_hint"),
            )
            self._minimize_toggle = SegmentedToggle(
                [
                    t("settings.capture_minimize_on"),
                    t("settings.capture_minimize_off"),
                ],
                content,
            )
            self._minimize_toggle.set_current(
                0 if self._config.get("capture_minimize", True) else 1
            )
            self._minimize_toggle.changed.connect(self._on_minimize_changed)
            minimize_row = QHBoxLayout()
            minimize_row.addWidget(self._minimize_toggle)
            minimize_row.addStretch(1)
            capture_layout.addLayout(minimize_row)
            layout.addWidget(capture_section)

        notify_section, notify_layout = self._make_card(
            content,
            t("settings.notifications"),
            t("settings.notifications.hint"),
        )
        self._notify_toggle = SegmentedToggle(
            [
                t("settings.notifications.on"),
                t("settings.notifications.off"),
            ],
            content,
        )
        self._notify_toggle.set_current(
            0 if self._config.get("show_save_notification", True) else 1
        )
        self._notify_toggle.changed.connect(self._on_notify_changed)
        notify_row = QHBoxLayout()
        notify_row.addWidget(self._notify_toggle)
        notify_row.addStretch(1)
        notify_layout.addLayout(notify_row)

        duration_row = QHBoxLayout()
        duration_row.setSpacing(10)
        duration_label = QLabel(t("settings.notifications.duration"), content)
        duration_label.setObjectName("settingsFieldLabel")
        duration_row.addWidget(duration_label)
        self._notify_duration = QComboBox(content)
        self._notify_duration.setObjectName("settingsDurationCombo")
        self._notify_duration.setCursor(Qt.PointingHandCursor)
        for seconds in (2, 3, 5, 8):
            self._notify_duration.addItem(
                t("settings.notifications.duration_sec", n=seconds), seconds
            )
        current_dur = int(self._config.get("notification_duration_sec", 5) or 5)
        dur_index = self._notify_duration.findData(current_dur)
        default_dur = self._notify_duration.findData(5)
        self._notify_duration.setCurrentIndex(
            dur_index if dur_index >= 0 else (default_dur if default_dur >= 0 else 0)
        )
        self._notify_duration.currentIndexChanged.connect(self._on_notify_duration_changed)
        duration_row.addWidget(self._notify_duration)
        duration_row.addStretch(1)
        notify_layout.addLayout(duration_row)
        layout.addWidget(notify_section)

        if capture_on:
            shortcuts_section, shortcuts_layout = self._make_card(
                content,
                t("settings.shortcuts"),
                t("settings.shortcuts.hint"),
            )
            bindings = load_shortcuts_from_config(self._config)
            for index, action_id in enumerate(SHORTCUT_ACTIONS):
                row = QFrame(shortcuts_section)
                row.setObjectName("shortcutRow")
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(
                    0, 8, 0, 10 if index < len(SHORTCUT_ACTIONS) - 1 else 4
                )
                row_layout.setSpacing(8)

                action_label = QLabel(t(ACTION_LABEL_KEYS[action_id]), row)
                action_label.setObjectName("shortcutActionLabel")
                row_layout.addWidget(action_label)

                value_row = QHBoxLayout()
                value_row.setSpacing(10)
                value_label = QLabel(format_shortcut_display(bindings[action_id]), row)
                value_label.setObjectName("shortcutValueLabel")
                value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                self._shortcut_value_labels[action_id] = value_label
                value_row.addWidget(value_label, 0, Qt.AlignVCenter)

                change_btn = QPushButton(t("settings.shortcuts.change"), row)
                change_btn.setObjectName("secondaryButton")
                change_btn.setCursor(Qt.PointingHandCursor)
                change_btn.clicked.connect(
                    lambda _checked=False, aid=action_id: self._on_change_shortcut(aid)
                )
                value_row.addWidget(change_btn, 0, Qt.AlignVCenter)
                value_row.addStretch(1)
                row_layout.addLayout(value_row)
                shortcuts_layout.addWidget(row)

            layout.addWidget(shortcuts_section)

        ui_section, ui_layout = self._make_card(
            content,
            t("settings.ui"),
            t("settings.window_hint"),
        )
        width_row = QHBoxLayout()
        width_row.setSpacing(10)
        width_label = QLabel(t("settings.window_width"), content)
        width_label.setObjectName("settingsFieldLabel")
        width_row.addWidget(width_label)
        self._width_edit = QLineEdit(content)
        self._width_edit.setObjectName("settingsSizeEdit")
        self._width_edit.setMaximumWidth(140)
        self._width_edit.setText(str(self._config.get("window_width", 1600)))
        self._width_edit.editingFinished.connect(self._autosave_window_size)
        width_row.addWidget(self._width_edit)
        ui_layout.addLayout(width_row)

        height_row = QHBoxLayout()
        height_row.setSpacing(10)
        height_label = QLabel(t("settings.window_height"), content)
        height_label.setObjectName("settingsFieldLabel")
        height_row.addWidget(height_label)
        self._height_edit = QLineEdit(content)
        self._height_edit.setObjectName("settingsSizeEdit")
        self._height_edit.setMaximumWidth(140)
        self._height_edit.setText(str(self._config.get("window_height", 900)))
        self._height_edit.editingFinished.connect(self._autosave_window_size)
        height_row.addWidget(self._height_edit)
        ui_layout.addLayout(height_row)
        layout.addWidget(ui_section)

        maintenance, maintenance_layout = self._make_card(
            content,
            t("settings.maintenance"),
            t("settings.maintenance.hint"),
        )
        self._reanalyze_btn = QPushButton(t("settings.maintenance.reanalyze"), content)
        self._reanalyze_btn.setObjectName("secondaryButton")
        self._reanalyze_btn.setCursor(Qt.PointingHandCursor)
        self._reanalyze_btn.clicked.connect(self.reanalyze_requested.emit)
        maintenance_layout.addWidget(self._reanalyze_btn, 0)
        layout.addWidget(maintenance)

        help_section, help_layout = self._make_card(
            content,
            t("settings.help"),
            t("settings.help.hint"),
        )
        self._replay_tour_btn = QPushButton(t("settings.help.replay_tour"), content)
        self._replay_tour_btn.setObjectName("secondaryButton")
        self._replay_tour_btn.setCursor(Qt.PointingHandCursor)
        self._replay_tour_btn.clicked.connect(self.replay_tour_requested.emit)
        help_layout.addWidget(self._replay_tour_btn, 0)
        self._ask_ai_explanation_btn = QPushButton(
            t("settings.help.ask_ai_explanation"), content
        )
        self._ask_ai_explanation_btn.setObjectName("secondaryButton")
        self._ask_ai_explanation_btn.setCursor(Qt.PointingHandCursor)
        self._ask_ai_explanation_btn.clicked.connect(
            self.ask_ai_explanation_requested.emit
        )
        help_layout.addWidget(self._ask_ai_explanation_btn, 0)
        self._replay_ai_btn = QPushButton(t("settings.help.replay_ai"), content)
        self._replay_ai_btn.setObjectName("secondaryButton")
        self._replay_ai_btn.setCursor(Qt.PointingHandCursor)
        self._replay_ai_btn.clicked.connect(self.replay_ai_tour_requested.emit)
        help_layout.addWidget(self._replay_ai_btn, 0)
        self._replay_automation_btn = QPushButton(
            t("settings.help.replay_automation"), content
        )
        self._replay_automation_btn.setObjectName("secondaryButton")
        self._replay_automation_btn.setCursor(Qt.PointingHandCursor)
        self._replay_automation_btn.clicked.connect(
            self.replay_automation_tour_requested.emit
        )
        help_layout.addWidget(self._replay_automation_btn, 0)
        self._feedback_btn = QPushButton(t("settings.help.feedback"), content)
        self._feedback_btn.setObjectName("secondaryButton")
        self._feedback_btn.setCursor(Qt.PointingHandCursor)
        self._feedback_btn.clicked.connect(self.feedback_requested.emit)
        help_layout.addWidget(self._feedback_btn, 0)
        layout.addWidget(help_section)

        self._status_label = QLabel("", content)
        self._status_label.setObjectName("mutedLabel")
        layout.addWidget(self._status_label)

        for card in content.findChildren(QFrame, "infoPanel"):
            apply_card_shadow(card)

        layout.addStretch()
        content.setMinimumWidth(420)
        content.setMinimumHeight(480)

        from app.ui.text_select import enable_label_text_selection

        enable_label_text_selection(self)

    def _make_card(
        self,
        parent: QWidget,
        title: str = "",
        hint: str = "",
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("infoPanel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)
        if title:
            title_label = QLabel(title, parent)
            title_label.setObjectName("sectionTitle")
            card_layout.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint, parent)
            hint_label.setObjectName("mutedLabel")
            hint_label.setWordWrap(True)
            card_layout.addWidget(hint_label)
        return card, card_layout

    def refresh(self) -> None:
        self._loading = True
        try:
            self._width_edit.setText(str(self._config.get("window_width", 1600)))
            self._height_edit.setText(str(self._config.get("window_height", 900)))
            if hasattr(self, "_minimize_toggle"):
                self._minimize_toggle.set_current(
                    0 if self._config.get("capture_minimize", True) else 1
                )
            self._notify_toggle.set_current(
                0 if self._config.get("show_save_notification", True) else 1
            )
            dur = int(self._config.get("notification_duration_sec", 5) or 5)
            dur_index = self._notify_duration.findData(dur)
            default_dur = self._notify_duration.findData(5)
            self._notify_duration.setCurrentIndex(
                dur_index if dur_index >= 0 else (default_dur if default_dur >= 0 else 0)
            )
            if hasattr(self, "_filename_panel"):
                self._filename_panel.set_folder(resolve_save_folder(self._config))
                self._filename_panel.set_template(
                    self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
                )
            if self._shortcut_value_labels:
                self._refresh_shortcut_labels()
        finally:
            self._loading = False

    def _refresh_shortcut_labels(self) -> None:
        bindings = load_shortcuts_from_config(self._config)
        for action_id, label in self._shortcut_value_labels.items():
            label.setText(format_shortcut_display(bindings.get(action_id)))

    def _on_change_shortcut(self, action_id: str) -> None:
        if self._loading:
            return
        dialog = ShortcutCaptureDialog(self)
        if dialog.exec() != ShortcutCaptureDialog.Accepted:
            return
        candidate = dialog.captured_shortcut()
        ok, err_key = validate_shortcut(candidate)
        if not ok or not candidate:
            QMessageBox.warning(
                self,
                t("common.warning"),
                t(err_key or "settings.shortcuts.error_invalid"),
            )
            return

        bindings = load_shortcuts_from_config(self._config)
        conflict = find_shortcut_conflict(action_id, candidate, bindings)
        if conflict is not None:
            QMessageBox.warning(
                self,
                t("common.warning"),
                t(
                    "settings.shortcuts.error_duplicate",
                    action=t(ACTION_LABEL_KEYS[conflict]),
                ),
            )
            return

        if bindings.get(action_id) == candidate:
            return

        bindings[action_id] = candidate
        apply_shortcuts_to_config(self._config, bindings)
        if self._persist():
            self._refresh_shortcut_labels()
            self.shortcuts_changed.emit()
            logger.info("Settings autosaved. shortcuts[%s]=%s", action_id, candidate)

    def _on_minimize_changed(self, index: int) -> None:
        if self._loading:
            return
        enabled = index == 0  # On is left
        if bool(self._config.get("capture_minimize", True)) == enabled:
            return
        self._config["capture_minimize"] = enabled
        # MainWindow reads this shared config value when Capture starts. Avoid
        # the broad settings_saved refresh here: synchronously refreshing the
        # whole shell from inside the toggle click could leave the footer
        # Capture control unable to complete its next click.
        if self._persist(notify=False):
            self._show_autosaved()
            logger.info("Settings autosaved. capture_minimize=%s", enabled)

    def _on_notify_changed(self, index: int) -> None:
        if self._loading:
            return
        enabled = index == 0  # On is left
        if bool(self._config.get("show_save_notification", True)) == enabled:
            return
        self._config["show_save_notification"] = enabled
        if self._persist():
            logger.info("Settings autosaved. show_save_notification=%s", enabled)

    def _on_notify_duration_changed(self, _index: int) -> None:
        if self._loading:
            return
        seconds = self._notify_duration.currentData()
        try:
            value = int(seconds)
        except (TypeError, ValueError):
            value = 3
        if int(self._config.get("notification_duration_sec", 5) or 5) == value:
            return
        self._config["notification_duration_sec"] = value
        if self._persist():
            logger.info("Settings autosaved. notification_duration_sec=%s", value)

    def _clear_status(self) -> None:
        self._status_label.setText("")

    def _show_autosaved(self) -> None:
        self._status_label.setText(t("settings.autosaved"))
        self._status_clear_timer.start()

    def _persist(self, *, notify: bool = True) -> bool:
        """Write config to disk and notify the shell. Returns False on failure."""
        try:
            save_config(self._config)
        except OSError as e:
            logger.exception("Failed to autosave settings: %s", e)
            QMessageBox.critical(
                self, t("common.error"), t("settings.save_failed", error=e)
            )
            return False
        if notify:
            self.settings_saved.emit()
            self._show_autosaved()
        return True

    def _on_filename_changed(self, template: str) -> None:
        if self._loading:
            return
        new_value = template or DEFAULT_FILENAME_TEMPLATE
        if self._config.get("filename_template") == new_value:
            return
        self._config["filename_template"] = new_value
        self._persist()

    def _autosave_window_size(self) -> None:
        if self._loading:
            return
        width_text = self._width_edit.text().strip()
        height_text = self._height_edit.text().strip()
        try:
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            QMessageBox.warning(
                self, t("common.warning"), t("settings.size_invalid")
            )
            self._loading = True
            try:
                self._width_edit.setText(
                    str(self._config.get("window_width", 1600))
                )
                self._height_edit.setText(
                    str(self._config.get("window_height", 900))
                )
            finally:
                self._loading = False
            return

        if (
            self._config.get("window_width") == width
            and self._config.get("window_height") == height
        ):
            return

        self._config["window_width"] = width
        self._config["window_height"] = height
        if self._persist():
            self.window_size_changed.emit()
            logger.info("Settings autosaved. Window: %sx%s", width, height)
