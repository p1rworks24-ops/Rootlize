from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ocr.job_models import OCRIndexProgress
from app.ocr.models import OCRDiffItem, OCRDiffResult, SearchResult
from app.ui.ocr_test_panel import OCRTestPanel
from app.ui.ocr_test_controller import OCRTestController
from app.paths import get_local_app_data_dir
from app.ocr.database import DB_FILE_NAME


class FakeOCRController(QObject):
    preview_finished = Signal(object, object)

    def __init__(self, *, usable=True):
        super().__init__()
        self.usable = usable
        self.progress = None
        self.actions = []
        self.search_results = []
        self.search_queries = []
        self.db_status = "not_opened"

    def environment_status(self):
        return {"runtime": "available" if self.usable else "not_configured", "models": "ready" if self.usable else "not_configured", "worker": "stopped", "database": self.db_status, "usable": self.usable}

    def preview(self, folder):
        self.actions.append(("preview", folder))
        return True

    def start(self, folder):
        self.actions.append(("start", folder))
        self.progress = OCRIndexProgress(state="running", total_requires_ocr=2, pending=2)

    def pause(self):
        self.actions.append(("pause",))
        self.progress = replace(self.progress, state="pausing")

    def resume(self): self.actions.append(("resume",))
    def cancel(self): self.actions.append(("cancel",))
    def status(self): return self.progress
    def is_running(self): return bool(self.progress and self.progress.state in {"preparing", "scanning", "initializing_worker", "running", "pausing", "paused", "cancelling"})
    def search(self, query, folder, limit):
        self.search_queries.append(query)
        return self.search_results[:limit]


def _app():
    return QApplication.instance() or QApplication([])


def _panel(tmp_path, *, selected=True, usable=True):
    _app()
    folder = tmp_path / "shots"
    if selected:
        folder.mkdir()
    config = {"selected_folder": str(folder) if selected else ""}
    controller = FakeOCRController(usable=usable)
    panel = OCRTestPanel(config, tmp_path, controller)
    panel._timer.stop()
    return panel, controller, folder


def test_initial_folder_and_environment_states(tmp_path):
    panel, _, _ = _panel(tmp_path, selected=False, usable=False)
    assert "No folder selected" in panel._folder_label.text()
    assert not panel._preview_btn.isEnabled()
    assert not panel._start_btn.isEnabled()
    assert "Not configured" in panel._environment_label.text()


def test_missing_folder_is_not_actionable(tmp_path):
    panel, _, folder = _panel(tmp_path)
    folder.rmdir()
    panel.refresh()
    assert "not available" in panel._folder_label.text()
    assert not panel._preview_btn.isEnabled()


def test_preview_updates_counts_without_starting_worker(tmp_path):
    panel, controller, folder = _panel(tmp_path)
    panel._preview_btn.click()
    assert controller.actions == [("preview", folder)]
    items = (
        OCRDiffItem(None, None, "a.png", "new", "new", True, None, "pending", 1, 1),
        OCRDiffItem(2, "b.png", "b.png", "unchanged", "same", False, "ready", "ready", 1, 1),
        OCRDiffItem(3, "c.png", "c.png", "modified", "changed", True, "ready", "stale", 1, 2),
    )
    result = OCRDiffResult(str(folder), "start", "end", 3, items)
    controller.preview_finished.emit(result, None)
    _app().processEvents()
    assert panel._count_labels["total"].text() == "3"
    assert panel._count_labels["needs"].text() == "2"
    assert not any(action[0] == "start" for action in controller.actions)


