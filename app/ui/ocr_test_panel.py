"""Development-only OCR validation panel shown at the bottom of Settings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from app.i18n import t
from app.utils.selected_folder import selected_folder_state


ACTIVE_STATES = {"preparing", "scanning", "initializing_worker", "running", "pausing", "paused", "cancelling", "closing"}


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return t("ocr_test.calculating")
    value = max(0, int(seconds))
    if value < 60:
        return t("ocr_test.seconds", count=value)
    return t("ocr_test.minutes", count=max(1, round(value / 60)))


class _ElidedFolderLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setFullText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._update_elision()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elision()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 520), hint.height())

    def _update_elision(self) -> None:
        width = max(20, self.contentsRect().width())
        if width <= 100:
            self.setText(self._full_text)
            return
        self.setText(self.fontMetrics().elidedText(self._full_text, Qt.ElideMiddle, width))


class OCRTestPanel(QFrame):
    def __init__(self, config: dict, app_root: Path, controller, parent=None):
        super().__init__(parent)
        self.setObjectName("infoPanel")
        self._config = config
        self._app_root = app_root
        self._controller = controller
        self._preview = None
        self._start_after_preview = False
        self._build_ui()
        controller.preview_finished.connect(self._on_preview_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        title = QLabel(t("ocr_test.title"), self)
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        hint = QLabel(t("ocr_test.subtitle"), self)
        hint.setObjectName("mutedLabel")
        outer.addWidget(hint)

        self._folder_label = _ElidedFolderLabel(self)
        self._folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._folder_label.setTextFormat(Qt.PlainText)
        outer.addWidget(self._folder_label)

        self._environment_label = QLabel(self)
        self._environment_label.setObjectName("mutedLabel")
        self._environment_label.setWordWrap(True)
        outer.addWidget(self._environment_label)

        counts = QGridLayout()
        counts.setHorizontalSpacing(24)
        counts.setVerticalSpacing(4)
        self._count_labels = {}
        for row, (key, text_key) in enumerate((
            ("total", "ocr_test.total_images"), ("new", "ocr_test.new"),
            ("modified", "ocr_test.modified"), ("missing", "ocr_test.missing"),
            ("indexed", "ocr_test.already_indexed"), ("needs", "ocr_test.needs_ocr"),
            ("retry", "ocr_test.retry_eligible"), ("scan_failed", "ocr_test.scan_failed"),
        )):
            counts.addWidget(QLabel(t(text_key), self), row // 2, (row % 2) * 2)
            value = QLabel("—", self)
            self._count_labels[key] = value
            counts.addWidget(value, row // 2, (row % 2) * 2 + 1)
        outer.addLayout(counts)

        buttons = QHBoxLayout()
        self._preview_btn = QPushButton(t("ocr_test.preview"), self)
        self._start_btn = QPushButton(t("ocr_test.start"), self)
        self._pause_btn = QPushButton(t("ocr_test.pause"), self)
        self._resume_btn = QPushButton(t("ocr_test.resume"), self)
        self._cancel_btn = QPushButton(t("ocr_test.cancel"), self)
        self._refresh_btn = QPushButton(t("ocr_test.refresh_status"), self)
        for button in (self._preview_btn, self._pause_btn, self._resume_btn, self._cancel_btn, self._refresh_btn):
            button.setObjectName("secondaryButton")
        for button in (self._preview_btn, self._start_btn, self._pause_btn, self._resume_btn, self._cancel_btn, self._refresh_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        self._preview_btn.clicked.connect(self._preview_indexing)
        self._start_btn.clicked.connect(self._start_ocr)
        self._pause_btn.clicked.connect(self._pause)
        self._resume_btn.clicked.connect(self._resume)
        self._cancel_btn.clicked.connect(self._cancel)
        self._refresh_btn.clicked.connect(self.refresh)

        progress_title = QLabel(t("ocr_test.progress"), self)
        progress_title.setObjectName("sectionTitle")
        outer.addWidget(progress_title)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        outer.addWidget(self._progress_bar)
        self._progress_label = QLabel(self)
        self._progress_label.setWordWrap(True)
        outer.addWidget(self._progress_label)
        self._error_label = QLabel(self)
        self._error_label.setObjectName("mutedLabel")
        self._error_label.setWordWrap(True)
        outer.addWidget(self._error_label)

        search_title = QLabel(t("ocr_test.search_title"), self)
        search_title.setObjectName("sectionTitle")
        outer.addWidget(search_title)
        search_row = QHBoxLayout()
        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText(t("ocr_test.search_placeholder"))
        self._search_btn = QPushButton(t("ocr_test.search"), self)
        search_row.addWidget(self._search_input, 1)
        search_row.addWidget(self._search_btn)
        outer.addLayout(search_row)
        # Never use a signal payload as the query.  PySide versions differ in
        # whether QPushButton.clicked(bool) drops the bool for a no-arg slot.
        self._search_input.returnPressed.connect(self._on_search_return_pressed)
        self._search_btn.clicked.connect(self._on_search_clicked)
        self._results_label = QLabel(t("ocr_test.results", count=0), self)
        outer.addWidget(self._results_label)
        self._results = QListWidget(self)
        self._results.setMaximumHeight(150)
        outer.addWidget(self._results)

    def _folder(self) -> tuple[Path | None, str]:
        return selected_folder_state(self._config, self._app_root)

    def refresh(self) -> None:
        folder, state = self._folder()
        if state == "unselected":
            text = t("ocr_test.no_folder")
        elif state != "ready":
            text = t("ocr_test.folder_unavailable")
        else:
            text = str(folder)
        self._folder_label.setFullText(f'{t("ocr_test.selected_folder")}:  {text}')
        self._folder_label.setToolTip(str(folder) if folder else "")
        self._refresh_environment_label()
        self.refresh_status()

    def _refresh_environment_label(self) -> None:
        env = self._controller.environment_status()
        self._environment_label.setText(t(
            "ocr_test.environment_status", runtime=t(f"ocr_test.status.{env['runtime']}"),
            worker=t(f"ocr_test.status.{env['worker']}"), models=t(f"ocr_test.status.{env['models']}"),
            database=t(f"ocr_test.status.{env['database']}"),
        ))

    def _valid_folder(self) -> Path | None:
        folder, state = self._folder()
        return folder if state == "ready" else None

    def _preview_indexing(self) -> None:
        folder = self._valid_folder()
        if folder and self._controller.preview(folder):
            self._preview_btn.setEnabled(False)
            self._error_label.setText(t("ocr_test.preview_running"))

    def _on_preview_finished(self, result, error) -> None:
        if error is not None:
            self._error_label.setText(t("ocr_test.folder_error"))
            self._preview = None
        else:
            self._error_label.clear()
            self._preview = result
            unchanged = len(result.unchanged_items)
            retry = sum(1 for item in result.items if item.previous_status == "failed" and item.requires_ocr)
            values = {
                "total": result.total_files, "new": len(result.new_items),
                "modified": len(result.modified_items), "missing": len(result.missing_items),
                "indexed": unchanged, "needs": result.reindex_required_count,
                "retry": retry, "scan_failed": len(result.scan_failed_items),
            }
            for key, value in values.items():
                self._count_labels[key].setText(str(value))
        self.refresh_status()
        if error is None and self._start_after_preview:
            self._start_after_preview = False
            self._confirm_start()
        elif error is not None:
            self._start_after_preview = False

    def _start_ocr(self) -> None:
        if self._preview is None:
            self._start_after_preview = True
            self._preview_indexing()
            return
        self._confirm_start()

    def _confirm_start(self) -> None:
        folder = self._valid_folder()
        if not folder:
            return
        count = self._preview.reindex_required_count if self._preview else 0
        message = t("ocr_test.start_message", count=count)
        box = QMessageBox(QMessageBox.Question, t("ocr_test.start_title"), message, parent=self)
        start_button = box.addButton(t("ocr_test.start_confirm"), QMessageBox.AcceptRole)
        box.addButton(t("ocr_test.cancel"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not start_button:
            return
        try:
            self._controller.start(folder)
        except Exception:
            self._error_label.setText(t("ocr_test.environment_error"))
        self.refresh_status()

    def _pause(self) -> None:
        self._controller.pause()
        self.refresh_status()

    def _resume(self) -> None:
        self._controller.resume()
        self.refresh_status()

    def _cancel(self) -> None:
        answer = QMessageBox.question(self, t("ocr_test.cancel_title"), t("ocr_test.cancel_message"), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._controller.cancel()
            self.refresh_status()

    def refresh_status(self) -> None:
        self._refresh_environment_label()
        status = self._controller.status()
        state = status.state if status else "idle"
        folder_ok = self._valid_folder() is not None
        env_ok = bool(self._controller.environment_status()["usable"])
        # A terminal state is published just before the service thread's final
        # worker cleanup completes.  Do not allow a new run in that brief gap.
        active = state in ACTIVE_STATES or self._controller.is_running()
        self._preview_btn.setEnabled(folder_ok and not active)
        self._start_btn.setEnabled(folder_ok and env_ok and not active)
        self._pause_btn.setEnabled(state == "running")
        self._resume_btn.setEnabled(state == "paused")
        self._cancel_btn.setEnabled(state in {"preparing", "scanning", "initializing_worker", "running", "pausing", "paused"})
        if status is None:
            self._progress_label.setText(t("ocr_test.progress_idle"))
            return
        maximum = max(1, status.total_requires_ocr)
        self._progress_bar.setRange(0, maximum)
        value = maximum if state == "completed" and status.total_requires_ocr == 0 else min(status.completed, maximum)
        self._progress_bar.setValue(value)
        current = status.current_filename or "—"
        if not status.total_requires_ocr:
            estimate = t("ocr_test.up_to_date")
        elif state in {"completed", "cancelled", "failed", "closing"}:
            estimate = "—"
        else:
            estimate = _duration(status.estimated_remaining_seconds)
        self._progress_label.setText(t(
            "ocr_test.progress_details", state=state.replace("_", " ").title(),
            discovered=status.total_discovered,
            completed=status.completed, total=status.total_requires_ocr,
            succeeded=status.succeeded, failed=status.failed, skipped=status.skipped,
            pending=status.pending, current=current, restarts=status.worker_restart_count,
            elapsed=_duration(status.elapsed_seconds), estimate=estimate,
        ))
        self._error_label.setText(t("ocr_test.last_error", error=status.last_error_type)) if status.last_error_type else None

    def _search(self) -> None:
        self._results.clear()
        query = self._search_input.text().strip()
        if not query:
            self._results_label.setText(t("ocr_test.results", count=0))
            return
        if len(query) < 3:
            self._results_label.setText(t("ocr_test.search_minimum"))
            return
        folder = self._valid_folder()
        if not folder:
            return
        try:
            results = self._controller.search(query, folder, 50)
        except Exception:
            self._error_label.setText(t("ocr_test.database_error"))
            return
        self._results_label.setText(t("ocr_test.results", count=len(results)))
        if not results:
            self._results.addItem(t("ocr_test.no_results"))
        for result in results:
            sources = []
            if result.matched_filename: sources.append(t("ocr_test.filename"))
            if result.matched_tags: sources.append(t("ocr_test.tags"))
            if result.matched_ocr: sources.append(t("ocr_test.ocr"))
            name = Path(result.path).name
            item = QListWidgetItem(f'{name}\n{t("ocr_test.matched_in")}: {" / ".join(sources)}')
            item.setToolTip(name)
            self._results.addItem(item)

    def _on_search_clicked(self, _checked: bool = False) -> None:
        self._search()

    def _on_search_return_pressed(self) -> None:
        self._search()

    def stop_polling(self) -> None:
        self._timer.stop()
