"""Always-visible left sidebar with Images, folder shortcuts, and Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QByteArray,
    QEvent,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    Signal,
    QSize,
)
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from app.branding import APP_NAME_SIDEBAR
from app.ui.icons import (
    icon_collapse_nav,
    icon_disclosure,
    icon_expand_nav,
    icon_notification,
    icon_pin,
    icon_user,
    pin_pixmap,
)
from app.ui.app_icon import app_mark_pixmap
from app.ui.design_tokens import (
    MOTION_NORMAL_MS,
    NAV_COLLAPSED_PADDING_X,
    NAV_COLLAPSED_WIDTH,
    NAV_EXPANDED_WIDTH,
    NAV_ITEM_GAP,
    NAV_PADDING_X,
    NAV_PADDING_Y,
    NAV_UTILITY_ICON,
    navigation_icon,
    navigation_icon_size,
)


_FAVORITE_MIME = "application/x-capixe-favorite-folder"


class NavFavoriteRow(QWidget):
    """Folder shortcut row: click to open, drag to reorder, name stays selectable."""

    clicked = Signal()
    dropped_on = Signal(str, str, bool)

    def __init__(self, path, *, current: bool, parent=None):
        from app.i18n import t

        super().__init__(parent)
        self.setObjectName("navFolderRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setFixedHeight(28)
        label = path.name or str(path)
        self.setToolTip(str(path))
        self.setProperty("navLabel", label)
        self.setProperty("folderPath", str(path))
        if current:
            self.setProperty("currentFolder", True)

        self._press_pos: QPoint | None = None
        self._press_had_selection = False
        self._press_origin = "row"
        self._dragged = False
        self._reordering = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 6, 0)
        layout.setSpacing(6)

        glyph = QLabel("📁", self)
        glyph.setObjectName("navFolderGlyph")
        glyph.setAlignment(Qt.AlignCenter)
        glyph.setCursor(Qt.PointingHandCursor)
        layout.addWidget(glyph, 0, Qt.AlignVCenter)

        self._name = QLabel(label, self)
        self._name.setObjectName("navFolderName")
        self._name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._name.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self._name.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self._name, 1, Qt.AlignVCenter)

        pin = QLabel(self)
        pin.setObjectName("navFolderPin")
        pin.setAlignment(Qt.AlignCenter)
        pin.setPixmap(pin_pixmap(size=14, filled=True))
        pin.setFixedSize(16, 16)
        pin.setAccessibleName(t("nav.favorites"))
        pin.setCursor(Qt.PointingHandCursor)
        layout.addWidget(pin, 0, Qt.AlignVCenter)

        for child in (glyph, self._name, pin):
            child.installEventFilter(self)

    def folder_path(self) -> str:
        return str(self.property("folderPath") or "")

    def set_drop_edge(self, edge: str) -> None:
        value = edge if edge in {"before", "after"} else ""
        if self.property("dropEdge") == value:
            return
        self.setProperty("dropEdge", value)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        origin = "name" if obj is self._name else "row"
        if etype == QEvent.Type.MouseButtonPress:
            self._note_press(event, origin=origin)
        elif etype == QEvent.Type.MouseMove:
            self._note_move(event)
            if self._maybe_begin_reorder(event):
                return True
        elif etype == QEvent.Type.MouseButtonRelease:
            self._note_release(event)
        return False

    def mousePressEvent(self, event) -> None:
        self._note_press(event, origin="row")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._note_move(event)
        if self._maybe_begin_reorder(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._note_release(event)
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_FAVORITE_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_FAVORITE_MIME):
            event.ignore()
            return
        event.acceptProposedAction()
        self.set_drop_edge("after" if self._drop_after(event) else "before")

    def dragLeaveEvent(self, event) -> None:
        self.set_drop_edge("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_FAVORITE_MIME):
            self.set_drop_edge("")
            event.ignore()
            return
        after = self._drop_after(event)
        source = bytes(event.mimeData().data(_FAVORITE_MIME)).decode("utf-8")
        self.set_drop_edge("")
        event.acceptProposedAction()
        self.dropped_on.emit(source, self.folder_path(), after)

    def _drop_after(self, event) -> bool:
        if hasattr(event, "position"):
            y = event.position().y()
        else:
            y = event.pos().y()
        return y >= (self.height() / 2)

    def _global_pos(self, event) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def _note_press(self, event, *, origin: str = "row") -> None:
        if event.button() != Qt.LeftButton:
            return
        self._press_pos = self._global_pos(event)
        self._press_had_selection = bool(self._name.selectedText())
        self._press_origin = origin
        self._dragged = False
        self._reordering = False

    def _note_move(self, event) -> None:
        if self._press_pos is None or self._dragged:
            return
        distance = (self._global_pos(event) - self._press_pos).manhattanLength()
        if distance >= QApplication.startDragDistance():
            self._dragged = True

    def _maybe_begin_reorder(self, event) -> bool:
        if self._press_pos is None or self._reordering:
            return False
        delta = self._global_pos(event) - self._press_pos
        if delta.manhattanLength() < QApplication.startDragDistance():
            return False
        self._dragged = True
        if self._press_origin == "name" and abs(delta.x()) >= abs(delta.y()):
            return False
        self._begin_reorder_drag()
        return True

    def _begin_reorder_drag(self) -> None:
        path = self.folder_path()
        if not path:
            return
        self._reordering = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_FAVORITE_MIME, QByteArray(path.encode("utf-8")))
        mime.setText(path)
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, max(1, self.height() // 2)))
        drag.exec(Qt.MoveAction)
        self._reordering = False
        self._press_pos = None
        self.set_drop_edge("")

    def _note_release(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._note_move(event)
        activate = (
            self._press_pos is not None
            and not self._dragged
            and not self._reordering
            and not self._press_had_selection
            and not bool(self._name.selectedText())
        )
        self._press_pos = None
        self._press_had_selection = False
        self._dragged = False
        self._reordering = False
        if activate:
            self.clicked.emit()


class NavAccountControl(QPushButton):
    """Account cluster: avatar + name + plan when expanded, avatar when collapsed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebarAccountControl")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCheckable(False)
        self.setFlat(True)
        self._collapsed = False
        self._identity_name = ""
        self._identity_plan = ""
        self._identity_tooltip = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._avatar = QLabel(self)
        self._avatar.setObjectName("sidebarAccountAvatar")
        self._avatar.setAlignment(Qt.AlignCenter)
        self._avatar.setFixedSize(28, 28)
        self._avatar.setPixmap(icon_user(size=16).pixmap(16, 16))
        self._avatar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._avatar, 0, Qt.AlignVCenter)

        text = QWidget(self)
        text.setObjectName("sidebarAccountText")
        text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self._name = QLabel(text)
        self._name.setObjectName("sidebarAccountName")
        self._name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._name.setWordWrap(False)
        self._name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._plan = QLabel(text)
        self._plan.setObjectName("sidebarAccountPlan")
        self._plan.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._plan.setWordWrap(False)
        self._plan.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_layout.addWidget(self._name)
        text_layout.addWidget(self._plan)
        layout.addWidget(text, 1, Qt.AlignVCenter)
        self._text = text
        self.setText("")
        self.setMinimumHeight(52)
        self._refresh_copy()

    def set_identity(self, name: str, plan: str = "", *, tooltip: str = "") -> None:
        self._identity_name = name
        self._identity_plan = plan
        self._identity_tooltip = tooltip
        self._refresh_copy()

    def _refresh_copy(self) -> None:
        from app.i18n import t

        name = self._identity_name or t("nav.account.signed_out")
        plan = self._identity_plan
        self._name.setText(self._elide(self._name, name))
        self._plan.setText(self._elide(self._plan, plan))
        self._plan.setVisible(bool(plan) and not self._collapsed)
        tip = str(getattr(self, "_identity_tooltip", "") or "").strip() or name
        self.setToolTip(f"{tip} · {plan}".strip(" ·") if plan else tip)
        self.setAccessibleName(t("nav.account"))
        self.setText("")

    def _elide(self, label: QLabel, text: str) -> str:
        if not text:
            return ""
        width = max(label.width(), self._text.width(), 120)
        metrics = QFontMetrics(label.font())
        if metrics.horizontalAdvance(text) <= width:
            return text
        return metrics.elidedText(text, Qt.ElideRight, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_copy()

    def sizeHint(self) -> QSize:
        if self._collapsed:
            return QSize(36, 36)
        return QSize(180, 52)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.setProperty("collapsed", "true" if self._collapsed else "false")
        self._text.setVisible(not self._collapsed)
        margins = (4, 4, 4, 4) if self._collapsed else (8, 6, 8, 6)
        self.layout().setContentsMargins(*margins)
        self.setMinimumHeight(36 if self._collapsed else 52)
        self.setSizePolicy(
            QSizePolicy.Fixed if self._collapsed else QSizePolicy.Expanding,
            QSizePolicy.Minimum,
        )
        self._refresh_copy()
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)


