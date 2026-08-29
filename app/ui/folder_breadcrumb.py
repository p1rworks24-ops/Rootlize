"""Single-line folder breadcrumb and child-folder chip strip."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

_ANCHOR_NAMES = {
    "pictures",
    "desktop",
    "documents",
    "downloads",
    "onedrive",
    "capixe",
}


class FolderChipItem:
    """QListWidgetItem-compatible chip used by existing folder tests."""

    def __init__(self, text: str, path: str) -> None:
        self._text = text
        self._path = path

    def text(self) -> str:
        return self._text

    def data(self, _role: int = 0) -> str:
        return self._path


class FolderBreadcrumb(QScrollArea):
    """Clickable path crumbs on one row, collapsing from the left with …."""

    folder_activated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("folderBreadcrumb")
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(32)
        self._path: Path | None = None
        self._segments: list[tuple[str, Path]] = []
        self._inner = QWidget(self)
        self._inner.setObjectName("folderBreadcrumbInner")
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setWidget(self._inner)

    def path(self) -> Path | None:
        return self._path

    def set_path(self, folder: Path | None) -> None:
        self._path = folder
        self._segments = self._split(folder)
        self.setToolTip("" if folder is None else str(folder))
        self._rebuild()

    @staticmethod
    def _split(folder: Path | None) -> list[tuple[str, Path]]:
        if folder is None:
            return []
        parts: list[tuple[str, Path]] = []
        current = folder
        while True:
            name = current.name or str(current)
            parts.append((name, current))
            parent = current.parent
            if parent == current:
                break
            current = parent
        parts.reverse()
        anchor = 0
        for index, (name, _path) in enumerate(parts):
            if name.casefold() in _ANCHOR_NAMES:
                anchor = index
        return parts[anchor:]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_leading_ellipsis()

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild(self) -> None:
        self._clear_layout()
        if not self._segments:
            placeholder = QLabel("…", self._inner)
            placeholder.setObjectName("folderBreadcrumbEllipsis")
            self._layout.addWidget(placeholder, 0, Qt.AlignVCenter)
            self._fit_inner()
            return

        for index, (name, path) in enumerate(self._segments):
            button = self._crumb_button(name, path, current=index == len(self._segments) - 1)
            self._layout.addWidget(button, 0, Qt.AlignVCenter)
            if index < len(self._segments) - 1:
                sep = QLabel("›", self._inner)
                sep.setObjectName("folderBreadcrumbSep")
                self._layout.addWidget(sep, 0, Qt.AlignVCenter)
        self._fit_inner()
        self._apply_leading_ellipsis()

    def _fit_inner(self) -> None:
        self._inner.adjustSize()
        width = max(self._inner.sizeHint().width(), self.viewport().width())
        self._inner.resize(width, max(self.height() - 2, 28))

    def _apply_leading_ellipsis(self) -> None:
        viewport_w = self.viewport().width()
        if viewport_w <= 8 or not self._segments:
            return
        widgets = [
            self._layout.itemAt(index).widget()
            for index in range(self._layout.count())
            if self._layout.itemAt(index).widget() is not None
        ]
        crumbs = [
            widget
            for widget in widgets
            if widget.objectName() == "folderBreadcrumbCrumb"
        ]
        seps = [
            widget
            for widget in widgets
            if widget.objectName() == "folderBreadcrumbSep"
        ]
        for widget in widgets:
            widget.show()
        existing = [
            widget
            for widget in widgets
            if widget.objectName() == "folderBreadcrumbEllipsis"
        ]
        ellipsis = existing[0] if existing else None
        if ellipsis is None:
            ellipsis = QLabel("…", self._inner)
            ellipsis.setObjectName("folderBreadcrumbEllipsis")
            self._layout.insertWidget(0, ellipsis, 0, Qt.AlignVCenter)
        ellipsis.hide()

        hidden = 0
        while (
            hidden < max(0, len(crumbs) - 1)
            and self._inner.sizeHint().width() > viewport_w
        ):
            crumbs[hidden].hide()
            if hidden < len(seps):
                seps[hidden].hide()
            ellipsis.show()
            hidden += 1
            self._inner.adjustSize()
        self._fit_inner()

    def _crumb_button(self, name: str, path: Path, *, current: bool) -> QPushButton:
        button = QPushButton(name, self._inner)
        button.setObjectName("folderBreadcrumbCrumb")
        button.setCursor(Qt.PointingHandCursor)
        button.setCheckable(False)
        button.setFlat(True)
        button.setToolTip(str(path))
        if current:
            button.setProperty("currentFolder", True)
        button.clicked.connect(
            lambda _checked=False, target=str(path): self.folder_activated.emit(target)
        )
        return button


class ChildFolderRow(QScrollArea):
    """Immediate child folders as a single horizontally scrolling chip row."""

    folder_activated = Signal(str)
    itemClicked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("childFolderList")
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(48)
        self._items: list[FolderChipItem] = []
        self._inner = QWidget(self)
        self._inner.setObjectName("childFolderListInner")
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setWidget(self._inner)

    def count(self) -> int:
        return len(self._items)

    def item(self, index: int) -> FolderChipItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def clear(self) -> None:
        self._items.clear()
        while self._layout.count():
            layout_item = self._layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def addItem(self, item: FolderChipItem) -> None:
        self._items.append(item)
        button = QPushButton(item.text(), self._inner)
        button.setObjectName("childFolderChip")
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(item.data())
        button.clicked.connect(lambda _checked=False, chip=item: self._emit_item(chip))
        self._layout.addWidget(button, 0, Qt.AlignVCenter)

    def finish(self) -> None:
        self._inner.adjustSize()
        width = max(self._inner.sizeHint().width(), self.viewport().width())
        self._inner.resize(width, max(self.height() - 2, 44))

    def _emit_item(self, item: FolderChipItem) -> None:
        self.itemClicked.emit(item)
        self.folder_activated.emit(item.data())
