"""Organize page: select images and run bulk operations (Tags, Rename, …)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QMessageBox,
    QAbstractItemView,
    QFrame,
    QFormLayout,
    QSplitter,
    QStackedWidget,
    QButtonGroup,
    QSizePolicy,
)

from app.config import save_config
from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.caption_delegate import (
    ITEM_KIND_IMAGE,
    ITEM_KIND_ROLE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    ROLE_CAPTION_TAGS_MUTED,
    CaptionIconDelegate,
)
from app.ui.icons import icon_add, icon_clear, icon_images, icon_search
from app.ui.widgets import ScreenshotListWidget
from app.utils.bulk_rename import build_sequential_names
from app.utils.save_folder import list_folder_names
from app.utils.search_filter import image_matches_search
from app.utils.sort_order import (
    DEFAULT_SORT_MODE,
    normalize_sort_mode,
    sort_option_labels,
    sort_png_files,
)
from app.utils.tag_format import format_tag, format_tags, normalize_tag
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import THUMBNAIL_MODE_SIZES, soft_wrap_filename
from app.utils.workspace import resolve_current_folder

# Operations registry keys (extend here for Move / Copy / Export / …)
OP_TAGS = "tags"
OP_RENAME = "rename"

# Selection-focused grid (Images-like medium cards)
_THUMB_MODE = "medium"
_ICON_SIZE, _GRID_W, _GRID_H = THUMBNAIL_MODE_SIZES[_THUMB_MODE]


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
        self._active_search_query = ""
        self._operations: dict[str, int] = {}
        self._op_buttons: dict[str, QPushButton] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel(t("work.title"), self)
        title.setObjectName("pageTitle")
        root.addWidget(title)

        subtitle = QLabel(t("work.subtitle"), self)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setObjectName("organizeSplitter")
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_image_list_panel())
        splitter.addWidget(self._build_operations_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([640, 360])

        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._select_operation(OP_TAGS)

    # ------------------------------------------------------------------ UI
    def _build_image_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("organizeListPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        list_title = QLabel(t("work.image_list"), panel)
        list_title.setObjectName("sectionTitle")
        header.addWidget(list_title)
        header.addStretch(1)

        folder_label = QLabel(t("work.folder_label"), panel)
        folder_label.setObjectName("toolbarFieldLabel")
        header.addWidget(folder_label)
        self._folder_combo = QComboBox(panel)
        self._folder_combo.setObjectName("organizeFolderCombo")
        self._folder_combo.setMinimumWidth(120)
        self._folder_combo.setMaximumWidth(200)
        self._folder_combo.setCursor(Qt.PointingHandCursor)
        self._folder_combo.currentIndexChanged.connect(self._on_folder_combo_changed)
        header.addWidget(self._folder_combo)
        layout.addLayout(header)

        # Selection status (purpose: pick targets, not browse)
        sel_box = QFrame(panel)
        sel_box.setObjectName("organizeSelectionBanner")
        sel_layout = QVBoxLayout(sel_box)
        sel_layout.setContentsMargins(12, 10, 12, 10)
        sel_layout.setSpacing(2)
        sel_heading = QLabel(t("work.selected_heading"), sel_box)
        sel_heading.setObjectName("organizeSelectedHeading")
        sel_layout.addWidget(sel_heading)
        self._selected_count_label = QLabel(t("work.selected_count", count=0), sel_box)
        self._selected_count_label.setObjectName("organizeSelectedCount")
        sel_layout.addWidget(self._selected_count_label)
        layout.addWidget(sel_box)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        sort_label = QLabel(t("images.sort_label"), panel)
        sort_label.setObjectName("toolbarFieldLabel")
        tools.addWidget(sort_label)
        self._sort_combo = QComboBox(panel)
        self._sort_combo.setMinimumWidth(140)
        self._sort_combo.setMaximumWidth(180)
        self._sort_combo.setCursor(Qt.PointingHandCursor)
        for mode, label in sort_option_labels():
            self._sort_combo.addItem(label, mode)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools.addWidget(self._sort_combo)
        tools.addStretch(1)
        select_all_btn = QPushButton(t("common.select_all"), panel)
        select_all_btn.setObjectName("secondaryButton")
        select_all_btn.setCursor(Qt.PointingHandCursor)
        select_all_btn.clicked.connect(self._select_all)
        tools.addWidget(select_all_btn)
        clear_btn = QPushButton(t("work.clear_selection"), panel)
        clear_btn.setObjectName("secondaryButton")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_selection)
        tools.addWidget(clear_btn)
        layout.addLayout(tools)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._search_input = QLineEdit(panel)
        self._search_input.setObjectName("screenshotsSearchInput")
        self._search_input.setPlaceholderText(t("images.search_placeholder"))
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, stretch=1)
        search_btn = QPushButton(t("images.search"), panel)
        search_btn.setIcon(icon_search())
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        clear_search_btn = QPushButton(t("images.clear"), panel)
        clear_search_btn.setObjectName("secondaryButton")
        clear_search_btn.setIcon(icon_clear())
        clear_search_btn.setCursor(Qt.PointingHandCursor)
        clear_search_btn.clicked.connect(self._on_clear_search)
        search_row.addWidget(clear_search_btn)
        layout.addLayout(search_row)

        self._list = ScreenshotListWidget(panel)
        self._list.setObjectName("organizeImageList")
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setWordWrap(True)
        self._list.setTextElideMode(Qt.ElideNone)
        self._list.setUniformItemSizes(True)
        self._list.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self._list.setGridSize(QSize(_GRID_W, _GRID_H))
        self._list.setSpacing(10)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setDragEnabled(False)
        self._list.setDragDropMode(QAbstractItemView.NoDragDrop)
        self._list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._caption_delegate = CaptionIconDelegate(
            icon_size=_ICON_SIZE,
            cell_width=_GRID_W,
            cell_height=_GRID_H,
            parent=self._list,
        )
        self._list.setItemDelegate(self._caption_delegate)
        layout.addWidget(self._list, stretch=1)
        return panel

    def _build_operations_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("organizeOpsPanel")
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(440)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        ops_title = QLabel(t("work.operations"), panel)
        ops_title.setObjectName("sectionTitle")
        layout.addWidget(ops_title)

        ops_hint = QLabel(t("work.operations_hint"), panel)
        ops_hint.setObjectName("mutedLabel")
        ops_hint.setWordWrap(True)
        layout.addWidget(ops_hint)

        # Operation picker — add future ops via _register_operation
        picker = QFrame(panel)
        picker.setObjectName("organizeOpPicker")
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(8, 8, 8, 8)
        picker_layout.setSpacing(6)
        self._op_btn_layout = picker_layout
        self._op_btn_group = QButtonGroup(self)
        self._op_btn_group.setExclusive(True)
        layout.addWidget(picker)

        self._op_stack = QStackedWidget(panel)
        self._op_stack.setObjectName("organizeOpStack")
        layout.addWidget(self._op_stack, stretch=1)

        self._register_operation(OP_TAGS, t("work.op_tags"), self._build_tags_settings())
        self._register_operation(
            OP_RENAME, t("work.op_rename"), self._build_rename_settings()
        )
        # Future: Move, Copy, Export, Compress, OCR, AI Analyze via _register_operation

        layout.addStretch(0)
        return panel

    def _register_operation(
        self, op_id: str, label: str, settings: QWidget
    ) -> QPushButton:
        """Register an operation button + settings page (extensible hub)."""
        btn = QPushButton(label, self)
        btn.setObjectName("operationButton")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, oid=op_id: self._select_operation(oid))
        self._op_btn_group.addButton(btn)
        self._op_btn_layout.addWidget(btn)
        index = self._op_stack.addWidget(settings)
        self._operations[op_id] = index
        self._op_buttons[op_id] = btn
        return btn

    def _select_operation(self, op_id: str) -> None:
        if op_id not in self._operations:
            return
        self._op_stack.setCurrentIndex(self._operations[op_id])
        for oid, btn in self._op_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(oid == op_id)
            btn.blockSignals(False)
        if op_id == OP_RENAME:
            self._update_rename_preview()

    def _build_tags_settings(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("organizeOpSettings")
        tags_layout = QVBoxLayout(panel)
        tags_layout.setContentsMargins(12, 12, 12, 12)
        tags_layout.setSpacing(8)

        tags_title = QLabel(t("work.bulk_tags"), panel)
        tags_title.setObjectName("sectionTitle")
        tags_layout.addWidget(tags_title)

        tags_hint = QLabel(t("work.bulk_tags_hint"), panel)
        tags_hint.setObjectName("mutedLabel")
        tags_hint.setWordWrap(True)
        tags_layout.addWidget(tags_hint)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel(t("work.tag_add"), panel))
        self._tag_add_combo = QComboBox(panel)
        self._tag_add_combo.setMinimumWidth(120)
        add_row.addWidget(self._tag_add_combo, stretch=1)
        add_btn = QPushButton(t("work.apply_add"), panel)
        add_btn.setIcon(icon_add())
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_bulk_add_tag)
        add_row.addWidget(add_btn)
        tags_layout.addLayout(add_row)

        remove_row = QHBoxLayout()
        remove_row.addWidget(QLabel(t("work.tag_remove"), panel))
        self._tag_remove_combo = QComboBox(panel)
        self._tag_remove_combo.setMinimumWidth(120)
        remove_row.addWidget(self._tag_remove_combo, stretch=1)
        remove_btn = QPushButton(t("work.apply_remove"), panel)
        remove_btn.setObjectName("secondaryButton")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._on_bulk_remove_tag)
        remove_row.addWidget(remove_btn)
        tags_layout.addLayout(remove_row)
        tags_layout.addStretch(1)
        return panel

    def _build_rename_settings(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("organizeOpSettings")
        rename_layout = QVBoxLayout(panel)
        rename_layout.setContentsMargins(12, 12, 12, 12)
        rename_layout.setSpacing(8)

        rename_title = QLabel(t("work.bulk_rename"), panel)
        rename_title.setObjectName("sectionTitle")
        rename_layout.addWidget(rename_title)

        rename_hint = QLabel(t("work.bulk_rename_hint"), panel)
        rename_hint.setObjectName("mutedLabel")
        rename_hint.setWordWrap(True)
        rename_layout.addWidget(rename_hint)

        form = QFormLayout()
        form.setSpacing(8)
        self._prefix_input = QLineEdit(panel)
        self._prefix_input.setPlaceholderText(t("work.rename_prefix_placeholder"))
        self._prefix_input.setText("ScreenShot_test_")
        self._prefix_input.textChanged.connect(self._update_rename_preview)
        form.addRow(t("work.rename_prefix"), self._prefix_input)

        self._digits_spin = QSpinBox(panel)
        self._digits_spin.setMinimum(3)
        self._digits_spin.setMaximum(8)
        self._digits_spin.setValue(3)
        self._digits_spin.valueChanged.connect(self._update_rename_preview)
        form.addRow(t("work.rename_digits"), self._digits_spin)
        rename_layout.addLayout(form)

        self._rename_preview = QLabel(t("work.rename_preview_empty"), panel)
        self._rename_preview.setObjectName("mutedLabel")
        self._rename_preview.setWordWrap(True)
        rename_layout.addWidget(self._rename_preview)

        rename_btn = QPushButton(t("work.apply_rename"), panel)
        rename_btn.setIcon(icon_images())
        rename_btn.setCursor(Qt.PointingHandCursor)
        rename_btn.clicked.connect(self._on_bulk_rename)
        rename_layout.addWidget(rename_btn, alignment=Qt.AlignLeft)
        rename_layout.addStretch(1)
        return panel

    # ----------------------------------------------------------- data / refresh
    def _get_folder_dir(self) -> Path:
        return self._metadata_service.resolve_folder_dir(
            self._config.get("screenshot_dir", "screenshots"),
            resolve_current_folder(self._config),
            self._app_root,
        )

    def refresh(self) -> None:
        self._reload_folder_combo()
        self._load_sort_from_project()
        self._reload_images()
        self._reload_tag_combos()
        self._update_selection_label()
        self._update_rename_preview()

    def _reload_folder_combo(self) -> None:
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
        self._load_sort_from_project()
        self._reload_images()
        self._reload_tag_combos()
        self._update_rename_preview()
        self.folder_changed.emit(name)

    def _load_sort_from_project(self) -> None:
        project_dir = self._get_folder_dir()
        if project_dir.exists():
            project = self._metadata_service.load_project(project_dir)
            self._sort_mode = normalize_sort_mode(
                project.get("display", {}).get("sort_mode")
            )
        else:
            self._sort_mode = DEFAULT_SORT_MODE
        self._sort_combo.blockSignals(True)
        index = self._sort_combo.findData(self._sort_mode)
        self._sort_combo.setCurrentIndex(index if index >= 0 else 0)
        self._sort_combo.blockSignals(False)

    def _save_sort_mode(self, sort_mode: str) -> None:
        project_dir = self._get_folder_dir()
        project_dir.mkdir(parents=True, exist_ok=True)
        project = self._metadata_service.load_project(project_dir)
        if "display" not in project:
            project["display"] = {}
        project["display"]["sort_mode"] = sort_mode
        self._metadata_service.save_project(project_dir, project)

    def _on_sort_changed(self) -> None:
        sort_mode = normalize_sort_mode(self._sort_combo.currentData())
        self._sort_mode = sort_mode
        try:
            self._save_sort_mode(sort_mode)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.sort_save_failed", error=e)
            )
        self._reload_images()

    def _on_search(self) -> None:
        self._active_search_query = self._search_input.text().strip()
        self._reload_images()

    def _on_clear_search(self) -> None:
        self._search_input.clear()
        self._active_search_query = ""
        self._reload_images()

    def _reload_images(self) -> None:
        selected = {
            item.data(Qt.UserRole)
            for item in self._list.selectedItems()
            if item.data(Qt.UserRole)
        }
        self._list.clear()
        folder_dir = self._get_folder_dir()
        if not folder_dir.exists():
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

        for path in sort_png_files(png_files, self._sort_mode):
            item = self._create_list_item(path, metadata)
            self._list.addItem(item)
            if str(path.resolve()) in selected:
                item.setSelected(True)

        self._update_selection_label()

    def _create_list_item(
        self, file_path: Path, metadata: dict | None = None
    ) -> QListWidgetItem:
        if metadata is None:
            metadata = self._metadata_service.load_metadata(file_path.parent)
        tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])

        item = QListWidgetItem("")
        item.setIcon(self._thumbnail_cache.get_icon(file_path, size=_ICON_SIZE))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        item.setSizeHint(QSize(_GRID_W - 4, _GRID_H - 4))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setData(Qt.UserRole, str(file_path.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        item.setData(ROLE_CAPTION_NAME, soft_wrap_filename(file_path.name))
        item.setData(
            ROLE_CAPTION_TAGS,
            format_tags(tags, empty=t("images.tag.none")),
        )
        item.setData(ROLE_CAPTION_TAGS_MUTED, not bool(tags))
        item.setData(ROLE_CAPTION_DATE, self._caption_date_text(file_path))
        item.setToolTip(
            f"{file_path.name}\n"
            f"{format_tags(tags, empty=t('images.tag.none'))}"
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
        for tag in global_tags:
            self._tag_add_combo.addItem(format_tag(tag), tag)
        self._tag_add_combo.blockSignals(False)

        folder_dir = self._get_folder_dir()
        used: set[str] = set()
        if folder_dir.exists():
            meta = self._metadata_service.load_metadata(folder_dir, force_reload=True)
            for entry in meta.get("images", {}).values():
                used.update(entry.get("tags", []))
        self._tag_remove_combo.blockSignals(True)
        self._tag_remove_combo.clear()
        for tag in sorted(used, key=str.casefold):
            self._tag_remove_combo.addItem(format_tag(tag), tag)
        self._tag_remove_combo.blockSignals(False)

    def _combo_tag(self, combo: QComboBox) -> str:
        data = combo.currentData()
        if data:
            return normalize_tag(str(data))
        return normalize_tag(combo.currentText())

    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        for item in self._list.selectedItems():
            data = item.data(Qt.UserRole)
            if data:
                paths.append(Path(data))
        return paths

    def _select_all(self) -> None:
        self._list.selectAll()

    def _clear_selection(self) -> None:
        self._list.clearSelection()

    def _on_selection_changed(self) -> None:
        self._update_selection_label()
        self._update_rename_preview()

    def _update_selection_label(self) -> None:
        count = len(self._list.selectedItems())
        self._selected_count_label.setText(t("work.selected_count", count=count))

    # ----------------------------------------------------------- operations
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
