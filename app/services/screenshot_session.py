"""Screenshot session: window minimized while a capture mode runs."""

from PySide6.QtCore import QObject, QTimer, Signal

from app.services.capture_modes import CAPTURE_REGION


class ScreenshotSession(QObject):
    """
    Tracks an in-progress capture after the main window is minimized.

    Capture mode only affects how the image is obtained; save / tags /
    metadata always go through ImageSaver + MetadataService.
    """

    finished = Signal()

    def __init__(self, timeout_ms: int = 60000, parent=None):
        super().__init__(parent)
        self._timeout_ms = timeout_ms
        self._active = False
        self._mode = CAPTURE_REGION
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def mode(self) -> str:
        return self._mode

    def start(self, mode: str = CAPTURE_REGION) -> None:
        """Begin the session (call after MainWindow.showMinimized())."""
        self._mode = mode or CAPTURE_REGION
        self._active = True
        self._timer.start(self._timeout_ms)

    def complete(self) -> None:
        """End the session early (e.g. after an image was saved)."""
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self.finished.emit()

    def cancel(self) -> None:
        """Cancel without emitting finished (e.g. app closing)."""
        self._active = False
        self._timer.stop()

    def _on_timeout(self) -> None:
        if self._active:
            self._active = False
            self.finished.emit()
