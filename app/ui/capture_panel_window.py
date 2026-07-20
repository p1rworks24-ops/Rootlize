"""Capture Panel — independent always-on-top mini window (150×150 capture page)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.services.capture_modes import (
    CAPTURE_FULLSCREEN,
    capture_mode_info,
    normalize_capture_mode,
)
from app.services.metadata_service import MetadataService
from app.ui.capture_mode_cycle import CaptureModeCycleButton
from app.ui.capture_settings import (
    CaptureTagCombo,
    CompactField,
    FilenameRuleCombo,
    UpwardComboBox,
)
from app.ui.icons import (
    fluent_icon,
    icon_fullscreen_capture,
    icon_region_capture,
    icon_save_folder_star,
)
from app.utils.filename_template import DEFAULT_FILENAME_TEMPLATE
from app.utils.workspace import DEFAULT_FOLDER

PANEL_SIZE = 150
# Compact settings shell; height grows when folder / filename text is long
SETTINGS_MIN_SIZE = QSize(248, 252)
SETTINGS_MAX_SIZE = QSize(280, 420)
# Backward-compatible alias for tests / callers
SETTINGS_SIZE = SETTINGS_MIN_SIZE

_PAGE_CAPTURE = 0
_PAGE_SETTINGS = 1
_TITLE_BTN = 22


class CapturePanelWindow(QWidget):
    """
    Soft-blue square Capture Panel (initially bottom-right).

    Independent of the main window; stays above all other windows.
    Drag the title bar to reposition. Settings page expands the panel.
    Closing the panel resets placement so the next open snaps bottom-right.
    """

    closed = Signal()
    capture_clicked = Signal()
    mode_cycle_clicked = Signal()
    folder_chosen = Signal(str)
    filename_template_changed = Signal(str)
    capture_tags_changed = Signal(list)
    settings_page_requested = Signal()

    MARGIN = 16

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        metadata_service: MetadataService | None = None,
        app_root: Path | None = None,
    ):
        super().__init__(
            None,
            Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint,
        )
        self.setObjectName("capturePanelWindow")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(PANEL_SIZE, PANEL_SIZE)
        self.setWindowTitle(t("shell.capture_panel.title"))
        self._drag_offset: QPoint | None = None
        self._placed_once = False
        self._show_anim: QParallelAnimationGroup | None = None
        self._page_anim: QPropertyAnimation | None = None
        self._metadata_service = metadata_service
        self._app_root = app_root or Path(".")
        self._settings_fields: list[CompactField] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        chrome = QFrame(self)
        chrome.setObjectName("capturePanelWindowChrome")
        self._chrome = chrome
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)

        title_bar = QWidget(chrome)
        title_bar.setObjectName("capturePanelTitleBar")
        title_bar.setAttribute(Qt.WA_StyledBackground, True)
        title_bar.setCursor(Qt.SizeAllCursor)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(8, 4, 4, 4)
        title_layout.setSpacing(4)

        self._title = QLabel(t("shell.capture_panel.title"), title_bar)
        self._title.setObjectName("capturePanelTitle")
        self._title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_layout.addWidget(self._title, stretch=1)

        # Trailing slot: ✕ on capture page, ← on settings page (same 1:1 square)
        self._back_btn = QToolButton(title_bar)
        self._back_btn.setObjectName("capturePanelBackButton")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setFixedSize(_TITLE_BTN, _TITLE_BTN)
        self._back_btn.setText("←")
        self._back_btn.setToolTip(t("shell.capture_panel.back"))
        self._back_btn.clicked.connect(self.show_capture_page)
        self._back_btn.hide()
        title_layout.addWidget(self._back_btn, 0, Qt.AlignVCenter)

        close_btn = QPushButton("✕", title_bar)
        close_btn.setObjectName("capturePanelCloseButton")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(_TITLE_BTN, _TITLE_BTN)
        close_btn.setToolTip(t("shell.capture_panel.close"))
        close_btn.clicked.connect(self.close)
        title_layout.addWidget(close_btn, 0, Qt.AlignVCenter)
        self._close_btn = close_btn

        chrome_layout.addWidget(title_bar)
        self._title_bar = title_bar

        self._stack = QStackedWidget(chrome)
        self._stack.setObjectName("capturePanelStack")
        chrome_layout.addWidget(self._stack, stretch=1)

        self._build_capture_page()
        self._build_settings_page()

        root.addWidget(chrome)
        self.apply_mode("region")

    def _build_capture_page(self) -> None:
        page = QWidget(self._stack)
        page.setObjectName("capturePanelWindowBody")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(0)

        controls = QWidget(page)
        controls.setObjectName("capturePanelControls")
        controls.setAttribute(Qt.WA_StyledBackground, False)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)
        controls_layout.setAlignment(Qt.AlignCenter)

        self._capture_btn = QToolButton(controls)
        self._capture_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self._capture_btn.setCursor(Qt.PointingHandCursor)
        self._capture_btn.setFixedSize(70, 68)
        self._capture_btn.setIconSize(QSize(18, 18))
        self._capture_btn.setObjectName("capturePanelShotButton")
        self._capture_btn.clicked.connect(self.capture_clicked.emit)
        self._capture_btn_fx = QGraphicsOpacityEffect(self._capture_btn)
        self._capture_btn.setGraphicsEffect(self._capture_btn_fx)
        controls_layout.addWidget(self._capture_btn, 0, Qt.AlignVCenter)

        side_col = QWidget(controls)
        side_col.setObjectName("capturePanelSideCol")
        side_col.setFixedWidth(28)
        side_layout = QVBoxLayout(side_col)
        side_layout.setContentsMargins(0, 4, 0, 4)
        side_layout.setSpacing(12)
        side_layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        # Icon-only mode cycle (no border chrome)
        self._cycle_btn = CaptureModeCycleButton(
            side_col,
            show_label=False,
            button_size=24,
            icon_size=16,
            fixed_width=24,
            button_object_name="capturePanelModeButton",
            icon_color="#1e40af",
        )
        self._cycle_btn.clicked.connect(self.mode_cycle_clicked.emit)
        side_layout.addWidget(self._cycle_btn, 0, Qt.AlignHCenter)

        self._settings_btn = QToolButton(side_col)
        self._settings_btn.setObjectName("capturePanelSettingsButton")
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setIcon(fluent_icon("\uE713", size=16, color="#1e40af"))
        self._settings_btn.setIconSize(QSize(16, 16))
        self._settings_btn.setToolTip(t("shell.capture_panel.settings_tooltip"))
        self._settings_btn.clicked.connect(self._on_settings_clicked)
        side_layout.addWidget(self._settings_btn, 0, Qt.AlignHCenter)

        controls_layout.addWidget(side_col, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(controls, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self._stack.addWidget(page)

    def _build_settings_page(self) -> None:
        page = QWidget(self._stack)
        page.setObjectName("capturePanelSettingsPage")
        self._settings_page = page
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        self._folder_combo = UpwardComboBox(page)
        self._folder_combo.setCursor(Qt.PointingHandCursor)
        self._folder_combo.setToolTip(t("shell.save_destination_tooltip"))
        self._folder_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self._folder_combo.setMinimumContentsLength(1)
        self._folder_combo.activated.connect(self._on_folder_activated)
        self._folder_combo.currentTextChanged.connect(self._on_settings_content_changed)
        folder_field = CompactField(
            t("shell.save_destination"),
            self._folder_combo,
            page,
            leading_icon=icon_save_folder_star(size=12),
            wrap_hint=True,
            expandable_value=True,
        )
        folder_field.setObjectName("capturePanelCompactField")
        layout.addWidget(folder_field)
        self._folder_field = folder_field
        self._settings_fields.append(folder_field)

        self._filename_combo = FilenameRuleCombo(page)
        self._filename_combo.setMinimumWidth(60)
        self._filename_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self._filename_combo.setMinimumContentsLength(1)
        self._filename_combo.template_changed.connect(
            self.filename_template_changed.emit
        )
        self._filename_combo.currentTextChanged.connect(self._on_settings_content_changed)
        self._filename_field = CompactField(
            t("shell.save_filename_title"),
            self._filename_combo,
            page,
            wrap_hint=True,
            expandable_value=True,
        )
        self._filename_field.setObjectName("capturePanelCompactField")
        self._filename_combo.preview_changed.connect(self._on_filename_preview)
        layout.addWidget(self._filename_field)
        self._settings_fields.append(self._filename_field)

        if self._metadata_service is not None:
            self._tag_combo = CaptureTagCombo(
                self._metadata_service, self._app_root, page
            )
            self._tag_combo.setMinimumWidth(60)
            self._tag_combo.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon
            )
            self._tag_combo.setMinimumContentsLength(1)
            self._tag_combo.tags_changed.connect(self.capture_tags_changed.emit)
            self._tag_combo.currentTextChanged.connect(self._on_settings_content_changed)
            tag_field = CompactField(
                t("shell.capture_tags"),
                self._tag_combo,
                page,
                wrap_hint=True,
                expandable_value=True,
            )
            tag_field.setObjectName("capturePanelCompactField")
            layout.addWidget(tag_field)
            self._settings_fields.append(tag_field)
        else:
            self._tag_combo = None

        layout.addStretch(1)
        self._stack.addWidget(page)

    def _on_filename_preview(self, text: str) -> None:
        self._filename_field.set_hint(text)
        self._on_settings_content_changed()

    def _on_settings_clicked(self) -> None:
        self.settings_page_requested.emit()
        self.show_settings_page()

    @property
    def capture_btn_opacity_effect(self) -> QGraphicsOpacityEffect:
        """Opacity effect used for mode-switch fade (mirrors main Capture button)."""
        return self._capture_btn_fx

    def apply_mode(self, mode: str) -> None:
        """Sync capture button chrome with the shell's active mode."""
        info = capture_mode_info(normalize_capture_mode(mode))
        icon = (
            icon_fullscreen_capture()
            if info.mode_id == CAPTURE_FULLSCREEN
            else icon_region_capture()
        )
        # Same two-line labels as the main Capture button
        label = t(info.label_key).replace(" Capture", "\nCapture")
        if "\n" not in label and " " in label:
            parts = label.split(" ", 1)
            label = f"{parts[0]}\n{parts[1]}"
        self._capture_btn.setText(label)
        self._capture_btn.setIcon(icon)
        self._capture_btn.setToolTip(t(info.tooltip_key))
        self._capture_btn.setProperty(
            "mode",
            "fullscreen" if info.mode_id == CAPTURE_FULLSCREEN else "region",
        )
        style = self._capture_btn.style()
        style.unpolish(self._capture_btn)
        style.polish(self._capture_btn)
        self._capture_btn.update()

    def sync_folder_selector(self, names: list[str], current: str) -> None:
        """Mirror the main window save-folder combo (last-used selection)."""
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
        folder = current or DEFAULT_FOLDER
        self._filename_combo.set_folder(folder)
        self._folder_field.set_hint(folder)
        self._on_settings_content_changed()

    def sync_filename_template(self, template: str) -> None:
        self._filename_combo.set_template(template or DEFAULT_FILENAME_TEMPLATE)

    def sync_capture_tags(self, tags: list) -> None:
        if self._tag_combo is not None:
            self._tag_combo.set_tags(list(tags or []))

    def reload_tag_choices(self) -> None:
        if self._tag_combo is not None:
            self._tag_combo.reload_choices(self._tag_combo.tags())

    def _on_folder_activated(self, index: int) -> None:
        name = self._folder_combo.itemData(index)
        if not name:
            name = self._folder_combo.itemText(index)
        if not name:
            return
        self._filename_combo.set_folder(str(name))
        self._folder_field.set_hint(str(name))
        self.folder_chosen.emit(str(name))
        self._on_settings_content_changed()

    def place_bottom_right(self, size: int | None = None) -> None:
        side = size if size is not None else PANEL_SIZE
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - side - self.MARGIN
        y = geo.bottom() - side - self.MARGIN
        self.move(max(geo.left() + self.MARGIN, x), max(geo.top() + self.MARGIN, y))

    def _geometry_keeping_bottom_right(self, size: QSize) -> QRect:
        geo = self.geometry()
        return QRect(
            geo.right() - size.width() + 1,
            geo.bottom() - size.height() + 1,
            size.width(),
            size.height(),
        )

    def _clamp_to_screen(self, rect: QRect) -> QRect:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return rect
        avail = screen.availableGeometry()
        x = min(
            max(rect.x(), avail.left() + self.MARGIN),
            avail.right() - rect.width() - self.MARGIN,
        )
        y = min(
            max(rect.y(), avail.top() + self.MARGIN),
            avail.bottom() - rect.height() - self.MARGIN,
        )
        return QRect(x, y, rect.width(), rect.height())

    def _settings_target_size(self) -> QSize:
        """Compact default; grow downward when long values need more room."""
        page = self._settings_page
        page.adjustSize()
        for field in self._settings_fields:
            field.updateGeometry()
        hint = page.sizeHint()
        title_h = max(self._title_bar.sizeHint().height(), 28)
        border = 6
        width = max(SETTINGS_MIN_SIZE.width(), min(SETTINGS_MAX_SIZE.width(), hint.width() + 8))
        height = max(
            SETTINGS_MIN_SIZE.height(),
            min(SETTINGS_MAX_SIZE.height(), hint.height() + title_h + border),
        )
        return QSize(width, height)

    def _on_settings_content_changed(self, *_args) -> None:
        if self._stack.currentIndex() != _PAGE_SETTINGS:
            return
        if self._page_anim is not None and self._page_anim.state() == QPropertyAnimation.Running:
            return
        target = self._settings_target_size()
        if self.width() == target.width() and self.height() == target.height():
            return
        end = self._clamp_to_screen(self._geometry_keeping_bottom_right(target))
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setGeometry(end)
        self.setFixedSize(target)

    def hide_for_capture(self) -> None:
        """Hide without emitting closed (capture session will restore)."""
        if self._show_anim is not None and self._show_anim.state() == QParallelAnimationGroup.Running:
            self._show_anim.stop()
        if self._page_anim is not None and self._page_anim.state() == QPropertyAnimation.Running:
            self._page_anim.stop()
        self.hide()

    def show_panel(self) -> None:
        if self._show_anim is not None and self._show_anim.state() == QParallelAnimationGroup.Running:
            self._show_anim.stop()
        if self._page_anim is not None and self._page_anim.state() == QPropertyAnimation.Running:
            self._page_anim.stop()

        # Capture page after restore from a shot
        self._stack.setCurrentIndex(_PAGE_CAPTURE)
        self._apply_chrome_for_page(_PAGE_CAPTURE)

        if not self._placed_once:
            self.place_bottom_right()
            self._placed_once = True

        end = self._clamp_to_screen(QRect(self.x(), self.y(), PANEL_SIZE, PANEL_SIZE))

        shrink = int(PANEL_SIZE * 0.82)
        start = QRect(
            end.center().x() - shrink // 2,
            end.center().y() - shrink // 2,
            shrink,
            shrink,
        )

        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setGeometry(start)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(240)
        geo_anim.setStartValue(start)
        geo_anim.setEndValue(end)
        geo_anim.setEasingCurve(QEasingCurve.OutCubic)

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(geo_anim)
        group.addAnimation(fade)

        def _lock_size() -> None:
            self.setFixedSize(PANEL_SIZE, PANEL_SIZE)
            self.setWindowOpacity(1.0)

        group.finished.connect(_lock_size)
        self._show_anim = group
        group.start()

    def show_settings_page(self) -> None:
        self._animate_page(_PAGE_SETTINGS)

    def show_capture_page(self) -> None:
        self._animate_page(_PAGE_CAPTURE)

    def _apply_chrome_for_page(self, page: int) -> None:
        if page == _PAGE_SETTINGS:
            self._title.setText(t("shell.capture_panel.settings"))
            self._close_btn.hide()
            self._back_btn.show()
            if hasattr(self, "_settings_btn"):
                self._settings_btn.setEnabled(False)
        else:
            self._title.setText(t("shell.capture_panel.title"))
            self._back_btn.hide()
            self._close_btn.show()
            if hasattr(self, "_settings_btn"):
                self._settings_btn.setEnabled(True)

    def _animate_page(self, page: int) -> None:
        target_size = (
            QSize(PANEL_SIZE, PANEL_SIZE)
            if page == _PAGE_CAPTURE
            else self._settings_target_size()
        )
        if (
            self._stack.currentIndex() == page
            and self.width() == target_size.width()
            and self.height() == target_size.height()
        ):
            return

        if self._page_anim is not None and self._page_anim.state() == QPropertyAnimation.Running:
            self._page_anim.stop()

        end = self._clamp_to_screen(self._geometry_keeping_bottom_right(target_size))
        start = self.geometry()

        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        # Swap content first; animate geometry only (smooth with translucent chrome)
        self._stack.setCurrentIndex(page)
        self._apply_chrome_for_page(page)

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(320)
        geo_anim.setStartValue(start)
        geo_anim.setEndValue(end)
        geo_anim.setEasingCurve(QEasingCurve.InOutCubic)

        def _finish() -> None:
            self.setFixedSize(target_size)
            self.move(end.topLeft())
            if page == _PAGE_SETTINGS:
                # Re-measure after layout settles (long folder names)
                self._on_settings_content_changed()

        geo_anim.finished.connect(_finish)
        self._page_anim = geo_anim
        geo_anim.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._show_anim is not None and self._show_anim.state() == QParallelAnimationGroup.Running:
            self._show_anim.stop()
        if self._page_anim is not None and self._page_anim.state() == QPropertyAnimation.Running:
            self._page_anim.stop()
        self.setWindowOpacity(1.0)
        # Next open always snaps to bottom-right
        self._placed_once = False
        self._stack.setCurrentIndex(_PAGE_CAPTURE)
        self._apply_chrome_for_page(_PAGE_CAPTURE)
        self.setFixedSize(PANEL_SIZE, PANEL_SIZE)
        self.closed.emit()
        self.hide()
        event.accept()

    def _drag_target(self, pos) -> bool:
        """Allow drag from title bar (not interactive chrome)."""
        child = self.childAt(pos)
        if child is None:
            return True
        blocked_names = {
            "capturePanelCloseButton",
            "capturePanelSettingsButton",
            "capturePanelBackButton",
        }
        w: QWidget | None = child
        while w is not None:
            if w.objectName() in blocked_names:
                return False
            if w is self._title_bar:
                return True
            if (
                w is self._capture_btn
                or w is self._cycle_btn
                or w is getattr(self, "_settings_btn", None)
            ):
                return False
            if w is self._stack:
                return False
            w = w.parentWidget()
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._drag_target(event.position().toPoint()):
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
