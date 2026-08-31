"""Organize page: select images and run bulk operations (Tags, Rename, …)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QLocale, Qt, Signal, QSize
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QMessageBox,
    QAbstractItemView,
    QAbstractSpinBox,
    QFrame,
    QFormLayout,
    QGraphicsDropShadowEffect,
    QInputDialog,
    QMenu,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QSizePolicy,
    QTextEdit,
    QFileDialog,
    QDateEdit,
)

from app.config import save_config
from app.i18n import t
from app.prototype_tour.events import emit_tour_event, tour_event_generation
from app.prototype_tour.models import UI_TAG_ADDED
from app.ui.checkbox import CapixeCheckBox
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import (
    GROUP_HEADER_HEIGHT,
    HEADER_VARIANT_NO_TAG,
    HEADER_VARIANT_ROLE,
    ITEM_KIND_HEADER,
    ITEM_KIND_IMAGE,
    ITEM_KIND_ROLE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_FAVORITE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    ROLE_CAPTION_TAGS_MUTED,
    CaptionIconDelegate,
)
from app.ui.icons import (
    icon_add,
    icon_clear,
    icon_folder,
    icon_images,
    icon_refresh,
    icon_search,
)
from app.ui.image_list_menu import (
    ensure_list_item_under_cursor_selected,
    populate_image_list_context_menu,
)
from app.ui.organize_ops import (
    OP_RENAME,
    OP_TAGS,
    OPERATION_SPECS,
    OPS_HINT_TO_LIST,
    OPS_ITEM_GAP,
    OPS_PAD_BOTTOM,
    OPS_PAD_TOP,
    OPS_PAD_X,
    OPS_TITLE_TO_HINT,
    OperationMenuItem,
    op_icon,
    op_spec,
)
from app.ui.widgets import ListPanelMarqueeBridge, ScreenshotListWidget
from app.ui.design_tokens import apply_card_shadow
from app.utils.file_clipboard import (
    clear_system_file_clipboard,
    paths_from_system_clipboard,
    set_files_on_clipboard,
    system_clipboard_is_cut,
)
from app.utils.group_by import (
    DEFAULT_GROUP_BY,
    GROUP_BY_NONE,
    NO_TAG_GROUP_KEY,
    build_groups,
    group_by_option_labels,
    normalize_group_by,
)

# Mild density scaling for Operations chrome + menu cards
_OPS_DENSITY = {
    "comfortable": {
        "title_pt": 15,
        "body_pt": 11,
        "section_pt": 11,
        "field_h": 28,
        "show_hints": True,
        "item_h": 68,
        "item_pad_x": 14,
        "item_pad_y": 12,
        "item_icon": 22,
        "item_gap": 10,
        "show_desc": True,
        "pad_x": 28,
        "pad_top": 28,
        "pad_bottom": 24,
        "title_gap": 10,
        "hint_gap": 18,
    },
    "normal": {
        "title_pt": 14,
        "body_pt": 11,
        "section_pt": 11,
        "field_h": 26,
        "show_hints": True,
        "item_h": 58,
        "item_pad_x": 12,
        "item_pad_y": 9,
        "item_icon": 20,
        "item_gap": 8,
        "show_desc": True,
        "pad_x": 24,
        "pad_top": 24,
        "pad_bottom": 20,
        "title_gap": 8,
        "hint_gap": 14,
    },
    "compact": {
        "title_pt": 13,
        "body_pt": 10,
        "section_pt": 10,
        "field_h": 24,
        "show_hints": True,
        "item_h": 46,
        "item_pad_x": 10,
        "item_pad_y": 7,
        "item_icon": 18,
        "item_gap": 6,
        "show_desc": False,
        "pad_x": 20,
        "pad_top": 20,
        "pad_bottom": 16,
        "title_gap": 6,
        "hint_gap": 10,
    },
    "tight": {
        "title_pt": 12,
        "body_pt": 10,
        "section_pt": 10,
        "field_h": 22,
        "show_hints": False,
        "item_h": 40,
        "item_pad_x": 10,
        "item_pad_y": 6,
        "item_icon": 16,
        "item_gap": 4,
        "show_desc": False,
        "pad_x": 16,
        "pad_top": 16,
        "pad_bottom": 12,
        "title_gap": 4,
        "hint_gap": 8,
    },
}
from app.utils.bulk_rename import build_sequential_names
from app.utils.save_folder import list_folder_names
from app.utils.search_filter import image_matches_search
from app.utils.selected_folder import get_selected_folder, set_selected_folder
from app.utils.sort_order import (
    DEFAULT_SORT_MODE,
    normalize_sort_mode,
    sort_option_labels,
    sort_png_files,
)
from app.utils.tag_format import format_tag, format_tags, normalize_tag
from app.utils.image_favorite import image_is_favorite, visible_tags
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import (
    DEFAULT_THUMBNAIL_MODE,
    THUMBNAIL_LIST_SPACING,
    THUMBNAIL_MODE_SIZES,
    normalize_thumbnail_mode,
    soft_wrap_filename,
    thumbnail_mode_labels,
)
from app.utils.workspace import resolve_current_folder, resolve_screenshot_root

CLIPBOARD_COPY = "copy"
CLIPBOARD_CUT = "cut"
TAG_CAPTION_ROW_HEIGHT = 16

# Operations card: hub (op list) ↔ detail (one op's settings)
_OPS_HUB = 0
_OPS_DETAIL = 1
OP_MOVE = "move"
_ACTION_COLOR_ROLE = Qt.UserRole + 701
_ACTION_COLORS = {
    OP_TAGS: "#2563eb",
    OP_RENAME: "#f59e0b",
    OP_MOVE: "#10b981",
}


def _batch_action_icon(op_id: str) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(_ACTION_COLORS[op_id]))
    painter.drawRoundedRect(1, 1, 12, 12, 2, 2)
    painter.end()
    return QIcon(pixmap)


class WorkPage(QWidget):
    """Bulk operations hub: pick images on the left, choose an operation on the right."""

    tags_changed = Signal()
    images_changed = Signal()
    folder_changed = Signal(str)

    def __init__(
        self,
        config: dict,
        metadata_service: MetadataService,
        thumbnail_cache: ThumbnailCache,
        app_root: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config
        self._metadata_service = metadata_service
        self._thumbnail_cache = thumbnail_cache
        self._app_root = app_root
        self._sort_mode = DEFAULT_SORT_MODE
        self._group_by = DEFAULT_GROUP_BY
        self._thumbnail_mode = DEFAULT_THUMBNAIL_MODE
        self._active_search_query = ""
        self._operations: dict[str, int] = {}
        self._op_buttons: dict[str, OperationMenuItem] = {}
        self._op_titles: dict[str, str] = {}
        self._ops_density = ""
        self._ops_fluid_labels: list[QLabel] = []
        self._ops_action_buttons: list[QPushButton] = []
        self._ops_fields: list[QWidget] = []
        self._clipboard_paths: list[Path] = []
        self._clipboard_mode: str | None = None
        self._current_op_id: str | None = None
        self._init_ui()
        self._setup_shortcuts()
        self._apply_thumbnail_mode()
        self._apply_ops_density(force=True)

    def _init_ui(self) -> None:
        from app.ui.page_header import PAGE_BODY_TOP_GAP, PAGE_HEADER_MARGINS, make_page_header

        self.setObjectName("organizePage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(
            make_page_header(
                self,
                t("work.title"),
                t("work.subtitle"),
                margins=PAGE_HEADER_MARGINS,
            )
        )

        body = QWidget(self)
        body.setObjectName("organizeBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, max(4, PAGE_BODY_TOP_GAP - 4), 12, 12)
        body_layout.setSpacing(8)

        list_panel = self._build_image_list_panel()
        ops_panel = self._build_operations_panel()
        apply_card_shadow(ops_panel)
        list_layout = list_panel.layout()
        list_layout.removeWidget(self._selection_row)
        list_layout.removeWidget(self._list)
        list_column = QFrame(list_panel)
        list_column.setObjectName("leftPanel")
        apply_card_shadow(list_column)
        self._list_column = list_column
        list_column_layout = QVBoxLayout(list_column)
        list_column_layout.setContentsMargins(12, 12, 12, 12)
        list_column_layout.setSpacing(8)
        list_column_layout.addWidget(self._build_list_section_header(list_column))
        list_column_layout.addWidget(self._selection_row)
        list_column_layout.addWidget(self._list, stretch=1)
        content_splitter = QSplitter(Qt.Horizontal, list_panel)
        content_splitter.setObjectName("organizeSplitter")
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(10)
        content_splitter.addWidget(list_column)
        content_splitter.addWidget(ops_panel)
        content_splitter.setStretchFactor(0, 7)
        content_splitter.setStretchFactor(1, 3)
        content_splitter.setSizes([720, 300])
        content_splitter.splitterMoved.connect(self._sync_top_control_widths)
        list_layout.addWidget(content_splitter, stretch=1)
        self._splitter = content_splitter
        body_layout.addWidget(list_panel)
        root.addWidget(body, stretch=1)

        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._apply_batch_visibility(False)
        self._sync_top_control_widths()

    @staticmethod
    def _apply_card_shadow(widget: QWidget) -> None:
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(18)
        effect.setOffset(0, 2)
        effect.setColor(QColor(15, 23, 42, 32))
        widget.setGraphicsEffect(effect)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "_splitter"):
            return
        if self._splitter.orientation() != Qt.Horizontal:
            self._splitter.setOrientation(Qt.Horizontal)
        self._apply_filter_layout()
        self._sync_top_control_widths()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_top_control_widths()

    def _sync_top_control_widths(self, *_args) -> None:
        if not hasattr(self, "_splitter"):
            return
        measured = self._list_column.width() if hasattr(self, "_list_column") else 0
        target = (
            measured
            if measured >= 240
            else max(360, int(max(0, self.width() - 44) * 0.70))
        )
        self._folder_bar.setMinimumWidth(target)
        self._folder_bar.setMaximumWidth(target)
        self._search_row.setMaximumWidth(target)
        self._filter_secondary.setMinimumWidth(target)
        self._filter_secondary.setMaximumWidth(target)

    def _apply_filter_layout(self, *, force: bool = False) -> None:
        if not hasattr(self, "_filter_secondary_grid"):
            return
        stacked = self.width() < 900
        if not force and stacked == self._filter_layout_stacked:
            return
        grid = self._filter_secondary_grid
        grid.removeWidget(self._date_row)
        grid.removeWidget(self._display_toolbar)
        grid.addWidget(self._date_row, 0, 0)
        grid.addWidget(self._display_toolbar, 1 if stacked else 0, 0 if stacked else 1)
        grid.setColumnStretch(0, 1 if stacked else 0)
        grid.setColumnStretch(1, 0 if stacked else 1)
        self._filter_layout_stacked = stacked

    def _apply_batch_visibility(self, has_selection: bool) -> None:
        if not hasattr(self, "_ops_panel"):
            return
        self._batch_action_controls.setVisible(has_selection)
        has_action = self._batch_action_combo.currentData() is not None
        self._ops_nav_stack.setVisible(has_selection and has_action)
        self._batch_idle_filler.setVisible(has_selection and not has_action)
        self._empty_state_holder.setVisible(not has_selection)
        self._no_selection_hint.setVisible(not has_selection)
        self._batch_selected_count.setVisible(has_selection)
        self._ops_panel_layout.setStretchFactor(
            self._empty_state_holder, 1 if not has_selection else 0
        )
        self._ops_panel_layout.setStretchFactor(
            self._batch_idle_filler, 1 if has_selection and not has_action else 0
        )
        self._ops_panel_layout.setStretchFactor(
            self._ops_nav_stack, 1 if has_selection and has_action else 0
        )
        self._ops_panel.setMinimumHeight(0)
        self._ops_panel.setMaximumHeight(16777215)

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _build_list_section_header(parent: QWidget) -> QWidget:
        header = QWidget(parent)
        header.setObjectName("sectionHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        title_row = QWidget(header)
        title_row.setObjectName("sectionHeaderTitleRow")
        title_row.setFixedHeight(28)
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(4, 0, 4, 0)
        title_layout.setSpacing(7)
        icon_label = QLabel(title_row)
        icon_label.setObjectName("sectionIcon")
        icon_label.setPixmap(icon_images().pixmap(QSize(14, 14)))
        title_layout.addWidget(icon_label, 0, Qt.AlignVCenter)
        title = QLabel(t("images.screenshots"), title_row)
        title.setObjectName("sectionTitle")
        title_layout.addWidget(title, 0, Qt.AlignVCenter)
        title_layout.addStretch(1)
        header_layout.addWidget(title_row)

        divider = QFrame(header)
        divider.setObjectName("sectionDivider")
        divider.setFrameShape(QFrame.HLine)
        header_layout.addWidget(divider)
        return header

    def _make_date_filter(self, placeholder: str, parent: QWidget) -> QDateEdit:
        edit = QDateEdit(parent)
        edit.setObjectName("organizeDateEdit")
        english_locale = QLocale(
            QLocale.Language.English, QLocale.Country.UnitedStates
        )
        edit.setLocale(english_locale)
        edit.setCalendarPopup(True)
        edit.calendarWidget().setLocale(english_locale)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setMinimumDate(self._date_minimum)
        edit.setMaximumDate(QDate(2999, 12, 31))
        edit.setSpecialValueText(placeholder)
        edit.setDate(self._date_minimum)
        edit.setMinimumWidth(96)
        edit.setMaximumWidth(112)
        return edit

    def _build_image_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("organizeListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        root_chip = QFrame(panel)
        root_chip.setObjectName("folderSelectorBar")
        self._folder_bar = root_chip
        root_chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root_chip_layout = QHBoxLayout(root_chip)
        root_chip_layout.setContentsMargins(7, 2, 7, 2)
        root_chip_layout.setSpacing(6)
        root_icon = QLabel(root_chip)
        root_icon.setObjectName("folderSelectorIcon")
        root_icon.setPixmap(icon_folder().pixmap(QSize(16, 16)))
        root_chip_layout.addWidget(root_icon, 0, Qt.AlignVCenter)
        root_label = QLabel(t("work.root_folder_label"), root_chip)
        root_chip_layout.addWidget(root_label)
        self._root_folder_value = QLabel("-", root_chip)
        self._root_folder_value.setObjectName("folderSelectorPath")
        self._root_folder_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._root_folder_value.setMinimumWidth(80)
        self._root_folder_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        root_chip_layout.addWidget(self._root_folder_value, stretch=1)
        self._choose_folder_btn = QPushButton(t("images.choose_folder"), root_chip)
        self._choose_folder_btn.setObjectName("secondaryButton")
        self._choose_folder_btn.setIcon(icon_folder())
        self._choose_folder_btn.setCursor(Qt.PointingHandCursor)
        self._choose_folder_btn.clicked.connect(self._choose_selected_folder)
        root_chip_layout.addWidget(self._choose_folder_btn)
        header.addWidget(root_chip)

        folder_chip = QFrame(panel)
        folder_chip.setObjectName("organizeFolderChip")
        folder_chip_layout = QHBoxLayout(folder_chip)
        folder_chip_layout.setContentsMargins(8, 4, 8, 4)
        folder_chip_layout.setSpacing(6)
        folder_label = QLabel(t("work.folder_label"), folder_chip)
        folder_label.setObjectName("organizeFolderLabel")
        folder_chip_layout.addWidget(folder_label)
        self._folder_combo = QComboBox(folder_chip)
        self._folder_combo.setObjectName("organizeFolderCombo")
        self._folder_combo.setMinimumWidth(110)
        self._folder_combo.setMaximumWidth(180)
        self._folder_combo.setCursor(Qt.PointingHandCursor)
        self._folder_combo.currentIndexChanged.connect(self._on_folder_combo_changed)
        folder_chip_layout.addWidget(self._folder_combo)
        header.addWidget(folder_chip)
        folder_chip.hide()
        header.addStretch(1)

        sel_box = QFrame(panel)
        sel_box.setObjectName("organizeSelectionBanner")
        sel_layout = QHBoxLayout(sel_box)
        sel_layout.setContentsMargins(2, 0, 2, 0)
        sel_layout.setSpacing(6)
        sel_heading = QLabel(t("work.selected_heading"), sel_box)
        sel_heading.setObjectName("organizeSelectedHeading")
        sel_layout.addWidget(sel_heading)
        sel_heading.hide()
        self._selected_count_label = QLabel(t("work.selected_count", count=0), sel_box)
        self._selected_count_label.setObjectName("organizeSelectedCount")
        sel_layout.addWidget(self._selected_count_label)
        self._selection_banner = sel_box
        layout.addLayout(header)

        toolbar = QWidget(panel)
        toolbar.setObjectName("headerTools")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(4, 2, 4, 4)
        tools.setSpacing(12)
        sort_label = QLabel(t("images.sort_label"), toolbar)
        sort_label.setObjectName("toolbarFieldLabel")
        tools.addWidget(sort_label)
        self._sort_combo = QComboBox(toolbar)
        self._sort_combo.setMinimumWidth(110)
        self._sort_combo.setMaximumWidth(160)
        self._sort_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in sort_option_labels():
            self._sort_combo.addItem(label, mode)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools.addWidget(self._sort_combo)

        group_label = QLabel(t("images.group_by_label"), toolbar)
        group_label.setObjectName("toolbarFieldLabel")
        tools.addWidget(group_label)
        self._group_combo = QComboBox(toolbar)
        self._group_combo.setMinimumWidth(64)
        self._group_combo.setMaximumWidth(90)
        self._group_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in group_by_option_labels():
            self._group_combo.addItem(label, mode)
        self._group_combo.currentIndexChanged.connect(self._on_group_by_changed)
        tools.addWidget(self._group_combo)

        view_label = QLabel(t("common.view"), toolbar)
        view_label.setObjectName("toolbarFieldLabel")
        tools.addWidget(view_label)
        self._view_combo = QComboBox(toolbar)
        self._view_combo.setMinimumWidth(64)
        self._view_combo.setMaximumWidth(90)
        self._view_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in thumbnail_mode_labels():
            self._view_combo.addItem(label, mode)
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        tools.addWidget(self._view_combo)

        self._show_tags_checkbox = CapixeCheckBox(t("images.show_tags"), toolbar)
        self._show_tags_checkbox.setObjectName("imagesShowTagsCheckBox")
        self._show_tags_checkbox.setToolTip(t("images.show_tags_tooltip"))
        self._show_tags_checkbox.setChecked(
            bool(self._config.get("show_tags_in_organize_list", True))
        )
        self._show_tags_checkbox.toggled.connect(self._on_show_tags_changed)
        tools.addWidget(self._show_tags_checkbox, 0, Qt.AlignVCenter)

        tools.addStretch(1)
        refresh_btn = QPushButton(t("images.refresh"), toolbar)
        refresh_btn.setObjectName("secondaryButton")
        refresh_btn.setIcon(icon_refresh())
        refresh_btn.setIconSize(QSize(14, 14))
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh)
        tools.addWidget(refresh_btn)
        layout.addWidget(toolbar)

        search_row = QWidget(panel)
        search_row.setObjectName("screenshotsSearchRow")
        self._search_row = search_row
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 2)
        search_layout.setSpacing(6)
        self._search_input = QLineEdit(search_row)
        self._search_input.setObjectName("screenshotsSearchInput")
        self._search_input.setPlaceholderText(t("images.search_placeholder"))
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input, stretch=1)
        search_btn = QPushButton(t("images.search"), search_row)
        search_btn.setIcon(icon_search())
        search_btn.setIconSize(QSize(14, 14))
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(search_btn)
        clear_search_btn = QPushButton(t("images.clear"), search_row)
        clear_search_btn.setObjectName("secondaryButton")
        clear_search_btn.setIcon(icon_clear())
        clear_search_btn.setIconSize(QSize(14, 14))
        clear_search_btn.setCursor(Qt.PointingHandCursor)
        clear_search_btn.clicked.connect(self._on_clear_search)
        search_layout.addWidget(clear_search_btn)
        layout.insertWidget(1, search_row)

        date_row = QWidget(panel)
        date_row.setObjectName("organizeDateFilterRow")
        date_layout = QHBoxLayout(date_row)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(6)
        date_label = QLabel(t("work.date_filter"), date_row)
        date_label.setObjectName("toolbarFieldLabel")
        date_layout.addWidget(date_label)
        self._date_minimum = QDate(1900, 1, 1)
        self._date_from = self._make_date_filter(t("work.date_from"), date_row)
        self._date_to = self._make_date_filter(t("work.date_to"), date_row)
        self._date_from.dateChanged.connect(self._on_date_filter_changed)
        self._date_to.dateChanged.connect(self._on_date_filter_changed)
        date_layout.addWidget(self._date_from)
        date_layout.addWidget(QLabel("–", date_row))
        date_layout.addWidget(self._date_to)
        self._clear_date_btn = QPushButton(t("work.clear_date"), date_row)
        self._clear_date_btn.setObjectName("secondaryButton")
        self._clear_date_btn.setCursor(Qt.PointingHandCursor)
        self._clear_date_btn.clicked.connect(self._clear_date_filter)
        date_layout.addWidget(self._clear_date_btn)
        layout.insertWidget(2, date_row)

        self._date_error_label = QLabel("", panel)
        self._date_error_label.setObjectName("organizeDateError")
        self._date_error_label.hide()
        layout.insertWidget(3, self._date_error_label)

        self._filter_secondary = QWidget(panel)
        self._filter_secondary.setObjectName("organizeFilterSecondary")
        self._filter_secondary_grid = QGridLayout(self._filter_secondary)
        self._filter_secondary_grid.setContentsMargins(0, 0, 0, 0)
        self._filter_secondary_grid.setHorizontalSpacing(10)
        self._filter_secondary_grid.setVerticalSpacing(4)
        layout.removeWidget(date_row)
        layout.removeWidget(toolbar)
        self._date_row = date_row
        self._display_toolbar = toolbar
        layout.insertWidget(2, self._filter_secondary)
        self._filter_layout_stacked: bool | None = None
        self._apply_filter_layout(force=True)

        selection_row = QWidget(panel)
        selection_row.setObjectName("organizeSelectionRow")
        self._selection_row = selection_row
        selection_layout = QHBoxLayout(selection_row)
        selection_layout.setContentsMargins(0, 2, 0, 2)
        selection_layout.setSpacing(6)
        selection_layout.addWidget(self._selection_banner)
        selection_layout.addStretch(1)
        self._select_results_btn = QPushButton(t("work.select_results"), selection_row)
        self._select_results_btn.setObjectName("secondaryButton")
        self._select_results_btn.setToolTip(t("work.select_results_tooltip"))
        self._select_results_btn.setCursor(Qt.PointingHandCursor)
        self._select_results_btn.clicked.connect(self._select_all)
        selection_layout.addWidget(self._select_results_btn)
        self._clear_selection_btn = QPushButton(
            t("work.clear_selection"), selection_row
        )
        self._clear_selection_btn.setObjectName("secondaryButton")
        self._clear_selection_btn.setCursor(Qt.PointingHandCursor)
        self._clear_selection_btn.clicked.connect(self._clear_selection)
        selection_layout.addWidget(self._clear_selection_btn)
        layout.addWidget(selection_row)

        self._list = ScreenshotListWidget(panel)
        self._list.setObjectName("organizeImageList")
        self._list.configure_explorer_selection()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.ElideNone)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(THUMBNAIL_LIST_SPACING)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setDragEnabled(False)
        self._list.setDragDropMode(QAbstractItemView.NoDragDrop)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        icon_size, grid_w, grid_h = THUMBNAIL_MODE_SIZES[self._thumbnail_mode]
        self._caption_delegate = CaptionIconDelegate(
            icon_size=icon_size,
            cell_width=grid_w,
            cell_height=grid_h,
            show_selection_badge=True,
            show_tags=bool(self._config.get("show_tags_in_organize_list", True)),
            parent=self._list,
        )
        self._list.setItemDelegate(self._caption_delegate)
        layout.addWidget(self._list, stretch=1)
        self._list_marquee_bridge = ListPanelMarqueeBridge(panel, self._list, self)
        return panel

    def _build_operations_panel(self) -> QWidget:
        """
        Single Operations card with hub ↔ detail navigation.

        Hub lists Batch Tags / Batch Rename / …; detail shows one op's form.
        Future ops (Convert, Resize, Export, …) register via OPERATION_SPECS.
        """
        panel = QFrame(self)
        panel.setObjectName("organizeOpsPanel")
        panel.setMinimumWidth(210)
        panel.setMaximumWidth(360)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        panel.installEventFilter(self)
        self._ops_panel = panel

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(OPS_PAD_X, OPS_PAD_TOP, OPS_PAD_X, OPS_PAD_BOTTOM)
        layout.setSpacing(0)
        self._ops_panel_layout = layout

        batch_title = QLabel(t("work.batch_actions"), panel)
        batch_title.setObjectName("organizeOpsTitle")
        layout.addWidget(batch_title)
        layout.addSpacing(4)

        self._batch_selected_count = QLabel("", panel)
        self._batch_selected_count.setObjectName("organizeBatchSelectedCount")
        self._batch_selected_count.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Fixed
        )
        layout.addWidget(self._batch_selected_count)
        layout.addSpacing(7)

        action_controls = QFrame(panel)
        action_controls.setObjectName("organizeBatchActionCard")
        action_controls.setProperty("actionId", "none")
        action_controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._batch_action_controls = action_controls
        action_layout = QVBoxLayout(action_controls)
        action_layout.setContentsMargins(9, 8, 9, 9)
        action_layout.setSpacing(4)
        action_label = QLabel(t("work.batch_action_select_label"), action_controls)
        action_label.setObjectName("organizeBulkSectionLabel")
        action_layout.addWidget(action_label)
        self._batch_action_combo = QComboBox(action_controls)
        self._batch_action_combo.setObjectName("organizeBatchActionCombo")
        self._batch_action_combo.setProperty("actionId", "none")
        self._batch_action_combo.setIconSize(QSize(14, 14))
        self._batch_action_combo.addItem(t("work.batch_action_choose"), None)
        for op_id, text_key in (
            (OP_TAGS, "work.tab_tags"),
            (OP_RENAME, "work.tab_rename"),
            (OP_MOVE, "work.tab_move"),
        ):
            self._batch_action_combo.addItem(
                _batch_action_icon(op_id), t(text_key), op_id
            )
            index = self._batch_action_combo.count() - 1
            self._batch_action_combo.setItemData(
                index, _ACTION_COLORS[op_id], _ACTION_COLOR_ROLE
            )
        self._batch_action_combo.currentIndexChanged.connect(
            self._on_batch_action_changed
        )
        action_layout.addWidget(self._batch_action_combo)

        self._batch_action_summary = QFrame(action_controls)
        self._batch_action_summary.setObjectName("organizeBatchActionSummary")
        summary_layout = QVBoxLayout(self._batch_action_summary)
        summary_layout.setContentsMargins(0, 2, 0, 0)
        summary_layout.setSpacing(0)
        self._batch_action_desc = QLabel("", self._batch_action_summary)
        self._batch_action_desc.setObjectName("organizeBatchActionDescription")
        self._batch_action_desc.setWordWrap(True)
        summary_layout.addWidget(self._batch_action_desc)
        self._batch_action_summary.hide()
        action_layout.addWidget(self._batch_action_summary)
        layout.addWidget(action_controls)
        layout.addSpacing(7)

        self._batch_idle_filler = QWidget(panel)
        self._batch_idle_filler.setObjectName("organizeBatchIdleFiller")
        self._batch_idle_filler.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        layout.addWidget(self._batch_idle_filler, stretch=1)

        self._empty_state_holder = QWidget(panel)
        self._empty_state_holder.setObjectName("organizeEmptyStateHolder")
        empty_holder_layout = QVBoxLayout(self._empty_state_holder)
        empty_holder_layout.setContentsMargins(0, 0, 0, 0)
        empty_holder_layout.setSpacing(0)
        empty_holder_layout.addStretch(1)

        self._no_selection_hint = QFrame(self._empty_state_holder)
        self._no_selection_hint.setObjectName("organizeNoSelectionHint")
        no_selection_layout = QVBoxLayout(self._no_selection_hint)
        no_selection_layout.setContentsMargins(14, 13, 14, 13)
        no_selection_layout.setSpacing(5)
        no_selection_title = QLabel(t("work.no_selection"), self._no_selection_hint)
        no_selection_title.setObjectName("organizeNoSelectionTitle")
        no_selection_title.setAlignment(Qt.AlignCenter)
        no_selection_layout.addWidget(no_selection_title)
        no_selection_body = QLabel(t("work.no_selection_hint"), self._no_selection_hint)
        no_selection_body.setObjectName("mutedLabel")
        no_selection_body.setWordWrap(True)
        no_selection_body.setAlignment(Qt.AlignCenter)
        no_selection_layout.addWidget(no_selection_body)
        empty_holder_layout.addWidget(self._no_selection_hint)
        empty_holder_layout.addStretch(1)
        layout.addWidget(self._empty_state_holder, stretch=1)

        self._ops_nav_stack = QStackedWidget(panel)
        self._ops_nav_stack.setObjectName("organizeOpsNavStack")
        layout.addWidget(self._ops_nav_stack, stretch=1)

        # --- Hub: operation list ---
        hub = QWidget(panel)
        hub.setObjectName("organizeOpsHub")
        hub_layout = QVBoxLayout(hub)
        hub_layout.setContentsMargins(0, 0, 0, 0)
        hub_layout.setSpacing(0)

        self._ops_title = QLabel(t("work.operations"), hub)
        self._ops_title.setObjectName("organizeOpsTitle")
        title_font = QFont(self._ops_title.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        self._ops_title.setFont(title_font)
        hub_layout.addWidget(self._ops_title)
        hub_layout.addSpacing(OPS_TITLE_TO_HINT)

        self._ops_hint = QLabel(t("work.operations_hint"), hub)
        self._ops_hint.setObjectName("organizeOpsHint")
        self._ops_hint.setWordWrap(True)
        hub_layout.addWidget(self._ops_hint)
        self._ops_fluid_labels.append(self._ops_hint)
        hub_layout.addSpacing(OPS_HINT_TO_LIST)

        picker_scroll = QScrollArea(hub)
        picker_scroll.setObjectName("organizeOpsScroll")
        picker_scroll.setWidgetResizable(True)
        picker_scroll.setFrameShape(QFrame.NoFrame)
        picker_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        picker_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        picker = QWidget(picker_scroll)
        picker.setObjectName("organizeOpPicker")
        self._op_picker = picker
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(OPS_ITEM_GAP)
        self._op_btn_layout = picker_layout
        picker_layout.addStretch(1)
        picker_scroll.setWidget(picker)
        hub_layout.addWidget(picker_scroll, stretch=1)
        self._ops_nav_stack.addWidget(hub)

        # --- Detail: one operation's settings ---
        detail = QWidget(panel)
        detail.setObjectName("organizeOpsDetail")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)

        self._ops_back_btn = QPushButton(t("work.operations_back"), detail)
        self._ops_back_btn.setObjectName("organizeOpsBackButton")
        self._ops_back_btn.setCursor(Qt.PointingHandCursor)
        self._ops_back_btn.clicked.connect(self._show_ops_hub)
        detail_layout.addWidget(self._ops_back_btn, 0, Qt.AlignLeft)
        detail_layout.addSpacing(OPS_TITLE_TO_HINT)

        header = QFrame(detail)
        header.setObjectName("organizeOpsDetailHeader")
        self._ops_detail_header = header
        header_col = QVBoxLayout(header)
        header_col.setContentsMargins(10, 10, 10, 10)
        header_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)

        self._ops_detail_icon = QLabel(header)
        self._ops_detail_icon.setObjectName("organizeOpsDetailIcon")
        self._ops_detail_icon.setFixedSize(28, 28)
        self._ops_detail_icon.setAlignment(Qt.AlignCenter)
        title_row.addWidget(self._ops_detail_icon, 0, Qt.AlignVCenter)

        self._ops_detail_title = QLabel("", header)
        self._ops_detail_title.setObjectName("organizeOpsTitle")
        title_row.addWidget(self._ops_detail_title, 1, Qt.AlignVCenter)
        header_col.addLayout(title_row)

        self._ops_detail_desc = QLabel("", header)
        self._ops_detail_desc.setObjectName("organizeOpsHint")
        self._ops_detail_desc.setWordWrap(True)
        header_col.addWidget(self._ops_detail_desc)
        self._ops_fluid_labels.append(self._ops_detail_desc)
        detail_layout.addWidget(header)
        header.hide()

        selected_strip = QFrame(detail)
        selected_strip.setObjectName("organizeOpsSelectedStrip")
        self._ops_selected_strip = selected_strip
        sel_lay = QVBoxLayout(selected_strip)
        sel_lay.setContentsMargins(10, 8, 10, 8)
        sel_lay.setSpacing(2)
        sel_heading = QLabel(t("work.selected_heading"), selected_strip)
        sel_heading.setObjectName("organizeBulkSectionLabel")
        sel_lay.addWidget(sel_heading)
        self._ops_fluid_labels.append(sel_heading)
        self._ops_detail_selected = QLabel(t("work.selected_count", count=0), selected_strip)
        self._ops_detail_selected.setObjectName("organizeOpsSelectedCount")
        sel_lay.addWidget(self._ops_detail_selected)
        self._ops_fluid_labels.append(self._ops_detail_selected)
        detail_layout.addWidget(selected_strip)
        selected_strip.hide()

        body_scroll = QScrollArea(detail)
        body_scroll.setObjectName("organizeOpsDetailScroll")
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._op_stack = QStackedWidget(body_scroll)
        self._op_stack.setObjectName("organizeOpStack")
        self._op_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body_scroll.setWidget(self._op_stack)
        detail_layout.addWidget(body_scroll, stretch=1)
        self._ops_nav_stack.addWidget(detail)

        builders = {
            OP_TAGS: self._build_tags_settings,
            OP_RENAME: self._build_rename_settings,
        }
        for spec in OPERATION_SPECS:
            self._add_operation_menu_item(spec)
            builder = builders.get(spec.op_id)
            if spec.enabled and builder is not None:
                self._register_operation_page(spec, builder())
        move_page = QLabel(t("work.move_existing_placeholder"), self._op_stack)
        move_page.setObjectName("mutedLabel")
        move_page.setWordWrap(True)
        move_page.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._operations[OP_MOVE] = self._op_stack.addWidget(move_page)
        self._op_titles[OP_MOVE] = t("work.tab_move")
        return panel

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_ops_panel", None) and event.type() == QEvent.Type.Resize:
            self._apply_ops_density()
        return super().eventFilter(obj, event)

    def _ops_density_for_height(self, height: int) -> str:
        """Pick density from panel height and how many menu rows must fit."""
        n = max(1, len(getattr(self, "_op_buttons", {}) or {"_": 1}))
        # Rough chrome: title + optional hint + paddings
        chrome = 72 + (36 if height >= 340 else 0)
        avail = max(60, height - chrome)
        per = avail / n
        if per >= 78 and height >= 520:
            return "comfortable"
        if per >= 60 and height >= 400:
            return "normal"
        if per >= 48 and height >= 300:
            return "compact"
        return "tight"

    def _apply_ops_density(self, *, force: bool = False) -> None:
        """Scale Operations padding / menu cards / fields to the panel size."""
        panel = getattr(self, "_ops_panel", None)
        if panel is None:
            return
        height = panel.height()
        if height < 80:
            return
        key = self._ops_density_for_height(height)
        if not force and key == self._ops_density:
            return
        self._ops_density = key
        d = _OPS_DENSITY[key]

        pad_x = 12
        pad_top = 9
        pad_bottom = 9
        self._ops_panel_layout.setContentsMargins(pad_x, pad_top, pad_x, pad_bottom)
        self._ops_panel_layout.setSpacing(0)
        self._op_btn_layout.setContentsMargins(0, 0, 0, 0)
        self._op_btn_layout.setSpacing(int(d["item_gap"]))

        self._set_label_pt(self._ops_title, int(d["title_pt"]), bold=True)
        if hasattr(self, "_ops_detail_title"):
            self._set_label_pt(self._ops_detail_title, int(d["title_pt"]), bold=True)
        show_hints = bool(d["show_hints"])
        on_hub = self._ops_nav_stack.currentIndex() == _OPS_HUB
        self._ops_hint.setVisible(show_hints and on_hub)
        if hasattr(self, "_ops_detail_desc"):
            self._ops_detail_desc.setVisible(show_hints)

        for label in self._ops_fluid_labels:
            name = label.objectName()
            if name in ("sectionTitle", "organizeOpsTitle"):
                self._set_label_pt(label, int(d["title_pt"]), bold=True)
            elif name in ("organizeBulkSectionLabel", "organizeOpsSelectedCount"):
                self._set_label_pt(label, int(d["section_pt"]), bold=True)
            else:
                self._set_label_pt(label, int(d["body_pt"]), bold=False)

        body_pt = int(d["body_pt"])
        field_h = int(d["field_h"])
        show_desc = bool(d["show_desc"])
        for item in self._op_buttons.values():
            item.apply_density(
                min_height=int(d["item_h"]),
                pad_x=int(d["item_pad_x"]),
                pad_y=int(d["item_pad_y"]),
                icon_size=int(d["item_icon"]),
                show_desc=show_desc,
                title_pt=body_pt + 1,
                desc_pt=max(9, body_pt - 1),
            )

        for btn in self._ops_action_buttons:
            font = QFont(btn.font())
            font.setPointSize(body_pt)
            btn.setFont(font)
            btn.setMinimumHeight(field_h)
            btn.setMaximumHeight(field_h + 6)
            btn.setIconSize(QSize(max(12, field_h - 10), max(12, field_h - 10)))

        for field in self._ops_fields:
            field.setMinimumHeight(field_h)
            field.setMaximumHeight(field_h + 4)
            font = QFont(field.font())
            font.setPointSize(body_pt)
            field.setFont(font)

        for settings in (
            getattr(self, "_tags_settings", None),
            getattr(self, "_rename_settings", None),
        ):
            if settings is None:
                continue
            lay = settings.layout()
            if lay is not None:
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(max(4, int(d["item_gap"]) - 2))

        if hasattr(self, "_rename_form"):
            self._rename_form.setSpacing(max(4, int(d["item_gap"]) - 2))

        panel.setProperty("opsDensity", key)
        self._repolish(panel)

    @staticmethod
    def _set_label_pt(label: QLabel, point_size: int, *, bold: bool) -> None:
        font = QFont(label.font())
        font.setPointSize(point_size)
        font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        label.setFont(font)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def _add_operation_menu_item(self, spec) -> OperationMenuItem:
        item = OperationMenuItem(
            spec,
            t(spec.title_key),
            t(spec.desc_key),
            self._op_picker,
        )
        item.clicked.connect(self._open_operation)
        # Insert before trailing stretch
        insert_at = max(0, self._op_btn_layout.count() - 1)
        self._op_btn_layout.insertWidget(insert_at, item)
        self._op_buttons[spec.op_id] = item
        self._op_titles[spec.op_id] = t(spec.title_key)
        self._repolish(item)
        return item

    def _register_operation_page(self, spec, settings: QWidget) -> None:
        """Register a detail settings page for an enabled operation."""
        index = self._op_stack.addWidget(settings)
        self._operations[spec.op_id] = index
        self._op_titles[spec.op_id] = t(spec.title_key)

    def _set_menu_selection(self, op_id: str | None) -> None:
        for oid, item in self._op_buttons.items():
            item.set_selected(oid == op_id)

    def _apply_op_chrome(self, op_id: str | None) -> None:
        """Tint detail chrome with the active operation accent (soft only)."""
        panel = getattr(self, "_ops_panel", None)
        if panel is None:
            return
        value = op_id or ""
        panel.setProperty("opId", value)
        if hasattr(self, "_ops_detail_header"):
            self._ops_detail_header.setProperty("opId", value)
        if hasattr(self, "_ops_selected_strip"):
            self._ops_selected_strip.setProperty("opId", value)
        for widget in (
            panel,
            getattr(self, "_ops_detail_header", None),
            getattr(self, "_ops_selected_strip", None),
            getattr(self, "_tags_settings", None),
            getattr(self, "_rename_settings", None),
        ):
            if widget is not None:
                self._repolish(widget)

    def _show_ops_hub(self) -> None:
        """Compatibility entry: the redesigned panel opens the active tab."""
        self._open_operation(self._current_op_id or OP_TAGS)

    def _on_batch_action_changed(self, _index: int) -> None:
        op_id = self._batch_action_combo.currentData()
        if op_id is None:
            self._current_op_id = None
            self._batch_action_controls.setProperty("actionId", "none")
            self._batch_action_combo.setProperty("actionId", "none")
            self._batch_action_desc.clear()
            self._batch_action_summary.hide()
            self._repolish(self._batch_action_controls)
            self._repolish(self._batch_action_combo)
            self._ops_nav_stack.hide()
            self._batch_idle_filler.show()
            self._ops_panel_layout.setStretchFactor(self._batch_idle_filler, 1)
            self._ops_panel_layout.setStretchFactor(self._ops_nav_stack, 0)
            return
        op_id = str(op_id)
        self._batch_action_controls.setProperty("actionId", op_id)
        self._batch_action_combo.setProperty("actionId", op_id)
        self._batch_action_desc.setText(t(f"work.batch_action_{op_id}_desc"))
        self._batch_action_summary.show()
        self._repolish(self._batch_action_controls)
        self._repolish(self._batch_action_combo)
        self._open_operation(op_id)

    def _open_operation(self, op_id: str) -> None:
        """Switch Operations card content to one operation's detail form."""
        if op_id not in self._operations:
            return
        spec = op_spec(op_id)
        self._current_op_id = op_id
        self._batch_action_controls.setProperty("actionId", op_id)
        self._batch_action_combo.setProperty("actionId", op_id)
        self._batch_action_desc.setText(t(f"work.batch_action_{op_id}_desc"))
        self._batch_action_summary.show()
        self._repolish(self._batch_action_controls)
        self._repolish(self._batch_action_combo)
        combo_index = self._batch_action_combo.findData(op_id)
        if combo_index >= 0 and combo_index != self._batch_action_combo.currentIndex():
            self._batch_action_combo.blockSignals(True)
            self._batch_action_combo.setCurrentIndex(combo_index)
            self._batch_action_combo.blockSignals(False)
        self._set_menu_selection(op_id)
        self._op_stack.setCurrentIndex(self._operations[op_id])
        title = self._op_titles.get(op_id, op_id)
        self._ops_detail_title.setText(title)
        if spec is not None:
            self._ops_detail_desc.setText(t(spec.hint_key))
            self._ops_detail_icon.setPixmap(
                op_icon(spec, size=22, selected=True).pixmap(22, 22)
            )
        else:
            self._ops_detail_desc.setText(t("work.move_existing_placeholder"))
            self._ops_detail_icon.clear()
        self._apply_op_chrome(op_id)
        self._ops_nav_stack.setCurrentIndex(_OPS_DETAIL)
        if self._selected_paths():
            self._batch_idle_filler.hide()
            self._ops_panel_layout.setStretchFactor(self._batch_idle_filler, 0)
            self._ops_panel_layout.setStretchFactor(self._ops_nav_stack, 1)
            self._ops_nav_stack.show()
        self._ops_back_btn.hide()
        self._apply_ops_density(force=True)
        if op_id == OP_RENAME:
            self._update_rename_preview()

    def _select_operation(self, op_id: str) -> None:
        """Compatibility helper — opens the operation detail view."""
        self._open_operation(op_id)

    def _build_tags_settings(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("organizeOpDetailBody")
        panel.setProperty("opId", OP_TAGS)
        self._tags_settings = panel
        tags_layout = QVBoxLayout(panel)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(8)

        def operation_card(title_key: str) -> tuple[QFrame, QVBoxLayout]:
            card = QFrame(panel)
            card.setObjectName("organizeTagActionCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(7, 6, 7, 7)
            card_layout.setSpacing(5)
            label = QLabel(t(title_key), card)
            label.setObjectName("organizeBulkSectionLabel")
            card_layout.addWidget(label)
            self._ops_fluid_labels.append(label)
            tags_layout.addWidget(card)
            return card, card_layout

        existing_card, existing_layout = operation_card("work.tag_existing")
        self._tag_add_combo = QComboBox(existing_card)
        self._tag_add_combo.setObjectName("organizeTagCombo")
        self._tag_add_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        existing_layout.addWidget(self._tag_add_combo)
        self._ops_fields.append(self._tag_add_combo)
        add_btn = QPushButton(t("work.apply_add"), existing_card)
        add_btn.setObjectName("organizeOpPrimaryButton")
        add_btn.setProperty("opId", OP_TAGS)
        add_btn.setIcon(icon_add())
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_bulk_add_tag)
        existing_layout.addWidget(add_btn)
        self._ops_action_buttons.append(add_btn)

        new_card, new_layout = operation_card("work.tag_new")
        self._tag_new_input = QLineEdit(new_card)
        self._tag_new_input.setPlaceholderText(t("work.tag_new_placeholder"))
        self._tag_new_input.returnPressed.connect(self._on_bulk_create_tag)
        new_layout.addWidget(self._tag_new_input)
        self._ops_fields.append(self._tag_new_input)
        new_btn = QPushButton(t("work.apply_new"), new_card)
        new_btn.setObjectName("organizeOpPrimaryButton")
        new_btn.setProperty("opId", OP_TAGS)
        new_btn.setIcon(icon_add())
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._on_bulk_create_tag)
        new_layout.addWidget(new_btn)
        self._ops_action_buttons.append(new_btn)

        remove_card, remove_layout = operation_card("work.tag_remove")
        self._tag_remove_combo = QComboBox(remove_card)
        self._tag_remove_combo.setObjectName("organizeTagCombo")
        self._tag_remove_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        remove_layout.addWidget(self._tag_remove_combo)
        self._ops_fields.append(self._tag_remove_combo)
        remove_btn = QPushButton(t("work.apply_remove"), remove_card)
        remove_btn.setObjectName("organizeOpSecondaryButton")
        remove_btn.setProperty("opId", OP_TAGS)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._on_bulk_remove_tag)
        remove_layout.addWidget(remove_btn)
        self._ops_action_buttons.append(remove_btn)
        tags_layout.addStretch(1)
        self._repolish(panel)
        return panel

    def _build_rename_settings(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("organizeOpDetailBody")
        panel.setProperty("opId", OP_RENAME)
        self._rename_settings = panel
        rename_layout = QVBoxLayout(panel)
        rename_layout.setContentsMargins(0, 0, 0, 0)
        rename_layout.setSpacing(OPS_ITEM_GAP)

        self._rename_form = QFormLayout()
        self._rename_form.setSpacing(OPS_ITEM_GAP)
        self._prefix_input = QLineEdit(panel)
        self._prefix_input.setPlaceholderText(t("work.rename_prefix_placeholder"))
        self._prefix_input.setText("ScreenShot_test_")
        self._prefix_input.textChanged.connect(self._update_rename_preview)
        self._rename_form.addRow(t("work.rename_prefix"), self._prefix_input)
        self._ops_fields.append(self._prefix_input)

        self._digits_spin = QSpinBox(panel)
        self._digits_spin.setMinimum(3)
        self._digits_spin.setMaximum(8)
        self._digits_spin.setValue(3)
        self._digits_spin.valueChanged.connect(self._update_rename_preview)
        self._rename_form.addRow(t("work.rename_digits"), self._digits_spin)
        self._ops_fields.append(self._digits_spin)
        rename_layout.addLayout(self._rename_form)

        self._rename_preview = QLabel(t("work.rename_preview_empty"), panel)
        self._rename_preview.setObjectName("mutedLabel")
        self._rename_preview.setWordWrap(True)
        rename_layout.addWidget(self._rename_preview)
        self._ops_fluid_labels.append(self._rename_preview)

        rename_btn = QPushButton(t("work.apply_rename"), panel)
        rename_btn.setObjectName("organizeOpPrimaryButton")
        rename_btn.setProperty("opId", OP_RENAME)
        rename_btn.setIcon(icon_images())
        rename_btn.setCursor(Qt.PointingHandCursor)
        rename_btn.clicked.connect(self._on_bulk_rename)
        rename_layout.addWidget(rename_btn, 0, Qt.AlignRight)
        self._ops_action_buttons.append(rename_btn)
        rename_layout.addStretch(1)
        self._repolish(panel)
        return panel

    # ----------------------------------------------------------- data / refresh
    def _get_folder_dir(self) -> Path:
        selected = get_selected_folder(self._config, self._app_root)
        if "selected_folder" in self._config:
            return selected or (self._app_root / "__unselected_folder__")
        return self._metadata_service.resolve_folder_dir(
            self._config.get("screenshot_dir", "screenshots"),
            resolve_current_folder(self._config),
            self._app_root,
        )

    def _root_folder_label(self) -> str:
        root = resolve_screenshot_root(
            self._config.get("screenshot_dir", "screenshots"),
            self._app_root,
        )
        return root.name or str(root)

    def refresh(self) -> None:
        selected = get_selected_folder(self._config, self._app_root)
        if "selected_folder" in self._config:
            display = str(selected) if selected else t("images.folder_unselected")
            self._root_folder_value.setText(display)
            self._root_folder_value.setToolTip(str(selected) if selected else "")
        else:
            self._root_folder_value.setText(self._root_folder_label())
            self._root_folder_value.setToolTip(
                str(
                    resolve_screenshot_root(
                        self._config.get("screenshot_dir", "screenshots"),
                        self._app_root,
                    )
                )
            )
        self._reload_folder_combo()
        self._load_display_from_project()
        self._apply_thumbnail_mode()
        self._reload_images()
        self._reload_tag_combos()
        self._update_selection_label()
        self._update_rename_preview()

    def _reload_folder_combo(self) -> None:
        if "selected_folder" in self._config:
            return
        names = list_folder_names(self._config, self._app_root)
        current = resolve_current_folder(self._config)
        self._folder_combo.blockSignals(True)
        self._folder_combo.clear()
        for name in names:
            self._folder_combo.addItem(name, name)
        index = self._folder_combo.findData(current)
        self._folder_combo.setCurrentIndex(index if index >= 0 else 0)
        self._folder_combo.blockSignals(False)

    def _on_folder_combo_changed(self, _index: int) -> None:
        name = self._folder_combo.currentData()
        if not name:
            name = self._folder_combo.currentText()
        if not name:
            return
        name = str(name)
        if name == resolve_current_folder(self._config):
            return
        self._config["current_folder"] = name
        try:
            save_config(self._config)
        except OSError:
            pass
        self._active_search_query = ""
        self._search_input.clear()
        self._load_display_from_project()
        self._apply_thumbnail_mode()
        self._reload_images()
        self._reload_tag_combos()
        self._update_rename_preview()
        self.folder_changed.emit(name)

    def _choose_selected_folder(self) -> None:
        current = get_selected_folder(self._config, self._app_root)
        start = str(current if current and current.exists() else Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            t("images.choose_folder_title"),
            start,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        path = set_selected_folder(self._config, selected)
        save_config(self._config)
        self._active_search_query = ""
        self._search_input.clear()
        self.refresh()
        self.folder_changed.emit(str(path))

    def _load_display_from_project(self) -> None:
        project_dir = self._get_folder_dir()
        if project_dir.exists():
            project = self._metadata_service.load_project(project_dir)
            display = project.get("display", {})
            self._sort_mode = normalize_sort_mode(display.get("sort_mode"))
            self._group_by = normalize_group_by(display.get("group_by"))
            self._thumbnail_mode = normalize_thumbnail_mode(
                display.get("thumbnail_mode")
            )
        else:
            self._sort_mode = DEFAULT_SORT_MODE
            self._group_by = DEFAULT_GROUP_BY
            self._thumbnail_mode = DEFAULT_THUMBNAIL_MODE
        self._sort_combo.blockSignals(True)
        index = self._sort_combo.findData(self._sort_mode)
        self._sort_combo.setCurrentIndex(index if index >= 0 else 0)
        self._sort_combo.blockSignals(False)
        self._group_combo.blockSignals(True)
        group_index = self._group_combo.findData(self._group_by)
        self._group_combo.setCurrentIndex(group_index if group_index >= 0 else 0)
        self._group_combo.blockSignals(False)
        self._view_combo.blockSignals(True)
        view_index = self._view_combo.findData(self._thumbnail_mode)
        self._view_combo.setCurrentIndex(view_index if view_index >= 0 else 0)
        self._view_combo.blockSignals(False)

    def _save_display_setting(self, key: str, value) -> None:
        project_dir = self._get_folder_dir()
        project_dir.mkdir(parents=True, exist_ok=True)
        project = self._metadata_service.load_project(project_dir)
        if "display" not in project:
            project["display"] = {}
        project["display"][key] = value
        self._metadata_service.save_project(project_dir, project)

    def _on_sort_changed(self) -> None:
        sort_mode = normalize_sort_mode(self._sort_combo.currentData())
        self._sort_mode = sort_mode
        try:
            self._save_display_setting("sort_mode", sort_mode)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.sort_save_failed", error=e)
            )
        self._reload_images()

    def _on_view_changed(self) -> None:
        mode = normalize_thumbnail_mode(self._view_combo.currentData())
        self._thumbnail_mode = mode
        try:
            self._save_display_setting("thumbnail_mode", mode)
            sizes = THUMBNAIL_MODE_SIZES.get(mode)
            if sizes:
                self._save_display_setting("thumbnail_size", sizes[0])
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.view_save_failed", error=e)
            )
            return
        self._apply_thumbnail_mode()
        self._reload_images()

    def _on_show_tags_changed(self, checked: bool) -> None:
        enabled = bool(checked)
        previous = bool(self._config.get("show_tags_in_organize_list", True))
        if previous == enabled:
            return
        self._config["show_tags_in_organize_list"] = enabled
        try:
            save_config(self._config)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.show_tags_save_failed", error=e)
            )
            self._show_tags_checkbox.blockSignals(True)
            self._show_tags_checkbox.setChecked(previous)
            self._show_tags_checkbox.blockSignals(False)
            self._config["show_tags_in_organize_list"] = previous
            return
        self._apply_thumbnail_mode()
        self._reload_images()

    def _on_group_by_changed(self) -> None:
        mode = normalize_group_by(self._group_combo.currentData())
        self._group_by = mode
        try:
            self._save_display_setting("group_by", mode)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.group_by_save_failed", error=e)
            )
            return
        self._apply_thumbnail_mode()
        self._reload_images()

    def _apply_thumbnail_mode(self) -> None:
        mode = normalize_thumbnail_mode(self._thumbnail_mode)
        icon_size, grid_w, grid_h = THUMBNAIL_MODE_SIZES[mode]
        show_tags = bool(self._config.get("show_tags_in_organize_list", True))
        if show_tags:
            grid_h += TAG_CAPTION_ROW_HEIGHT
        self._caption_delegate.set_list_mode(False)
        self._caption_delegate.set_show_tags(show_tags)
        self._caption_delegate.set_geometry(icon_size, grid_w, grid_h)
        self._caption_delegate._show_selection_badge = True
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setFlow(QListWidget.LeftToRight)
        self._list.setWrapping(True)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setIconSize(QSize(icon_size, icon_size))
        # Same spacing model as Images / Group By (sizeHint + list spacing)
        self._list.setGridSize(QSize())
        self._list.setSpacing(THUMBNAIL_LIST_SPACING)
        # Card height follows the complete wrapped filename.
        self._list.setUniformItemSizes(False)
        self._list.configure_explorer_selection()
        self._list.setDragEnabled(False)
        self._list.setDragDropMode(QAbstractItemView.NoDragDrop)
        style = self._list.style()
        if style is not None:
            style.unpolish(self._list)
            style.polish(self._list)
        self._list.update()

    def _on_search(self) -> None:
        self._active_search_query = self._search_input.text().strip()
        self._reload_images()

    def _on_clear_search(self) -> None:
        self._search_input.clear()
        self._active_search_query = ""
        self._reload_images()

    def _date_value(self, edit: QDateEdit) -> QDate | None:
        value = edit.date()
        return None if value == self._date_minimum else value

    def _date_range_is_valid(self) -> bool:
        date_from = self._date_value(self._date_from)
        date_to = self._date_value(self._date_to)
        valid = not (date_from and date_to and date_from > date_to)
        self._date_error_label.setText(
            "" if valid else t("work.date_invalid_range")
        )
        self._date_error_label.setVisible(not valid)
        return valid

    def _on_date_filter_changed(self, _date: QDate) -> None:
        if self._date_range_is_valid():
            self._reload_images()

    def _clear_date_filter(self) -> None:
        self._date_from.blockSignals(True)
        self._date_to.blockSignals(True)
        self._date_from.setDate(self._date_minimum)
        self._date_to.setDate(self._date_minimum)
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(False)
        self._date_error_label.hide()
        self._reload_images()

    def _matches_date_filter(self, path: Path) -> bool:
        modified = QDate.fromString(
            datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d"),
            "yyyy-MM-dd",
        )
        date_from = self._date_value(self._date_from)
        date_to = self._date_value(self._date_to)
        return not ((date_from and modified < date_from) or (date_to and modified > date_to))

    def _reload_images(self) -> None:
        selected = {
            item.data(Qt.UserRole)
            for item in self._list.selectedItems()
            if item.data(Qt.UserRole)
        }
        self._list.clear()
        folder_dir = self._get_folder_dir()
        if not folder_dir.exists():
            self._result_count = 0
            self._update_selection_label()
            return

        png_files = list(folder_dir.glob("*.png"))
        metadata = self._metadata_service.load_metadata(folder_dir)
        if self._active_search_query:
            filtered: list[Path] = []
            for path in png_files:
                tags = metadata.get("images", {}).get(path.name, {}).get("tags", [])
                if image_matches_search(path.name, tags, self._active_search_query):
                    filtered.append(path)
            png_files = filtered

        png_files = [path for path in png_files if self._matches_date_filter(path)]
        self._result_count = len(png_files)

        seen_paths: set[str] = set()
        for group_key, group_files in build_groups(
            png_files, self._group_by, metadata, self._sort_mode
        ):
            # Organize must show/select each physical image once even when it has
            # multiple tags; duplicate cards would make batch counts unsafe.
            group_files = [
                path
                for path in group_files
                if str(path.resolve()) not in seen_paths
            ]
            seen_paths.update(str(path.resolve()) for path in group_files)
            if not group_files:
                continue
            if self._group_by != GROUP_BY_NONE:
                self._list.addItem(self._create_group_header(group_key))
            for path in group_files:
                item = self._create_list_item(path, metadata)
                self._list.addItem(item)
                if str(path.resolve()) in selected:
                    item.setSelected(True)

        self._apply_cut_visuals()
        self._update_selection_label()

    def _create_group_header(self, group_key: str) -> QListWidgetItem:
        title = t("group_by.no_tag") if group_key == NO_TAG_GROUP_KEY else group_key
        item = QListWidgetItem(title)
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_HEADER)
        item.setData(HEADER_VARIANT_ROLE, HEADER_VARIANT_NO_TAG if group_key == NO_TAG_GROUP_KEY else "")
        item.setFlags(Qt.ItemIsEnabled)
        font = QFont(item.font())
        font.setWeight(
            QFont.Weight.DemiBold
            if group_key != NO_TAG_GROUP_KEY
            else QFont.Weight.Normal
        )
        item.setFont(font)
        item.setSizeHint(QSize(max(self._list.viewport().width() - 8, 240), GROUP_HEADER_HEIGHT))
        return item

    def _create_list_item(
        self, file_path: Path, metadata: dict | None = None
    ) -> QListWidgetItem:
        if metadata is None:
            metadata = self._metadata_service.load_metadata(file_path.parent)
        tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])

        icon_size, grid_w, grid_h = THUMBNAIL_MODE_SIZES[
            normalize_thumbnail_mode(self._thumbnail_mode)
        ]
        item = QListWidgetItem("")
        item.setIcon(self._thumbnail_cache.get_icon(file_path, size=icon_size))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        item.setSizeHint(QSize(grid_w - 4, grid_h - 4))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setData(Qt.UserRole, str(file_path.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        item.setData(ROLE_CAPTION_NAME, soft_wrap_filename(file_path.name))
        visible = visible_tags(tags)
        item.setData(
            ROLE_CAPTION_TAGS,
            format_tags(visible, empty=t("images.tag.none")),
        )
        item.setData(ROLE_CAPTION_TAGS_MUTED, not bool(visible))
        item.setData(ROLE_CAPTION_DATE, self._caption_date_text(file_path))
        item.setData(ROLE_CAPTION_FAVORITE, image_is_favorite(metadata, file_path.name))
        item.setToolTip(
            f"{file_path.name}\n"
            f"{format_tags(visible, empty=t('images.tag.none'))}"
        )
        return item

    def _caption_date_text(self, file_path: Path) -> str:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        return mtime.strftime("%Y-%m-%d %H:%M")

    def _reload_tag_combos(self) -> None:
        global_tags = self._metadata_service.load_global_tags(
            self._app_root, force_reload=True
        )
        self._tag_add_combo.blockSignals(True)
        self._tag_add_combo.clear()
        self._tag_add_combo.addItem(t("work.tag_choose"), "")
        for tag in global_tags:
            self._add_tag_combo_item(self._tag_add_combo, tag)
        self._tag_add_combo.setCurrentIndex(0)
        self._tag_add_combo.blockSignals(False)

        folder_dir = self._get_folder_dir()
        used: set[str] = set()
        if folder_dir.exists():
            meta = self._metadata_service.load_metadata(folder_dir, force_reload=True)
            for entry in meta.get("images", {}).values():
                used.update(entry.get("tags", []))
        self._tag_remove_combo.blockSignals(True)
        self._tag_remove_combo.clear()
        self._tag_remove_combo.addItem(t("work.tag_choose"), "")
        for tag in sorted(used, key=str.casefold):
            self._add_tag_combo_item(self._tag_remove_combo, tag)
        self._tag_remove_combo.setCurrentIndex(0)
        self._tag_remove_combo.blockSignals(False)

    @staticmethod
    def _add_tag_combo_item(combo: QComboBox, tag: str) -> None:
        label = format_tag(tag)
        combo.addItem(label, tag)
        index = combo.count() - 1
        combo.setItemData(index, label, Qt.ToolTipRole)

    def _combo_tag(self, combo: QComboBox) -> str:
        data = combo.currentData()
        if data:
            return normalize_tag(str(data))
        return normalize_tag(combo.currentText())

    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for item in self._list.selectedItems():
            data = item.data(Qt.UserRole)
            if data and str(data) not in seen:
                seen.add(str(data))
                paths.append(Path(data))
        return paths

    def _select_all(self) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(ITEM_KIND_ROLE) == ITEM_KIND_IMAGE:
                item.setSelected(True)

    def _clear_selection(self) -> None:
        self._list.clearSelection()

    def _on_selection_changed(self) -> None:
        self._update_selection_label()
        self._update_rename_preview()

    def _update_selection_label(self) -> None:
        count = len(self._list.selectedItems())
        results = getattr(self, "_result_count", 0)
        text = t("work.results_selected", results=results, selected=count)
        self._selected_count_label.setText(text)
        folder_selected = (
            bool(get_selected_folder(self._config, self._app_root))
            if "selected_folder" in self._config
            else self._get_folder_dir().exists()
        )
        self._selection_banner.setVisible(folder_selected)
        self._select_results_btn.setEnabled(results > 0 and count < results)
        self._clear_selection_btn.setEnabled(count > 0)
        has_selection = count > 0
        self._apply_batch_visibility(has_selection)
        self._op_stack.setEnabled(has_selection)
        for button in self._ops_action_buttons:
            button.setEnabled(has_selection)
        if hasattr(self, "_ops_detail_selected"):
            self._ops_detail_selected.setText(t("work.selected_count", count=count))
        if hasattr(self, "_batch_selected_count"):
            self._batch_selected_count.setText(
                t(
                    "work.batch_selected_count_one"
                    if count == 1
                    else "work.batch_selected_count",
                    count=count,
                )
            )

    # ----------------------------------------------------------- operations
    def _on_bulk_create_tag(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, t("work.title"), t("work.need_selection"))
            return
        raw = normalize_tag(self._tag_new_input.text())
        if not raw:
            return
        try:
            tag_name = self._metadata_service.ensure_global_tag(self._app_root, raw)
            if not tag_name:
                return
            count = 0
            for path in paths:
                if self._metadata_service.add_image_tag(
                    path.parent, path.name, tag_name
                ):
                    count += 1
            self._tag_new_input.clear()
            self._reload_tag_combos()
            self._reload_images()
            self.tags_changed.emit()
            QMessageBox.information(
                self,
                t("work.title"),
                t("work.tag_add_done", tag=format_tag(tag_name), count=count),
            )
            if count:
                emit_tour_event(UI_TAG_ADDED, generation=tour_event_generation())
        except OSError as e:
            QMessageBox.critical(self, t("common.error"), t("work.tag_failed", error=e))

    def _on_bulk_add_tag(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, t("work.title"), t("work.need_selection"))
            return
        tag = self._combo_tag(self._tag_add_combo)
        if not tag:
            return
        try:
            count = 0
            for path in paths:
                if self._metadata_service.add_image_tag(path.parent, path.name, tag):
                    count += 1
            self._reload_tag_combos()
            self._reload_images()
            self.tags_changed.emit()
            QMessageBox.information(
                self,
                t("work.title"),
                t("work.tag_add_done", tag=format_tag(tag), count=count),
            )
            if count:
                emit_tour_event(UI_TAG_ADDED, generation=tour_event_generation())
        except OSError as e:
            QMessageBox.critical(self, t("common.error"), t("work.tag_failed", error=e))

    def _on_bulk_remove_tag(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, t("work.title"), t("work.need_selection"))
            return
        tag = self._combo_tag(self._tag_remove_combo)
        if not tag:
            return
        try:
            count = 0
            for path in paths:
                if self._metadata_service.remove_image_tag(path.parent, path.name, tag):
                    count += 1
            self._reload_tag_combos()
            self._reload_images()
            self.tags_changed.emit()
            QMessageBox.information(
                self,
                t("work.title"),
                t("work.tag_remove_done", tag=format_tag(tag), count=count),
            )
        except OSError as e:
            QMessageBox.critical(self, t("common.error"), t("work.tag_failed", error=e))

    def _update_rename_preview(self) -> None:
        paths = self._selected_paths()
        prefix = self._prefix_input.text().strip()
        if not paths or not prefix:
            self._rename_preview.setText(t("work.rename_preview_empty"))
            return
        mapping = build_sequential_names(paths, prefix, self._digits_spin.value())
        samples = mapping[:3]
        lines = [f"{src.name} → {new_name}" for src, new_name in samples]
        if len(mapping) > 3:
            lines.append(t("work.rename_preview_more", count=len(mapping) - 3))
        self._rename_preview.setText("\n".join(lines))

    def _on_bulk_rename(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, t("work.title"), t("work.need_selection"))
            return
        prefix = self._prefix_input.text().strip()
        if not prefix:
            QMessageBox.warning(
                self, t("common.warning"), t("work.rename_prefix_required")
            )
            return

        mapping = build_sequential_names(paths, prefix, self._digits_spin.value())
        project_dir = self._get_folder_dir()

        selected_names = {p.name for p in paths}
        existing = {
            p.name for p in project_dir.glob("*.png") if p.name not in selected_names
        }
        for _, new_name in mapping:
            if new_name in existing:
                QMessageBox.warning(
                    self,
                    t("common.warning"),
                    t("work.rename_conflict", name=new_name),
                )
                return

        reply = QMessageBox.question(
            self,
            t("work.bulk_rename"),
            t("work.rename_confirm", count=len(mapping), prefix=prefix),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            temp_map: list[tuple[str, str]] = []
            for i, (src, new_name) in enumerate(mapping):
                temp_name = f"__sstool_tmp_{i:06d}__.png"
                self._metadata_service.rename_image(project_dir, src.name, temp_name)
                temp_map.append((temp_name, new_name))
                self._thumbnail_cache.invalidate(src)

            for temp_name, new_name in temp_map:
                dest = self._metadata_service.rename_image(
                    project_dir, temp_name, new_name
                )
                self._thumbnail_cache.invalidate(project_dir / temp_name)
                self._thumbnail_cache.invalidate(dest)

            self._reload_images()
            self.images_changed.emit()
            QMessageBox.information(
                self,
                t("work.title"),
                t("work.rename_done", count=len(mapping)),
            )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("work.rename_failed", error=e)
            )
            self._reload_images()

    # ------------------------------------------- context menu / clipboard
    def _setup_shortcuts(self) -> None:
        bindings = [
            (QKeySequence.SelectAll, self._select_all),
            (QKeySequence(Qt.Key_Escape), self._clear_selection),
            (QKeySequence.Copy, self._shortcut_copy),
            (QKeySequence.Cut, self._shortcut_cut),
            (QKeySequence.Paste, self._shortcut_paste),
            (QKeySequence.Delete, self._shortcut_delete),
            (QKeySequence(Qt.Key_F2), self._shortcut_rename),
        ]
        for sequence, slot in bindings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _file_shortcut_focus_ok(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QAbstractSpinBox)):
            return False
        if isinstance(focus, QComboBox) and focus.isEditable():
            return False
        return True

    def _shortcut_copy(self) -> None:
        if self._file_shortcut_focus_ok():
            self._copy_selected_images()

    def _shortcut_cut(self) -> None:
        if self._file_shortcut_focus_ok():
            self._cut_selected_images()

    def _shortcut_paste(self) -> None:
        if self._file_shortcut_focus_ok():
            self._paste_clipboard()

    def _shortcut_delete(self) -> None:
        if self._file_shortcut_focus_ok():
            self._delete_selected_images()

    def _shortcut_rename(self) -> None:
        if self._file_shortcut_focus_ok():
            self._rename_selected_image()

    def _on_context_menu(self, pos) -> None:
        ensure_list_item_under_cursor_selected(self._list, pos)
        menu = QMenu(self)
        populate_image_list_context_menu(
            menu,
            self,
            thumbnail_mode=self._thumbnail_mode,
            selected_count=len(self._selected_paths()),
            has_clipboard=self._has_clipboard(),
            on_set_thumbnail_mode=self._set_thumbnail_mode_from_menu,
            on_open=self._open_selected_images,
            on_copy=self._copy_selected_images,
            on_cut=self._cut_selected_images,
            on_paste=self._paste_clipboard,
            on_rename=self._rename_selected_image,
            on_delete=self._delete_selected_images,
            on_explorer=self._open_selected_in_explorer,
        )
        menu.exec(self._list.mapToGlobal(pos))

    def _set_thumbnail_mode_from_menu(self, mode: str) -> None:
        mode = normalize_thumbnail_mode(mode)
        self._thumbnail_mode = mode
        index = self._view_combo.findData(mode)
        if index >= 0:
            self._view_combo.blockSignals(True)
            self._view_combo.setCurrentIndex(index)
            self._view_combo.blockSignals(False)
        try:
            self._save_display_setting("thumbnail_mode", mode)
            sizes = THUMBNAIL_MODE_SIZES.get(mode)
            if sizes:
                self._save_display_setting("thumbnail_size", sizes[0])
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.view_save_failed", error=e)
            )
            return
        self._apply_thumbnail_mode()
        self._reload_images()

    def _has_clipboard(self) -> bool:
        if bool(self._clipboard_mode) and any(
            p.exists() for p in self._clipboard_paths
        ):
            return True
        return bool(paths_from_system_clipboard())

    def _resolve_paste_sources(self) -> tuple[list[Path], str | None]:
        if self._clipboard_mode and any(p.exists() for p in self._clipboard_paths):
            return (
                [p for p in self._clipboard_paths if p.exists()],
                self._clipboard_mode,
            )
        system_paths = paths_from_system_clipboard()
        if not system_paths:
            return [], None
        mode = CLIPBOARD_CUT if system_clipboard_is_cut() else CLIPBOARD_COPY
        return system_paths, mode

    def _set_clipboard(self, paths: list[Path], mode: str) -> None:
        valid = [p for p in paths if p.exists()]
        self._clipboard_paths = list(valid)
        self._clipboard_mode = mode if valid else None
        self._apply_cut_visuals()
        if valid:
            set_files_on_clipboard(valid, cut=(mode == CLIPBOARD_CUT))

    def _clear_clipboard(self) -> None:
        self._clipboard_paths = []
        self._clipboard_mode = None
        self._apply_cut_visuals()
        clear_system_file_clipboard()

    def _is_cut_path(self, file_path: Path) -> bool:
        if self._clipboard_mode != CLIPBOARD_CUT:
            return False
        resolved = str(file_path.resolve())
        return any(str(p.resolve()) == resolved for p in self._clipboard_paths)

    def _style_item_as_cut(self, item: QListWidgetItem, file_path: Path) -> None:
        icon_size = THUMBNAIL_MODE_SIZES[
            normalize_thumbnail_mode(self._thumbnail_mode)
        ][0]
        base = self._thumbnail_cache.get_icon(file_path, size=icon_size).pixmap(
            icon_size, icon_size
        )
        faded = QPixmap(base.size())
        faded.fill(Qt.transparent)
        painter = QPainter(faded)
        painter.setOpacity(0.35)
        painter.drawPixmap(0, 0, base)
        painter.end()
        item.setIcon(QIcon(faded))
        item.setForeground(QBrush(QColor(156, 163, 175)))

    def _apply_cut_visuals(self) -> None:
        icon_size = THUMBNAIL_MODE_SIZES[
            normalize_thumbnail_mode(self._thumbnail_mode)
        ][0]
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None:
                continue
            path_str = item.data(Qt.UserRole)
            if not path_str:
                continue
            path = Path(path_str)
            if self._is_cut_path(path):
                self._style_item_as_cut(item, path)
            else:
                item.setIcon(self._thumbnail_cache.get_icon(path, size=icon_size))
                item.setForeground(QBrush(QColor("#1f2937")))

    def _copy_selected_images(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        self._set_clipboard(paths, CLIPBOARD_COPY)

    def _cut_selected_images(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        self._set_clipboard(paths, CLIPBOARD_CUT)

    def _paste_clipboard(self) -> None:
        valid, mode = self._resolve_paste_sources()
        if not mode or not valid:
            if self._clipboard_mode:
                self._clear_clipboard()
            return

        project_dir = self._get_folder_dir()
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(project_dir)
            if mode == CLIPBOARD_CUT:
                for path in valid:
                    dest = self._metadata_service.move_image_to_project(
                        path, project_dir
                    )
                    self._thumbnail_cache.invalidate(path)
                    self._thumbnail_cache.invalidate(dest)
                self._clear_clipboard()
            else:
                for path in valid:
                    dest = self._metadata_service.copy_image_to_project(
                        path, project_dir
                    )
                    self._thumbnail_cache.invalidate(dest)
            self._metadata_service.invalidate_cache(project_dir)
            self._reload_images()
            self.images_changed.emit()
        except OSError as e:
            key = (
                "images.cut.failed" if mode == CLIPBOARD_CUT else "images.paste.failed"
            )
            QMessageBox.critical(self, t("common.error"), t(key, error=e))

    def _open_selected_images(self) -> None:
        for path in self._selected_paths():
            if path.exists():
                os.startfile(str(path))

    def _open_selected_in_explorer(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        parent = paths[0].parent
        if parent.exists():
            os.startfile(str(parent))

    def _rename_selected_image(self) -> None:
        paths = self._selected_paths()
        if len(paths) != 1:
            return
        path = paths[0]
        stem = path.stem
        new_stem, ok = QInputDialog.getText(
            self,
            t("images.rename_title"),
            t("images.rename_prompt"),
            text=stem,
        )
        if not ok:
            return
        new_stem = new_stem.strip()
        if not new_stem:
            QMessageBox.warning(
                self, t("common.warning"), t("images.rename_invalid")
            )
            return
        if new_stem.lower().endswith(".png"):
            new_stem = new_stem[:-4]
        if any(ch in new_stem for ch in '<>:"/\\|?*'):
            QMessageBox.warning(
                self, t("common.warning"), t("images.rename_invalid")
            )
            return
        new_name = f"{new_stem}.png"
        if new_name == path.name:
            return
        try:
            dest = self._metadata_service.rename_image(
                path.parent, path.name, new_name
            )
            self._thumbnail_cache.invalidate(path)
            self._reload_images()
            self.images_changed.emit()
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item and item.data(Qt.UserRole) == str(dest.resolve()):
                    item.setSelected(True)
                    self._list.setCurrentItem(item)
                    break
        except FileExistsError:
            QMessageBox.warning(
                self, t("common.warning"), t("images.rename_exists")
            )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.rename_failed", error=e)
            )

    def _delete_selected_images(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        if len(paths) == 1:
            message = t("images.delete_confirm", name=paths[0].name)
        else:
            message = t("images.delete_confirm_multi", count=len(paths))
        reply = QMessageBox.question(
            self,
            t("common.confirm_delete"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            deleted_keys = {str(p.resolve()) for p in paths}
            for file_path in paths:
                if not file_path.exists():
                    continue
                self._metadata_service.delete_image_file(
                    file_path.parent, file_path.name
                )
                self._thumbnail_cache.invalidate(file_path)
            if self._clipboard_paths:
                remaining = [
                    p
                    for p in self._clipboard_paths
                    if str(p.resolve()) not in deleted_keys
                ]
                if remaining:
                    self._clipboard_paths = remaining
                    set_files_on_clipboard(
                        remaining, cut=(self._clipboard_mode == CLIPBOARD_CUT)
                    )
                    self._apply_cut_visuals()
                else:
                    self._clear_clipboard()
            self._reload_images()
            self.images_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.delete_failed", error=e)
            )
