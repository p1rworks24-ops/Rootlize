from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QPoint,
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
    QFrame,
    QFileDialog,
    QGraphicsOpacityEffect,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
)

from app.ui.design_tokens import (
    CAPTURE_BAR_HEIGHT,
    CAPTURE_BAR_ITEM_GAP,
    CAPTURE_BAR_PADDING_X,
    CAPTURE_BUTTON_HEIGHT,
    CAPTURE_BUTTON_WIDTH,
    CAPTURE_EDGE_BUTTON_HEIGHT,
    CAPTURE_FIELD_HEIGHT,
    CAPTURE_FIELD_TITLE_HEIGHT,
    NAV_RESPONSIVE_BREAKPOINT,
    apply_card_shadow,
)

# Soft floor so the configured default size is not also the drag minimum
_WINDOW_MIN_WIDTH = 720
_WINDOW_MIN_HEIGHT = 480


class _CaptureSettingsScroll(QScrollArea):
    """Shrinkable settings strip that leaves toolbar actions in the main layout."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, max(hint.height(), CAPTURE_BAR_HEIGHT))

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 640), max(hint.height(), CAPTURE_BAR_HEIGHT))


class _CaptureFlatField(QWidget):
    """Mode-like label + control without a surrounding setting card."""

    def __init__(self, label_text: str, control: QWidget, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("captureFlatField")
        self.setFixedHeight(CAPTURE_FIELD_HEIGHT)
        self._control = control
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text, self)
        label.setObjectName("captureModeSelectorLabel")
        label.setFixedHeight(CAPTURE_FIELD_TITLE_HEIGHT)
        self.label = label
        layout.addWidget(label)
        control.setObjectName("captureFlatCombo")
        control.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(control)

    def set_hint(self, text: str) -> None:
        self._control.setToolTip((text or "").strip())

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
from app.ui.capture_mode_selector import CaptureModeSelector
from app.ui.capture_panel_window import CapturePanelWindow
from app.ui.capture_settings import (
    CaptureTagCombo,
    FilenameRuleCombo,
    field_separator,
)
from app.ui.floating_toast import FloatingToastHost
from app.ui.icons import (
    icon_about,
    icon_ai,
    icon_collapse_capture,
    icon_capture_panel,
    icon_expand_capture,
    icon_organize,
    icon_fullscreen_capture,
    icon_home,
    icon_images,
    icon_region_capture,
    icon_settings,
    icon_tags,
)
from app.ui.pages.about_page import AboutPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.images_page import ImagesPage, THUMBNAIL_ICON_SIZE
from app.ui.pages.settings_page import SettingsPage
from app.ui.ocr_test_controller import ImageAnalysisController
from app.ui.pages.tags_page import TagsPage
from app.ui.pages.work_page import WorkPage
from app.ui.side_nav import SideNav
from app.ui.styles import APP_STYLE
from app.ui.welcome_dialog import WelcomeDialog
from app.paths import is_frozen
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.save_folder import list_folder_names
from app.utils.selected_folder import selected_folder_state
from app.utils.snipping_toast import snipping_toast_suppressor
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.window_acrylic import set_windows_caption_color
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

# Temporarily retired from the product navigation. Keep the implementations and
# stack positions intact so restoring both pages is a one-line change.
MANAGEMENT_PAGES_ENABLED = False

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
            config.get("window_width", 1600),
            config.get("window_height", 900),
        )
        self.setStyleSheet(APP_STYLE)
        set_windows_caption_color(self, "#F3F6FA")

        self._metadata_service = MetadataService()
        self._thumbnail_cache = ThumbnailCache(size=THUMBNAIL_ICON_SIZE)
        self._image_saver = ImageSaver(config, self._metadata_service, self._app_root)
        self._screenshot_session = ScreenshotSession(parent=self)
        self._screenshot_session.finished.connect(self._on_screenshot_session_finished)
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

        _selected, folder_state = selected_folder_state(
            self._config, self._app_root
        )
        self._show_page(PAGE_HOME if folder_state == "ready" else PAGE_IMAGES)

    def arm_capture_hotkeys(self) -> None:
        """Enable global Capture shortcuts after startup UI is ready."""
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.set_armed(True)

    def show_welcome_if_needed(self) -> None:
        """Show the lightweight first-run guide after the main UI is visible."""
        # Source launches are the local design/QA environment and intentionally
        # preview onboarding every time. Packaged users see it only once.
        if is_frozen() and bool(self._config.get("onboarding_completed", False)):
            return
        existing = getattr(self, "_welcome_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = WelcomeDialog(self)
        self._welcome_dialog = dialog
        dialog.finished.connect(
            lambda _result, current=dialog: self._complete_welcome(current)
        )
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _complete_welcome(self, dialog: WelcomeDialog) -> None:
        """Persist completion only after the displayed dialog actually closes."""
        if getattr(self, "_welcome_dialog", None) is not dialog:
            return
        self._welcome_dialog = None
        self._config["onboarding_completed"] = True
        try:
            save_config(self._config)
        except OSError:
            pass
        if dialog.go_to_images:
            self._show_page(PAGE_IMAGES)

    def _init_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("appShell")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._side_nav = SideNav(self)
        primary_nav_items = NAV_ITEMS[:2]
        if MANAGEMENT_PAGES_ENABLED:
            primary_nav_items += NAV_ITEMS[2:4]
        for page_id, label_key, icon_fn, accent in primary_nav_items:
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
        self._side_nav.add_test_user()
        self._side_nav.page_selected.connect(self._show_page)
        self._side_nav._anim.valueChanged.connect(
            lambda _value: self._sync_capture_bar_geometry()
        )
        root.addWidget(self._side_nav)

        content_column = QWidget(self)
        content_column.setObjectName("appContent")
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
            management_pages_enabled=MANAGEMENT_PAGES_ENABLED,
        )
        self._home_page.folder_changed.connect(self._on_home_folder_changed)

        self._image_analysis_controller = ImageAnalysisController(self)
        self._images_page = ImagesPage(
            self._config,
            self._metadata_service,
            self._thumbnail_cache,
            self._app_root,
            self,
            analysis_controller=self._image_analysis_controller,
        )
        self._images_page.folder_changed.connect(self._on_images_folder_changed)
        if self._images_page._analysis_bar is not None:
            self._images_page._analysis_bar.analysis_summary_changed.connect(
                self._home_page.set_analysis_summary
            )
            self._images_page._analysis_bar.analysis_progress_changed.connect(
                self._home_page.set_analysis_progress
            )
        self._images_page._splitter.splitterMoved.connect(
            lambda _pos, _index: self._sync_capture_bar_geometry()
        )

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
        self._images_page.tags_page_requested.connect(
            lambda: self._show_page(PAGE_TAGS)
        )

        self._settings_page = SettingsPage(
            self._config,
            self._app_root,
            self,
            ocr_controller=self._image_analysis_controller,
        )
        self._settings_page.settings_saved.connect(self._on_settings_saved)
        self._settings_page.shortcuts_changed.connect(self._reload_capture_hotkeys)
        self._settings_page.window_size_changed.connect(
            self._apply_window_size_from_settings
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
        self._capture_bar_host = bottom_host
        bottom_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom_host_layout = QVBoxLayout(bottom_host)
        bottom_host_layout.setContentsMargins(12, 4, 12, 8)
        bottom_host_layout.setSpacing(2)

        self._capture_bar_restore_row = QWidget(bottom_host)
        self._capture_bar_restore_row.setObjectName("captureBarRestoreRow")
        restore_layout = QHBoxLayout(self._capture_bar_restore_row)
        restore_layout.setContentsMargins(0, 6, CAPTURE_BAR_PADDING_X, 0)
        restore_layout.setSpacing(0)
        self._capture_bar_restore_btn = QPushButton("", self._capture_bar_restore_row)
        self._capture_bar_restore_btn.setObjectName("captureBarToggleButton")
        self._capture_bar_restore_btn.setIcon(icon_expand_capture())
        self._capture_bar_restore_btn.setIconSize(QSize(14, 14))
        self._capture_bar_restore_btn.setCursor(Qt.PointingHandCursor)
        self._capture_bar_restore_btn.setFixedSize(
            CAPTURE_EDGE_BUTTON_HEIGHT, CAPTURE_EDGE_BUTTON_HEIGHT
        )
        self._capture_bar_restore_btn.clicked.connect(self._toggle_capture_bar)
        restore_layout.addStretch(1)
        restore_layout.addWidget(self._capture_bar_restore_btn)
        bottom_host_layout.addWidget(self._capture_bar_restore_row)

        # One stable toolbar layout. Only the settings group may scroll when the
        # window is narrow; Hide / Capture / Capture Panel stay in this row.
        bottom_bar = QWidget(bottom_host)
        bottom_bar.setObjectName("globalBottomBar")
        self._capture_bar = bottom_bar
        bottom_bar.setMinimumWidth(0)
        bottom_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        capture_card_layout = QVBoxLayout(bottom_bar)
        capture_card_layout.setContentsMargins(
            CAPTURE_BAR_PADDING_X,
            18,
            CAPTURE_BAR_PADDING_X,
            19,
        )
        capture_card_layout.setSpacing(0)

        capture_title_row = QWidget(bottom_bar)
        capture_title_row.setObjectName("captureBarTitleRow")
        capture_title_row.setFixedHeight(CAPTURE_EDGE_BUTTON_HEIGHT)
        self._capture_bar_title_row = capture_title_row
        capture_title_layout = QHBoxLayout(capture_title_row)
        capture_title_layout.setContentsMargins(0, 0, 0, 0)
        capture_title_layout.setSpacing(7)

        capture_title_icon = QLabel(capture_title_row)
        capture_title_icon.setObjectName("captureBarTitleIcon")
        capture_title_icon.setFixedSize(20, 20)
        capture_title_icon.setPixmap(
            icon_fullscreen_capture(color="#2563eb").pixmap(18, 18)
        )
        capture_title_icon.setAlignment(Qt.AlignCenter)
        self._capture_bar_title_icon = capture_title_icon
        capture_title_layout.addWidget(capture_title_icon)

        capture_title = QLabel(t("shell.capture_bar.title"), capture_title_row)
        capture_title.setObjectName("captureBarTitle")
        self._capture_bar_title = capture_title
        capture_title_layout.addWidget(capture_title)
        capture_title_layout.addStretch(1)

        self._capture_bar_toggle_btn = QPushButton("", capture_title_row)
        self._capture_bar_toggle_btn.setObjectName("captureBarToggleButton")
        self._capture_bar_toggle_btn.setIcon(icon_collapse_capture())
        self._capture_bar_toggle_btn.setIconSize(QSize(14, 14))
        self._capture_bar_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._capture_bar_toggle_btn.setFixedSize(
            CAPTURE_EDGE_BUTTON_HEIGHT, CAPTURE_EDGE_BUTTON_HEIGHT
        )
        self._capture_bar_toggle_btn.clicked.connect(self._toggle_capture_bar)
        capture_title_layout.addWidget(self._capture_bar_toggle_btn)

        capture_controls_row = QWidget(bottom_bar)
        capture_controls_row.setObjectName("captureBarControlsRow")
        bottom_bar_layout = QHBoxLayout(capture_controls_row)
        self._capture_bar_layout = bottom_bar_layout
        bottom_bar_layout.setContentsMargins(0, 0, 0, 0)
        bottom_bar_layout.setSpacing(CAPTURE_BAR_ITEM_GAP)
        bottom_bar_layout.setAlignment(Qt.AlignVCenter)

        bottom_bar_layout.addStretch(1)

        # 1) Capture button (primary action). Its icon and mode label live in
        # the button itself, matching the compact reference CTA.
        capture_action_field = QWidget(bottom_bar)
        capture_action_field.setObjectName("captureActionField")
        capture_action_field.setFixedHeight(CAPTURE_BUTTON_HEIGHT)
        self._capture_action_field = capture_action_field
        capture_action_layout = QVBoxLayout(capture_action_field)
        # Extra trailing inset separates the primary action from Mode without
        # changing the spacing used by the rest of the capture bar.
        capture_action_layout.setContentsMargins(0, 0, 8, 0)
        capture_action_layout.setSpacing(0)

        self._capture_btn = QToolButton(capture_action_field)
        self._capture_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self._capture_btn.setAccessibleName(t("shell.capture.action"))
        self._capture_btn.setCursor(Qt.PointingHandCursor)
        self._capture_btn.setFixedSize(CAPTURE_BUTTON_WIDTH, CAPTURE_BUTTON_HEIGHT)
        self._capture_btn.setIconSize(QSize(20, 20))
        self._capture_btn.clicked.connect(self._on_capture_clicked)
        capture_action_layout.addWidget(self._capture_btn, 0, Qt.AlignHCenter)
        bottom_bar_layout.addWidget(capture_action_field, 0, Qt.AlignVCenter)
        bottom_bar_layout.addSpacing(12)

        # 2) Explicit mode selector. It changes state only; Capture executes it.
        self._capture_mode_selector = CaptureModeSelector(bottom_bar)
        self._capture_mode_selector.mode_selected.connect(self._set_capture_mode)
        bottom_bar_layout.addWidget(
            self._capture_mode_selector, 0, Qt.AlignVCenter
        )

        # Soft separator before settings (keeps capture controls distinct)
        bar_divider = QFrame(bottom_bar)
        bar_divider.setObjectName("captureBarDivider")
        bar_divider.setFixedWidth(1)
        bar_divider.setFixedHeight(36)
        bottom_bar_layout.addSpacing(2)
        bottom_bar_layout.addWidget(bar_divider, 0, Qt.AlignVCenter)
        bottom_bar_layout.addSpacing(2)

        # 4) Settings fields. This is the only shrinkable/scrollable segment;
        # the primary and secondary actions remain ordinary toolbar widgets.
        settings_scroll = _CaptureSettingsScroll(bottom_bar)
        self._capture_settings_scroll = settings_scroll
        settings_scroll.setObjectName("captureSettingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        settings_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        settings_scroll.setFixedHeight(CAPTURE_FIELD_HEIGHT)
        settings_scroll.setMinimumWidth(0)
        settings_scroll.setMaximumWidth(360)

        settings_strip = QWidget(settings_scroll)
        settings_strip.setObjectName("captureSettingsFlatStrip")
        self._capture_settings_strip = settings_strip
        settings_strip.setMinimumWidth(0)
        settings_strip.setMaximumWidth(360)
        settings_strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        strip_layout = QHBoxLayout(settings_strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(8)
        strip_layout.setAlignment(Qt.AlignVCenter)

        self._save_folder_btn = QPushButton(settings_strip)
        self._save_folder_btn.setObjectName("captureSaveFolderButton")
        self._save_folder_btn.setCursor(Qt.PointingHandCursor)
        self._save_folder_btn.setMinimumWidth(110)
        self._save_folder_btn.clicked.connect(self._choose_capture_save_folder)
        self._save_folder_field = _CaptureFlatField(
            t("shell.capture_bar.folder"), self._save_folder_btn, settings_strip
        )
        self._save_folder_btn.setObjectName("captureSaveFolderButton")
        strip_layout.addWidget(self._save_folder_field, stretch=1)
        strip_layout.addWidget(field_separator(settings_strip))

        self._filename_combo = FilenameRuleCombo(settings_strip)
        self._filename_combo.template_changed.connect(self._on_filename_template_changed)
        self._filename_field = _CaptureFlatField(
            t("shell.capture_bar.filename"),
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
        self._capture_tags_field = _CaptureFlatField(
            t("shell.capture_bar.tags"), self._capture_tag_combo, settings_strip
        )
        strip_layout.addWidget(self._capture_tags_field, stretch=1)

        settings_scroll.setWidget(settings_strip)
        bottom_bar_layout.addWidget(settings_scroll, 0, Qt.AlignVCenter)

        # Secondary utility group: keep it in the stable toolbar layout while
        # distinguishing it from the save settings group.
        secondary_divider = QFrame(bottom_bar)
        secondary_divider.setObjectName("captureBarDivider")
        secondary_divider.setFixedWidth(1)
        secondary_divider.setFixedHeight(36)
        bottom_bar_layout.addSpacing(2)
        bottom_bar_layout.addWidget(secondary_divider, 0, Qt.AlignVCenter)
        bottom_bar_layout.addSpacing(2)

        # Capture Panel opener — button + short hint (matches CompactField rhythm)
        panel_field = QWidget(bottom_bar)
        panel_field.setObjectName("capturePanelField")
        self._capture_panel_field = panel_field
        panel_field.setFixedHeight(CAPTURE_FIELD_HEIGHT)
        panel_field_layout = QHBoxLayout(panel_field)
        panel_field_layout.setContentsMargins(0, 0, 0, 0)
        panel_field_layout.setSpacing(8)
        panel_field_layout.setAlignment(Qt.AlignVCenter)

        self._capture_panel_btn = QPushButton(
            "", panel_field
        )
        self._capture_panel_btn.setObjectName("capturePanelPopOutButton")
        self._capture_panel_btn.setIcon(icon_capture_panel())
        self._capture_panel_btn.setIconSize(QSize(20, 20))
        self._capture_panel_btn.setCursor(Qt.PointingHandCursor)
        self._capture_panel_btn.setFixedSize(36, 36)
        self._capture_panel_btn.setAccessibleName(t("shell.capture_panel.button"))
        self._capture_panel_btn.setToolTip(t("shell.capture_panel.pop_out_tooltip"))
        self._capture_panel_btn.clicked.connect(self._toggle_capture_panel)
        panel_field_layout.addWidget(self._capture_panel_btn)

        panel_hint = QLabel(t("shell.capture_panel.use_hint"), panel_field)
        panel_hint.setObjectName("capturePanelUseHint")
        panel_hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._capture_panel_use_hint = panel_hint
        panel_field_layout.addWidget(panel_hint)

        bottom_bar_layout.addWidget(panel_field, 0, Qt.AlignVCenter)

        bottom_bar_layout.addStretch(1)

        capture_card_layout.addWidget(capture_controls_row)
        bottom_host_layout.addWidget(bottom_bar)
        capture_title_row.raise_()
        apply_card_shadow(bottom_bar, blue_tinted=True)

        # Fixed footer; only the settings segment scrolls when space is limited.
        content_layout.addWidget(bottom_host, stretch=0)

        self._mode_fade = QParallelAnimationGroup(self)
        self._mode_fade_gen = 0
        self._capture_bar_animation: QPropertyAnimation | None = None
        self._refresh_capture_mode_ui(animate=False)

        root.addWidget(content_column, stretch=1)
        self.setCentralWidget(central)
        self._apply_navigation_density()

        self._refresh_folder_selector()
        self._filename_combo.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._capture_tag_combo.set_tags(list(self._config.get("capture_tags") or []))
        # Ensure Settings page widgets mirror the last-used config on launch
        self._settings_page.refresh()
        self._set_capture_bar_visible(
            bool(self._config.get("capture_bar_visible", True)),
            persist=False,
            animate=False,
        )

    def _toggle_capture_bar(self) -> None:
        self._set_capture_bar_visible(not self._capture_bar_visible)

    def _set_capture_bar_visible(
        self,
        visible: bool,
        *,
        persist: bool = True,
        animate: bool = True,
    ) -> None:
        """Show/hide compact capture controls while leaving a small restore action."""
        visible = bool(visible)
        self._capture_bar_visible = visible
        self._capture_bar_host.layout().setContentsMargins(
            8,
            2,
            8,
            4,
        )
        self._capture_bar_toggle_btn.setText("")
        self._capture_bar_restore_btn.setText("")
        self._capture_bar_toggle_btn.setIcon(icon_collapse_capture())
        self._capture_bar_restore_btn.setIcon(icon_expand_capture())
        self._capture_bar_toggle_btn.setToolTip(t("shell.capture_bar.hide_tooltip"))
        self._capture_bar_restore_btn.setToolTip(t("shell.capture_bar.show_tooltip"))
        self._capture_bar_toggle_btn.setAccessibleName(
            t("shell.capture_bar.hide_tooltip")
        )
        self._capture_bar_restore_btn.setAccessibleName(
            t("shell.capture_bar.show_tooltip")
        )
        self._capture_bar_host.setProperty("captureBarVisible", visible)
        self._sync_capture_bar_geometry()
        if self._capture_bar_animation is not None:
            self._capture_bar_animation.stop()

        expanded_height = max(
            CAPTURE_BAR_HEIGHT, self._capture_bar.sizeHint().height()
        )
        if not animate:
            self._capture_bar.setMaximumHeight(16777215)
            self._capture_bar.setVisible(visible)
            self._capture_bar_restore_row.setVisible(not visible)
        elif visible:
            self._capture_bar_restore_row.hide()
            self._capture_bar.setMaximumHeight(0)
            self._capture_bar.show()
            animation = QPropertyAnimation(
                self._capture_bar, b"maximumHeight", self
            )
            animation.setDuration(240)
            animation.setStartValue(0)
            animation.setEndValue(expanded_height)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            animation.finished.connect(
                lambda: self._capture_bar.setMaximumHeight(16777215)
            )
            self._capture_bar_animation = animation
            animation.start()
        else:
            self._capture_bar_restore_row.hide()
            self._capture_bar.show()
            animation = QPropertyAnimation(
                self._capture_bar, b"maximumHeight", self
            )
            animation.setDuration(210)
            animation.setStartValue(max(1, self._capture_bar.height()))
            animation.setEndValue(0)
            animation.setEasingCurve(QEasingCurve.InOutCubic)

            def finish_collapse() -> None:
                self._capture_bar.hide()
                self._capture_bar.setMaximumHeight(16777215)
                self._capture_bar_restore_row.show()

            animation.finished.connect(finish_collapse)
            self._capture_bar_animation = animation
            animation.start()
        self._config["capture_bar_visible"] = visible
        if persist:
            try:
                save_config(self._config)
            except OSError:
                pass

    def _persist_runtime_settings(self) -> None:
        """Write last-used shell settings so the next launch restores them.

        Window size is owned by Settings (default 1600×900) — do not overwrite
        it from the live geometry here.
        """
        # Only load_config() supplies this marker. Lightweight/test-created
        # MainWindow configs must never leak into the real AppData config when
        # their windows are closed after path overrides have been released.
        if "window_size_default_version" not in self._config:
            return
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

        folder = resolve_save_folder(self._config) or DEFAULT_FOLDER
        if hasattr(self, "_save_folder_btn"):
            root = resolve_screenshot_root(
                self._config.get("screenshot_dir", "screenshots"), self._app_root
            )
            destination = root / folder
            self._save_folder_btn.setText(destination.name or folder)
            self._save_folder_btn.setToolTip(str(destination))
        if hasattr(self, "_filename_combo"):
            self._filename_combo.set_folder(folder)
        self._sync_capture_panel_settings()

    def _choose_capture_save_folder(self) -> None:
        """Choose the exact directory used for new captures."""
        root = resolve_screenshot_root(
            self._config.get("screenshot_dir", "screenshots"), self._app_root
        )
        current = root / (resolve_save_folder(self._config) or DEFAULT_FOLDER)
        selected = QFileDialog.getExistingDirectory(
            self,
            t("shell.save_folder_choose_title"),
            str(current if current.exists() else root),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        destination = Path(selected).resolve()
        if not destination.name:
            return

        parent = destination.parent
        self._config["screenshot_dir"] = str(parent)
        self._apply_save_folder(destination.name)
        self._refresh_folder_selector()
        self._images_page.refresh()
        self._home_page.refresh()

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
        if hasattr(self, "_save_folder_btn"):
            root = resolve_screenshot_root(
                self._config.get("screenshot_dir", "screenshots"), self._app_root
            )
            destination = root / str(name)
            self._save_folder_btn.setText(destination.name)
            self._save_folder_btn.setToolTip(str(destination))
        # Refresh ★ marker on Viewing folder tree
        self._images_page.refresh_save_folder_marker()
        if self._capture_panel_window is not None:
            self._capture_panel_window.sync_folder_selector(
                list_folder_names(self._config, self._app_root),
                str(name),
            )

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
        if not MANAGEMENT_PAGES_ENABLED and page_id in (PAGE_ORGANIZE, PAGE_TAGS):
            page_id = PAGE_IMAGES
        self._stack.setCurrentIndex(page_id)
        self._side_nav.set_current_page(page_id)
        # Capture controls belong to the Images workspace only. Hiding the
        # host removes its height from every information/settings page.
        self._capture_bar_host.setVisible(page_id == PAGE_IMAGES)
        if page_id == PAGE_IMAGES:
            QTimer.singleShot(0, self._sync_capture_bar_geometry)
        self._refresh_folder_selector()

        if page_id == PAGE_HOME:
            self._home_page.refresh()
            self._images_page._refresh_analysis_preview()
        elif page_id == PAGE_IMAGES:
            self._images_page.refresh()
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

    def _on_home_folder_changed(self, path: str) -> None:
        """Refresh Images and related views after Home changes the folder."""
        self._images_page.refresh()
        self._on_images_folder_changed(Path(path).name)

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
            width = int(self._config.get("window_width", 1600) or 1600)
        except (TypeError, ValueError):
            width = 1600
        try:
            height = int(self._config.get("window_height", 900) or 900)
        except (TypeError, ValueError):
            height = 900
        self.setMinimumSize(_WINDOW_MIN_WIDTH, _WINDOW_MIN_HEIGHT)
        self.resize(max(width, _WINDOW_MIN_WIDTH), max(height, _WINDOW_MIN_HEIGHT))

    def _apply_navigation_density(self) -> None:
        if hasattr(self, "_side_nav"):
            self._side_nav.set_responsive_compact(
                self.width() < NAV_RESPONSIVE_BREAKPOINT
            )

    def _sync_capture_bar_geometry(self) -> None:
        """Align the footer card with the Images gallery workspace."""
        if not hasattr(self, "_capture_bar_host"):
            return
        try:
            host = self._capture_bar_host
            host_width = host.width()
        except RuntimeError:
            # A queued resize callback may arrive after Qt destroys the shell.
            return
        left = 16
        right = 16
        if host_width > 0 and hasattr(self, "_images_page"):
            workspace = self._images_page._left_workspace
            point = host.mapFromGlobal(
                workspace.mapToGlobal(QPoint(0, 0))
            )
            target_width = workspace.width()
            # The fixed Capture/Mode/Panel actions need a safe floor. At the
            # normal 1600px window the card aligns to the gallery; narrower
            # windows fall back to the available footer width.
            required_width = max(620, self._capture_bar.minimumSizeHint().width())
            if target_width >= required_width:
                left = max(12, point.x())
                right = max(12, host_width - left - target_width)
        try:
            host.layout().setContentsMargins(left, 2, right, 10)
        except RuntimeError:
            return
        QTimer.singleShot(0, self._position_capture_bar_header)

    def _position_capture_bar_header(self) -> None:
        """Overlay the card heading without changing the capture bar height."""
        if not hasattr(self, "_capture_bar_title_row"):
            return
        try:
            inset = CAPTURE_BAR_PADDING_X
            self._capture_bar_title_row.setGeometry(
                inset,
                6,
                max(0, self._capture_bar.width() - (inset * 2)),
                CAPTURE_EDGE_BUTTON_HEIGHT,
            )
            self._capture_bar_title_row.raise_()
        except RuntimeError:
            return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_navigation_density()
        QTimer.singleShot(0, self._sync_capture_bar_geometry)
        QTimer.singleShot(40, self._sync_capture_bar_geometry)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_capture_bar_geometry)
        QTimer.singleShot(40, self._sync_capture_bar_geometry)

    def _on_capture_clicked(self) -> None:
        """Toolbar Capture — defer so we are not inside the mouse-press stack."""
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
        """Cycle mode for the compact floating Capture Panel control."""
        self._set_capture_mode(next_capture_mode(self._capture_mode))

    def _set_capture_mode(self, mode: str) -> None:
        """Persist and present a mode selection without starting a capture."""
        self._capture_mode = normalize_capture_mode(mode)
        self._config["capture_mode"] = self._capture_mode
        try:
            save_config(self._config)
        except OSError:
            pass
        self._refresh_capture_mode_ui(animate=False)

    def _apply_capture_mode_chrome(self) -> None:
        info = capture_mode_info(self._capture_mode)
        icon = (
            icon_fullscreen_capture(color="#2563eb")
            if info.mode_id == CAPTURE_FULLSCREEN
            else icon_region_capture(color="#2563eb")
        )
        self._capture_btn.setText(
            "Full Screen\nCapture"
            if info.mode_id == CAPTURE_FULLSCREEN
            else "Region\nCapture"
        )
        self._capture_btn.setIcon(icon)
        self._capture_btn.setToolTip(t(info.tooltip_key))
        self._capture_btn.setObjectName(info.button_object_name)
        style = self._capture_btn.style()
        style.unpolish(self._capture_btn)
        style.polish(self._capture_btn)
        self._capture_btn.update()
        self._capture_mode_selector.set_mode(info.mode_id)
        if self._capture_panel_window is not None:
            self._capture_panel_window.apply_mode(self._capture_mode)

    def _capture_mode_opacity_effects(self) -> list[QGraphicsOpacityEffect]:
        effects: list[QGraphicsOpacityEffect] = []
        panel = self._capture_panel_window
        if panel is not None:
            effects.append(panel.capture_btn_opacity_effect)
        return effects

    def _refresh_capture_mode_ui(self, *, animate: bool = False) -> None:
        effects = self._capture_mode_opacity_effects()
        if not animate or not effects:
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
            # A missed clipboard event or a rejected OS capture request must
            # never turn the Capture control into a dead button. The new click
            # explicitly replaces the stale request.
            self._screenshot_session.cancel()

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
                # Region capture is triggered by a synthetic Win+Shift+S.
                # Give the Capture button click time to fully release even
                # when the window stays visible; firing too early can make
                # Windows ignore the shortcut.
                delay_ms = (
                    80 if mode == CAPTURE_FULLSCREEN else _SNIP_HOTKEY_DELAY_MS
                )

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
        if not default_region_trigger():
            # Do not leave the capture session locked until its 60-second
            # timeout when Windows rejects the shortcut. Completing it makes
            # the Capture button immediately usable again.
            self._screenshot_session.complete()

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
        # The written path is authoritative. This keeps the notification in
        # sync with the folder selected in Capture settings even if config/UI
        # state changes around the save operation.
        folder = saved_path.parent.name or resolve_save_folder(self._config) or DEFAULT_FOLDER
        self._toast_host.show_success(
            filename=saved_path.name,
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
        if hasattr(self, "_images_page") and self._images_page._analysis_bar is not None:
            self._images_page._analysis_bar.stop_polling()
        if hasattr(self, "_image_analysis_controller"):
            self._image_analysis_controller.close(timeout=3.0)
        snipping_toast_suppressor.exit()
        if hasattr(self, "_hotkey_manager"):
            self._hotkey_manager.stop()
        if hasattr(self, "_toast_host"):
            self._toast_host.shutdown()
        if self._capture_panel_window is not None:
            self._capture_panel_window.close()
            self._capture_panel_window = None
        self._screenshot_session.cancel()
        if hasattr(self, "_clipboard_watcher"):
            self._clipboard_watcher.stop()

        app = QApplication.instance()
        if app is not None:
            app.quit()
        super().closeEvent(event)
