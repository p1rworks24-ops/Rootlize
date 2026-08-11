"""User-facing analysis flow on the Images page."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.i18n import set_locale
from app.ocr.job_models import OCRIndexProgress
from app.ocr.models import OCRDiffItem, OCRDiffResult
from app.ui.images_analysis import ImagesAnalysisBar


class FakeAnalysisController(QObject):
    preview_finished = Signal(object, object)

    def __init__(self, *, usable=True):
        super().__init__()
        self.usable = usable
        self.previewed = []
        self.started = []
        self.progress = None

    def environment_status(self):
        return {"usable": self.usable}

    def preview(self, folder):
        self.previewed.append(folder)
        return True

    def start(self, folder):
        self.started.append(folder)
        self.progress = OCRIndexProgress(
            state="running", folder_path=str(folder), total_requires_ocr=2, pending=2
        )
        return "run"

    def status(self):
        return self.progress

    def is_running(self):
        return bool(self.progress and self.progress.state == "running")


def _app():
    return QApplication.instance() or QApplication([])


def _preview(folder: Path, count: int) -> OCRDiffResult:
    items = tuple(
        OCRDiffItem(
            image_id=None,
            old_path=None,
            new_path=str(folder / f"{index}.png"),
            classification="new",
            reason="New image",
            requires_ocr=True,
            previous_status=None,
            next_status="pending",
            size_bytes=1,
            mtime_ns=1,
        )
        for index in range(count)
    )
    return OCRDiffResult(str(folder), "start", "end", count, items)


def test_pending_images_can_be_analyzed_and_progress_becomes_searchable(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller)
    assert bar._analyze_btn.objectName() == "secondaryButton"
    assert not bar._analyze_btn.icon().isNull()
    completed = []
    summaries = []
    bar.analysis_completed.connect(lambda: completed.append(True))
    bar.analysis_summary_changed.connect(summaries.append)

    bar.set_folder(tmp_path)
    assert controller.previewed == [tmp_path.resolve()]
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    assert bar._analyze_btn.isEnabled()
    assert bar._status_label.text() == "0 analyzed · 2 not analyzed · 2 total"
    assert summaries[-1]["pending_names"] == {"0.png", "1.png"}
    assert "OCR" not in bar._status_label.text()

    bar._analyze_btn.click()
    assert controller.started == [tmp_path.resolve()]
    bar.refresh_status()
    assert bar._progress.isVisibleTo(bar)
    assert "0 of 2" in bar._status_label.text()
    assert "Calculating time" in bar._status_label.text()

    controller.progress = replace(
        controller.progress,
        completed=1,
        pending=1,
        estimated_remaining_seconds=75,
    )
    bar.refresh_status()
    assert "1 of 2" in bar._status_label.text()
    assert "About 1 min remaining" in bar._status_label.text()

    controller.progress = replace(
        controller.progress,
        state="completed",
        completed=2,
        succeeded=2,
        pending=0,
    )
    bar.refresh_status()
    assert bar._status_label.text() == "2 analyzed · 0 not analyzed · 2 total"
    assert completed == [True]


def test_zero_targets_is_searchable_without_starting_worker(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 0), None)

    assert not bar._analyze_btn.isEnabled()
    assert controller.started == []
    assert bar._status_label.text() == "0 analyzed · 0 not analyzed · 0 total"


def test_unavailable_and_failed_states_remain_safe_and_retryable(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController(usable=False)
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 1), None)
    assert not bar._analyze_btn.isEnabled()
    assert bar._status_label.text() == "0 analyzed · 1 not analyzed · 1 total"
    assert "not available" in bar._analyze_btn.toolTip()

    controller.preview_finished.emit(None, RuntimeError("private details"))
    assert bar._analyze_btn.isEnabled()
    assert "private details" not in bar._status_label.text()
