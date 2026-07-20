"""Optional Windows acrylic / blur behind frameless panels."""

from __future__ import annotations

import sys


def enable_light_acrylic(widget) -> bool:
    """
    Enable a light acrylic-like backdrop on Windows 11+.

    Returns True if the attribute was applied. Safe no-op elsewhere.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    hwnd = int(widget.winId())
    if not hwnd:
        return False

    # DWMWA_SYSTEMBACKDROP_TYPE = 38
    # DWMSBT_TRANSIENTWINDOW = 3 (Acrylic)
    # DWMSBT_MAINWINDOW = 2 (Mica)
    DWMWA_SYSTEMBACKDROP_TYPE = 38
    DWMSBT_TRANSIENTWINDOW = 3
    value = ctypes.c_int(DWMSBT_TRANSIENTWINDOW)
    try:
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except (AttributeError, OSError):
        return False
    return result == 0
