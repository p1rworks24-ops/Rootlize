"""Resize a running Capixe window and grab desktop shots. Does not write config."""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication

SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
SWP_NOMOVE = 0x0002
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SW_RESTORE = 9

user32 = ctypes.windll.user32
user32.EnumWindows.argtypes = [
    ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM),
    wintypes.LPARAM,
]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD),
]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]


def find_windows(pid: int) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if proc.value != pid:
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if title and user32.IsWindowVisible(hwnd):
            found.append((int(hwnd), title))
        return True

    user32.EnumWindows(enum_cb, 0)
    return found


def grab(hwnd: int, path: Path) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    screen = QGuiApplication.primaryScreen()
    geo = QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    pix = screen.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
    pix.save(str(path))
    return rect.left, rect.top, pix.width(), pix.height()


def main() -> int:
    pid = int(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    hwnd = 0
    title = ""
    for _ in range(30):
        windows = find_windows(pid)
        if windows:
            hwnd, title = windows[0]
            break
        time.sleep(0.5)
    if not hwnd:
        print("no window")
        return 1
    print(f"window title={title!r} hwnd={hwnd}")
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 40, 40, 1600, 900, SWP_SHOWWINDOW)
    user32.SetForegroundWindow(hwnd)
    time.sleep(2.0)
    print("1600", grab(hwnd, out / "exe-1600x900.png"))
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 40, 40, 1100, 900, SWP_SHOWWINDOW)
    time.sleep(1.5)
    print("1100", grab(hwnd, out / "exe-1100x900.png"))
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 40, 40, 1600, 900, SWP_SHOWWINDOW)
    time.sleep(0.8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
