"""Clipboard monitoring starts from the app launch boundary."""

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.clipboard_watcher import ClipboardWatcher


class _FakeClipboard:
    def __init__(self, image: QImage) -> None:
        self.current = image

    def image(self) -> QImage:
        return self.current


def _image(color: int) -> QImage:
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(color)
    return image


def test_startup_clipboard_image_is_ignored_but_new_image_is_detected():
    QApplication.instance() or QApplication([])
    detected = []
    before_launch = _image(0x112233)
    clipboard = _FakeClipboard(before_launch)
    watcher = ClipboardWatcher(on_image_detected=detected.append)
    watcher._clipboard = clipboard

    watcher.start()
    watcher._check_clipboard()
    assert detected == []

    clipboard.current = _image(0x445566)
    watcher._check_clipboard()
    assert len(detected) == 1
    watcher.stop()
