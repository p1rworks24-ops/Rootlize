from pathlib import Path
import inspect
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    Qt, QSize, QEvent, QObject, Signal, QTimer, QFileSystemWatcher, QPoint, QThreadPool,
    QRect, QItemSelection, QItemSelectionModel,
)
from PySide6.QtGui import (
    QMouseEvent,
    QPixmap,
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
    QKeySequence,
    QShortcut,
    QImageReader,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
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
    QAbstractSpinBox,
    QFrame,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QFileDialog,
    QScrollArea,
    QDialog,
    QStyleOptionViewItem,
)

from app.config import (
    accept_ask_ai_consent,
    has_ask_ai_external_processing_consent,
    needs_ask_ai_consent_notice,
    save_config,
)
from app.prototype_tour.events import emit_tour_event, tour_event_generation
from app.prototype_tour.models import (
    ANCHOR_IMAGES_ASK_AI,
    ANCHOR_SEARCH_RESULTS_GRID,
    EVENT_ASK_AI_CONSENT_ACCEPTED,
    EVENT_ASK_AI_CONSENT_CANCELLED,
    EVENT_ASK_AI_CONSENT_SHOWN,
    UI_ACT_COMPLETED,
    UI_ACT_PREVIEW_SHOWN,
    UI_ASK_AI_OPENED,
    UI_AUTOMATION_SAVED,
    UI_FAVORITE_CHANGED,
    UI_FIND_FAILED,
    UI_FIND_FINISHED,
    UI_FOLDER_SELECTED,
    UI_SELECTION_CHANGED,
    UI_TAG_ADDED,
)
from app.ai_actions import ActionType
from app.i18n import t
from app.ui.checkbox import CapixeCheckBox
from app.services.metadata_service import MetadataService
from app.actions import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
    ActionContext,
    ActionRequest,
    ActionService,
    ActionTarget,
)
from app.automation import (
    AutomationService,
    WorkflowValidationError,
    default_workflow_name,
    sanitize_step_parameters,
    workflow_from_session,
)
from app.workspace import (
    KIND_ACT,
    KIND_ACT_PLAN,
    KIND_CLARIFY,
    KIND_FIND,
    KIND_HELP,
    KIND_NARROW,
    KIND_QUESTION,
    KIND_UNSUPPORTED,
    ORIGIN_BROWSE,
    ORIGIN_MEANING,
    ORIGIN_TEXT,
    SOURCE_RESULT_SET,
    AskAiTurn,
    WorkspaceSession,
    bind_action_proposal,
    build_act_plan,
    execute_act_plan,
    prepare_act_plan,
    proposal_to_request,
    route_ask_ai_turn,
)
from app.workspace.plan import (
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    action_result_is_user_failure,
    build_combined_preview,
    combined_result_is_user_failure,
    summarize_action_result,
    summarize_combined_result,
)
from app.workspace.planner import default_name_generator
from app.ai_budget import AiBudgetExceeded, format_ai_user_message
from app.ai_proxy.errors import (
    AiProxyError,
    classify_ask_ai_failure,
    log_ask_ai_turn,
)
from app.relevance import RelevanceProviderError
from app.ui.caption_delegate import (
    CARD_INSET,
    GROUP_HEADER_HEIGHT,
    HEADER_VARIANT_NO_TAG,
    HEADER_VARIANT_ROLE,
    ITEM_KIND_FOLDER,
    ITEM_KIND_HEADER,
    ITEM_KIND_IMAGE,
    ITEM_KIND_ROLE,
    ROLE_CAPTION_DATE,
    ROLE_CAPTION_NAME,
    ROLE_CAPTION_TAGS,
    ROLE_CAPTION_TAGS_MUTED,
    ROLE_CAPTION_FAVORITE,
    CaptionIconDelegate,
    media_rect_for_card,
)
from app.ui.icons import (
    icon_about,
    icon_ai,
    icon_ai_sparkle,
    icon_back,
    icon_clear,
    icon_favorite,
    icon_pin,
    icon_folder,
    icon_folder_fill,
    icon_images,
    icon_layout_grid,
    icon_layout_list,
    icon_new_folder,
    icon_preview,
    icon_search,
    icon_send_up,
    icon_tags,
    project_tree_icon,
)
from app.ui.image_list_menu import (
    ensure_list_item_under_cursor_selected,
    populate_empty_gallery_context_menu,
    populate_image_list_context_menu,
)
from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRDatabaseError, OCRRecordNotFoundError
from app.ocr.repository import OCRRepository
from app.ui.ask_ai_chat import AskAiChatView
from app.ui.ask_ai_consent_dialog import AskAiConsentDialog
from app.ui.ask_ai_preview import (
    ask_ai_ui_preview_enabled,
    preview_reply_for,
    preview_result_paths,
)
from app.ui.ask_ai_result_restore import (
    is_existing_image_file,
    paths_in_folder,
    primary_result_folder,
    resolve_stored_result_paths,
    result_path_key,
)
from app.ui.ask_ai_status import ask_ai_chat_status, ask_ai_grid_status, ask_ai_phase_copy
from app.ui.ask_ai_turn_task import AskAiTurnTask
from app.ui.page_motion import (
    fade_outgoing_snapshot,
    opaque_grab,
    show_only_stack_page,
    stop_page_fade,
)
from app.ui.images_search import (
    ActionExecutorProvider,
    ActionPlanProvider,
    ActionPlanTask,
    HybridImagesSearchProvider,
    ImagesSearchTask,
    SearchProvider,
    SemanticImagesSearchProvider,
    create_meaning_search_provider,
    execute_image_tag_action,
    plan_image_action,
    search_indexed_images,
)
from app.semantic.catalog import DEFAULT_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING
from app.ui.images_analysis import ImagesAnalysisBar
from app.ui.images_content_search_setup import ImageContentSearchSetup
from app.ui.design_tokens import (
    CONTROL_COMPACT,
    CONTROL_STANDARD,
    IMAGES_COMMAND_GAP,
    IMAGES_LEFT_CARD_PAD_X,
    IMAGES_LEFT_CARD_PAD_Y,
    IMAGES_PREVIEW_IMAGE_MAX_HEIGHT,
    IMAGES_PREVIEW_IMAGE_MIN_HEIGHT,
    IMAGES_RIGHT_PANEL_DEFAULT_WIDTH,
    IMAGES_RIGHT_PANEL_MAX_WIDTH,
    IMAGES_RIGHT_PANEL_MIN_WIDTH,
    IMAGES_AI_PANEL_DEFAULT_WIDTH,
    IMAGES_AI_PANEL_MIN_WIDTH,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    MOTION_SLOW_MS,
    WORKSPACE_GAP,
    WORKSPACE_PADDING,
    WORKSPACE_PANEL_PADDING,
    paint_canvas,
)
from app.ui.flow_layout import FlowLayout
from app.ui.folder_breadcrumb import ChildFolderRow, FolderChipItem, FolderBreadcrumb
from app.ui.search_busy import SearchBusyCard, SearchBusySpinner, format_searching_status
from app.ui.segmented_toggle import SegmentedToggle
from app.ui.widgets import (
    ListPanelMarqueeBridge,
    ProjectTreeWidget,
    ScreenshotListWidget,
)
from app.utils.file_clipboard import (
    clear_system_file_clipboard,
    paths_from_system_clipboard,
    set_files_on_clipboard,
    system_clipboard_is_cut,
)
from app.utils.group_by import (
    DISPLAY_SCHEMA_KEY,
    DISPLAY_SCHEMA_VERSION,
    GROUP_BY_NONE,
    GROUP_BY_ANALYSIS,
    GROUP_BY_TAG,
    ANALYZED_GROUP_KEY,
    NO_TAG_GROUP_KEY,
    UNANALYZED_GROUP_KEY,
    SEMANTIC_MISSING_GROUP_KEY,
    SEMANTIC_STALE_GROUP_KEY,
    SEMANTIC_FAILED_GROUP_KEY,
    SEMANTIC_CORRUPT_GROUP_KEY,
    OCR_MISSING_GROUP_KEY,
    PROCESSING_GROUP_KEY,
    build_groups,
    group_by_option_labels,
    migrate_legacy_display,
    normalize_group_by,
)
from app.utils.folder_shortcuts import (
    is_favorite_folder,
    list_child_folders,
    list_favorite_folders,
    list_recent_folders,
    remember_recent_folder,
    toggle_favorite_folder,
)
from app.utils.search_filter import image_matches_search
from app.utils.image_favorite import (
    FILTER_FAVORITES_ONLY,
    apply_favorite_filter,
    image_is_favorite,
    normalize_filter_mode,
    visible_tags,
)
from app.utils.file_copy_name import make_unique_copy_filename
from app.utils.folder_ops import (
    delete_folder,
    duplicate_folder,
    is_valid_folder_name,
    rename_folder,
)
from app.utils.selected_folder import (
    get_selected_folder,
    selected_folder_state,
    set_selected_folder,
)
from app.utils.sort_order import (
    DEFAULT_IMAGES_SORT,
    IMAGES_SORT_KEY,
    VALID_IMAGES_SORT_MODES,
    arrangement_from_display,
    expand_images_sort,
    images_sort_option_labels,
    normalize_images_sort,
    should_insert_before,
)
from app.utils.tag_format import format_tag, format_tags, normalize_tag
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.logger import setup_logger
from app.utils.view_mode import (
    DEFAULT_GALLERY_LAYOUT,
    THUMBNAIL_LIST_SPACING,
    THUMBNAIL_MODE_SIZES,
    compute_responsive_grid,
    is_list_mode,
    normalize_gallery_layout,
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

THUMBNAIL_ICON_SIZE = 220
SECTION_ICON_SIZE = 14
FOLDER_PANEL_EXPANDED_WIDTH = 220
FOLDER_PANEL_COLLAPSED_WIDTH = 36
FOLDER_PANEL_MAX_WIDTH = 360
FOLDER_PANEL_MIN_EXPANDED = 160
LIST_PANEL_MIN_WIDTH = 220
FS_WATCH_DEBOUNCE_MS = 350
FS_SIGNATURE_POLL_MS = 1500
logger = setup_logger()

SEARCH_DEBOUNCE_MS = 400
VISION_SEARCH_DEBOUNCE_MS = 1200
USER_FACING_MEANING_MODE = "vision_relevance"
USER_FACING_TEXT_MODE = "text"
LEGACY_MEANING_MODES = frozenset({"hybrid", "semantic"})
TAG_CAPTION_ROW_HEIGHT = 16
# Wide enough to keep Sort / Group / View inline with the Screenshots title
HEADER_TOOLS_INLINE_MIN_WIDTH = 520

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


class ElidedPathLabel(QLabel):
    """Single-line path label that keeps the full value in its tooltip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""

    def setPath(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text if text != "-" else "")
        self._update_elided_text()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        width = max(self.contentsRect().width(), 0)
        if width <= 0:
            self.setText(self._full_text)
            return
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, width))


class _TagPickerPopup(QFrame):
    """Compact popup that closes on Escape and stays owned by the page."""

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)


class _TagsPopupEventFilter(QObject):
    """App-level filter so Tags can close on an outside click without leaking."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(event, QMouseEvent) or event.button() != Qt.LeftButton:
            return False
        page = self.parent()
        if page is None:
            return False
        try:
            page._close_tags_popup_if_outside(event.globalPosition().toPoint())
        except RuntimeError:
            return False
        return False


class _FolderMouseNavFilter(QObject):
    """Explorer-style Back/Forward from mouse side buttons while Images is visible."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if not isinstance(event, QMouseEvent):
            return False
        button = event.button()
        if button not in (Qt.BackButton, Qt.ForwardButton):
            return False
        page = self.parent()
        if page is None or not page.isVisible():
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        try:
            if not page._event_targets_folder_nav(obj):
                return False
            if button == Qt.BackButton:
                page._navigate_folder_back()
            else:
                page._navigate_folder_forward()
        except RuntimeError:
            return False
        return True


class TagPickerButton(QPushButton):
    """Upward-opening tag picker with a fixed New Tag action."""

    tag_selected = Signal(str)
    new_tag_requested = Signal()
    tag_delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tagPickerButton")
        self.setProperty("tagPreviewControl", True)
        self.setCursor(Qt.PointingHandCursor)
        self._placeholder = "Select tag..."
        self._entries: list[tuple[str, str]] = []
        self._current_index = -1

        self._popup = _TagPickerPopup(self.window(), Qt.Popup)
        self._popup.setObjectName("tagPickerPopup")
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(6, 6, 6, 6)
        popup_layout.setSpacing(4)
        self._popup_list = QListWidget(self._popup)
        self._popup_list.setObjectName("tagPickerList")
        self._popup_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        popup_layout.addWidget(self._popup_list)
        divider = QFrame(self._popup)
        divider.setObjectName("sectionDivider")
        divider.setFrameShape(QFrame.HLine)
        popup_layout.addWidget(divider)
        self._new_tag_button = QPushButton(t("images.tag.new_action"), self._popup)
        self._new_tag_button.setObjectName("tagPickerNewAction")
        self._new_tag_button.setCursor(Qt.PointingHandCursor)
        self._new_tag_button.clicked.connect(self._request_new_tag)
        popup_layout.addWidget(self._new_tag_button)
        self.clicked.connect(self.showPopup)
        self._update_text()

    def setPlaceholderText(self, text: str) -> None:
        self._placeholder = text
        self._update_text()

    def clear(self) -> None:
        self._entries.clear()
        self._current_index = -1
        self._update_text()

    def addItem(self, text: str, data: str = "") -> None:
        self._entries.append((text, data))

    def count(self) -> int:
        return len(self._entries)

    def itemText(self, index: int) -> str:
        return self._entries[index][0] if 0 <= index < self.count() else ""

    def itemData(self, index: int):
        return self._entries[index][1] if 0 <= index < self.count() else None

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        previous = self._current_index
        self._current_index = index if 0 <= index < self.count() else -1
        self._update_text()
        if self._current_index != previous and not self.signalsBlocked():
            self.tag_selected.emit(self.selectedTag())

    def findData(self, data) -> int:
        for index, (_text, entry_data) in enumerate(self._entries):
            if entry_data == data:
                return index
        return -1

    def selectedTag(self) -> str:
        data = self.itemData(self._current_index)
        return normalize_tag(str(data)) if data else ""

    def showPopup(self) -> None:
        if not self.isEnabled():
            return
        self._prepare_popup()
        self._popup.move(self._popup_origin())
        self._popup.show()
        self._popup.raise_()
        from app.ui.page_motion import fade_in_window

        fade_in_window(self._popup)
        self._popup_list.setFocus()

    def _prepare_popup(self) -> None:
        self._popup_list.clear()
        for index, (text, data) in enumerate(self._entries):
            item = QListWidgetItem(self._popup_list)
            item.setData(Qt.UserRole, data)
            item.setToolTip(text)
            item.setSizeHint(QSize(0, 28))
            row = QWidget(self._popup_list)
            row.setObjectName("tagPickerRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            select = QPushButton(text, row)
            select.setObjectName("tagPickerRowButton")
            select.setProperty("selected", index == self._current_index)
            select.setToolTip(text)
            select.clicked.connect(
                lambda checked=False, tag_data=data: self._choose_tag(tag_data)
            )
            delete = QPushButton("×", row)
            delete.setObjectName("tagPickerDeleteButton")
            delete.setToolTip(t("images.tag.delete_global_tooltip", tag=text))
            delete.clicked.connect(
                lambda checked=False, tag_data=data: self._request_tag_delete(tag_data)
            )
            row_layout.addWidget(select, stretch=1)
            row_layout.addWidget(delete)
            self._popup_list.setItemWidget(item, row)
            if index == self._current_index:
                self._popup_list.setCurrentItem(item)
        self._popup_list.setFixedHeight(min(max(self.count(), 1), 10) * 28 + 4)
        self._popup.setFixedWidth(max(self.width(), 220))
        self._popup.adjustSize()

    def _popup_origin(self) -> QPoint:
        anchor = self.mapToGlobal(QPoint(0, 0))
        screen = QApplication.screenAt(anchor)
        screen_top = screen.availableGeometry().top() if screen else 0
        popup_y = max(screen_top, anchor.y() - self._popup.height() - 4)
        return QPoint(anchor.x(), popup_y)

    def hidePopup(self) -> None:
        self._popup.close()

    def _choose_tag(self, data: str) -> None:
        tag = normalize_tag(str(data or ""))
        self.setCurrentIndex(self.findData(tag))
        self.hidePopup()

    def _request_tag_delete(self, data: str) -> None:
        tag = normalize_tag(str(data or ""))
        self.hidePopup()
        if tag:
            self.tag_delete_requested.emit(tag)

    def _request_new_tag(self) -> None:
        self.hidePopup()
        self.new_tag_requested.emit()

    def _update_text(self) -> None:
        self.setText(
            self.itemText(self._current_index)
            if self._current_index >= 0
            else self._placeholder
        )


class PreviewImageView(QScrollArea):
    """High-quality, bounded image preview with wheel zoom and scrolling."""

    open_requested = Signal()
    MIN_SCALE = 0.001
    MAX_SCALE = 6.0
    ZOOM_STEP = 1.15

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewImageView")
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._label = QLabel(self)
        self._label.setObjectName("previewImageLabel")
        self._label.setAlignment(Qt.AlignCenter)
        self.setWidget(self._label)
        self.viewport().installEventFilter(self)
        self._source = QPixmap()
        self._scale = 1.0
        self._fit_scale = 1.0
        self._fit_mode = True

    @property
    def image_label(self) -> QLabel:
        return self._label

    @property
    def scale_factor(self) -> float:
        return self._scale

    def has_image(self) -> bool:
        return not self._source.isNull()

    def clear_message(self, text: str) -> None:
        self._source = QPixmap()
        self._label.setPixmap(QPixmap())
        self._label.setText(text)
        self._label.setMaximumSize(16777215, 16777215)
        self._label.setMinimumSize(self.viewport().size())
        self._label.resize(self.viewport().size())
        self._scale = 1.0
        self._fit_scale = 1.0
        self._fit_mode = True
        self._reset_scrollbars()

    def load_path(self, path: Path) -> bool:
        self.clear_message("")
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return False
        self._source = QPixmap.fromImage(image)
        del image
        self.fit_to_preview()
        return True

    def fit_to_preview(self) -> None:
        if not self.has_image():
            return
        viewport_size = self.viewport().size()
        available_w = max(viewport_size.width() - 4, 1)
        available_h = max(viewport_size.height() - 4, 1)
        self._fit_scale = min(
            1.0,
            available_w / self._source.width(),
            available_h / self._source.height(),
        )
        self._fit_scale = max(self._fit_scale, self.MIN_SCALE)
        self._scale = self._fit_scale
        self._fit_mode = True
        self._render_source()
        self._reset_scrollbars()

    def zoom_by_steps(self, steps: int, anchor=None) -> None:
        if not self.has_image() or steps == 0:
            return
        old_scale = self._scale
        target = old_scale * (self.ZOOM_STEP ** steps)
        self._scale = min(self.MAX_SCALE, max(self._fit_scale, target))
        if abs(self._scale - old_scale) < 0.0001:
            return

        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        if anchor is None:
            anchor_x = self.viewport().width() / 2
            anchor_y = self.viewport().height() / 2
        else:
            anchor_x = anchor.x()
            anchor_y = anchor.y()
        content_x = hbar.value() + anchor_x
        content_y = vbar.value() + anchor_y
        ratio = self._scale / old_scale
        self._fit_mode = False
        self._render_source()
        hbar.setValue(round(content_x * ratio - anchor_x))
        vbar.setValue(round(content_y * ratio - anchor_y))

    def _render_source(self) -> None:
        if not self.has_image():
            return
        width = max(1, round(self._source.width() * self._scale))
        height = max(1, round(self._source.height() * self._scale))
        scaled = self._source.scaled(
            width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._label.setText("")
        self._label.setPixmap(scaled)
        self._label.setFixedSize(scaled.size())

    def _reset_scrollbars(self) -> None:
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode and self.has_image():
            self.fit_to_preview()
        elif not self.has_image():
            self._label.setMinimumSize(self.viewport().size())
            self._label.resize(self.viewport().size())

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport():
            if event.type() == QEvent.Type.Wheel:
                if self.has_image():
                    steps = 1 if event.angleDelta().y() > 0 else -1
                    self.zoom_by_steps(steps, event.position())
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if self.has_image() and event.button() == Qt.LeftButton:
                    self.open_requested.emit()
                return True
        return super().eventFilter(obj, event)


class _OverlayStack(QStackedWidget):
    """Right-column stack. Instant switch — opacity fades flash black on Windows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        paint_canvas(self)


def _is_usage_limit_error(error: object) -> bool:
    if isinstance(error, AiBudgetExceeded):
        return error.reason == "limit_reached"
    return str(getattr(error, "code", "") or "") == "budget_exceeded"


def _apply_ask_ai_usage_limit(message, error=None) -> bool:
    """Show the prototype usage-limit state. Not a generic API error."""
    del error
    title = t("account.ai.limit_reached")
    body = t("account.ai.limit_reached_body")
    if message is not None and hasattr(message, "set_limit_card"):
        message.set_limit_card(title, body)
        return True
    if message is not None and hasattr(message, "fail"):
        message.fail(f"{title}\n{body}")
        return True
    return False


def _tour_find_fail_reason(error: object) -> str:
    if isinstance(error, AiBudgetExceeded):
        if error.reason == "not_authenticated":
            return "unauthenticated"
        return "budget"
    code = str(getattr(error, "code", "") or "")
    if code == "unauthenticated":
        return "unauthenticated"
    if code in {"budget_unavailable", "budget_exceeded"}:
        return "budget"
    if "offline" in code:
        return "offline"
    return "unavailable"


def _request_tag_label(request: ActionRequest) -> str:
    from app.actions.tags import format_tag_list, requested_tags

    tags = requested_tags(request)
    return format_tag_list(tags) or str(request.param("tag") or "")


def _replace_preview_detail(plan) -> str:
    removed: list[str] = []
    added: list[str] = []
    seen_removed: set[str] = set()
    seen_added: set[str] = set()
    for item in getattr(plan, "items", ()) or ():
        for tag in (item.after or {}).get("removed_tags") or ():
            if tag and tag not in seen_removed:
                seen_removed.add(tag)
                removed.append(str(tag))
        for tag in (item.after or {}).get("added_tags") or ():
            if tag and tag not in seen_added:
                seen_added.add(tag)
                added.append(str(tag))
    parts = []
    if removed:
        parts.append(t("images.ai.plan_remove_tags_detail", tags=", ".join(removed)))
    if added:
        parts.append(t("images.ai.plan_add_tags_detail", tags=", ".join(added)))
    return "\n".join(parts)


def _split_unsupported_copy(raw: str, key: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if key == "images.ai.not_available_delete":
        return t("images.ai.not_available_delete").split(". ", 1)[0] + ".", t("images.ai.unsupported_body")
    if ". " in text:
        title, body = text.split(". ", 1)
        return title.rstrip(".") + ".", body
    return text or t("images.ai.unsupported_title"), t("images.ai.unsupported_body")


def _clarify_chips_for(key: str, query: str) -> list[tuple[str, str]]:
    chips = [
        (t("images.ai.clarify_chip_search"), "Find images"),
        (t("images.ai.clarify_chip_organize"), "Organize these images"),
        (t("images.ai.clarify_chip_results"), "What can I do with these results?"),
    ]
    noun = str(query or "").strip()
    if noun and key in {"images.ai.clarify_search", "images.ai.not_understood"}:
        chips[0] = (t("images.ai.clarify_chip_search"), f"Find images with {noun}")
    return chips


class ImagesPage(QWidget):
    """Image browser: list, search, sort, preview, tags, folders, and view modes."""

    folder_changed = Signal(str)
    folder_shortcuts_changed = Signal()
    tags_changed = Signal()  # emitted when global tag master changes from this page
    tags_page_requested = Signal()
    capture_requested = Signal()
    automation_run_finished = Signal(str, bool, str)

    def __init__(
        self,
        config: dict,
        metadata_service: MetadataService,
        thumbnail_cache: ThumbnailCache,
        app_root: Path,
        parent=None,
        search_provider: SearchProvider | None = None,
        semantic_search_provider: SearchProvider | None = None,
        analysis_controller=None,
        action_plan_provider: ActionPlanProvider | None = None,
        action_executor: ActionExecutorProvider | None = None,
        vision_search_provider: SearchProvider | None = None,
        semantic_index_indexer=None,
    ):
        super().__init__(parent)
        self._config = config
        self._metadata_service = metadata_service
        self._thumbnail_cache = thumbnail_cache
        self._app_root = app_root
        self._analysis_controller = analysis_controller
        self._semantic_index_indexer = semantic_index_indexer
        self._owned_hybrid_search_provider = None
        if search_provider is None:
            self._owned_hybrid_search_provider = HybridImagesSearchProvider(
                model_key=self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY),
                query_embedding_method=self._config.get(
                    "developer_query_embedding", DEFAULT_QUERY_EMBEDDING
                ),
            )
            search_provider = self._owned_hybrid_search_provider
        self._search_provider = search_provider
        self._owned_semantic_search_provider = None
        if semantic_search_provider is None:
            self._owned_semantic_search_provider = SemanticImagesSearchProvider(
                model_key=self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY),
                query_embedding_method=self._config.get(
                    "developer_query_embedding", DEFAULT_QUERY_EMBEDDING
                ),
            )
            semantic_search_provider = self._owned_semantic_search_provider
        self._semantic_search_provider = semantic_search_provider
        if vision_search_provider is None:
            self._owned_vision_search_provider = create_meaning_search_provider(
                model_key=self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY),
                query_embedding_method=self._config.get(
                    "developer_query_embedding", DEFAULT_QUERY_EMBEDDING
                ),
            )
        else:
            self._owned_vision_search_provider = vision_search_provider
        self._action_plan_provider = action_plan_provider or plan_image_action
        self._action_executor = action_executor or execute_image_tag_action
        self._search_pool = QThreadPool(self)
        # Search synchronizes filename/tag facts into one SQLite index. Keep
        # writes serialized and suppress duplicate requests for the same query.
        self._search_pool.setMaxThreadCount(1)
        self._search_request_id = 0
        self._tour_search_generation = 0
        self._search_tasks: dict[int, ImagesSearchTask] = {}
        self._search_started_at: dict[int, float] = {}
        # A Vision request owns its result collection.  It is deliberately
        # separate from the normal folder listing so unjudged candidates can
        # never become progressive search results by inheritance.
        self._progressive_visible_paths: dict[int, list[Path]] = {}
        self._local_search_by_request: dict[int, list[Path]] = {}
        self._last_search_error = None
        self._action_request_id = 0
        self._action_tasks: dict[int, ActionPlanTask] = {}
        self._ask_ai_request_id = 0
        self._ask_ai_search_tasks: dict[int, ImagesSearchTask] = {}
        self._ask_ai_result_by_request: dict[int, object] = {}
        self._ask_ai_grid_active = False
        self._ask_ai_grid_query = ""
        self._ask_ai_grid_paths: list[Path] = []
        self._ask_ai_prep_timer = QTimer(self)
        self._ask_ai_prep_timer.setInterval(400)
        self._ask_ai_prep_timer.timeout.connect(self._refresh_ask_ai_prep_status)
        self._ask_ai_pending_query: str | None = None
        self._ask_ai_pending_folder: Path | None = None
        self._ask_ai_initial_prep_done = False
        self._ask_ai_preview_timer: QTimer | None = None
        self._ask_ai_preview_seq = 0
        self._preview_panel_width: int | None = None
        self._pending_action_plan = None
        self._pending_action_paths: dict[int, Path] = {}
        self._action_executing = False
        self._workspace = WorkspaceSession()
        self._ask_ai_kind_by_request: dict[int, str] = {}
        self._ask_ai_pending_turn = None
        self._pending_act_request = None
        self._pending_act_message = None
        self._pending_prepared_plan = None
        self._pending_act_continuation = None
        self._last_savable_plan = None
        self._last_savable_request = None
        self._ask_ai_planner_response_id = ""
        self._ask_ai_planner_user_id = ""
        self._ask_ai_turn_busy = False
        self._ask_ai_turn_tasks: dict[int, AskAiTurnTask] = {}
        self._automation_auto_confirm = False
        self._automation_run_id = ""
        self._automation_service = AutomationService()

        self._active_search_query = ""
        self._active_search_mode = self._configured_search_mode()
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._preview_cache_path: str | None = None
        file_sort, group_by, filter_mode = expand_images_sort(DEFAULT_IMAGES_SORT)
        self._images_sort = DEFAULT_IMAGES_SORT
        self._sort_mode = file_sort
        self._filter_mode = filter_mode
        self._group_by = group_by
        self._thumbnail_mode = "small"
        self._gallery_layout = DEFAULT_GALLERY_LAYOUT
        self._unanalyzed_names: set[str] | dict[str, str] = set()
        self._analysis_details: dict[str, dict] = {}
        self._updating_folder_ui = False
        self._clipboard_paths: list[Path] = []
        self._clipboard_mode: str | None = None
        self._updating_selection = False
        # Always start with Viewing folder open (collapse is session-only)
        self._folder_tree_expanded = True
        self._config["images_folder_tree_expanded"] = True
        self._folder_panel_expanded_width = FOLDER_PANEL_EXPANDED_WIDTH
        self._fs_refreshing = False
        self._undo: UndoRecord | None = None
        self._caption_delegate: CaptionIconDelegate | None = None
        self._gallery_layout_key = None
        self._header_tools_inline = True
        self._ai_panel_expanded = False
        self._right_mode_animation = None
        self._right_mode_overlay = None
        self._quick_preview_dialog = None
        self._folder_forward_stack: list[Path] = []
        self._navigating_history = False
        self._folder_nav_filter = _FolderMouseNavFilter(self)
        self._folder_nav_filter_installed = False
        self.destroyed.connect(self._cleanup_folder_nav_filter)
        self._thumbnail_load_generation = 0
        self._thumbnail_load_queue: list[tuple[QListWidgetItem, Path]] = []
        self._thumbnail_load_timer = QTimer(self)
        self._thumbnail_load_timer.setSingleShot(True)
        self._thumbnail_load_timer.timeout.connect(self._hydrate_thumbnail_batch)

        self._init_ui()
        self._setup_shortcuts()
        self._setup_fs_watcher()
        self._load_display_settings_from_project()
        self._apply_thumbnail_mode()
        self.reload_tag_choices()
        self._apply_folder_tree_expanded(True, persist=False)
        self._apply_header_tools_layout(force=True)

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        paint_canvas(self)

        page_root = QWidget(self)
        page_root.setObjectName("imagesWorkspacePage")
        paint_canvas(page_root)
        outer.addWidget(page_root)
        main_layout = QVBoxLayout(page_root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        from app.ui.page_header import PAGE_HEADER_MARGINS, make_page_header

        # Use the same restrained title treatment as Organize / Tags. Images
        # previously had a one-off hero illustration that broke page alignment.
        page_header = make_page_header(
            page_root,
            t("images.title"),
            t("images.subtitle"),
            margins=PAGE_HEADER_MARGINS,
        )
        page_header.hide()
        main_layout.addWidget(page_header)

        folder_selector = QFrame(page_root)
        folder_selector.setObjectName("folderSelectorBar")
        self._folder_selector = folder_selector
        folder_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selector_layout = QHBoxLayout(folder_selector)
        selector_layout.setContentsMargins(0, 2, 0, 2)
        selector_layout.setSpacing(SPACE_2)
        folder_icon_label = QLabel(folder_selector)
        folder_icon_label.setObjectName("sectionIcon")
        folder_icon_label.setPixmap(
            icon_folder(color="#3d4450").pixmap(QSize(14, 14))
        )
        folder_icon_label.hide()
        selector_layout.addWidget(folder_icon_label, 0, Qt.AlignVCenter)
        folder_selector_title = QLabel(
            t("images.folder_selector_label"), folder_selector
        )
        folder_selector_title.setObjectName("sectionTitle")
        self._folder_selector_title = folder_selector_title
        folder_selector_title.hide()
        selector_layout.addWidget(folder_selector_title, 0, Qt.AlignVCenter)
        self._folder_path_field = QFrame(folder_selector)
        self._folder_path_field.setObjectName("folderPathField")
        path_field_layout = QHBoxLayout(self._folder_path_field)
        path_field_layout.setContentsMargins(0, 2, 0, 2)
        path_field_layout.setSpacing(8)
        self._selected_folder_value = ElidedPathLabel(self._folder_path_field)
        self._selected_folder_value.setObjectName("folderSelectorPath")
        self._selected_folder_value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        path_field_layout.addWidget(self._selected_folder_value, stretch=1)
        self._folder_breadcrumb = FolderBreadcrumb(self)
        self._folder_breadcrumb.folder_activated.connect(self.open_folder)
        self._folder_breadcrumb.hide()
        selector_layout.addWidget(self._folder_path_field, stretch=1)
        self._favorite_folder_btn = QPushButton(folder_selector)
        self._favorite_folder_btn.setObjectName("folderFavoriteButton")
        self._favorite_folder_btn.setCursor(Qt.PointingHandCursor)
        self._favorite_folder_btn.clicked.connect(self._toggle_current_folder_favorite)
        selector_layout.addWidget(self._favorite_folder_btn)
        self._choose_folder_btn = QPushButton(t("images.choose_folder"), folder_selector)
        self._choose_folder_btn.setObjectName("secondaryButton")
        self._choose_folder_btn.setIcon(icon_folder())
        self._choose_folder_btn.setCursor(Qt.PointingHandCursor)
        self._choose_folder_btn.clicked.connect(self._choose_selected_folder)
        selector_layout.addWidget(self._choose_folder_btn)

        # Content: Folders | List | Preview
        content = QWidget(page_root)
        content.setObjectName("imagesWorkspaceBody")
        self._content = content
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(
            WORKSPACE_PADDING, WORKSPACE_GAP, WORKSPACE_PADDING, WORKSPACE_PADDING
        )
        content_layout.setSpacing(WORKSPACE_GAP)

        controls = QFrame(content)
        controls.setObjectName("imagesCommandSurface")
        self._command_surface = controls
        controls.setAttribute(Qt.WA_StyledBackground, True)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(
            IMAGES_LEFT_CARD_PAD_X,
            IMAGES_LEFT_CARD_PAD_Y,
            IMAGES_LEFT_CARD_PAD_X,
            IMAGES_LEFT_CARD_PAD_Y,
        )
        controls_layout.setSpacing(SPACE_2)

        self._command_primary_row = QWidget(controls)
        self._command_primary_row.setObjectName("imagesCommandPrimaryRow")
        self._command_primary_layout = QHBoxLayout(self._command_primary_row)
        self._command_primary_layout.setContentsMargins(0, 0, 0, 0)
        self._command_primary_layout.setSpacing(IMAGES_COMMAND_GAP)
        # The active folder remains a separate locator card. It is inserted
        # into the left workspace below so it aligns with Search and gallery.
        controls_layout.addWidget(self._command_primary_row)
        self._splitter = QSplitter(Qt.Horizontal, content)
        self._splitter.setObjectName("imagesSplitter")

        # Folder tree (collapsible) — same card chrome as Screenshots / Preview
        self._folder_panel = QWidget(self)
        self._folder_panel.setObjectName("folderPanel")
        self._folder_panel.setMinimumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
        self._folder_panel.setMaximumWidth(FOLDER_PANEL_MAX_WIDTH)
        self._folder_panel.installEventFilter(self)
        self._folder_panel.setAttribute(Qt.WA_Hover, True)
        folder_layout = QVBoxLayout(self._folder_panel)
        folder_layout.setContentsMargins(
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
        )
        folder_layout.setSpacing(6)

        self._folder_collapse_btn = QPushButton("◀", self)
        self._folder_collapse_btn.setObjectName("sectionToggleButton")
        self._folder_collapse_btn.setCursor(Qt.PointingHandCursor)
        self._folder_collapse_btn.setToolTip(t("images.collapse_folders"))
        self._folder_collapse_btn.clicked.connect(self._toggle_folder_tree)

        # Same header row as Screenshots / Preview (toggle on the right)
        self._folder_header = self._build_section_header(
            t("images.folders"),
            icon_folder(),
            trailing=self._folder_collapse_btn,
        )
        self._folder_header_title_row = self._folder_header.findChild(
            QWidget, "sectionHeaderTitleRow"
        )
        self._folder_header_divider = self._folder_header.findChild(
            QFrame, "sectionDivider"
        )
        self._folder_header_icon = None
        self._folder_header_title = None
        for lab in self._folder_header.findChildren(QLabel):
            if lab.objectName() == "sectionIcon" and self._folder_header_icon is None:
                self._folder_header_icon = lab
            elif lab.objectName() == "sectionTitle" and self._folder_header_title is None:
                self._folder_header_title = lab

        # Hints sit under the shared title row (same vertical level as other panels)
        self._folder_project_hint = QLabel(self._folder_header)
        self._folder_project_hint.setObjectName("mutedLabel")
        self._folder_project_hint.setWordWrap(True)
        self._save_folder_legend = QLabel(
            t("images.save_folder_star_legend"), self._folder_header
        )
        self._save_folder_legend.setObjectName("saveFolderLegend")
        self._save_folder_legend.setWordWrap(True)
        # Insert hints above the divider so the title row stays aligned with peers
        header_layout = self._folder_header.layout()
        if header_layout is not None and self._folder_header_divider is not None:
            divider_index = header_layout.indexOf(self._folder_header_divider)
            if divider_index < 0:
                divider_index = header_layout.count()
            header_layout.insertWidget(divider_index, self._folder_project_hint)
            header_layout.insertWidget(divider_index + 1, self._save_folder_legend)
        folder_layout.addWidget(self._folder_header)
        self._folder_header.installEventFilter(self)
        if self._folder_header_title_row is not None:
            self._folder_header_title_row.installEventFilter(self)

        # Collapsed rail: frame shows ▶ (not a separate button)
        self._folder_expand_glyph = QLabel("▶", self._folder_panel)
        self._folder_expand_glyph.setObjectName("folderExpandGlyph")
        self._folder_expand_glyph.setAlignment(Qt.AlignCenter)
        self._folder_expand_glyph.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._folder_expand_glyph.hide()
        folder_layout.addWidget(self._folder_expand_glyph)

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
        self._folder_panel.hide()

        # Image list
        list_panel = QFrame(self)
        list_panel.setObjectName("leftPanel")
        list_panel.setAttribute(Qt.WA_StyledBackground, True)
        list_panel.setMinimumWidth(LIST_PANEL_MIN_WIDTH)
        self._list_panel = list_panel
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, IMAGES_LEFT_CARD_PAD_Y)
        list_layout.setSpacing(4)

        # Secondary display controls live below the primary search row.
        self._header_tools = QFrame(self)
        self._header_tools.setObjectName("headerTools")
        self._header_tools.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        tools_layout = QHBoxLayout(self._header_tools)
        tools_layout.setContentsMargins(4, 0, 4, 0)
        tools_layout.setSpacing(12)
        tools_layout.setAlignment(Qt.AlignVCenter)

        def _tool_field(label_text: str) -> tuple[QWidget, QLabel, QComboBox]:
            field = QWidget(self._header_tools)
            field.setObjectName("headerToolField")
            field_layout = QHBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(6)
            lbl = QLabel(label_text, field)
            lbl.setObjectName("toolbarFieldLabel")
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            field_layout.addWidget(lbl, 0, Qt.AlignVCenter)
            combo = QComboBox(field)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            combo.setCursor(Qt.PointingHandCursor)
            field_layout.addWidget(combo, 0, Qt.AlignVCenter)
            return field, lbl, combo

        filter_field, self._filter_label, self._filter_combo = _tool_field(
            t("filter.label")
        )
        self._filter_combo.setMinimumWidth(110)
        self._filter_combo.setMaximumWidth(160)
        self._filter_combo.addItem(t("filter.all"), "all")
        self._filter_combo.addItem(t("filter.favorites_only"), FILTER_FAVORITES_ONLY)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_field.hide()
        self._filter_combo.hide()
        self._filter_label.hide()

        sort_field, self._sort_label, self._sort_combo = _tool_field(
            t("images.sort_label")
        )
        self._sort_field = sort_field
        self._sort_combo.setMinimumWidth(110)
        self._sort_combo.setMaximumWidth(160)
        for mode, label in images_sort_option_labels():
            self._sort_combo.addItem(label, mode)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        tools_layout.addWidget(sort_field, 0, Qt.AlignVCenter)

        self._ai_results_clear_btn = QPushButton(t("images.clear"), self._header_tools)
        self._ai_results_clear_btn.setObjectName("secondaryButton")
        self._ai_results_clear_btn.setIcon(icon_clear())
        self._ai_results_clear_btn.setIconSize(QSize(14, 14))
        self._ai_results_clear_btn.setCursor(Qt.PointingHandCursor)
        self._ai_results_clear_btn.setToolTip(t("images.clear"))
        self._ai_results_clear_btn.setAccessibleName(t("images.clear"))
        self._ai_results_clear_btn.setAutoDefault(False)
        self._ai_results_clear_btn.setDefault(False)
        self._ai_results_clear_btn.clicked.connect(self._on_clear_search)
        tools_layout.addWidget(self._ai_results_clear_btn, 0, Qt.AlignVCenter)
        self._ai_results_clear_btn.hide()

        group_field, self._group_label, self._group_combo = _tool_field(
            t("images.group_by_label")
        )
        self._group_combo.setMinimumWidth(64)
        self._group_combo.setMaximumWidth(90)
        for mode, label in group_by_option_labels(include_analysis=True):
            self._group_combo.addItem(label, mode)
        self._group_combo.currentIndexChanged.connect(self._on_group_by_changed)
        tools_layout.addWidget(group_field, 0, Qt.AlignVCenter)
        group_field.hide()
        self._group_combo.hide()

        view_field, self._view_label, self._view_combo = _tool_field(t("common.view"))
        self._view_combo.setMinimumWidth(64)
        self._view_combo.setMaximumWidth(90)
        for mode, label in thumbnail_mode_labels():
            self._view_combo.addItem(label, mode)
        self._view_combo.currentIndexChanged.connect(self._on_view_combo_changed)
        tools_layout.addWidget(view_field, 0, Qt.AlignVCenter)
        view_field.hide()
        self._view_combo.hide()

        self._layout_toggle = SegmentedToggle(
            [t("view.grid"), t("view.list")],
            self._header_tools,
            icons=[icon_layout_grid(), icon_layout_list()],
            icon_size=14,
        )
        self._layout_toggle.setObjectName("galleryLayoutToggle")
        self._layout_toggle.setToolTip(t("view.layout_tooltip"))
        self._layout_toggle.changed.connect(self._on_gallery_layout_changed)
        blocked = self._layout_toggle.blockSignals(True)
        self._layout_toggle.set_current(0)
        self._layout_toggle.blockSignals(blocked)
        layout_field = QWidget(self._header_tools)
        layout_field.setObjectName("headerToolField")
        layout_field_layout = QHBoxLayout(layout_field)
        layout_field_layout.setContentsMargins(0, 0, 0, 0)
        layout_field_layout.setSpacing(6)
        self._layout_label = QLabel(t("images.layout_label"), layout_field)
        self._layout_label.setObjectName("toolbarFieldLabel")
        self._layout_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._layout_label.hide()
        layout_field_layout.addWidget(self._layout_label, 0, Qt.AlignVCenter)
        layout_field_layout.addWidget(self._layout_toggle, 0, Qt.AlignVCenter)
        self._layout_field = layout_field

        self._view_menu_btn = QPushButton(t("common.view"), self._header_tools)
        self._view_menu_btn.setObjectName("secondaryButton")
        self._view_menu_btn.setCursor(Qt.PointingHandCursor)
        self._view_menu_btn.clicked.connect(self._show_view_menu)
        self._view_menu_btn.hide()

        self._actions_tags_btn = QPushButton(
            t("images.actions.tags"), self._header_tools
        )
        self._actions_tags_btn.setObjectName("secondaryButton")
        self._actions_tags_btn.setIcon(icon_tags())
        self._actions_tags_btn.setIconSize(QSize(15, 15))
        self._actions_tags_btn.setCursor(Qt.PointingHandCursor)
        self._actions_tags_btn.clicked.connect(self._show_tags_popup)
        tools_layout.addWidget(self._actions_tags_btn, 0, Qt.AlignVCenter)

        # Search is the primary action and comes before display controls.
        search_row = QWidget(self._command_primary_row)
        search_row.setObjectName("screenshotsSearchRow")
        self._search_row = search_row
        search_layout = QVBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        search_header = QWidget(search_row)
        search_header.setObjectName("searchHeaderRow")
        search_header.setAttribute(Qt.WA_StyledBackground, True)
        search_header.setAutoFillBackground(False)
        search_header_layout = QHBoxLayout(search_header)
        search_header_layout.setContentsMargins(0, 0, 0, 0)
        search_header_layout.setSpacing(8)

        search_shell = QFrame(search_header)
        search_shell.setObjectName("screenshotsSearchShell")
        search_shell.setAttribute(Qt.WA_StyledBackground, True)
        self._search_shell = search_shell
        shell_layout = QHBoxLayout(search_shell)
        shell_layout.setContentsMargins(12, 3, 4, 3)
        shell_layout.setSpacing(6)

        search_glyph = QLabel(search_shell)
        search_glyph.setObjectName("searchShellGlyph")
        search_glyph.setPixmap(icon_search().pixmap(QSize(16, 16)))
        shell_layout.addWidget(search_glyph, 0, Qt.AlignVCenter)

        self._search_input = QLineEdit(search_shell)
        self._search_input.setObjectName("screenshotsSearchInput")
        self._search_input.setFrame(False)
        self._search_input.setAutoFillBackground(False)
        search_palette = self._search_input.palette()
        search_palette.setColor(QPalette.ColorRole.Base, Qt.transparent)
        search_palette.setColor(QPalette.ColorRole.Window, Qt.transparent)
        self._search_input.setPalette(search_palette)
        self._search_input.setPlaceholderText(t("images.search_placeholder"))
        self._search_input.returnPressed.connect(self._on_search)
        self._search_input.installEventFilter(self)
        shell_layout.addWidget(self._search_input, stretch=1)

        self._clear_search_btn = QPushButton("", search_shell)
        self._clear_search_btn.setObjectName("searchClearButton")
        self._clear_search_btn.setIcon(icon_clear())
        self._clear_search_btn.setIconSize(QSize(14, 14))
        self._clear_search_btn.setFixedSize(28, 28)
        self._clear_search_btn.setCursor(Qt.PointingHandCursor)
        self._clear_search_btn.setAccessibleName(t("images.clear"))
        self._clear_search_btn.setToolTip(t("images.clear"))
        self._clear_search_btn.clicked.connect(self._on_clear_search)
        shell_layout.addWidget(self._clear_search_btn, 0, Qt.AlignVCenter)

        self._search_btn = QPushButton(t("images.search"), search_shell)
        self._search_btn.setObjectName("imagesPrimarySearchButton")
        self._search_btn.setCursor(Qt.PointingHandCursor)
        self._search_btn.clicked.connect(self._on_search)
        shell_layout.addWidget(self._search_btn, 0, Qt.AlignVCenter)
        search_header_layout.addWidget(search_shell, stretch=1)
        search_layout.addWidget(search_header)

        # Hidden compatibility/test hook for developer routing values.
        self._search_mode_combo = QComboBox(self)
        self._search_mode_combo.setObjectName("imagesSearchMode")
        self._search_mode_combo.addItem(t("settings.developer_search.hybrid"), "hybrid")
        self._search_mode_combo.addItem(t("images.search_mode.text"), "text")
        self._search_mode_combo.addItem(t("images.search_mode.semantic"), "semantic")
        self._search_mode_combo.addItem(
            t("settings.developer_search.vision_relevance"), "vision_relevance"
        )
        self._search_mode_combo.setToolTip(t("images.search_mode.tooltip"))
        self._search_mode_combo.currentIndexChanged.connect(
            self._on_search_mode_changed
        )
        self._search_mode_combo.hide()
        mode_index = self._search_mode_combo.findData(self._active_search_mode)
        if mode_index >= 0:
            self._search_mode_combo.setCurrentIndex(mode_index)
        self._apply_search_placeholder()

        self._command_primary_layout.addWidget(search_row, 1, Qt.AlignTop)

        self._action_input_row = QWidget(controls)
        self._action_input_row.setObjectName("imagesActionInputRow")
        self._action_input_row.setProperty("prototype_anchor", ANCHOR_IMAGES_ASK_AI)
        self._tour_act_preview_widget = None
        self._tour_favorite_anchor = None
        action_layout = QHBoxLayout(self._action_input_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)
        self._action_input = QLineEdit(self._action_input_row)
        self._action_input.setObjectName("imagesActionInput")
        self._action_input.setPlaceholderText(t("images.ai.placeholder"))
        self._action_input.returnPressed.connect(self._on_ask_ai_send)
        self._action_input.textEdited.connect(self._invalidate_action_confirmation)
        self._action_input.textChanged.connect(self._sync_action_send_enabled)
        action_layout.addWidget(self._action_input, stretch=1)
        self._action_preview_btn = QPushButton(self._action_input_row)
        self._action_preview_btn.setObjectName("aiSendButton")
        self._action_preview_btn.setIcon(icon_send_up(size=16))
        self._action_preview_btn.setIconSize(QSize(16, 16))
        self._action_preview_btn.setFixedSize(CONTROL_COMPACT, CONTROL_COMPACT)
        self._action_preview_btn.setCursor(Qt.PointingHandCursor)
        self._action_preview_btn.setToolTip(t("images.ai.send"))
        self._action_preview_btn.setAccessibleName(t("images.ai.send"))
        self._action_preview_btn.setDefault(False)
        self._action_preview_btn.setAutoDefault(False)
        self._action_preview_btn.clicked.connect(self._on_ask_ai_send)
        action_layout.addWidget(self._action_preview_btn, 0, Qt.AlignVCenter)
        self._sync_action_send_enabled()
        controls_layout.addWidget(self._action_input_row)
        self._action_input_row.hide()
        self._action_input.hide()
        self._action_preview_btn.hide()

        self._action_preview = QFrame(controls)
        self._action_preview.setObjectName("imagesActionPreview")
        action_preview_layout = QVBoxLayout(self._action_preview)
        action_preview_layout.setContentsMargins(SPACE_3, SPACE_2, SPACE_3, SPACE_2)
        action_preview_layout.setSpacing(SPACE_1)
        self._action_summary_label = QLabel(self._action_preview)
        self._action_summary_label.setObjectName("sectionTitle")
        self._action_summary_label.setWordWrap(True)
        action_preview_layout.addWidget(self._action_summary_label)
        self._action_detail_label = QLabel(self._action_preview)
        self._action_detail_label.setObjectName("mutedLabel")
        self._action_detail_label.setWordWrap(True)
        action_preview_layout.addWidget(self._action_detail_label)
        self._action_next_btn = QPushButton(
            t("images.ai.confirm"), self._action_preview
        )
        self._action_next_btn.setObjectName("secondaryButton")
        self._action_next_btn.setEnabled(False)
        self._action_next_btn.setToolTip(t("images.ai.preview_only"))
        self._action_next_btn.clicked.connect(self._on_action_confirmed)
        action_preview_layout.addWidget(self._action_next_btn, 0, Qt.AlignRight)
        self._action_preview.hide()
        controls_layout.addWidget(self._action_preview)

        self._content_search_setup = ImageContentSearchSetup(
            controls,
            model_key=self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY),
        )
        self._content_search_setup.installed.connect(self._on_semantic_bundle_installed)
        controls_layout.addWidget(self._content_search_setup)

        self._analysis_bar = None
        if self._analysis_controller is not None:
            self._analysis_bar = ImagesAnalysisBar(
                self._analysis_controller, page_root, auto_start=True
            )
            self._analysis_bar.hide()
            page_root.layout().addWidget(self._analysis_bar)
            self._analysis_bar.analysis_completed.connect(
                self._on_analysis_completed
            )
            self._analysis_bar.analysis_summary_changed.connect(
                self._on_analysis_summary_changed
            )
            self._analysis_bar.library_prep_changed.connect(
                self._on_library_prep_changed
            )

        self._search_status_row = QWidget(self)
        self._search_status_row.setObjectName("searchStatusRow")
        search_status_layout = QHBoxLayout(self._search_status_row)
        search_status_layout.setContentsMargins(0, 0, 0, 0)
        search_status_layout.setSpacing(6)
        self._search_status_spinner = SearchBusySpinner(
            self._search_status_row, size=14
        )
        self._search_status_spinner.hide()
        search_status_layout.addWidget(self._search_status_spinner, 0, Qt.AlignVCenter)
        self._search_result_label = QLabel(self._search_status_row)
        self._search_result_label.setObjectName("searchResultLabel")
        search_status_layout.addWidget(self._search_result_label, 0, Qt.AlignVCenter)
        self._search_status_row.hide()
        self._library_prep_label = QLabel(self)
        self._library_prep_label.setObjectName("libraryPrepLabel")
        self._library_prep_label.hide()

        tools_layout.addStretch(1)
        tools_layout.addWidget(self._layout_field, 0, Qt.AlignVCenter)

        self._header_tools_row = QWidget(list_panel)
        self._header_tools_row.setObjectName("imagesResultsHeader")
        self._header_tools_row.setAttribute(Qt.WA_StyledBackground, True)
        self._header_tools_row_layout = QHBoxLayout(self._header_tools_row)
        self._header_tools_row_layout.setContentsMargins(
            IMAGES_LEFT_CARD_PAD_X + 8,
            IMAGES_LEFT_CARD_PAD_Y,
            IMAGES_LEFT_CARD_PAD_X + 8,
            SPACE_2,
        )
        self._header_tools_row_layout.setSpacing(8)
        self._folder_up_btn = QPushButton(self._header_tools_row)
        self._folder_up_btn.setObjectName("galleryFolderUpButton")
        self._folder_up_btn.setIcon(icon_back())
        self._folder_up_btn.setIconSize(QSize(15, 15))
        self._folder_up_btn.setFixedSize(28, 28)
        self._folder_up_btn.setCursor(Qt.PointingHandCursor)
        self._folder_up_btn.setToolTip(t("images.folder_up_tooltip"))
        self._folder_up_btn.setAccessibleName(t("images.folder_up"))
        self._folder_up_btn.clicked.connect(self._navigate_folder_back)
        self._header_tools_row_layout.addWidget(self._folder_up_btn, 0, Qt.AlignVCenter)
        self._gallery_count_label = QLabel(t("images.item_count", count=0), self._header_tools_row)
        self._gallery_count_label.setObjectName("galleryItemCount")
        self._header_tools_row_layout.addWidget(self._gallery_count_label, 0, Qt.AlignVCenter)
        self._header_tools_row_layout.addWidget(self._search_status_row, 0, Qt.AlignVCenter)
        self._header_tools_row_layout.addWidget(self._library_prep_label, 0, Qt.AlignVCenter)
        self._header_tools_row_layout.addStretch(1)
        self._header_tools_row_layout.addWidget(self._header_tools)
        self._header_tools_slot = self._header_tools_row
        self._header_tools_slot_layout = self._header_tools_row_layout
        self._header_tools_inline = False
        self._gallery_header = self._build_section_header(
            t("images.screenshots"),
            icon_images(),
            panel_header=True,
        )
        list_layout.addWidget(self._header_tools_row)
        gallery_body = QWidget(list_panel)
        gallery_body.setObjectName("imagesGalleryBody")
        gallery_body.setAutoFillBackground(False)
        gallery_layout = QVBoxLayout(gallery_body)
        gallery_layout.setContentsMargins(
            IMAGES_LEFT_CARD_PAD_X, 0, IMAGES_LEFT_CARD_PAD_X, 0
        )
        gallery_layout.setSpacing(4)
        gallery_layout.addWidget(self._gallery_header)
        self._gallery_header.hide()

        self._child_folders = ChildFolderRow(self)
        self._child_folders.itemClicked.connect(self._on_child_folder_clicked)
        self._child_folders.hide()

        self._list_stack = QStackedWidget(gallery_body)
        self._list_stack.setObjectName("imagesListStack")

        self._list_empty = QFrame(self._list_stack)
        self._list_empty.setObjectName("emptyHintCard")
        empty_layout = QVBoxLayout(self._list_empty)
        empty_layout.setContentsMargins(16, 24, 16, 24)
        empty_layout.setSpacing(6)
        empty_layout.addStretch(1)
        self._list_empty_title = QLabel(t("images.empty_title"), self._list_empty)
        self._list_empty_title.setObjectName("emptyHintTitle")
        self._list_empty_title.setWordWrap(True)
        self._list_empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self._list_empty_title)
        self._list_empty_body = QLabel(t("images.empty_body"), self._list_empty)
        self._list_empty_body.setObjectName("emptyHintBody")
        self._list_empty_body.setWordWrap(True)
        self._list_empty_body.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self._list_empty_body)
        self._empty_choose_folder_btn = QPushButton(
            t("images.choose_folder"), self._list_empty
        )
        self._empty_choose_folder_btn.setObjectName("secondaryButton")
        self._empty_choose_folder_btn.setCursor(Qt.PointingHandCursor)
        self._empty_choose_folder_btn.clicked.connect(self._choose_selected_folder)
        empty_layout.addWidget(self._empty_choose_folder_btn, 0, Qt.AlignCenter)
        empty_layout.addStretch(1)
        self._list_empty.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_empty.customContextMenuRequested.connect(
            self._on_empty_hint_context_menu
        )
        self._list_empty_title.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_empty_title.customContextMenuRequested.connect(
            self._on_empty_hint_context_menu
        )
        self._list_empty_body.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_empty_body.customContextMenuRequested.connect(
            self._on_empty_hint_context_menu
        )

        self._list_searching = SearchBusyCard(self._list_stack)

        self._list_widget = ScreenshotListWidget(self)
        self._list_widget.setObjectName("screenshotList")
        self._list_widget.setProperty("prototype_anchor", ANCHOR_SEARCH_RESULTS_GRID)
        self._list_widget.setViewMode(QListWidget.IconMode)
        self._list_widget.setResizeMode(QListWidget.Adjust)
        self._list_widget.setSpacing(THUMBNAIL_LIST_SPACING)
        self._list_widget.setWordWrap(True)
        self._list_widget.setUniformItemSizes(True)
        self._list_widget.setTextElideMode(Qt.ElideMiddle)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget.configure_explorer_selection()
        # setViewMode/setMovement reset Qt DnD flags — restore drag-to-folder only
        self._list_widget.configure_drag_export_only()
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self._list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self._list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._on_context_menu)
        self._list_widget.viewport().installEventFilter(self)

        self._list_stack.addWidget(self._list_widget)  # 0 = images
        self._list_stack.addWidget(self._list_empty)  # 1 = empty hint
        self._list_stack.addWidget(self._list_searching)  # 2 = searching
        gallery_layout.addWidget(self._list_stack, stretch=1)
        list_layout.addWidget(gallery_body, stretch=1)
        self._list_marquee_bridge = ListPanelMarqueeBridge(
            list_panel, self._list_widget, self
        )
        # Left workspace owns both commands and the gallery. Keeping them in
        # one splitter column makes their right edges align while the details
        # column can start at the top beside Folder / Search.
        left_workspace = QWidget(self)
        left_workspace.setObjectName("imagesLeftWorkspace")
        left_workspace_layout = QVBoxLayout(left_workspace)
        left_workspace_layout.setContentsMargins(0, 0, 0, 0)
        left_workspace_layout.setSpacing(SPACE_2)
        self._folder_browser = QFrame(left_workspace)
        self._folder_browser.setObjectName("folderBrowser")
        self._folder_browser.setAttribute(Qt.WA_StyledBackground, True)
        folder_browser_layout = QVBoxLayout(self._folder_browser)
        folder_browser_layout.setContentsMargins(
            IMAGES_LEFT_CARD_PAD_X,
            6,
            IMAGES_LEFT_CARD_PAD_X,
            6,
        )
        folder_browser_layout.setSpacing(0)
        folder_browser_layout.addWidget(folder_selector)
        self._folder_browser_divider = QFrame(self._folder_browser)
        self._folder_browser_divider.setObjectName("folderBrowserDivider")
        self._folder_browser_divider.setFrameShape(QFrame.NoFrame)
        self._folder_browser_divider.setFixedHeight(1)
        self._folder_browser_divider.hide()
        self._child_folders.hide()
        left_workspace_layout.addWidget(controls)
        left_workspace_layout.addWidget(self._folder_browser)
        left_workspace_layout.addWidget(list_panel, stretch=1)
        self._left_workspace = left_workspace
        self._splitter.addWidget(left_workspace)
        self._list_panel.installEventFilter(self)

        # Preview + AI chat share the permanent right column.
        right_panel = QWidget(self)
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._right_stack = _OverlayStack(right_panel)
        self._right_stack.setObjectName("rightModeStack")
        right_layout.addWidget(self._right_stack, stretch=1)

        self._preview_page = QWidget(self._right_stack)
        self._preview_page.setObjectName("previewModePage")
        self._preview_page.setAttribute(Qt.WA_StyledBackground, True)
        preview_page_layout = QVBoxLayout(self._preview_page)
        preview_page_layout.setContentsMargins(0, 0, 0, 0)
        preview_page_layout.setSpacing(SPACE_2)

        self._preview_card = QFrame(self._preview_page)
        self._preview_card.setObjectName("previewCard")
        self._preview_card.setProperty("cardRole", "preview")
        self._preview_card.setMinimumHeight(0)
        self._preview_card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        preview_card_layout = QVBoxLayout(self._preview_card)
        preview_card_layout.setContentsMargins(
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
        )
        preview_card_layout.setSpacing(SPACE_2)
        preview_card_layout.addWidget(
            self._build_section_header(
                t("images.preview"),
                icon_preview(),
            )
        )

        self._preview_view = PreviewImageView(self._preview_card)
        self._preview_view.setMinimumSize(160, IMAGES_PREVIEW_IMAGE_MIN_HEIGHT)
        self._preview_view.setMaximumHeight(IMAGES_PREVIEW_IMAGE_MAX_HEIGHT)
        self._preview_view.setFixedHeight(IMAGES_PREVIEW_IMAGE_MAX_HEIGHT)
        self._preview_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._preview_label = self._preview_view.image_label
        self._preview_view.clear_message(t("images.select_image"))
        self._preview_view.open_requested.connect(self._open_preview_image)
        preview_card_layout.addWidget(self._preview_view, stretch=0)

        self._information_card = QWidget(self._preview_card)
        self._information_card.setObjectName("previewInfoSection")
        self._information_card.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        information_layout = QVBoxLayout(self._information_card)
        information_layout.setContentsMargins(0, SPACE_2, 0, 0)
        information_layout.setSpacing(SPACE_2)
        information_layout.addWidget(
            self._build_section_header(t("images.information"), icon_about())
        )

        information_grid = QGridLayout()
        information_grid.setContentsMargins(2, 0, 2, 0)
        information_grid.setHorizontalSpacing(8)
        information_grid.setVerticalSpacing(4)

        def _info_row(row: int, label_text: str) -> ElidedPathLabel:
            key = QLabel(label_text, self._information_card)
            key.setObjectName("previewInfoKey")
            value = ElidedPathLabel(self._information_card)
            value.setObjectName("previewInfoValue")
            value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            information_grid.addWidget(key, row, 0, Qt.AlignTop)
            information_grid.addWidget(value, row, 1)
            return value

        self._file_info_label = _info_row(0, t("images.info_file"))
        self._modified_info_label = _info_row(1, t("images.info_modified"))
        self._folder_info_label = _info_row(2, t("images.info_folder"))
        self._dimensions_info_label = _info_row(3, t("images.info_dimensions"))
        self._size_info_label = _info_row(4, t("images.info_size"))
        self._tags_info_label = _info_row(5, t("images.tags"))
        information_grid.setColumnStretch(1, 1)
        information_layout.addLayout(information_grid)
        preview_card_layout.addWidget(self._information_card)
        self._right_scroll_host = self._preview_card
        preview_page_layout.addWidget(self._preview_card, stretch=0)

        # Tags is a floating tool window so it cannot sit under the splitter.
        self._tags_card = QFrame(self)
        self._tags_card.setObjectName("previewCard")
        self._tags_card.setProperty("cardRole", "tags")
        self._tags_card.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self._tags_card.setAttribute(Qt.WA_StyledBackground, True)
        self._tags_card.setMinimumHeight(0)
        self._tags_card.setFixedWidth(360)
        self._tags_card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._tags_card_layout = QVBoxLayout(self._tags_card)
        self._tags_card_layout.setContentsMargins(
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
        )
        self._tags_card_layout.setSpacing(SPACE_2)
        self._tags_close_btn = QPushButton("×", self._tags_card)
        self._tags_close_btn.setObjectName("tagsPopoverClose")
        self._tags_close_btn.setFixedSize(28, 28)
        self._tags_close_btn.setCursor(Qt.PointingHandCursor)
        self._tags_close_btn.setToolTip(t("images.tags_popup_close"))
        self._tags_close_btn.setAccessibleName(t("common.close"))
        self._tags_close_btn.clicked.connect(self._hide_tags_popup)
        self._tags_header = self._build_section_header(
            t("images.tags"), icon_tags(), trailing=self._tags_close_btn
        )
        self._tags_header.setCursor(Qt.OpenHandCursor)
        self._tags_header.installEventFilter(self)
        for child in self._tags_header.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._tags_card_layout.addWidget(self._tags_header)

        self._tags_display_row = QWidget(self._tags_card)
        self._tags_display_row.setObjectName("tagsDisplayRow")
        tags_display_layout = QHBoxLayout(self._tags_display_row)
        tags_display_layout.setContentsMargins(2, 2, 2, 2)
        tags_display_layout.setSpacing(8)
        self._show_tags_checkbox = CapixeCheckBox(
            t("images.show_tags"), self._tags_display_row
        )
        self._show_tags_checkbox.setObjectName("imagesShowTagsCheckBox")
        self._show_tags_checkbox.setToolTip(t("images.show_tags_tooltip"))
        self._show_tags_checkbox.setChecked(
            bool(self._config.get("show_tags_in_image_list", False))
        )
        self._show_tags_checkbox.toggled.connect(self._on_show_tags_changed)
        tags_display_layout.addWidget(self._show_tags_checkbox, 1)
        self._tags_card_layout.addWidget(self._tags_display_row)
        self._tags_display_divider = QFrame(self._tags_card)
        self._tags_display_divider.setObjectName("sectionDivider")
        self._tags_display_divider.setFrameShape(QFrame.NoFrame)
        self._tags_display_divider.setFixedHeight(1)
        self._tags_card_layout.addWidget(self._tags_display_divider)

        self._tag_combo = TagPickerButton(self._tags_card)
        self._tag_combo.setFixedHeight(28)
        self._tag_combo.setPlaceholderText(t("images.tag.select_placeholder"))
        self._tag_combo.tag_selected.connect(self._on_tag_selected)
        self._tag_combo.new_tag_requested.connect(self._open_new_tag_dialog)
        self._tag_combo.tag_delete_requested.connect(self._confirm_delete_global_tag)
        self._tags_card_layout.addWidget(self._tag_combo)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self._tag_assign_btn = QPushButton(t("images.tag.add_button"), self._tags_card)
        self._tag_assign_btn.setProperty("tagPreviewControl", True)
        self._tag_assign_btn.setFixedHeight(28)
        self._tag_assign_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tag_assign_btn.setCursor(Qt.PointingHandCursor)
        self._tag_assign_btn.clicked.connect(self._on_assign_tag_from_popup)
        action_row.addWidget(self._tag_assign_btn, stretch=1)
        self._tags_card_layout.addLayout(action_row)

        self._current_tags_label = QLabel(t("images.tag.current"), self._tags_card)
        self._current_tags_label.setObjectName("currentTagsLabel")
        self._tags_card_layout.addWidget(self._current_tags_label)

        self._current_tags_scroll = QScrollArea(self._tags_card)
        self._current_tags_scroll.setObjectName("currentTagsScroll")
        self._current_tags_scroll.setWidgetResizable(True)
        self._current_tags_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._current_tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._current_tags_scroll.setMinimumHeight(36)
        self._current_tags_scroll.setMaximumHeight(160)
        self._current_tags_host = QWidget(self._current_tags_scroll)
        self._current_tags_host.setObjectName("currentTagsHost")
        self._tags_layout = FlowLayout(self._current_tags_host, spacing=6)
        self._tags_layout.setContentsMargins(0, 0, 0, 4)
        self._current_tags_scroll.setWidget(self._current_tags_host)
        self._tags_card_layout.addWidget(self._current_tags_scroll)

        self._tag_empty_hint = QLabel(t("images.tag.select_image_hint"), self._tags_card)
        self._tag_empty_hint.setObjectName("mutedLabel")
        self._tag_empty_hint.setWordWrap(True)
        self._tags_card_layout.addWidget(self._tag_empty_hint)

        self._information_card.setEnabled(False)
        self._info_widget = self._tags_card  # compatibility for existing callers/tests
        self._tags_card.hide()
        self._tags_popup_animation = None
        self._tags_user_placed = False
        self._tags_drag_origin = None
        self._tags_drag_geom = None
        self._tags_outside_filter_installed = False
        self._tags_click_filter = _TagsPopupEventFilter(self)
        self._tags_escape = QShortcut(QKeySequence(Qt.Key_Escape), self._tags_card)
        self._tags_escape.setContext(Qt.WidgetWithChildrenShortcut)
        self._tags_escape.activated.connect(self._hide_tags_popup)

        self._ask_ai_btn = QPushButton(t("images.ai.ask"), self._preview_page)
        self._ask_ai_btn.setObjectName("askAiButton")
        self._ask_ai_btn.setIcon(icon_ai_sparkle(size=14))
        self._ask_ai_btn.setIconSize(QSize(14, 14))
        self._ask_ai_btn.setCursor(Qt.PointingHandCursor)
        self._ask_ai_btn.setToolTip(t("images.ai.ask_tooltip"))
        self._ask_ai_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._ask_ai_btn.clicked.connect(self._show_ai_panel)
        preview_page_layout.addWidget(self._ask_ai_btn)
        preview_page_layout.addStretch(1)
        self._right_stack.addWidget(self._preview_page)

        self._ai_page = QWidget(self._right_stack)
        self._ai_page.setObjectName("aiModePage")
        self._ai_page.setAttribute(Qt.WA_StyledBackground, True)
        ai_outer = QVBoxLayout(self._ai_page)
        ai_outer.setContentsMargins(0, 0, 0, 0)
        ai_outer.setSpacing(0)
        self._ai_panel_card = QFrame(self._ai_page)
        self._ai_panel_card.setObjectName("askAiPanelCard")
        self._ai_panel_card.setAttribute(Qt.WA_StyledBackground, True)
        ai_page_layout = QVBoxLayout(self._ai_panel_card)
        ai_page_layout.setContentsMargins(
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
            WORKSPACE_PANEL_PADDING,
        )
        ai_page_layout.setSpacing(SPACE_2)
        self._preview_mode_btn = QPushButton("", self._ai_page)
        self._preview_mode_btn.setObjectName("aiPanelClose")
        self._preview_mode_btn.setIcon(icon_clear())
        self._preview_mode_btn.setIconSize(QSize(16, 16))
        self._preview_mode_btn.setFixedSize(CONTROL_STANDARD, CONTROL_STANDARD)
        self._preview_mode_btn.setCursor(Qt.PointingHandCursor)
        self._preview_mode_btn.setToolTip(t("common.close"))
        self._preview_mode_btn.setAccessibleName(t("common.close"))
        self._preview_mode_btn.setDefault(False)
        self._preview_mode_btn.setAutoDefault(False)
        self._preview_mode_btn.clicked.connect(self._show_preview_panel)
        self._ai_header = self._build_section_header(
            t("images.ai.panel_title"),
            icon_ai(muted=False),
            trailing=self._preview_mode_btn,
            title_row_height=CONTROL_STANDARD,
        )
        ai_page_layout.addWidget(self._ai_header)
        self._ask_ai_preview_hint = QLabel(
            t("images.ai.ui_preview_hint"), self._ai_page
        )
        self._ask_ai_preview_hint.setObjectName("askAiPreviewHint")
        self._ask_ai_preview_hint.setWordWrap(True)
        self._ask_ai_preview_hint.hide()
        ai_page_layout.addWidget(self._ask_ai_preview_hint)
        self._ai_history = AskAiChatView(self._ai_page)
        self._ai_history.set_start_action_handler(self._on_ask_ai_start_action)
        self._ai_history.set_restore_results_handler(self._restore_ask_ai_result_grid)
        self._ai_history.set_confirm_handlers(
            self._on_ask_ai_act_confirmed,
            self._on_ask_ai_act_cancelled,
            self._on_ask_ai_save_automation,
        )
        self._ai_history.set_chip_handler(self._on_ask_ai_chip)
        self._ai_history.set_sign_in_handler(self._on_ask_ai_sign_in)
        ai_page_layout.addWidget(self._ai_history, stretch=1)
        self._action_input_row.setParent(self._ai_page)
        self._action_input_row.show()
        self._action_input.show()
        self._action_preview_btn.show()
        ai_page_layout.addWidget(self._action_input_row)
        self._action_preview.setParent(self._ai_page)
        ai_page_layout.addWidget(self._action_preview)
        self._action_preview.hide()
        ai_outer.addWidget(self._ai_panel_card)
        self._right_stack.addWidget(self._ai_page)
        self._right_stack.setCurrentWidget(self._preview_page)
        self._ai_page.hide()

        self._splitter.addWidget(right_panel)
        self._right_panel = right_panel
        self._ai_panel = right_panel

        self._command_surface.setGraphicsEffect(None)
        self._search_shell.setGraphicsEffect(None)
        self._folder_browser.setGraphicsEffect(None)
        self._preview_card.setGraphicsEffect(None)
        # Keep preview column width stable — long filenames must not resize the list grid
        right_panel.setMinimumWidth(IMAGES_RIGHT_PANEL_MIN_WIDTH)
        right_panel.setMaximumWidth(IMAGES_RIGHT_PANEL_MAX_WIDTH)
        right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_panel.installEventFilter(self)
        self._folder_panel.setMinimumWidth(FOLDER_PANEL_MIN_EXPANDED)
        self._folder_panel.setMaximumWidth(FOLDER_PANEL_MAX_WIDTH)

        self._splitter.setChildrenCollapsible(True)
        # Transparent gutter — panels are separated by their own frames
        self._splitter.setHandleWidth(14)
        self._splitter.setSizes(
            [
                0,
                900,
                IMAGES_RIGHT_PANEL_DEFAULT_WIDTH,
            ]
        )
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        content_layout.addWidget(self._splitter, stretch=1)
        main_layout.addWidget(content, stretch=1)

        # Soft floor only — do not push the main window past Settings size
        page_root.setMinimumWidth(480)
        page_root.setMinimumHeight(320)

        self._populate_folder_tree()
        self._sync_primary_control_widths()
        self._update_actions_state(0)

    def _build_section_header(
        self,
        title: str,
        icon,
        *,
        leading: QWidget | None = None,
        trailing: QWidget | None = None,
        with_divider: bool = True,
        panel_header: bool = False,
        title_row_height: int = 28,
    ) -> QWidget:
        """Shared section header used by Folders / Screenshots / Preview / Tags."""
        wrap = QWidget(self)
        wrap.setObjectName("sectionHeader")
        layout = QVBoxLayout(wrap)
        side_margin = 4 if panel_header else 0
        layout.setContentsMargins(side_margin, 0, side_margin, 2)
        layout.setSpacing(6)

        # Fixed-height title row so Screenshots / Preview dividers share the same Y
        title_row = QWidget(wrap)
        title_row.setObjectName("sectionHeaderTitleRow")
        title_row.setFixedHeight(title_row_height)
        row = QHBoxLayout(title_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignVCenter)

        if leading is not None:
            row.addWidget(leading, 0, Qt.AlignVCenter)

        icon_label = QLabel(title_row)
        icon_label.setObjectName("sectionIcon")
        icon_label.setPixmap(icon.pixmap(SECTION_ICON_SIZE, SECTION_ICON_SIZE))
        row.addWidget(icon_label, 0, Qt.AlignVCenter)

        title_label = QLabel(title, title_row)
        title_label.setObjectName("sectionTitle")
        row.addWidget(title_label, 0, Qt.AlignVCenter)

        if trailing is not None:
            row.addStretch(1)
            row.addWidget(trailing, 0, Qt.AlignVCenter)
        else:
            row.addStretch(1)

        layout.addWidget(title_row)

        if with_divider:
            line = QFrame(wrap)
            line.setObjectName("sectionDivider")
            line.setFrameShape(QFrame.HLine)
            line.setFixedHeight(1)
            layout.addWidget(line)
        return wrap

    def _set_file_info_text(self, text: str) -> None:
        """Compatibility helper for multi-selection and cleared Preview state."""
        self._file_info_label.setPath(text)
        self._modified_info_label.setPath("-")
        self._folder_info_label.setPath("-")
        self._dimensions_info_label.setPath("-")
        self._size_info_label.setPath("-")
        if hasattr(self, "_tags_info_label"):
            self._tags_info_label.setPath("-")

    def _fit_file_info_font(self) -> None:
        for label in (
            self._file_info_label,
            self._modified_info_label,
            self._folder_info_label,
            self._dimensions_info_label,
            self._size_info_label,
            getattr(self, "_tags_info_label", None),
        ):
            if label is None:
                continue
            label._update_elided_text()

    def _set_image_information(self, file_path: Path) -> None:
        self._file_info_label.setPath(file_path.name)
        modified = "-"
        if file_path.exists():
            modified = datetime.fromtimestamp(file_path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        self._modified_info_label.setPath(modified)
        self._folder_info_label.setPath(str(file_path.parent))
        reader = QImageReader(str(file_path))
        image_size = reader.size()
        dimensions = "-"
        if image_size.isValid():
            dimensions = f"{image_size.width()} × {image_size.height()}"
        self._dimensions_info_label.setPath(dimensions)

        size_text = "-"
        if file_path.exists():
            byte_count = file_path.stat().st_size
            if byte_count < 1024:
                size_text = f"{byte_count} B"
            elif byte_count < 1024 * 1024:
                size_text = f"{byte_count / 1024:.1f} KB"
            else:
                size_text = f"{byte_count / (1024 * 1024):.1f} MB"
        self._size_info_label.setPath(size_text)
        if hasattr(self, "_tags_info_label"):
            tags = self._metadata_service.get_image_tags(file_path.parent, file_path.name)
            self._tags_info_label.setPath(format_tags(tags) if tags else t("images.tag.none"))

    def _toggle_folder_tree(self) -> None:
        self._apply_folder_tree_expanded(not self._folder_tree_expanded)

    def _apply_folder_tree_expanded(
        self, expanded: bool, *, persist: bool = True
    ) -> None:
        """Show/hide the folder body and let the image list reclaim width."""
        self._folder_tree_expanded = expanded

        # Expanded chrome (Viewing folder card) vs collapsed open-rail with ▶
        self._folder_header.setVisible(expanded)
        self._folder_body.setVisible(expanded)
        self._folder_collapse_btn.setVisible(expanded)
        if self._folder_header_icon is not None:
            self._folder_header_icon.setVisible(expanded)
        if self._folder_header_title is not None:
            self._folder_header_title.setVisible(expanded)
        if self._folder_header_divider is not None:
            self._folder_header_divider.setVisible(expanded)
        if hasattr(self, "_folder_project_hint"):
            self._folder_project_hint.setVisible(expanded)
        if hasattr(self, "_save_folder_legend"):
            self._save_folder_legend.setVisible(expanded)
        self._folder_expand_glyph.setVisible(not expanded)
        self._folder_expand_glyph.setText("▶")

        sizes = self._splitter.sizes()
        while len(sizes) < 3:
            sizes.append(200)

        layout = self._folder_panel.layout()

        def _set_stretch(widget: QWidget, stretch: int) -> None:
            if layout is None:
                return
            index = layout.indexOf(widget)
            if index >= 0:
                layout.setStretch(index, stretch)

        if expanded:
            if layout is not None:
                layout.setContentsMargins(10, 10, 10, 10)
                # Glyph must not keep stretch space while Viewing folder is open
                _set_stretch(self._folder_expand_glyph, 0)
                _set_stretch(self._folder_body, 1)
            self._folder_panel.setObjectName("folderPanel")
            self._folder_panel.setCursor(Qt.ArrowCursor)
            self._folder_panel.setToolTip("")
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
                layout.setContentsMargins(0, 0, 0, 0)
                _set_stretch(self._folder_expand_glyph, 1)
                _set_stretch(self._folder_body, 0)
            self._folder_panel.setObjectName("folderPanelCollapsed")
            self._folder_panel.setCursor(Qt.PointingHandCursor)
            self._folder_panel.setToolTip(t("images.expand_folders"))
            self._folder_panel.setMinimumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
            self._folder_panel.setMaximumWidth(FOLDER_PANEL_COLLAPSED_WIDTH)
            freed = max(0, sizes[0] - FOLDER_PANEL_COLLAPSED_WIDTH)
            sizes[0] = FOLDER_PANEL_COLLAPSED_WIDTH
            sizes[1] = sizes[1] + freed
            self._splitter.setSizes(sizes)

        # Refresh stylesheet after objectName change
        self._folder_panel.style().unpolish(self._folder_panel)
        self._folder_panel.style().polish(self._folder_panel)
        self._folder_panel.update()

        if persist:
            self._config["images_folder_tree_expanded"] = expanded
            try:
                save_config(self._config)
            except OSError:
                pass

    def _on_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        """Remember folder width so Screenshots resize doesn't permanently crush it."""
        self._sync_primary_control_widths()
        if not self._folder_tree_expanded:
            return
        sizes = self._splitter.sizes()
        if sizes and sizes[0] >= FOLDER_PANEL_MIN_EXPANDED:
            self._folder_panel_expanded_width = sizes[0]

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._set_folder_nav_filter(True)
        self._sync_primary_control_widths()

    def hideEvent(self, event) -> None:
        self._set_folder_nav_filter(False)
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        from app.ui.page_motion import stop_page_fade

        if hasattr(self, "_right_stack"):
            stop_page_fade(self._right_stack)
        self._sync_primary_control_widths()
        if hasattr(self, "_tags_card") and self._tags_card.isVisible():
            self._sync_tags_popup_geometry()

    def _sync_primary_control_widths(self) -> None:
        if not hasattr(self, "_command_surface"):
            return
        # Folder context spans the command surface; Search remains usable on its
        # own row even at the minimum window width.
        self._folder_selector.setMinimumWidth(0)
        self._folder_selector.setMaximumWidth(16777215)
        self._search_row.setMinimumWidth(0)

    def _setup_shortcuts(self) -> None:
        """Explorer-like keyboard shortcuts for the Images page."""
        bindings = [
            (QKeySequence.Find, self._focus_search),
            (QKeySequence(Qt.Key_Escape), self._on_escape),
            (QKeySequence.SelectAll, self._select_all_images),
            (QKeySequence.Copy, self._shortcut_copy),
            (QKeySequence.Cut, self._shortcut_cut),
            (QKeySequence.Paste, self._shortcut_paste),
            (QKeySequence.Delete, self._shortcut_delete),
            (QKeySequence(Qt.Key_F2), self._shortcut_rename),
            (QKeySequence(Qt.Key_Space), self._shortcut_quick_preview),
            (QKeySequence.Undo, self._undo_last_action),
            (QKeySequence(Qt.Key_Backspace), self._shortcut_folder_back),
            (QKeySequence(Qt.ALT | Qt.Key_Left), self._shortcut_folder_back),
            (QKeySequence(Qt.ALT | Qt.Key_Right), self._shortcut_folder_forward),
        ]
        for sequence, slot in bindings:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    def _file_shortcut_focus_ok(self) -> bool:
        """Avoid stealing Ctrl+C/X/V from text fields."""
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

    def _shortcut_folder_back(self) -> None:
        if self._file_shortcut_focus_ok():
            self._navigate_folder_back()

    def _shortcut_folder_forward(self) -> None:
        if self._file_shortcut_focus_ok():
            self._navigate_folder_forward()

    def _focus_search(self) -> None:
        self._search_input.setFocus(Qt.ShortcutFocusReason)
        self._search_input.selectAll()

    def _setup_fs_watcher(self) -> None:
        """Watch screenshot root + current folder for Explorer-side changes."""
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_debounce = QTimer(self)
        self._fs_debounce.setSingleShot(True)
        self._fs_debounce.setInterval(FS_WATCH_DEBOUNCE_MS)
        self._fs_debounce.timeout.connect(self._on_fs_change_debounced)
        self._fs_watcher.directoryChanged.connect(self._schedule_fs_refresh)
        self._fs_signature = None
        self._fs_signature_timer = QTimer(self)
        self._fs_signature_timer.setInterval(FS_SIGNATURE_POLL_MS)
        self._fs_signature_timer.timeout.connect(self._poll_folder_signature)
        self._fs_signature_timer.start()
        self._resync_fs_watcher()
        self._fs_signature = self._folder_signature()

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

    def _folder_signature(self) -> tuple[tuple[str, int, int], ...] | None:
        folder_dir = self._get_folder_dir()
        if not folder_dir.exists():
            return None
        entries: list[tuple[str, int, int]] = []
        try:
            for path in self._get_png_files(folder_dir):
                stat = path.stat()
                entries.append((path.name, int(stat.st_size), int(stat.st_mtime_ns)))
        except OSError:
            return None
        entries.sort()
        return tuple(entries)

    def _poll_folder_signature(self) -> None:
        if self._fs_refreshing or self._updating_folder_ui:
            return
        signature = self._folder_signature()
        if signature is None:
            return
        if self._fs_signature is None:
            self._fs_signature = signature
            return
        if signature != self._fs_signature:
            self._schedule_fs_refresh()

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
        if "selected_folder" in self._config:
            self._metadata_service.invalidate_cache()
            self._apply_thumbnail_mode()
            self.reload_tag_choices()
            self._load_images(force_reload_metadata=True)
            self._resync_fs_watcher()
            self._apply_cut_visuals()
            self._update_selected_folder_ui()
            self._fs_signature = self._folder_signature()
            self._refresh_analysis_preview(force=True)
            return
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
        self._update_selected_folder_ui()
        self._fs_signature = self._folder_signature()
        self._refresh_analysis_preview(force=True)

    def _targets_from_paths(self, paths: list[Path] | tuple[Path, ...]) -> tuple[ActionTarget, ...]:
        return tuple(ActionTarget(path=str(Path(path))) for path in paths)

    def _action_ocr(self):
        controller = self._analysis_controller
        if controller is None:
            return None, None
        repo = getattr(controller, "ocr_repository", None)
        if repo is not None:
            return repo, None
        try:
            database = OCRDatabase().open()
            return OCRRepository(database), database
        except OCRDatabaseError:
            return None, None

    def _execute_action(self, request: ActionRequest, *, confirmed: bool = True):
        ocr, database = self._action_ocr()
        try:
            return ActionService(
                ActionContext(
                    metadata=self._metadata_service,
                    ocr=ocr,
                    app_root=self._app_root,
                )
            ).execute(request, confirmed=confirmed)
        finally:
            if database is not None:
                database.close()

    def _action_error_code(self, result) -> str:
        for item in result.items:
            if item.error:
                return str(item.error)
        for found in result.issues:
            if found.severity == "error":
                return str(found.code or found.message)
        return ""

    def _undo_moves_from_result(self, result) -> list[dict[str, str]]:
        moves: list[dict[str, str]] = []
        for item in result.items:
            if item.status != "success":
                continue
            source = item.before.get("path")
            dest = item.after.get("path")
            if not source or not dest:
                continue
            moves.append(
                {
                    "from": str(Path(source).resolve()),
                    "to": str(Path(dest).resolve()),
                    "source_project": str(Path(source).resolve().parent),
                }
            )
            self._thumbnail_cache.invalidate(Path(source))
        return moves

    def _show_action_failure(self, result, fallback_key: str) -> None:
        code = self._action_error_code(result)
        mapped = {
            "folder_exists": "images.folder.exists",
            "invalid_folder_name": "images.folder.name_invalid",
            "parent_missing": "images.folder.missing",
            "name_conflict": "images.rename_exists",
            "invalid_filename": "images.rename_invalid",
            "reserved_name": "images.rename_invalid",
            "source_missing": "images.folder.missing",
        }.get(code)
        if mapped in {"images.folder.exists", "images.folder.name_invalid", "images.folder.missing", "images.rename_exists", "images.rename_invalid"}:
            QMessageBox.warning(self, t("common.warning"), t(mapped))
            return
        QMessageBox.critical(self, t("common.error"), t(fallback_key, error=code or result.status))

    # ---- public API ----

    def refresh(self, *, defer_thumbnails: bool = False) -> None:
        """Reload folders, images, and display settings."""
        started = time.perf_counter()
        logger.info("Images library load start defer_thumbnails=%s", defer_thumbnails)
        self._show_tags_checkbox.blockSignals(True)
        self._show_tags_checkbox.setChecked(
            bool(self._config.get("show_tags_in_image_list", False))
        )
        self._show_tags_checkbox.blockSignals(False)
        self._update_selected_folder_ui()
        self._metadata_service.invalidate_cache(self._get_folder_dir())
        self._load_display_settings_from_project()
        self._populate_folder_tree()
        self._apply_thumbnail_mode()
        self.reload_tag_choices()
        self._load_images(
            force_reload_metadata=True,
            defer_thumbnails=defer_thumbnails,
        )
        self._resync_fs_watcher()
        self._apply_cut_visuals(defer_uncut_thumbnails=defer_thumbnails)
        self._fs_signature = self._folder_signature()
        self._refresh_analysis_preview()
        logger.info(
            "Images library load end defer_thumbnails=%s elapsed_ms=%.1f",
            defer_thumbnails,
            (time.perf_counter() - started) * 1000,
        )

    def on_folder_changed(self) -> None:
        """Called when the active folder changes externally."""
        self._cancel_semantic_index()
        self._reset_ask_ai_folder_prep()
        self._preview_cache_path = None
        self._clear_preview()
        self.refresh()

    def _on_analysis_completed(self) -> None:
        self._refresh_analysis_preview(force=True)
        if self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)

    def _on_analysis_summary_changed(self, summary: object) -> None:
        data = summary if isinstance(summary, dict) else {}
        names = data.get("pending_names", set())
        self._unanalyzed_names = set(names) if names else set()
        details = data.get("details", {})
        self._analysis_details = details if isinstance(details, dict) else {}
        if self._analysis_details:
            self._unanalyzed_names = {
                name: value.get("display_status", value.get("semantic_status", ""))
                for name, value in self._analysis_details.items()
            }
        if self._group_by == GROUP_BY_ANALYSIS:
            self._load_images()

    def _on_library_prep_changed(self, snapshot: object) -> None:
        if not hasattr(self, "_library_prep_label"):
            return
        data = snapshot if isinstance(snapshot, dict) else {}
        text = str(data.get("text") or "").strip()
        state = str(data.get("state") or "hidden")
        if state == "hidden" or not text:
            self._library_prep_label.hide()
            self._library_prep_label.clear()
            self._library_prep_label.setToolTip("")
            return
        self._library_prep_label.setText(text)
        self._library_prep_label.setToolTip(str(data.get("hint") or ""))
        self._library_prep_label.show()

    def reanalyze_library(self) -> None:
        """Settings/maintenance entry point for unresolved local analysis."""
        if self._analysis_bar is None:
            return
        self._analysis_bar.start_analysis()

    def _refresh_analysis_preview(self, *, force: bool = False) -> None:
        if self._analysis_bar is None:
            return
        folder = self._get_folder_dir()
        self._analysis_bar.set_folder(
            folder if folder.exists() else None,
            force=force,
        )

    def reload_tag_choices(self) -> None:
        """Reload global tags without changing the active Preview image."""
        if not hasattr(self, "_tag_combo"):
            return
        selected_tag = self._selected_tag_from_combo()
        self._tag_combo.blockSignals(True)
        self._tag_combo.clear()
        for tag in self._metadata_service.load_global_tags(
            self._app_root, force_reload=True
        ):
            self._tag_combo.addItem(format_tag(tag), tag)
        self._tag_combo.setCurrentIndex(self._tag_combo.findData(selected_tag))
        self._tag_combo.blockSignals(False)
        self._update_tag_action_state()

    def _on_tag_selected(self, _tag: str) -> None:
        self._update_tag_action_state()

    def add_saved_image(self, saved_path: Path) -> None:
        self._add_image_to_list(saved_path)
        self._fs_signature = self._folder_signature()
        self._refresh_analysis_preview(force=True)

    def select_image_path(self, path_str: str) -> None:
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item.data(Qt.UserRole) == path_str:
                self._list_widget.setCurrentItem(item)
                self._on_item_clicked(item)
                return

    # ---- paths / folders ----

    def _update_selected_folder_ui(self) -> None:
        path, state = selected_folder_state(self._config, self._app_root)
        text = str(path) if path is not None else t("images.folder_unselected")
        self._selected_folder_value.setPath(text)
        self._folder_breadcrumb.set_path(path if state == "ready" else None)
        self._folder_breadcrumb.hide()
        is_fav = bool(path) and is_favorite_folder(self._config, path)
        self._favorite_folder_btn.setIcon(icon_pin(filled=is_fav))
        self._favorite_folder_btn.setToolTip(
            t("images.favorite_folder_remove") if is_fav else t("images.favorite_folder_add")
        )
        self._favorite_folder_btn.setAccessibleName(
            t("images.favorite_folder_remove") if is_fav else t("images.favorite_folder_add")
        )
        self._favorite_folder_btn.setProperty("favorited", is_fav)
        self._favorite_folder_btn.style().unpolish(self._favorite_folder_btn)
        self._favorite_folder_btn.style().polish(self._favorite_folder_btn)
        self._favorite_folder_btn.setEnabled(state == "ready")
        self._update_folder_up_button()
        if state == "unselected":
            self._list_empty_title.setText(t("images.folder_unselected"))
            self._list_empty_body.setText(t("images.folder_unselected_body"))
        elif state == "missing":
            self._list_empty_title.setText(t("images.folder_missing"))
            self._list_empty_body.setText(str(path))
        else:
            self._list_empty_title.setText(t("images.empty_title"))
            self._list_empty_body.setText(t("images.empty_body"))
        self._refresh_child_folders()

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
        self.open_folder(selected)

    def open_folder(self, folder: str | Path) -> None:
        if not self._navigating_history:
            self._folder_forward_stack.clear()
        path = set_selected_folder(self._config, folder)
        remember_recent_folder(self._config, path)
        save_config(self._config)
        self._cancel_semantic_index()
        self._reset_ask_ai_folder_prep()
        self._isolate_ask_ai_search()
        self._clear_ask_ai_grid()
        self._workspace.reset(scope_folder=path)
        self._cancel_search_tasks()
        self._search_request_id += 1
        self._search_debounce.stop()
        self._active_search_query = ""
        self._search_input.clear()
        self._preview_cache_path = None
        self._clear_preview()
        self.refresh()
        self.folder_changed.emit(str(path))
        self.folder_shortcuts_changed.emit()
        emit_tour_event(UI_FOLDER_SELECTED, generation=tour_event_generation())

    def _toggle_current_folder_favorite(self) -> None:
        path = get_selected_folder(self._config, self._app_root)
        if path is None or not path.exists():
            return
        toggle_favorite_folder(self._config, path)
        save_config(self._config)
        self._update_selected_folder_ui()
        self.folder_shortcuts_changed.emit()

    def _refresh_child_folders(self) -> None:
        if not hasattr(self, "_child_folders"):
            return
        # Child folders now live in the image grid. Keep the chip row hidden
        # so existing callers/tests can still inspect `_child_folders`.
        path, state = selected_folder_state(self._config, self._app_root)
        children = list_child_folders(path) if state == "ready" else []
        self._child_folders.clear()
        for child in children:
            self._child_folders.addItem(FolderChipItem(child.name, str(child)))
        self._child_folders.finish()
        self._child_folders.hide()
        if hasattr(self, "_folder_browser_divider"):
            self._folder_browser_divider.hide()
        self._update_folder_up_button()

    def _current_child_folders(self) -> list[Path]:
        path, state = selected_folder_state(self._config, self._app_root)
        if state != "ready":
            return []
        return list_child_folders(path)

    def _parent_folder_path(self) -> Path | None:
        path, state = selected_folder_state(self._config, self._app_root)
        if state != "ready" or path is None:
            return None
        parent = path.parent
        if parent == path:
            return None
        return parent

    def _update_folder_up_button(self) -> None:
        if not hasattr(self, "_folder_up_btn"):
            return
        parent = self._parent_folder_path()
        enabled = parent is not None
        self._folder_up_btn.setEnabled(enabled)
        if enabled:
            self._folder_up_btn.setToolTip(
                t("images.folder_up_tooltip") + f"\n{parent}"
            )
        else:
            self._folder_up_btn.setToolTip(t("images.folder_up_tooltip"))

    def _go_to_parent_folder(self) -> None:
        self._navigate_folder_back()

    def _open_folder_from_history(self, folder: str | Path) -> None:
        self._navigating_history = True
        try:
            self.open_folder(folder)
        finally:
            self._navigating_history = False

    def _navigate_folder_back(self) -> None:
        current, state = selected_folder_state(self._config, self._app_root)
        parent = self._parent_folder_path()
        if parent is None:
            return
        if state == "ready" and current is not None:
            resolved = current.resolve()
            if not self._folder_forward_stack or self._folder_forward_stack[-1] != resolved:
                self._folder_forward_stack.append(resolved)
        self._open_folder_from_history(parent)

    def _navigate_folder_forward(self) -> None:
        while self._folder_forward_stack:
            target = self._folder_forward_stack.pop()
            if target.exists() and target.is_dir():
                self._open_folder_from_history(target)
                return

    def _cleanup_folder_nav_filter(self, *_args) -> None:
        try:
            self._set_folder_nav_filter(False)
        except (RuntimeError, AttributeError):
            pass

    def _set_folder_nav_filter(self, enabled: bool) -> None:
        app = QApplication.instance()
        if app is None:
            return
        if enabled and not self._folder_nav_filter_installed:
            app.installEventFilter(self._folder_nav_filter)
            self._folder_nav_filter_installed = True
        elif not enabled and self._folder_nav_filter_installed:
            try:
                app.removeEventFilter(self._folder_nav_filter)
            except RuntimeError:
                pass
            self._folder_nav_filter_installed = False

    def _event_targets_folder_nav(self, obj) -> bool:
        if not isinstance(obj, QWidget) and not isinstance(obj, QObject):
            return False
        widget = obj if isinstance(obj, QWidget) else getattr(obj, "parent", lambda: None)()
        if not isinstance(widget, QWidget):
            return False
        tags = getattr(self, "_tags_card", None)
        current: QWidget | None = widget
        while current is not None:
            if current is self or current is tags:
                return True
            current = current.parentWidget()
        return False

    def _on_child_folder_clicked(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.UserRole)
        if target:
            self.open_folder(target)

    def _get_screenshot_root(self) -> Path:
        selected = get_selected_folder(self._config, self._app_root)
        if "selected_folder" in self._config:
            return selected or (self._app_root / "__unselected_folder__")
        path_obj = Path(self._config.get("screenshot_dir", "screenshots"))
        if not path_obj.is_absolute():
            path_obj = (self._app_root / path_obj).resolve()
        return path_obj.resolve()

    def _get_folder_dir(self) -> Path:
        """Directory that holds images + .sstool for the current folder."""
        selected = get_selected_folder(self._config, self._app_root)
        if "selected_folder" in self._config:
            return selected or (self._app_root / "__unselected_folder__")
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
        if "selected_folder" in self._config:
            return
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
                font.setWeight(QFont.Weight.DemiBold)
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
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_CREATE_FOLDER,
                    parameters={
                        "parent_path": str(self._get_screenshot_root()),
                        "name": name,
                    },
                )
            )
            if result.status != "success":
                self._show_action_failure(result, "images.folder.create_failed")
                return
            folder_dir = Path(result.items[0].after.get("path") or folder_dir)
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
            self._cancel_semantic_index()
            self._reset_ask_ai_folder_prep()
            self._isolate_ask_ai_search()
            self._clear_ask_ai_grid()
            self._load_display_settings_from_project()
            self._populate_folder_tree()
            self._apply_thumbnail_mode()
            self._load_images(force_reload_metadata=True)
            self._resync_fs_watcher()
            self._apply_cut_visuals()

            self.folder_changed.emit(folder_name)
            emit_tour_event(UI_FOLDER_SELECTED, generation=tour_event_generation())
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
                result = self._execute_action(
                    ActionRequest(
                        action_id=ACTION_MOVE,
                        targets=self._targets_from_paths(paths),
                        parameters={"destination_path": str(dest_dir)},
                    )
                )
                moves = self._undo_moves_from_result(result)
                if result.failed and not result.succeeded:
                    self._show_action_failure(result, "images.dnd.move_failed")
                    return
                if not moves:
                    return
                self._push_undo(
                    UndoRecord(kind=UNDO_DND_MOVE, payload={"moves": moves})
                )
                if result.failed:
                    self._show_action_failure(result, "images.dnd.move_failed")

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
        display = {}
        if project_dir.exists():
            project = self._metadata_service.load_project(project_dir)
            display, migrated = migrate_legacy_display(project.get("display", {}))
            self._thumbnail_mode = "small"
            self._gallery_layout = normalize_gallery_layout(display.get("gallery_layout"))
            arrangement = arrangement_from_display(display)
            if migrated or display.get(IMAGES_SORT_KEY) not in VALID_IMAGES_SORT_MODES:
                display[IMAGES_SORT_KEY] = arrangement
                project["display"] = display
                try:
                    self._metadata_service.save_project(project_dir, project)
                except OSError:
                    pass
        else:
            self._thumbnail_mode = "small"
            self._gallery_layout = DEFAULT_GALLERY_LAYOUT
            arrangement = DEFAULT_IMAGES_SORT
            display = {}

        self._apply_images_arrangement(arrangement, persist=False)

        self._view_combo.blockSignals(True)
        view_index = self._view_combo.findData(self._thumbnail_mode)
        self._view_combo.setCurrentIndex(view_index if view_index >= 0 else 0)
        self._view_combo.blockSignals(False)
        if hasattr(self, "_layout_toggle"):
            blocked = self._layout_toggle.blockSignals(True)
            self._layout_toggle.set_current(1 if self._gallery_layout == "list" else 0)
            self._layout_toggle.blockSignals(blocked)

    def _apply_images_arrangement(self, arrangement: str, *, persist: bool) -> None:
        arrangement = normalize_images_sort(arrangement)
        file_sort, group_by, filter_mode = expand_images_sort(arrangement)
        self._images_sort = arrangement
        self._sort_mode = file_sort
        self._group_by = group_by
        self._filter_mode = filter_mode

        self._sort_combo.blockSignals(True)
        index = self._sort_combo.findData(arrangement)
        self._sort_combo.setCurrentIndex(index if index >= 0 else 0)
        self._sort_combo.blockSignals(False)

        self._filter_combo.blockSignals(True)
        filter_index = self._filter_combo.findData(filter_mode)
        self._filter_combo.setCurrentIndex(filter_index if filter_index >= 0 else 0)
        self._filter_combo.blockSignals(False)

        self._group_combo.blockSignals(True)
        group_index = self._group_combo.findData(group_by)
        self._group_combo.setCurrentIndex(group_index if group_index >= 0 else 0)
        self._group_combo.blockSignals(False)

        if persist:
            self._save_display_settings({IMAGES_SORT_KEY: arrangement})

    def _save_display_setting(self, key: str, value) -> None:
        self._save_display_settings({key: value})

    def _save_display_settings(self, updates: dict) -> None:
        project_dir = self._get_folder_dir()
        project_dir.mkdir(parents=True, exist_ok=True)
        project = self._metadata_service.load_project(project_dir)
        if "display" not in project:
            project["display"] = {}
        project["display"].update(updates)
        project["display"][DISPLAY_SCHEMA_KEY] = DISPLAY_SCHEMA_VERSION
        self._metadata_service.save_project(project_dir, project)

    def _on_sort_changed(self) -> None:
        arrangement = normalize_images_sort(self._sort_combo.currentData())
        try:
            self._apply_images_arrangement(arrangement, persist=True)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.sort_save_failed", error=e)
            )
            return
        self._load_images()

    def _on_filter_changed(self) -> None:
        filter_mode = normalize_filter_mode(self._filter_combo.currentData())
        self._filter_mode = filter_mode
        try:
            self._save_display_setting("filter_mode", filter_mode)
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

    def _on_view_combo_changed(self) -> None:
        self._set_thumbnail_mode(normalize_thumbnail_mode(self._view_combo.currentData()))

    def _on_show_tags_changed(self, checked: bool) -> None:
        enabled = bool(checked)
        if bool(self._config.get("show_tags_in_image_list", False)) == enabled:
            return
        self._config["show_tags_in_image_list"] = enabled
        try:
            save_config(self._config)
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.show_tags_save_failed", error=e)
            )
            self._show_tags_checkbox.blockSignals(True)
            self._show_tags_checkbox.setChecked(not enabled)
            self._show_tags_checkbox.blockSignals(False)
            self._config["show_tags_in_image_list"] = not enabled
            return
        self._apply_thumbnail_mode()
        self._load_images()

    def _on_gallery_layout_changed(self, index: int) -> None:
        if not hasattr(self, "_list_widget"):
            return
        layout = "list" if index == 1 else "grid"
        self._set_gallery_layout(layout)

    def _set_gallery_layout(self, layout: str) -> None:
        layout = normalize_gallery_layout(layout)
        self._gallery_layout = layout
        if hasattr(self, "_layout_toggle"):
            blocked = self._layout_toggle.blockSignals(True)
            self._layout_toggle.set_current(1 if layout == "list" else 0)
            self._layout_toggle.blockSignals(blocked)
        try:
            self._save_display_setting("gallery_layout", layout)
        except OSError:
            pass
        self._apply_thumbnail_mode()
        self._load_images()

    def _show_view_menu(self) -> None:
        menu = QMenu(self)
        group_menu = menu.addMenu(t("images.group_by_label"))
        group = QActionGroup(menu)
        group.setExclusive(True)
        for mode, label in group_by_option_labels(include_analysis=True):
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(mode == self._group_by)
            action.triggered.connect(
                lambda _checked=False, value=mode: self._apply_group_by_from_menu(value)
            )
            group.addAction(action)
            group_menu.addAction(action)
        tags_action = QAction(t("images.actions.tags"), menu)
        tags_action.triggered.connect(self._show_tags_popup)
        menu.addAction(tags_action)
        menu.exec(self._view_menu_btn.mapToGlobal(self._view_menu_btn.rect().bottomLeft()))

    def _apply_group_by_from_menu(self, mode: str) -> None:
        index = self._group_combo.findData(mode)
        if index >= 0:
            self._group_combo.setCurrentIndex(index)

    def _set_thumbnail_mode(self, mode: str) -> None:
        mode = normalize_thumbnail_mode(mode)
        self._thumbnail_mode = mode
        if hasattr(self, "_view_combo"):
            self._view_combo.blockSignals(True)
            idx = self._view_combo.findData(mode)
            self._view_combo.setCurrentIndex(idx if idx >= 0 else 0)
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
        self._load_images()

    def _is_folder_expand_click_target(self, obj) -> bool:
        return obj is self._folder_panel

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_tags_header", None) and self._handle_tags_header_drag(obj, event):
            return True
        if obj is getattr(self, "_search_input", None) and event.type() in (
            QEvent.Type.FocusIn,
            QEvent.Type.FocusOut,
        ):
            shell = getattr(self, "_search_shell", None)
            if shell is not None:
                shell.setProperty("focused", event.type() == QEvent.Type.FocusIn)
                style = shell.style()
                if style is not None:
                    style.unpolish(shell)
                    style.polish(shell)
                shell.update()
        if (
            getattr(self, "_folder_tree_expanded", True) is False
            and self._is_folder_expand_click_target(obj)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.LeftButton
        ):
            self._apply_folder_tree_expanded(True)
            return True
        if event.type() == QEvent.Type.Resize:
            if obj is self._list_widget.viewport():
                self._relayout_gallery_grid()
            elif obj is self._list_panel:
                self._apply_header_tools_layout()
            elif obj is self._right_panel:
                self._fit_file_info_font()
        return super().eventFilter(obj, event)

    def _apply_header_tools_layout(self, *, force: bool = False) -> None:
        """Keep Sort / Group / View on a dedicated row (never clip the title)."""
        if not hasattr(self, "_header_tools"):
            return
        self._header_tools_inline = False
        self._header_tools_row.show()
        self._header_tools.show()
        self._sort_label.show()
        self._filter_label.hide()
        self._layout_label.hide()
        self._group_label.hide()
        self._view_label.hide()
        wide = self._list_panel.width() >= HEADER_TOOLS_INLINE_MIN_WIDTH
        self._tune_header_tools_sizes(wide)

    def _tune_header_tools_sizes(self, wide: bool) -> None:
        """Roomier combos when the list column is wide; compact when narrow."""
        panel_width = self._list_panel.width()
        self._sort_label.show()
        self._filter_label.hide()
        self._layout_label.hide()
        self._group_label.hide()
        self._view_label.hide()
        if wide:
            self._sort_combo.setMinimumWidth(110)
            self._sort_combo.setMaximumWidth(160)
            self._group_combo.setMinimumWidth(64)
            self._group_combo.setMaximumWidth(90)
            self._view_combo.setMinimumWidth(64)
            self._view_combo.setMaximumWidth(90)
        elif panel_width >= 300:
            self._sort_combo.setMinimumWidth(96)
            self._sort_combo.setMaximumWidth(140)
            self._group_combo.setMinimumWidth(56)
            self._group_combo.setMaximumWidth(80)
            self._view_combo.setMinimumWidth(56)
            self._view_combo.setMaximumWidth(80)
        else:
            self._sort_combo.setMinimumWidth(72)
            self._sort_combo.setMaximumWidth(96)
            self._group_combo.setMinimumWidth(44)
            self._group_combo.setMaximumWidth(60)
            self._view_combo.setMinimumWidth(44)
            self._view_combo.setMaximumWidth(60)

    def _apply_thumbnail_mode(self) -> None:
        if self._caption_delegate is None:
            self._caption_delegate = CaptionIconDelegate(
                show_selection_badge=True,
                pastel_emphasis=False,
                parent=self._list_widget,
            )
            self._caption_delegate.favorite_clicked.connect(self._on_favorite_star_clicked)
            self._list_widget.setItemDelegate(self._caption_delegate)
        else:
            self._caption_delegate._show_selection_badge = True

        list_layout = is_list_mode(self._gallery_layout)
        show_tags = bool(self._config.get("show_tags_in_image_list", False))
        self._caption_delegate.set_list_mode(list_layout)
        self._caption_delegate.set_show_tags(show_tags)
        self._list_widget.setProperty("captionMode", "list" if list_layout else "icon")
        self._list_widget.setViewMode(QListWidget.IconMode)
        self._list_widget.setMovement(QListWidget.Static)
        if list_layout:
            self._list_widget.setFlow(QListWidget.TopToBottom)
            self._list_widget.setWrapping(False)
        else:
            self._list_widget.setFlow(QListWidget.LeftToRight)
            self._list_widget.setWrapping(True)
        self._list_widget.setResizeMode(QListWidget.Adjust)
        self._list_widget.setGridSize(QSize())
        self._list_widget.setSpacing(
            4 if list_layout else THUMBNAIL_LIST_SPACING
        )
        self._list_widget.setWordWrap(True)
        self._list_widget.setUniformItemSizes(False)
        self._list_widget.setTextElideMode(Qt.ElideNone)
        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list_widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._list_widget.configure_explorer_selection()
        self._list_widget.configure_drag_export_only()

        style = self._list_widget.style()
        style.unpolish(self._list_widget)
        style.polish(self._list_widget)
        self._gallery_layout_key = None
        self._update_gallery_card_geometry()
        self._refresh_gallery_item_hints()
        self._list_widget.update()

    def _gallery_viewport_width(self) -> int:
        viewport_w = self._list_widget.viewport().width()
        if viewport_w < 32:
            return max(self._list_widget.width() - 8, 280)
        return viewport_w

    def _gallery_scrollbar_reserve(self) -> int:
        vbar = self._list_widget.verticalScrollBar()
        if vbar is None or vbar.isVisible():
            return 0
        return max(vbar.sizeHint().width(), 0)

    def _responsive_grid_metrics(self) -> tuple[int, int, int]:
        min_card = THUMBNAIL_MODE_SIZES[self._thumbnail_mode][1]
        return compute_responsive_grid(
            self._gallery_viewport_width(),
            min_card,
            reserve_scrollbar=self._gallery_scrollbar_reserve(),
        )

    def _update_gallery_card_geometry(self) -> None:
        list_layout = is_list_mode(self._gallery_layout)
        icon_size = self._current_icon_size()
        grid_w, grid_h = self._current_card_size()
        media_w, media_h = self._grid_media_logical_size()
        header_w = self._header_row_width()
        if self._caption_delegate is not None:
            self._caption_delegate.set_geometry(
                icon_size, grid_w, grid_h, header_width=header_w
            )
        if list_layout:
            self._list_widget.setIconSize(QSize(icon_size, icon_size))
        else:
            self._list_widget.setIconSize(QSize(media_w, media_h))
        self._gallery_layout_key = (
            self._gallery_viewport_width(),
            self._thumbnail_mode,
            self._gallery_layout,
            bool(self._config.get("show_tags_in_image_list", False)),
            self._group_by,
            grid_w,
            header_w,
        )

    def _relayout_gallery_grid(self) -> None:
        if not hasattr(self, "_list_widget") or self._caption_delegate is None:
            return
        list_layout = is_list_mode(self._gallery_layout)
        if list_layout:
            grid_w, grid_h = self._current_card_size()
            header_w = self._header_row_width()
            key = (
                self._gallery_viewport_width(),
                "list",
                grid_w,
                grid_h,
                header_w,
                bool(self._config.get("show_tags_in_image_list", False)),
            )
        else:
            columns, card_w, header_w = self._responsive_grid_metrics()
            key = (
                self._gallery_viewport_width(),
                self._thumbnail_mode,
                self._gallery_layout,
                bool(self._config.get("show_tags_in_image_list", False)),
                self._group_by,
                columns,
                card_w,
                header_w,
            )
        if key == getattr(self, "_gallery_layout_key", None):
            return
        self._update_gallery_card_geometry()
        self._refresh_gallery_item_hints()
        self._list_widget.doItemsLayout()
        self._list_widget.update()

    def _refresh_gallery_item_hints(self) -> None:
        grid_w, grid_h = self._current_card_size()
        header_w = self._header_row_width()
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None:
                continue
            if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                item.setSizeHint(QSize(header_w, GROUP_HEADER_HEIGHT))
            else:
                item.setSizeHint(QSize(grid_w, grid_h))

    def _header_row_width(self) -> int:
        if is_list_mode(self._gallery_layout):
            return max(self._gallery_viewport_width() - 8, 280)
        _columns, _card_w, header_w = self._responsive_grid_metrics()
        return header_w

    def _refresh_header_widths(self) -> None:
        self._refresh_gallery_item_hints()

    def _current_icon_size(self) -> int:
        key = "list" if is_list_mode(self._gallery_layout) else self._thumbnail_mode
        return THUMBNAIL_MODE_SIZES[key][0]

    def _shows_tags_in_list(self) -> bool:
        return bool(self._config.get("show_tags_in_image_list", False))

    def _grid_media_logical_size(self) -> tuple[int, int]:
        card_w, card_h = self._current_card_size()
        inner = QRect(0, 0, card_w, card_h).adjusted(
            CARD_INSET, CARD_INSET, -CARD_INSET, -CARD_INSET
        )
        media = media_rect_for_card(inner, self._shows_tags_in_list())
        return max(media.width(), 1), max(media.height(), 1)

    def _thumbnail_pixel_size(self) -> tuple[int, int]:
        widget = getattr(self, "_list_widget", None)
        dpr = 1.0
        if widget is not None:
            dpr = max(1.0, float(widget.devicePixelRatioF()))
        scale = max(dpr, 2.0)
        if is_list_mode(self._gallery_layout):
            side = max(1, int(round(self._current_icon_size() * scale)))
            return side, side
        media_w, media_h = self._grid_media_logical_size()
        return (
            min(512, max(1, int(round(media_w * scale)))),
            min(512, max(1, int(round(media_h * scale)))),
        )

    def _thumbnail_icon(self, file_path: Path):
        width, height = self._thumbnail_pixel_size()
        return self._thumbnail_cache.get_icon(file_path, width=width, height=height)

    def _current_card_size(self) -> tuple[int, int]:
        if is_list_mode(self._gallery_layout):
            grid_h = THUMBNAIL_MODE_SIZES["list"][2]
            if self._shows_tags_in_list():
                grid_h += TAG_CAPTION_ROW_HEIGHT
            return max(self._gallery_viewport_width() - 8, 280), grid_h
        _columns, card_w, _header_w = self._responsive_grid_metrics()
        grid_h = THUMBNAIL_MODE_SIZES[self._thumbnail_mode][2]
        if self._shows_tags_in_list():
            grid_h += TAG_CAPTION_ROW_HEIGHT
        return card_w, grid_h

    # ---- list helpers ----

    def _get_selected_path(self) -> str | None:
        """Return the selected image path, or None when nothing is selected.

        Uses actual selection (not merely currentItem). Qt often keeps a
        current item after a background click clears the selection; that must
        not count as a selected image for preview / Clear reload restore.
        """
        items = self._selected_image_items()
        if not items:
            return None
        current = self._list_widget.currentItem()
        if current is not None and current.isSelected() and self._is_image_item(current):
            return current.data(Qt.UserRole)
        return items[0].data(Qt.UserRole)

    def _get_png_files(self, target_dir: Path) -> list[Path]:
        # Sorting is applied in build_groups (whole list or within each group).
        supported = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        return [
            path for path in target_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in supported
        ]

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
        favorite: bool | None = None,
        soft_wrap: bool = True,
    ) -> None:
        name = soft_wrap_filename(file_path.name) if soft_wrap else file_path.name
        visible = visible_tags(tags)
        item.setData(ROLE_CAPTION_NAME, name)
        item.setData(
            ROLE_CAPTION_TAGS,
            format_tags(visible, empty=t("images.tag.none")),
        )
        item.setData(ROLE_CAPTION_TAGS_MUTED, not bool(visible))
        item.setData(ROLE_CAPTION_DATE, self._caption_date_text(file_path))
        if favorite is None:
            favorite = self._metadata_service.is_image_favorite(
                file_path.parent, file_path.name
            )
        item.setData(ROLE_CAPTION_FAVORITE, bool(favorite))

    def _group_header_label(self, group_key: str) -> str:
        if group_key == NO_TAG_GROUP_KEY:
            return t("group_by.no_tag")
        if group_key == UNANALYZED_GROUP_KEY:
            return t("group_by.unanalyzed")
        if group_key == ANALYZED_GROUP_KEY:
            return t("group_by.analyzed")
        labels = {
            SEMANTIC_MISSING_GROUP_KEY: t("group_by.semantic_missing"),
            SEMANTIC_STALE_GROUP_KEY: t("group_by.semantic_stale"),
            SEMANTIC_FAILED_GROUP_KEY: t("group_by.semantic_failed"),
            SEMANTIC_CORRUPT_GROUP_KEY: t("group_by.semantic_corrupt"),
            OCR_MISSING_GROUP_KEY: t("group_by.ocr_missing"),
            PROCESSING_GROUP_KEY: t("group_by.processing"),
        }
        if group_key in labels:
            return labels[group_key]
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
            font.setWeight(QFont.Weight.DemiBold)
            font.setPointSize(max(font.pointSize(), 10))
            item.setForeground(QBrush(QColor("#374151")))
            item.setBackground(QBrush(QColor("#f3f4f6")))
        item.setFont(font)
        item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        item.setSizeHint(QSize(self._header_row_width(), GROUP_HEADER_HEIGHT))
        return item

    def _create_folder_item(self, folder: Path) -> QListWidgetItem:
        item = QListWidgetItem("")
        item.setIcon(icon_folder_fill(size=48))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        grid_w, grid_h = self._current_card_size()
        item.setSizeHint(QSize(grid_w, grid_h))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setData(Qt.UserRole, str(folder.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_FOLDER)
        item.setData(ROLE_CAPTION_NAME, folder.name)
        item.setData(ROLE_CAPTION_TAGS, "")
        item.setData(ROLE_CAPTION_DATE, "")
        item.setToolTip(str(folder))
        return item

    def _create_list_item(
        self,
        file_path: Path,
        metadata: dict | None = None,
        *,
        defer_thumbnail: bool = False,
    ) -> QListWidgetItem:
        if metadata is None:
            metadata = self._metadata_service.load_metadata(file_path.parent)

        tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])

        item = QListWidgetItem("")
        if not defer_thumbnail:
            item.setIcon(self._thumbnail_icon(file_path))
        item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        grid_w, grid_h = self._current_card_size()
        item.setSizeHint(QSize(grid_w, grid_h))
        # Drag to folders only — never accept drops (no in-list reorder)
        item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        )
        self._set_caption_roles(
            item,
            file_path,
            tags,
            favorite=image_is_favorite(metadata, file_path.name),
            soft_wrap=True,
        )

        item.setData(Qt.UserRole, str(file_path.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        tooltip_lines = [file_path.name]
        detail = self._analysis_details.get(file_path.name)
        if detail:
            tooltip_lines.extend([
                str(detail.get("path") or file_path),
                f"OCR: {detail.get('ocr_status', '-')}",
                f"Meaning: {detail.get('semantic_status', '-')}",
            ])
            if detail.get("ocr_failure_reason"):
                tooltip_lines.append(f"OCR reason: {detail['ocr_failure_reason']}")
            if detail.get("semantic_failure_reason"):
                tooltip_lines.append(f"Meaning reason: {detail['semantic_failure_reason']}")
        if bool(self._config.get("show_tags_in_image_list", False)):
            tooltip_lines.append(
                format_tags(visible_tags(tags), empty=t("images.tag.none"))
            )
        tooltip_lines.append(self._caption_date_text(file_path))
        item.setToolTip("\n".join(tooltip_lines))
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
        width, height = self._thumbnail_pixel_size()
        base = self._thumbnail_icon(file_path).pixmap(width, height)
        faded = QPixmap(base.size())
        faded.fill(Qt.transparent)
        painter = QPainter(faded)
        painter.setOpacity(0.35)
        painter.drawPixmap(0, 0, base)
        painter.end()
        item.setIcon(QIcon(faded))
        item.setForeground(QBrush(QColor(156, 163, 175)))

    def _apply_cut_visuals(self, *, defer_uncut_thumbnails: bool = False) -> None:
        """Refresh cut translucency on all visible list items."""
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if not self._is_image_item(item):
                continue
            path_str = item.data(Qt.UserRole)
            if not path_str:
                continue
            path = Path(path_str)
            if self._is_cut_path(path):
                self._style_item_as_cut(item, path)
            elif not defer_uncut_thumbnails:
                item.setIcon(self._thumbnail_icon(path))
                item.setForeground(QBrush(QColor("#1f2937")))

    def _populate_list(
        self,
        filtered_files: list[Path],
        selected_path_str: str | None,
        *,
        preserve_order: bool = False,
        defer_thumbnails: bool = False,
    ) -> bool:
        self._updating_selection = True
        self._list_widget.clear()
        target_dir = self._get_folder_dir()
        metadata = (
            self._metadata_service.load_metadata(target_dir)
            if target_dir.exists()
            else {"images": {}}
        )

        groups = (
            [("", filtered_files)]
            if preserve_order
            else build_groups(
                filtered_files,
                self._group_by,
                metadata,
                self._sort_mode,
                self._unanalyzed_names,
            )
        )

        selected_item = None
        if not preserve_order and not self._active_search_query.strip():
            for folder in self._current_child_folders():
                self._list_widget.addItem(self._create_folder_item(folder))
        for group_key, group_files in groups:
            if self._group_by != GROUP_BY_NONE and not preserve_order:
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
                item = self._create_list_item(
                    file_path,
                    metadata,
                    defer_thumbnail=defer_thumbnails,
                )
                self._list_widget.addItem(item)
                if defer_thumbnails:
                    self._thumbnail_load_queue.append((item, file_path))
                if selected_path_str and item.data(Qt.UserRole) == selected_path_str:
                    if selected_item is None:
                        selected_item = item

        self._gallery_count_label.setText(
            t("images.item_count", count=len(filtered_files))
        )
        self._refresh_gallery_item_hints()
        self._set_list_empty_state(len(filtered_files))

        if defer_thumbnails:
            self._start_thumbnail_hydration()

        if selected_item is not None:
            self._list_widget.setCurrentItem(selected_item)
            self._updating_selection = False
            self._show_image(selected_item)
            return True

        self._updating_selection = False
        return False

    def _start_thumbnail_hydration(self) -> None:
        """Decode thumbnails in short UI batches so navigation can keep painting."""
        self._thumbnail_load_generation += 1
        if self._thumbnail_load_queue:
            logger.info(
                "Images thumbnail load start count=%d",
                len(self._thumbnail_load_queue),
            )
            self._thumbnail_load_timer.start(0)

    def _hydrate_thumbnail_batch(self) -> None:
        deadline = time.perf_counter() + 0.008
        while self._thumbnail_load_queue and time.perf_counter() < deadline:
            item, path = self._thumbnail_load_queue.pop(0)
            if self._list_widget.row(item) >= 0:
                item.setIcon(self._thumbnail_icon(path))
        if self._thumbnail_load_queue:
            self._thumbnail_load_timer.start(0)
        else:
            logger.info("Images thumbnail load end")

    def _clear_preview(self) -> None:
        self._preview_cache_path = None
        self._preview_view.clear_message(t("images.select_image"))
        self._set_file_info_text("-")
        self._information_card.setEnabled(False)
        self._clear_tags_layout()
        self.reload_tag_choices()
        self._tag_empty_hint.show()
        self._current_tags_scroll.hide()
        self._current_tags_label.hide()
        self._update_tag_action_state()

    def _clear_tags_layout(self) -> None:
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _display_tags(self, file_path: Path, *, reload_choices: bool = True) -> None:
        self._clear_tags_layout()
        tags = self._metadata_service.get_image_tags(file_path.parent, file_path.name)

        if tags:
            for tag in dict.fromkeys(tags):
                self._tags_layout.addWidget(
                    self._make_current_tag_chip(file_path, tag)
                )
        else:
            empty_label = QLabel(t("images.tag.none"), self._current_tags_host)
            empty_label.setObjectName("mutedLabel")
            self._tags_layout.addWidget(empty_label)

        self._tag_empty_hint.hide()
        self._current_tags_label.show()
        self._current_tags_scroll.show()
        self._current_tags_host.updateGeometry()
        if hasattr(self, "_tags_info_label"):
            self._tags_info_label.setPath(format_tags(tags) if tags else t("images.tag.none"))
        if reload_choices:
            self.reload_tag_choices()
        else:
            self._update_tag_action_state()

    def _make_current_tag_chip(self, file_path: Path, tag: str) -> QFrame:
        chip = QFrame(self._current_tags_host)
        chip.setObjectName("currentTagChip")
        chip.setToolTip(format_tag(tag))
        chip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(7, 1, 2, 1)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignVCenter)
        label = QLabel(format_tag(tag), chip)
        label.setObjectName("currentTagChipLabel")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        label.setFixedHeight(20)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setMaximumWidth(150)
        label.setToolTip(format_tag(tag))
        layout.addWidget(label, 0, Qt.AlignVCenter)
        remove = QPushButton("✕", chip)
        remove.setObjectName("currentTagRemoveButton")
        # Apply inherited QSS before fixing the outer hit target. Otherwise a
        # later polish pass can reinterpret the QSS height as content height.
        remove.ensurePolished()
        remove.setFixedSize(20, 20)
        remove.setCursor(Qt.PointingHandCursor)
        remove.setToolTip(t("images.tag.remove_chip_tooltip", tag=format_tag(tag)))
        remove.clicked.connect(
            lambda checked=False, path=file_path, tag_name=tag: self._confirm_remove_tag(
                path, tag_name
            )
        )
        layout.addWidget(remove, 0, Qt.AlignVCenter)
        return chip

    def _on_current_item_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if self._updating_selection:
            return
        if current is None or not current.isSelected():
            if not self._selected_image_items():
                self._clear_preview()
            return
        if not self._is_image_item(current):
            return
        self._show_image(current)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if self._is_folder_item(item):
            return
        if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return
        if not item.isSelected():
            return
        self._show_image(item)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if self._is_folder_item(item):
            target = item.data(Qt.UserRole)
            if target:
                self.open_folder(target)
            return
        if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return
        path_str = item.data(Qt.UserRole)
        if path_str:
            self._open_image_path(Path(path_str))

    def _shortcut_quick_preview(self) -> None:
        if not self._file_shortcut_focus_ok():
            return
        path = self._selected_image_path()
        if path is not None:
            self._open_quick_preview(path, large=False)

    def _open_quick_preview(self, path: Path, *, large: bool) -> None:
        from app.ui.quick_preview_dialog import QuickPreviewDialog

        dialog = QuickPreviewDialog(self, large=large)
        if not dialog.load_path(path):
            return
        self._quick_preview_dialog = dialog
        dialog.exec()
        dialog.deleteLater()
        self._quick_preview_dialog = None

    def _show_image(self, item: QListWidgetItem) -> None:
        """Show preview + enable tag UI for the selected list item."""
        if not self._is_image_item(item):
            return

        file_path_str = item.data(Qt.UserRole)
        if not file_path_str:
            return

        file_path = Path(file_path_str)
        self._information_card.setEnabled(True)
        self._set_image_information(file_path)
        self._display_tags(file_path)

        if self._preview_cache_path == file_path_str:
            if self._preview_view.has_image():
                return

        self._preview_cache_path = None
        if not self._preview_view.load_path(file_path):
            self._preview_view.clear_message(t("images.load_failed"))
            self._preview_cache_path = file_path_str
            return

        self._preview_cache_path = file_path_str

    def _open_preview_image(self) -> None:
        path = self._selected_image_path()
        if path is not None:
            self._open_image_path(path)

    def _selected_image_path(self) -> Path | None:
        current_item = self._list_widget.currentItem()
        if not self._is_image_item(current_item):
            items = self._selected_image_items()
            current_item = items[0] if items else None
        if not self._is_image_item(current_item):
            return None
        return Path(current_item.data(Qt.UserRole))

    def _selected_tag_from_combo(self) -> str:
        return self._tag_combo.selectedTag()

    def _update_tag_action_state(self) -> None:
        path = self._selected_image_path()
        tag_name = self._selected_tag_from_combo()
        has_image = path is not None and path.exists()
        assigned = set()
        if has_image and path is not None:
            assigned = set(
                self._metadata_service.get_image_tags(path.parent, path.name)
            )
        # The picker is also the global tag list/management entry point.
        self._tag_combo.setEnabled(True)
        self._tag_assign_btn.setEnabled(has_image and bool(tag_name) and tag_name not in assigned)

    def _on_assign_existing_tag(self) -> None:
        path = self._selected_image_path()
        if path is None:
            return

        tag_name = self._selected_tag_from_combo()
        if not tag_name:
            return

        self._add_tag_to_paths([path], tag_name)

    def _on_assign_tag_from_popup(self) -> None:
        paths = self._selected_image_paths()
        tag_name = self._selected_tag_from_combo()
        if paths and tag_name:
            self._add_tag_to_paths(paths, tag_name)

    def _confirm_remove_tag(self, file_path: Path, tag_name: str) -> None:
        if self._selected_image_path() != file_path:
            return
        if not self._confirm_tag_removal_dialog(tag_name):
            return
        if self._selected_image_path() != file_path:
            return
        paths = self._selected_image_paths()
        if not self._tags_card.isVisible() or len(paths) <= 1:
            paths = [file_path]
        self._remove_tag_from_paths(paths, tag_name)

    def _confirm_tag_removal_dialog(self, tag_name: str) -> bool:
        dialog = QMessageBox(self)
        dialog.setObjectName("removeTagDialog")
        dialog.setWindowTitle(t("images.tag.remove_title"))
        dialog.setText(t("images.tag.remove_message", tag=format_tag(tag_name)))
        cancel = dialog.addButton(t("common.cancel"), QMessageBox.RejectRole)
        remove = dialog.addButton(t("images.tag.remove_action"), QMessageBox.AcceptRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() is remove
        dialog.deleteLater()
        return confirmed

    def _tag_usage_count_in_selected_folder(self, tag_name: str) -> int:
        folder = self._get_folder_dir()
        if not folder.exists():
            return 0
        metadata = self._metadata_service.load_metadata(folder, force_reload=True)
        return sum(
            1
            for info in metadata.get("images", {}).values()
            if tag_name in info.get("tags", [])
        )

    def _confirm_delete_global_tag(self, tag_name: str) -> None:
        affected = self._tag_usage_count_in_selected_folder(tag_name)
        if not self._confirm_global_tag_deletion_dialog(tag_name, affected):
            return

        folder = self._get_folder_dir()
        try:
            metadata = self._metadata_service.load_metadata(folder, force_reload=True)
            for file_name, info in metadata.get("images", {}).items():
                if tag_name in info.get("tags", []):
                    self._metadata_service.remove_image_tag(folder, file_name, tag_name)
            self._metadata_service.remove_global_tag(self._app_root, tag_name)
            self.reload_tag_choices()
            active = self._selected_image_path()
            if active is not None:
                self._display_tags(active)
                self._update_list_for_tag_change(active)
            else:
                self._load_images(force_reload_metadata=True)
            self.tags_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.remove_failed", error=e)
            )

    def _confirm_global_tag_deletion_dialog(
        self, tag_name: str, affected: int
    ) -> bool:
        dialog = QMessageBox(self)
        dialog.setObjectName("deleteGlobalTagDialog")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(t("images.tag.delete_global_title"))
        dialog.setText(
            t(
                "images.tag.delete_global_message",
                tag=format_tag(tag_name),
                count=affected,
            )
        )
        cancel = dialog.addButton(t("common.cancel"), QMessageBox.RejectRole)
        delete = dialog.addButton(
            t("images.tag.delete_global_action"), QMessageBox.DestructiveRole
        )
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() is delete
        dialog.deleteLater()
        return confirmed

    def _create_and_assign_tag_name(self, raw_name: str) -> None:
        paths = self._selected_image_paths()
        new_tag = normalize_tag(raw_name.strip())
        if not new_tag:
            return

        try:
            created_new = new_tag not in self._metadata_service.load_global_tags(
                self._app_root
            )
            tag_name = self._metadata_service.ensure_global_tag(self._app_root, new_tag)
            if not tag_name:
                return

            if paths:
                self._add_tag_to_paths(paths, tag_name)
            self.reload_tag_choices()
            self._tag_combo.setCurrentIndex(self._tag_combo.findData(tag_name))
            if len(paths) == 1:
                self._display_tags(paths[0], reload_choices=False)
            if created_new:
                self.tags_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=e)
            )

    def _open_new_tag_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("newTagDialog")
        dialog.setWindowTitle(t("images.tag.new_title"))
        dialog.setModal(True)
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title = QLabel(t("images.tag.new_title"), dialog)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        label = QLabel(t("images.tag.name_label"), dialog)
        layout.addWidget(label)
        name_input = QLineEdit(dialog)
        name_input.setObjectName("newTagNameInput")
        layout.addWidget(name_input)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"), dialog)
        cancel.setObjectName("secondaryButton")
        create = QPushButton(t("common.create"), dialog)
        create.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        layout.addLayout(buttons)
        name_input.textChanged.connect(
            lambda text: create.setEnabled(bool(normalize_tag(text.strip())))
        )
        cancel.clicked.connect(dialog.reject)
        create.clicked.connect(dialog.accept)
        name_input.returnPressed.connect(
            lambda: dialog.accept() if create.isEnabled() else None
        )
        name_input.setFocus()
        accepted = dialog.exec() == QDialog.Accepted
        value = name_input.text()
        dialog.deleteLater()
        if accepted:
            self._create_and_assign_tag_name(value)

    def _on_create_and_assign_tag(self) -> None:
        """Compatibility entry point; creation now uses the dedicated dialog."""
        self._open_new_tag_dialog()

    def _is_image_item(self, item: QListWidgetItem | None) -> bool:
        return (
            item is not None
            and item.data(ITEM_KIND_ROLE) == ITEM_KIND_IMAGE
            and bool(item.data(Qt.UserRole))
        )

    def _is_folder_item(self, item: QListWidgetItem | None) -> bool:
        return item is not None and item.data(ITEM_KIND_ROLE) == ITEM_KIND_FOLDER

    def _selected_image_items(self) -> list[QListWidgetItem]:
        """Selected list items that are real images (not group headers or folders)."""
        result: list[QListWidgetItem] = []
        for item in self._list_widget.selectedItems():
            kind = item.data(ITEM_KIND_ROLE)
            if kind in (ITEM_KIND_HEADER, ITEM_KIND_FOLDER):
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
        if self._updating_selection:
            return
        self._sync_workspace_selection()
        items = self._selected_image_items()
        emit_tour_event(
            UI_SELECTION_CHANGED,
            selected_count=len(items),
            already_favorite=self._selected_images_are_favorite() if items else False,
            generation=tour_event_generation(),
        )
        self._sync_tour_favorite_anchor()
        self._update_actions_state(len(items))
        current = self._list_widget.currentItem()
        if self._is_folder_item(current):
            self._clear_preview()
            return
        if not items:
            # Background click / deselect — clear current so reload won't restore it
            current = self._list_widget.currentItem()
            if current is not None:
                self._updating_selection = True
                self._list_widget.setCurrentItem(None)
                self._updating_selection = False
            self._clear_preview()
            return
        if len(items) == 1:
            self._show_image(items[0])
            return
        current = self._list_widget.currentItem()
        if current is not None and current.isSelected() and self._is_image_item(current):
            self._show_image(current)
        self._set_file_info_text(
            t("images.file_selected_count", count=len(items))
        )

    def _update_actions_state(self, count: int | None = None) -> None:
        # Tags also provides global tag navigation, so it is available without
        # an image selection. Image-specific controls handle their own state.
        self._actions_tags_btn.setEnabled(True)

    def _show_tags_popup(self) -> None:
        if self._tags_card.isVisible():
            self._hide_tags_popup()
            return
        if self._tags_popup_animation is not None:
            self._tags_popup_animation.stop()
            self._tags_popup_animation = None
        self.reload_tag_choices()
        active = self._selected_image_path()
        if active is not None:
            self._display_tags(active, reload_choices=False)
        self._tags_user_placed = False
        self._prepare_tags_popup_window()
        self._tags_card.setMaximumHeight(16777215)
        self._tags_card.adjustSize()
        end = self._tags_overlay_geometry()
        self._tags_card.setGeometry(end)
        self._tags_card.show()
        self._tags_card.raise_()
        self._install_tags_outside_filter()

    def _hide_tags_popup(self) -> None:
        if not self._tags_card.isVisible():
            return
        if self._tags_popup_animation is not None:
            self._tags_popup_animation.stop()
            self._tags_popup_animation = None
        picker = getattr(self._tag_combo, "_popup", None)
        if picker is not None and picker.isVisible():
            picker.close()
        self._tags_card.hide()
        self._tags_user_placed = False
        self._tags_drag_origin = None
        self._remove_tags_outside_filter()

    def _prepare_tags_popup_window(self) -> None:
        host = self.window() if self.window() is not None else self
        flags = Qt.Tool | Qt.FramelessWindowHint
        if self._tags_card.parentWidget() is not host or not self._tags_card.isWindow():
            self._tags_card.setParent(host, flags)
            self._tags_card.setAttribute(Qt.WA_StyledBackground, True)

    def _tags_screen_rect(self) -> QRect:
        button = getattr(self, "_actions_tags_btn", None)
        anchor = button.mapToGlobal(QPoint(0, 0)) if button is not None else QPoint(0, 0)
        screen = QApplication.screenAt(anchor)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QRect(8, 8, 1600, 900)
        return screen.availableGeometry().adjusted(8, 8, -8, -8)

    def _tags_overlay_geometry(self) -> QRect:
        area = self._tags_screen_rect()
        width = min(360, max(280, area.width()))
        self._tags_card.adjustSize()
        height = min(max(self._tags_card.sizeHint().height(), 240), area.height())
        button = self._actions_tags_btn
        button_br = button.mapToGlobal(QPoint(button.width(), button.height()))
        x = min(max(button_br.x() - width, area.left()), area.right() - width + 1)
        y = button_br.y() + 8
        if y + height > area.bottom():
            above = button.mapToGlobal(QPoint(0, 0)).y() - height - 8
            y = above if above >= area.top() else max(
                area.top(), area.bottom() - height + 1
            )
        return QRect(x, y, width, height)

    def _clamp_tags_geometry(self, rect: QRect) -> QRect:
        area = self._tags_screen_rect()
        width = min(rect.width(), area.width())
        height = min(rect.height(), area.height())
        x = min(max(rect.x(), area.left()), area.right() - width + 1)
        y = min(max(rect.y(), area.top()), area.bottom() - height + 1)
        return QRect(x, y, width, height)

    def _sync_tags_popup_geometry(self) -> None:
        if not self._tags_card.isVisible():
            return
        if self._tags_user_placed:
            self._tags_card.setGeometry(self._clamp_tags_geometry(self._tags_card.geometry()))
        else:
            self._tags_card.setGeometry(self._tags_overlay_geometry())
        self._tags_card.raise_()

    def _install_tags_outside_filter(self) -> None:
        app = QApplication.instance()
        filter_obj = getattr(self, "_tags_click_filter", None)
        if app is None or filter_obj is None or self._tags_outside_filter_installed:
            return
        app.installEventFilter(filter_obj)
        self._tags_outside_filter_installed = True

    def _remove_tags_outside_filter(self, *_args) -> None:
        app = QApplication.instance()
        filter_obj = getattr(self, "_tags_click_filter", None)
        if app is None or filter_obj is None or not getattr(self, "_tags_outside_filter_installed", False):
            self._tags_outside_filter_installed = False
            return
        try:
            app.removeEventFilter(filter_obj)
        except RuntimeError:
            pass
        self._tags_outside_filter_installed = False

    def _tags_popup_global_rect(self) -> QRect:
        origin = self._tags_card.mapToGlobal(QPoint(0, 0))
        return QRect(origin, self._tags_card.size())

    def _widget_contains_global(self, widget: QWidget | None, pos) -> bool:
        if widget is None or not widget.isVisible():
            return False
        origin = widget.mapToGlobal(QPoint(0, 0))
        return QRect(origin, widget.size()).contains(pos)

    def _close_tags_popup_if_outside(self, pos) -> None:
        if not getattr(self, "_tags_card", None) or not self._tags_card.isVisible():
            return
        if self._tags_popup_global_rect().contains(pos):
            return
        if self._widget_contains_global(self._actions_tags_btn, pos):
            return
        picker = getattr(self._tag_combo, "_popup", None)
        if self._widget_contains_global(picker, pos):
            return
        self._hide_tags_popup()

    def _handle_tags_header_drag(self, obj, event) -> bool:
        header = getattr(self, "_tags_header", None)
        if header is None or obj is not header:
            return False
        if not self._tags_card.isVisible():
            return False
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            global_pos = (
                event.globalPosition().toPoint()
                if isinstance(event, QMouseEvent)
                else event.globalPos()
            )
            self._tags_drag_origin = global_pos
            self._tags_drag_geom = QRect(self._tags_card.geometry())
            header.setCursor(Qt.ClosedHandCursor)
            header.grabMouse()
            return True
        if event.type() == QEvent.Type.MouseMove and self._tags_drag_origin is not None:
            global_pos = (
                event.globalPosition().toPoint()
                if isinstance(event, QMouseEvent)
                else event.globalPos()
            )
            delta = global_pos - self._tags_drag_origin
            moved = self._tags_drag_geom.translated(delta.x(), delta.y())
            self._tags_card.setGeometry(self._clamp_tags_geometry(moved))
            self._tags_user_placed = True
            return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            if QWidget.mouseGrabber() is header:
                header.releaseMouse()
            self._tags_drag_origin = None
            header.setCursor(Qt.OpenHandCursor)
            return False
        return False

    def _gallery_viewport_pos(self, widget_pos):
        return self._list_widget.viewport().mapFrom(self._list_widget, widget_pos)

    def _gallery_context_kind(self, widget_pos) -> str:
        """Classify a gallery context-menu point: image, folder, header, or empty."""
        viewport_pos = self._gallery_viewport_pos(widget_pos)
        hit = self._list_widget._selectable_item_at(viewport_pos)
        if self._is_image_item(hit):
            return "image"
        if self._is_folder_item(hit):
            return "folder"
        raw = self._list_widget.itemAt(viewport_pos)
        if raw is not None and raw.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
            return "header"
        return "empty"

    def _on_context_menu(self, pos) -> None:
        kind = self._gallery_context_kind(pos)
        if kind == "image":
            ensure_list_item_under_cursor_selected(
                self._list_widget, self._gallery_viewport_pos(pos)
            )
            menu = QMenu(self)
            populate_image_list_context_menu(
                menu,
                self,
                thumbnail_mode=self._thumbnail_mode,
                selected_count=len(self._selected_image_paths()),
                has_clipboard=self._has_clipboard(),
                on_set_thumbnail_mode=None,
                on_open=self._open_selected_images,
                on_copy=self._copy_selected_images,
                on_cut=self._cut_selected_images,
                on_paste=self._paste_clipboard,
                on_rename=self._rename_selected_image,
                on_delete=self._delete_selected_images,
                on_explorer=self._open_selected_in_explorer,
                on_move=self._choose_move_destination,
                on_analyze=self._retry_selected_analysis,
                on_favorite=self._toggle_selected_image_favorite,
                favorite_checked=self._selected_images_are_favorite(),
            )
            menu.exec(self._list_widget.mapToGlobal(pos))
            return
        if kind in ("folder", "header"):
            return
        self._popup_empty_gallery_menu(self._list_widget.mapToGlobal(pos))

    def _on_empty_hint_context_menu(self, pos) -> None:
        widget = self.sender()
        if not isinstance(widget, QWidget):
            widget = self._list_empty
        self._popup_empty_gallery_menu(widget.mapToGlobal(pos))

    def _can_create_child_folder(self) -> bool:
        _path, state = selected_folder_state(self._config, self._app_root)
        return state == "ready"

    def _empty_gallery_menu(self) -> QMenu:
        menu = QMenu(self)
        populate_empty_gallery_context_menu(
            menu,
            self,
            enabled=self._can_create_child_folder(),
            icon=icon_folder(),
            on_new_folder=self._create_child_folder_in_current_view,
        )
        return menu

    def _popup_empty_gallery_menu(self, global_pos) -> None:
        self._empty_gallery_menu().exec(global_pos)

    def _prompt_new_folder_name(self) -> str | None:
        dialog = QDialog(self)
        dialog.setObjectName("newFolderDialog")
        dialog.setWindowTitle(t("images.folder.new_title"))
        dialog.setModal(True)
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title = QLabel(t("images.folder.new_title"), dialog)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        label = QLabel(t("images.folder.name_label"), dialog)
        layout.addWidget(label)
        name_input = QLineEdit(dialog)
        name_input.setObjectName("newFolderNameInput")
        layout.addWidget(name_input)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton(t("common.cancel"), dialog)
        cancel.setObjectName("secondaryButton")
        create = QPushButton(t("common.create"), dialog)
        create.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        layout.addLayout(buttons)
        name_input.textChanged.connect(
            lambda text: create.setEnabled(bool(text.strip()))
        )
        cancel.clicked.connect(dialog.reject)
        create.clicked.connect(dialog.accept)
        name_input.returnPressed.connect(
            lambda: dialog.accept() if create.isEnabled() else None
        )
        name_input.setFocus()
        accepted = dialog.exec() == QDialog.Accepted
        value = name_input.text()
        dialog.deleteLater()
        if not accepted:
            return None
        return value

    def _create_child_folder_in_current_view(self) -> None:
        if not self._can_create_child_folder():
            return
        name = self._prompt_new_folder_name()
        if name is None:
            return
        self._create_child_folder_named(name)

    def _create_child_folder_named(self, raw_name: str) -> Path | None:
        name = (raw_name or "").strip()
        if not name:
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.name_required")
            )
            return None
        if not is_valid_folder_name(name):
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.name_invalid")
            )
            return None

        parent, state = selected_folder_state(self._config, self._app_root)
        if state != "ready" or parent is None:
            QMessageBox.warning(
                self, t("common.warning"), t("images.folder.missing")
            )
            return None

        try:
            created_result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_CREATE_FOLDER,
                    parameters={"parent_path": str(parent), "name": name},
                )
            )
            if created_result.status != "success":
                self._show_action_failure(created_result, "images.folder.create_failed")
                return None
            created = Path(created_result.items[0].after["path"])
        except OSError as exc:
            QMessageBox.critical(
                self,
                t("common.error"),
                t("images.folder.create_failed", error=exc),
            )
            return None

        self._refresh_gallery_after_child_folder_created()
        return created

    def _refresh_gallery_after_child_folder_created(self) -> None:
        """Stay in the current folder and show the new child if this view lists it."""
        self._refresh_child_folders()
        if self._ask_ai_grid_active or self._active_search_query.strip():
            return
        selected = self._selected_image_paths()
        self._updating_folder_ui = True
        try:
            self._load_images()
            if selected:
                self._restore_selected_paths(selected)
            if hasattr(self, "_fs_debounce"):
                self._fs_debounce.stop()
            self._fs_signature = self._folder_signature()
        finally:
            self._updating_folder_ui = False

    def _selected_images_are_favorite(self) -> bool:
        paths = self._selected_image_paths()
        if not paths:
            return False
        return all(
            self._metadata_service.is_image_favorite(path.parent, path.name)
            for path in paths
        )

    def _on_favorite_star_clicked(self, index) -> None:
        item = self._list_widget.item(index.row())
        if item is None or not self._is_image_item(item):
            return
        path = Path(item.data(Qt.UserRole))
        make_favorite = not bool(item.data(ROLE_CAPTION_FAVORITE))
        self._set_paths_favorite([path], make_favorite)

    def _toggle_selected_image_favorite(self) -> None:
        paths = self._selected_image_paths()
        if not paths:
            return
        self._set_paths_favorite(paths, not self._selected_images_are_favorite())

    def _set_paths_favorite(self, paths: list[Path], favorite: bool) -> None:
        if not paths:
            return
        try:
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_ADD_FAVORITE if favorite else ACTION_REMOVE_FAVORITE,
                    targets=self._targets_from_paths(paths),
                )
            )
        except OSError as exc:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=exc)
            )
            return
        if result.failed and not result.succeeded and not result.skipped:
            self._show_action_failure(result, "images.tag.save_failed")
            return
        emit_tour_event(
            UI_FAVORITE_CHANGED,
            ok=True,
            favorited=bool(favorite),
            generation=tour_event_generation(),
        )
        self._refresh_after_action_results((result,))

    def _ensure_tour_favorite_anchor(self) -> QWidget | None:
        list_widget = getattr(self, "_list_widget", None)
        if list_widget is None:
            return None
        widget = getattr(self, "_tour_favorite_anchor", None)
        if widget is None:
            viewport = list_widget.viewport()
            widget = QWidget(viewport)
            widget.setObjectName("tourFavoriteAnchor")
            widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            widget.setAttribute(Qt.WA_NoSystemBackground, True)
            widget.hide()
            self._tour_favorite_anchor = widget
        return widget

    def _sync_tour_favorite_anchor(self) -> None:
        widget = self._ensure_tour_favorite_anchor()
        if widget is None:
            return
        items = self._selected_image_items() if hasattr(self, "_list_widget") else []
        delegate = getattr(self, "_caption_delegate", None)
        if not items or delegate is None:
            widget.hide()
            return
        item = items[0]
        option = QStyleOptionViewItem()
        option.rect = self._list_widget.visualItemRect(item)
        option.widget = self._list_widget
        star = delegate.favorite_hit_rect(option)
        if star.isEmpty() or not option.rect.isValid():
            widget.hide()
            return
        widget.setGeometry(star)
        widget.show()

    def _toggle_ai_panel(self) -> None:
        if self._ai_panel_expanded:
            self._show_preview_panel()
        else:
            self._show_ai_panel()

    def _has_ask_ai_external_processing_consent(self) -> bool:
        return has_ask_ai_external_processing_consent(self._config)

    def _needs_ask_ai_consent_notice(self) -> bool:
        return needs_ask_ai_consent_notice(self._config)

    def _ask_ai_external_ready(self) -> bool:
        return (
            self._has_ask_ai_external_processing_consent()
            and not self._needs_ask_ai_consent_notice()
        )

    def _tour_handles_ai_consent(self) -> bool:
        return False

    def _track_prototype_event(self, event_name: str) -> None:
        window = self.window()
        tour = getattr(window, "_prototype_tour", None)
        tracker = getattr(tour, "track_event", None) if tour is not None else None
        if callable(tracker):
            tracker(event_name)

    def _persist_ask_ai_consent(self) -> None:
        accept_ask_ai_consent(self._config)
        try:
            save_config(self._config)
        except OSError:
            pass

    def _ask_ai_consent_parent(self):
        host = self.window()
        return host if host is not None else self

    def show_ask_ai_explanation(self) -> bool:
        """Settings path: show the same one-screen explanation without opening Ask AI."""
        self._track_prototype_event(EVENT_ASK_AI_CONSENT_SHOWN)
        dialog = AskAiConsentDialog(self._ask_ai_consent_parent())
        accepted = dialog.exec() == QDialog.Accepted
        if accepted:
            self._persist_ask_ai_consent()
            self._track_prototype_event(EVENT_ASK_AI_CONSENT_ACCEPTED)
        return accepted

    def _request_ask_ai_external_processing_consent(self) -> bool:
        if not self._needs_ask_ai_consent_notice():
            return True
        self._track_prototype_event(EVENT_ASK_AI_CONSENT_SHOWN)
        dialog = AskAiConsentDialog(self._ask_ai_consent_parent())
        if dialog.exec() != QDialog.Accepted:
            self._track_prototype_event(EVENT_ASK_AI_CONSENT_CANCELLED)
            return False
        self._persist_ask_ai_consent()
        self._track_prototype_event(EVENT_ASK_AI_CONSENT_ACCEPTED)
        return True

    def _ask_ai_ui_preview_enabled(self) -> bool:
        return ask_ai_ui_preview_enabled(self._config)

    def _sync_ask_ai_preview_hint(self) -> None:
        hint = getattr(self, "_ask_ai_preview_hint", None)
        enabled = self._ask_ai_ui_preview_enabled()
        if hint is not None:
            hint.setVisible(enabled)
        history = getattr(self, "_ai_history", None)
        if history is not None:
            history.set_coming_soon_visible(enabled)
            if not history.has_conversation():
                history.show_start_menu()

    def _show_ai_panel(self) -> None:
        explanation_shown = False
        if not self._ask_ai_ui_preview_enabled():
            needed = self._needs_ask_ai_consent_notice()
            if not self._request_ask_ai_external_processing_consent():
                return
            explanation_shown = needed
            folder = self._get_folder_dir()
            if folder is not None:
                self._start_semantic_index_from_ask_ai(folder)
        already = (
            self._ai_panel_expanded
            and self._right_stack.currentWidget() is self._ai_page
        )
        self._ai_panel_expanded = True
        self._right_panel.show()
        self._apply_right_panel_width(ai=True)
        if not already:
            self._set_right_stack_page(self._ai_page)
        self._action_input_row.show()
        self._action_input.show()
        self._action_preview_btn.show()
        self._sync_action_send_enabled()
        self._sync_ask_ai_preview_hint()
        self._action_input.setFocus(Qt.OtherFocusReason)
        emit_tour_event(
            UI_ASK_AI_OPENED,
            generation=tour_event_generation(),
            explanation_shown=explanation_shown,
        )

    def _show_preview_panel(self) -> None:
        already = (
            not self._ai_panel_expanded
            and self._right_stack.currentWidget() is self._preview_page
        )
        self._ai_panel_expanded = False
        self._isolate_ask_ai_search()
        self._right_panel.show()
        self._apply_right_panel_width(ai=False)
        if not already:
            self._set_right_stack_page(self._preview_page)

    def _apply_right_panel_width(self, *, ai: bool) -> None:
        minimum = IMAGES_AI_PANEL_MIN_WIDTH if ai else IMAGES_RIGHT_PANEL_MIN_WIDTH
        self._right_panel.setMinimumWidth(minimum)
        self._right_panel.setMaximumWidth(IMAGES_RIGHT_PANEL_MAX_WIDTH)
        sizes = list(self._splitter.sizes())
        if len(sizes) < 3:
            return
        if ai:
            if self._preview_panel_width is None:
                self._preview_panel_width = sizes[2]
            target = max(sizes[2], IMAGES_AI_PANEL_DEFAULT_WIDTH)
            extra = target - sizes[2]
            if extra <= 0:
                return
            sizes[1] = max(LIST_PANEL_MIN_WIDTH, sizes[1] - extra)
            sizes[2] = target
            self._splitter.setSizes(sizes)
            return
        restore = self._preview_panel_width
        self._preview_panel_width = None
        if restore is None:
            return
        delta = sizes[2] - restore
        if delta <= 0:
            return
        sizes[2] = restore
        sizes[1] = sizes[1] + delta
        self._splitter.setSizes(sizes)

    def _set_right_stack_page(self, target: QWidget) -> None:
        current = self._right_stack.currentWidget()
        self._stop_right_mode_animation()
        if current is target:
            show_only_stack_page(self._right_stack, target)
            return
        animate = (
            current is not None
            and self._right_stack.isVisible()
            and self._right_stack.width() > 1
            and self._right_stack.height() > 1
        )
        snapshot = opaque_grab(current) if animate else None
        if animate:
            fade_outgoing_snapshot(
                self._right_stack, snapshot, duration_ms=MOTION_SLOW_MS
            )
        show_only_stack_page(self._right_stack, target)

    def _stop_right_mode_animation(self) -> None:
        stop_page_fade(self._right_stack)
        self._right_mode_animation = None
        self._right_mode_overlay = None
        for page in (self._preview_page, self._ai_page):
            page.setGraphicsEffect(None)

    def _sync_action_send_enabled(self, *_args) -> None:
        if not hasattr(self, "_action_preview_btn"):
            return
        has_text = bool(self._action_input.text().strip())
        busy = bool(getattr(self, "_ask_ai_turn_busy", False))
        self._action_preview_btn.setEnabled(has_text and not busy)
        self._action_preview_btn.setProperty("processing", busy)
        style = self._action_preview_btn.style()
        if style is not None:
            style.unpolish(self._action_preview_btn)
            style.polish(self._action_preview_btn)

    def set_capture_expanded(self, expanded: bool) -> None:
        del expanded

    def _retry_selected_analysis(self) -> None:
        paths = self._selected_image_paths()
        if not paths or self._analysis_controller is None:
            return
        if hasattr(self._analysis_controller, "retry_analysis_paths"):
            if self._analysis_controller.retry_analysis_paths(paths):
                self._analysis_bar.refresh_status()

    def _has_clipboard(self) -> bool:
        if bool(self._clipboard_mode) and any(
            p.exists() for p in self._clipboard_paths
        ):
            return True
        return bool(paths_from_system_clipboard())

    def _resolve_paste_sources(self) -> tuple[list[Path], str | None]:
        """Prefer in-app clipboard; fall back to system file URLs."""
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
        previous = {
            "mode": self._clipboard_mode,
            "paths": [str(p) for p in self._clipboard_paths],
        }
        self._clipboard_paths = list(valid)
        self._clipboard_mode = mode if valid else None
        self._apply_cut_visuals()
        if valid:
            set_files_on_clipboard(valid, cut=(mode == CLIPBOARD_CUT))
            self._push_undo(
                UndoRecord(
                    kind=UNDO_COPY if mode == CLIPBOARD_COPY else UNDO_CUT,
                    payload={"previous": previous},
                )
            )
        else:
            clear_system_file_clipboard()

    def _clear_clipboard(self) -> None:
        self._clipboard_paths = []
        self._clipboard_mode = None
        self._apply_cut_visuals()
        clear_system_file_clipboard()

    def _select_all_images(self) -> None:
        selection = QItemSelection()
        first_index = None
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is None or item.data(ITEM_KIND_ROLE) in (
                ITEM_KIND_HEADER,
                ITEM_KIND_FOLDER,
            ):
                continue
            if not item.data(Qt.UserRole):
                continue
            index = self._list_widget.indexFromItem(item)
            selection.select(index, index)
            if first_index is None:
                first_index = index

        model = self._list_widget.selectionModel()
        model.select(selection, QItemSelectionModel.ClearAndSelect)
        if first_index is not None:
            model.setCurrentIndex(first_index, QItemSelectionModel.NoUpdate)

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
        valid, mode = self._resolve_paste_sources()
        if not mode or not valid:
            if self._clipboard_mode:
                self._clear_clipboard()
            return

        project_dir = self._get_folder_dir()
        from_internal = bool(self._clipboard_mode) and any(
            p.exists() for p in self._clipboard_paths
        )
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(project_dir)

            inserted: list[Path] = []
            moves: list[dict[str, str]] = []
            if mode == CLIPBOARD_CUT:
                result = self._execute_action(
                    ActionRequest(
                        action_id=ACTION_MOVE,
                        targets=self._targets_from_paths(valid),
                        parameters={"destination_path": str(project_dir)},
                    )
                )
                moves = self._undo_moves_from_result(result)
                inserted = [Path(item.after["path"]) for item in result.items if item.status == "success" and item.after.get("path")]
                if result.failed and not result.succeeded:
                    self._show_action_failure(result, "images.cut.failed")
                    return
                self._clear_clipboard()
                if moves:
                    self._push_undo(
                        UndoRecord(kind=UNDO_PASTE_CUT, payload={"moves": moves})
                    )
                if result.failed:
                    self._show_action_failure(result, "images.cut.failed")
            else:
                for path in valid:
                    dest = self._metadata_service.copy_image_to_project(
                        path, project_dir
                    )
                    inserted.append(dest)
                if from_internal:
                    # Keep system files available for external paste after in-app Copy
                    pass
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
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_RENAME,
                    targets=self._targets_from_paths([path]),
                    parameters={"new_name": new_name},
                )
            )
            if result.status != "success" or not result.succeeded:
                self._show_action_failure(result, "images.rename_failed")
                return
            dest = Path(result.items[0].after["path"])
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
                    set_files_on_clipboard(
                        remaining, cut=(self._clipboard_mode == CLIPBOARD_CUT)
                    )
                    self._apply_cut_visuals()
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

    def _choose_move_destination(self) -> None:
        paths = self._selected_image_paths()
        if not paths:
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            t("images.move.choose_destination"),
            str(self._get_screenshot_root()),
        )
        if selected:
            self._move_selected_images_to(Path(selected), paths)

    def _move_selected_images_to(
        self, destination: Path, paths: list[Path] | None = None
    ) -> None:
        paths = list(paths or self._selected_image_paths())
        if not paths:
            return
        destination = destination.resolve()
        source_dirs = {path.parent.resolve() for path in paths}
        if len(source_dirs) == 1 and destination in source_dirs:
            return
        try:
            destination.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(destination)
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_MOVE,
                    targets=self._targets_from_paths(paths),
                    parameters={"destination_path": str(destination)},
                )
            )
            moves = self._undo_moves_from_result(result)
            if result.failed and not result.succeeded:
                self._show_action_failure(result, "images.dnd.move_failed")
                return
            if moves:
                self._push_undo(
                    UndoRecord(kind=UNDO_DND_MOVE, payload={"moves": moves})
                )
            self._sync_from_filesystem()
            if result.failed:
                self._show_action_failure(result, "images.dnd.move_failed")
        except OSError as exc:
            QMessageBox.critical(
                self,
                t("common.error"),
                t("images.dnd.move_failed", error=exc),
            )

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
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_ADD_TAG,
                    targets=self._targets_from_paths(paths),
                    parameters={"tag": tag},
                )
            )
            if result.failed and not result.succeeded:
                self._show_action_failure(result, "images.tag.save_failed")
                return
            self._refresh_after_action_results((result,))
            emit_tour_event(UI_TAG_ADDED, generation=tour_event_generation())
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.save_failed", error=e)
            )

    def _remove_tag_from_paths(self, paths: list[Path], tag: str) -> None:
        try:
            result = self._execute_action(
                ActionRequest(
                    action_id=ACTION_REMOVE_TAG,
                    targets=self._targets_from_paths(paths),
                    parameters={"tag": tag},
                )
            )
            if result.failed and not result.succeeded:
                self._show_action_failure(result, "images.tag.remove_failed")
                return
            self._refresh_after_action_results((result,))
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("images.tag.remove_failed", error=e)
            )

    def _restore_selected_paths(self, paths: list[Path]) -> None:
        """Restore a multi-selection by file identity after rebuilding the list."""
        wanted = {str(path.resolve()) for path in paths}
        if not wanted:
            return
        self._updating_selection = True
        try:
            self._list_widget.clearSelection()
            for index in range(self._list_widget.count()):
                item = self._list_widget.item(index)
                if item.data(Qt.UserRole) in wanted:
                    item.setSelected(True)
        finally:
            self._updating_selection = False
        self._on_selection_changed()

    def _find_list_row(self, file_path: Path) -> int:
        path_str = str(file_path.resolve())
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if not self._is_image_item(item):
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
            if not self._is_image_item(other):
                continue
            other_path = Path(other.data(Qt.UserRole))
            if should_insert_before(file_path, other_path, self._sort_mode):
                self._list_widget.insertItem(i, item)
                return
        self._list_widget.addItem(item)

    def _update_list_item_metadata(self, file_path: Path) -> None:
        row = self._find_list_row(file_path)
        if row == -1:
            return
        metadata = self._metadata_service.load_metadata(file_path.parent)
        tags = metadata.get("images", {}).get(file_path.name, {}).get("tags", [])
        item = self._list_widget.item(row)
        item.setText("")
        self._set_caption_roles(
            item,
            file_path,
            tags,
            favorite=image_is_favorite(metadata, file_path.name),
            soft_wrap=True,
        )
        item.setToolTip(
            f"{file_path.name}\n"
            f"{format_tags(visible_tags(tags), empty=t('images.tag.none'))}\n"
            f"{self._caption_date_text(file_path)}"
        )

    def _paths_from_action_results(self, results) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        for result in results or ():
            for item in getattr(result, "items", ()) or ():
                raw = (item.after or {}).get("path") or (item.before or {}).get("path")
                if not raw:
                    continue
                path = Path(raw)
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                paths.append(path)
        return paths

    def _apply_result_path_relocations(self, results) -> None:
        replacements: dict[str, str] = {}
        for result in results or ():
            if getattr(result, "action_id", "") not in {ACTION_MOVE, ACTION_RENAME}:
                continue
            for item in getattr(result, "items", ()) or ():
                if getattr(item, "status", "") != "success":
                    continue
                before = (item.before or {}).get("path")
                after = (item.after or {}).get("path")
                if before and after and before != after:
                    replacements[str(before)] = str(after)
        if replacements:
            self._workspace.relocate_paths(replacements)

    def _refresh_after_action_results(self, results, *, filesystem_changed: bool = False) -> None:
        action_ids = {getattr(result, "action_id", "") for result in results or ()}
        if ACTION_CREATE_FOLDER in action_ids and not (
            action_ids & {ACTION_MOVE, ACTION_RENAME}
        ):
            self._refresh_gallery_after_child_folder_created()
            return
        if filesystem_changed or action_ids & {ACTION_MOVE, ACTION_RENAME}:
            self._apply_result_path_relocations(results)
            self._sync_from_filesystem()
            return
        paths = self._paths_from_action_results(results)
        rebuild = self._filter_mode == FILTER_FAVORITES_ONLY or (
            self._group_by != GROUP_BY_NONE
            and bool(action_ids & {ACTION_ADD_TAG, ACTION_REMOVE_TAG, ACTION_REMOVE_ALL_TAGS, ACTION_REPLACE_TAGS})
        )
        if rebuild:
            selected = self._selected_image_paths() or paths
            self._load_images()
            if selected:
                self._restore_selected_paths(selected)
            self._sync_tour_favorite_anchor()
            return
        for path in paths:
            if path.exists():
                self._update_list_item_metadata(path)
        selected = self._selected_image_paths()
        if len(selected) == 1:
            self._display_tags(selected[0], reload_choices=False)
        if action_ids & {ACTION_ADD_TAG, ACTION_REMOVE_TAG, ACTION_REMOVE_ALL_TAGS, ACTION_REPLACE_TAGS} and self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)
            return
        self._sync_tour_favorite_anchor()
        list_widget = getattr(self, "_list_widget", None)
        if list_widget is not None:
            list_widget.viewport().update()

    def _update_list_for_tag_change(self, file_path: Path) -> None:
        # Tag / date groups and the favorites list depend on metadata.
        if self._group_by != GROUP_BY_NONE or self._filter_mode == FILTER_FAVORITES_ONLY:
            self._load_images()
            return

        self._update_list_item_metadata(file_path)

        if not self._active_search_query.strip():
            return

        # Tags are a unified-search source; refresh through the same API instead
        # of reproducing its matching rules in the UI.
        self._start_unified_search(self._active_search_query)

    def _set_list_empty_state(self, folder_image_count: int) -> None:
        """Show the empty hint only when the folder has no images and no folders."""
        if not hasattr(self, "_list_stack"):
            return
        in_progress = self._search_request_id in getattr(self, "_search_tasks", {})
        if in_progress:
            self._list_stack.setCurrentIndex(0)
            return
        searching = bool(self._active_search_query.strip())
        has_folders = (not searching) and bool(self._current_child_folders())
        if not has_folders and hasattr(self, "_list_widget") and not searching:
            for index in range(self._list_widget.count()):
                if self._is_folder_item(self._list_widget.item(index)):
                    has_folders = True
                    break
        empty = folder_image_count <= 0 and not has_folders
        self._list_stack.setCurrentIndex(1 if empty else 0)

    def _search_busy_visible(self) -> bool:
        return (
            hasattr(self, "_list_searching")
            and self._list_stack.currentWidget() is self._list_searching
        )

    def prewarm_meaning_search(self) -> None:
        """Hide first-search worker start / SHA-256 / ONNX load after UI warmup."""
        provider = getattr(self, "_owned_vision_search_provider", None)
        prewarm = getattr(provider, "prewarm", None)
        if callable(prewarm):
            prewarm()

    def _meaning_bundle_preparing_text(self, *, meaning: bool | None = None) -> str | None:
        """Short wait copy only while OpenCLIP integrity is still running."""
        if meaning is None:
            mode = getattr(self, "_active_search_mode", USER_FACING_TEXT_MODE)
            meaning = (
                self._user_facing_search_mode(mode) == USER_FACING_MEANING_MODE
            )
        if not meaning:
            return None
        from app.semantic.installer import product_bundle_ui_state

        if product_bundle_ui_state(
            self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY)
        ) != "pending":
            return None
        return t("images.meaning.preparing")

    def _show_search_busy(self) -> None:
        self._set_search_status(t("images.searching"), searching=True)
        if self._list_widget.count() == 0:
            self._list_stack.setCurrentIndex(0)

    def _hide_search_status(self) -> None:
        self._search_status_spinner.hide()
        self._search_result_label.clear()
        self._search_result_label.hide()
        self._search_status_row.hide()
        if hasattr(self, "_gallery_count_label"):
            self._gallery_count_label.show()

    def _set_search_status(self, text: str, *, searching: bool = False) -> None:
        self._search_result_label.setText(text)
        self._search_result_label.show()
        self._search_status_row.show()
        self._search_status_spinner.setVisible(searching)
        if hasattr(self, "_gallery_count_label"):
            self._gallery_count_label.hide()

    def _update_search_feedback(
        self, query: str, result_count: int, folder_image_count: int
    ) -> None:
        query = query.strip()
        if not query:
            self._hide_search_status()
            self._gallery_count_label.show()
            self._empty_choose_folder_btn.show()
            self._set_list_empty_state(folder_image_count)
            self._update_selected_folder_ui()
            return

        if result_count:
            key = "images.search_result_one" if result_count == 1 else "images.search_results"
            self._set_search_status(t(key, count=result_count, query=query), searching=False)
            self._list_stack.setCurrentIndex(0)
            return

        self._set_search_status(
            t("images.search_results", count=0, query=query), searching=False
        )
        self._list_empty_title.setText(t("images.search_no_results", query=query))
        self._list_empty_body.setText(t("images.search_try_another"))
        self._empty_choose_folder_btn.hide()
        self._list_stack.setCurrentIndex(1)

    def _search_candidates(self, folder: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
        metadata = self._metadata_service.load_metadata(folder)
        images = metadata.get("images", {})
        return tuple(
            (path, tuple(visible_tags(images.get(path.name, {}).get("tags", []))))
            for path in self._get_png_files(folder)
        )

    def _local_search_matches(self, query: str) -> list[Path]:
        """Filename and tag hits from the current folder (no OCR / Vision)."""
        folder = self._get_folder_dir()
        if not query.strip() or not folder.exists():
            return []
        matches = [
            path
            for path, tags in self._search_candidates(folder)
            if image_matches_search(path.name, list(tags), query)
        ]
        return apply_favorite_filter(
            matches,
            self._metadata_service.load_metadata(folder),
            self._filter_mode,
        )

    @staticmethod
    def _merge_search_paths(local: list[Path], ranked: list[Path]) -> list[Path]:
        seen: set[str] = set()
        merged: list[Path] = []
        for path in (*local, *ranked):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            merged.append(path)
        return merged

    def _start_unified_search(self, query: str) -> None:
        self._isolate_ask_ai_search()
        self._clear_ask_ai_grid()
        folder = self._get_folder_dir()
        if not folder.exists():
            self._update_search_feedback(query, 0, 0)
            self._list_widget.clear()
            self._clear_preview()
            emit_tour_event(
                UI_FIND_FINISHED,
                ok=False,
                result_count=0,
                kind=self._tour_search_kind(),
                generation=self._tour_search_generation,
            )
            return
        resolved_folder = folder.resolve()
        duplicate = any(
            task.query == query
            and task.folder.resolve() == resolved_folder
            and task.mode == self._active_search_mode
            for task in self._search_tasks.values()
        )
        if duplicate:
            waiting = self._meaning_bundle_preparing_text()
            self._set_search_status(
                waiting or t("images.searching"), searching=True
            )
            if self._list_widget.count() == 0:
                self._list_stack.setCurrentIndex(0)
            logger.info(
                "Images-search accepted existing query=%r mode=%s reason=in_progress",
                query,
                self._active_search_mode,
            )
            return
        self._cancel_search_tasks()
        self._search_request_id += 1
        request_id = self._search_request_id
        mode = self._active_search_mode
        provider = self._provider_for_mode(mode)
        logger.info(
            "Images-search start request=%d query=%r configured_mode=%s active_mode=%s provider=%s",
            request_id,
            query,
            self._configured_search_mode(),
            mode,
            type(provider).__name__ if not inspect.isfunction(provider) else provider.__name__,
        )
        self._set_search_status(
            self._meaning_bundle_preparing_text() or t("images.searching"),
            searching=True,
        )
        local_matches = self._local_search_matches(query)
        self._local_search_by_request[request_id] = list(local_matches)
        self._progressive_visible_paths[request_id] = list(local_matches)
        self._search_started_at[request_id] = time.perf_counter()
        if local_matches:
            self._populate_list(
                local_matches, self._get_selected_path(), preserve_order=True
            )
        else:
            self._list_widget.clear()
            self._gallery_count_label.setText(t("images.item_count", count=0))
            self._clear_preview()
            self._list_stack.setCurrentIndex(0)
        task = ImagesSearchTask(
            request_id,
            query,
            folder,
            self._search_candidates(folder),
            provider,
            mode,
        )
        self._search_tasks[request_id] = task
        # A bound QObject method lets Qt disconnect safely when the page dies.
        task.signals.progress.connect(self._progress_unified_search)
        task.signals.finished.connect(self._finish_unified_search)
        self._search_pool.start(task)

    def _cancel_search_tasks(self) -> None:
        for task in self._search_tasks.values():
            task.cancel()

    def _progress_unified_search(
        self, request_id, query, folder, result_paths, checked_count, total_count
    ) -> None:
        if request_id != self._search_request_id:
            return
        if query != self._active_search_query:
            return
        if folder != str(self._get_folder_dir().resolve()):
            return
        existing = {
            str(path.resolve()): path
            for path in self._get_png_files(self._get_folder_dir())
        }
        ranked_paths = [
            existing[str(Path(path).resolve())]
            for path in result_paths
            if str(Path(path).resolve()) in existing
        ]
        visible = self._progressive_visible_paths.setdefault(request_id, [])
        known = {str(path.resolve()) for path in visible}
        additions = [path for path in ranked_paths if str(path.resolve()) not in known]
        selected_path = self._get_selected_path()
        first_visible = bool(additions) and not visible
        if additions and not visible:
            self._populate_list(additions, selected_path, preserve_order=True)
            visible.extend(additions)
        elif additions:
            metadata = self._metadata_service.load_metadata(self._get_folder_dir())
            for path in additions:
                self._list_widget.addItem(self._create_list_item(path, metadata))
            visible.extend(additions)
            self._gallery_count_label.setText(t("images.item_count", count=len(visible)))
        if visible:
            self._list_stack.setCurrentIndex(0)
            if first_visible:
                started = self._search_started_at.get(request_id)
                logger.info(
                    "Images-search first result request=%d visible=%d elapsed_seconds=%s",
                    request_id,
                    len(visible),
                    None if started is None else round(time.perf_counter() - started, 3),
                )
        self._set_search_status(format_searching_status(
            matches=len(visible), checked=checked_count, total=total_count,
        ), searching=True)

    def _ask_ai_waiting_for_prep(self) -> bool:
        return self._ask_ai_pending_query is not None

    def _ask_ai_prep_incomplete(self) -> bool:
        indexer = self._semantic_index_indexer
        if indexer is None:
            return False
        probe = getattr(indexer, "has_unready_images", None)
        if callable(probe):
            try:
                return bool(probe(self._get_folder_dir()))
            except TypeError:
                return bool(probe())
        is_running = getattr(indexer, "is_running", None)
        if callable(is_running) and is_running():
            return True
        snapshot = getattr(indexer, "snapshot", None)
        if callable(snapshot):
            data = snapshot()
            return bool(
                getattr(data, "running", False)
                and int(getattr(data, "needed", 0) or 0) > 0
            )
        return False

    def _should_wait_for_initial_prep(self) -> bool:
        if self._ask_ai_initial_prep_done:
            return False
        return self._ask_ai_prep_incomplete()

    def _ask_ai_prep_error(self) -> BaseException | None:
        if self._ask_ai_initial_prep_done:
            return None
        indexer = self._semantic_index_indexer
        probe = getattr(indexer, "last_error", None)
        if callable(probe):
            try:
                error = probe()
            except TypeError:
                error = probe
            if isinstance(error, BaseException):
                return error
        snapshot = getattr(indexer, "snapshot", None)
        if callable(snapshot):
            data = snapshot()
            error = getattr(data, "last_error", None)
            if isinstance(error, BaseException):
                return error
        return None

    def _fail_pending_ask_ai_prep(self, error: BaseException) -> None:
        self._ask_ai_pending_query = None
        self._ask_ai_pending_folder = None
        self._ask_ai_pending_turn = None
        self._pending_act_continuation = None
        self._ask_ai_prep_timer.stop()
        text = format_ai_user_message(error)
        message = self._ask_ai_result_by_request.get(self._ask_ai_request_id)
        if message is not None and not getattr(message, "frozen", False):
            if _is_usage_limit_error(error):
                _apply_ask_ai_usage_limit(message, error)
            else:
                message.fail(text)
        if self._ask_ai_grid_query:
            self._set_ask_ai_grid_status(
                self._ask_ai_grid_query,
                0,
                searching=False,
            )

    def _ask_ai_prep_counts(self) -> tuple[int, int]:
        indexer = self._semantic_index_indexer
        snapshot = getattr(indexer, "snapshot", None)
        if not callable(snapshot):
            return 0, 0
        data = snapshot()
        return (
            int(getattr(data, "ready", 0) or 0),
            int(getattr(data, "total", 0) or 0),
        )

    def _ask_ai_chat_status(self, *, searching: bool, count: int = 0) -> str:
        ready, total = self._ask_ai_prep_counts()
        return ask_ai_chat_status(
            searching=searching,
            count=count,
            preparing=self._ask_ai_waiting_for_prep() and not searching,
            ready=ready,
            total=total,
        )

    def _apply_ask_ai_prep_copy(self) -> None:
        ready, total = self._ask_ai_prep_counts()
        message = self._ask_ai_result_by_request.get(self._ask_ai_request_id)
        if message is not None and not getattr(message, "frozen", False):
            message.set_searching(
                ask_ai_chat_status(
                    searching=False,
                    preparing=True,
                    ready=ready,
                    total=total,
                )
            )
        if self._ask_ai_grid_query:
            self._set_ask_ai_grid_status(
                self._ask_ai_grid_query,
                0,
                searching=False,
            )

    def _refresh_ask_ai_prep_status(self) -> None:
        if self._ask_ai_pending_query:
            if self._should_wait_for_initial_prep():
                self._apply_ask_ai_prep_copy()
                return
            error = self._ask_ai_prep_error()
            if error is not None:
                self._fail_pending_ask_ai_prep(error)
                return
            self._start_pending_ask_ai_search()
            return
        self._ask_ai_prep_timer.stop()

    def _start_ask_ai_prep_timer(self) -> None:
        if self._ask_ai_pending_query and not self._ask_ai_prep_timer.isActive():
            self._ask_ai_prep_timer.start()

    def _reset_ask_ai_folder_prep(self) -> None:
        self._ask_ai_pending_query = None
        self._ask_ai_pending_folder = None
        self._ask_ai_pending_turn = None
        self._pending_act_continuation = None
        self._ask_ai_initial_prep_done = False
        self._ask_ai_prep_timer.stop()
        self.reset_ask_ai_planner_conversation()

    def reset_ask_ai_planner_conversation(self) -> None:
        """Drop the API conversation chain. Local result/selection state is separate."""
        self._ask_ai_planner_response_id = ""

    def note_ask_ai_account(self, user_id: str = "") -> None:
        current = str(user_id or "")
        previous = str(getattr(self, "_ask_ai_planner_user_id", "") or "")
        if current != previous:
            self.reset_ask_ai_planner_conversation()
            folder = self._get_folder_dir()
            self._workspace.reset(scope_folder=folder if folder.exists() else None)
        self._ask_ai_planner_user_id = current

    def _begin_ask_ai_prep_wait(self, query: str, folder: Path) -> None:
        message = self._ask_ai_result_by_request.get(self._ask_ai_request_id)
        reuse = message is not None and not getattr(message, "frozen", False)
        if not reuse:
            self._isolate_ask_ai_search()
            request_id = self._ask_ai_request_id
            message = self._ai_history.add_result_message(request_id, query=query)
            self._ask_ai_result_by_request[request_id] = message
        self._ask_ai_pending_query = query
        self._ask_ai_pending_folder = folder
        set_folder = getattr(message, "set_result_folder", None)
        if callable(set_folder):
            set_folder(folder)
        set_query = getattr(message, "set_result_query", None)
        if callable(set_query):
            set_query(query)
        self._begin_ask_ai_grid(query, searching=False)
        self._apply_ask_ai_prep_copy()
        self._start_ask_ai_prep_timer()

    def _update_ask_ai_prep_wait(self, query: str, folder: Path) -> None:
        self._ask_ai_pending_query = query
        self._ask_ai_pending_folder = folder
        self._ask_ai_grid_query = query
        self._apply_ask_ai_prep_copy()
        self._start_ask_ai_prep_timer()

    def _start_pending_ask_ai_search(self) -> None:
        query = self._ask_ai_pending_query
        folder = self._ask_ai_pending_folder
        turn = self._ask_ai_pending_turn
        if not query or folder is None:
            self._ask_ai_pending_query = None
            self._ask_ai_pending_folder = None
            self._ask_ai_prep_timer.stop()
            return
        if self._ask_ai_search_tasks:
            return
        self._ask_ai_pending_query = None
        self._ask_ai_pending_folder = None
        self._ask_ai_pending_turn = None
        self._ask_ai_initial_prep_done = True
        self._ask_ai_prep_timer.stop()
        self._start_ask_ai_meaning_search(query, folder, isolate=False, turn=turn)

    def _cancel_ask_ai_search_tasks(self) -> None:
        for task in self._ask_ai_search_tasks.values():
            task.cancel()

    def _isolate_ask_ai_search(self) -> None:
        message = self._ask_ai_result_by_request.get(self._ask_ai_request_id)
        freeze = getattr(message, "freeze", None)
        if callable(freeze):
            freeze()
            self._bind_ask_ai_ocr_image_ids(message)
        if hasattr(self, "_ai_history"):
            freeze_confirms = getattr(self._ai_history, "freeze_pending_confirms", None)
            if callable(freeze_confirms):
                freeze_confirms()
        self._pending_act_request = None
        self._pending_act_message = None
        self._pending_prepared_plan = None
        self._pending_act_continuation = None
        self._cancel_ask_ai_preview()
        self._cancel_ask_ai_search_tasks()
        self._ask_ai_request_id += 1
        if self._ask_ai_grid_active and self._ask_ai_grid_query:
            self._set_ask_ai_grid_status(
                self._ask_ai_grid_query,
                len(self._ask_ai_grid_paths),
                searching=False,
            )

    def _cancel_ask_ai_preview(self) -> None:
        timer = getattr(self, "_ask_ai_preview_timer", None)
        if timer is None:
            return
        timer.stop()
        timer.deleteLater()
        self._ask_ai_preview_timer = None

    def _clear_ask_ai_grid(self) -> None:
        self._ask_ai_grid_active = False
        self._ask_ai_grid_query = ""
        self._ask_ai_grid_paths = []
        self._ask_ai_pending_query = None
        self._ask_ai_pending_folder = None
        self._ask_ai_prep_timer.stop()
        self._sync_ai_results_clear_button()

    def _sync_ai_results_clear_button(self) -> None:
        button = getattr(self, "_ai_results_clear_btn", None)
        if button is None:
            return
        button.setVisible(bool(self._ask_ai_grid_active))

    def _exit_ask_ai_results(self) -> None:
        self._isolate_ask_ai_search()
        self._clear_ask_ai_grid()
        self._cancel_search_tasks()
        self._search_request_id += 1
        self._load_images()

    def _set_ask_ai_grid_status(self, query: str, count: int, *, searching: bool) -> None:
        preparing = self._ask_ai_waiting_for_prep() and not searching
        ready, total = self._ask_ai_prep_counts()
        self._set_search_status(
            ask_ai_grid_status(
                query=query,
                count=count,
                searching=searching,
                preparing=preparing,
                ready=ready,
                total=total,
            ),
            searching=searching or preparing,
        )

    def _begin_ask_ai_grid(self, query: str, *, searching: bool = True) -> None:
        self._cancel_search_tasks()
        self._search_request_id += 1
        self._active_search_query = ""
        self._ask_ai_grid_active = True
        self._ask_ai_grid_query = query
        self._ask_ai_grid_paths = []
        self._list_widget.clear()
        self._gallery_count_label.setText(t("images.item_count", count=0))
        self._clear_preview()
        self._list_stack.setCurrentIndex(0)
        self._set_ask_ai_grid_status(query, 0, searching=searching)
        self._sync_ai_results_clear_button()

    def _apply_ask_ai_grid_paths(self, paths: list[Path], *, searching: bool) -> None:
        query = self._ask_ai_grid_query
        selected_path = self._get_selected_path()
        visible = list(self._ask_ai_grid_paths)
        known = {str(path.resolve()) for path in visible}
        additions = [path for path in paths if str(path.resolve()) not in known]
        if additions and not visible:
            self._populate_list(additions, selected_path, preserve_order=True)
            visible.extend(additions)
        elif additions:
            metadata = self._metadata_service.load_metadata(self._get_folder_dir())
            for path in additions:
                self._list_widget.addItem(self._create_list_item(path, metadata))
            visible.extend(additions)
            self._gallery_count_label.setText(t("images.item_count", count=len(visible)))
        self._ask_ai_grid_paths = visible
        self._ask_ai_grid_active = True
        if visible:
            self._list_stack.setCurrentIndex(0)
        elif not searching:
            if self._ask_ai_waiting_for_prep():
                self._list_stack.setCurrentIndex(0)
            else:
                self._list_empty_title.setText(t("images.ai.no_matches"))
                self._list_empty_body.setText(t("images.ai.rephrase_target"))
                self._empty_choose_folder_btn.hide()
                self._list_stack.setCurrentIndex(1)
        if query:
            self._set_ask_ai_grid_status(query, len(visible), searching=searching)
        self._sync_ai_results_clear_button()

    def _reload_ask_ai_grid(self, *, defer_thumbnails: bool = False) -> bool:
        if not self._ask_ai_grid_active or not self._ask_ai_grid_query:
            return False
        selected_path_str = self._get_selected_path()
        paths = [path for path in self._ask_ai_grid_paths if path.exists()]
        self._ask_ai_grid_paths = paths
        searching = bool(self._ask_ai_search_tasks)
        if paths:
            restored = self._populate_list(
                paths,
                selected_path_str,
                preserve_order=True,
                defer_thumbnails=defer_thumbnails,
            )
            if not restored:
                self._clear_preview()
            self._list_stack.setCurrentIndex(0)
        elif searching or self._ask_ai_waiting_for_prep():
            self._list_widget.clear()
            self._clear_preview()
            self._list_stack.setCurrentIndex(0)
        else:
            self._list_widget.clear()
            self._clear_preview()
            self._list_empty_title.setText(t("images.ai.no_matches"))
            self._list_empty_body.setText(t("images.ai.rephrase_target"))
            self._empty_choose_folder_btn.hide()
            self._list_stack.setCurrentIndex(1)
        self._set_ask_ai_grid_status(
            self._ask_ai_grid_query, len(paths), searching=searching
        )
        return True

    def _on_ask_ai_send(self) -> None:
        self._invalidate_action_confirmation()
        if hasattr(self, "_action_preview"):
            self._action_preview.hide()
        if getattr(self, "_ask_ai_turn_busy", False):
            return
        query = self._action_input.text().strip()
        if not query:
            return
        self._tour_search_generation = tour_event_generation()
        if self._ask_ai_ui_preview_enabled():
            self._send_ask_ai_ui_preview(query)
            return
        if not self._ask_ai_external_ready():
            if not self._request_ask_ai_external_processing_consent():
                return
        folder = self._get_folder_dir()
        self._action_input.clear()
        self._ask_ai_turn_busy = True
        self._sync_action_send_enabled()
        if hasattr(self, "_ai_history"):
            self._ai_history.add_user_message(query)
        self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        message = self._ai_history.add_result_message(request_id, query=query)
        self._ask_ai_result_by_request[request_id] = message
        set_phase = getattr(message, "set_phase", None)
        if callable(set_phase):
            set_phase("understanding")
        if not folder.exists():
            self._finish_ask_ai_turn_busy()
            message.fail(
                f"{t('images.ai.no_folder')} {t('images.ai.choose_folder')}"
            )
            return
        QTimer.singleShot(0, lambda: self._begin_ask_ai_planner(query, request_id, message))

    def _finish_ask_ai_turn_busy(self) -> None:
        self._ask_ai_turn_busy = False
        self._sync_action_send_enabled()

    def _begin_ask_ai_planner(self, query: str, request_id: int, message) -> None:
        if request_id != self._ask_ai_request_id:
            self._finish_ask_ai_turn_busy()
            return
        self._sync_workspace_selection()
        catalog = self._act_plan_image_catalog()
        task = AskAiTurnTask(
            request_id,
            query,
            self._workspace.context,
            images=catalog,
            conversation=self._ask_ai_conversation_state(),
            complete_json=getattr(self, "_act_plan_complete_json", None),
            name_generator=getattr(self, "_act_plan_name_generator", None),
            allow_ai=True,
        )
        self._ask_ai_turn_tasks[request_id] = task
        task.signals.finished.connect(self._on_ask_ai_turn_finished)
        self._search_pool.start(task)

    def _on_ask_ai_turn_finished(self, request_id: int, turn, error) -> None:
        task = self._ask_ai_turn_tasks.pop(request_id, None)
        if task is not None:
            task.signals.finished.disconnect(self._on_ask_ai_turn_finished)
        if request_id != self._ask_ai_request_id:
            self._finish_ask_ai_turn_busy()
            return
        self._finish_ask_ai_turn_busy()
        message = self._ask_ai_result_by_request.get(request_id)
        if error is not None:
            self._fail_ask_ai_turn(message, error)
            return
        self._dispatch_ask_ai_turn(turn, message)

    def _fail_ask_ai_turn(self, message, error) -> None:
        category = classify_ask_ai_failure(error)
        proxy = error if isinstance(error, AiProxyError) else None
        cause = getattr(error, "__cause__", None)
        if proxy is None and isinstance(cause, AiProxyError):
            proxy = cause
        log_ask_ai_turn(
            operation="act_plan",
            stage="ui_fail",
            category=category,
            http_status=int(getattr(proxy or error, "status", 0) or 0),
            proxy_code=str(
                getattr(proxy, "code", "")
                or getattr(error, "reason", "")
                or getattr(error, "code", "")
                or "-"
            ),
            retry_attempted=bool(getattr(proxy, "retry_attempted", False)),
            stale_chain_retry=bool(getattr(proxy, "stale_chain_retry", False)),
            auth_retry=bool(getattr(proxy, "auth_retry", False)),
        )
        text = format_ai_user_message(error)
        auth = category == "auth"
        schema = category == "schema"
        budget = category == "budget"
        if message is not None and not getattr(message, "frozen", False):
            if auth and hasattr(message, "set_auth_card"):
                message.set_auth_card(text)
                return
            if schema and hasattr(message, "set_clarify_card"):
                message.set_clarify_card(t("images.ai.not_understood"))
                return
            if budget and _is_usage_limit_error(error) and _apply_ask_ai_usage_limit(message, error):
                return
            fail = getattr(message, "set_error_card", None)
            if callable(fail):
                fail(text if budget else t("images.ai.temporarily_unavailable"))
            else:
                message.fail(text if budget else t("images.ai.temporarily_unavailable"))
            return
        if isinstance(error, (AiBudgetExceeded, AiProxyError)):
            if budget and _is_usage_limit_error(error):
                message = self._ai_history.add_result_message(self._ask_ai_request_id)
                self._ask_ai_result_by_request[self._ask_ai_request_id] = message
                if _apply_ask_ai_usage_limit(message, error):
                    return
            self._add_ask_ai_local_text(text if auth or budget else t("images.ai.temporarily_unavailable"))
            return
        logger.error("Ask AI planner turn failed", exc_info=error)
        self._add_ask_ai_local_text(t("images.ai.temporarily_unavailable"))

    def _dispatch_ask_ai_turn(self, turn, message) -> None:
        query = getattr(turn, "query", "") or ""
        if getattr(turn, "planner_response_id", ""):
            self._ask_ai_planner_response_id = turn.planner_response_id
        if turn.kind == KIND_HELP:
            self._complete_ask_ai_text(message, t("images.ai.start.help.reply"))
            return
        if turn.kind == KIND_QUESTION:
            text = turn.message or t(turn.message_key or "images.ai.question_not_search")
            self._complete_ask_ai_text(message, text)
            return
        if turn.kind == KIND_UNSUPPORTED:
            self._show_ask_ai_unsupported(message, turn)
            return
        if turn.kind == KIND_CLARIFY:
            self._show_ask_ai_clarify(message, turn)
            return
        if turn.kind == KIND_ACT:
            set_phase = getattr(message, "set_phase", None)
            if callable(set_phase):
                set_phase("preparing")
            self._start_ask_ai_act(turn, processing=message)
            return
        if turn.kind == KIND_ACT_PLAN:
            set_phase = getattr(message, "set_phase", None)
            if callable(set_phase):
                set_phase("preparing")
            self._start_ask_ai_act_plan(turn, processing=message)
            return
        folder = self._get_folder_dir()
        self._start_semantic_index_from_ask_ai(folder)
        if self._ask_ai_pending_query is not None:
            self._ask_ai_pending_turn = turn
            self._update_ask_ai_prep_wait(turn.query or query, folder)
            return
        if self._should_wait_for_initial_prep():
            self._ask_ai_pending_turn = turn
            self._begin_ask_ai_prep_wait(turn.query or query, folder)
            return
        error = self._ask_ai_prep_error()
        if error is not None:
            if message is not None:
                if _is_usage_limit_error(error):
                    _apply_ask_ai_usage_limit(message, error)
                else:
                    message.fail(format_ai_user_message(error))
            return
        self._ask_ai_initial_prep_done = True
        if message is not None:
            set_phase = getattr(message, "set_phase", None)
            if callable(set_phase):
                set_phase("searching" if turn.kind != KIND_NARROW else "refining")
        self._start_ask_ai_meaning_search(turn.query or query, folder, isolate=False, turn=turn)

    def _complete_ask_ai_text(self, message, text: str) -> None:
        if message is not None and not getattr(message, "frozen", False):
            message.complete_text(text)
            return
        self._add_ask_ai_local_text(text)

    def _show_ask_ai_unsupported(self, message, turn) -> None:
        key = turn.message_key or "images.ai.not_available"
        raw = turn.message or t(key)
        title, body = _split_unsupported_copy(raw, key)
        if message is not None and hasattr(message, "set_unsupported_card") and not getattr(message, "frozen", False):
            message.set_unsupported_card(title, body)
            return
        self._complete_ask_ai_text(message, raw)

    def _show_ask_ai_clarify(self, message, turn) -> None:
        key = turn.message_key or "images.ai.not_understood"
        extra = ""
        if key == "images.ai.missing_target":
            extra = "images.ai.clarify_target"
        text = turn.message or t(key)
        if extra and extra != key and not turn.message:
            text = f"{text} {t(extra)}"
        chips = _clarify_chips_for(key, turn.query or "")
        if message is not None and hasattr(message, "set_clarify_card") and not getattr(message, "frozen", False):
            message.set_clarify_card(text, chips)
            return
        self._complete_ask_ai_text(message, text)

    def _on_ask_ai_chip(self, text: str) -> None:
        if not hasattr(self, "_action_input"):
            return
        payload = str(text or "").strip()
        if not payload:
            return
        self._action_input.setText(payload)
        self._on_ask_ai_send()

    def _on_ask_ai_sign_in(self) -> None:
        window = self.window()
        show = getattr(window, "_show_page", None)
        if not callable(show):
            return
        try:
            from app.ui.main_window import PAGE_ACCOUNT
        except ImportError:
            return
        show(PAGE_ACCOUNT)

    def _send_ask_ai_ui_preview(self, query: str) -> None:
        """Local chat UI only — never starts Meaning Search or facts generation."""
        self._action_input.clear()
        self._sync_action_send_enabled()
        if hasattr(self, "_ai_history"):
            self._ai_history.add_user_message(query)
        self._sync_workspace_selection()
        turn = route_ask_ai_turn(
            query,
            self._workspace.context,
            allow_ai=False,
            conversation=self._ask_ai_conversation_state(),
        )
        if turn.kind == KIND_HELP:
            self._add_ask_ai_local_text(t("images.ai.start.help.reply"))
            return
        if turn.kind in {KIND_UNSUPPORTED, KIND_QUESTION}:
            self._add_ask_ai_local_text(
                turn.message or t(turn.message_key or "images.ai.not_understood")
            )
            return
        if turn.kind == KIND_CLARIFY:
            reasons = set(turn.reasons or ())
            mock_chat = reasons & {
                "underspecified_search",
                "needs_planner",
                "planner_unavailable",
            }
            if not mock_chat:
                self._add_ask_ai_local_text(
                    turn.message or t(turn.message_key or "images.ai.not_understood")
                )
                return
        if turn.kind == KIND_ACT:
            self._start_ask_ai_act(turn)
            return
        if turn.kind == KIND_ACT_PLAN:
            self._start_ask_ai_act_plan(turn, preview=True)
            return
        if turn.kind == KIND_NARROW:
            self._send_ask_ai_preview_narrow(turn)
            return
        self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        message = self._ai_history.add_result_message(request_id, query=query)
        self._ask_ai_result_by_request[request_id] = message
        set_folder = getattr(message, "set_result_folder", None)
        if callable(set_folder):
            set_folder(self._get_folder_dir())
        message.set_searching(t("images.searching"))
        prior = list(self._ai_history.user_texts[:-1])
        reply = preview_reply_for(
            query, index=self._ask_ai_preview_seq, history=prior
        )
        self._ask_ai_preview_seq += 1
        timer = QTimer(self)
        timer.setSingleShot(True)

        def finish() -> None:
            if self._ask_ai_preview_timer is timer:
                self._ask_ai_preview_timer = None
            if request_id != self._ask_ai_request_id:
                return
            if reply.kind == "error":
                message.fail(f"{t('images.ai.error')} {reply.text}")
                return
            if reply.kind == "results":
                folder = self._get_folder_dir()
                files = (
                    sorted(self._get_png_files(folder), key=lambda path: path.name.lower())
                    if folder.exists()
                    else []
                )
                paths = preview_result_paths(files, reply)
                set_folder = getattr(message, "set_result_folder", None)
                if callable(set_folder):
                    set_folder(folder)
                status = self._ask_ai_chat_status(searching=False, count=len(paths))
                message.complete(paths, status)
                self._bind_ask_ai_ocr_image_ids(message)
                self._show_ask_ai_stored_results(query, paths)
                self._remember_workspace_results(paths, query, origin=ORIGIN_MEANING, narrowed=False)
                return
            message.complete_text(reply.text)

        timer.timeout.connect(finish)
        self._ask_ai_preview_timer = timer
        timer.start(reply.delay_ms)

    def _start_semantic_index_from_ask_ai(self, folder: Path) -> None:
        if self._ask_ai_ui_preview_enabled():
            return
        indexer = self._semantic_index_indexer
        if indexer is None or not folder.exists():
            return
        if not self._ask_ai_external_ready():
            return
        start = getattr(indexer, "start", None)
        if callable(start):
            start(folder, consented=True)

    def record_tour_ai_consent(self) -> None:
        """Store product consent. Does not start facts generation."""
        self._persist_ask_ai_consent()

    def start_tour_ai_preparation(self) -> str:
        """Start existing facts generation for the current folder. No Tutorial-only data."""
        if self._ask_ai_ui_preview_enabled():
            return "failed"
        folder = self._get_folder_dir()
        indexer = self._semantic_index_indexer
        if indexer is None or folder is None or not folder.exists():
            return "failed"
        if not self._ask_ai_external_ready():
            return "failed"
        snap = self.tour_ai_preparation_snapshot()
        if snap.get("running"):
            return "already"
        start = getattr(indexer, "start", None)
        if not callable(start):
            return "failed"
        started = start(folder, consented=True)
        after = self.tour_ai_preparation_snapshot()
        if after.get("error") and not after.get("running"):
            return "failed"
        if started:
            return "started"
        if int(after.get("needed") or 0) <= 0:
            return "ready"
        if after.get("running"):
            return "already"
        return "failed"

    def tour_ai_preparation_snapshot(self) -> dict:
        indexer = self._semantic_index_indexer
        snapshot = getattr(indexer, "snapshot", None) if indexer is not None else None
        if not callable(snapshot):
            return {}
        data = snapshot()
        return {
            "ready": int(getattr(data, "ready", 0) or 0),
            "total": int(getattr(data, "total", 0) or 0),
            "needed": int(getattr(data, "needed", 0) or 0),
            "running": bool(getattr(data, "running", False)),
            "error": getattr(data, "last_error", None) is not None,
        }

    def tour_local_preparation_snapshot(self) -> dict:
        bar = getattr(self, "_analysis_bar", None)
        reader = getattr(bar, "tour_local_snapshot", None) if bar is not None else None
        if callable(reader):
            data = reader()
            return data if isinstance(data, dict) else {}
        return {
            "ready": 0,
            "total": 0,
            "needed": 0,
            "running": False,
            "error": False,
        }

    def _cancel_semantic_index(self) -> None:
        indexer = self._semantic_index_indexer
        cancel = getattr(indexer, "cancel", None)
        if callable(cancel):
            cancel()

    def _start_ask_ai_meaning_search(
        self, query: str, folder: Path, *, isolate: bool = True, turn=None
    ) -> None:
        if self._ask_ai_ui_preview_enabled():
            return
        if isolate:
            self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        kind = getattr(turn, "kind", None) or KIND_FIND
        source = getattr(turn, "target_source", None) or SOURCE_RESULT_SET
        self._ask_ai_kind_by_request[request_id] = kind
        message = self._ask_ai_result_by_request.get(request_id)
        if message is None or getattr(message, "frozen", False):
            message = self._ai_history.add_result_message(request_id, query=query)
            self._ask_ai_result_by_request[request_id] = message
        set_query = getattr(message, "set_result_query", None)
        if callable(set_query):
            set_query(query)
        set_folder = getattr(message, "set_result_folder", None)
        if callable(set_folder):
            set_folder(folder)
        message.set_searching(
            self._meaning_bundle_preparing_text(meaning=True)
            or self._ask_ai_chat_status(searching=True)
        )
        self._begin_ask_ai_grid(query)
        provider = self._owned_vision_search_provider
        logger.info(
            "Ask-AI meaning search start request=%d query=%r kind=%s provider=%s",
            request_id,
            query,
            kind,
            type(provider).__name__ if not inspect.isfunction(provider) else provider.__name__,
        )
        candidates = self._search_candidates(folder)
        scope_ids = None
        if kind == KIND_NARROW:
            scoped = self._candidates_for_source(folder, source)
            if scoped:
                candidates = scoped
            ids, _paths = self._workspace.context.targets(source)
            scope_ids = ids or None
        task = ImagesSearchTask(
            request_id,
            query,
            folder,
            candidates,
            provider,
            "vision_relevance",
            scope_image_ids=scope_ids,
        )
        self._ask_ai_search_tasks[request_id] = task
        task.signals.progress.connect(self._progress_ask_ai_search)
        task.signals.finished.connect(self._finish_ask_ai_search)
        self._search_pool.start(task)

    def _sync_workspace_selection(self) -> None:
        paths = self._selected_image_paths()
        mapping = self._image_ids_for_paths(paths)
        self._workspace.set_selection(
            image_ids=tuple(mapping.get(result_path_key(path)) for path in paths if result_path_key(path) in mapping),
            paths=[str(path) for path in paths],
        )

    def _image_ids_for_paths(self, paths) -> dict[str, int]:
        mapping: dict[str, int] = {}
        missing: list[Path] = []
        known = self._workspace.context.path_to_image_id
        for path in paths or ():
            key = result_path_key(path)
            if key in known:
                mapping[key] = known[key]
            else:
                missing.append(Path(path))
        if missing:
            mapping.update(self._lookup_ocr_ids(missing))
            if mapping:
                self._workspace.remember_ids(mapping)
        return mapping

    def _lookup_ocr_ids(self, paths) -> dict[str, int]:
        mapping: dict[str, int] = {}
        if self._ask_ai_ui_preview_enabled():
            return mapping
        try:
            database = OCRDatabase().open()
        except OCRDatabaseError:
            return mapping
        try:
            repository = OCRRepository(database)
            for path in paths:
                try:
                    image = repository.get_image_by_path(path)
                except (OCRRecordNotFoundError, OCRDatabaseError, OSError):
                    continue
                mapping[result_path_key(path)] = int(image.image_id)
        except OCRDatabaseError:
            return mapping
        finally:
            database.close()
        return mapping

    def _remember_workspace_results(
        self, paths, query: str, *, origin: str, narrowed: bool
    ) -> None:
        visible = [Path(path) for path in paths or ()]
        mapping = self._image_ids_for_paths(visible)
        ids = tuple(
            mapping[result_path_key(path)]
            for path in visible
            if result_path_key(path) in mapping
        )
        folder = self._get_folder_dir()
        if narrowed:
            self._workspace.set_narrow(
                image_ids=ids,
                paths=[str(path) for path in visible],
                query=query,
                path_to_image_id=mapping,
            )
            return
        self._workspace.set_find(
            image_ids=ids,
            paths=[str(path) for path in visible],
            query=query,
            scope_folder=folder if folder.exists() else None,
            origin=origin,
            path_to_image_id=mapping,
        )

    def _candidates_for_source(self, folder: Path, source: str):
        _ids, paths = self._workspace.context.targets(source)
        if not paths:
            return ()
        wanted = {result_path_key(path) for path in paths}
        return tuple(
            (path, tags)
            for path, tags in self._search_candidates(folder)
            if result_path_key(path) in wanted
        )

    def _send_ask_ai_preview_narrow(self, turn) -> None:
        ids, stored = self._workspace.context.targets(turn.target_source)
        paths = [Path(path) for path in stored if is_existing_image_file(path)]
        if ids and not paths:
            paths = [
                Path(path)
                for path, image_id in self._workspace.context.path_to_image_id.items()
                if image_id in set(ids) and is_existing_image_file(path)
            ]
        needle = (turn.query or "").casefold()
        if needle:
            filtered = [path for path in paths if needle in path.name.casefold()]
            paths = filtered or paths[: max(1, len(paths) // 2)] if paths else []
        self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        message = self._ai_history.add_result_message(request_id, query=turn.query)
        self._ask_ai_result_by_request[request_id] = message
        status = t("images.ai.narrowed", count=len(paths))
        message.complete(paths, status)
        self._show_ask_ai_stored_results(turn.query, paths)
        self._remember_workspace_results(
            paths, turn.query, origin=ORIGIN_MEANING, narrowed=True
        )

    def _start_ask_ai_act(self, turn, processing=None) -> None:
        if processing is None:
            self._isolate_ask_ai_search()
        if turn.proposal is None:
            self._complete_ask_ai_text(processing, t("images.ai.not_understood"))
            return
        proposal, resolution = bind_action_proposal(
            turn.proposal,
            self._workspace.context,
            current_folder=self._get_folder_dir(),
        )
        if not resolution.ok:
            log_ask_ai_turn(
                operation="act_plan",
                stage="target_resolve",
                category="validation",
            )
            self._show_ask_ai_clarify(
                processing,
                AskAiTurn(
                    kind=KIND_CLARIFY,
                    query=turn.query,
                    message_key=getattr(resolution, "message_key", "") or "images.ai.missing_target",
                    message=self._target_clarify_text(resolution),
                ),
            )
            return
        request = proposal_to_request(
            proposal,
            current_folder=self._get_folder_dir(),
            screenshot_root=self._get_screenshot_root(),
        )
        plan = self._plan_action_request(request)
        message = self._confirm_from_processing(processing)
        runnable = sum(
            1 for item in plan.items if getattr(item, "status", "") in {"ready", "skipped"}
        )
        if request.action_id == ACTION_CREATE_FOLDER:
            runnable = plan.executable_count or sum(
                1 for item in plan.items if getattr(item, "status", "") == "skipped"
            )
        if runnable <= 0:
            issue_text = self._action_plan_clarify_text(plan) or t("images.ai.not_understood")
            message.fail(issue_text)
            return
        summary, detail, label = self._act_preview_copy(request, plan)
        message.set_preview(summary, detail, label)
        self._pending_act_request = request
        self._pending_act_message = message
        self._last_savable_request = request
        self._last_savable_plan = None
        self._tour_act_preview_widget = message
        emit_tour_event(
            UI_ACT_PREVIEW_SHOWN,
            action=getattr(request, "action_id", "") or "",
            generation=tour_event_generation(),
        )

    def _target_clarify_text(self, resolution) -> str:
        key = getattr(resolution, "message_key", "") or "images.ai.missing_target"
        text = t(key)
        hint = getattr(resolution, "hint_key", "") or ""
        if hint and hint != key:
            text = f"{text} {t(hint)}"
        return text

    def _action_plan_clarify_text(self, plan) -> str:
        codes = {
            str(getattr(item, "code", "") or "")
            for item in getattr(plan, "issues", ()) or ()
        }
        if "target_required" in codes:
            return f"{t('images.ai.missing_target')} {t('images.ai.clarify_target')}"
        if plan.issues:
            message = plan.issues[0].message or plan.issues[0].code
            if message == "At least one image is required.":
                return f"{t('images.ai.missing_target')} {t('images.ai.clarify_target')}"
            return message
        return ""

    def _ask_ai_conversation_state(self) -> dict:
        pending = getattr(self, "_pending_act_request", None)
        last = getattr(self, "_last_savable_request", None)
        pending_id = getattr(pending, "action_id", "") if pending is not None else ""
        last_id = getattr(last, "action_id", "") if last is not None else ""
        plan = getattr(self, "_last_savable_plan", None) or getattr(self, "_pending_prepared_plan", None)
        if not last_id and plan is not None:
            steps = getattr(getattr(plan, "plan", plan), "action_steps", lambda: ())()
            if steps:
                last_id = getattr(steps[0], "action_id", "") or ""
        return {
            "pending_action": pending_id,
            "last_confirmed_action": last_id,
            "planner_response_id": str(getattr(self, "_ask_ai_planner_response_id", "") or ""),
        }

    def _confirm_from_processing(self, processing):
        convert = getattr(self._ai_history, "convert_result_to_confirm", None)
        if processing is not None and callable(convert):
            for key, value in list(self._ask_ai_result_by_request.items()):
                if value is processing:
                    self._ask_ai_result_by_request.pop(key, None)
            return convert(processing)
        return self._ai_history.add_confirm_message()

    def _start_ask_ai_act_plan(self, turn, *, preview: bool = False, processing=None) -> None:
        if getattr(turn, "plan", None) is not None:
            self._begin_act_plan(turn.plan, preview=preview, processing=processing)
            return
        try:
            outcome = build_act_plan(
                turn.query,
                self._workspace.context,
                name_generator=default_name_generator if preview else getattr(self, "_act_plan_name_generator", None),
                images=self._act_plan_image_catalog(),
                allow_ai=not preview,
                complete_json=None if preview else getattr(self, "_act_plan_complete_json", None),
            )
        except (AiBudgetExceeded, AiProxyError) as exc:
            self._fail_ask_ai_turn(processing, exc)
            return
        except Exception as exc:
            self._fail_ask_ai_turn(processing, exc)
            return
        if outcome.status != "plan" or outcome.plan is None:
            key = outcome.message_key or "images.ai.not_understood"
            text = outcome.message or t(key)
            if key == "images.ai.missing_target" and not outcome.message:
                text = f"{text} {t('images.ai.clarify_target')}"
            self._complete_ask_ai_text(processing, text)
            return
        self._begin_act_plan(outcome.plan, preview=preview, processing=processing)

    def _begin_act_plan(self, plan, *, preview: bool = False, processing=None) -> None:
        search_steps = [step for step in plan.steps if step.type in {STEP_FIND, STEP_NARROW}]
        if search_steps:
            first = search_steps[0]
            fake = AskAiTurn(
                kind=KIND_NARROW if first.type == STEP_NARROW else KIND_FIND,
                query=first.query,
                target_source=first.target_source,
            )
            if preview:
                if first.type == STEP_NARROW:
                    self._send_ask_ai_preview_narrow(fake)
                else:
                    self._send_ask_ai_preview_find(fake)
                self._preview_remaining_act_plan(plan, next_index=1, preview=True, isolate=False)
                return
            folder = self._get_folder_dir()
            self._start_semantic_index_from_ask_ai(folder)
            if self._ask_ai_pending_query is not None:
                self._ask_ai_pending_turn = fake
                self._update_ask_ai_prep_wait(first.query, folder)
                self._pending_act_continuation = (plan, 1)
                return
            if self._should_wait_for_initial_prep():
                self._ask_ai_pending_turn = fake
                self._begin_ask_ai_prep_wait(first.query, folder)
                self._pending_act_continuation = (plan, 1)
                return
            error = self._ask_ai_prep_error()
            if error is not None:
                self._fail_ask_ai_turn(processing, error)
                return
            self._ask_ai_initial_prep_done = True
            self._start_ask_ai_meaning_search(
                first.query, folder, isolate=processing is None, turn=fake
            )
            self._pending_act_continuation = (plan, 1)
            return
        self._preview_remaining_act_plan(
            plan,
            next_index=0,
            preview=preview,
            isolate=processing is None,
            processing=processing,
        )

    def _send_ask_ai_preview_find(self, turn) -> None:
        folder = self._get_folder_dir()
        files = (
            sorted(self._get_png_files(folder), key=lambda path: path.name.lower())
            if folder.exists()
            else []
        )
        needle = (turn.query or "").casefold()
        paths = [path for path in files if needle in path.name.casefold()] if needle else files[:3]
        self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        message = self._ai_history.add_result_message(request_id, query=turn.query)
        self._ask_ai_result_by_request[request_id] = message
        status = self._ask_ai_chat_status(searching=False, count=len(paths))
        message.complete(paths, status)
        self._show_ask_ai_stored_results(turn.query, paths)
        self._remember_workspace_results(
            paths, turn.query, origin=ORIGIN_MEANING, narrowed=False
        )

    def _preview_remaining_act_plan(
        self,
        plan,
        *,
        next_index: int,
        preview: bool = False,
        isolate: bool = True,
        processing=None,
    ) -> None:
        remaining = plan.steps[next_index:]
        next_search = next((step for step in remaining if step.type in {STEP_FIND, STEP_NARROW}), None)
        if next_search is not None:
            search_index = plan.steps.index(next_search)
            fake = AskAiTurn(
                kind=KIND_NARROW if next_search.type == STEP_NARROW else KIND_FIND,
                query=next_search.query,
                target_source=next_search.target_source,
            )
            if preview:
                if next_search.type == STEP_NARROW:
                    self._send_ask_ai_preview_narrow(fake)
                else:
                    self._send_ask_ai_preview_find(fake)
                self._preview_remaining_act_plan(
                    plan, next_index=search_index + 1, preview=True, isolate=False
                )
                return
            folder = self._get_folder_dir()
            self._start_ask_ai_meaning_search(
                next_search.query, folder, isolate=processing is None, turn=fake
            )
            self._pending_act_continuation = (plan, search_index + 1)
            return
        if not plan.action_steps():
            self._complete_ask_ai_text(processing, t("images.ai.not_understood"))
            return
        if not self._workspace.context.has_targets(SOURCE_RESULT_SET) and any(
            step.action_id != ACTION_CREATE_FOLDER for step in plan.action_steps()
        ):
            self._complete_ask_ai_text(processing, t("images.ai.no_matches"))
            return
        self._show_prepared_act_plan(plan, isolate=isolate, processing=processing)

    def _show_prepared_act_plan(self, plan, *, isolate: bool = True, processing=None) -> None:
        if isolate:
            self._isolate_ask_ai_search()
        ocr, database = self._action_ocr()
        try:
            service = ActionService(
                ActionContext(
                    metadata=self._metadata_service,
                    ocr=ocr,
                    app_root=self._app_root,
                    managed_root=self._get_screenshot_root(),
                )
            )
            prepared = prepare_act_plan(
                plan,
                self._workspace.context,
                service,
                current_folder=self._get_folder_dir(),
                screenshot_root=self._get_screenshot_root(),
                preview_text=lambda steps_plan, requests, action_plans, context: build_combined_preview(
                    steps_plan, requests, action_plans, context, t=t
                ),
            )
        finally:
            if database is not None:
                database.close()
        if getattr(self, "_automation_auto_confirm", False):
            if not prepared.validation.ok or not prepared.preview.executable:
                key = prepared.validation.message_key or "images.ai.plan_rejected"
                text = t(key) if str(key).startswith("images.") else prepared.preview.summary
                if key == "images.ai.missing_target":
                    text = f"{text} {t('images.ai.clarify_target')}"
                self._complete_ask_ai_text(processing, text)
                return
            self._pending_prepared_plan = prepared
            self._pending_act_message = None
            self._last_savable_plan = plan
            self._last_savable_request = None
            self._execute_prepared_act_plan(None, prepared)
            return
        message = self._confirm_from_processing(processing)
        if not prepared.validation.ok or not prepared.preview.executable:
            key = prepared.validation.message_key or "images.ai.plan_rejected"
            text = t(key) if key.startswith("images.") else prepared.preview.summary
            if key == "images.ai.missing_target":
                text = f"{text} {t('images.ai.clarify_target')}"
            message.fail(text)
            return
        message.set_preview(
            prepared.preview.summary,
            prepared.preview.detail,
            prepared.preview.confirm_label,
        )
        self._pending_prepared_plan = prepared
        self._pending_act_message = message
        self._last_savable_plan = plan
        self._last_savable_request = None
        self._tour_act_preview_widget = message
        action_ids = {
            str(getattr(step, "action_id", "") or "")
            for step in getattr(plan, "steps", ())
        }
        action = ACTION_ADD_TAG if ACTION_ADD_TAG in action_ids else next(iter(action_ids), "")
        emit_tour_event(
            UI_ACT_PREVIEW_SHOWN,
            action=action,
            generation=tour_event_generation(),
        )

    def _act_plan_image_catalog(self) -> tuple[dict, ...]:
        ctx = self._workspace.context
        ids, paths = ctx.targets(SOURCE_RESULT_SET)
        selected_ids = set(ctx.selected_image_ids or ())
        selected_paths = {str(path) for path in ctx.selected_paths or ()}
        items: list[dict] = []
        for index, image_id in enumerate(ids):
            path = Path(paths[index]) if index < len(paths) else None
            name = path.name if path is not None else ""
            tags: list[str] = []
            if path is not None:
                try:
                    tags = list(self._metadata_service.get_image_tags(path.parent, path.name))
                except OSError:
                    tags = []
            selected = int(image_id) in selected_ids or (
                path is not None and str(path) in selected_paths
            )
            items.append({
                "image_id": int(image_id),
                "name": name,
                "tags": tags,
                "selected": selected,
            })
        return tuple(items)

    def _continue_act_plan_after_search(self) -> None:
        continuation = self._pending_act_continuation
        self._pending_act_continuation = None
        if not continuation:
            return
        plan, next_index = continuation
        self._preview_remaining_act_plan(plan, next_index=next_index, isolate=False)

    def _plan_action_request(self, request: ActionRequest):
        ocr, database = self._action_ocr()
        try:
            return ActionService(
                ActionContext(
                    metadata=self._metadata_service,
                    ocr=ocr,
                    app_root=self._app_root,
                    managed_root=self._get_screenshot_root(),
                )
            ).plan(request)
        finally:
            if database is not None:
                database.close()

    def _act_preview_copy(self, request: ActionRequest, plan) -> tuple[str, str, str]:
        count = plan.item_count or plan.executable_count
        dest = Path(str(plan.summary.get("destination_path") or request.param("destination_path") or ""))
        dest_name = dest.name if dest.name else str(dest)
        if request.action_id == ACTION_MOVE:
            detail_parts = []
            if dest_name:
                detail_parts.append(t("images.ai.destination_line", name=dest_name))
            if (plan.summary or {}).get("destination_will_create") or any(
                getattr(found, "code", "") == "destination_will_create"
                for found in getattr(plan, "issues", ()) or ()
            ):
                detail_parts.append(t("images.ai.will_create_destination", name=dest_name or dest.name))
            return (
                t("images.ai.will_move_count", count=count),
                "\n".join(part for part in detail_parts if part),
                t("images.ai.confirm_move"),
            )
        if request.action_id == ACTION_ADD_TAG:
            tag = _request_tag_label(request)
            return (
                t("images.ai.will_tag_count", count=count, tag=tag),
                "",
                t("images.ai.confirm_tag"),
            )
        if request.action_id == ACTION_REMOVE_TAG:
            tag = _request_tag_label(request)
            return (
                t("images.ai.will_remove_tag_count", count=count, tag=tag),
                "",
                t("images.ai.confirm_remove_tag"),
            )
        if request.action_id == ACTION_REMOVE_ALL_TAGS:
            removed: list[str] = []
            seen_removed: set[str] = set()
            no_tags = 0
            for item in getattr(plan, "items", ()) or ():
                if getattr(item, "status", "") == "skipped":
                    no_tags += 1
                for tag in (getattr(item, "after", None) or {}).get("removed_tags") or ():
                    if tag and tag not in seen_removed:
                        seen_removed.add(tag)
                        removed.append(str(tag))
            parts = [t("images.ai.plan_image_count", count=count)]
            if removed:
                shown = removed[:8]
                parts.append(t("images.ai.plan_tags_to_remove", tags=", ".join(shown)))
                leftover = len(removed) - len(shown)
                if leftover > 0:
                    parts.append(t("images.ai.plan_tags_more", count=leftover))
            if no_tags:
                parts.append(t("images.ai.plan_no_tags_count", count=no_tags))
            return (
                t("images.ai.preview_remove_all_tags"),
                "\n".join(parts),
                t("images.ai.confirm_remove_all_tags"),
            )
        if request.action_id == ACTION_REPLACE_TAGS:
            tag = _request_tag_label(request)
            detail = _replace_preview_detail(plan)
            return (
                t("images.ai.will_replace_tags_count", count=count, tag=tag),
                detail,
                t("images.ai.confirm_replace_tags"),
            )
        if request.action_id == ACTION_RENAME:
            pairs = []
            for item in plan.items:
                before = str((item.before or {}).get("name") or "")
                after = str((item.after or {}).get("name") or "")
                if before or after:
                    pairs.append(t("images.ai.rename_from_to", before=before, after=after))
            detail = "\n".join(pairs[:8])
            if len(pairs) > 8:
                detail = f"{detail}\n{t('images.ai.rename_more', count=len(pairs) - 8)}"
            return (
                t("images.ai.will_rename_count", count=count),
                detail,
                t("images.ai.confirm_rename"),
            )
        if request.action_id == ACTION_CREATE_FOLDER:
            name = str(request.param("name") or "")
            return (
                t("images.ai.will_create_folder", name=name),
                "",
                t("images.ai.confirm_folder"),
            )
        if request.action_id == ACTION_ADD_FAVORITE:
            return (
                t("images.ai.will_favorite_count", count=count),
                "",
                t("images.ai.confirm_favorite"),
            )
        if request.action_id == ACTION_REMOVE_FAVORITE:
            return (
                t("images.ai.will_unfavorite_count", count=count),
                "",
                t("images.ai.confirm_unfavorite"),
            )
        return t("images.ai.not_understood"), "", t("images.ai.confirm")

    def _on_ask_ai_act_confirmed(self, message) -> None:
        if getattr(message, "frozen", False):
            return
        if self._action_executing or getattr(message, "executing", False):
            return
        count = self._act_execute_count(message)
        set_exec = getattr(message, "set_executing", None)
        if callable(set_exec):
            set_exec(
                t("images.ai.updating_count", count=count)
                if count
                else t("images.ai.preparing_changes")
            )
        self._action_executing = True
        QTimer.singleShot(0, lambda: self._run_confirmed_ask_ai_act(message))

    def _act_execute_count(self, message) -> int:
        prepared = getattr(self, "_pending_prepared_plan", None)
        if prepared is not None and message is self._pending_act_message:
            preview = getattr(prepared, "preview", None)
            for attr in ("image_count", "item_count", "count", "executable_count"):
                value = getattr(preview, attr, None)
                if value:
                    return int(value)
            plans = getattr(prepared, "action_plans", None) or ()
            total = 0
            for plan in plans:
                total += int(
                    getattr(plan, "item_count", 0) or getattr(plan, "executable_count", 0) or 0
                )
            if total:
                return total
        request = self._pending_act_request
        if request is not None:
            targets = getattr(request, "targets", None) or ()
            if targets:
                return len(tuple(targets))
        return 0

    def _run_confirmed_ask_ai_act(self, message) -> None:
        try:
            prepared = getattr(self, "_pending_prepared_plan", None)
            if prepared is not None and message is self._pending_act_message:
                self._execute_prepared_act_plan(message, prepared)
                return
            request = self._pending_act_request
            if request is None or message is not self._pending_act_message:
                return
            result = self._execute_action(request, confirmed=True)
            self._pending_act_request = None
            self._pending_act_message = None
            text = summarize_action_result(result, t=t, parameters=request.parameters)
            failed_for_user = action_result_is_user_failure(result)
            warning = (not failed_for_user) and (
                getattr(result, "status", "") == "partial" or result.failed_count > 0
            )
            if failed_for_user:
                message.fail(text)
                emit_tour_event(
                    UI_ACT_COMPLETED,
                    ok=False,
                    action=request.action_id,
                    generation=tour_event_generation(),
                )
                return
            message.complete(text, warning=warning)
            emit_tour_event(
                UI_ACT_COMPLETED,
                ok=True,
                action=request.action_id,
                generation=tour_event_generation(),
            )
            self._refresh_after_action_results(
                (result,),
                filesystem_changed=request.action_id
                in {ACTION_MOVE, ACTION_RENAME, ACTION_CREATE_FOLDER},
            )
        finally:
            self._action_executing = False

    def _execute_prepared_act_plan(self, message, prepared) -> None:
        if getattr(self, "_pending_prepared_plan", None) is not prepared:
            return
        self._pending_prepared_plan = None
        self._pending_act_message = None
        ocr, database = self._action_ocr()
        try:
            service = ActionService(
                ActionContext(
                    metadata=self._metadata_service,
                    ocr=ocr,
                    app_root=self._app_root,
                    managed_root=self._get_screenshot_root(),
                )
            )
            result = execute_act_plan(
                prepared,
                service,
                confirmed=True,
                current_folder=self._get_folder_dir(),
                screenshot_root=self._get_screenshot_root(),
                context=self._workspace.context,
            )
        finally:
            if database is not None:
                database.close()
        self._pending_prepared_plan = None
        self._pending_act_message = None
        text = summarize_combined_result(result, t=t)
        warning = (not combined_result_is_user_failure(result)) and (
            getattr(result, "status", "") == "partial"
            or any(
                getattr(item, "failed_count", 0)
                for _step, item in result.steps
                if item is not None
            )
        )
        if combined_result_is_user_failure(result):
            if message is not None:
                message.fail(text)
            elif not self._automation_run_id:
                QMessageBox.warning(self, t("automation.run_title"), text)
            emit_tour_event(
                UI_ACT_COMPLETED,
                ok=False,
                action="plan",
                generation=tour_event_generation(),
            )
            self._finish_automation_run(False, text)
            return
        if message is not None:
            message.complete(text, warning=warning)
        action_ids = {step.action_id for step, _item in result.steps if step.type == STEP_ACTION}
        action = ACTION_ADD_TAG if ACTION_ADD_TAG in action_ids else (next(iter(action_ids), "plan") if action_ids else "plan")
        emit_tour_event(
            UI_ACT_COMPLETED,
            ok=True,
            action=action,
            generation=tour_event_generation(),
        )
        self._refresh_after_action_results(
            [item for _step, item in result.steps if item is not None],
            filesystem_changed=bool(
                action_ids & {ACTION_MOVE, ACTION_RENAME, ACTION_CREATE_FOLDER}
            ),
        )
        self._finish_automation_run(True, text)

    def _on_ask_ai_act_cancelled(self, message) -> None:
        if message is not self._pending_act_message:
            return
        self._pending_act_request = None
        self._pending_prepared_plan = None
        self._pending_act_message = None
        cancelled = getattr(message, "set_cancelled", None)
        if callable(cancelled):
            cancelled(t("images.ai.act_cancelled"))
        else:
            message.complete(t("images.ai.act_cancelled"))

    def _finish_automation_run(self, ok: bool, message: str = "") -> None:
        run_id = str(getattr(self, "_automation_run_id", "") or "")
        if not run_id:
            self._automation_auto_confirm = False
            return
        self._automation_run_id = ""
        self._automation_auto_confirm = False
        self.automation_run_finished.emit(run_id, ok, message)

    def _abort_pending_automation_run(self, message: str) -> None:
        if not getattr(self, "_automation_run_id", ""):
            return
        self._pending_act_continuation = None
        self._finish_automation_run(False, message)

    def run_automation_workflow(self, workflow, *, auto_confirm: bool = False) -> None:
        """Re-evaluate Trigger / Target, then preview or execute after dialog confirm."""
        from app.automation import validate_workflow
        from app.workspace.plan import STEP_FIND, STEP_NARROW

        self._automation_auto_confirm = bool(auto_confirm)
        self._automation_run_id = workflow.id if auto_confirm else ""
        if not auto_confirm:
            self._show_ai_panel()
            if not getattr(self, "_ai_panel_expanded", False):
                self._automation_auto_confirm = False
                return
        validation = validate_workflow(workflow)
        if hasattr(self, "_ai_history") and not auto_confirm:
            self._ai_history.add_user_message(t("automation.run_prompt", name=workflow.name))
        if not validation.ok:
            self._add_ask_ai_local_text(t(validation.message_key or "automation.invalid"))
            return
        folder = Path(workflow.scope_folder) if workflow.scope_folder else self._get_folder_dir()
        if workflow.scope_folder:
            try:
                folder_ok = folder.is_dir()
            except OSError:
                folder_ok = False
            if not folder_ok:
                self._add_ask_ai_local_text(t("automation.missing_folder"))
                return
            current = self._get_folder_dir()
            if result_path_key(folder) != result_path_key(current):
                self.open_folder(folder)
                if not auto_confirm:
                    self._show_ai_panel()
        preview = self._ask_ai_ui_preview_enabled()
        search_steps = [step for step in workflow.plan.steps if step.type in {STEP_FIND, STEP_NARROW}]
        origin = workflow.origin or ORIGIN_MEANING
        if not search_steps:
            files = (
                sorted(self._get_png_files(folder), key=lambda path: path.name.lower())
                if folder.exists()
                else []
            )
            self._remember_workspace_results(files, "", origin=ORIGIN_BROWSE, narrowed=False)
            self._preview_remaining_act_plan(workflow.plan, next_index=0, preview=preview)
            return
        if origin == ORIGIN_TEXT:
            query = search_steps[0].query
            if preview:
                files = (
                    sorted(self._get_png_files(folder), key=lambda path: path.name.lower())
                    if folder.exists()
                    else []
                )
                needle = query.casefold()
                paths = [path for path in files if needle in path.name.casefold()] if needle else files
            else:
                paths = self._local_search_matches(query)
                try:
                    indexed = search_indexed_images(query, folder, self._search_candidates(folder))
                    paths = self._merge_search_paths(paths, list(indexed))
                except Exception:
                    pass
            self._remember_workspace_results(paths, query, origin=ORIGIN_TEXT, narrowed=False)
            self._preview_remaining_act_plan(workflow.plan, next_index=1, preview=preview)
            return
        self._begin_act_plan(workflow.plan, preview=preview)

    def _on_ask_ai_save_automation(self, _message) -> None:
        workflow = self._draft_automation_workflow()
        if workflow is None:
            self._add_ask_ai_local_text(t("automation.invalid"))
            return
        from app.ui.automation_save_dialog import AutomationSaveDialog

        dialog = AutomationSaveDialog(
            self,
            title=t("automation.save_title"),
            name=workflow.name,
            description=workflow.description,
            confirm_label=t("automation.save"),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        workflow = workflow.with_name(
            dialog.workflow_name(), description=dialog.workflow_description()
        )
        try:
            self._automation_service.save(workflow)
        except WorkflowValidationError:
            self._add_ask_ai_local_text(t("automation.invalid"))
            return
        self._add_ask_ai_local_text(t("automation.saved"))
        emit_tour_event(UI_AUTOMATION_SAVED, generation=tour_event_generation())

    def _draft_automation_workflow(self):
        ctx = self._workspace.context
        plan = self._last_savable_plan
        if plan is None and getattr(self, "_pending_prepared_plan", None) is not None:
            plan = self._pending_prepared_plan.plan
        request = self._last_savable_request or self._pending_act_request
        if plan is not None:
            return workflow_from_session(
                name=default_workflow_name(plan),
                context=ctx,
                plan=plan,
            )
        if request is None:
            return None
        parameters = sanitize_step_parameters(request.action_id, request.parameters)
        if request.action_id == ACTION_MOVE and not parameters.get("destination_name"):
            dest = Path(str(request.param("destination_path") or ""))
            if dest.name:
                parameters["destination_name"] = dest.name
        return workflow_from_session(
            name="",
            context=ctx,
            action_id=request.action_id,
            parameters=parameters,
        )

    def _show_ask_ai_stored_results(self, query: str, paths) -> None:
        """Show stored result paths in the grid. Does not search or call APIs."""
        visible = [
            Path(path)
            for path in paths or ()
            if is_existing_image_file(path)
        ]
        self._begin_ask_ai_grid(query, searching=False)
        self._apply_ask_ai_grid_paths(visible, searching=False)

    def _restore_ask_ai_result_grid(self, message) -> None:
        """Re-display this message's stored images. Does not re-run Meaning Search."""
        query = getattr(message, "result_query", "") or ""
        visible = self._resolve_ask_ai_result_paths(message)
        target = primary_result_folder(
            visible, getattr(message, "result_folder", None)
        )
        if target is not None:
            visible = paths_in_folder(visible, target)
            current = self._get_folder_dir()
            if result_path_key(current) != result_path_key(target):
                self.open_folder(target)
            else:
                self._isolate_ask_ai_search()
        else:
            self._isolate_ask_ai_search()
        self._show_ask_ai_stored_results(query, visible)
        self._remember_workspace_results(
            visible, query, origin=ORIGIN_MEANING, narrowed=False
        )

    def _resolve_ask_ai_result_paths(self, message) -> list[Path]:
        stored = list(getattr(message, "paths", []) or [])
        missing = [path for path in stored if not is_existing_image_file(path)]
        ocr_ids = getattr(message, "ocr_image_ids", {}) or {}
        ocr_records = self._ask_ai_ocr_records_for_ids(ocr_ids) if missing else []
        return resolve_stored_result_paths(
            stored,
            ocr_ids=ocr_ids,
            ocr_records=ocr_records,
            lookup_folders=self._ask_ai_restore_lookup_folders(stored, message),
        )

    def _ask_ai_restore_lookup_folders(self, stored_paths, message) -> list[Path]:
        folders: list[Path] = []
        seen: set[str] = set()

        def add(folder: Path | str | None) -> None:
            if folder is None:
                return
            path = Path(folder)
            try:
                if not path.is_dir():
                    return
                key = result_path_key(path)
            except OSError:
                return
            if key in seen:
                return
            seen.add(key)
            folders.append(path)

        add(self._get_folder_dir())
        add(getattr(message, "result_folder", None))
        for stored in stored_paths:
            add(Path(stored).parent)
        for item in list_recent_folders(self._config):
            add(item)
        for item in list_favorite_folders(self._config):
            add(item)
        root = self._get_screenshot_root()
        add(root)
        for child in list_child_folders(root):
            add(child)
        return folders

    def _ask_ai_ocr_records_for_ids(self, ocr_ids: dict[str, int]) -> list:
        if self._ask_ai_ui_preview_enabled():
            return []
        wanted = {int(image_id) for image_id in dict(ocr_ids or {}).values()}
        if not wanted:
            return []
        try:
            database = OCRDatabase().open()
        except OCRDatabaseError:
            return []
        try:
            repository = OCRRepository(database)
            records = []
            for image_id in wanted:
                try:
                    records.append(repository.get_image(image_id))
                except (OCRRecordNotFoundError, OCRDatabaseError):
                    continue
            return records
        except OCRDatabaseError:
            return []
        finally:
            database.close()

    def _bind_ask_ai_ocr_image_ids(self, message) -> None:
        if self._ask_ai_ui_preview_enabled():
            return
        bind = getattr(message, "bind_ocr_image_ids", None)
        if message is None or not callable(bind):
            return
        if getattr(message, "ocr_image_ids", None):
            return
        paths = list(getattr(message, "paths", []) or [])
        if not paths:
            return
        mapping: dict[str, int] = {}
        try:
            database = OCRDatabase().open()
        except OCRDatabaseError:
            return
        try:
            repository = OCRRepository(database)
            for path in paths:
                try:
                    image = repository.get_image_by_path(path)
                except (OCRRecordNotFoundError, OCRDatabaseError, OSError):
                    continue
                mapping[result_path_key(path)] = int(image.image_id)
        except OCRDatabaseError:
            return
        finally:
            database.close()
        if mapping:
            bind(mapping)

    def _on_ask_ai_start_action(self, action_id: str) -> None:
        """Local Start Menu only — never starts Meaning Search or facts generation."""
        if action_id == "find":
            self._add_ask_ai_local_text(t("images.ai.start.find.prompt"))
            self._action_input.setFocus(Qt.OtherFocusReason)
            return
        if action_id == "help":
            self._add_ask_ai_local_text(t("images.ai.start.help.reply"))
            self._action_input.setFocus(Qt.OtherFocusReason)

    def _add_ask_ai_local_text(self, text: str) -> None:
        if getattr(self, "_automation_run_id", ""):
            self._finish_automation_run(False, text)
            return
        if getattr(self, "_automation_auto_confirm", False):
            self._automation_auto_confirm = False
            if text.strip():
                QMessageBox.warning(self.window() or self, t("automation.run_title"), text)
            return
        if not text.strip() or not hasattr(self, "_ai_history"):
            return
        current = self._ask_ai_result_by_request.get(getattr(self, "_ask_ai_request_id", None))
        if current is not None and not getattr(current, "frozen", False):
            complete = getattr(current, "complete_text", None)
            if callable(complete):
                complete(text)
                return
        self._isolate_ask_ai_search()
        request_id = self._ask_ai_request_id
        message = self._ai_history.add_result_message(request_id)
        self._ask_ai_result_by_request[request_id] = message
        message.complete_text(text)

    def _ask_ai_existing_paths(self, result_paths) -> list[Path]:
        folder = self._get_folder_dir()
        if not folder.exists():
            return []
        existing = {str(path.resolve()): path for path in self._get_png_files(folder)}
        return [
            existing[str(Path(path).resolve())]
            for path in result_paths or ()
            if str(Path(path).resolve()) in existing
        ]

    def _progress_ask_ai_search(
        self, request_id, query, folder, result_paths, checked_count, total_count
    ) -> None:
        if request_id != self._ask_ai_request_id:
            return
        if folder != str(self._get_folder_dir().resolve()):
            return
        message = self._ask_ai_result_by_request.get(request_id)
        if message is None or getattr(message, "frozen", False):
            return
        visible = self._ask_ai_existing_paths(result_paths)
        message.add_paths(visible)
        message.set_searching(self._ask_ai_chat_status(searching=True, count=len(visible)))
        self._apply_ask_ai_grid_paths(visible, searching=True)

    def _finish_ask_ai_search(
        self,
        request_id: int,
        query: str,
        folder: str,
        result_paths: object,
        error: object,
    ) -> None:
        task = self._ask_ai_search_tasks.pop(request_id, None)
        if request_id != self._ask_ai_request_id:
            logger.info(
                "Ask-AI meaning search ignored request=%d current_request=%d reason=stale_request",
                request_id, self._ask_ai_request_id,
            )
            return
        if folder != str(self._get_folder_dir().resolve()):
            logger.info(
                "Ask-AI meaning search ignored request=%d query=%r reason=stale_folder",
                request_id, query,
            )
            return
        message = self._ask_ai_result_by_request.get(request_id)
        if message is None or getattr(message, "frozen", False):
            return
        cancelled = getattr(task, "_cancelled", None)
        if cancelled is not None and cancelled.is_set():
            message.freeze()
            if self._ask_ai_grid_query:
                self._set_ask_ai_grid_status(
                    self._ask_ai_grid_query,
                    len(self._ask_ai_grid_paths),
                    searching=False,
                )
            self._abort_pending_automation_run(t("images.ai.act_cancelled"))
            emit_tour_event(
                UI_FIND_FAILED,
                reason="cancelled",
                ok=False,
                generation=self._tour_search_generation,
            )
            return
        if error is not None:
            logger.error(
                "Ask-AI meaning search failed request=%d query=%r error_type=%s error=%s",
                request_id, query, type(error).__name__, error,
            )
            reason = _tour_find_fail_reason(error)
            if isinstance(error, (AiBudgetExceeded, AiProxyError)):
                fail_text = format_ai_user_message(error)
                if _is_usage_limit_error(error):
                    _apply_ask_ai_usage_limit(message, error)
                else:
                    message.fail(fail_text)
                if self._ask_ai_grid_query:
                    self._set_ask_ai_grid_status(
                        self._ask_ai_grid_query,
                        len(self._ask_ai_grid_paths),
                        searching=False,
                    )
                self._abort_pending_automation_run(fail_text)
                emit_tour_event(
                    UI_FIND_FAILED,
                    reason=reason,
                    ok=False,
                    generation=self._tour_search_generation,
                )
                return
            detail = format_ai_user_message(error) if isinstance(error, RelevanceProviderError) else t("images.search_error_body")
            fail_text = f"{t('images.ai.error')} {detail}"
            message.fail(fail_text)
            if self._ask_ai_grid_query:
                self._set_ask_ai_grid_status(
                    self._ask_ai_grid_query,
                    len(self._ask_ai_grid_paths),
                    searching=False,
                )
            self._abort_pending_automation_run(fail_text)
            emit_tour_event(
                UI_FIND_FAILED,
                reason=reason,
                ok=False,
                generation=self._tour_search_generation,
            )
            return
        visible = self._ask_ai_existing_paths(result_paths)
        kind = self._ask_ai_kind_by_request.pop(request_id, KIND_FIND)
        if kind == KIND_NARROW:
            allowed = {result_path_key(path) for path in self._workspace.context.result_paths}
            if self._workspace.context.selected_paths and not allowed:
                allowed = {result_path_key(path) for path in self._workspace.context.selected_paths}
            if allowed:
                visible = [path for path in visible if result_path_key(path) in allowed]
            status = t("images.ai.narrowed", count=len(visible))
            self._remember_workspace_results(
                visible, query, origin=self._workspace.context.origin or ORIGIN_MEANING, narrowed=True
            )
            self._ask_ai_grid_paths = []
            self._list_widget.clear()
        else:
            status = self._ask_ai_chat_status(searching=False, count=len(visible))
            self._remember_workspace_results(
                visible, query, origin=ORIGIN_MEANING, narrowed=False
            )
        message.complete(visible, status)
        self._bind_ask_ai_ocr_image_ids(message)
        self._apply_ask_ai_grid_paths(visible, searching=False)
        emit_tour_event(
            UI_FIND_FINISHED,
            ok=len(visible) > 0,
            result_count=len(visible),
            ai=True,
            kind="meaning",
            generation=self._tour_search_generation,
        )
        self._continue_act_plan_after_search()

    def _show_action_message(self, summary: str, detail: str) -> None:
        self._action_summary_label.setText(summary)
        self._action_detail_label.setText(detail)
        self._action_detail_label.setVisible(bool(detail))
        self._action_next_btn.hide()
        self._action_preview.show()

    def _append_ai_history(self, role: str, text: str) -> None:
        if not hasattr(self, "_ai_history") or not text.strip():
            return
        if role == "user":
            self._ai_history.add_user_message(text.strip())

    def _invalidate_action_confirmation(self, *_args) -> None:
        self._pending_action_plan = None
        self._pending_action_paths = {}
        self._pending_act_request = None
        if hasattr(self, "_pending_prepared_plan"):
            self._pending_prepared_plan = None
        if hasattr(self, "_ai_history"):
            freeze_confirms = getattr(self._ai_history, "freeze_pending_confirms", None)
            if callable(freeze_confirms):
                freeze_confirms()
        if hasattr(self, "_action_next_btn"):
            self._action_next_btn.setEnabled(False)
            self._action_next_btn.hide()

    def _finish_action_preview(
        self, request_id, instruction, folder, plan, result_paths, error
    ) -> None:
        self._action_tasks.pop(request_id, None)
        if request_id != self._action_request_id:
            return
        self._sync_action_send_enabled()
        if folder != str(self._get_folder_dir().resolve()):
            return
        if error is not None or plan is None:
            self._show_action_message(
                t("images.ai.error"), t("images.ai.try_again")
            )
            return

        reasons = set(plan.ambiguity_reasons)
        if plan.clarification_required:
            if "no_matches" in reasons:
                summary = t("images.ai.no_matches")
                detail = t("images.ai.rephrase_target")
            elif "missing_search_query" in reasons:
                summary = t("images.ai.missing_target")
                detail = t("images.ai.describe_target")
            else:
                summary = t("images.ai.not_understood")
                detail = t("images.ai.try_again")
            self._show_action_message(summary, detail)
            return

        if plan.action is ActionType.TAG and not plan.action_parameters.tag:
            self._show_action_message(
                t("images.ai.missing_parameter"), t("images.ai.which_tag")
            )
            return
        if plan.action is ActionType.MOVE and not plan.action_parameters.destination_folder:
            self._show_action_message(
                t("images.ai.missing_parameter"), t("images.ai.which_destination")
            )
            return

        paths = tuple(Path(path) for path in result_paths)
        count = len(paths)
        if plan.action is ActionType.SEARCH:
            summary = t("images.ai.found", count=count)
            detail = t("images.ai.target_description", query=plan.search_query)
        elif plan.action is ActionType.TAG:
            summary = t("images.ai.found", count=count)
            detail = t(
                "images.ai.will_tag", tag=plan.action_parameters.tag
            )
        elif plan.action is ActionType.MOVE:
            summary = t("images.ai.found", count=count)
            detail = t(
                "images.ai.will_move",
                destination=plan.action_parameters.destination_folder,
            )
        else:
            self._show_action_message(
                t("images.ai.not_available"), t("images.ai.try_again")
            )
            return

        self._action_summary_label.setText(summary)
        self._action_detail_label.setText(detail)
        self._action_detail_label.show()
        can_execute_tag = (
            plan.action is ActionType.TAG
            and bool(plan.matched_image_ids)
            and bool(plan.action_parameters.tag)
            and not plan.clarification_required
            and plan.confirmation_required
            and len(paths) == len(plan.matched_image_ids)
        )
        self._pending_action_plan = plan if can_execute_tag else None
        self._pending_action_paths = (
            dict(zip(plan.matched_image_ids, paths)) if can_execute_tag else {}
        )
        self._action_next_btn.setText(
            t("images.ai.apply_tag", count=count, tag=plan.action_parameters.tag)
            if can_execute_tag else t("images.ai.confirm")
        )
        self._action_next_btn.setToolTip("")
        self._action_next_btn.setEnabled(can_execute_tag)
        self._action_next_btn.setVisible(can_execute_tag)
        self._action_preview.show()

        self._search_debounce.stop()
        self._search_input.blockSignals(True)
        self._search_input.setText(plan.search_query)
        self._search_input.blockSignals(False)
        self._active_search_query = plan.search_query
        existing = {
            str(path.resolve()): path for path in self._get_png_files(self._get_folder_dir())
        }
        visible_paths = [
            existing[str(path.resolve())] for path in paths
            if str(path.resolve()) in existing
        ]
        self._update_search_feedback(
            plan.search_query, len(visible_paths), len(existing)
        )
        restored = self._populate_list(
            visible_paths, self._get_selected_path(), preserve_order=True
        )
        if not restored:
            self._clear_preview()

    def _on_action_confirmed(self) -> None:
        if self._action_executing or self._pending_action_plan is None:
            return
        plan = self._pending_action_plan
        preview_paths = dict(self._pending_action_paths)
        self._action_executing = True
        self._action_next_btn.setEnabled(False)
        try:
            result = self._action_executor(plan, preview_paths, self._metadata_service)
            changed_paths = [
                preview_paths[image_id]
                for image_id in result.succeeded_image_ids
                if image_id in preview_paths
            ]
            for path in changed_paths:
                self._update_list_for_tag_change(path)
            selected = self._get_selected_path()
            if selected and Path(selected) in changed_paths:
                self._display_tags(Path(selected))
            self._action_summary_label.setText(t(
                "images.ai.tag_applied", count=len(result.succeeded_image_ids),
                tag=normalize_tag(plan.action_parameters.tag or ""),
            ))
            self._action_detail_label.setText(t(
                "images.ai.tag_result",
                skipped=len(result.skipped_image_ids),
                failed=len(result.failed_image_ids),
            ))
            self._action_detail_label.setVisible(
                bool(result.skipped_image_ids or result.failed_image_ids)
            )
            if result.failed_image_ids:
                self._action_next_btn.setEnabled(True)
                self._action_next_btn.show()
            else:
                self._invalidate_action_confirmation()
        except Exception:
            self._action_summary_label.setText(t("images.ai.execute_failed"))
            self._action_detail_label.setText(t("images.ai.execute_retry"))
            self._action_detail_label.show()
            self._action_next_btn.setEnabled(True)
            self._action_next_btn.show()
        finally:
            self._action_executing = False

    def _finish_unified_search(
        self,
        request_id: int,
        query: str,
        folder: str,
        result_paths: object,
        error: object,
    ) -> None:
        task = self._search_tasks.pop(request_id, None)
        progressive_visible = self._progressive_visible_paths.pop(request_id, None)
        local_matches = self._local_search_by_request.pop(request_id, [])
        started = self._search_started_at.pop(request_id, None)
        if request_id != self._search_request_id:
            logger.info(
                "Images-search callback ignored request=%d current_request=%d reason=stale_request",
                request_id, self._search_request_id,
            )
            return
        if query != self._active_search_query:
            logger.info(
                "Images-search callback ignored request=%d query=%r active_query=%r reason=stale_query",
                request_id, query, self._active_search_query,
            )
            return
        if folder != str(self._get_folder_dir().resolve()):
            logger.info(
                "Images-search callback ignored request=%d query=%r reason=stale_folder",
                request_id, query,
            )
            return

        cancelled = getattr(task, "_cancelled", None)
        if cancelled is not None and cancelled.is_set():
            logger.info(
                "Images-search callback ignored request=%d query=%r reason=cancelled",
                request_id, query,
            )
            visible = list(progressive_visible or local_matches or [])
            folder_count = len(self._get_png_files(self._get_folder_dir())) if self._get_folder_dir().exists() else 0
            self._update_search_feedback(query, len(visible), folder_count)
            return

        selected_path_str = self._get_selected_path()
        png_files = self._get_png_files(self._get_folder_dir())
        existing = {str(path.resolve()): path for path in png_files}
        local_files = [
            existing[str(path.resolve())]
            for path in local_matches
            if str(path.resolve()) in existing
        ]
        if error is not None:
            logger.error(
                "Images-search failure state request=%d query=%r error_type=%s error=%s",
                request_id, query, type(error).__name__, error,
            )
            self._last_search_error = error
            if local_files:
                self._update_search_feedback(query, len(local_files), len(png_files))
                restored = self._populate_list(
                    local_files, selected_path_str, preserve_order=True
                )
                if not restored:
                    self._clear_preview()
                emit_tour_event(
                    UI_FIND_FINISHED,
                    ok=True,
                    result_count=len(local_files),
                    kind=self._tour_search_kind(),
                    generation=self._tour_search_generation,
                )
                return
            self._hide_search_status()
            self._list_empty_title.setText(t("images.search_error"))
            if isinstance(error, (AiBudgetExceeded, AiProxyError, RelevanceProviderError)):
                self._list_empty_body.setText(format_ai_user_message(error))
            else:
                self._list_empty_body.setText(t("images.search_error_body"))
            self._empty_choose_folder_btn.hide()
            self._list_stack.setCurrentIndex(1)
            emit_tour_event(
                UI_FIND_FAILED,
                reason=_tour_find_fail_reason(error),
                ok=False,
                generation=self._tour_search_generation,
            )
            return

        filtered_files = [
            existing[str(path.resolve())]
            for path in result_paths
            if str(path.resolve()) in existing
        ]
        metadata = self._metadata_service.load_metadata(self._get_folder_dir())
        filtered_files = apply_favorite_filter(
            filtered_files,
            metadata,
            self._filter_mode,
        )
        local_files = apply_favorite_filter(
            local_files, metadata, self._filter_mode
        )
        filtered_files = self._merge_search_paths(local_files, filtered_files)
        self._last_search_error = None
        logger.info(
            "Images-search completed request=%d query=%r result_count=%d elapsed_seconds=%s",
            request_id, query, len(filtered_files),
            None if started is None else round(time.perf_counter() - started, 3),
        )
        self._update_search_feedback(query, len(filtered_files), len(png_files))
        self._remember_workspace_results(
            filtered_files, query, origin=ORIGIN_TEXT, narrowed=False
        )
        emit_tour_event(
            UI_FIND_FINISHED,
            ok=len(filtered_files) > 0,
            result_count=len(filtered_files),
            kind=self._tour_search_kind(),
            generation=self._tour_search_generation,
        )
        if (
            task is not None
            and task.mode == "vision_relevance"
            and progressive_visible is not None
            and [str(path.resolve()) for path in progressive_visible]
            == [str(path.resolve()) for path in filtered_files]
        ):
            return
        restored = self._populate_list(
            filtered_files,
            selected_path_str,
            preserve_order=True,
        )
        if not restored:
            self._clear_preview()

    def _load_images(
        self,
        force_reload_metadata: bool = False,
        *,
        defer_thumbnails: bool = False,
    ) -> None:
        self._thumbnail_load_generation += 1
        self._thumbnail_load_queue.clear()
        selected_path_str = self._get_selected_path()
        target_dir = self._get_folder_dir()

        if not target_dir.exists():
            self._list_widget.clear()
            self._gallery_count_label.setText(t("images.item_count", count=0))
            self._hide_search_status()
            self._set_list_empty_state(0)
            self._clear_preview()
            return

        metadata = self._metadata_service.load_metadata(
            target_dir,
            force_reload=force_reload_metadata,
        )
        png_files = self._get_png_files(target_dir)
        if self._reload_ask_ai_grid(defer_thumbnails=defer_thumbnails):
            return
        if self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)
            return
        filtered_files = apply_favorite_filter(
            png_files, metadata, self._filter_mode
        )
        self._update_search_feedback(
            self._active_search_query, len(filtered_files), len(png_files)
        )
        restored = self._populate_list(
            filtered_files,
            selected_path_str,
            defer_thumbnails=defer_thumbnails,
        )
        if not restored:
            self._clear_preview()

    def _add_image_to_list(self, saved_path: Path) -> None:
        # Only add if it belongs to the current Project/Folder
        if saved_path.parent.resolve() != self._get_folder_dir().resolve():
            return

        if self._ask_ai_grid_active:
            return
        if self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)
            return
        if self._find_list_row(saved_path) != -1:
            return
        self._insert_list_item_sorted(saved_path)
        self._set_list_empty_state(1)

    def _on_search(self) -> None:
        self._search_debounce.stop()
        query = self._search_input.text()
        self._tour_search_generation = tour_event_generation()
        logger.info(
            "Images first/explicit search submit query=%r source=button_or_enter active_query=%r",
            query,
            self._active_search_query,
        )
        self._active_search_query = query
        if query.strip():
            self._start_unified_search(query)
        else:
            self._cancel_search_tasks()
            self._search_request_id += 1
            self._load_images()

    def _on_semantic_bundle_installed(self) -> None:
        for provider in (
            self._owned_hybrid_search_provider,
            self._owned_semantic_search_provider,
            self._owned_vision_search_provider,
        ):
            if provider is not None:
                provider.refresh_bundle()
        self._refresh_analysis_preview(force=True)
        if self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)

    def _on_search_mode_changed(self) -> None:
        mode = str(self._search_mode_combo.currentData() or "text")
        if mode == self._active_search_mode:
            return
        self._active_search_mode = mode
        self._config["developer_search_mode"] = mode
        try:
            save_config(self._config)
        except OSError:
            pass
        self._apply_search_placeholder()
        self._search_debounce.stop()
        self._cancel_search_tasks()
        self._search_request_id += 1
        self._clear_ask_ai_grid()
        self._active_search_query = ""
        self._load_images()

    def _apply_search_placeholder(self) -> None:
        if self._active_search_mode == "text":
            self._search_input.setPlaceholderText(t("images.search_placeholder"))
        else:
            self._search_input.setPlaceholderText(t("images.search_placeholder_meaning"))

    @staticmethod
    def _normalize_search_mode(value: object) -> str:
        mode = str(value or "").strip().lower()
        return mode if mode in {"hybrid", "text", "semantic", "vision_relevance"} else "hybrid"

    @staticmethod
    def _user_facing_search_mode(mode: str) -> str:
        """Text stays text. Meaning, including leftover hybrid/semantic, is vision_relevance."""
        if mode == USER_FACING_TEXT_MODE:
            return USER_FACING_TEXT_MODE
        return USER_FACING_MEANING_MODE

    def _tour_search_kind(self) -> str:
        mode = self._user_facing_search_mode(
            getattr(self, "_active_search_mode", USER_FACING_TEXT_MODE)
        )
        return "meaning" if mode == USER_FACING_MEANING_MODE else "basic"

    def _configured_search_mode(self) -> str:
        return self._user_facing_search_mode(
            self._normalize_search_mode(
                self._config.get("developer_search_mode", USER_FACING_TEXT_MODE)
            )
        )

    def _provider_for_mode(self, mode: str):
        if mode == "text":
            return search_indexed_images
        if mode == "semantic":
            return self._semantic_search_provider
        if mode == "vision_relevance":
            return self._owned_vision_search_provider
        return self._search_provider

    def sync_search_mode_from_config(self, *, rerun: bool = True) -> None:
        """Apply Settings routing and rerun the current regular search."""
        mode = self._configured_search_mode()
        model_changed = False
        model_key = self._config.get("developer_semantic_model", DEFAULT_MODEL_KEY)
        query_embedding = self._config.get(
            "developer_query_embedding", DEFAULT_QUERY_EMBEDDING
        )
        model_setter = getattr(self._semantic_search_provider, "set_model_key", None)
        if callable(model_setter):
            model_changed = model_setter(model_key)
        hybrid_setter = getattr(self._owned_hybrid_search_provider, "set_model_key", None)
        if callable(hybrid_setter):
            model_changed = hybrid_setter(model_key) or model_changed
        vision_setter = getattr(self._owned_vision_search_provider, "set_model_key", None)
        if callable(vision_setter):
            model_changed = vision_setter(model_key) or model_changed
        for provider in (
            self._semantic_search_provider,
            self._owned_hybrid_search_provider,
            self._owned_vision_search_provider,
        ):
            method_setter = getattr(provider, "set_query_embedding_method", None)
            if callable(method_setter):
                model_changed = method_setter(query_embedding) or model_changed
        self._content_search_setup.set_model_key(model_key)
        mode_changed = mode != self._active_search_mode
        if not mode_changed and not model_changed:
            return
        self._active_search_mode = mode
        self._cancel_search_tasks()
        self._search_request_id += 1
        index = self._search_mode_combo.findData(mode)
        if index >= 0:
            blocked = self._search_mode_combo.blockSignals(True)
            self._search_mode_combo.setCurrentIndex(index)
            self._search_mode_combo.blockSignals(blocked)
        self._apply_search_placeholder()
        if rerun and self._active_search_query.strip():
            self._start_unified_search(self._active_search_query)

    def _on_escape(self) -> None:
        if hasattr(self, "_tags_card") and self._tags_card.isVisible():
            self._hide_tags_popup()
            return
        self._on_clear_search()

    def _on_clear_search(self) -> None:
        self._search_input.clear()
        self._search_debounce.stop()
        if self._ask_ai_grid_active:
            self._exit_ask_ai_results()
            return
        if not self._active_search_query:
            self._update_search_feedback("", 0, len(self._get_png_files(self._get_folder_dir())) if self._get_folder_dir().exists() else 0)
            return
        self._active_search_query = ""
        self._cancel_search_tasks()
        self._search_request_id += 1
        self._load_images()

    def closeEvent(self, event) -> None:
        self._set_folder_nav_filter(False)
        self._hide_tags_popup()
        self._thumbnail_load_timer.stop()
        self._thumbnail_load_queue.clear()
        self._search_debounce.stop()
        self._isolate_ask_ai_search()
        self._cancel_search_tasks()
        self._cancel_semantic_index()
        self._search_request_id += 1
        super().closeEvent(event)
