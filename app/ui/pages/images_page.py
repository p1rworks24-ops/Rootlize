from pathlib import Path
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QSize, QEvent, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import (
    QPixmap,
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QSplitter,
    QMenu,
    QMessageBox,
    QLineEdit,
    QComboBox,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
    QAbstractItemView,
    QButtonGroup,
    QFrame,
)

from app.config import save_config
from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import (
    GROUP_HEADER_HEIGHT,
    HEADER_VARIANT_NO_TAG,
    HEADER_VARIANT_ROLE,
    ITEM_KIND_HEADER,
    ITEM_KIND_IMAGE,
    ITEM_KIND_ROLE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    ROLE_CAPTION_TAGS_MUTED,
    CaptionIconDelegate,
)
from app.ui.icons import (
    icon_clear,
    icon_folder,
    icon_images,
    icon_new_folder,
    icon_preview,
    icon_refresh,
    icon_search,
    icon_tags,
    project_tree_icon,
)
from app.ui.widgets import ScreenshotListWidget, ProjectTreeWidget
from app.utils.group_by import (
    DEFAULT_GROUP_BY,
    GROUP_BY_NONE,
    GROUP_BY_TAG,
    NO_TAG_GROUP_KEY,
    build_groups,
    group_by_option_labels,
    normalize_group_by,
)
from app.utils.file_copy_name import make_unique_copy_filename
from app.utils.folder_ops import (
    delete_folder,
    duplicate_folder,
    is_valid_folder_name,
    rename_folder,
)
from app.utils.search_filter import image_matches_search
from app.utils.sort_order import (
    DEFAULT_SORT_MODE,
    normalize_sort_mode,
    should_insert_before,
    sort_option_labels,
)
from app.utils.tag_format import format_tag, format_tags, normalize_tag
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import (
    DEFAULT_THUMBNAIL_MODE,
    THUMBNAIL_MODE_SIZES,
    is_list_mode,
    normalize_thumbnail_mode,
    soft_wrap_filename,
    thumbnail_mode_labels,
)
from app.utils.workspace import (
    DEFAULT_FOLDER,
    list_folder_names as workspace_list_folders,
    pick_folder_name,
    resolve_current_folder,
    resolve_save_folder,
)

TAG_MODE_EXISTING = 0
TAG_MODE_NEW = 1

THUMBNAIL_ICON_SIZE = 128
PREVIEW_PADDING = 24
SECTION_ICON_SIZE = 14
FOLDER_PANEL_EXPANDED_WIDTH = 220
FOLDER_PANEL_COLLAPSED_WIDTH = 36
FOLDER_PANEL_MAX_WIDTH = 360
FOLDER_PANEL_MIN_EXPANDED = 160
LIST_PANEL_MIN_WIDTH = 220
RIGHT_PANEL_DEFAULT_WIDTH = 280
RIGHT_PANEL_MIN_WIDTH = 200
RIGHT_PANEL_MAX_WIDTH = 480
FS_WATCH_DEBOUNCE_MS = 350

CLIPBOARD_COPY = "copy"
CLIPBOARD_CUT = "cut"

UNDO_COPY = "copy"
UNDO_CUT = "cut"
UNDO_PASTE_COPY = "paste_copy"
UNDO_PASTE_CUT = "paste_cut"
UNDO_DELETE = "delete"
UNDO_RENAME = "rename"
UNDO_DND_COPY = "dnd_copy"
UNDO_DND_MOVE = "dnd_move"


