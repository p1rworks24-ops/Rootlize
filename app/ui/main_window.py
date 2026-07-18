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
    QToolButton,
)

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
from app.services.clipboard_watcher import ClipboardWatcher
from app.services.image_saver import ImageSaver
from app.services.metadata_service import MetadataService
from app.services.screenshot_session import ScreenshotSession
from app.ui.capture_mode_cycle import CaptureModeCycleButton
from app.ui.capture_settings import (
    CaptureTagCombo,
    CompactField,
    FilenameRuleCombo,
    field_separator,
)
from app.ui.icons import (
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
from app.ui.pages.home_page import HomePage
from app.ui.pages.images_page import ImagesPage, THUMBNAIL_ICON_SIZE
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.tags_page import TagsPage
from app.ui.pages.work_page import WorkPage
from app.ui.side_nav import SideNav
from app.ui.styles import APP_STYLE
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.save_folder import list_folder_names
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.workspace import (
    DEFAULT_FOLDER,
    pick_folder_name,
    resolve_current_folder,
    resolve_save_folder,
)

# Delay so minimize finishes before capture (keeps our window out of the shot).
_SNIP_HOTKEY_DELAY_MS = 250

PAGE_HOME = 0
PAGE_IMAGES = 1
PAGE_ORGANIZE = 2
PAGE_ACTION = PAGE_ORGANIZE  # backward-compatible alias
PAGE_TAGS = 3
PAGE_SETTINGS = 4

NAV_ITEMS = [
    (PAGE_HOME, "nav.home", icon_home),
    (PAGE_IMAGES, "nav.images", icon_images),
    (PAGE_ORGANIZE, "nav.organize", icon_organize),
    (PAGE_TAGS, "nav.tags", icon_tags),
    (PAGE_SETTINGS, "nav.settings", icon_settings),
]


class MainWindow(QMainWindow):
    """App shell: left navigation + stacked pages."""

    def __init__(self, config: dict):
        super().__init__()
        self._config = config
        self._app_root = Path(__file__).resolve().parent.parent.parent

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

        self.setWindowTitle(config.get("window_title", "Screenshot Manager"))
        self.resize(
            config.get("window_width", 1100),
            config.get("window_height", 720),
        )
        self.setStyleSheet(APP_STYLE)

        self._metadata_service = MetadataService()
        self._thumbnail_cache = ThumbnailCache(size=THUMBNAIL_ICON_SIZE)
        self._image_saver = ImageSaver(config, self._metadata_service, self._app_root)
        self._screenshot_session = ScreenshotSession(parent=self)
        self._screenshot_session.finished.connect(self._on_screenshot_session_finished)
        self._pending_recent_path: str | None = None
        self._page_before_screenshot = PAGE_HOME

        self._init_ui()

        interval_ms = config.get("clipboard_check_interval_ms", 500)
        self._clipboard_watcher = ClipboardWatcher(
            interval_ms=interval_ms,
            on_image_detected=self._on_image_detected,
        )
        self._clipboard_watcher.start()

        self._show_page(PAGE_HOME)

    def _init_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._side_nav = SideNav(self)
        # Home → Images → Organize → Tags, then AI placeholder, then Settings
        for page_id, label_key, icon_fn in NAV_ITEMS[:4]:
            self._side_nav.add_nav_item(page_id, t(label_key), icon_fn())
        self._side_nav.add_placeholder_item(
            t("nav.ai"),
            icon_ai(muted=True),
            tooltip=t("nav.ai_tooltip"),
        )
        self._side_nav.add_nav_item(
            PAGE_SETTINGS, t("nav.settings"), icon_settings()
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

        self._stack.addWidget(self._home_page)  # 0
        self._stack.addWidget(self._images_page)  # 1
        self._stack.addWidget(self._work_page)  # 2
        self._stack.addWidget(self._tags_page)  # 3
        self._stack.addWidget(self._settings_page)  # 4

        content_layout.addWidget(self._stack, stretch=1)

        # Capture toolbar — inset from window edges, centered when wide
        bottom_host = QWidget(self)
        bottom_host.setObjectName("globalBottomBarHost")
        bottom_host_layout = QVBoxLayout(bottom_host)
        bottom_host_layout.setContentsMargins(18, 8, 18, 14)
        bottom_host_layout.setSpacing(0)

        bottom_bar = QWidget(bottom_host)
        bottom_bar.setObjectName("globalBottomBar")
        bottom_bar_layout = QHBoxLayout(bottom_bar)
        bottom_bar_layout.setContentsMargins(14, 10, 14, 10)
        bottom_bar_layout.setSpacing(12)
        bottom_bar_layout.setAlignment(Qt.AlignVCenter)
        # Side stretches keep the cluster centered when maximized / wide
        bottom_bar_layout.addStretch(1)

        # Button + cycle + settings share one row so the button center
        # lines up with the setting value fields (desc sits on a second row).
        capture_row = QWidget(bottom_bar)
        capture_row.setObjectName("captureCluster")
        capture_row_layout = QHBoxLayout(capture_row)
        capture_row_layout.setContentsMargins(0, 0, 0, 0)
        capture_row_layout.setSpacing(8)
        capture_row_layout.setAlignment(Qt.AlignVCenter)

        # Near-square capture button (icon above text)
        self._capture_btn = QToolButton(capture_row)
        self._capture_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self._capture_btn.setCursor(Qt.PointingHandCursor)
        self._capture_btn.setFixedSize(86, 70)
        self._capture_btn.setIconSize(QSize(22, 22))
        self._capture_btn.clicked.connect(self._on_capture_clicked)
        self._capture_btn_fx = QGraphicsOpacityEffect(self._capture_btn)
        self._capture_btn.setGraphicsEffect(self._capture_btn_fx)
        capture_row_layout.addWidget(self._capture_btn, 0, Qt.AlignVCenter)

        self._cycle_mode_btn = CaptureModeCycleButton(capture_row)
        self._cycle_mode_btn.clicked.connect(self._cycle_capture_mode)
        capture_row_layout.addWidget(self._cycle_mode_btn, 0, Qt.AlignVCenter)

        settings_strip = QFrame(capture_row)
        settings_strip.setObjectName("captureSettingsStrip")
        settings_strip.setMaximumWidth(720)
        strip_layout = QHBoxLayout(settings_strip)
        strip_layout.setContentsMargins(10, 0, 10, 0)
        strip_layout.setSpacing(10)
        strip_layout.setAlignment(Qt.AlignVCenter)

        self._folder_combo = QComboBox(settings_strip)
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
            )
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
        strip_layout.addWidget(self._filename_field)
        strip_layout.addWidget(field_separator(settings_strip))

        self._capture_tag_combo = CaptureTagCombo(
            self._metadata_service, self._app_root, settings_strip
        )
        self._capture_tag_combo.set_tags(list(self._config.get("capture_tags") or []))
        self._capture_tag_combo.tags_changed.connect(self._on_capture_tags_changed)
        strip_layout.addWidget(
            CompactField(t("shell.capture_tags"), self._capture_tag_combo, settings_strip)
        )

        capture_row_layout.addWidget(settings_strip, 0, Qt.AlignVCenter)

        capture_cluster = QWidget(bottom_bar)
        capture_cluster.setObjectName("captureClusterWrap")
        cluster_outer = QVBoxLayout(capture_cluster)
        cluster_outer.setContentsMargins(0, 0, 0, 0)
        cluster_outer.setSpacing(4)
        cluster_outer.addWidget(capture_row)

        self._capture_desc = QLabel(capture_cluster)
        self._capture_desc.setObjectName("captureModeDescription")
        self._capture_desc.setWordWrap(True)
        self._capture_desc.setFixedWidth(96)
        self._capture_desc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._capture_desc_fx = QGraphicsOpacityEffect(self._capture_desc)
        self._capture_desc.setGraphicsEffect(self._capture_desc_fx)
        cluster_outer.addWidget(self._capture_desc, 0, Qt.AlignLeft)

        bottom_bar_layout.addWidget(capture_cluster, stretch=0)
        bottom_bar_layout.addStretch(1)
        bottom_host_layout.addWidget(bottom_bar)

        bottom_scroll = QScrollArea(self)
        bottom_scroll.setObjectName("bottomBarScroll")
        bottom_scroll.setWidgetResizable(True)
        bottom_scroll.setFrameShape(QFrame.NoFrame)
        bottom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bottom_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bottom_scroll.setWidget(bottom_host)
        bottom_scroll.setMinimumHeight(128)
        bottom_scroll.setMaximumHeight(150)
        content_layout.addWidget(bottom_scroll)

        self._mode_fade = QParallelAnimationGroup(self)
        self._mode_fade_gen = 0
        self._refresh_capture_mode_ui(animate=False)

        root.addWidget(content_column, stretch=1)
        self.setCentralWidget(central)

        self._refresh_folder_selector()
        self._filename_combo.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )

    def _on_capture_tags_changed(self, tags: list) -> None:
        self._config["capture_tags"] = list(tags)
        try:
            save_config(self._config)
        except OSError:
            pass
        self._image_saver.update_config(self._config)

    def _on_filename_template_changed(self, template: str) -> None:
        self._config["filename_template"] = template or DEFAULT_FILENAME_TEMPLATE
        try:
            save_config(self._config)
        except OSError:
            pass
        self._image_saver.update_config(self._config)

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

    def _on_toolbar_folder_chosen(self, index: int) -> None:
        name = self._folder_combo.itemData(index)
        if not name:
            name = self._folder_combo.itemText(index)
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
        if self._stack.currentIndex() == PAGE_ORGANIZE:
            self._work_page.refresh()

    def _on_images_tags_changed(self) -> None:
        self._tags_page.refresh()
        self._capture_tag_combo.reload_choices(self._capture_tag_combo.tags())
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

    def _on_work_images_changed(self) -> None:
        self._images_page.refresh()
        self._home_page.refresh()

    def _on_settings_saved(self) -> None:
        self._image_saver.update_config(self._config)
        self._metadata_service.invalidate_cache()
        self._thumbnail_cache.clear()
        self.resize(
            self._config.get("window_width", 1100),
            self._config.get("window_height", 720),
        )
        self._refresh_folder_selector()
        self._filename_combo.set_template(
            self._config.get("filename_template") or DEFAULT_FILENAME_TEMPLATE
        )
        self._settings_page.refresh()
        self._images_page.on_folder_changed()
        self._work_page.refresh()
        self._home_page.refresh()

    def _on_capture_clicked(self) -> None:
        self._start_capture_session(self._capture_mode)

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
        self._capture_desc.setText(t(info.description_key))

    def _refresh_capture_mode_ui(self, *, animate: bool = False) -> None:
        if not animate:
            self._capture_btn_fx.setOpacity(1.0)
            self._capture_desc_fx.setOpacity(1.0)
            self._apply_capture_mode_chrome()
            return

        if self._mode_fade.state() == QParallelAnimationGroup.Running:
            self._mode_fade.stop()

        self._mode_fade_gen += 1
        gen = self._mode_fade_gen
        self._mode_fade = QParallelAnimationGroup(self)
        for fx in (self._capture_btn_fx, self._capture_desc_fx):
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
            for fx in (self._capture_btn_fx, self._capture_desc_fx):
                anim = QPropertyAnimation(fx, b"opacity", self)
                anim.setDuration(260)
                anim.setStartValue(0.08)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.InOutCubic)
                fade_in.addAnimation(anim)
            self._mode_fade_in = fade_in
            fade_in.start()

        self._mode_fade.finished.connect(_swap_and_fade_in)
        self._mode_fade.start()

    def _start_capture_session(self, mode: str | None = None) -> None:
        """Start a capture; mode only changes how the image is obtained."""
        if self._screenshot_session.is_active:
            return

        mode = normalize_capture_mode(mode or self._capture_mode)
        self._page_before_screenshot = self._stack.currentIndex()
        self.showMinimized()
        self._screenshot_session.start(mode)
        QTimer.singleShot(
            _SNIP_HOTKEY_DELAY_MS,
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

    def _on_screenshot_session_finished(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._home_page.refresh()
        self._images_page.refresh()
        self._show_page(self._page_before_screenshot)

    def _on_image_detected(self, detected: DetectedImage) -> None:
        saved_path = self._image_saver.save_image(detected.image, detected.detected_at)
        if saved_path is not None:
            self._images_page.add_saved_image(saved_path)
            self._home_page.refresh()
            if self._screenshot_session.is_active:
                self._screenshot_session.complete()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._screenshot_session.cancel()
        self._clipboard_watcher.stop()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()
        super().closeEvent(event)
