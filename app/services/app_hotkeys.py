"""App-lifetime hotkey registration (Windows RegisterHotKey).

Active only while the process runs — no tray resident / service.
Designed so a future always-on-top / tray host can reuse the same bindings.

Hotkeys stay disarmed until the UI finishes startup (splash), so queued or
spurious WM_HOTKEY messages cannot start Capture during launch.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from app.services.shortcut_spec import (
    SHORTCUT_ACTIONS,
    normalize_shortcut,
    validate_shortcut,
)
from app.utils.logger import setup_logger

logger = setup_logger()


def _real_registration_enabled() -> bool:
    """Skip Win32 RegisterHotKey under pytest (avoids OS conflicts / aborts)."""
    return sys.platform == "win32" and "pytest" not in sys.modules


WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_SNAPSHOT = 0x2C
VK_DELETE = 0x2E
VK_INSERT = 0x2D
VK_HOME = 0x24
VK_END = 0x23
VK_PRIOR = 0x21  # PageUp
VK_NEXT = 0x22  # PageDown

# Bits present in WM_HOTKEY lParam (RegisterHotKey's MOD_NOREPEAT is not echoed)
_HOTKEY_MOD_MASK = MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_WIN


def _qt_key_to_vk(key: Qt.Key) -> int | None:
    if Qt.Key_A <= key <= Qt.Key_Z:
        return int(key)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return int(key)
    if Qt.Key_F1 <= key <= Qt.Key_F12:
        return 0x70 + (int(key) - int(Qt.Key_F1))
    mapping = {
        Qt.Key_Print: VK_SNAPSHOT,
        Qt.Key_Delete: VK_DELETE,
        Qt.Key_Insert: VK_INSERT,
        Qt.Key_Home: VK_HOME,
        Qt.Key_End: VK_END,
        Qt.Key_PageUp: VK_PRIOR,
        Qt.Key_PageDown: VK_NEXT,
    }
    return mapping.get(key)


def _sequence_to_win(text: str) -> tuple[int, int] | None:
    """Return (win_mods_including_NOREPEAT, vk) for RegisterHotKey, or None."""
    ok, _ = validate_shortcut(text)
    if not ok:
        return None
    seq = QKeySequence(normalize_shortcut(text) or "")
    if seq.count() != 1:
        return None
    combo = seq[0]
    key = combo.key()
    mods = combo.keyboardModifiers()
    vk = _qt_key_to_vk(key)
    if vk is None:
        return None
    win_mods = MOD_NOREPEAT
    if mods & Qt.ControlModifier:
        win_mods |= MOD_CONTROL
    if mods & Qt.ShiftModifier:
        win_mods |= MOD_SHIFT
    if mods & Qt.AltModifier:
        win_mods |= MOD_ALT
    return win_mods, vk


def _message_address(message) -> int:
    """Resolve the void* message parameter to an integer address (PySide6-safe)."""
    if message is None:
        return 0
    if isinstance(message, int):
        return message
    # Shiboken VoidPtr / wrappers
    for attr in ("__int__", "__index__"):
        fn = getattr(message, attr, None)
        if callable(fn):
            try:
                return int(fn())
            except (TypeError, ValueError, OverflowError):
                pass
    try:
        return int(message)
    except (TypeError, ValueError, OverflowError):
        return 0


class _HotkeyNativeFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "AppHotkeyManager") -> None:
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        """
        Handle WM_HOTKEY only.

        Important:
        - Never return True for unknown messages (would swallow clicks / resize).
        - Verify lParam matches the binding we registered (rejects mis-parsed MSG).
        - Defer the Python callback so we do not re-enter Qt from the filter.
        """
        if sys.platform != "win32":
            return False
        et = bytes(eventType) if not isinstance(eventType, (bytes, bytearray)) else bytes(eventType)
        # Hotkeys are delivered as dispatcher messages; also accept generic on some Qt builds.
        if et not in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            return False

        addr = _message_address(message)
        if addr == 0:
            return False
        try:
            msg = ctypes.cast(addr, ctypes.POINTER(wintypes.MSG)).contents
        except (TypeError, ValueError, OSError):
            return False

        if int(msg.message) != WM_HOTKEY:
            return False

        hotkey_id = int(msg.wParam)
        binding = self._manager._id_to_binding.get(hotkey_id)
        if binding is None:
            return False

        # WM_HOTKEY lParam: low word = mods, high word = vk
        lparam = int(msg.lParam)
        event_mods = lparam & 0xFFFF
        event_vk = (lparam >> 16) & 0xFFFF
        expected_mods, expected_vk = binding[1], binding[2]
        if event_vk != expected_vk or (event_mods & _HOTKEY_MOD_MASK) != (
            expected_mods & _HOTKEY_MOD_MASK
        ):
            logger.warning(
                "Ignoring WM_HOTKEY id=%s with mismatched lParam "
                "(mods=0x%X vk=0x%X; expected mods=0x%X vk=0x%X)",
                hotkey_id,
                event_mods,
                event_vk,
                expected_mods & _HOTKEY_MOD_MASK,
                expected_vk,
            )
            return False

        if not self._manager.is_armed:
            # Consume during startup so the message is not re-dispatched oddly,
            # but do not start Capture.
            return True

        generation = self._manager._generation
        # Defer: starting capture (minimize/grab) inside the native filter breaks
        # the first UI click and can reset window geometry oddly.
        QTimer.singleShot(
            0,
            lambda hid=hotkey_id, gen=generation: self._manager._handle_hotkey_id(
                hid, gen
            ),
        )
        return True


class AppHotkeyManager(QObject):
    """
    Registers global hotkeys for the life of the QApplication.

    Emits activated(action_id) when a bound shortcut is pressed.
    """

    activated = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bindings: dict[str, str] = {}
        # hotkey_id -> (action_id, win_mods_without_norepeat, vk)
        self._id_to_binding: dict[int, tuple[str, int, int]] = {}
        self._next_id = 1
        self._generation = 0
        self._armed = False
        self._filter: _HotkeyNativeFilter | None = None
        self._started = False

    @property
    def is_armed(self) -> bool:
        return self._armed

    def set_armed(self, armed: bool) -> None:
        """Enable/disable Capture activation from registered hotkeys."""
        self._armed = bool(armed)

    def start(self, app: QApplication | None = None) -> None:
        """Install the native filter (idempotent)."""
        if self._started:
            return
        application = app or QApplication.instance()
        if application is None:
            return
        self._filter = _HotkeyNativeFilter(self)
        application.installNativeEventFilter(self._filter)
        self._started = True

    def stop(self) -> None:
        """Unregister all hotkeys and remove the native filter."""
        self.set_armed(False)
        self.clear()
        application = QApplication.instance()
        if application is not None and self._filter is not None:
            application.removeNativeEventFilter(self._filter)
        self._filter = None
        self._started = False

    def clear(self) -> None:
        self._generation += 1
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            for hotkey_id in list(self._id_to_binding):
                user32.UnregisterHotKey(None, hotkey_id)
        self._id_to_binding.clear()

    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def set_bindings(self, bindings: dict[str, str]) -> dict[str, str]:
        """
        Replace registered hotkeys.

        Returns {action_id: reason} for actions that failed to register.
        """
        self.clear()
        self._bindings = {}
        failures: dict[str, str] = {}

        for action_id in SHORTCUT_ACTIONS:
            text = normalize_shortcut(bindings.get(action_id))
            if text and validate_shortcut(text)[0]:
                self._bindings[action_id] = text

        if not _real_registration_enabled():
            if sys.platform != "win32":
                logger.warning("Global capture hotkeys are only supported on Windows.")
                return {a: "unsupported_platform" for a in SHORTCUT_ACTIONS}
            return {}

        user32 = ctypes.windll.user32
        for action_id in SHORTCUT_ACTIONS:
            text = self._bindings.get(action_id)
            if not text:
                failures[action_id] = "empty"
                continue
            converted = _sequence_to_win(text)
            if converted is None:
                failures[action_id] = "unsupported"
                continue
            win_mods, vk = converted
            hotkey_id = self._next_id
            self._next_id += 1
            if not user32.RegisterHotKey(None, hotkey_id, win_mods, vk):
                logger.warning(
                    "RegisterHotKey failed for %s (%s)", action_id, text
                )
                failures[action_id] = "register_failed"
                continue
            self._id_to_binding[hotkey_id] = (
                action_id,
                win_mods & _HOTKEY_MOD_MASK,
                vk,
            )
            logger.info("Registered hotkey %s → %s (id=%s)", text, action_id, hotkey_id)
        return failures

    def _handle_hotkey_id(
        self, hotkey_id: int, generation: int | None = None
    ) -> None:
        if not self._armed:
            return
        if generation is not None and generation != self._generation:
            return
        binding = self._id_to_binding.get(hotkey_id)
        if binding is None:
            return
        self.activated.emit(binding[0])

    # Back-compat for tests that inspected the old map
    @property
    def _id_to_action(self) -> dict[int, str]:
        return {hid: binding[0] for hid, binding in self._id_to_binding.items()}
