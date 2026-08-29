"""Thin event bus. Screens emit names only; the controller owns progression."""

from __future__ import annotations

from collections.abc import Callable

_BUS_ATTR = "_capixe_tour_bus"

Listener = Callable[[str, dict], None]


class TourEventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self.generation = 0

    def subscribe(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def bump_generation(self) -> int:
        self.generation += 1
        return self.generation

    def emit(self, name: str, payload: dict | None = None) -> None:
        data = dict(payload or {})
        for listener in list(self._listeners):
            listener(name, data)


def install_tour_bus(app, bus: TourEventBus | None = None) -> TourEventBus:
    existing = getattr(app, _BUS_ATTR, None)
    if isinstance(existing, TourEventBus):
        return existing
    created = bus or TourEventBus()
    setattr(app, _BUS_ATTR, created)
    return created


def uninstall_tour_bus(app) -> None:
    if hasattr(app, _BUS_ATTR):
        delattr(app, _BUS_ATTR)


def get_tour_bus(app=None) -> TourEventBus | None:
    if app is None:
        try:
            from PySide6.QtWidgets import QApplication
        except Exception:
            return None
        app = QApplication.instance()
    if app is None:
        return None
    bus = getattr(app, _BUS_ATTR, None)
    return bus if isinstance(bus, TourEventBus) else None


_FALLBACK_GENERATION = 0


def tour_event_generation() -> int:
    bus = get_tour_bus()
    if bus is not None:
        return bus.generation
    return _FALLBACK_GENERATION


def bump_tour_generation() -> int:
    """Mark a new step entry. Later events must carry this generation to complete."""
    global _FALLBACK_GENERATION
    bus = get_tour_bus()
    if bus is not None:
        return bus.bump_generation()
    _FALLBACK_GENERATION += 1
    return _FALLBACK_GENERATION


def emit_tour_event(name: str, **payload) -> None:
    """No-op when the tour is not installed. Never include query/path/image."""
    bus = get_tour_bus()
    if bus is None:
        return
    bus.emit(name, payload)
