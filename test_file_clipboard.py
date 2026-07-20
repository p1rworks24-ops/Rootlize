"""System clipboard file URLs for Explorer paste-out."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

from app.utils.file_clipboard import (
    paths_from_system_clipboard,
    set_files_on_clipboard,
    system_clipboard_is_cut,
)


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_png(path: Path) -> None:
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def test_set_files_on_clipboard_exposes_urls_for_external_paste():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shot.png"
        _write_png(path)
        set_files_on_clipboard([path], cut=False)
        mime = QGuiApplication.clipboard().mimeData()
        assert mime is not None
        assert mime.hasUrls()
        urls = [QUrl(u) for u in mime.urls()]
        assert any(Path(u.toLocalFile()).resolve() == path.resolve() for u in urls)
        assert system_clipboard_is_cut() is False
        assert paths_from_system_clipboard()[0].resolve() == path.resolve()
    _ = app


def test_set_files_on_clipboard_cut_marks_move_drop_effect():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cut_me.png"
        _write_png(path)
        set_files_on_clipboard([path], cut=True)
        assert system_clipboard_is_cut() is True
    _ = app
