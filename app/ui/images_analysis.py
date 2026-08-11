"""Small user-facing analysis control for the Images page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, QSize, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton

from app.i18n import t
from app.ui.icons import icon_analyze

ACTIVE_STATES = {
    "preparing", "scanning", "initializing_worker", "running",
    "pausing", "paused", "cancelling", "closing",
}


class ImagesAnalysisBar(QFrame):
    """Expose only analysis readiness and progress; diagnostics stay in Settings."""

    analysis_completed = Signal()
    analysis_summary_changed = Signal(object)
    analysis_progress_changed = Signal(object)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("imagesAnalysisBar")
        self._controller = controller
        self._folder: Path | None = None
        self._preview = None
        self._preview_running = False
        self._start_after_preview = False
        self._last_state = "idle"
        self._summary_total = 0
        self._summary_analyzed = 0
        self._summary_pending = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        self._status_label = QLabel(t("images.analysis.checking"), self)
        self._status_label.setObjectName("mutedLabel")
        layout.addWidget(self._status_label, 1)
        self._progress = QProgressBar(self)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(100)
        self._progress.hide()
        layout.addWidget(self._progress)
        self._analyze_btn = QPushButton(t("images.analysis.action"), self)
        self._analyze_btn.setObjectName("secondaryButton")
        self._analyze_btn.setIcon(icon_analyze())
        self._analyze_btn.setIconSize(QSize(16, 16))
        self._analyze_btn.clicked.connect(self._start_analysis)
        layout.addWidget(self._analyze_btn)

        controller.preview_finished.connect(self._on_preview_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start()

    def set_folder(self, folder: Path | None, *, force: bool = False) -> None:
        resolved = folder.resolve() if folder and folder.exists() else None
        if not force and resolved == self._folder and self._preview is not None:
            return
        self._folder = resolved
        self._preview = None
        self._start_after_preview = False
        if self._folder is None:
            self._status_label.setText(t("images.analysis.no_folder"))
            self._analyze_btn.setEnabled(False)
            self._progress.hide()
            return
        self._request_preview()

    def _request_preview(self) -> None:
        if self._folder is None or self._preview_running or self._controller.is_running():
            return
        self._preview_running = bool(self._controller.preview(self._folder))
        if self._preview_running:
            self._status_label.setText(t("images.analysis.checking"))
            self._analyze_btn.setEnabled(False)

    def _on_preview_finished(self, result, error) -> None:
        self._preview_running = False
        if result is not None and self._folder is not None:
            if Path(result.folder_path).resolve() != self._folder:
                return
        if error is not None or result is None:
            self._preview = None
            self._status_label.setText(t("images.analysis.check_failed"))
            self._analyze_btn.setEnabled(True)
            self._start_after_preview = False
            return
        self._preview = result
        count = result.reindex_required_count
        pending_names = {
            Path(item.new_path).name
            for item in result.items
            if item.requires_ocr and item.new_path
        }
        analyzed = max(0, result.total_files - len(pending_names))
        self._summary_total = result.total_files
        self._summary_analyzed = analyzed
        self._summary_pending = len(pending_names)
        self.analysis_summary_changed.emit(
            {
                "total": result.total_files,
                "analyzed": analyzed,
                "pending": len(pending_names),
                "pending_names": pending_names,
            }
        )
        if count:
            self._status_label.setText(t(
                "images.analysis.summary",
                total=result.total_files,
                analyzed=analyzed,
                pending=len(pending_names),
            ))
            usable = bool(self._controller.environment_status()["usable"])
            self._analyze_btn.setText(t("images.analysis.action"))
            self._analyze_btn.setEnabled(usable)
            if not usable:
                self._analyze_btn.setToolTip(t("images.analysis.unavailable"))
        else:
            self._status_label.setText(t(
                "images.analysis.summary",
                total=result.total_files,
                analyzed=analyzed,
                pending=0,
            ))
            self._analyze_btn.setEnabled(False)
        if self._start_after_preview:
            self._start_after_preview = False
            self._begin_if_needed()

    def _start_analysis(self) -> None:
        if self._preview is None:
            self._start_after_preview = True
            self._request_preview()
            return
        self._begin_if_needed()

    def start_analysis(self) -> None:
        """Public entry point shared by Images and the Home dashboard."""
        self._start_analysis()

    def _begin_if_needed(self) -> None:
        if self._folder is None or not self._preview:
            return
        if self._preview.reindex_required_count <= 0:
            self._show_summary()
            return
        try:
            self._controller.start(self._folder)
        except Exception:
            self._status_label.setText(t("images.analysis.start_failed"))
            self._analyze_btn.setEnabled(True)
            return
        self.refresh_status()

    def refresh_status(self) -> None:
        status = self._controller.status()
        if status is None:
            return
        self.analysis_progress_changed.emit(status)
        state = status.state
        active = state in ACTIVE_STATES or self._controller.is_running()
        if active:
            maximum = max(1, status.total_requires_ocr)
            self._progress.setRange(0, maximum)
            self._progress.setValue(min(status.completed, maximum))
            self._progress.show()
            estimate = status.estimated_remaining_seconds
            remaining = t("images.analysis.estimate_calculating")
            if estimate is not None:
                seconds = max(0, int(round(estimate)))
                remaining = (
                    t("images.analysis.estimate_minutes", count=max(1, round(seconds / 60)))
                    if seconds >= 60
                    else t("images.analysis.estimate_seconds", count=seconds)
                )
            self._status_label.setText(t(
                "images.analysis.progress_with_estimate",
                analyzed=min(
                    self._summary_total,
                    self._summary_analyzed + status.completed,
                ),
                pending=max(0, self._summary_pending - status.completed),
                all_count=self._summary_total,
                completed=status.completed,
                total=status.total_requires_ocr,
                remaining=remaining,
            ))
            self._analyze_btn.setText(t("images.analysis.running"))
            self._analyze_btn.setEnabled(False)
        elif state == "completed":
            self._progress.hide()
            if status.failed:
                self._summary_analyzed = min(
                    self._summary_total,
                    self._summary_analyzed + status.succeeded,
                )
                self._summary_pending = max(
                    0, self._summary_total - self._summary_analyzed
                )
                self._show_summary()
                self._status_label.setToolTip(t(
                    "images.analysis.completed_with_failures",
                    succeeded=status.succeeded,
                    failed=status.failed,
                ))
                self._analyze_btn.setEnabled(True)
            else:
                self._summary_analyzed = self._summary_total
                self._summary_pending = 0
                self._show_summary()
                self._analyze_btn.setEnabled(False)
            self._analyze_btn.setText(t("images.analysis.action"))
            if self._last_state in ACTIVE_STATES:
                self._preview = None
                self.analysis_completed.emit()
        elif state in {"failed", "cancelled"}:
            self._progress.hide()
            self._status_label.setText(t("images.analysis.failed"))
            self._analyze_btn.setText(t("images.analysis.action"))
            self._analyze_btn.setEnabled(True)
        self._last_state = state

    def _show_summary(self) -> None:
        self._status_label.setText(t(
            "images.analysis.summary",
            total=self._summary_total,
            analyzed=self._summary_analyzed,
            pending=self._summary_pending,
        ))

    def stop_polling(self) -> None:
        self._timer.stop()
