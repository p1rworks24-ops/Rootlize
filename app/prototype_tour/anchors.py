"""Live widget anchors. Overlay reads geometry; it never hardcodes coordinates."""

from __future__ import annotations

from weakref import ref

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QWidget


class AnchorRegistry:
    def __init__(self) -> None:
        self._widgets: dict[str, ref[QWidget]] = {}

    def register(self, key: str, widget: QWidget | None) -> None:
        name = str(key or "").strip()
        if not name:
            return
        if widget is None:
            self._widgets.pop(name, None)
            return
        widget.setProperty("prototype_anchor", name)
        self._widgets[name] = ref(widget)

    def unregister(self, key: str) -> None:
        self._widgets.pop(str(key or ""), None)

    def widget(self, key: str) -> QWidget | None:
        held = self._widgets.get(str(key or ""))
        if held is None:
            return None
        widget = held()
        if widget is None:
            self._widgets.pop(key, None)
            return None
        try:
            visible = widget.isVisible()
        except RuntimeError:
            self._widgets.pop(key, None)
            return None
        return widget if visible else None

    def visible_all(self, keys: tuple[str, ...] | list[str]) -> list[tuple[str, QWidget]]:
        found: list[tuple[str, QWidget]] = []
        for key in keys:
            widget = self.widget(key)
            if widget is not None:
                found.append((key, widget))
        return found

    def first_visible(self, keys: tuple[str, ...] | list[str]) -> tuple[str, QWidget] | None:
        found = self.visible_all(keys)
        return found[0] if found else None

    def rect_in(self, overlay: QWidget, key: str, *, pad: int = 8) -> QRect | None:
        widget = self.widget(key)
        if widget is None:
            return None
        return widget_rect_in(overlay, widget, pad=pad)


def widget_rect_in(overlay: QWidget, widget: QWidget, *, pad: int = 8) -> QRect:
    origin = widget.mapToGlobal(QPoint(0, 0))
    local = overlay.mapFromGlobal(origin)
    rect = QRect(local, widget.size()).adjusted(-pad, -pad, pad, pad)
    bounds = overlay.rect().adjusted(8, 8, -8, -8)
    return rect.intersected(bounds)
