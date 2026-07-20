"""
Temporarily suppress Windows Snipping Tool / Screen Sketch toast notifications.

HKCU only — no elevation required. While this process holds the suppress
context, Screen Sketch toasts are disabled; the previous Enabled values are
restored when the context exits (app quit).
"""

from __future__ import annotations

import atexit
import sys
from typing import Any

# Known Screen Sketch / Snipping Tool notification sender ids (Win10/11).
_SCREEN_SKETCH_SENDERS = (
    "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "Microsoft.ScreenSketch_8wekyb3d8bbwe!screenSketch",
    "MicrosoftWindows.Client.CBS_cw5n1h2txyewy!ScreenSketch",
)

_SETTINGS_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"


class SnippingToastSuppressor:
    """
    Disable Screen Sketch toasts for the lifetime of the app session.

    Safe to call on non-Windows platforms (no-op). Nested enter/exit is
    reference-counted so multiple callers do not clobber each other.
    """

    def __init__(self) -> None:
        self._depth = 0
        self._saved: dict[str, Any] = {}

    def enter(self) -> None:
        if sys.platform != "win32":
            return
        self._depth += 1
        if self._depth != 1:
            return
        try:
            import winreg
        except ImportError:
            return

        self._saved.clear()
        senders = set(_SCREEN_SKETCH_SENDERS)
        senders.update(self._discover_screen_sketch_senders(winreg))
        for sender in senders:
            self._set_enabled(winreg, sender, enabled=0, remember=True)

    def exit(self) -> None:
        if sys.platform != "win32":
            return
        if self._depth <= 0:
            return
        self._depth -= 1
        if self._depth != 0:
            return
        try:
            import winreg
        except ImportError:
            self._saved.clear()
            return

        for sender, previous in list(self._saved.items()):
            self._restore_enabled(winreg, sender, previous)
        self._saved.clear()

    @staticmethod
    def _discover_screen_sketch_senders(winreg) -> set[str]:
        found: set[str] = set()
        try:
            root = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _SETTINGS_ROOT, 0, winreg.KEY_READ
            )
        except OSError:
            return found
        try:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                lower = name.lower()
                if "screensketch" in lower or "screenclip" in lower or "snipping" in lower:
                    found.add(name)
        finally:
            winreg.CloseKey(root)
        return found

    def _set_enabled(
        self, winreg, sender: str, *, enabled: int, remember: bool
    ) -> None:
        key_path = f"{_SETTINGS_ROOT}\\{sender}"
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            )
        except OSError:
            return
        try:
            if remember and sender not in self._saved:
                try:
                    previous, _ = winreg.QueryValueEx(key, "Enabled")
                    self._saved[sender] = int(previous)
                except FileNotFoundError:
                    self._saved[sender] = None
            winreg.SetValueEx(key, "Enabled", 0, winreg.REG_DWORD, int(enabled))
        except OSError:
            pass
        finally:
            winreg.CloseKey(key)

    @staticmethod
    def _restore_enabled(winreg, sender: str, previous: Any) -> None:
        key_path = f"{_SETTINGS_ROOT}\\{sender}"
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE,
            )
        except OSError:
            return
        try:
            if previous is None:
                try:
                    winreg.DeleteValue(key, "Enabled")
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(
                    key, "Enabled", 0, winreg.REG_DWORD, int(previous)
                )
        except OSError:
            pass
        finally:
            winreg.CloseKey(key)


# Process-wide suppressor used by MainWindow
snipping_toast_suppressor = SnippingToastSuppressor()
atexit.register(snipping_toast_suppressor.exit)

