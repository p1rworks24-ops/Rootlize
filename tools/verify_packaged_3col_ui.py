"""Interact with a running packaged Capixe window and grab shots."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_packaged_exe_ui import find_windows, grab
from tools.verify_packaged_meaning_search import click, foreground, type_text, _key, VK_CONTROL, VK_F, VK_RETURN

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


def main() -> int:
    pid = int(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    windows = find_windows(pid)
    if not windows:
        print("no window")
        return 1
    hwnd, title = windows[0]
    print(f"window title={title!r} hwnd={hwnd}")
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 40, 40, 1600, 900, SWP_SHOWWINDOW)
    foreground(hwnd)
    time.sleep(0.8)

    # First image card in the center grid.
    click(430, 390)
    time.sleep(0.6)
    print("preview", grab(hwnd, out / "exe-image-preview.png"))

    # Ask AI button at the bottom of the right panel.
    click(1480, 900)
    time.sleep(0.6)
    print("ask-ai", grab(hwnd, out / "exe-ask-ai.png"))

    # Preview back button in the AI header.
    click(1520, 150)
    time.sleep(0.5)
    print("back-preview", grab(hwnd, out / "exe-back-preview.png"))

    click(520, 120)
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
    print("sent meaning dog")
    time.sleep(22)
    print("meaning-dog", grab(hwnd, out / "exe-meaning-dog.png"))

    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 40, 40, 1600, 900, SWP_SHOWWINDOW)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
