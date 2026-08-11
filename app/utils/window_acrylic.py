"""Optional Windows acrylic / blur behind frameless panels."""

from __future__ import annotations

import sys


def set_windows_caption_color(widget, color: str) -> bool:
    """Set the native Windows title-bar background color from ``#RRGGBB``."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        value = color.removeprefix("#")
        if len(value) != 6:
            return False
        red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    except (ImportError, TypeError, ValueError):
        return False

    hwnd = int(widget.winId())
    if not hwnd:
        return False

    # DWMWA_CAPTION_COLOR = 35; COLORREF stores bytes as 0x00BBGGRR.
    DWMWA_CAPTION_COLOR = 35
    caption_color = ctypes.c_uint32(red | (green << 8) | (blue << 16))
    try:
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_uint(DWMWA_CAPTION_COLOR),
            ctypes.byref(caption_color),
            ctypes.sizeof(caption_color),
        )
    except (AttributeError, OSError):
        return False
    return result == 0


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
