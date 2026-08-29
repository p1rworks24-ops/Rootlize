"""User-facing analysis flow on the Images page."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.i18n import set_locale
from app.ocr.job_models import OCRIndexProgress
from app.ocr.models import OCRDiffItem, OCRDiffResult
from app.ui.images_analysis import (
    ImagesAnalysisBar,
    aggregate_analysis_states,
    has_auto_start_work,
    has_semantic_auto_start_work,
    library_prep_text,
    needs_analysis_retry,
    resolve_library_prep_state,
    unresolved_analysis_paths,
)


def test_analysis_state_aggregation_keeps_semantic_and_ocr_independent():
    counts = aggregate_analysis_states({
        "ready.png": {"ocr_status": "ready", "semantic_status": "unchanged"},
        "ocr.png": {"ocr_status": "missing", "semantic_status": "unchanged"},
        "semantic.png": {"ocr_status": "ready", "semantic_status": "stale_model"},
        "running.png": {"ocr_status": "running", "semantic_status": "missing_embedding"},
        "failed.png": {"ocr_status": "ready", "semantic_status": "failed"},
    }, 5)
    assert counts == {
        "total": 5,
        "semantic_ready": 2, "semantic_pending": 2, "semantic_failed": 1,
        "ocr_ready": 3, "ocr_pending": 2, "ocr_failed": 0,
        "processing": 1,
    }


def test_analysis_summary_covers_success_and_failure_matrix():
    counts = aggregate_analysis_states({
        "both-ready": {"semantic_status": "unchanged", "ocr_status": "ready"},
        "semantic-ready-ocr-failed": {"semantic_status": "unchanged", "ocr_status": "failed"},
        "semantic-failed-ocr-ready": {"semantic_status": "failed", "ocr_status": "ready"},
        "both-failed": {"semantic_status": "failed", "ocr_status": "failed"},
    }, 4)
    assert counts["semantic_ready"] == 2
    assert counts["semantic_failed"] == 2
    assert counts["ocr_ready"] == 2
    assert counts["ocr_failed"] == 2


class FakeAnalysisController(QObject):
    preview_finished = Signal(object, object)

    def __init__(self, *, usable=True):
        super().__init__()
        self.usable = usable
        self.previewed = []
        self.started = []
        self.progress = None
        self.semantic_pending = set()
        self.semantic_started = []
        self.details = {}
        self.retried = []
        self.cancelled = []
        self.bundle_available = True

    def semantic_available(self):
        return bool(self.bundle_available)

    def cancel(self):
        self.cancelled.append(
            getattr(self.progress, "folder_path", None) if self.progress else None
        )
        if self.progress is not None:
            self.progress = replace(self.progress, state="cancelled")

    def environment_status(self):
        return {"usable": self.usable}

    def preview(self, folder):
        self.previewed.append(folder)
        return True

    def start(self, folder):
        if getattr(self, "start_error", None):
            raise self.start_error
        self.started.append(folder)
        self.progress = OCRIndexProgress(
            state="running", folder_path=str(folder), total_requires_ocr=2, pending=2
        )
        return "run"

    def status(self):
        return self.progress

    def is_running(self):
        return bool(self.progress and self.progress.state == "running")

    def semantic_pending_names(self, _folder):
        return set(self.semantic_pending)

    def start_semantic(self, folder):
        self.semantic_started.append(folder)
        self.progress = OCRIndexProgress(
            state="running", folder_path=str(folder),
            total_requires_ocr=len(self.semantic_pending),
            pending=len(self.semantic_pending),
        )
        return bool(self.semantic_pending)

    def analysis_details(self, _folder):
        return dict(self.details)

    def retry_analysis_paths(self, paths):
        self.retried.append(tuple(Path(path) for path in paths))
        self.progress = OCRIndexProgress(
            state="running", folder_path=str(paths[0].parent),
            total_requires_ocr=len(self.retried[-1]),
            pending=len(self.retried[-1]),
        )
        return True


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
    assert bar._status_label.text() == "Meaning ready 0 · Text ready 0 · Total 2"
    assert summaries[-1]["pending_names"] == {"0.png", "1.png"}

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
    assert "Total 2" in bar._status_label.text()
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
    assert bar._status_label.text() == "Meaning ready 0 · Text ready 0 · Total 0"


def test_semantic_missing_image_is_not_reported_analyzed_and_runs_without_ocr(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    controller.semantic_pending = {"semantic-only.png"}
    bar = ImagesAnalysisBar(controller)
    preview = OCRDiffResult(
        str(tmp_path), "start", "end", 1,
        (OCRDiffItem(
            image_id=1, old_path=str(tmp_path / "semantic-only.png"),
            new_path=str(tmp_path / "semantic-only.png"), classification="unchanged",
            reason="unchanged", requires_ocr=False, previous_status="ready",
            next_status=None, size_bytes=1, mtime_ns=1,
        ),),
    )
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(preview, None)

    assert "Meaning ready 0" in bar._status_label.text()
    assert "Total 1" in bar._status_label.text()
    bar._analyze_btn.click()
    assert controller.started == []
    assert controller.semantic_started == [tmp_path.resolve()]


def test_unavailable_and_failed_states_remain_safe_and_retryable(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController(usable=False)
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 1), None)
    assert not bar._analyze_btn.isEnabled()
    assert bar._status_label.text() == "Meaning ready 0 · Text ready 0 · Total 1"
    assert "not available" in bar._analyze_btn.toolTip()

    controller.preview_finished.emit(None, RuntimeError("private details"))
    assert bar._analyze_btn.isEnabled()
    assert "private details" not in bar._status_label.text()


def test_completed_summary_uses_current_semantic_embedding_count(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    controller.semantic_pending = {"missing.png"}
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    controller.progress = OCRIndexProgress(
        state="completed", folder_path=str(tmp_path), completed=2,
        succeeded=2, failed=0, total_requires_ocr=2,
    )
    bar._last_state = "idle"

    bar.refresh_status()

    assert bar._summary_analyzed == 1
    assert bar._summary_pending == 1
    assert bar._analyze_btn.isEnabled()


def _diff_item(folder: Path, name: str, **overrides) -> OCRDiffItem:
    path = str(folder / name)
    values = dict(
        image_id=1,
        old_path=path,
        new_path=path,
        classification="unchanged",
        reason="test",
        requires_ocr=True,
        previous_status="pending",
        next_status="pending",
        size_bytes=1,
        mtime_ns=1,
    )
    values.update(overrides)
    return OCRDiffItem(**values)


def test_auto_start_work_ignores_failed_only_leftovers(tmp_path):
    failed = OCRDiffResult(
        str(tmp_path), "start", "end", 1,
        (_diff_item(tmp_path, "failed.png", previous_status="failed"),),
    )
    added = OCRDiffResult(
        str(tmp_path), "start", "end", 1,
        (_diff_item(
            tmp_path, "new.png", classification="new", image_id=None,
            old_path=None, previous_status=None, next_status="pending",
        ),),
    )
    assert not has_auto_start_work(failed, {
        "failed.png": {"ocr_status": "failed", "semantic_status": "failed"},
    })
    assert has_auto_start_work(added, {})
    assert has_semantic_auto_start_work({
        "shot.png": {"ocr_status": "ready", "semantic_status": "missing_embedding"},
    })
    assert not has_semantic_auto_start_work({
        "failed.png": {"ocr_status": "ready", "semantic_status": "failed"},
    })
    assert needs_analysis_retry(
        OCRIndexProgress(state="cancelled"), {}, {}
    )
    assert unresolved_analysis_paths({
        "ready.png": {
            "path": str(tmp_path / "ready.png"),
            "ocr_status": "ready",
            "semantic_status": "unchanged",
        },
        "failed.png": {
            "path": str(tmp_path / "failed.png"),
            "ocr_status": "failed",
            "semantic_status": "unchanged",
        },
    }) == [tmp_path / "failed.png"]


def test_same_folder_skips_preview_until_forced(tmp_path):
    _app()
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 0), None)
    bar.set_folder(tmp_path)
    assert controller.previewed == [tmp_path.resolve()]
    bar.set_folder(tmp_path, force=True)
    assert controller.previewed == [tmp_path.resolve(), tmp_path.resolve()]


def test_force_during_preview_rescans_instead_of_keeping_stale_result(tmp_path):
    _app()
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    assert bar._preview_running
    bar.set_folder(tmp_path, force=True)
    controller.preview_finished.emit(_preview(tmp_path, 1), None)
    assert controller.previewed == [tmp_path.resolve(), tmp_path.resolve()]


def test_auto_start_runs_for_new_images_without_analyze_button(tmp_path):
    _app()
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller, auto_start=True)
    assert bar._analyze_btn.isHidden()
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    assert controller.started == [tmp_path.resolve()]


def test_auto_start_unavailable_environment_starts_semantic_without_banner(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController(usable=False)
    retry_signals = []
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.retry_needed_changed.connect(retry_signals.append)
    controller.semantic_pending = {"0.png", "1.png"}
    controller.details = {
        "0.png": {
            "path": str(tmp_path / "0.png"),
            "ocr_status": "pending",
            "semantic_status": "missing_embedding",
        },
        "1.png": {
            "path": str(tmp_path / "1.png"),
            "ocr_status": "pending",
            "semantic_status": "missing_embedding",
        },
    }
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    assert controller.started == []
    assert controller.semantic_started == [tmp_path.resolve()]
    assert bar._analyze_btn.isHidden()
    assert True not in retry_signals


def test_auto_start_start_failure_retries_in_background(tmp_path, monkeypatch):
    from PySide6.QtTest import QTest

    _app()
    set_locale("en")
    monkeypatch.setattr("app.ui.images_analysis.AUTO_RETRY_DELAYS_MS", (1, 1))
    controller = FakeAnalysisController()
    controller.start_error = RuntimeError("OCR environment unavailable")
    retry_signals = []
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.retry_needed_changed.connect(retry_signals.append)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    assert controller.started == []
    assert True not in retry_signals
    assert bar._auto_retry_attempt >= 1
    QTest.qWait(40)
    assert True not in retry_signals


def test_failed_analysis_retries_in_background_without_banner(tmp_path, monkeypatch):
    from PySide6.QtTest import QTest

    _app()
    set_locale("en")
    monkeypatch.setattr("app.ui.images_analysis.AUTO_RETRY_DELAYS_MS", (1, 1))
    controller = FakeAnalysisController()
    retry_signals = []
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.retry_needed_changed.connect(retry_signals.append)
    failed = OCRDiffResult(
        str(tmp_path), "start", "end", 1,
        (_diff_item(tmp_path, "shot.png", previous_status="failed"),),
    )
    controller.details = {
        "shot.png": {
            "path": str(tmp_path / "shot.png"),
            "ocr_status": "failed",
            "semantic_status": "unchanged",
        }
    }
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(failed, None)
    assert controller.started == []
    assert True not in retry_signals
    QTest.qWait(40)
    assert controller.retried == [(tmp_path / "shot.png",)]
    assert controller.started == []


def test_failed_ocr_run_still_starts_semantic_followup(tmp_path):
    _app()
    controller = FakeAnalysisController()
    controller.semantic_pending = {"shot.png"}
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(_preview(tmp_path, 1), None)
    controller.progress = OCRIndexProgress(state="failed", failed=1)
    bar._last_state = "running"
    bar.refresh_status()
    assert controller.semantic_started[-1] == tmp_path.resolve()


def test_filesystem_sync_forces_analysis_preview(tmp_path):
    from app.services.metadata_service import MetadataService
    from app.ui.pages.images_page import FS_WATCH_DEBOUNCE_MS, ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache

    app = _app()
    set_locale("en")
    folder = tmp_path / "Library"
    folder.mkdir()
    controller = FakeAnalysisController()
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        analysis_controller=controller,
    )
    page.show()
    app.processEvents()
    page.refresh()
    assert controller.previewed
    controller.preview_finished.emit(_preview(folder, 0), None)
    count = len(controller.previewed)
    page._sync_from_filesystem()
    assert len(controller.previewed) == count + 1
    controller.preview_finished.emit(_preview(folder, 0), None)
    assert page._analysis_bar.isHidden()
    assert not hasattr(page, "_analysis_retry_bar")

    page._fs_signature = page._folder_signature()
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(1)
    added = folder / "added-while-open.png"
    assert image.save(str(added), "PNG")
    preview_count = len(controller.previewed)
    page._poll_folder_signature()
    QTest.qWait(FS_WATCH_DEBOUNCE_MS + 80)
    app.processEvents()
    assert len(controller.previewed) == preview_count + 1
    page.close()


def test_library_prep_states_are_user_facing_and_hide_without_bundle():
    set_locale("en")
    assert resolve_library_prep_state(
        folder=None, bundle_available=True, checking=False,
        running=False, semantic_ready=0, total=10,
    ) == "hidden"
    assert resolve_library_prep_state(
        folder=Path("x"), bundle_available=False, checking=False,
        running=False, semantic_ready=0, total=10,
    ) == "hidden"
    assert resolve_library_prep_state(
        folder=Path("x"), bundle_available=True, checking=True,
        running=False, semantic_ready=0, total=10,
    ) == "checking"
    assert resolve_library_prep_state(
        folder=Path("x"), bundle_available=True, checking=False,
        running=True, semantic_ready=2, total=10,
    ) == "preparing"
    assert resolve_library_prep_state(
        folder=Path("x"), bundle_available=True, checking=False,
        running=False, semantic_ready=4, total=10,
    ) == "preparing"
    assert resolve_library_prep_state(
        folder=Path("x"), bundle_available=True, checking=False,
        running=False, semantic_ready=10, total=10,
    ) == "ready"
    assert "Preparing your images" in library_prep_text("preparing", ready=243, total=836)
    assert "243" in library_prep_text("preparing", ready=243, total=836)
    assert "836" in library_prep_text("preparing", ready=243, total=836)
    assert "Reading text from images" in library_prep_text(
        "preparing", ready=38, total=50, activity="Reading text from images"
    )
    assert "OCR" not in library_prep_text(
        "preparing", ready=38, total=50, activity="Reading text from images"
    )
    assert "Ready" in library_prep_text("ready", ready=836, total=836)


def test_auto_start_publishes_preparing_then_ready(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    snapshots = []
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.library_prep_changed.connect(snapshots.append)
    bar.set_folder(tmp_path)
    assert snapshots[-1]["state"] == "checking"
    controller.details = {
        "0.png": {"ocr_status": "pending", "semantic_status": "missing_embedding"},
        "1.png": {"ocr_status": "pending", "semantic_status": "missing_embedding"},
    }
    controller.preview_finished.emit(_preview(tmp_path, 2), None)
    assert controller.started == [tmp_path.resolve()]
    assert snapshots[-1]["state"] == "preparing"
    assert snapshots[-1]["total"] == 2
    controller.progress = replace(
        controller.progress, state="completed", completed=2, succeeded=2, pending=0,
    )
    controller.semantic_pending = set()
    bar.refresh_status()
    assert snapshots[-1]["state"] == "ready"


def test_ready_images_are_not_reanalyzed(tmp_path):
    _app()
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller, auto_start=True)
    preview = OCRDiffResult(
        str(tmp_path), "start", "end", 2,
        (
            _diff_item(
                tmp_path, "a.png", classification="unchanged",
                requires_ocr=False, previous_status="ready", next_status=None,
            ),
            _diff_item(
                tmp_path, "b.png", classification="unchanged",
                requires_ocr=False, previous_status="ready", next_status=None,
            ),
        ),
    )
    controller.details = {
        "a.png": {"ocr_status": "ready", "semantic_status": "unchanged"},
        "b.png": {"ocr_status": "ready", "semantic_status": "unchanged"},
    }
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(preview, None)
    assert controller.started == []
    assert controller.semantic_started == []


def test_only_new_images_start_differential_analysis(tmp_path):
    _app()
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller, auto_start=True)
    preview = OCRDiffResult(
        str(tmp_path), "start", "end", 2,
        (
            _diff_item(
                tmp_path, "ready.png", classification="unchanged",
                requires_ocr=False, previous_status="ready", next_status=None,
            ),
            _diff_item(
                tmp_path, "new.png", classification="new", image_id=None,
                old_path=None, previous_status=None, next_status="pending",
            ),
        ),
    )
    controller.details = {
        "ready.png": {"ocr_status": "ready", "semantic_status": "unchanged"},
        "new.png": {"ocr_status": "pending", "semantic_status": "missing_embedding"},
    }
    bar.set_folder(tmp_path)
    controller.preview_finished.emit(preview, None)
    assert controller.started == [tmp_path.resolve()]


def test_folder_switch_cancels_previous_and_ignores_stale_progress(tmp_path):
    _app()
    set_locale("en")
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    controller = FakeAnalysisController()
    snapshots = []
    bar = ImagesAnalysisBar(controller, auto_start=True)
    bar.library_prep_changed.connect(snapshots.append)
    bar.set_folder(folder_a)
    controller.preview_finished.emit(_preview(folder_a, 2), None)
    assert controller.started == [folder_a.resolve()]
    bar.set_folder(folder_b)
    assert controller.cancelled
    assert snapshots[-1]["folder"] == str(folder_b.resolve())
    assert snapshots[-1]["state"] == "checking"
    controller.progress = OCRIndexProgress(
        state="running",
        folder_path=str(folder_a.resolve()),
        completed=2,
        total_requires_ocr=2,
    )
    bar.refresh_status()
    assert snapshots[-1]["folder"] == str(folder_b.resolve())
    assert snapshots[-1]["state"] == "checking"
    assert "2 / 2" not in snapshots[-1]["text"]


def test_hidden_analysis_bar_still_drives_compact_prep_label(tmp_path):
    from app.services.metadata_service import MetadataService
    from app.ui.pages.images_page import ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache

    app = _app()
    set_locale("en")
    folder = tmp_path / "Library"
    folder.mkdir()
    controller = FakeAnalysisController()
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        analysis_controller=controller,
    )
    page.show()
    app.processEvents()
    assert page._analysis_bar.isHidden()
    page._analysis_bar.set_folder(folder)
    controller.details = {
        "0.png": {"ocr_status": "pending", "semantic_status": "missing_embedding"},
    }
    controller.preview_finished.emit(_preview(folder, 1), None)
    app.processEvents()
    assert page._library_prep_label.isVisible()
    assert "Preparing your images" in page._library_prep_label.text()
    assert "Analyze" not in page._library_prep_label.text()
    assert "embedding" not in page._library_prep_label.text().lower()
    assert "ocr" not in page._library_prep_label.text().lower()
    assert page._library_prep_label.toolTip()
    page.close()


def test_tour_local_snapshot_idle_ocr_failures_are_not_needed(tmp_path):
    _app()
    set_locale("en")
    controller = FakeAnalysisController()
    bar = ImagesAnalysisBar(controller)
    bar.set_folder(tmp_path)
    controller.details = {
        f"{index}.png": {
            "ocr_status": "ready" if index < 167 else "failed",
            "semantic_status": "unchanged",
        }
        for index in range(174)
    }
    preview = OCRDiffResult(str(tmp_path), "start", "end", 174, ())
    controller.preview_finished.emit(preview, None)
    snapshot = bar.tour_local_snapshot()
    assert snapshot["ready"] == 167
    assert snapshot["total"] == 174
    assert snapshot["failed"] == 7
    assert snapshot["running"] is False
    assert snapshot["needed"] == 0
    assert snapshot["error"] is False
