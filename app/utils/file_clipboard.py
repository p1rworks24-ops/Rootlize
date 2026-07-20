"""System clipboard helpers for Explorer-style file Copy / Cut / Paste."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication

# Windows CFSTR_PREFERREDDROPEFFECT values
_DROP_EFFECT_COPY = 1
_DROP_EFFECT_MOVE = 2

# Qt maps CFSTR_PREFERREDDROPEFFECT to this MIME type on Windows
_PREFERRED_DROP_EFFECT_MIME = (
    'application/x-qt-windows-mime;value="Preferred DropEffect"'
)


def set_files_on_clipboard(paths: list[Path], *, cut: bool = False) -> None:
    """Publish local files so Explorer (and other apps) can Paste them."""
    urls: list[QUrl] = []
    for path in paths:
        if not path.exists():
            continue
        urls.append(QUrl.fromLocalFile(str(path.resolve())))
    if not urls:
        return

    mime = QMimeData()
    mime.setUrls(urls)
    local_paths = [u.toLocalFile() for u in urls]
    mime.setText("\n".join(local_paths))
    # Explicit uri-list helps some Windows shell consumers
    uri_list = "\r\n".join(u.toString(QUrl.FullyEncoded) for u in urls) + "\r\n"
    mime.setData("text/uri-list", QByteArray(uri_list.encode("utf-8")))
    effect = _DROP_EFFECT_MOVE if cut else _DROP_EFFECT_COPY
    mime.setData(
        _PREFERRED_DROP_EFFECT_MIME,
        QByteArray(struct.pack("<I", effect)),
    )
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setMimeData(mime)


def clear_system_file_clipboard() -> None:
    """Clear the system clipboard after a successful Cut-paste inside the app."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.clear()


def paths_from_system_clipboard(*, png_only: bool = True) -> list[Path]:
    """Read local file paths from the system clipboard (Explorer or this app)."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return []
    mime = clipboard.mimeData()
    if mime is None or not mime.hasUrls():
        return []
    paths: list[Path] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if png_only and path.suffix.lower() != ".png":
            continue
        if path.exists() and path.is_file():
            paths.append(path)
    return paths


def system_clipboard_is_cut() -> bool:
    """True when Windows Preferred DropEffect indicates Move (Cut)."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False
    mime = clipboard.mimeData()
    if mime is None or not mime.hasFormat(_PREFERRED_DROP_EFFECT_MIME):
        return False
    raw = bytes(mime.data(_PREFERRED_DROP_EFFECT_MIME))
    if len(raw) < 4:
        return False
    effect = struct.unpack("<I", raw[:4])[0]
    return effect == _DROP_EFFECT_MOVE