def test_progress_and_button_state_transitions(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    controller.progress = OCRIndexProgress(state="running", total_requires_ocr=10, completed=4, succeeded=3, failed=1, pending=6, current_filename="sample.png")
    panel.refresh_status()
    assert panel._pause_btn.isEnabled() and panel._cancel_btn.isEnabled()
    assert not panel._start_btn.isEnabled() and not panel._resume_btn.isEnabled()
    assert panel._progress_bar.value() == 4
    assert "sample.png" in panel._progress_label.text()
    controller.progress = replace(controller.progress, state="paused")
    panel.refresh_status()
    assert panel._resume_btn.isEnabled() and not panel._pause_btn.isEnabled()


def test_terminal_progress_refreshes_database_status_and_hides_unknown_estimate(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    controller.db_status = "ready"
    controller.progress = OCRIndexProgress(state="completed", total_discovered=2, total_requires_ocr=2, completed=2, succeeded=2)
    panel.refresh_status()
    assert "Index DB: Ready" in panel._environment_label.text()
    assert "Estimated remaining: —" in panel._progress_label.text()
    controller.progress = OCRIndexProgress(state="completed", total_discovered=2, total_requires_ocr=0)
    panel.refresh_status()
    assert panel._progress_bar.value() == panel._progress_bar.maximum() == 1
    assert "Up to date" in panel._progress_label.text()


def test_search_shows_match_sources_but_not_ocr_text(tmp_path):
    panel, controller, folder = _panel(tmp_path)
    controller.search_results = [SearchResult(1, str(folder / "sample.png"), 1, True, False, True, -1.0)]
    panel._search_input.setText("error")
    panel._search()
    text = panel._results.item(0).text()
    assert "sample.png" in text and "Filename / OCR" in text
    assert "full secret OCR body" not in text
    panel._search_input.setText("ab")
    panel._search()
    assert "3 characters" in panel._results_label.text()


def test_search_button_discards_clicked_bool_and_reads_current_text(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    panel._search_input.setText("config.get")
    panel._on_search_clicked(True)
    assert controller.search_queries == ["config.get"]


def test_enter_search_uses_current_unicode_and_special_character_text(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    for query in ("ファイル", "localhost:3000", r"C:\shots"):
        panel._search_input.setText(query)
        panel._search_input.returnPressed.emit()
    assert controller.search_queries == ["ファイル", "localhost:3000", r"C:\shots"]


def test_empty_and_short_search_do_not_call_repository(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    panel._search_input.setText("")
    panel._on_search_clicked(False)
    assert panel._results.count() == 0
    panel._search_input.setText("ab")
    panel._search_input.returnPressed.emit()
    assert "3 characters" in panel._results_label.text()
    assert controller.search_queries == []


def test_real_controller_requires_python_and_all_three_models(tmp_path, monkeypatch):
    python_path = tmp_path / "python.exe"
    python_path.write_bytes(b"")
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("CAPIXE_OCR_PYTHON", str(python_path))
    monkeypatch.setenv("CAPIXE_OCR_MODEL_DIR", str(models))
    controller = OCRTestController()
    assert not controller.environment_status()["usable"]
    for name in ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"):
        (models / name).write_bytes(b"model")
    status = controller.environment_status()
    assert status["runtime"] == "available"
    assert status["models"] == "ready"
    assert status["usable"] is True
    python_path.unlink()
    assert not controller.environment_status()["usable"]
    controller.close()


def test_frozen_environment_ignores_source_ocr_env_vars(tmp_path, monkeypatch):
    from app.ui.ocr_test_controller import REQUIRED_MODEL_FILES

    exe = tmp_path / "Capixe.exe"
    exe.write_bytes(b"")
    models = tmp_path / "resources" / "ocr_models"
    models.mkdir(parents=True)
    for name in REQUIRED_MODEL_FILES:
        (models / name).write_bytes(b"model")
    monkeypatch.setattr("app.ui.ocr_test_controller.is_frozen", lambda: True)
    monkeypatch.setattr("app.ui.ocr_test_controller.sys.executable", str(exe))
    monkeypatch.setattr(
        "app.ui.ocr_test_controller.get_resource_root", lambda: tmp_path
    )
    monkeypatch.setenv("CAPIXE_OCR_PYTHON", str(tmp_path / "missing-python.exe"))
    monkeypatch.setenv("CAPIXE_OCR_MODEL_DIR", str(tmp_path / "missing-models"))
    controller = OCRTestController()
    status = controller.environment_status()
    assert status["runtime"] == "available"
    assert status["models"] == "ready"
    assert status["usable"] is True
    controller.close()


def test_cancel_requires_confirmation(tmp_path, monkeypatch):
    panel, controller, _ = _panel(tmp_path)
    controller.progress = OCRIndexProgress(state="running")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    panel._cancel()
    assert ("cancel",) not in controller.actions
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    panel._cancel()
    assert ("cancel",) in controller.actions


def test_terminal_state_waits_for_service_thread_cleanup_before_restart(tmp_path):
    panel, controller, _ = _panel(tmp_path)
    controller.progress = OCRIndexProgress(state="cancelled")
    controller.is_running = lambda: True
    panel.refresh_status()
    assert not panel._start_btn.isEnabled()
    controller.is_running = lambda: False
    panel.refresh_status()
    assert panel._start_btn.isEnabled()


def test_initial_preview_does_not_create_persistent_ocr_database(tmp_path):
    app = _app()
    folder = tmp_path / "shots"
    folder.mkdir()
    controller = OCRTestController()
    completed = []
    controller.preview_finished.connect(lambda result, error: completed.append((result, error)))
    assert controller.preview(folder)
    for _ in range(200):
        app.processEvents()
        if completed:
            break
        __import__("time").sleep(0.005)
    assert completed and completed[0][1] is None
    assert not (get_local_app_data_dir() / DB_FILE_NAME).exists()
    controller.close()
