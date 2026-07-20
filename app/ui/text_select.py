"""Enable click-drag text selection on labels across the app."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

_SELECTABLE = Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard

# Chrome / toolbar labels — keep as labels (no I-beam caret)
_SKIP_OBJECT_NAMES = frozenset(
    {
        "toolbarFieldLabel",
        "sectionIcon",
        "compactFieldLabel",
        "compactFieldChevron",
        "compactFieldHint",
        "capturePanelTitle",
        "capturePanelFieldHint",
        "captureModeCycleLabel",
        "sidebarBrand",
        "organizeFolderLabel",
        "organizeListTitle",
        "organizeOpsTitle",
        "organizeOpsHint",
        "operationMenuIcon",
        "operationMenuTitle",
        "operationMenuDesc",
        "operationMenuStatus",
        "splashTitle",
        "splashBadge",
        "splashNavBrand",
    }
)


def enable_label_text_selection(root: QWidget) -> None:
    """Make QLabel text selectable by mouse drag (and keyboard) under root."""
    labels: list[QLabel] = []
    if isinstance(root, QLabel):
        labels.append(root)
    labels.extend(root.findChildren(QLabel))
    for label in labels:
        if not (label.text() or "").strip():
            continue
        if label.objectName() in _SKIP_OBJECT_NAMES:
            continue
        label.setTextInteractionFlags(_SELECTABLE)
        label.setCursor(Qt.IBeamCursor)
