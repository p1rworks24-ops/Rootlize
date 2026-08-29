"""Focus packaged Capixe and submit Meaning search 'dog'."""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
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

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_F = 0x46
SW_RESTORE = 9


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


def _key(vk: int, up: bool = False) -> None:
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def type_text(text: str) -> None:
    for char in text:
        vk = user32.VkKeyScanW(ord(char)) & 0xFF
        _key(vk)
        _key(vk, up=True)
        time.sleep(0.04)


def click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def foreground(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_RESTORE)
    current = user32.GetForegroundWindow()
    pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    current_thread = user32.GetWindowThreadProcessId(current, ctypes.byref(pid))
    this_thread = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(this_thread, target_thread, True)
    if current_thread:
        user32.AttachThreadInput(this_thread, current_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(this_thread, target_thread, False)
    if current_thread:
        user32.AttachThreadInput(this_thread, current_thread, False)


def main() -> int:
    pid = int(sys.argv[1])
    hwnd = 0
    title = ""
    for _ in range(50):
        windows = find_windows(pid)
        if windows:
            hwnd, title = windows[0]
            break
        time.sleep(0.2)
    if not hwnd:
        print("no window")
        return 1
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    foreground(hwnd)
    time.sleep(0.3)
    # Search field sits in the top command row, right of the nav.
    click(rect.left + 430, rect.top + 95)
    time.sleep(0.2)
    _key(VK_CONTROL)
    _key(VK_F)
    _key(VK_F, up=True)
    _key(VK_CONTROL, up=True)
    time.sleep(0.2)
    type_text("dog")
    time.sleep(0.15)
    _key(VK_RETURN)
    _key(VK_RETURN, up=True)
    print(f"sent dog hwnd={hwnd} title={title!r} rect=({rect.left},{rect.top},{rect.right},{rect.bottom})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
