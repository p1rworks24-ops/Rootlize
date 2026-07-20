from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
)

# Soft floor so Settings defaults (e.g. 1050×600) are not also the drag minimum
_WINDOW_MIN_WIDTH = 720
_WINDOW_MIN_HEIGHT = 480


class _BottomBarScroll(QScrollArea):
    """Horizontal strip that must not inflate the main window minimum width."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, max(hint.height(), 88))

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 800), max(hint.height(), 88))

from app.config import save_config
from app.i18n import t
from app.models.detected_image import DetectedImage
from app.services.capture_modes import (
    CAPTURE_FULLSCREEN,
    CAPTURE_REGION,
    capture_mode_info,
    default_region_trigger,
    grab_fullscreen_image,
    next_capture_mode,
    normalize_capture_mode,
)
from app.services.app_hotkeys import AppHotkeyManager
from app.services.clipboard_watcher import ClipboardWatcher
from app.services.image_saver import ImageSaver
from app.services.metadata_service import MetadataService
from app.services.screenshot_session import ScreenshotSession
from app.services.shortcut_spec import (
    ACTION_FULLSCREEN_CAPTURE,
    ACTION_REGION_CAPTURE,
    load_shortcuts_from_config,
)
from app.ui.capture_mode_cycle import CaptureModeCycleButton
from app.ui.capture_panel_window import CapturePanelWindow
from app.ui.capture_settings import (
    CaptureTagCombo,
    CompactField,
    FilenameRuleCombo,
    UpwardComboBox,
    field_separator,
)
from app.ui.floating_toast import FloatingToastHost
from app.ui.icons import (
    icon_about,
    icon_ai,
    icon_organize,
    icon_fullscreen_capture,
    icon_home,
    icon_images,
    icon_region_capture,
    icon_save_folder_star,
    icon_settings,
    icon_tags,
)
from app.ui.pages.about_page import AboutPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.images_page import ImagesPage, THUMBNAIL_ICON_SIZE
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tags_page import TagsPage
from app.ui.pages.work_page import WorkPage
from app.ui.side_nav import SideNav
from app.ui.styles import APP_STYLE
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.save_folder import list_folder_names
from app.utils.snipping_toast import snipping_toast_suppressor
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.workspace import (
    DEFAULT_FOLDER,
    pick_folder_name,
    resolve_current_folder,
    resolve_save_folder,
    resolve_screenshot_root,
)

# Delay so minimize finishes before capture (keeps our window out of the shot).
_SNIP_HOTKEY_DELAY_MS = 250

PAGE_HOME = 0
PAGE_IMAGES = 1
PAGE_ORGANIZE = 2
PAGE_ACTION = PAGE_ORGANIZE  # backward-compatible alias
PAGE_TAGS = 3
PAGE_SETTINGS = 4
PAGE_ABOUT = 5

# (page_id, i18n key, icon factory, navAccent for per-item colors)
NAV_ITEMS = [
    (PAGE_HOME, "nav.home", icon_home, "home"),
    (PAGE_IMAGES, "nav.images", icon_images, "images"),
    (PAGE_ORGANIZE, "nav.organize", icon_organize, "organize"),
    (PAGE_TAGS, "nav.tags", icon_tags, "tags"),
    (PAGE_SETTINGS, "nav.settings", icon_settings, "settings"),
    (PAGE_ABOUT, "nav.about", icon_about, "about"),
]


class MainWindow(QMainWindow):
    """App shell: left navigation + stacked pages."""

    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        from app.paths import get_legacy_install_root

        # Used to resolve any remaining relative screenshot_dir paths.
        # User data (config/tags) lives under APPDATA — not this root.
        self._app_root = get_legacy_install_root()

        # Normalize legacy current_project → current_folder
        if not self._config.get("current_folder"):
            self._config["current_folder"] = resolve_current_folder(self._config)
        # Capture destination is independent from Images viewing folder
        if not str(self._config.get("save_folder") or "").strip():
            self._config["save_folder"] = resolve_current_folder(self._config)
        self._capture_mode = normalize_capture_mode(
            self._config.get("capture_mode")
        )
        self._config["capture_mode"] = self._capture_mode

        from app.branding import APP_NAME

        self.setWindowTitle(APP_NAME)
        from app.ui.app_icon import load_app_icon

        _icon = load_app_icon()
        if not _icon.isNull():
            self.setWindowIcon(_icon)
        self.resize(
            config.get("window_width", 1050),
            config.get("window_height", 600),
        )
        self.setStyleSheet(APP_STYLE)

        self._metadata_service = MetadataService()
        self._thumbnail_cache = ThumbnailCache(size=THUMBNAIL_ICON_SIZE)
        self._image_saver = ImageSaver(config, self._metadata_service, self._app_root)
        self._screenshot_session = ScreenshotSession(parent=self)
        self._screenshot_session.finished.connect(self._on_screenshot_session_finished)
        self._pending_recent_path: str | None = None
        self._page_before_screenshot = PAGE_HOME
        self._minimized_for_capture = False
        self._keep_minimized_after_capture = False
        self._restore_panel_after_capture = False
        self._capture_from_panel = False
        self._capture_panel_window: CapturePanelWindow | None = None
        self._pre_capture_geometry: bytes | None = None
        self._pre_capture_state = Qt.WindowNoState

        self._init_ui()
        # Re-apply after layout builds — child mins can inflate the first resize()
        self._apply_configured_window_size()
        from app.ui.text_select import enable_label_text_selection

        enable_label_text_selection(self)

        # Suppress Snipping Tool clipboard toasts while this app is running
        snipping_toast_suppressor.enter()

        interval_ms = config.get("clipboard_check_interval_ms", 500)
        self._clipboard_watcher = ClipboardWatcher(
            interval_ms=interval_ms,
            on_image_detected=self._on_image_detected,
        )
        self._clipboard_watcher.start()

        # App-lifetime capture hotkeys (unregistered on close).
        # Stay disarmed until splash finishes so startup cannot auto-Capture.
        self._hotkey_manager = AppHotkeyManager(self)
        self._hotkey_manager.activated.connect(self._on_hotkey_activated)
        self._hotkey_manager.start(QApplication.instance())
        self._reload_capture_hotkeys()

        # App-owned floating toast (not Windows notification center)
        self._toast_host = FloatingToastHost(self)

        self._show_page(PAGE_HOME)

    def arm_capture_hotkeys(self) -> None:
        """Enable global Capture shortcuts after startup UI is ready."""
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.set_armed(True)

    def _init_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._side_nav = SideNav(self)
        # Home → Images → Organize → Tags, then AI placeholder, then Settings → About
        for page_id, label_key, icon_fn, accent in NAV_ITEMS[:4]:
            self._side_nav.add_nav_item(
                page_id, t(label_key), icon_fn(), accent=accent
            )
        self._side_nav.add_placeholder_item(
            t("nav.ai"),
            icon_ai(muted=True),
            tooltip=t("nav.ai_tooltip"),
            accent="ai",
        )
        for page_id, label_key, icon_fn, accent in NAV_ITEMS[4:]:
            self._side_nav.add_nav_item(
                page_id, t(label_key), icon_fn(), accent=accent
            )
        self._side_nav.add_stretch()
        self._side_nav.page_selected.connect(self._show_page)
        root.addWidget(self._side_nav)

        content_column = QWidget(self)
        content_layout = QVBoxLayout(content_column)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._stack = QStackedWidget(self)

        self._home_page = HomePage(
            self._config,
            self._metadata_service,
            self._thumbnail_cache,
            self._app_root,
            self,
        )
        self._home_page.open_images_requested.connect(
            lambda: self._show_page(PAGE_IMAGES)
        )
        self._home_page.open_action_requested.connect(
            lambda: self._show_page(PAGE_ORGANIZE)
        )
        self._home_page.open_tags_requested.connect(
            lambda: self._show_page(PAGE_TAGS)
        )
        self._home_page.open_settings_requested.connect(
            lambda: self._show_page(PAGE_SETTINGS)
        )

        self._images_page = ImagesPage(
            self._config,
            self._metadata_service,
            self._thumbnail_cache,
            self._app_root,
            self,
        )
        self._images_page.folder_changed.connect(self._on_images_folder_changed)

        self._work_page = WorkPage(
            self._config,
            self._metadata_service,
            self._thumbnail_cache,
            self._app_root,
            self,
        )
        self._work_page.tags_changed.connect(self._on_work_tags_changed)
        self._work_page.images_changed.connect(self._on_work_images_changed)
        self._work_page.folder_changed.connect(self._on_work_folder_changed)

        self._tags_page = TagsPage(
            self._metadata_service,
            self._app_root,
            self._config,
            self,
        )
        self._tags_page.tags_changed.connect(self._on_tags_changed)
        self._images_page.tags_changed.connect(self._on_images_tags_changed)

        self._settings_page = SettingsPage(self._config, self._app_root, self)
        self._settings_page.settings_saved.connect(self._on_settings_saved)
        self._settings_page.shortcuts_changed.connect(self._reload_capture_hotkeys)
        self._settings_page.window_size_changed.connect(
            self._apply_window_size_from_settings
        )
        self._home_page.browse_root_requested.connect(
            self._settings_page.browse_root_folder
        )

        self._about_page = AboutPage(self)

        self._stack.addWidget(self._home_page)  # 0
        self._stack.addWidget(self._images_page)  # 1
        self._stack.addWidget(self._work_page)  # 2
        self._stack.addWidget(self._tags_page)  # 3
        self._stack.addWidget(self._settings_page)  # 4
        self._stack.addWidget(self._about_page)  # 5

        content_layout.addWidget(self._stack, stretch=1)

        # Capture toolbar — separate controls, aligned with settings fields
        bottom_host = QWidget(self)
        bottom_host.setObjectName("globalBottomBarHost")
        bottom_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_host_layout = QVBoxLayout(bottom_host)
        bottom_host_layout.setContentsMargins(16, 10, 16, 12)
        bottom_host_layout.setSpacing(0)

        # Horizontal scroll when the window is narrower than the capture chrome
        bottom_scroll = _BottomBarScroll(bottom_host)
        bottom_scroll.setObjectName("globalBottomBarScroll")
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setFrameShape(QFrame.NoFrame)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bottom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bottom_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_scroll.setMinimumHeight(88)
        bottom_scroll.setMinimumWidth(0)

        bottom_bar = QWidget(bottom_scroll)
        bottom_bar.setObjectName("globalBottomBar")
        bottom_bar.setMinimumWidth(0)
        bottom_bar_layout = QHBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(18, 12, 18, 12)
        bottom_bar_layout.setSpacing(12)
        bottom_bar_layout.setAlignment(Qt.AlignVCenter)
        bottom_bar_layout.addStretch(1)

        # 1) Capture button (primary action)
        self._capture_btn = QToolButton(bottom_bar)
        self._capture_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self._capture_btn.setCursor(Qt.PointingHandCursor)
        self._capture_btn.setFixedSize(78, 64)
        self._capture_btn.setIconSize(QSize(20, 20))
        self._capture_btn.clicked.connect(self._on_capture_clicked)
        self._capture_btn_fx = QGraphicsOpacityEffect(self._capture_btn)
        self._capture_btn.setGraphicsEffect(self._capture_btn_fx)
        bottom_bar_layout.addWidget(self._capture_btn, 0, Qt.AlignVCenter)

        # 2) Mode cycle (own control — CompactField-like height)
        self._cycle_mode_btn = CaptureModeCycleButton(bottom_bar)
        self._cycle_mode_btn.clicked.connect(self._cycle_capture_mode)
        bottom_bar_layout.addWidget(self._cycle_mode_btn, 0, Qt.AlignVCenter)

        # 3) Mode description (own column — mirrors CompactField label/value)
        desc_card = QFrame(bottom_bar)
        desc_card.setObjectName("captureModeDescCard")
        desc_card.setMinimumWidth(128)
        desc_card.setMaximumWidth(168)
        desc_card_layout = QVBoxLayout(desc_card)
        desc_card_layout.setContentsMargins(0, 0, 0, 0)
        desc_card_layout.setSpacing(4)
        self._capture_desc_caption = QLabel(t("shell.capture.mode_caption"), desc_card)
        self._capture_desc_caption.setObjectName("captureModeDescCaption")
        desc_card_layout.addWidget(self._capture_desc_caption)
        self._capture_desc = QLabel(desc_card)
        self._capture_desc.setObjectName("captureModeDescription")
        self._capture_desc.setWordWrap(True)
        self._capture_desc.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # No QGraphicsOpacityEffect on description — it vanishes on window resize
        desc_card_layout.addWidget(self._capture_desc, stretch=1)
        bottom_bar_layout.addWidget(desc_card, 0, Qt.AlignVCenter)

        # Soft separator before settings (keeps capture controls distinct)
        bar_divider = QFrame(bottom_bar)
        bar_divider.setObjectName("captureBarDivider")
        bar_divider.setFixedWidth(1)
        bar_divider.setFixedHeight(48)
        bottom_bar_layout.addSpacing(4)
        bottom_bar_layout.addWidget(bar_divider, 0, Qt.AlignVCenter)
        bottom_bar_layout.addSpacing(4)

        # 4) Settings fields
        settings_strip = QFrame(bottom_bar)
        settings_strip.setObjectName("captureSettingsStrip")
        settings_strip.setMinimumWidth(0)
        settings_strip.setMaximumWidth(640)
        settings_strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        strip_layout = QHBoxLayout(settings_strip)
        strip_layout.setContentsMargins(14, 8, 14, 8)
        strip_layout.setSpacing(12)
        strip_layout.setAlignment(Qt.AlignVCenter)

        self._folder_combo = UpwardComboBox(settings_strip)
        self._folder_combo.setCursor(Qt.PointingHandCursor)
        self._folder_combo.setToolTip(t("shell.save_destination_tooltip"))
        self._folder_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._folder_combo.setMinimumWidth(110)
        self._folder_combo.activated.connect(self._on_toolbar_folder_chosen)
        strip_layout.addWidget(
            CompactField(
                t("shell.save_destination"),
                self._folder_combo,
                settings_strip,
                leading_icon=icon_save_folder_star(size=12),
            ),
            stretch=1,
        )
        strip_layout.addWidget(field_separator(settings_strip))

        self._filename_combo = FilenameRuleCombo(settings_strip)
        self._filename_combo.template_changed.connect(self._on_filename_template_changed)
        self._filename_field = CompactField(
            t("shell.save_filename_title"),
            self._filename_combo,
            settings_strip,
        )
        self._filename_combo.preview_changed.connect(self._filename_field.set_hint)
        strip_layout.addWidget(self._filename_field, stretch=1)
        strip_layout.addWidget(field_separator(settings_strip))

        self._capture_tag_combo = CaptureTagCombo(
            self._metadata_service, self._app_root, settings_strip
        )
        self._capture_tag_combo.set_tags(list(self._config.get("capture_tags") or []))
        self._capture_tag_combo.tags_changed.connect(self._on_capture_tags_changed)
        strip_layout.addWidget(
            CompactField(
                t("shell.capture_tags"), self._capture_tag_combo, settings_strip
            ),
            stretch=1,
        )

        bottom_bar_layout.addWidget(settings_strip, 0, Qt.AlignVCenter)

        # Capture Panel opener — button + short hint (matches CompactField rhythm)
        panel_field = QWidget(bottom_bar)
        panel_field.setObjectName("capturePanelField")
        panel_field_layout = QVBoxLayout(panel_field)
        panel_field_layout.setContentsMargins(0, 0, 0, 0)
        panel_field_layout.setSpacing(2)
        panel_field_layout.setAlignment(Qt.AlignTop)

        self._capture_panel_btn = QPushButton(
            t("shell.capture_panel.button"), panel_field
        )
        self._capture_panel_btn.setObjectName("capturePanelPopOutButton")
        self._capture_panel_btn.setCursor(Qt.PointingHandCursor)
        self._capture_panel_btn.setToolTip(t("shell.capture_panel.pop_out_tooltip"))
        self._capture_panel_btn.clicked.connect(self._toggle_capture_panel)
        panel_field_layout.addWidget(self._capture_panel_btn)

        panel_hint = QLabel(t("shell.capture_panel.hint"), panel_field)
        panel_hint.setObjectName("capturePanelFieldHint")
        panel_hint.setWordWrap(True)
        panel_hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        panel_field_layout.addWidget(panel_hint)

        bottom_bar_layout.addWidget(panel_field, 0, Qt.AlignVCenter)

        bottom_bar_layout.addStretch(1)
        bottom_scroll.setWidget(bottom_bar)
        bottom_host_layout.addWidget(bottom_scroll)

        # Fixed footer — page content scrolls; bar scrolls horizontally when narrow
        content_layout.addWidget(bottom_host, stretch=0)

        self._mode_fade = QParallelAnimationGroup(self)
        self._mode_fade_gen = 0
        self._refresh_capture_mode_ui(animate=False)

        root.addWidget(content_column, stretch=1)
        self.setCentralWidget(central)

        self._refresh_folder_selector()
        self._filename_combo.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._capture_tag_combo.set_tags(list(self._config.get("capture_tags") or []))
        # Ensure Settings page widgets mirror the last-used config on launch
        self._settings_page.refresh()

    def _persist_runtime_settings(self) -> None:
        """Write last-used shell settings so the next launch restores them.

        Window size is owned by Settings (default 1050×600) — do not overwrite
        it from the live geometry here.
        """
        self._config["capture_mode"] = self._capture_mode
        self._config["save_folder"] = resolve_save_folder(self._config)
        self._config["current_folder"] = resolve_current_folder(self._config)
        self._config["filename_template"] = (
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._config["capture_tags"] = list(self._config.get("capture_tags") or [])
        try:
            save_config(self._config)
        except OSError:
            pass

    def _on_capture_tags_changed(self, tags: list) -> None:
        self._config["capture_tags"] = list(tags)
        try:
            save_config(self._config)
        except OSError:
            pass
        self._image_saver.update_config(self._config)
        if self._capture_panel_window is not None:
            self._capture_panel_window.sync_capture_tags(list(tags))
        # Keep toolbar combo aligned when the panel edits tags
        self._capture_tag_combo.blockSignals(True)
        self._capture_tag_combo.set_tags(list(tags))
        self._capture_tag_combo.blockSignals(False)

    def _on_filename_template_changed(self, template: str) -> None:
        self._config["filename_template"] = template or DEFAULT_FILENAME_TEMPLATE
        try:
            save_config(self._config)
        except OSError:
            pass
        self._image_saver.update_config(self._config)
        if self._capture_panel_window is not None:
            self._capture_panel_window.sync_filename_template(
                self._config["filename_template"]
            )
        self._filename_combo.blockSignals(True)
        self._filename_combo.set_template(self._config["filename_template"])
        self._filename_combo.blockSignals(False)

    def _refresh_folder_selector(self) -> None:
        """Rebuild the save-destination folder combo from the screenshot root."""
        names = list_folder_names(self._config, self._app_root)
        current = resolve_save_folder(self._config)
        if names and current not in names:
            current = pick_folder_name(names)
            self._config["save_folder"] = current
            try:
                save_config(self._config)
            except OSError:
                pass
            self._image_saver.update_config(self._config)

        self._folder_combo.blockSignals(True)
        self._folder_combo.clear()
        if not names:
            self._folder_combo.addItem(t("shell.save_destination_empty"), "")
            self._folder_combo.setEnabled(False)
        else:
            self._folder_combo.setEnabled(True)
            for name in names:
                self._folder_combo.addItem(name, name)
            index = self._folder_combo.findData(current)
            self._folder_combo.setCurrentIndex(index if index >= 0 else 0)
        self._folder_combo.blockSignals(False)
        folder = resolve_save_folder(self._config) or DEFAULT_FOLDER
        if hasattr(self, "_filename_combo"):
            self._filename_combo.set_folder(folder)
        self._sync_capture_panel_settings()

    def _apply_save_folder(self, name: str) -> None:
        """Persist save folder and keep toolbar / panel / saver in sync."""
        if not name:
            return
        # Save folder only — do not change Images viewing folder
        self._config["save_folder"] = str(name)
        try:
            save_config(self._config)
        except OSError:
            pass
        self._image_saver.update_config(self._config)
        self._filename_combo.set_folder(str(name))
        # Refresh ★ marker on Viewing folder tree
        self._images_page.refresh_save_folder_marker()
        if self._capture_panel_window is not None:
            self._capture_panel_window.sync_folder_selector(
                list_folder_names(self._config, self._app_root),
                str(name),
            )

    def _on_toolbar_folder_chosen(self, index: int) -> None:
        name = self._folder_combo.itemData(index)
        if not name:
            name = self._folder_combo.itemText(index)
        self._apply_save_folder(str(name) if name else "")

    def _on_panel_folder_chosen(self, name: str) -> None:
        self._apply_save_folder(name)
        # Keep main toolbar combo selected
        index = self._folder_combo.findData(name)
        if index >= 0:
            self._folder_combo.blockSignals(True)
            self._folder_combo.setCurrentIndex(index)
            self._folder_combo.blockSignals(False)

    def _sync_capture_panel_settings(self) -> None:
        panel = self._capture_panel_window
        if panel is None:
            return
        names = list_folder_names(self._config, self._app_root)
        current = resolve_save_folder(self._config) or DEFAULT_FOLDER
        panel.sync_folder_selector(names, current)
        panel.sync_filename_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        panel.sync_capture_tags(list(self._config.get("capture_tags") or []))

    def _show_page(self, page_id: int) -> None:
        self._stack.setCurrentIndex(page_id)
        self._side_nav.set_current_page(page_id)
        self._refresh_folder_selector()

        if page_id == PAGE_HOME:
            self._home_page.refresh()
        elif page_id == PAGE_IMAGES:
            self._images_page.refresh()
            if self._pending_recent_path:
                self._images_page.select_image_path(self._pending_recent_path)
                self._pending_recent_path = None
        elif page_id == PAGE_ORGANIZE:
            self._work_page.refresh()
        elif page_id == PAGE_TAGS:
            self._tags_page.refresh()
        elif page_id == PAGE_SETTINGS:
            self._settings_page.refresh()
        elif page_id == PAGE_ABOUT:
            pass

    def _on_images_folder_changed(self, _name: str = "") -> None:
        # Viewing folder changed — keep save_folder as-is; only refresh combo names
        self._refresh_folder_selector()
        self._home_page.refresh()
        if self._stack.currentIndex() == PAGE_ORGANIZE:
            self._work_page.refresh()

    def _on_tags_changed(self) -> None:
        self._images_page.refresh()
        self._refresh_folder_selector()
        self._capture_tag_combo.reload_choices(self._capture_tag_combo.tags())
        if self._capture_panel_window is not None:
            self._capture_panel_window.reload_tag_choices()
        if self._stack.currentIndex() == PAGE_ORGANIZE:
            self._work_page.refresh()

    def _on_images_tags_changed(self) -> None:
        self._tags_page.refresh()
        self._capture_tag_combo.reload_choices(self._capture_tag_combo.tags())
        if self._capture_panel_window is not None:
            self._capture_panel_window.reload_tag_choices()
        if self._stack.currentIndex() == PAGE_ORGANIZE:
            self._work_page.refresh()

    def _on_work_folder_changed(self, _name: str = "") -> None:
        """Viewing folder changed from Organize — sync Images / Home without reloading Organize."""
        self._refresh_folder_selector()
        self._home_page.refresh()
        self._images_page.on_folder_changed()

    def _on_work_tags_changed(self) -> None:
        self._tags_page.refresh()
        self._images_page.refresh()
        self._capture_tag_combo.reload_choices(self._capture_tag_combo.tags())
        if self._capture_panel_window is not None:
            self._capture_panel_window.reload_tag_choices()

    def _on_work_images_changed(self) -> None:
        self._images_page.refresh()
        self._home_page.refresh()

    def _on_settings_saved(self) -> None:
        self._image_saver.update_config(self._config)
        self._metadata_service.invalidate_cache()
        self._thumbnail_cache.clear()
        self._refresh_folder_selector()
        self._filename_combo.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._settings_page.refresh()
        self._images_page.on_folder_changed()
        self._work_page.refresh()
        self._home_page.refresh()

    def _apply_window_size_from_settings(self) -> None:
        """Apply configured size only when the user edits Window width/height."""
        self._apply_configured_window_size()

    def _apply_configured_window_size(self) -> None:
        """Honor Settings size without locking that size as the drag minimum."""
        try:
            width = int(self._config.get("window_width", 1050) or 1050)
        except (TypeError, ValueError):
            width = 1050
        try:
            height = int(self._config.get("window_height", 600) or 600)
        except (TypeError, ValueError):
            height = 600
        self.setMinimumSize(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        self.resize(max(width, _WINDOW_MIN_WIDTH), max(height, _WINDOW_MIN_HEIGHT))

    def _on_capture_clicked(self) -> None:
        """Toolbar Capture — defer so we are not inside the mouse-press stack."""
        # Mode-cycle fade can leave opacity low; restore hit-target chrome first
        self._capture_btn_fx.setOpacity(1.0)
        mode = normalize_capture_mode(self._capture_mode)
        if mode == CAPTURE_FULLSCREEN:
            QTimer.singleShot(0, lambda: self._capture_fullscreen(from_panel=False))
        else:
            QTimer.singleShot(0, lambda: self._capture_region(from_panel=False))

    def _capture_region(self, *, from_panel: bool = False) -> None:
        """Region Capture — shared by toolbar button, panel, and shortcut."""
        self._start_capture_session(CAPTURE_REGION, from_panel=from_panel)

    def _capture_fullscreen(self, *, from_panel: bool = False) -> None:
        """Full Screen Capture — shared by toolbar button, panel, and shortcut."""
        self._start_capture_session(CAPTURE_FULLSCREEN, from_panel=from_panel)

    def _on_hotkey_activated(self, action_id: str) -> None:
        if action_id == ACTION_REGION_CAPTURE:
            self._capture_region(from_panel=False)
        elif action_id == ACTION_FULLSCREEN_CAPTURE:
            self._capture_fullscreen(from_panel=False)

    def _reload_capture_hotkeys(self) -> None:
        """Register shortcuts from config (startup + Settings change)."""
        bindings = load_shortcuts_from_config(self._config)
        self._config["shortcuts"] = dict(bindings)
        self._hotkey_manager.set_bindings(bindings)

    def _on_panel_capture_clicked(self) -> None:
        """Panel Capture — same mode handlers as the toolbar (deferred)."""
        mode = normalize_capture_mode(self._capture_mode)
        if mode == CAPTURE_FULLSCREEN:
            QTimer.singleShot(0, lambda: self._capture_fullscreen(from_panel=True))
        else:
            QTimer.singleShot(0, lambda: self._capture_region(from_panel=True))

    def _ensure_capture_panel(self) -> CapturePanelWindow:
        if self._capture_panel_window is None:
            panel = CapturePanelWindow(
                metadata_service=self._metadata_service,
                app_root=self._app_root,
            )
            panel.setStyleSheet(APP_STYLE)
            panel.capture_clicked.connect(self._on_panel_capture_clicked)
            panel.mode_cycle_clicked.connect(self._cycle_capture_mode)
            panel.folder_chosen.connect(self._on_panel_folder_chosen)
            panel.filename_template_changed.connect(self._on_filename_template_changed)
            panel.capture_tags_changed.connect(self._on_capture_tags_changed)
            panel.settings_page_requested.connect(self._sync_capture_panel_settings)
            panel.closed.connect(self._on_capture_panel_closed)
            self._capture_panel_window = panel
            self._sync_capture_panel_settings()
        return self._capture_panel_window

    def _on_capture_panel_closed(self) -> None:
        self._restore_panel_after_capture = False

    def _toggle_capture_panel(self) -> None:
        """Show / raise the independent always-on-top Capture Panel (150×150)."""
        panel = self._ensure_capture_panel()
        panel.apply_mode(self._capture_mode)
        self._sync_capture_panel_settings()
        if panel.isVisible():
            panel.raise_()
            panel.activateWindow()
            return
        panel.show_panel()

    def _cycle_capture_mode(self) -> None:
        self._capture_mode = next_capture_mode(self._capture_mode)
        self._config["capture_mode"] = self._capture_mode
        try:
            save_config(self._config)
        except OSError:
            pass
        self._refresh_capture_mode_ui(animate=True)

    def _apply_capture_mode_chrome(self) -> None:
        info = capture_mode_info(self._capture_mode)
        icon = (
            icon_fullscreen_capture()
            if info.mode_id == CAPTURE_FULLSCREEN
            else icon_region_capture()
        )
        # Two-line label keeps the near-square button readable
        label = t(info.label_key).replace(" Capture", "\nCapture")
        if "\n" not in label and " " in label:
            parts = label.split(" ", 1)
            label = f"{parts[0]}\n{parts[1]}"
        self._capture_btn.setText(label)
        self._capture_btn.setIcon(icon)
        self._capture_btn.setToolTip(t(info.tooltip_key))
        self._capture_btn.setObjectName(info.button_object_name)
        style = self._capture_btn.style()
        style.unpolish(self._capture_btn)
        style.polish(self._capture_btn)
        self._capture_btn.update()
        # Caption = mode name; body = short how-to (mode-colored)
        mode_name = t(info.label_key).replace(" Capture", "")
        self._capture_desc_caption.setText(mode_name)
        self._capture_desc.setText(t(info.description_key))
        mode_attr = (
            "fullscreen" if info.mode_id == CAPTURE_FULLSCREEN else "region"
        )
        for widget in (self._capture_desc_caption, self._capture_desc):
            widget.setProperty("mode", mode_attr)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        if self._capture_panel_window is not None:
            self._capture_panel_window.apply_mode(self._capture_mode)

    def _capture_mode_opacity_effects(self) -> list[QGraphicsOpacityEffect]:
        effects = [self._capture_btn_fx]
        panel = self._capture_panel_window
        if panel is not None:
            effects.append(panel.capture_btn_opacity_effect)
        return effects

    def _refresh_capture_mode_ui(self, *, animate: bool = False) -> None:
        effects = self._capture_mode_opacity_effects()
        if not animate:
            for fx in effects:
                fx.setOpacity(1.0)
            self._apply_capture_mode_chrome()
            return

        if self._mode_fade.state() == QParallelAnimationGroup.Running:
            self._mode_fade.stop()

        self._mode_fade_gen += 1
        gen = self._mode_fade_gen
        self._mode_fade = QParallelAnimationGroup(self)
        for fx in effects:
            anim = QPropertyAnimation(fx, b"opacity", self)
            anim.setDuration(180)
            anim.setStartValue(max(fx.opacity(), 0.25))
            anim.setEndValue(0.08)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._mode_fade.addAnimation(anim)

        def _swap_and_fade_in() -> None:
            if gen != self._mode_fade_gen:
                return
            self._apply_capture_mode_chrome()
            fade_in = QParallelAnimationGroup(self)
            for fx in self._capture_mode_opacity_effects():
                anim_in = QPropertyAnimation(fx, b"opacity", self)
                anim_in.setDuration(260)
                anim_in.setStartValue(0.08)
                anim_in.setEndValue(1.0)
                anim_in.setEasingCurve(QEasingCurve.InOutCubic)
                fade_in.addAnimation(anim_in)
            self._mode_fade_in = fade_in
            fade_in.start()

        self._mode_fade.finished.connect(_swap_and_fade_in)
        self._mode_fade.start()

    def _start_capture_session(
        self, mode: str | None = None, *, from_panel: bool = False
    ) -> None:
        """Start a capture; mode only changes how the image is obtained."""
        if self._screenshot_session.is_active:
            return

        mode = normalize_capture_mode(mode or self._capture_mode)
        self._page_before_screenshot = self._stack.currentIndex()
        self._restore_panel_after_capture = False
        self._capture_from_panel = from_panel
        self._minimized_for_capture = False
        # Snapshot before we optionally minimize for the shot
        self._keep_minimized_after_capture = self.isMinimized()
        self._pre_capture_geometry = None
        self._pre_capture_state = Qt.WindowNoState

        panel = self._capture_panel_window
        if from_panel:
            # Panel shot: leave the main window exactly as-is (shown or minimized)
            if panel is not None and panel.isVisible():
                panel.hide_for_capture()
                self._restore_panel_after_capture = True
            # Fullscreen grab needs a beat after the panel hides; region snip too
            delay_ms = 80 if mode == CAPTURE_FULLSCREEN else 40
        else:
            self._minimized_for_capture = bool(
                self._config.get("capture_minimize", True)
            )
            if panel is not None and panel.isVisible():
                # Keep an open panel out of a main-bar shot
                panel.hide_for_capture()
                self._restore_panel_after_capture = True
            if self._minimized_for_capture:
                # Remember size/state so showNormal() does not snap to defaults
                self._pre_capture_geometry = self.saveGeometry()
                self._pre_capture_state = self.windowState()
                self.showMinimized()
                delay_ms = _SNIP_HOTKEY_DELAY_MS
            else:
                delay_ms = 80 if mode == CAPTURE_FULLSCREEN else 40

        self._screenshot_session.start(mode)
        QTimer.singleShot(
            delay_ms,
            lambda m=mode: self._run_capture_mode(m),
        )

    def _start_screenshot_session(self) -> None:
        """Backward-compatible alias — uses the currently selected capture mode."""
        self._start_capture_session(self._capture_mode)

    def _run_capture_mode(self, mode: str) -> None:
        if not self._screenshot_session.is_active:
            return
        if mode == CAPTURE_FULLSCREEN:
            self._run_fullscreen_capture()
            return
        # Default / region — OS snipping UI; clipboard watcher → ImageSaver
        default_region_trigger()

    def _run_fullscreen_capture(self) -> None:
        # Flush pending hide/minimize so the grab does not race the UI
        QApplication.processEvents()
        image = grab_fullscreen_image()
        if image is None or image.isNull():
            self._screenshot_session.complete()
            return
        detected = DetectedImage(
            image=image,
            width=image.width(),
            height=image.height(),
            detected_at=datetime.now(),
        )
        # Same save path as clipboard / region captures
        self._on_image_detected(detected)

    def _restore_window_after_capture(self, *, activate: bool = False) -> None:
        """Restore pre-capture geometry/state (avoid snapping to default size)."""
        geo = self._pre_capture_geometry
        state = self._pre_capture_state
        self._pre_capture_geometry = None
        self._pre_capture_state = Qt.WindowNoState
        # Never steal focus for save toasts — restore visibility only when asked
        if not activate:
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        try:
            if geo:
                self.restoreGeometry(geo)
            if self.isMinimized():
                if state & Qt.WindowMaximized:
                    self.showMaximized()
                else:
                    self.showNormal()
            elif state & Qt.WindowMaximized and not self.isMaximized():
                self.showMaximized()
        finally:
            if not activate:
                self.setAttribute(Qt.WA_ShowWithoutActivating, False)

    def _finish_capture_session_ui(self) -> None:
        """Refresh pages / panel after a capture — never raise or activate the shell."""
        self._home_page.refresh()
        self._images_page.refresh()
        if self._restore_panel_after_capture and self._capture_panel_window is not None:
            self._restore_panel_after_capture = False
            panel = self._capture_panel_window
            panel.apply_mode(self._capture_mode)
            panel.show_panel()
        else:
            self._restore_panel_after_capture = False

    def _on_screenshot_session_finished(self) -> None:
        from_panel = self._capture_from_panel
        self._capture_from_panel = False

        if from_panel:
            # Keep main window state unchanged — only refresh data + restore panel
            self._finish_capture_session_ui()
            return

        stay_minimized = self._keep_minimized_after_capture
        self._keep_minimized_after_capture = False

        if stay_minimized:
            # Already minimized before capture — stay minimized (toast is independent)
            self._minimized_for_capture = False
            self._pre_capture_geometry = None
            self._pre_capture_state = Qt.WindowNoState
            self._finish_capture_session_ui()
            return

        if self._minimized_for_capture:
            # Un-minimize for capture-minimize UX without stealing foreground
            self._restore_window_after_capture(activate=False)
        self._minimized_for_capture = False
        # Toast / save must not raise_() or activateWindow()
        self._show_page(self._page_before_screenshot)
        self._finish_capture_session_ui()

    def _on_image_detected(self, detected: DetectedImage) -> None:
        saved_path = self._image_saver.save_image(detected.image, detected.detected_at)
        if saved_path is not None:
            self._images_page.add_saved_image(saved_path)
            self._home_page.refresh()
            # End capture session before toast so restore (if any) is not tied to notify
            if self._screenshot_session.is_active:
                self._screenshot_session.complete()
            self._show_save_success_toast(saved_path)
        else:
            if self._screenshot_session.is_active:
                self._screenshot_session.complete()
            self._show_save_error_toast(
                self._image_saver.last_error
                or t("toast.save_failed_generic")
            )

    def _notification_duration_ms(self) -> int:
        try:
            seconds = int(self._config.get("notification_duration_sec", 5) or 5)
        except (TypeError, ValueError):
            seconds = 5
        return max(1, seconds) * 1000

    def _show_save_success_toast(self, saved_path: Path) -> None:
        if not bool(self._config.get("show_save_notification", True)):
            return
        folder = resolve_save_folder(self._config) or DEFAULT_FOLDER
        root = resolve_screenshot_root(
            self._config.get("screenshot_dir", "screenshots"),
            self._app_root,
        )
        project = root.name or "Root"
        self._toast_host.show_success(
            filename=saved_path.name,
            project=project,
            folder=folder,
            duration_ms=self._notification_duration_ms(),
        )

    def _show_save_error_toast(self, message: str) -> None:
        if not bool(self._config.get("show_save_notification", True)):
            return
        self._toast_host.show_error(
            message=message,
            duration_ms=self._notification_duration_ms(),
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_runtime_settings()
        snipping_toast_suppressor.exit()
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.stop()
        if hasattr(self, "_toast_host"):
            self._toast_host.shutdown()
        if self._capture_panel_window is not None:
            self._capture_panel_window.close()
            self._capture_panel_window = None
        self._screenshot_session.cancel()
        self._clipboard_watcher.stop()

        app = QApplication.instance()
        if app is not None:
            app.quit()
        super().closeEvent(event)
