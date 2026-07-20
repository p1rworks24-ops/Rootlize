from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QFrame,
    QButtonGroup,
    QSizePolicy,
)

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.flow_layout import FlowLayout
from app.ui.icons import icon_add, icon_clear, icon_search
from app.ui.scroll_page import make_page_scroll
from app.utils.tag_format import format_tag, normalize_tag


class TagsPage(QWidget):
    """Common tag master management (not per-project)."""

    tags_changed = Signal()

    def __init__(
        self,
        metadata_service: MetadataService,
        app_root: Path,
        config: dict,
        parent=None,
    ):
        super().__init__(parent)
        self._metadata_service = metadata_service
        self._app_root = app_root
        self._config = config
        self._all_tags: list[str] = []
        self._chip_buttons: dict[str, QPushButton] = {}
        self._selected_tag = ""
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        content.setObjectName("tagsContentColumn")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(12)

        from app.ui.page_header import make_page_header

        layout.addWidget(
            make_page_header(content, t("tags.title"), t("tags.subtitle"))
        )

        hint = QLabel(t("tags.hint"), content)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Search — same pattern as Images
        search_row = QWidget(content)
        search_row.setObjectName("tagsSearchRow")
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 2, 0, 4)
        search_layout.setSpacing(6)

        self._search_input = QLineEdit(search_row)
        self._search_input.setObjectName("tagsSearchInput")
        self._search_input.setPlaceholderText(t("tags.search_placeholder"))
        self._search_input.returnPressed.connect(self._apply_filter)
        self._search_input.textChanged.connect(self._apply_filter)
        search_layout.addWidget(self._search_input, stretch=1)

        search_btn = QPushButton(t("tags.search"), search_row)
        search_btn.setIcon(icon_search())
        search_btn.setIconSize(QSize(14, 14))
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(self._apply_filter)
        search_layout.addWidget(search_btn)

        clear_btn = QPushButton(t("tags.clear"), search_row)
        clear_btn.setObjectName("secondaryButton")
        clear_btn.setIcon(icon_clear())
        clear_btn.setIconSize(QSize(14, 14))
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear_search)
        search_layout.addWidget(clear_btn)
        layout.addWidget(search_row)

        # Chip board — compact tag pills, not full-width rows
        chip_panel = QFrame(content)
        chip_panel.setObjectName("tagsChipPanel")
        chip_panel.setMinimumHeight(160)
        chip_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        chip_outer = QVBoxLayout(chip_panel)
        chip_outer.setContentsMargins(12, 12, 12, 12)
        chip_outer.setSpacing(8)

        board_title = QLabel(t("tags.board_title"), chip_panel)
        board_title.setObjectName("sectionTitle")
        chip_outer.addWidget(board_title)

        self._empty_label = QLabel(t("tags.empty"), chip_panel)
        self._empty_label.setObjectName("mutedLabel")
        self._empty_label.setAlignment(Qt.AlignCenter)
        chip_outer.addWidget(self._empty_label)

        self._chips_host = QWidget(chip_panel)
        self._chips_host.setObjectName("tagsChipHost")
        self._chips_layout = FlowLayout(self._chips_host, spacing=8)
        self._chips_host.setLayout(self._chips_layout)
        chip_outer.addWidget(self._chips_host)

        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chip_group.idToggled.connect(self._on_chip_toggled)

        layout.addWidget(chip_panel)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._new_tag_input = QLineEdit(content)
        self._new_tag_input.setPlaceholderText(t("tags.new_placeholder"))
        self._new_tag_input.returnPressed.connect(self._on_add)
        add_row.addWidget(self._new_tag_input, stretch=1)

        add_btn = QPushButton(t("tags.add"), content)
        add_btn.setIcon(icon_add())
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        rename_btn = QPushButton(t("tags.rename"), content)
        rename_btn.setObjectName("secondaryButton")
        rename_btn.setCursor(Qt.PointingHandCursor)
        rename_btn.clicked.connect(self._on_rename)
        actions.addWidget(rename_btn)

        delete_btn = QPushButton(t("tags.delete"), content)
        delete_btn.setObjectName("secondaryButton")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(delete_btn)
        actions.addStretch()
        layout.addLayout(actions)

        layout.addStretch(1)
        content.setMinimumWidth(360)
        content.setMinimumHeight(420)

    def refresh(self) -> None:
        self._all_tags = list(
            self._metadata_service.load_global_tags(self._app_root, force_reload=True)
        )
        self._rebuild_chips()
        self._apply_filter()

    def _clear_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                self._chip_group.removeButton(widget)
                widget.deleteLater()
        self._chip_buttons.clear()

    def _rebuild_chips(self) -> None:
        prev = self._selected_tag
        self._clear_chips()
        for i, tag in enumerate(self._all_tags):
            btn = QPushButton(format_tag(tag), self._chips_host)
            btn.setObjectName("tagMasterChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tag)
            self._chip_group.addButton(btn, i)
            self._chips_layout.addWidget(btn)
            self._chip_buttons[tag] = btn
            if tag == prev:
                btn.setChecked(True)
                self._selected_tag = tag

        if prev and prev not in self._chip_buttons:
            self._selected_tag = ""

        self._empty_label.setVisible(not self._all_tags)
        self._chips_host.setVisible(bool(self._all_tags))

    def _apply_filter(self) -> None:
        query = (self._search_input.text() or "").strip().casefold()
        visible = 0
        for tag, btn in self._chip_buttons.items():
            show = (not query) or (query in tag.casefold()) or (
                query in format_tag(tag).casefold()
            )
            btn.setVisible(show)
            if show:
                visible += 1
        has_tags = bool(self._all_tags)
        self._empty_label.setVisible(has_tags and visible == 0)
        if has_tags and visible == 0:
            self._empty_label.setText(t("tags.search_empty"))
        elif not has_tags:
            self._empty_label.setText(t("tags.empty"))
            self._empty_label.setVisible(True)
        # Relayout after show/hide — otherwise restored chips keep old geometry
        # and overlap when clearing a search filter.
        self._relayout_chips()

    def _relayout_chips(self) -> None:
        self._chips_layout.invalidate()
        width = self._chips_host.width()
        if width <= 0:
            panel = self._chips_host.parentWidget()
            width = panel.width() - 24 if panel is not None else 400
        width = max(width, 120)
        height = self._chips_layout.heightForWidth(width)
        self._chips_host.setMinimumHeight(height)
        self._chips_host.setMaximumHeight(16777215)
        self._chips_layout.activate()
        self._chips_host.updateGeometry()
        self._chips_host.update()
        panel = self._chips_host.parentWidget()
        if panel is not None and panel.layout() is not None:
            panel.layout().invalidate()
            panel.updateGeometry()

    def _on_clear_search(self) -> None:
        self._search_input.clear()
        self._apply_filter()

    def _on_chip_toggled(self, button_id: int, checked: bool) -> None:
        if not checked:
            return
        btn = self._chip_group.button(button_id)
        if btn is None:
            return
        for tag, chip in self._chip_buttons.items():
            if chip is btn:
                self._selected_tag = tag
                return

    def _selected(self) -> str:
        return self._selected_tag

    def _on_add(self) -> None:
        name = normalize_tag(self._new_tag_input.text())
        if not name:
            return
        try:
            created = self._metadata_service.add_global_tag(self._app_root, name)
            self._new_tag_input.clear()
            self.refresh()
            self.tags_changed.emit()
            if created and created in self._chip_buttons:
                self._chip_buttons[created].setChecked(True)
                self._selected_tag = created
            if created and created != name:
                QMessageBox.information(
                    self,
                    t("common.tag"),
                    t("tags.added_as", name=created),
                )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("tags.add_failed", error=e)
            )

    def _on_rename(self) -> None:
        old = self._selected()
        if not old:
            QMessageBox.information(self, t("common.tag"), t("tags.select_first"))
            return
        text, ok = QInputDialog.getText(
            self,
            t("tags.rename_title"),
            t("tags.rename_prompt"),
            text=old,
        )
        if not ok:
            return
        new = normalize_tag(text)
        if not new or new == old:
            return
        try:
            renamed = self._metadata_service.rename_global_tag(
                self._app_root, old, new
            )
            if renamed is None:
                return
            self._selected_tag = renamed
            self.refresh()
            self.tags_changed.emit()
            if renamed in self._chip_buttons:
                self._chip_buttons[renamed].setChecked(True)
            if renamed != new:
                QMessageBox.information(
                    self,
                    t("common.tag"),
                    t("tags.renamed_as", name=renamed),
                )
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("tags.rename_failed", error=e)
            )

    def _on_delete(self) -> None:
        tag = self._selected()
        if not tag:
            QMessageBox.information(self, t("common.tag"), t("tags.select_first"))
            return
        reply = QMessageBox.question(
            self,
            t("common.confirm_delete"),
            t("tags.delete_confirm", name=format_tag(tag)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._metadata_service.remove_global_tag(self._app_root, tag)
            self._selected_tag = ""
            self.refresh()
            self.tags_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("tags.delete_failed", error=e)
            )