class SideNav(QFrame):
    """Fixed-width sidebar so folder names stay visible without hover."""

    page_selected = Signal(int)
    folder_opened = Signal(str)
    favorites_reordered = Signal(list)
    favorites_expanded_changed = Signal(bool)
    expanded_changed = Signal(bool)
    capture_clicked = Signal()

    COLLAPSED_WIDTH = NAV_COLLAPSED_WIDTH
    EXPANDED_WIDTH = NAV_EXPANDED_WIDTH
    ANIM_MS = MOTION_NORMAL_MS
    _BRAND_ICON_PX = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._expanded = True
        self._animating = False
        self._responsive_compact: bool | None = None
        self._nav_buttons: dict[int, QPushButton] = {}
        self._placeholder_buttons: list[QPushButton] = []
        self._rail_buttons: list[QPushButton] = []
        self._folder_buttons: list[QWidget] = []
        self._section_labels: list[QLabel] = []
        self._label_keys: dict[int, str] = {}
        self._favorite_paths: list[Path] = []
        self._favorites_expanded = True
        self._width = self.EXPANDED_WIDTH

        self.setFixedWidth(self.EXPANDED_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            NAV_PADDING_X, NAV_PADDING_Y, NAV_PADDING_X, NAV_PADDING_Y
        )
        self._layout.setSpacing(NAV_ITEM_GAP)

        brand_wrap = QWidget(self)
        brand_wrap.setObjectName("sidebarBrandWrap")
        brand_lay = QHBoxLayout(brand_wrap)
        brand_lay.setContentsMargins(4, 10, 0, 12)
        brand_lay.setSpacing(4)
        brand_lay.setAlignment(Qt.AlignVCenter)
        self._brand_wrap = brand_wrap
        self._brand_layout = brand_lay

        brand_block = QWidget(brand_wrap)
        brand_block.setObjectName("sidebarBrandBlock")
        brand_block.setAttribute(Qt.WA_StyledBackground, True)
        block_lay = QHBoxLayout(brand_block)
        block_lay.setContentsMargins(2, 2, 6, 2)
        block_lay.setSpacing(10)
        block_lay.setAlignment(Qt.AlignVCenter)
        self._brand_block = brand_block
        self._brand_block_layout = block_lay

        self._brand_icon = QLabel(brand_block)
        self._brand_icon.setObjectName("sidebarBrandIcon")
        self._brand_icon.setAlignment(Qt.AlignCenter)
        self._brand_icon.setFixedSize(self._BRAND_ICON_PX, self._BRAND_ICON_PX)
        self._brand_icon.setPixmap(app_mark_pixmap(self._BRAND_ICON_PX))
        block_lay.addWidget(self._brand_icon, 0, Qt.AlignVCenter)

        self._brand = QLabel(APP_NAME_SIDEBAR, brand_block)
        self._brand.setObjectName("sidebarBrand")
        self._brand.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._brand.setWordWrap(False)
        brand_font = QFont(self._brand.font())
        brand_font.setPixelSize(17)
        brand_font.setWeight(QFont.Weight.DemiBold)
        self._brand.setFont(brand_font)
        self._brand.setAccessibleName(APP_NAME_SIDEBAR)
        self._brand_block.setAccessibleName(APP_NAME_SIDEBAR)
        block_lay.addWidget(self._brand, 1, Qt.AlignVCenter)
        brand_lay.addWidget(brand_block, 1, Qt.AlignVCenter)

        shadow = QGraphicsDropShadowEffect(self._brand_icon)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(17, 24, 39, 28))
        self._brand_icon.setGraphicsEffect(shadow)

        self._collapse_btn = QPushButton(brand_wrap)
        self._collapse_btn.setObjectName("sidebarUtilityButton")
        self._collapse_btn.setIcon(icon_collapse_nav())
        self._collapse_btn.setIconSize(QSize(16, 16))
        self._collapse_btn.setCursor(Qt.PointingHandCursor)
        self._collapse_btn.setFocusPolicy(Qt.NoFocus)
        self._collapse_btn.clicked.connect(self.toggle_expanded)
        brand_lay.addWidget(self._collapse_btn, 0, Qt.AlignVCenter)
        self._brand_icon.installEventFilter(self)
        self._brand_block.installEventFilter(self)

        self._layout.addWidget(brand_wrap)
        self._layout.addSpacing(16)

        self._anim = QPropertyAnimation(self, b"navWidth", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)
        self._sync_collapse_labels()

    def get_nav_width(self) -> int:
        return self._width

    def set_nav_width(self, value: int) -> None:
        self._width = max(0, int(value))
        self.setMinimumWidth(self._width)
        self.setMaximumWidth(self._width)
        self.setFixedWidth(self._width)

    navWidth = Property(int, get_nav_width, set_nav_width)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(self._width, hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(self._width, 0)

    def add_nav_item(
        self,
        page_id: int,
        label: str,
        icon,
        *,
        label_key: str = "",
        accent: str = "",
    ) -> QPushButton:
        btn = self._make_nav_button(label, icon, accent=accent)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.clicked.connect(
            lambda checked=False, pid=page_id: self.page_selected.emit(pid)
        )
        self._layout.addWidget(btn)
        self._nav_buttons[page_id] = btn
        self._label_keys[page_id] = label_key or label
        self._apply_button_labels()
        return btn

    def _make_nav_button(
        self,
        label: str,
        icon,
        *,
        accent: str = "",
        tooltip: str = "",
        utility: bool = False,
    ) -> QPushButton:
        btn = QPushButton(self)
        btn.setObjectName("navUtilityButton" if utility else "navButton")
        if utility:
            btn.setIcon(icon)
            btn.setIconSize(QSize(NAV_UTILITY_ICON, NAV_UTILITY_ICON))
        else:
            btn.setIcon(navigation_icon(icon, accent))
            icon_size = navigation_icon_size()
            btn.setIconSize(QSize(icon_size, icon_size))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tooltip or label)
        btn.setProperty("navLabel", label)
        if accent:
            btn.setProperty("navAccent", accent)
        self._polish(btn)
        return btn

    def add_folder_sections(self) -> None:
        """Pinned folders nested under Images. Collapsing shifts items below."""
        from app.i18n import t

        self._favorites_rail_button = self._make_nav_button(
            t("nav.favorites"),
            icon_pin(filled=True),
            accent="favorites",
            tooltip=t("nav.favorites"),
        )
        self._favorites_rail_button.setCheckable(False)
        self._favorites_rail_button.setFocusPolicy(Qt.NoFocus)
        self._favorites_rail_button.clicked.connect(self._open_favorites_menu)
        self._favorites_rail_button.hide()
        self._layout.addWidget(self._favorites_rail_button)
        self._rail_buttons.append(self._favorites_rail_button)

        branch = QFrame(self)
        branch.setObjectName("navFavoritesBranch")
        branch.setAttribute(Qt.WA_StyledBackground, True)
        branch_layout = QVBoxLayout(branch)
        branch_layout.setContentsMargins(0, 2, 0, 4)
        branch_layout.setSpacing(2)

        self._favorites_toggle = QPushButton(branch)
        self._favorites_toggle.setObjectName("navFavoritesToggle")
        self._favorites_toggle.setCheckable(True)
        self._favorites_toggle.setChecked(self._favorites_expanded)
        self._favorites_toggle.setCursor(Qt.PointingHandCursor)
        self._favorites_toggle.setFocusPolicy(Qt.NoFocus)
        self._favorites_toggle.setIconSize(QSize(12, 12))
        self._favorites_toggle.setProperty("labelKey", "nav.favorites")
        self._favorites_toggle.clicked.connect(self._on_favorites_toggle)
        branch_layout.addWidget(self._favorites_toggle)

        scroll = QScrollArea(branch)
        scroll.setObjectName("navFolderScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        scroll.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        inner = QWidget(scroll)
        inner.setObjectName("navFolderScrollInner")
        inner.setAutoFillBackground(False)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 2, 0, 2)
        inner_layout.setSpacing(2)

        self._favorites_host = QWidget(inner)
        self._favorites_host.setObjectName("navFolderSection")
        self._favorites_host.setAutoFillBackground(False)
        self._favorites_layout = QVBoxLayout(self._favorites_host)
        self._favorites_layout.setContentsMargins(0, 0, 0, 2)
        self._favorites_layout.setSpacing(2)
        inner_layout.addWidget(self._favorites_host)

        self._recents_header = self._add_section_label("nav.recent_folders", inner_layout)
        self._recents_host = QWidget(inner)
        self._recents_host.setObjectName("navFolderSection")
        self._recents_host.setAutoFillBackground(False)
        self._recents_layout = QVBoxLayout(self._recents_host)
        self._recents_layout.setContentsMargins(0, 0, 0, 2)
        self._recents_layout.setSpacing(2)
        inner_layout.addWidget(self._recents_host)
        self._recents_header.hide()
        self._recents_host.hide()

        scroll.setWidget(inner)
        self._folder_scroll = scroll
        branch_layout.addWidget(scroll)

        self._favorites_branch = branch
        self._layout.addWidget(branch)
        self._sync_favorites_toggle_chrome()
        self._sync_favorites_scroll_height()

    def _add_section_label(self, label_key: str, layout=None) -> QLabel:
        parent = self if layout is None else layout.parentWidget()
        label = QLabel(parent)
        label.setObjectName("navSectionLabel")
        label.setProperty("labelKey", label_key)
        target = layout if layout is not None else self._layout
        target.addWidget(label)
        self._section_labels.append(label)
        return label

    def _on_favorites_toggle(self, checked: bool) -> None:
        self.set_favorites_expanded(bool(checked))

    def set_favorites_expanded(self, expanded: bool, *, notify: bool = True) -> None:
        expanded = bool(expanded)
        changed = expanded != bool(getattr(self, "_favorites_expanded", True))
        self._favorites_expanded = expanded
        self._sync_favorites_visibility()
        if changed and notify:
            self.favorites_expanded_changed.emit(expanded)

    def _sync_favorites_toggle_chrome(self) -> None:
        from app.i18n import t

        btn = getattr(self, "_favorites_toggle", None)
        if btn is None:
            return
        expanded = bool(getattr(self, "_favorites_expanded", True))
        btn.blockSignals(True)
        btn.setChecked(expanded)
        btn.blockSignals(False)
        btn.setIcon(icon_disclosure(expanded=expanded))
        btn.setText(t("nav.favorites") if self._expanded else "")
        btn.setToolTip(
            t("nav.favorites_hide") if expanded else t("nav.favorites_show")
        )
        btn.setAccessibleName(t("nav.favorites"))
        btn.setProperty("labelKey", "nav.favorites")

    def _sync_favorites_scroll_height(self) -> None:
        scroll = getattr(self, "_folder_scroll", None)
        if scroll is None:
            return
        if not self._favorite_paths:
            content_h = 40
        else:
            content_h = min(196, len(self._favorite_paths) * 30 + 6)
        scroll.setFixedHeight(max(28, content_h))

    def _sync_favorites_visibility(self) -> None:
        nav_open = bool(self._expanded)
        fav_open = bool(getattr(self, "_favorites_expanded", True))
        branch = getattr(self, "_favorites_branch", None)
        if branch is not None:
            branch.setVisible(nav_open)
        toggle = getattr(self, "_favorites_toggle", None)
        if toggle is not None:
            toggle.setVisible(nav_open)
        scroll = getattr(self, "_folder_scroll", None)
        if scroll is not None:
            scroll.setVisible(nav_open and fav_open)
        self._sync_favorites_toggle_chrome()
        self._sync_favorites_scroll_height()

    def set_folder_shortcuts(
        self,
        *,
        favorites: list,
        recents: list,
        current_folder: str = "",
    ) -> None:
        from app.i18n import t

        del recents
        self._favorite_paths = [Path(path) for path in favorites]
        self._clear_folder_buttons()
        if not favorites:
            empty = QLabel(t("nav.favorites_empty"), self._favorites_host)
            empty.setObjectName("navSectionEmpty")
            empty.setProperty("folderShortcut", True)
            empty.setWordWrap(True)
            self._favorites_layout.addWidget(empty)
        for path in self._favorite_paths:
            self._add_favorite_row(
                self._favorites_layout,
                path,
                current=str(path) == current_folder,
            )
        self._recents_header.hide()
        self._recents_host.hide()
        self._sync_favorites_scroll_height()
        self._apply_button_labels()

    def _add_favorite_row(self, layout, path, *, current: bool) -> NavFavoriteRow:
        row = NavFavoriteRow(path, current=current, parent=self)
        row.clicked.connect(
            lambda target=str(path): self.folder_opened.emit(target)
        )
        row.dropped_on.connect(self.reorder_favorites)
        layout.addWidget(row)
        self._folder_buttons.append(row)
        self._polish(row)
        return row

    def reorder_favorites(
        self, source: str, target: str, after: bool = False
    ) -> None:
        """Move `source` before or after `target` and emit the new order."""
        paths = [str(path) for path in self._favorite_paths]
        if source not in paths or target not in paths:
            return
        from_index = paths.index(source)
        to_index = paths.index(target)
        if after:
            to_index += 1
        item = paths.pop(from_index)
        if from_index < to_index:
            to_index -= 1
        paths.insert(to_index, item)
        if paths == [str(path) for path in self._favorite_paths]:
            self._clear_favorite_drop_edges()
            return
        rows = {
            row.folder_path(): row
            for row in self._folder_buttons
            if isinstance(row, NavFavoriteRow)
        }
        ordered_rows = [rows[path] for path in paths if path in rows]
        for row in ordered_rows:
            self._favorites_layout.removeWidget(row)
        for index, row in enumerate(ordered_rows):
            self._favorites_layout.insertWidget(index, row)
            row.set_drop_edge("")
        self._folder_buttons = ordered_rows
        self._favorite_paths = [Path(path) for path in paths]
        self.favorites_reordered.emit(paths)

    def _clear_favorite_drop_edges(self) -> None:
        for row in self._folder_buttons:
            if isinstance(row, NavFavoriteRow):
                row.set_drop_edge("")

    def _clear_folder_buttons(self) -> None:
        self._folder_buttons.clear()
        for layout in (self._favorites_layout, self._recents_layout):
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def _open_favorites_menu(self) -> None:
        from app.i18n import t

        menu = QMenu(self)
        if not self._favorite_paths:
            empty = menu.addAction(t("nav.favorites_empty"))
            empty.setEnabled(False)
        else:
            for path in self._favorite_paths:
                action = menu.addAction(path.name or str(path))
                action.setToolTip(str(path))
                action.triggered.connect(
                    lambda checked=False, target=str(path): self.folder_opened.emit(
                        target
                    )
                )
        anchor = self._favorites_rail_button
        menu.exec(anchor.mapToGlobal(QPoint(anchor.width(), 0)))

    def add_placeholder_item(
        self,
        label: str,
        icon,
        *,
        tooltip: str = "",
        accent: str = "ai",
    ) -> QPushButton:
        """
        Non-navigating nav row (e.g. future AI).

        Visible and hoverable for tooltip, but not checkable and emits no page change.
        """
        btn = self._make_nav_button(label, icon, accent=accent, tooltip=tooltip)
        btn.setObjectName("navButtonPlaceholder")
        btn.setCursor(Qt.ArrowCursor)
        btn.setCheckable(False)
        btn.setEnabled(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(lambda checked=False: None)
        self._layout.addWidget(btn)
        self._placeholder_buttons.append(btn)
        self._apply_button_labels()
        self._polish(btn)
        return btn

    @staticmethod
    def _polish(widget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def add_stretch(self) -> None:
        self._layout.addStretch()

    def add_account_footer(self, *, capture_enabled: bool = True) -> QWidget:
        """Utility actions (Capture / Notifications), then a separate account cluster."""
        from app.i18n import t
        from app.ui.icons import icon_capture_nav

        self._capture_enabled = capture_enabled
        self._utility_divider = QFrame(self)
        self._utility_divider.setObjectName("navUtilityDivider")
        self._utility_divider.setFrameShape(QFrame.NoFrame)
        self._utility_divider.setFixedHeight(1)
        self._layout.addSpacing(8)
        self._layout.addWidget(self._utility_divider)
        self._layout.addSpacing(8)

        utility_wrap = QWidget(self)
        utility_wrap.setObjectName("navUtilityGroup")
        utility_layout = QVBoxLayout(utility_wrap)
        utility_layout.setContentsMargins(0, 0, 0, 0)
        utility_layout.setSpacing(NAV_ITEM_GAP)

        self._capture_button = self._make_nav_button(
            t("nav.capture"),
            icon_capture_nav(),
            tooltip=t("nav.capture"),
            utility=True,
        )
        self._capture_button.setCheckable(False)
        self._capture_button.setFocusPolicy(Qt.NoFocus)
        self._capture_button.setAccessibleName(t("nav.capture"))
        self._capture_button.clicked.connect(self.capture_clicked.emit)
        utility_layout.addWidget(self._capture_button)
        if capture_enabled:
            self._rail_buttons.append(self._capture_button)
        else:
            self._capture_button.hide()
            self._capture_button.setEnabled(False)

        self._notification_button = self._make_nav_button(
            t("nav.notifications"),
            icon_notification(),
            tooltip=t("nav.notifications"),
            utility=True,
        )
        self._notification_button.setCheckable(False)
        self._notification_button.setFocusPolicy(Qt.NoFocus)
        self._notification_button.setAccessibleName(t("nav.notifications"))
        self._notification_button.setEnabled(False)
        self._notification_button.hide()
        utility_layout.addWidget(self._notification_button)

        self._layout.addWidget(utility_wrap)
        self._notification_item = utility_wrap
        self._utility_group = utility_wrap
        self._layout.addSpacing(8)

        self._account_control = NavAccountControl(self)
        self._user_button = self._account_control
        self._layout.addWidget(self._account_control)
        self._apply_button_labels()
        return self._account_control

    def add_version_footer(self) -> QLabel:
        """Quiet product version — not a prototype account control."""
        from app.branding import APP_NAME, DISPLAY_VERSION

        label = QLabel(f"{APP_NAME} {DISPLAY_VERSION}", self)
        label.setObjectName("sidebarVersionLabel")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._layout.addWidget(label)
        self._version_label = label
        return label

    def set_current_page(self, page_id: int) -> None:
        # Account (and other off-rail pages) are not exclusive nav buttons.
        # AutoExclusive would keep the previous rail item checked, so clicking
        # that same Images/Settings item again would not emit and could not
        # return from Account.
        on_rail = page_id in self._nav_buttons
        for btn in self._nav_buttons.values():
            btn.setAutoExclusive(False)
        for pid, btn in self._nav_buttons.items():
            btn.setChecked(pid == page_id)
        for btn in self._placeholder_buttons:
            btn.setChecked(False)
        if on_rail:
            for btn in self._nav_buttons.values():
                btn.setAutoExclusive(True)

    def set_capture_active(self, active: bool) -> None:
        """Mark Capture as an on utility action without treating it as a page."""
        if not hasattr(self, "_capture_button"):
            return
        self._capture_button.setProperty(
            "utilityActive", "true" if active else "false"
        )
        self._polish(self._capture_button)

    def set_responsive_compact(self, compact: bool) -> None:
        """Window width no longer forces the rail open or closed."""
        self._responsive_compact = bool(compact)

    def set_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded and not self._animating:
            return
        self._expanded = expanded
        self.expanded_changed.emit(expanded)
        if not expanded:
            self._apply_button_labels()
        target = self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
        if not animate:
            self._anim.stop()
            self._animating = False
            self.set_nav_width(target)
            self._apply_button_labels()
            return
        self._animate_to(expanded)

    def eventFilter(self, obj, event) -> bool:
        if (
            obj in (self._brand_icon, self._brand_block)
            and event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and not self._expanded
        ):
            self.set_expanded(True)
            return True
        return super().eventFilter(obj, event)

    def toggle_expanded(self) -> None:
        if self._animating:
            return
        self.set_expanded(not self._expanded)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)

    def _animate_to(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._animating = True
        self._anim.stop()
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setStartValue(self._width)
        self._anim.setEndValue(
            self.EXPANDED_WIDTH if expanded else self.COLLAPSED_WIDTH
        )
        self._anim.start()

    def _on_anim_finished(self) -> None:
        self._animating = False
        self._apply_button_labels()

    def _sync_collapse_labels(self) -> None:
        from app.i18n import t

        if self._expanded:
            self._collapse_btn.setIcon(icon_collapse_nav())
            self._collapse_btn.setToolTip(t("nav.collapse"))
            self._collapse_btn.setAccessibleName(t("nav.collapse"))
        else:
            self._collapse_btn.setIcon(icon_expand_nav())
            self._collapse_btn.setToolTip(t("nav.expand"))
            self._collapse_btn.setAccessibleName(t("nav.expand"))

    def _apply_button_labels(self, *, force_expanded: bool | None = None) -> None:
        expanded = self._expanded if force_expanded is None else bool(force_expanded)
        pad_x = NAV_PADDING_X if expanded else NAV_COLLAPSED_PADDING_X
        self._layout.setContentsMargins(pad_x, NAV_PADDING_Y, pad_x, NAV_PADDING_Y)
        self.setProperty("navCollapsed", "false" if expanded else "true")
        self._polish(self)

        self._brand_icon.setPixmap(app_mark_pixmap(self._BRAND_ICON_PX))
        self._brand.setText(APP_NAME_SIDEBAR)
        self._brand.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._brand.setVisible(expanded)
        self._brand_icon.setVisible(True)
        self._brand_block.setVisible(True)
        self._collapse_btn.setVisible(expanded)
        if expanded:
            self._brand_block.setMinimumWidth(0)
            self._brand_block.setMaximumWidth(16777215)
            self._brand_layout.setContentsMargins(4, 10, 0, 12)
            self._brand_layout.setSpacing(4)
            self._brand_layout.setAlignment(Qt.AlignVCenter)
            self._brand_block_layout.setContentsMargins(2, 2, 6, 2)
            self._brand_block_layout.setSpacing(10)
            self._brand_block_layout.setAlignment(Qt.AlignVCenter)
            self._brand_icon.setCursor(Qt.ArrowCursor)
            self._brand_block.setCursor(Qt.ArrowCursor)
            self._brand_icon.setToolTip("")
            self._brand_block.setToolTip("")
        else:
            self._brand_block.setFixedWidth(self._BRAND_ICON_PX)
            self._brand_layout.setContentsMargins(0, 10, 0, 12)
            self._brand_layout.setSpacing(0)
            self._brand_layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self._brand_block_layout.setContentsMargins(0, 2, 0, 2)
            self._brand_block_layout.setSpacing(0)
            self._brand_block_layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self._brand_icon.setCursor(Qt.PointingHandCursor)
            self._brand_block.setCursor(Qt.PointingHandCursor)
        self._sync_collapse_labels()
        if not expanded:
            self._brand_icon.setToolTip(self._collapse_btn.toolTip())
            self._brand_block.setToolTip(self._collapse_btn.toolTip())

        buttons = (
            list(self._nav_buttons.values())
            + self._placeholder_buttons
            + self._rail_buttons
        )
        for btn in buttons:
            label = btn.property("navLabel") or ""
            btn.setText(str(label) if expanded else "")
            btn.setToolTip(str(label))
            btn.setProperty("collapsed", "false" if expanded else "true")
            self._polish(btn)
        for row in self._folder_buttons:
            if isinstance(row, NavFavoriteRow):
                label = row.property("navLabel") or ""
                row._name.setText(str(label))

        from app.i18n import t

        for label in self._section_labels:
            key = label.property("labelKey") or ""
            label.setText(t(key))
            label.setVisible(expanded and key != "nav.recent_folders")
        if hasattr(self, "_recents_header"):
            self._recents_header.hide()
        if hasattr(self, "_recents_host"):
            self._recents_host.hide()
        if hasattr(self, "_folder_scroll"):
            self._sync_favorites_visibility()
        if hasattr(self, "_favorites_rail_button"):
            self._favorites_rail_button.setVisible(not expanded)
            self._favorites_rail_button.setToolTip(t("nav.favorites"))
        if hasattr(self, "_account_control"):
            self._account_control.set_collapsed(not expanded)
        if hasattr(self, "_version_label"):
            self._version_label.setVisible(expanded)
        if hasattr(self, "_utility_divider"):
            self._utility_divider.setVisible(expanded)
        if hasattr(self, "_capture_button"):
            self._capture_button.setToolTip(t("nav.capture"))
            self._capture_button.setAccessibleName(t("nav.capture"))
            self._capture_button.setVisible(bool(getattr(self, "_capture_enabled", True)))
        if hasattr(self, "_notification_button"):
            self._notification_button.setToolTip(t("nav.notifications"))
            self._notification_button.setAccessibleName(t("nav.notifications"))
            self._notification_button.setEnabled(False)
            self._notification_button.hide()
        for host_name in ("_favorites_host", "_recents_host"):
            host = getattr(self, host_name, None)
            if host is None:
                continue
            for child in host.findChildren(QLabel):
                if child.objectName() == "navSectionEmpty":
                    child.setVisible(expanded)
