from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLineEdit,
    QInputDialog,
    QMessageBox,
)

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.icons import icon_add
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
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = make_page_scroll(self)
        outer.addWidget(scroll)

        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(t("tags.title"), content)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(t("tags.subtitle"), content)
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        hint = QLabel(t("tags.hint"), content)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget(content)
        self._list.setMinimumHeight(220)
        layout.addWidget(self._list, stretch=1)

        add_row = QHBoxLayout()
        self._new_tag_input = QLineEdit(content)
        self._new_tag_input.setPlaceholderText(t("tags.new_placeholder"))
        self._new_tag_input.returnPressed.connect(self._on_add)
        add_row.addWidget(self._new_tag_input)

        add_btn = QPushButton(t("tags.add"), content)
        add_btn.setIcon(icon_add())
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        actions = QHBoxLayout()
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

        content.setMinimumWidth(360)
        content.setMinimumHeight(420)

    def refresh(self) -> None:
        self._list.clear()
        for tag in self._metadata_service.load_global_tags(
            self._app_root, force_reload=True
        ):
            item = QListWidgetItem(format_tag(tag))
            item.setData(Qt.UserRole, tag)
            self._list.addItem(item)

    def _selected_tag(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ""
        data = item.data(Qt.UserRole)
        if data:
            return str(data)
        return normalize_tag(item.text())

    def _on_add(self) -> None:
        name = normalize_tag(self._new_tag_input.text())
        if not name:
            return
        try:
            created = self._metadata_service.add_global_tag(self._app_root, name)
            self._new_tag_input.clear()
            self.refresh()
            self.tags_changed.emit()
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
        old = self._selected_tag()
        if not old:
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
            self.refresh()
            self.tags_changed.emit()
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
        tag = self._selected_tag()
        if not tag:
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
            self.refresh()
            self.tags_changed.emit()
        except OSError as e:
            QMessageBox.critical(
                self, t("common.error"), t("tags.delete_failed", error=e)
            )
