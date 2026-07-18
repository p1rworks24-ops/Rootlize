"""Windows keyboard shortcuts via SendInput (no extra dependencies)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_S = 0x53

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT),
    ]


def _key_event(vk: int, *, key_up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else 0
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=ULONG_PTR(0),
        ),
    )


def send_win_shift_s() -> bool:
    """
    Send Win+Shift+S (Windows Snipping Tool / Screen Sketch).

    Returns True if the keys were sent, False if not on Windows or SendInput failed.
    """
    if sys.platform != "win32":
        return False

    events = [
        _key_event(VK_LWIN),
        _key_event(VK_SHIFT),
        _key_event(VK_S),
        _key_event(VK_S, key_up=True),
        _key_event(VK_SHIFT, key_up=True),
        _key_event(VK_LWIN, key_up=True),
    ]
    array_type = INPUT * len(events)
    inputs = array_type(*events)
    sent = ctypes.windll.user32.SendInput(
        len(events),
        ctypes.byref(inputs),
        ctypes.sizeof(INPUT),
    )
    return sent == len(events)
