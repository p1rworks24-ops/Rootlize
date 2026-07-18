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
)

from app.config import save_config
from app.i18n import t
from app.ui.filename_rule_panel import FilenameRulePanel
from app.ui.icons import icon_folder
from app.ui.scroll_page import make_page_scroll
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.logger import setup_logger
from app.utils.save_folder import apply_screenshot_dir
from app.utils.workspace import resolve_save_folder

logger = setup_logger()


class SettingsPage(QWidget):
    """In-app settings page — changes autosave on select / edit commit."""

    settings_saved = Signal()

    def __init__(self, config: dict, app_root: Path, parent=None):
        super().__init__(parent)
        self._config = config
        self._app_root = app_root
        self._loading = False
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
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(t("settings.title"), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(t("settings.subtitle"), content)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

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
        self._width_edit.setText(str(self._config.get("window_width", 1100)))
        self._width_edit.editingFinished.connect(self._autosave_window_size)
        width_row.addWidget(self._width_edit)
        ui_layout.addLayout(width_row)

        height_row = QHBoxLayout()
        height_row.addWidget(QLabel(t("settings.window_height"), content))
        self._height_edit = QLineEdit(content)
        self._height_edit.setText(str(self._config.get("window_height", 720)))
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

    def refresh(self) -> None:
        self._loading = True
        try:
            self._path_edit.setText(self._config.get("screenshot_dir", "screenshots"))
            self._width_edit.setText(str(self._config.get("window_width", 1100)))
            self._height_edit.setText(str(self._config.get("window_height", 720)))
            self._filename_panel.set_folder(resolve_save_folder(self._config))
            self._filename_panel.set_template(
                self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
            )
        finally:
            self._loading = False

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
                    str(self._config.get("window_width", 1100))
                )
                self._height_edit.setText(
                    str(self._config.get("window_height", 720))
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
            logger.info("Settings autosaved. Window: %sx%s", width, height)
