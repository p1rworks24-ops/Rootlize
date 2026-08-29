"""Optional image-content search bundle setup UI."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton

from app.semantic.catalog import model_id_for_key, normalize_model_key
from app.semantic.installer import (
    BundleInstaller,
    InstallProgress,
    LocalDirectorySource,
    configured_download_source,
    product_bundle_ui_state,
    start_product_bundle_warmup,
)


def _format_size(size: int) -> str:
    return f"{size / (1024 ** 3):.1f} GB" if size >= 1024 ** 3 else f"{size / (1024 ** 2):.0f} MB"


class _Signals(QObject):
    described = Signal(object, object)
    progress = Signal(object)
    finished = Signal(object)


class _WarmupRelay(QObject):
    finished = Signal()


class _DescribeTask(QRunnable):
    def __init__(self, installer):
        super().__init__(); self.installer = installer; self.signals = _Signals()
    def run(self):
        try: self.signals.described.emit(self.installer.describe(), None)
        except Exception as exc: self.signals.described.emit(None, exc)


class _InstallTask(QRunnable):
    def __init__(self, installer, cancel_event):
        super().__init__(); self.installer = installer; self.cancel_event = cancel_event; self.signals = _Signals()
    def run(self):
        try:
            bundle = self.installer.install(on_progress=self.signals.progress.emit, cancel_event=self.cancel_event)
            self.signals.finished.emit(bundle)
        except Exception as exc: self.signals.finished.emit(exc)


class ImageContentSearchSetup(QFrame):
    """Small opt-in affordance; normal text search remains available in every state."""

    installed = Signal()

    def __init__(self, parent=None, *, source=None, models_root=None, model_key=None):
        super().__init__(parent)
        self.setObjectName("imageContentSearchSetup")
        self._model_key = normalize_model_key(model_key)
        self._source = source if source is not None else configured_download_source(self._model_key)
        self._models_root = models_root
        self._pool = QThreadPool(self); self._pool.setMaxThreadCount(1)
        self._tasks = []
        self._cancel_event = None
        self._warmup_relay = None
        layout = QHBoxLayout(self); layout.setContentsMargins(8, 4, 8, 4); layout.setSpacing(8)
        self._label = QLabel("Find images by what they show.", self); layout.addWidget(self._label, 1)
        self._progress = QProgressBar(self); self._progress.setRange(0, 100); self._progress.hide(); layout.addWidget(self._progress)
        self._button = QPushButton("Set up", self); self._button.clicked.connect(self._begin); layout.addWidget(self._button)
        self._local = QPushButton("Install from folder…", self); self._local.clicked.connect(self._choose_local); layout.addWidget(self._local)
        self._cancel = QPushButton("Cancel", self); self._cancel.clicked.connect(self._cancel_download); self._cancel.hide(); layout.addWidget(self._cancel)
        self.refresh()

    def refresh(self):
        state = product_bundle_ui_state(self._model_key, root=self._models_root)
        if state == "ready":
            self.hide()
            return
        if state == "pending":
            self.hide()
            self._ensure_warmup()
            return
        self.show()
        if self._source is None:
            self._label.setText("Meaning search needs a one-time setup.")
            self._button.hide(); self._local.show()
        else:
            self._label.setText("Set up meaning search to find images by what they show.")
            self._button.show(); self._button.setEnabled(True); self._local.show()

    def _ensure_warmup(self):
        if self._warmup_relay is not None:
            return
        relay = _WarmupRelay(self)
        relay.finished.connect(self.refresh)
        self._warmup_relay = relay
        widget = self

        def on_done(_bundle, _error):
            try:
                from shiboken6 import isValid
            except Exception:
                isValid = lambda obj: obj is not None
            if not isValid(relay) or not isValid(widget):
                return
            try:
                relay.finished.emit()
            except RuntimeError:
                return

        start_product_bundle_warmup(
            self._model_key,
            root=self._models_root,
            on_done=on_done,
        )

    def set_model_key(self, model_key):
        self._model_key = normalize_model_key(model_key)
        self._source = configured_download_source(self._model_key)
        if self._warmup_relay is not None:
            try:
                self._warmup_relay.finished.disconnect(self.refresh)
            except RuntimeError:
                pass
            self._warmup_relay = None
        self.refresh()

    def _choose_local(self):
        directory = QFileDialog.getExistingDirectory(self, "Select verified Semantic model bundle")
        if not directory:
            return
        source = LocalDirectorySource(__import__("pathlib").Path(directory))
        try:
            manifest = source.manifest()
            if str(manifest.get("model_id")) != model_id_for_key(self._model_key):
                raise ValueError("Selected bundle is for a different model.")
        except Exception:
            QMessageBox.warning(self, "Invalid model bundle", "The selected folder is not a verified bundle for the active model.")
            return
        self._source = source
        self._begin()

    def _begin(self):
        installer = BundleInstaller(self._source, self._models_root)
        self._label.setText("Checking download details…"); self._button.setEnabled(False)
        task = _DescribeTask(installer); self._tasks.append(task)
        task.signals.described.connect(lambda result, error: self._described(installer, task, result, error))
        self._pool.start(task)

    def _described(self, installer, task, result, error):
        if task in self._tasks: self._tasks.remove(task)
        self._button.setEnabled(True)
        if error is not None:
            self._show_error(); return
        _manifest, total = result
        answer = QMessageBox.question(
            self, "Find images by their content",
            "Download files that let Rootlize find images by what they show. "
            f"Processing stays on this device. Approximate download: {_format_size(total)}.\n\nDownload now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            self._label.setText("Find images by what they show."); return
        self._cancel_event = threading.Event()
        self._button.hide(); self._local.hide(); self._cancel.show(); self._progress.show(); self._progress.setValue(0)
        self._label.setText("Downloading files for image-content search…")
        install_task = _InstallTask(installer, self._cancel_event); self._tasks.append(install_task)
        install_task.signals.progress.connect(self._on_progress)
        install_task.signals.finished.connect(lambda value: self._finished(install_task, value))
        self._pool.start(install_task)

    def _on_progress(self, progress: InstallProgress):
        if progress.total_bytes > 0:
            self._progress.setValue(min(100, int(progress.downloaded_bytes * 100 / progress.total_bytes)))

    def _cancel_download(self):
        if self._cancel_event is not None:
            self._cancel_event.set(); self._label.setText("Cancelling download…"); self._cancel.setEnabled(False)

    def _finished(self, task, value):
        if task in self._tasks: self._tasks.remove(task)
        self._cancel_event = None; self._cancel.setEnabled(True); self._cancel.hide(); self._progress.hide()
        if isinstance(value, BaseException):
            self._button.show(); self._local.show(); self._button.setText("Retry"); self._show_error(); return
        self._label.setText("Search by image content is ready.")
        self._local.hide()
        self.installed.emit()

    def _show_error(self):
        self._label.setText("The download could not be completed. Text search is still available.")
        if self._source is not None: self._button.show()
        self._local.show(); self._button.setText("Retry"); self._button.setEnabled(True)
        QMessageBox.warning(self, "Download failed", "The files could not be downloaded or verified. Check your connection and try again.")