@dataclass
class UndoRecord:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class ImagesPage(QWidget):
    """Image browser: list, search, sort, preview, tags, folders, and view modes."""

    folder_changed = Signal(str)
    tags_changed = Signal()  # emitted when global tag master changes from this page

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

        self._active_search_query = ""
        self._preview_cache_path: str | None = None
        self._sort_mode = DEFAULT_SORT_MODE
        self._group_by = DEFAULT_GROUP_BY
        self._thumbnail_mode = DEFAULT_THUMBNAIL_MODE
        self._updating_folder_ui = False
        self._clipboard_paths: list[Path] = []
        self._clipboard_mode: str | None = None
        self._updating_selection = False
        self._folder_tree_expanded = bool(
            self._config.get("images_folder_tree_expanded", True)
        )
        self._folder_panel_expanded_width = FOLDER_PANEL_EXPANDED_WIDTH
        self._fs_refreshing = False
        self._undo: UndoRecord | None = None
        self._caption_delegate: CaptionIconDelegate | None = None

        self._init_ui()
        self._setup_shortcuts()
        self._setup_fs_watcher()
        self._load_display_settings_from_project()
        self._apply_thumbnail_mode()
        self.reload_tag_choices()
        self._apply_folder_tree_expanded(self._folder_tree_expanded, persist=False)

    def _init_ui(self) -> None:
        from app.ui.scroll_page import make_page_scroll

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        page_scroll = make_page_scroll(self)
        outer.addWidget(page_scroll)

        page_root = QWidget(page_scroll)
        page_scroll.setWidget(page_root)
        main_layout = QVBoxLayout(page_root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        page_header = QWidget(page_root)
        page_header.setObjectName("imagesPageHeader")
        header_layout = QVBoxLayout(page_header)
        header_layout.setContentsMargins(28, 20, 28, 8)
        header_layout.setSpacing(6)

        page_title = QLabel(t("images.title"), page_header)
        page_title.setObjectName("pageTitle")
        header_layout.addWidget(page_title)

        page_subtitle = QLabel(t("images.subtitle"), page_header)
        page_subtitle.setObjectName("pageSubtitle")
        page_subtitle.setWordWrap(True)
        header_layout.addWidget(page_subtitle)
        main_layout.addWidget(page_header)

        # Content: Folders | List | Preview
        content = QWidget(page_root)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(12, 4, 12, 12)
        content_layout.setSpacing(12)

        self._splitter = QSplitter(Qt.Horizontal, content)

        # Folder tree (collapsible)
        self._folder_panel = QWidget(self)
        self._folder_panel.setObjectName("folderPanel")
        self._folder_panel.setMinimumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
        self._folder_panel.setMaximumWidth(FOLDER_PANEL_MAX_WIDTH)
        folder_layout = QVBoxLayout(self._folder_panel)
        folder_layout.setContentsMargins(8, 8, 8, 8)
        folder_layout.setSpacing(4)

        self._folder_collapse_btn = QPushButton("◀", self)
        self._folder_collapse_btn.setObjectName("sectionToggleButton")
        self._folder_collapse_btn.setCursor(Qt.PointingHandCursor)
        self._folder_collapse_btn.setToolTip(t("images.collapse_folders"))
        self._folder_collapse_btn.clicked.connect(self._toggle_folder_tree)

        self._folder_header = QWidget(self._folder_panel)
        self._folder_header.setObjectName("sectionHeader")
        folder_header_layout = QVBoxLayout(self._folder_header)
        folder_header_layout.setContentsMargins(0, 2, 0, 0)
        folder_header_layout.setSpacing(4)

        folder_title_row = QHBoxLayout()
        folder_title_row.setContentsMargins(0, 0, 0, 0)
        folder_title_row.setSpacing(6)
        folder_title_row.addWidget(self._folder_collapse_btn)

        self._folder_header_labels = QWidget(self._folder_header)
        labels_layout = QHBoxLayout(self._folder_header_labels)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(6)
        folder_icon = QLabel(self._folder_header_labels)
        folder_icon.setObjectName("sectionIcon")
        folder_icon.setPixmap(icon_folder().pixmap(SECTION_ICON_SIZE, SECTION_ICON_SIZE))
        labels_layout.addWidget(folder_icon)
        folder_title = QLabel(t("images.folders"), self._folder_header_labels)
        folder_title.setObjectName("sectionTitle")
        labels_layout.addWidget(folder_title)
        labels_layout.addStretch(1)
        folder_title_row.addWidget(self._folder_header_labels, stretch=1)
        folder_header_layout.addLayout(folder_title_row)

        self._folder_project_hint = QLabel(self._folder_header)
        self._folder_project_hint.setObjectName("mutedLabel")
        self._folder_project_hint.setWordWrap(True)
        folder_header_layout.addWidget(self._folder_project_hint)

        self._save_folder_legend = QLabel(
            t("images.save_folder_star_legend"), self._folder_header
        )
        self._save_folder_legend.setObjectName("saveFolderLegend")
        self._save_folder_legend.setWordWrap(True)
        folder_header_layout.addWidget(self._save_folder_legend)

        self._folder_header_divider = QFrame(self._folder_header)
        self._folder_header_divider.setObjectName("sectionDivider")
        self._folder_header_divider.setFrameShape(QFrame.HLine)
        self._folder_header_divider.setFixedHeight(1)
        folder_header_layout.addWidget(self._folder_header_divider)
        folder_layout.addWidget(self._folder_header)

        self._folder_body = QWidget(self._folder_panel)
        folder_body_layout = QVBoxLayout(self._folder_body)
        folder_body_layout.setContentsMargins(0, 0, 0, 0)
        folder_body_layout.setSpacing(4)

        self._add_folder_btn = QPushButton(t("images.new_folder"), self)
        self._add_folder_btn.setObjectName("folderAddButton")
        self._add_folder_btn.setIcon(icon_new_folder())
        self._add_folder_btn.setCursor(Qt.PointingHandCursor)
        self._add_folder_btn.setToolTip(t("images.new_folder_tooltip"))
        self._add_folder_btn.setAutoDefault(False)
        self._add_folder_btn.setDefault(False)
        self._add_folder_btn.clicked.connect(self._create_new_folder)
        folder_body_layout.addWidget(self._add_folder_btn)

        self._folder_tree = ProjectTreeWidget(self)
        self._folder_tree.setObjectName("folderTree")
        self._folder_tree.setHeaderHidden(True)
        self._folder_tree.setRootIsDecorated(False)
        self._folder_tree.setAnimated(False)
        self._folder_tree.setIndentation(0)
        self._folder_tree.setIconSize(QSize(34, 16))
        self._folder_tree.setUniformRowHeights(True)
        self._folder_tree.setItemsExpandable(False)
        self._folder_tree.setExpandsOnDoubleClick(False)
        self._folder_tree.itemClicked.connect(self._on_folder_clicked)
        self._folder_tree.paths_dropped.connect(self._on_paths_dropped_on_folder)
        self._folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._folder_tree.customContextMenuRequested.connect(self._on_folder_context_menu)
        folder_body_layout.addWidget(self._folder_tree)
        folder_layout.addWidget(self._folder_body, stretch=1)
        self._splitter.addWidget(self._folder_panel)

        # Image list
        list_panel = QWidget(self)
        list_panel.setObjectName("leftPanel")
        list_panel.setMinimumWidth(LIST_PANEL_MIN_WIDTH)
        self._list_panel = list_panel
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        # Screenshots header: title + Sort / Group By as integrated tools
        header_tools = QWidget(self)
        header_tools.setObjectName("headerTools")
        tools_layout = QHBoxLayout(header_tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(6)

        sort_label = QLabel(t("images.sort_label"), header_tools)
        sort_label.setObjectName("toolbarFieldLabel")
        tools_layout.addWidget(sort_label)

        self._sort_combo = QComboBox(header_tools)
        self._sort_combo.setMinimumWidth(140)
        self._sort_combo.setMaximumWidth(180)
        self._sort_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in sort_option_labels():
            self._sort_combo.addItem(label, mode)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools_layout.addWidget(self._sort_combo)

        group_label = QLabel(t("images.group_by_label"), header_tools)
        group_label.setObjectName("toolbarFieldLabel")
        tools_layout.addWidget(group_label)

        self._group_combo = QComboBox(header_tools)
        self._group_combo.setMinimumWidth(88)
        self._group_combo.setMaximumWidth(120)
        self._group_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in group_by_option_labels():
            self._group_combo.addItem(label, mode)
        self._group_combo.currentIndexChanged.connect(self._on_group_by_changed)
        tools_layout.addWidget(self._group_combo)

        list_layout.addWidget(
            self._build_section_header(
                t("images.screenshots"),
                icon_images(),
                trailing=header_tools,
            )
        )

        # Search spans only the Screenshots column (same width as this panel)
        search_row = QWidget(list_panel)
        search_row.setObjectName("screenshotsSearchRow")
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 6, 0, 6)
        search_layout.setSpacing(6)

        self._refresh_btn = QPushButton(t("images.refresh"), search_row)
        self._refresh_btn.setObjectName("secondaryButton")
        self._refresh_btn.setIcon(icon_refresh())
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh)
        search_layout.addWidget(self._refresh_btn)

        self._search_input = QLineEdit(search_row)
        self._search_input.setObjectName("screenshotsSearchInput")
        self._search_input.setPlaceholderText(t("images.search_placeholder"))
        self._search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self._search_input, stretch=1)

        self._search_btn = QPushButton(t("images.search"), search_row)
        self._search_btn.setIcon(icon_search())
        self._search_btn.setCursor(Qt.PointingHandCursor)
        self._search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(self._search_btn)

        self._clear_search_btn = QPushButton(t("images.clear"), search_row)
        self._clear_search_btn.setObjectName("secondaryButton")
        self._clear_search_btn.setIcon(icon_clear())
        self._clear_search_btn.setCursor(Qt.PointingHandCursor)
        self._clear_search_btn.clicked.connect(self._on_clear_search)
        search_layout.addWidget(self._clear_search_btn)

        list_layout.addWidget(search_row)

        self._list_widget = ScreenshotListWidget(self)
        self._list_widget.setObjectName("screenshotList")
        self._list_widget.setViewMode(QListWidget.IconMode)
        self._list_widget.setResizeMode(QListWidget.Adjust)
        self._list_widget.setSpacing(10)
        self._list_widget.setWordWrap(True)
        self._list_widget.setUniformItemSizes(True)
        self._list_widget.setTextElideMode(Qt.ElideMiddle)
        self._list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list_widget.setSelectionRectVisible(True)
        # setViewMode/setMovement reset Qt DnD flags — restore drag-to-folder only
        self._list_widget.configure_drag_export_only()
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self._list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self._list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self._list_widget.viewport().installEventFilter(self)
        list_layout.addWidget(self._list_widget, stretch=1)
        self._splitter.addWidget(list_panel)

        # Preview + tags
        right_panel = QWidget(self)
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        right_layout.addWidget(
            self._build_section_header(t("images.preview"), icon_preview())
        )

        self._preview_label = QLabel(t("images.select_image"), self)
        self._preview_label.setObjectName("previewLabel")
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumSize(160, 160)
        right_layout.addWidget(self._preview_label, stretch=1)

        self._info_widget = QWidget(self)
        self._info_widget.setObjectName("infoPanel")
        self._info_layout = QVBoxLayout(self._info_widget)
        self._info_layout.setContentsMargins(12, 10, 12, 12)
        self._info_layout.setSpacing(8)

        self._file_info_label = QLabel(t("images.file_none"), self)
        self._info_layout.addWidget(self._file_info_label)

        self._info_layout.addWidget(
            self._build_section_header(t("images.tags"), icon_tags())
        )

        self._tags_layout = QHBoxLayout()
        self._tags_layout.setSpacing(6)
        self._info_layout.addLayout(self._tags_layout)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        self._tag_mode_group = QButtonGroup(self)
        self._tag_mode_existing_btn = QPushButton(t("images.tag.mode_existing"), self)
        self._tag_mode_existing_btn.setObjectName("tagModeButton")
        self._tag_mode_existing_btn.setCheckable(True)
        self._tag_mode_existing_btn.setCursor(Qt.PointingHandCursor)
        self._tag_mode_new_btn = QPushButton(t("images.tag.mode_new"), self)
        self._tag_mode_new_btn.setObjectName("tagModeButton")
        self._tag_mode_new_btn.setCheckable(True)
        self._tag_mode_new_btn.setCursor(Qt.PointingHandCursor)
        self._tag_mode_group.addButton(self._tag_mode_existing_btn, TAG_MODE_EXISTING)
        self._tag_mode_group.addButton(self._tag_mode_new_btn, TAG_MODE_NEW)
        self._tag_mode_existing_btn.setChecked(True)
        self._tag_mode_group.buttonClicked.connect(self._on_tag_mode_button)
        mode_row.addWidget(self._tag_mode_existing_btn)
        mode_row.addWidget(self._tag_mode_new_btn)
        mode_row.addStretch()
        self._info_layout.addLayout(mode_row)

        # Select existing: combo + Assign
        self._tag_existing_row = QWidget(self)
        existing_layout = QHBoxLayout(self._tag_existing_row)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.setSpacing(8)
        self._tag_combo = QComboBox(self)
        self._tag_combo.setEditable(False)
        self._tag_combo.setPlaceholderText(t("images.tag.select_placeholder"))
        existing_layout.addWidget(self._tag_combo)
        self._tag_assign_btn = QPushButton(t("images.tag.assign"), self)
        self._tag_assign_btn.setCursor(Qt.PointingHandCursor)
        self._tag_assign_btn.clicked.connect(self._on_assign_existing_tag)
        existing_layout.addWidget(self._tag_assign_btn)
        self._info_layout.addWidget(self._tag_existing_row)

        # Create new: line edit + Create & Assign
        self._tag_new_row = QWidget(self)
        new_layout = QHBoxLayout(self._tag_new_row)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.setSpacing(8)
        self._tag_new_input = QLineEdit(self)
        self._tag_new_input.setPlaceholderText(t("images.tag.new_placeholder"))
        self._tag_new_input.returnPressed.connect(self._on_create_and_assign_tag)
        new_layout.addWidget(self._tag_new_input)
        self._tag_create_btn = QPushButton(t("images.tag.create_assign"), self)
        self._tag_create_btn.setCursor(Qt.PointingHandCursor)
        self._tag_create_btn.clicked.connect(self._on_create_and_assign_tag)
        new_layout.addWidget(self._tag_create_btn)
        self._tag_new_row.hide()
        self._info_layout.addWidget(self._tag_new_row)

        self._info_widget.setEnabled(False)
        right_layout.addWidget(self._info_widget)

        self._splitter.addWidget(right_panel)
        self._right_panel = right_panel
        right_panel.setMinimumWidth(RIGHT_PANEL_MIN_WIDTH)
        right_panel.setMaximumWidth(RIGHT_PANEL_MAX_WIDTH)
        self._folder_panel.setMinimumWidth(FOLDER_PANEL_MIN_EXPANDED)
        self._folder_panel.setMaximumWidth(FOLDER_PANEL_MAX_WIDTH)

        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        self._splitter.setSizes(
            [FOLDER_PANEL_EXPANDED_WIDTH, 560, RIGHT_PANEL_DEFAULT_WIDTH]
        )
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        content_layout.addWidget(self._splitter)
        main_layout.addWidget(content, stretch=1)

        # Prefer scrolling over clipping when the window is smaller than the panels
        min_w = (
            FOLDER_PANEL_MIN_EXPANDED
            + LIST_PANEL_MIN_WIDTH
            + RIGHT_PANEL_MIN_WIDTH
            + 48
        )
        page_root.setMinimumWidth(min_w)
        page_root.setMinimumHeight(420)

        self._populate_folder_tree()

    def _build_section_header(
        self,
        title: str,
        icon,
        *,
        leading: QWidget | None = None,
        trailing: QWidget | None = None,
        with_divider: bool = True,
    ) -> QWidget:
        """Shared section header used by Folders / Screenshots / Preview / Tags."""
        wrap = QWidget(self)
        wrap.setObjectName("sectionHeader")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        if leading is not None:
            row.addWidget(leading)

        icon_label = QLabel(wrap)
        icon_label.setObjectName("sectionIcon")
        icon_label.setPixmap(icon.pixmap(SECTION_ICON_SIZE, SECTION_ICON_SIZE))
        row.addWidget(icon_label)

        title_label = QLabel(title, wrap)
        title_label.setObjectName("sectionTitle")
        row.addWidget(title_label)

        if trailing is not None:
            row.addStretch(1)
            row.addWidget(trailing)
        else:
            row.addStretch(1)

        layout.addLayout(row)

        if with_divider:
            line = QFrame(wrap)
            line.setObjectName("sectionDivider")
            line.setFrameShape(QFrame.HLine)
            line.setFixedHeight(1)
            layout.addWidget(line)
        return wrap

    def _toggle_folder_tree(self) -> None:
        self._apply_folder_tree_expanded(not self._folder_tree_expanded)

    def _apply_folder_tree_expanded(
        self, expanded: bool, *, persist: bool = True
    ) -> None:
        """Show/hide the folder body and let the image list reclaim width."""
        self._folder_tree_expanded = expanded
        self._folder_body.setVisible(expanded)
        self._folder_header_labels.setVisible(expanded)
        self._folder_header_divider.setVisible(expanded)
        if hasattr(self, "_folder_project_hint"):
            self._folder_project_hint.setVisible(expanded)
        if hasattr(self, "_save_folder_legend"):
            self._save_folder_legend.setVisible(expanded)

        sizes = self._splitter.sizes()
        while len(sizes) < 3:
            sizes.append(200)

        layout = self._folder_panel.layout()
        if expanded:
            if layout is not None:
                layout.setContentsMargins(8, 8, 8, 8)
            self._folder_panel.setObjectName("folderPanel")
            self._folder_panel.setMinimumWidth(FOLDER_PANEL_MIN_EXPANDED)
            self._folder_panel.setMaximumWidth(FOLDER_PANEL_MAX_WIDTH)
            self._folder_collapse_btn.setText("◀")
            self._folder_collapse_btn.setToolTip(t("images.collapse_folders"))
            target = max(self._folder_panel_expanded_width, FOLDER_PANEL_MIN_EXPANDED)
            freed = sizes[0]
            sizes[0] = target
            sizes[1] = max(120, sizes[1] + freed - target)
            self._splitter.setSizes(sizes)
        else:
            if sizes[0] > FOLDER_PANEL_COLLAPSED_WIDTH:
                self._folder_panel_expanded_width = sizes[0]
            if layout is not None:
                layout.setContentsMargins(4, 8, 4, 8)
            self._folder_panel.setObjectName("folderPanelCollapsed")
            self._folder_panel.setMinimumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
            self._folder_panel.setMaximumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
            self._folder_collapse_btn.setText("▶")
            self._folder_collapse_btn.setToolTip(t("images.expand_folders"))
            freed = max(0, sizes[0] - FOLDER_PANEL_COLLAPSED_WIDTH)
            sizes[0] = FOLDER_PANEL_COLLAPSED_WIDTH
            sizes[1] = sizes[1] + freed
            self._splitter.setSizes(sizes)

        # Refresh stylesheet after objectName change
        self._folder_panel.style().unpolish(self._folder_panel)
        self._folder_panel.style().polish(self._folder_panel)

        if persist:
            self._config["images_folder_tree_expanded"] = expanded
            try:
                save_config(self._config)
            except OSError:
                pass

    def _on_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """Remember folder width so Screenshots resize doesn't permanently crush it."""
        if not self._folder_tree_expanded:
            return
        sizes = self._splitter.sizes()
        if sizes and sizes[0] >= FOLDER_PANEL_MIN_EXPANDED:
            self._folder_panel_expanded_width = sizes[0]

    def _setup_shortcuts(self) -> None:
        """Explorer-like keyboard shortcuts for the Images page."""
        bindings = [
            (QKeySequence.SelectAll, self._select_all_images),
            (QKeySequence.Copy, self._copy_selected_images),
            (QKeySequence.Cut, self._cut_selected_images),
            (QKeySequence.Paste, self._paste_clipboard),
            (QKeySequence.Delete, self._delete_selected_images),
            (QKeySequence(Qt.Key_F2), self._rename_selected_image),
            (QKeySequence.Undo, self._undo_last_action),
        ]
        for sequence, slot in bindings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _setup_fs_watcher(self) -> None:
        """Watch screenshot root + current folder for Explorer-side changes."""
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_debounce = QTimer(self)
        self._fs_debounce.setSingleShot(True)
        self._fs_debounce.setInterval(FS_WATCH_DEBOUNCE_MS)
        self._fs_debounce.timeout.connect(self._on_fs_change_debounced)
        self._fs_watcher.directoryChanged.connect(self._schedule_fs_refresh)
        self._resync_fs_watcher()

    def _resync_fs_watcher(self) -> None:
        if not hasattr(self, "_fs_watcher"):
            return
        watched_dirs = list(self._fs_watcher.directories())
        if watched_dirs:
            self._fs_watcher.removePaths(watched_dirs)
        watched_files = list(self._fs_watcher.files())
        if watched_files:
            self._fs_watcher.removePaths(watched_files)

        paths: list[str] = []
        root = self._get_screenshot_root()
        if root.exists():
            paths.append(str(root))
        folder_dir = self._get_folder_dir()
        if folder_dir.exists() and str(folder_dir) not in paths:
            paths.append(str(folder_dir))
        if paths:
            self._fs_watcher.addPaths(paths)

    def _schedule_fs_refresh(self, _path: str = "") -> None:
        if self._fs_refreshing or self._updating_folder_ui:
            return
        self._fs_debounce.start()

    def _on_fs_change_debounced(self) -> None:
        if self._fs_refreshing:
            return
        self._fs_refreshing = True
        try:
            self._sync_from_filesystem()
        finally:
            self._fs_refreshing = False

    def _sync_from_filesystem(self) -> None:
        """Rebuild Folder Tree + image list after external Explorer changes."""
        folder_names = self._list_folder_names()
        current_folder = resolve_current_folder(self._config)
        if folder_names and current_folder not in folder_names:
            fallback_folder = pick_folder_name(folder_names, DEFAULT_FOLDER)
            self._config["current_folder"] = fallback_folder
            try:
                save_config(self._config)
            except OSError:
                pass
            self._preview_cache_path = None
            self._clear_preview()
            self._load_display_settings_from_project()
            self.folder_changed.emit(fallback_folder)

        self._metadata_service.invalidate_cache()
        self._populate_folder_tree()
        self._apply_thumbnail_mode()
        self.reload_tag_choices()
        self._load_images(force_reload_metadata=True)
        self._resync_fs_watcher()
        self._apply_cut_visuals()

    # ---- public API ----

    def refresh(self) -> None:
        """Reload folders, images, and display settings."""
        self._metadata_service.invalidate_cache(self._get_folder_dir())
        self._load_display_settings_from_project()
        self._populate_folder_tree()
        self._apply_thumbnail_mode()
        self.reload_tag_choices()
        self._load_images(force_reload_metadata=True)
        self._resync_fs_watcher()
        self._apply_cut_visuals()

    def on_folder_changed(self) -> None:
        """Called when the active folder changes externally."""
        self._preview_cache_path = None
        self._clear_preview()
        self.refresh()

    def reload_tag_choices(self) -> None:
        """Reload global tags into the existing-tag combo (exclude already assigned)."""
        if not hasattr(self, "_tag_combo"):
            return

        assigned: set[str] = set()
        selected = self._get_selected_path()
        if selected:
            path = Path(selected)
            assigned = set(
                self._metadata_service.get_image_tags(path.parent, path.name)
            )

        self._tag_combo.blockSignals(True)
        self._tag_combo.clear()
        for tag in self._metadata_service.load_global_tags(
            self._app_root, force_reload=True
        ):
            if tag not in assigned:
                self._tag_combo.addItem(format_tag(tag), tag)
        self._tag_combo.setCurrentIndex(0 if self._tag_combo.count() else -1)
        self._tag_combo.blockSignals(False)
        self._tag_assign_btn.setEnabled(self._tag_combo.count() > 0)

    def _on_tag_mode_button(self, _button: QPushButton) -> None:
        mode_id = self._tag_mode_group.checkedId()
        self._apply_tag_mode(mode_id)

    def _apply_tag_mode(self, mode_id: int) -> None:
        existing = mode_id == TAG_MODE_EXISTING
        self._tag_existing_row.setVisible(existing)
        self._tag_new_row.setVisible(not existing)
        if existing:
            self.reload_tag_choices()
        else:
            self._tag_new_input.clear()
            self._tag_new_input.setFocus()

    def _on_tag_mode_changed(self, mode_id: int) -> None:
        """Compatibility wrapper for tests / callers that pass a mode id."""
        self._apply_tag_mode(mode_id)

    def add_saved_image(self, saved_path: Path) -> None:
        self._add_image_to_list(saved_path)

    def select_image_path(self, path_str: str) -> None:
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.data(Qt.UserRole) == path_str:
                self._list_widget.setCurrentItem(item)
                self._on_item_clicked(item)
                return

    # ---- paths / folders ----

    def _get_screenshot_root(self) -> Path:
        path_obj = Path(self._config.get("screenshot_dir", "screenshots"))
        if not path_obj.is_absolute():
            path_obj = (self._app_root / path_obj).resolve()
        return path_obj.resolve()

    def _get_folder_dir(self) -> Path:
        """Directory that holds images + .sstool for the current folder."""
        folder = resolve_current_folder(self._config)
        return self._metadata_service.resolve_folder_dir(
            self._config.get("screenshot_dir", "screenshots"),
            folder,
            self._app_root,
        )

    def _list_folder_names(self) -> list[str]:
        return workspace_list_folders(self._get_screenshot_root(), ensure_default=True)

    def refresh_save_folder_marker(self) -> None:
        """Refresh ★ markers when Screenshot Save folder changes."""
        self._populate_folder_tree()

    def _populate_folder_tree(self) -> None:
        """Show folders under the screenshot root."""
        current = resolve_current_folder(self._config)
        save_folder = resolve_save_folder(self._config)
        if hasattr(self, "_folder_project_hint"):
            root_name = self._get_screenshot_root().name
            self._folder_project_hint.setText(
                t("images.viewing_folder_hint", root=root_name)
            )
        self._updating_folder_ui = True
        self._folder_tree.blockSignals(True)
        self._folder_tree.clear()

        selected_item = None
        folder_names = self._list_folder_names()

        if folder_names and current not in folder_names:
            current = pick_folder_name(folder_names, DEFAULT_FOLDER)
            self._config["current_folder"] = current

        for name in folder_names:
            selected = name == current
            is_save = name == save_folder
            # ★ matches folder-name font size (same text run)
            display = f"★ {name}" if is_save else name
            item = QTreeWidgetItem([display])
            item.setIcon(0, project_tree_icon(selected=selected))
            item.setData(0, Qt.UserRole, name)
            tip = name
            if is_save:
                tip = t("images.save_folder_marker_tooltip", name=name)
            item.setToolTip(0, tip)
            if selected:
                font = QFont(item.font(0))
                font.setBold(True)
                item.setFont(0, font)
                item.setForeground(0, QBrush(QColor("#047857")))
                item.setBackground(0, QBrush(QColor("#d1fae5")))
                selected_item = item
            elif is_save:
                item.setForeground(0, QBrush(QColor("#1d4ed8")))
            self._folder_tree.addTopLevelItem(item)

        if selected_item is not None:
            self._folder_tree.setCurrentItem(selected_item)

        self._folder_tree.blockSignals(False)
        self._updating_folder_ui = False

    def _on_folder_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating_folder_ui:
            return
        name = item.data(0, Qt.UserRole)
        if not name or name == self._config.get("current_folder"):
            return
        self._switch_folder(str(name))

    def _create_new_folder(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            t("images.folder.new_title"),
            t("images.folder.name_prompt"),
        )
        if not ok:
            return

        name = name.strip()
        if not name:
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.name_required")
            )
            return

        if any(ch in name for ch in '\\/:*?"<>|'):
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.name_invalid")
            )
            return

        try:
            folder_dir = self._get_screenshot_root() / name
            if folder_dir.exists():
                QMessageBox.warning(
                    self, t("common.warning"), t("images.folder.exists")
                )
                return

            folder_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(folder_dir)
            self._metadata_service.save_metadata(folder_dir, {"images": {}})
            self._switch_folder(name)
        except OSError as e:
            QMessageBox.critical(
                self,
                t("common.error"),
                t("images.folder.create_failed", error=e),
            )

    def _on_folder_context_menu(self, pos) -> None:
        item = self._folder_tree.itemAt(pos)
        menu = QMenu(self)

        new_act = menu.addAction(t("images.folder.new_folder"))
        new_act.triggered.connect(self._create_new_folder)
        menu.addSeparator()

        rename_act = menu.addAction(t("images.folder.rename"))
        duplicate_act = menu.addAction(t("images.folder.duplicate"))
        delete_act = menu.addAction(t("images.folder.delete"))

        target_name = item.data(0, Qt.UserRole) if item is not None else None
        for act in (rename_act, duplicate_act, delete_act):
            act.setEnabled(bool(target_name))

        if target_name:
            rename_act.triggered.connect(
                lambda checked=False, n=str(target_name): self._rename_folder(n)
            )
            duplicate_act.triggered.connect(
                lambda checked=False, n=str(target_name): self._duplicate_folder(n)
            )
            delete_act.triggered.connect(
                lambda checked=False, n=str(target_name): self._delete_folder(n)
            )

        menu.exec(self._folder_tree.viewport().mapToGlobal(pos))

    def _rename_folder(self, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(
            self,
            t("images.folder.rename_title"),
            t("images.folder.rename_prompt"),
            text=old_name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if not is_valid_folder_name(new_name):
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.name_invalid")
            )
            return

        root = self._get_screenshot_root()
        src = root / old_name
        try:
            if not src.exists():
                QMessageBox.warning(
                    self, t("common.warning"), t("images.folder.missing")
                )
                return
            rename_folder(src, new_name)
            self._metadata_service.invalidate_cache()
            if self._config.get("save_folder") == old_name:
                self._config["save_folder"] = new_name
                try:
                    save_config(self._config)
                except OSError:
                    pass
            if self._config.get("current_folder") == old_name:
                self._switch_folder(new_name)
            else:
                self._populate_folder_tree()
                self.folder_changed.emit(str(self._config.get("current_folder") or ""))
        except FileExistsError:
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.exists")
            )
        except (OSError, ValueError) as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.folder.rename_failed", error=e)
            )

    def _duplicate_folder(self, name: str) -> None:
        root = self._get_screenshot_root()
        src = root / name
        try:
            if not src.exists():
                QMessageBox.warning(
                    self, t("common.warning"), t("images.folder.missing")
                )
                return
            dest = duplicate_folder(src, root)
            self._metadata_service.invalidate_cache()
            self._populate_folder_tree()
            self.folder_changed.emit(str(self._config.get("current_folder") or ""))
            QMessageBox.information(
                self,
                t("images.folders"),
                t("images.folder.duplicated", name=dest.name),
            )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.folder.duplicate_failed", error=e)
            )

    def _delete_folder(self, name: str) -> None:
        names = self._list_folder_names()
        if len(names) <= 1:
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.delete_last")
            )
            return

        reply = QMessageBox.question(
            self,
            t("common.confirm_delete"),
            t("images.folder.delete_confirm", name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        root = self._get_screenshot_root()
        path = root / name
        try:
            if not path.exists():
                QMessageBox.warning(
                    self, t("common.warning"), t("images.folder.missing")
                )
                return
            delete_folder(path)
            self._metadata_service.invalidate_cache()
            remaining = self._list_folder_names()
            if self._config.get("save_folder") == name:
                self._config["save_folder"] = pick_folder_name(remaining)
                try:
                    save_config(self._config)
                except OSError:
                    pass
            if self._config.get("current_folder") == name:
                fallback = pick_folder_name(remaining)
                self._switch_folder(fallback)
            else:
                self._populate_folder_tree()
                self.folder_changed.emit(str(self._config.get("current_folder") or ""))
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.folder.delete_failed", error=e)
            )

    def _switch_folder(self, folder_name: str) -> None:
        try:
            self._config["current_folder"] = folder_name or DEFAULT_FOLDER
            save_config(self._config)

            folder_dir = self._get_folder_dir()
            folder_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(folder_dir)

            self._preview_cache_path = None
            self._clear_preview()
            self._load_display_settings_from_project()
            self._populate_folder_tree()
            self._apply_thumbnail_mode()
            self._load_images(force_reload_metadata=True)
            self._resync_fs_watcher()
            self._apply_cut_visuals()

            self.folder_changed.emit(folder_name)
        except OSError as e:
            QMessageBox.critical(
                self,
                t("common.error"),
                t("images.folder.switch_failed", error=e),
            )

    def switch_folder(self, folder_name: str) -> None:
        """Public entry point used by the shell Folder selector."""
        name = (folder_name or "").strip() or DEFAULT_FOLDER
        if name == self._config.get("current_folder"):
            return
        self._switch_folder(name)

    def _on_paths_dropped_on_folder(
        self, folder_name: str, paths: list, copy_mode: bool
    ) -> None:
        """Handle Explorer-like drop onto a folder in the Folder Tree."""
        paths = [Path(p) for p in paths if Path(p).exists()]
        if not paths:
            return

        dest_dir = self._get_screenshot_root() / folder_name
        current = resolve_current_folder(self._config)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(dest_dir)

            if copy_mode:
                created: list[str] = []
                for path in paths:
                    dest = self._metadata_service.copy_image_to_project(path, dest_dir)
                    created.append(str(dest.resolve()))
                self._push_undo(
                    UndoRecord(
                        kind=UNDO_DND_COPY,
                        payload={"created": created},
                    )
                )
            else:
                moves: list[dict[str, str]] = []
                for path in paths:
                    if path.parent.resolve() == dest_dir.resolve():
                        continue
                    original = str(path.resolve())
                    dest = self._metadata_service.move_image_to_project(path, dest_dir)
                    moves.append(
                        {
                            "from": original,
                            "to": str(dest.resolve()),
                            "source_project": str(path.parent.resolve()),
                        }
                    )
                    self._thumbnail_cache.invalidate(path)
                if not moves:
                    return
                self._push_undo(
                    UndoRecord(kind=UNDO_DND_MOVE, payload={"moves": moves})
                )

            if folder_name == current:
                self._metadata_service.invalidate_cache(dest_dir)
                self._load_images(force_reload_metadata=True)
            else:
                if not copy_mode:
                    self._load_images(force_reload_metadata=True)
            self._populate_folder_tree()
            self._resync_fs_watcher()
        except OSError as e:
            key = (
                "images.dnd.copy_failed" if copy_mode else "images.dnd.move_failed"
            )
            QMessageBox.critical(self, t("common.error"), t(key, error=e))

    # ---- display settings ----

    def _load_display_settings_from_project(self) -> None:
        project_dir = self._get_folder_dir()
        if project_dir.exists():
            project = self._metadata_service.load_project(project_dir)
            display = project.get("display", {})
            self._sort_mode = normalize_sort_mode(display.get("sort_mode"))
            self._group_by = normalize_group_by(display.get("group_by"))
            self._thumbnail_mode = normalize_thumbnail_mode(display.get("thumbnail_mode"))
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
            return
        self._load_images()

    def _on_group_by_changed(self) -> None:
        group_by = normalize_group_by(self._group_combo.currentData())
        self._group_by = group_by
        try:
            self._save_display_setting("group_by", group_by)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.group_by_save_failed", error=e)
            )
            return
        self._apply_thumbnail_mode()
        self._load_images()

    def _set_thumbnail_mode(self, mode: str) -> None:
        mode = normalize_thumbnail_mode(mode)
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
        self._load_images()

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is self._list_widget.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._refresh_header_widths()
        return super().eventFilter(obj, event)

    def _apply_thumbnail_mode(self) -> None:
        mode = self._thumbnail_mode
        grouped = self._group_by != GROUP_BY_NONE

        if self._caption_delegate is None:
            self._caption_delegate = CaptionIconDelegate(parent=self._list_widget)
            self._list_widget.setItemDelegate(self._caption_delegate)

        # All sizes use IconMode cards (Small = compact cards, not a stretched list row)
        icon_size, grid_w, grid_h = THUMBNAIL_MODE_SIZES[mode]
        self._caption_delegate.set_list_mode(False)
        self._caption_delegate.set_geometry(icon_size, grid_w, grid_h)
        self._list_widget.setProperty("captionMode", "icon")
        self._list_widget.setViewMode(QListWidget.IconMode)
        self._list_widget.setFlow(QListWidget.LeftToRight)
        self._list_widget.setWrapping(True)
        self._list_widget.setResizeMode(QListWidget.Adjust)
        self._list_widget.setIconSize(QSize(icon_size, icon_size))
        # Fixed grid forces every item into one cell — headers then sit beside images.
        # Clear grid when grouped so sizeHint can make headers span a full row.
        if grouped:
            self._list_widget.setGridSize(QSize())
        else:
            self._list_widget.setGridSize(QSize(grid_w, grid_h))
        self._list_widget.setSpacing(8)
        self._list_widget.setWordWrap(True)
        self._list_widget.setUniformItemSizes(not grouped)
        self._list_widget.setTextElideMode(Qt.ElideNone)
        self._list_widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # IconMode + movement changes clear DragOnly — restore Explorer drag-out
        self._list_widget.configure_drag_export_only()

        style = self._list_widget.style()
        style.unpolish(self._list_widget)
        style.polish(self._list_widget)
        self._refresh_header_widths()
        self._list_widget.update()

    def _header_row_width(self) -> int:
        viewport_w = self._list_widget.viewport().width()
        min_w = 200
        if self._caption_delegate is not None:
            min_w = max(min_w, self._caption_delegate.cell_width * 2)
        return max(viewport_w - 8, min_w)

    def _refresh_header_widths(self) -> None:
        if self._group_by == GROUP_BY_NONE:
            return
        width = self._header_row_width()
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None:
                continue
            if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                item.setSizeHint(QSize(width, GROUP_HEADER_HEIGHT))

    def _current_icon_size(self) -> int:
        return THUMBNAIL_MODE_SIZES[self._thumbnail_mode][0]

    # ---- list helpers ----

    def _get_selected_path(self) -> str | None:
        current_item = self._list_widget.currentItem()
        if current_item is None:
            return None
        if current_item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return None
        return current_item.data(Qt.UserRole)

    def _get_png_files(self, target_dir: Path) -> list[Path]:
        # Sorting is applied in build_groups (whole list or within each group).
        return list(target_dir.glob("*.png"))

    def _filter_png_files(
        self,
        png_files: list[Path],
        metadata: dict,
        search_query: str,
    ) -> list[Path]:
        filtered_files = []
        for file_path in png_files:
            tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])
            if image_matches_search(file_path.name, tags, search_query):
                filtered_files.append(file_path)
        return filtered_files

    def _caption_date_text(self, file_path: Path) -> str:
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
        return mtime.strftime("%Y-%m-%d %H:%M")

    def _format_details_text(self, file_path: Path, tags: list[str]) -> str:
        date_text = self._caption_date_text(file_path)
        tags_text = format_tags(tags, empty="-")
        return f"{file_path.name}    {date_text}    {tags_text}"

    def _set_caption_roles(
        self,
        item: QListWidgetItem,
        file_path: Path,
        tags: list[str],
        *,
        soft_wrap: bool = True,
    ) -> None:
        name = soft_wrap_filename(file_path.name) if soft_wrap else file_path.name
        item.setData(ROLE_CAPTION_NAME, name)
        item.setData(
            ROLE_CAPTION_TAGS,
            format_tags(tags, empty=t("images.tag.none")),
        )
        item.setData(ROLE_CAPTION_TAGS_MUTED, not bool(tags))
        item.setData(ROLE_CAPTION_DATE, self._caption_date_text(file_path))

    def _group_header_label(self, group_key: str) -> str:
        if group_key == NO_TAG_GROUP_KEY:
            return t("group_by.no_tag")
        if self._group_by == GROUP_BY_TAG:
            return format_tag(group_key)
        return group_key

    def _create_header_item(
        self, title: str, *, variant: str = ""
    ) -> QListWidgetItem:
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, None)
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_HEADER)
        item.setData(HEADER_VARIANT_ROLE, variant)
        item.setFlags(Qt.ItemIsEnabled)  # visible, not selectable
        font = QFont(item.font())
        if variant == HEADER_VARIANT_NO_TAG:
            font.setItalic(True)
            font.setBold(False)
            item.setForeground(QBrush(QColor("#6b7280")))
            item.setBackground(QBrush(QColor("#f9fafb")))
        else:
            font.setBold(True)
            font.setPointSize(max(font.pointSize(), 10))
            item.setForeground(QBrush(QColor("#374151")))
            item.setBackground(QBrush(QColor("#f3f4f6")))
        item.setFont(font)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        item.setSizeHint(QSize(self._header_row_width(), GROUP_HEADER_HEIGHT))
        return item

    def _create_list_item(self, file_path: Path, metadata: dict | None = None) -> QListWidgetItem:
        if metadata is None:
            metadata = self._metadata_service.load_metadata(file_path.parent)

        tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])
        icon_size = self._current_icon_size()

        item = QListWidgetItem("")
        item.setIcon(self._thumbnail_cache.get_icon(file_path, size=icon_size))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        _, grid_w, grid_h = THUMBNAIL_MODE_SIZES[self._thumbnail_mode]
        item.setSizeHint(QSize(grid_w - 4, grid_h - 4))
        # Drag to folders only — never accept drops (no in-list reorder)
        item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        )
        self._set_caption_roles(item, file_path, tags, soft_wrap=True)

        item.setData(Qt.UserRole, str(file_path.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        item.setToolTip(
            f"{file_path.name}\n"
            f"{format_tags(tags, empty=t('images.tag.none'))}\n"
            f"{self._caption_date_text(file_path)}"
        )
        if self._is_cut_path(file_path):
            self._style_item_as_cut(item, file_path)
        return item

    def _is_cut_path(self, file_path: Path) -> bool:
        if self._clipboard_mode != CLIPBOARD_CUT:
            return False
        resolved = str(file_path.resolve())
        return any(str(p.resolve()) == resolved for p in self._clipboard_paths)

    def _style_item_as_cut(self, item: QListWidgetItem, file_path: Path) -> None:
        """Explorer-like translucent cut state."""
        icon_size = self._current_icon_size()
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
        """Refresh cut translucency on all visible list items."""
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None or item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                continue
            path_str = item.data(Qt.UserRole)
            if not path_str:
                continue
            path = Path(path_str)
            if self._is_cut_path(path):
                self._style_item_as_cut(item, path)
            else:
                icon_size = self._current_icon_size()
                item.setIcon(self._thumbnail_cache.get_icon(path, size=icon_size))
                item.setForeground(QBrush(QColor("#1f2937")))

    def _populate_list(self, filtered_files: list[Path], selected_path_str: str | None) -> bool:
        self._updating_selection = True
        self._list_widget.clear()
        target_dir = self._get_folder_dir()
        metadata = (
            self._metadata_service.load_metadata(target_dir)
            if target_dir.exists()
            else {"images": {}}
        )

        groups = build_groups(
            filtered_files,
            self._group_by,
            metadata,
            self._sort_mode,
        )

        selected_item = None
        for group_key, group_files in groups:
            if self._group_by != GROUP_BY_NONE:
                variant = (
                    HEADER_VARIANT_NO_TAG
                    if group_key == NO_TAG_GROUP_KEY
                    else ""
                )
                self._list_widget.addItem(
                    self._create_header_item(
                        self._group_header_label(group_key),
                        variant=variant,
                    )
                )
            for file_path in group_files:
                item = self._create_list_item(file_path, metadata)
                self._list_widget.addItem(item)
                if selected_path_str and item.data(Qt.UserRole) == selected_path_str:
                    if selected_item is None:
                        selected_item = item

        if selected_item is not None:
            self._list_widget.setCurrentItem(selected_item)
            self._updating_selection = False
            self._show_image(selected_item)
            return True

        self._updating_selection = False
        return False

    def _clear_preview(self) -> None:
        self._preview_cache_path = None
        self._preview_label.setPixmap(QPixmap())
        self._preview_label.setText(t("images.select_image"))
        self._file_info_label.setText(t("images.file_none"))
        self._info_widget.setEnabled(False)
        self._clear_tags_layout()
        self.reload_tag_choices()

    def _clear_tags_layout(self) -> None:
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _display_tags(self, file_path: Path) -> None:
        self._clear_tags_layout()
        tags = self._metadata_service.get_image_tags(file_path.parent, file_path.name)

        if tags:
            for tag in tags:
                tag_btn = QPushButton(f"{format_tag(tag)}  ×", self)
                tag_btn.setObjectName("tagChip")
                tag_btn.setCursor(Qt.PointingHandCursor)
                tag_btn.setToolTip(t("images.tag.remove_tooltip"))
                tag_btn.clicked.connect(
                    lambda checked=False, tag_name=tag: self._delete_tag(
                        file_path, tag_name
                    )
                )
                self._tags_layout.addWidget(tag_btn)
        else:
            empty_label = QLabel(t("images.tag.none"), self)
            empty_label.setObjectName("mutedLabel")
            self._tags_layout.addWidget(empty_label)

        self._tags_layout.addStretch()
        self.reload_tag_choices()

    def _on_current_item_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if self._updating_selection:
            return
        if current is None:
            self._clear_preview()
            return
        if current.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return
        self._show_image(current)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._show_image(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return
        path_str = item.data(Qt.UserRole)
        if path_str:
            self._open_image_path(Path(path_str))

    def _show_image(self, item: QListWidgetItem) -> None:
        """Show preview + enable tag UI for the selected list item."""
        if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return

        file_path_str = item.data(Qt.UserRole)
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        self._info_widget.setEnabled(True)
        self._file_info_label.setText(t("images.file_name", name=file_path.name))
        self._display_tags(file_path)

        if self._preview_cache_path == file_path_str:
            existing = self._preview_label.pixmap()
            if existing is not None and not existing.isNull():
                return

        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            self._preview_label.setPixmap(QPixmap())
            self._preview_label.setText(t("images.load_failed"))
            self._preview_cache_path = file_path_str
            return

        scaled_pixmap = pixmap.scaled(
            max(self._preview_label.width() - PREVIEW_PADDING * 2, 100),
            max(self._preview_label.height() - PREVIEW_PADDING * 2, 100),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled_pixmap)
        self._preview_cache_path = file_path_str

    def _selected_image_path(self) -> Path | None:
        current_item = self._list_widget.currentItem()
        if not current_item:
            return None
        file_path_str = current_item.data(Qt.UserRole)
        if not file_path_str:
            return None
        return Path(file_path_str)

    def _selected_tag_from_combo(self) -> str:
        index = self._tag_combo.currentIndex()
        if index < 0:
            return ""
        data = self._tag_combo.itemData(index)
        if data:
            return normalize_tag(str(data))
        return normalize_tag(self._tag_combo.itemText(index))

    def _on_assign_existing_tag(self) -> None:
        file_path = self._selected_image_path()
        if file_path is None:
            return

        tag_name = self._selected_tag_from_combo()
        if not tag_name:
            return

        try:
            added = self._metadata_service.add_image_tag(
                file_path.parent, file_path.name, tag_name
            )
            if added:
                self._display_tags(file_path)
                self._update_list_for_tag_change(file_path)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=e)
            )

    def _on_create_and_assign_tag(self) -> None:
        file_path = self._selected_image_path()
        if file_path is None:
            return

        new_tag = normalize_tag(self._tag_new_input.text())
        if not new_tag:
            return

        try:
            created_new = new_tag not in self._metadata_service.load_global_tags(
                self._app_root
            )
            tag_name = self._metadata_service.ensure_global_tag(self._app_root, new_tag)
            if not tag_name:
                return

            added = self._metadata_service.add_image_tag(
                file_path.parent, file_path.name, tag_name
            )
            self._tag_new_input.clear()
            if added:
                self._display_tags(file_path)
                self._update_list_for_tag_change(file_path)
            if created_new:
                self.tags_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=e)
            )

    def _delete_tag(self, file_path: Path, tag_to_remove: str) -> None:
        try:
            if self._metadata_service.remove_image_tag(
                file_path.parent, file_path.name, tag_to_remove
            ):
                self._display_tags(file_path)
                self._update_list_for_tag_change(file_path)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.remove_failed", error=e)
            )

    def _selected_image_items(self) -> list[QListWidgetItem]:
        """Selected list items that are real images (not group headers)."""
        result: list[QListWidgetItem] = []
        for item in self._list_widget.selectedItems():
            if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                continue
            if item.data(Qt.UserRole):
                result.append(item)
        return result

    def _selected_image_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for item in self._selected_image_items():
            path_str = item.data(Qt.UserRole)
            if not path_str or path_str in seen:
                continue
            seen.add(path_str)
            path = Path(path_str)
            if path.exists():
                paths.append(path)
        return paths

    def _on_selection_changed(self) -> None:
        items = self._selected_image_items()
        if len(items) == 1:
            self._show_image(items[0])
        elif len(items) > 1:
            current = self._list_widget.currentItem()
            if (
                current is not None
                and current.data(ITEM_KIND_ROLE) != ITEM_KIND_HEADER
                and current.data(Qt.UserRole)
            ):
                self._show_image(current)
            self._file_info_label.setText(
                t("images.file_selected_count", count=len(items))
            )

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)

        view_menu = menu.addMenu(t("common.view"))
        view_group = QActionGroup(self)
        view_group.setExclusive(True)

        for mode, label in thumbnail_mode_labels():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self._thumbnail_mode)
            action.setData(mode)
            action.triggered.connect(
                lambda checked=False, m=mode: self._set_thumbnail_mode(m)
            )
            view_group.addAction(action)
            view_menu.addAction(action)

        menu.addSeparator()

        # Ensure the item under the cursor is part of the selection (Explorer-like)
        item_at = self._list_widget.itemAt(pos)
        if (
            item_at is not None
            and item_at.data(ITEM_KIND_ROLE) != ITEM_KIND_HEADER
            and not item_at.isSelected()
        ):
            self._list_widget.clearSelection()
            item_at.setSelected(True)
            self._list_widget.setCurrentItem(item_at)

        selected = self._selected_image_paths()
        count = len(selected)
        has_clipboard = self._has_clipboard()

        if count >= 1:
            open_action = QAction(t("images.open"), self)
            open_action.triggered.connect(self._open_selected_images)
            menu.addAction(open_action)

            copy_label = (
                t("common.copy") if count == 1 else t("images.copy_count", count=count)
            )
            copy_action = QAction(copy_label, self)
            copy_action.triggered.connect(self._copy_selected_images)
            menu.addAction(copy_action)

            cut_label = (
                t("common.cut") if count == 1 else t("images.cut_count", count=count)
            )
            cut_action = QAction(cut_label, self)
            cut_action.triggered.connect(self._cut_selected_images)
            menu.addAction(cut_action)

        paste_action = QAction(t("common.paste"), self)
        paste_action.setEnabled(has_clipboard)
        paste_action.triggered.connect(self._paste_clipboard)
        menu.addAction(paste_action)

        if count == 1:
            rename_action = QAction(t("images.rename_title"), self)
            rename_action.triggered.connect(self._rename_selected_image)
            menu.addAction(rename_action)

        if count >= 1:
            delete_label = (
                t("common.delete")
                if count == 1
                else t("images.delete_count", count=count)
            )
            delete_action = QAction(delete_label, self)
            delete_action.triggered.connect(self._delete_selected_images)
            menu.addAction(delete_action)

            menu.addSeparator()
            explorer_action = QAction(t("images.open_explorer"), self)
            explorer_action.triggered.connect(self._open_selected_in_explorer)
            menu.addAction(explorer_action)

        menu.exec(self._list_widget.mapToGlobal(pos))

    def _has_clipboard(self) -> bool:
        return bool(self._clipboard_mode) and any(
            p.exists() for p in self._clipboard_paths
        )

    def _set_clipboard(self, paths: list[Path], mode: str) -> None:
        valid = [p for p in paths if p.exists()]
        previous = {
            "mode": self._clipboard_mode,
            "paths": [str(p) for p in self._clipboard_paths],
        }
        self._clipboard_paths = list(valid)
        self._clipboard_mode = mode if valid else None
        self._apply_cut_visuals()
        if valid:
            self._push_undo(
                UndoRecord(
                    kind=UNDO_COPY if mode == CLIPBOARD_COPY else UNDO_CUT,
                    payload={"previous": previous},
                )
            )

    def _clear_clipboard(self) -> None:
        self._clipboard_paths = []
        self._clipboard_mode = None
        self._apply_cut_visuals()

    def _select_all_images(self) -> None:
        self._list_widget.clearSelection()
        first = None
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None or item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                continue
            item.setSelected(True)
            if first is None:
                first = item
        if first is not None:
            self._list_widget.setCurrentItem(first)

    def _copy_selected_images(self) -> None:
        paths = self._selected_image_paths()
        if not paths:
            return
        self._set_clipboard(paths, CLIPBOARD_COPY)

    def _cut_selected_images(self) -> None:
        paths = self._selected_image_paths()
        if not paths:
            return
        self._set_clipboard(paths, CLIPBOARD_CUT)

    def _paste_clipboard(self) -> None:
        """Paste clipboard into the current folder (Copy = duplicate, Cut = move)."""
        if not self._clipboard_mode:
            return

        project_dir = self._get_folder_dir()
        valid = [p for p in self._clipboard_paths if p.exists()]
        if not valid:
            self._clear_clipboard()
            return

        mode = self._clipboard_mode
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(project_dir)

            inserted: list[Path] = []
            moves: list[dict[str, str]] = []
            if mode == CLIPBOARD_CUT:
                for path in valid:
                    original = str(path.resolve())
                    dest = self._metadata_service.move_image_to_project(
                        path, project_dir
                    )
                    inserted.append(dest)
                    moves.append(
                        {
                            "from": original,
                            "to": str(dest.resolve()),
                            "source_project": str(path.parent.resolve()),
                        }
                    )
                    self._thumbnail_cache.invalidate(path)
                self._clear_clipboard()
                self._push_undo(
                    UndoRecord(kind=UNDO_PASTE_CUT, payload={"moves": moves})
                )
            else:
                for path in valid:
                    dest = self._metadata_service.copy_image_to_project(
                        path, project_dir
                    )
                    inserted.append(dest)
                self._push_undo(
                    UndoRecord(
                        kind=UNDO_PASTE_COPY,
                        payload={
                            "created": [str(p.resolve()) for p in inserted],
                            "project": str(project_dir.resolve()),
                        },
                    )
                )

            self._metadata_service.invalidate_cache(project_dir)
            self._load_images(force_reload_metadata=True)
            self._populate_folder_tree()
            self._resync_fs_watcher()
            if inserted:
                self._select_path_in_list(inserted[-1])
        except OSError as e:
            key = (
                "images.cut.failed" if mode == CLIPBOARD_CUT else "images.paste.failed"
            )
            QMessageBox.critical(self, t("common.error"), t(key, error=e))

    def _rename_selected_image(self) -> None:
        paths = self._selected_image_paths()
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
        # Strip accidental extension typed by user
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
            old_name = path.name
            project_dir = path.parent
            dest = self._metadata_service.rename_image(project_dir, old_name, new_name)
            self._thumbnail_cache.invalidate(path)
            self._push_undo(
                UndoRecord(
                    kind=UNDO_RENAME,
                    payload={
                        "project": str(project_dir.resolve()),
                        "old_name": old_name,
                        "new_name": dest.name,
                    },
                )
            )
            self._load_images(force_reload_metadata=True)
            self._select_path_in_list(dest)
        except FileExistsError:
            QMessageBox.warning(
                self, t("common.warning"), t("images.rename_exists")
            )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.rename_failed", error=e)
            )

    def _delete_selected_images(self) -> None:
        paths = self._selected_image_paths()
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
            backup_dir = Path(tempfile.mkdtemp(prefix="sstool_undo_"))
            backups: list[dict[str, Any]] = []
            deleted_keys = {str(p.resolve()) for p in paths}

            for file_path in paths:
                if not file_path.exists():
                    continue
                tags = self._metadata_service.get_image_tags(
                    file_path.parent, file_path.name
                )
                backup_path = backup_dir / file_path.name
                # Unique backup name if collision within batch
                if backup_path.exists():
                    backup_path = backup_dir / f"{file_path.stem}_{file_path.stat().st_mtime_ns}.png"
                shutil.copy2(file_path, backup_path)
                backups.append(
                    {
                        "backup": str(backup_path),
                        "original": str(file_path.resolve()),
                        "project": str(file_path.parent.resolve()),
                        "name": file_path.name,
                        "tags": list(tags),
                    }
                )
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
                else:
                    self._clear_clipboard()

            if backups:
                self._push_undo(
                    UndoRecord(
                        kind=UNDO_DELETE,
                        payload={
                            "backup_dir": str(backup_dir),
                            "items": backups,
                        },
                    )
                )
            else:
                shutil.rmtree(backup_dir, ignore_errors=True)

            self._load_images(force_reload_metadata=True)
            self._clear_preview()
        except Exception as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.delete_failed", error=e)
            )

    def _push_undo(self, record: UndoRecord) -> None:
        self._discard_undo_temp()
        self._undo = record

    def _discard_undo_temp(self) -> None:
        if self._undo is None:
            return
        if self._undo.kind == UNDO_DELETE:
            backup_dir = self._undo.payload.get("backup_dir")
            if backup_dir:
                shutil.rmtree(backup_dir, ignore_errors=True)
        self._undo = None

    def _undo_last_action(self) -> None:
        if self._undo is None:
            return

        record = self._undo
        self._undo = None
        try:
            if record.kind in (UNDO_COPY, UNDO_CUT):
                previous = record.payload.get("previous") or {}
                mode = previous.get("mode")
                paths = [Path(p) for p in previous.get("paths", [])]
                self._clipboard_paths = [p for p in paths if p.exists()]
                self._clipboard_mode = mode if self._clipboard_paths else None
                self._apply_cut_visuals()
            elif record.kind in (UNDO_PASTE_COPY, UNDO_DND_COPY):
                for path_str in record.payload.get("created", []):
                    path = Path(path_str)
                    if path.exists():
                        self._metadata_service.delete_image_file(
                            path.parent, path.name
                        )
                        self._thumbnail_cache.invalidate(path)
                self._load_images(force_reload_metadata=True)
                self._clear_preview()
            elif record.kind in (UNDO_PASTE_CUT, UNDO_DND_MOVE):
                for move in record.payload.get("moves", []):
                    dest = Path(move["to"])
                    source_project = Path(move["source_project"])
                    if dest.exists():
                        restored = self._metadata_service.move_image_to_project(
                            dest, source_project
                        )
                        # Prefer original filename when free
                        original_name = Path(move["from"]).name
                        target = source_project / original_name
                        if restored.name != original_name and not target.exists():
                            restored = self._metadata_service.rename_image(
                                source_project, restored.name, original_name
                            )
                        self._thumbnail_cache.invalidate(dest)
                self._load_images(force_reload_metadata=True)
            elif record.kind == UNDO_DELETE:
                last_restored: Path | None = None
                for item in record.payload.get("items", []):
                    backup = Path(item["backup"])
                    project = Path(item["project"])
                    name = item["name"]
                    if not backup.exists():
                        continue
                    project.mkdir(parents=True, exist_ok=True)
                    dest = project / name
                    if dest.exists():
                        existing = {p.name for p in project.glob("*.png")}
                        dest = project / make_unique_copy_filename(name, existing)
                    shutil.copy2(backup, dest)
                    meta = self._metadata_service.load_metadata(project)
                    meta.setdefault("images", {})[dest.name] = {
                        "tags": list(item.get("tags", [])),
                    }
                    self._metadata_service.save_metadata(project, meta)
                    last_restored = dest
                backup_dir = record.payload.get("backup_dir")
                if backup_dir:
                    shutil.rmtree(backup_dir, ignore_errors=True)
                self._load_images(force_reload_metadata=True)
                if last_restored is not None:
                    self._select_path_in_list(last_restored)
            elif record.kind == UNDO_RENAME:
                project = Path(record.payload["project"])
                old_name = record.payload["old_name"]
                new_name = record.payload["new_name"]
                restored = self._metadata_service.rename_image(
                    project, new_name, old_name
                )
                self._thumbnail_cache.invalidate(project / new_name)
                self._load_images(force_reload_metadata=True)
                self._select_path_in_list(restored)
        except Exception as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.undo_failed", error=e)
            )

    def _select_path_in_list(self, file_path: Path) -> None:
        """Select a list item by file path, if present."""
        row = self._find_list_row(file_path)
        if row < 0:
            return
        item = self._list_widget.item(row)
        self._list_widget.clearSelection()
        item.setSelected(True)
        self._list_widget.setCurrentItem(item)
        self._show_image(item)

    def _open_selected_images(self) -> None:
        for path in self._selected_image_paths():
            self._open_image_path(path)

    def _open_image_path(self, file_path: Path) -> None:
        if file_path.exists():
            os.startfile(str(file_path))

    def _open_selected_in_explorer(self) -> None:
        paths = self._selected_image_paths()
        if not paths:
            return
        self._open_in_explorer_path(paths[0])

    def _open_in_explorer(self, item: QListWidgetItem) -> None:
        file_path_str = item.data(Qt.UserRole)
        if file_path_str:
            self._open_in_explorer_path(Path(file_path_str))

    def _open_in_explorer_path(self, file_path: Path) -> None:
        if file_path.exists():
            os.startfile(str(file_path.parent))

    def _delete_image(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        self._list_widget.clearSelection()
        item.setSelected(True)
        self._delete_selected_images()

    def _add_tag_to_paths(self, paths: list[Path], tag: str) -> None:
        try:
            for path in paths:
                self._metadata_service.add_image_tag(path.parent, path.name, tag)
            if len(paths) == 1:
                self._display_tags(paths[0])
                self._update_list_for_tag_change(paths[0])
            else:
                self._load_images()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=e)
            )

    def _remove_tag_from_paths(self, paths: list[Path], tag: str) -> None:
        try:
            for path in paths:
                self._metadata_service.remove_image_tag(path.parent, path.name, tag)
            if len(paths) == 1:
                self._display_tags(paths[0])
                self._update_list_for_tag_change(paths[0])
            else:
                self._load_images()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.remove_failed", error=e)
            )

    def _find_list_row(self, file_path: Path) -> int:
        path_str = str(file_path.resolve())
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                continue
            if item.data(Qt.UserRole) == path_str:
                return i
        return -1

    def _insert_list_item_sorted(self, file_path: Path) -> None:
        if self._group_by != GROUP_BY_NONE:
            self._load_images()
            return

        item = self._create_list_item(file_path)
        for i in range(self._list_widget.count()):
            other = self._list_widget.item(i)
            if other.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                continue
            other_path = Path(other.data(Qt.UserRole))
            if should_insert_before(file_path, other_path, self._sort_mode):
                self._list_widget.insertItem(i, item)
                return
        self._list_widget.addItem(item)

    def _update_list_for_tag_change(self, file_path: Path) -> None:
        # Tag / date groups depend on metadata; rebuild the list.
        if self._group_by != GROUP_BY_NONE:
            self._load_images()
            return

        # Refresh item caption / details text after tag changes
        row = self._find_list_row(file_path)
        if row != -1:
            metadata = self._metadata_service.load_metadata(file_path.parent)
            tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])
            item = self._list_widget.item(row)
            item.setText("")
            self._set_caption_roles(item, file_path, tags, soft_wrap=True)
            item.setToolTip(
                f"{file_path.name}\n"
                f"{format_tags(tags, empty=t('images.tag.none'))}\n"
                f"{self._caption_date_text(file_path)}"
            )

        if not self._active_search_query.strip():
            return

        tags = self._metadata_service.get_image_tags(file_path.parent, file_path.name)
        matches = image_matches_search(file_path.name, tags, self._active_search_query)
        row = self._find_list_row(file_path)

        if matches and row == -1:
            self._insert_list_item_sorted(file_path)
        elif not matches and row != -1:
            was_selected = self._get_selected_path() == str(file_path.resolve())
            self._list_widget.takeItem(row)
            if was_selected:
                self._clear_preview()

    def _load_images(self, force_reload_metadata: bool = False) -> None:
        selected_path_str = self._get_selected_path()
        target_dir = self._get_folder_dir()

        if not target_dir.exists():
            self._list_widget.clear()
            self._clear_preview()
            return

        metadata = self._metadata_service.load_metadata(
            target_dir,
            force_reload=force_reload_metadata,
        )
        png_files = self._get_png_files(target_dir)
        filtered_files = self._filter_png_files(
            png_files,
            metadata,
            self._active_search_query,
        )
        restored = self._populate_list(filtered_files, selected_path_str)
        if not restored:
            self._clear_preview()

    def _add_image_to_list(self, saved_path: Path) -> None:
        # Only add if it belongs to the current Project/Folder
        if saved_path.parent.resolve() != self._get_folder_dir().resolve():
            return

        metadata = self._metadata_service.load_metadata(saved_path.parent)
        tags = metadata.get("images", {}).get(saved_path.name, {}).get("tags", [])
        if not image_matches_search(saved_path.name, tags, self._active_search_query):
            return
        if self._find_list_row(saved_path) != -1:
            return
        self._insert_list_item_sorted(saved_path)

    def _on_search(self) -> None:
        self._active_search_query = self._search_input.text()
        self._load_images()

    def _on_clear_search(self) -> None:
        self._search_input.clear()
        self._active_search_query = ""
        self._load_images()
