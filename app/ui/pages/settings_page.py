from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
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
from app.ui.filename_rule_panel import FilenameRulePanel
from app.ui.icons import icon_folder
from app.ui.scroll_page import make_page_scroll
from app.ui.segmented_toggle import SegmentedToggle
from app.ui.shortcut_capture_dialog import ShortcutCaptureDialog
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.logger import setup_logger
from app.utils.save_folder import apply_screenshot_dir
from app.utils.workspace import resolve_save_folder

logger = setup_logger()


class SettingsPage(QWidget):
    """In-app settings page — changes autosave on select / edit commit."""

    settings_saved = Signal()
    # Emitted only when Window width/height are saved (triggers shell resize)
    window_size_changed = Signal()
    # Emitted when capture shortcuts change (shell re-registers hotkeys)
    shortcuts_changed = Signal()

    def __init__(self, config: dict, app_root: Path, parent=None):
        super().__init__(parent)
        self._config = config
        self._app_root = app_root
        self._loading = False
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
        layout.setSpacing(12)

        from app.ui.page_header import make_page_header

        layout.addWidget(
            make_page_header(content, t("settings.title"), t("settings.subtitle"))
        )

        autosave_hint = QLabel(t("settings.autosave_hint"), content)
        autosave_hint.setObjectName("settingsAutosaveHint")
        autosave_hint.setWordWrap(True)
        layout.addWidget(autosave_hint)

        save_section = QFrame(content)
        save_section.setObjectName("infoPanel")
        save_layout = QVBoxLayout(save_section)
        save_layout.setContentsMargins(16, 14, 16, 14)
        save_layout.setSpacing(8)

        save_title = QLabel(t("settings.save_folder"), content)
        save_title.setObjectName("sectionTitle")
        save_layout.addWidget(save_title)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(content)
        self._path_edit.setText(self._config.get("screenshot_dir", "screenshots"))
        self._path_edit.editingFinished.connect(self._autosave_path)
        path_row.addWidget(self._path_edit)

        browse_btn = QPushButton(t("common.browse"), content)
        browse_btn.setObjectName("secondaryButton")
        browse_btn.setIcon(icon_folder())
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        save_layout.addLayout(path_row)
        layout.addWidget(save_section)

        name_section = QFrame(content)
        name_section.setObjectName("infoPanel")
        name_layout = QVBoxLayout(name_section)
        # Match other settings cards: even inset around the rule list
        name_layout.setContentsMargins(16, 14, 16, 14)
        self._filename_panel = FilenameRulePanel(name_section)
        self._filename_panel.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._filename_panel.set_folder(resolve_save_folder(self._config))
        self._filename_panel.template_changed.connect(self._on_filename_changed)
        name_layout.addWidget(self._filename_panel)
        layout.addWidget(name_section)

        # Capture behavior (separate from UI window size)
        capture_section = QFrame(content)
        capture_section.setObjectName("infoPanel")
        capture_layout = QVBoxLayout(capture_section)
        capture_layout.setContentsMargins(16, 14, 16, 14)
        capture_layout.setSpacing(8)

        capture_title = QLabel(t("settings.capture_minimize"), content)
        capture_title.setObjectName("sectionTitle")
        capture_layout.addWidget(capture_title)

        minimize_hint = QLabel(t("settings.capture_minimize_hint"), content)
        minimize_hint.setObjectName("mutedLabel")
        minimize_hint.setWordWrap(True)
        capture_layout.addWidget(minimize_hint)

        self._minimize_toggle = SegmentedToggle(
            [
                t("settings.capture_minimize_on"),
                t("settings.capture_minimize_off"),
            ],
            content,
        )
        # 0 = On (left), 1 = Off (right) — default On
        self._minimize_toggle.set_current(
            0 if self._config.get("capture_minimize", True) else 1
        )
        self._minimize_toggle.changed.connect(self._on_minimize_changed)
        minimize_row = QHBoxLayout()
        minimize_row.addWidget(self._minimize_toggle)
        minimize_row.addStretch(1)
        capture_layout.addLayout(minimize_row)
        layout.addWidget(capture_section)

        # Notifications — app-owned floating toast
        notify_section = QFrame(content)
        notify_section.setObjectName("infoPanel")
        notify_layout = QVBoxLayout(notify_section)
        notify_layout.setContentsMargins(16, 14, 16, 14)
        notify_layout.setSpacing(8)

        notify_title = QLabel(t("settings.notifications"), content)
        notify_title.setObjectName("sectionTitle")
        notify_layout.addWidget(notify_title)

        notify_hint = QLabel(t("settings.notifications.hint"), content)
        notify_hint.setObjectName("mutedLabel")
        notify_hint.setWordWrap(True)
        notify_layout.addWidget(notify_hint)

        self._notify_toggle = SegmentedToggle(
            [
                t("settings.notifications.on"),
                t("settings.notifications.off"),
            ],
            content,
        )
        # 0 = On (left), 1 = Off (right) — default On
        self._notify_toggle.set_current(
            0 if self._config.get("show_save_notification", True) else 1
        )
        self._notify_toggle.changed.connect(self._on_notify_changed)
        notify_row = QHBoxLayout()
        notify_row.addWidget(self._notify_toggle)
        notify_row.addStretch(1)
        notify_layout.addLayout(notify_row)

        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel(t("settings.notifications.duration"), content))
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

        # Keyboard Shortcuts (app-wide capture hotkeys)
        shortcuts_section = QFrame(content)
        shortcuts_section.setObjectName("infoPanel")
        shortcuts_layout = QVBoxLayout(shortcuts_section)
        shortcuts_layout.setContentsMargins(16, 14, 16, 14)
        shortcuts_layout.setSpacing(10)

        shortcuts_title = QLabel(t("settings.shortcuts"), content)
        shortcuts_title.setObjectName("sectionTitle")
        shortcuts_layout.addWidget(shortcuts_title)

        shortcuts_hint = QLabel(t("settings.shortcuts.hint"), content)
        shortcuts_hint.setObjectName("mutedLabel")
        shortcuts_hint.setWordWrap(True)
        shortcuts_layout.addWidget(shortcuts_hint)

        bindings = load_shortcuts_from_config(self._config)
        for index, action_id in enumerate(SHORTCUT_ACTIONS):
            row = QFrame(shortcuts_section)
            row.setObjectName("shortcutRow")
            row_layout = QVBoxLayout(row)
            # Last row: no extra bottom pad under the divider look
            row_layout.setContentsMargins(0, 8, 0, 10 if index < len(SHORTCUT_ACTIONS) - 1 else 4)
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

        ui_section = QFrame(content)
        ui_section.setObjectName("infoPanel")
        ui_layout = QVBoxLayout(ui_section)
        ui_layout.setContentsMargins(16, 14, 16, 14)
        ui_layout.setSpacing(8)

        ui_title = QLabel(t("settings.ui"), content)
        ui_title.setObjectName("sectionTitle")
        ui_layout.addWidget(ui_title)

        width_row = QHBoxLayout()
        width_row.addWidget(QLabel(t("settings.window_width"), content))
        self._width_edit = QLineEdit(content)
        self._width_edit.setText(str(self._config.get("window_width", 1050)))
        self._width_edit.editingFinished.connect(self._autosave_window_size)
        width_row.addWidget(self._width_edit)
        ui_layout.addLayout(width_row)

        height_row = QHBoxLayout()
        height_row.addWidget(QLabel(t("settings.window_height"), content))
        self._height_edit = QLineEdit(content)
        self._height_edit.setText(str(self._config.get("window_height", 600)))
        self._height_edit.editingFinished.connect(self._autosave_window_size)
        height_row.addWidget(self._height_edit)
        ui_layout.addLayout(height_row)

        future_hint = QLabel(t("settings.future_hint"), content)
        future_hint.setObjectName("mutedLabel")
        future_hint.setWordWrap(True)
        ui_layout.addWidget(future_hint)
        layout.addWidget(ui_section)

        self._status_label = QLabel("", content)
        self._status_label.setObjectName("mutedLabel")
        layout.addWidget(self._status_label)

        layout.addStretch()
        content.setMinimumWidth(420)
        content.setMinimumHeight(480)

        from app.ui.text_select import enable_label_text_selection

        enable_label_text_selection(self)

    def refresh(self) -> None:
        self._loading = True
        try:
            self._path_edit.setText(self._config.get("screenshot_dir", "screenshots"))
            self._width_edit.setText(str(self._config.get("window_width", 1050)))
            self._height_edit.setText(str(self._config.get("window_height", 600)))
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
            self._filename_panel.set_folder(resolve_save_folder(self._config))
            self._filename_panel.set_template(
                self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
            )
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
        if self._persist():
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

    def browse_root_folder(self) -> None:
        """Public entry for Browse (Settings button / Home Root Folder gear)."""
        self._on_browse()

    def _on_browse(self) -> None:
        current_dir = self._path_edit.text()
        resolved_current = Path(current_dir)
        if not resolved_current.is_absolute():
            resolved_current = (self._app_root / resolved_current).resolve()

        selected = QFileDialog.getExistingDirectory(
            self,
            t("settings.select_directory"),
            str(resolved_current),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return

        selected_path = Path(selected)
        try:
            relative_path = selected_path.relative_to(self._app_root)
            self._path_edit.setText(str(relative_path))
        except ValueError:
            self._path_edit.setText(str(selected_path))
        self._autosave_path()

    def _autosave_path(self) -> None:
        if self._loading:
            return
        selected_path = self._path_edit.text().strip()
        if not selected_path:
            QMessageBox.warning(
                self, t("common.warning"), t("settings.path_empty")
            )
            self._path_edit.setText(
                self._config.get("screenshot_dir", "screenshots")
            )
            return

        if selected_path == str(self._config.get("screenshot_dir", "")).strip():
            return

        try:
            apply_screenshot_dir(self._config, self._app_root, selected_path)
            # apply_screenshot_dir already persisted; sync UI text + notify shell
            self._loading = True
            try:
                self._path_edit.setText(
                    self._config.get("screenshot_dir", selected_path)
                )
            finally:
                self._loading = False
            self.settings_saved.emit()
            self._show_autosaved()
            logger.info(
                "Settings autosaved. Directory: %s",
                self._config.get("screenshot_dir"),
            )
        except Exception as e:
            logger.exception("Failed to autosave screenshot dir: %s", e)
            QMessageBox.critical(
                self, t("common.error"), t("settings.save_failed", error=e)
            )
            self._loading = True
            try:
                self._path_edit.setText(
                    self._config.get("screenshot_dir", "screenshots")
                )
            finally:
                self._loading = False

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
                    str(self._config.get("window_width", 1050))
                )
                self._height_edit.setText(
                    str(self._config.get("window_height", 600))
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
