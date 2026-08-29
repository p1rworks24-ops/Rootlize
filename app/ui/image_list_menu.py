"""Shared Explorer-like context menu for Images / Organize image lists."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QListWidget, QMenu, QWidget

from app.i18n import t
from app.ui.caption_delegate import ITEM_KIND_HEADER, ITEM_KIND_ROLE
from app.utils.view_mode import thumbnail_mode_labels


def ensure_list_item_under_cursor_selected(list_widget: QListWidget, pos) -> None:
    """If right-click lands on an unselected image, select only that item."""
    item_at = list_widget.itemAt(pos)
    if (
        item_at is not None
        and item_at.data(ITEM_KIND_ROLE) != ITEM_KIND_HEADER
        and not item_at.isSelected()
    ):
        list_widget.clearSelection()
        item_at.setSelected(True)
        list_widget.setCurrentItem(item_at)


def populate_image_list_context_menu(
    menu: QMenu,
    parent: QWidget,
    *,
    thumbnail_mode: str,
    selected_count: int,
    has_clipboard: bool,
    on_set_thumbnail_mode: Callable[[str], None] | None = None,
    on_open: Callable[[], None],
    on_copy: Callable[[], None],
    on_cut: Callable[[], None],
    on_paste: Callable[[], None],
    on_rename: Callable[[], None],
    on_delete: Callable[[], None],
    on_explorer: Callable[[], None],
            on_move: Callable[[], None] | None = None,
            on_analyze: Callable[[], None] | None = None,
            on_favorite: Callable[[], None] | None = None,
            favorite_checked: bool = False,
        ) -> None:
    """Fill menu with View + Open/Copy/Cut/Paste/Rename/Delete/Explorer."""
    if on_set_thumbnail_mode is not None:
        view_menu = menu.addMenu(t("common.view"))
        view_group = QActionGroup(parent)
        view_group.setExclusive(True)

        for mode, label in thumbnail_mode_labels():
            action = QAction(label, parent)
            action.setCheckable(True)
            action.setChecked(mode == thumbnail_mode)
            action.setData(mode)
            action.triggered.connect(
                lambda checked=False, m=mode: on_set_thumbnail_mode(m)
            )
            view_group.addAction(action)
            view_menu.addAction(action)

        menu.addSeparator()

    count = selected_count
    if count >= 1:
        open_action = QAction(t("images.open"), parent)
        open_action.triggered.connect(on_open)
        menu.addAction(open_action)

        if on_favorite is not None:
            fav_action = QAction(
                t("images.favorite_image_remove")
                if favorite_checked
                else t("images.favorite_image_add"),
                parent,
            )
            fav_action.triggered.connect(on_favorite)
            menu.addAction(fav_action)

        copy_label = (
            t("common.copy") if count == 1 else t("images.copy_count", count=count)
        )
        copy_action = QAction(copy_label, parent)
        copy_action.triggered.connect(on_copy)
        menu.addAction(copy_action)

        cut_label = (
            t("common.cut") if count == 1 else t("images.cut_count", count=count)
        )
        cut_action = QAction(cut_label, parent)
        cut_action.triggered.connect(on_cut)
        menu.addAction(cut_action)

    paste_action = QAction(t("common.paste"), parent)
    paste_action.setEnabled(has_clipboard)
    paste_action.triggered.connect(on_paste)
    menu.addAction(paste_action)

    if count == 1:
        rename_action = QAction(t("images.rename_title"), parent)
        rename_action.triggered.connect(on_rename)
        menu.addAction(rename_action)

    if count >= 1:
        if on_analyze is not None:
            analyze_action = QAction(t("images.analysis.retry_selected"), parent)
            analyze_action.triggered.connect(on_analyze)
            menu.addAction(analyze_action)

        if on_move is not None:
            move_action = QAction(t("images.actions.move"), parent)
            move_action.triggered.connect(on_move)
            menu.addAction(move_action)

        delete_label = (
            t("common.delete")
            if count == 1
            else t("images.delete_count", count=count)
        )
        delete_action = QAction(delete_label, parent)
        delete_action.triggered.connect(on_delete)
        menu.addAction(delete_action)

        menu.addSeparator()
        explorer_action = QAction(t("images.open_explorer"), parent)
        explorer_action.triggered.connect(on_explorer)
        menu.addAction(explorer_action)


def populate_empty_gallery_context_menu(
    menu: QMenu,
    parent: QWidget,
    *,
    enabled: bool,
    icon: QIcon | None,
    on_new_folder: Callable[[], None],
) -> None:
    """Fill the empty-background gallery menu (currently New Folder only)."""
    action = QAction(t("images.folder.new_folder"), parent)
    if icon is not None and not icon.isNull():
        action.setIcon(icon)
    action.setEnabled(enabled)
    action.triggered.connect(on_new_folder)
    menu.addAction(action)
