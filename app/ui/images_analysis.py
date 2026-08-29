"""Small user-facing analysis control for the Images page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from app.i18n import t
from app.ocr.index_exceptions import OCRIndexAlreadyRunningError
from app.ui.icons import icon_analyze

ACTIVE_STATES = {
    "preparing", "scanning", "initializing_worker", "running",
    "pausing", "paused", "cancelling", "closing",
}
AUTO_START_OCR_CLASSIFICATIONS = {"new", "modified", "restored"}
AUTO_START_OCR_PREVIOUS = {"pending", "stale", "running", None}
AUTO_START_SEMANTIC_STATES = {"missing_embedding", "stale_model", "modified"}
FAILED_OCR_STATES = {"failed", "error"}
FAILED_SEMANTIC_STATES = {"failed", "corrupt", "error"}
READY_OCR_STATES = {"ready"}
READY_SEMANTIC_STATES = {"unchanged", "ready"}
AUTO_RETRY_DELAYS_MS = (1500, 8000, 30000)


def has_auto_start_work(result, details: dict[str, dict] | None = None) -> bool:
    """True when folder diff has new/changed work, not failed-only leftovers."""
    items = getattr(result, "items", ()) or ()
    for item in items:
        if not getattr(item, "requires_ocr", False):
            continue
        if getattr(item, "classification", "") in AUTO_START_OCR_CLASSIFICATIONS:
            return True
        if getattr(item, "previous_status", None) in AUTO_START_OCR_PREVIOUS:
            return True
    return has_semantic_auto_start_work(details)


def has_semantic_auto_start_work(details: dict[str, dict] | None = None) -> bool:
    """True when embeddings are missing or stale and should start immediately."""
    for detail in (details or {}).values():
        semantic = str(detail.get("semantic_status", "")).lower()
        if semantic in AUTO_START_SEMANTIC_STATES:
            return True
    return False


def needs_analysis_retry(
    status=None,
    details: dict[str, dict] | None = None,
    counts: dict[str, int] | None = None,
) -> bool:
    """True when failed/cancelled leftovers still need background retry."""
    state = str(getattr(status, "state", "") or "").lower()
    if state in {"failed", "cancelled"}:
        return True
    if state == "completed" and int(getattr(status, "failed", 0) or 0) > 0:
        return True
    if counts and (
        int(counts.get("ocr_failed", 0) or 0) > 0
        or int(counts.get("semantic_failed", 0) or 0) > 0
    ):
        return True
    for detail in (details or {}).values():
        if str(detail.get("ocr_status", "")).lower() in FAILED_OCR_STATES:
            return True
        if str(detail.get("semantic_status", "")).lower() in FAILED_SEMANTIC_STATES:
            return True
    return False


def unresolved_analysis_paths(details: dict[str, dict] | None) -> list[Path]:
    """Paths whose OCR or Semantic state is not ready."""
    paths: list[Path] = []
    for detail in (details or {}).values():
        ocr = str(detail.get("ocr_status", "")).lower()
        semantic = str(detail.get("semantic_status", "")).lower()
        if ocr in READY_OCR_STATES and semantic in READY_SEMANTIC_STATES:
            continue
        path = detail.get("path")
        if path:
            paths.append(Path(path))
    return paths


def aggregate_analysis_states(details: dict[str, dict], total: int) -> dict[str, int]:
    """Count OCR and Semantic states independently without losing either."""
    counts = {
        "total": max(0, int(total)),
        "semantic_ready": 0, "semantic_pending": 0, "semantic_failed": 0,
        "ocr_ready": 0, "ocr_pending": 0, "ocr_failed": 0,
        "processing": 0,
    }
    active_values = {"running", "processing", "claimed"}
    for detail in details.values():
        ocr = str(detail.get("ocr_status", "missing")).lower()
        semantic = str(detail.get("semantic_status", "missing_embedding")).lower()
        if semantic in {"unchanged", "ready"}:
            counts["semantic_ready"] += 1
        elif semantic in {"failed", "corrupt", "error"}:
            counts["semantic_failed"] += 1
        else:
            counts["semantic_pending"] += 1
        if ocr == "ready":
            counts["ocr_ready"] += 1
        elif ocr in {"failed", "error"}:
            counts["ocr_failed"] += 1
        else:
            counts["ocr_pending"] += 1
        if ocr in active_values or semantic in active_values:
            counts["processing"] += 1
    unclassified = max(0, counts["total"] - len(details))
    counts["semantic_pending"] += unclassified
    counts["ocr_pending"] += unclassified
    return counts


def format_count(value: int) -> str:
    return f"{max(0, int(value)):,}"


def resolve_library_prep_state(
    *,
    folder,
    bundle_available: bool,
    checking: bool,
    running: bool,
    semantic_ready: int,
    total: int,
    failed: bool = False,
) -> str:
    """User-facing AI-search prep state. Hidden when Meaning search cannot run."""
    if folder is None:
        return "hidden"
    if int(total) <= 0 and not running and not checking:
        return "hidden"
    if checking:
        return "checking"
    if not bundle_available:
        return "hidden"
    if failed and int(semantic_ready) <= 0:
        return "failed"
    if running or int(semantic_ready) < max(0, int(total)):
        return "preparing"
    return "ready"


def library_prep_activity(
    *,
    ocr_pending: int = 0,
    semantic_pending: int = 0,
    running: bool = False,
) -> str:
    """Secondary status under the shared 'preparing images' heading."""
    if int(ocr_pending) > 0:
        return t("images.prep.activity.ocr")
    if int(semantic_pending) > 0 or running:
        return t("images.prep.activity.search")
    return ""


def library_prep_text(
    state: str,
    *,
    ready: int = 0,
    total: int = 0,
    activity: str = "",
) -> str:
    """Copy for library preparation. Separate from Meaning search progress."""
    if state == "checking":
        return t("images.prep.checking")
    if state == "preparing":
        text = t(
            "images.prep.preparing",
            ready=format_count(ready),
            total=format_count(total),
        )
        detail = str(activity or "").strip()
        return f"{text} · {detail}" if detail else text
    if state == "ready":
        return t("images.prep.ready", count=format_count(total or ready))
    if state == "failed":
        return t("images.prep.failed")
    return ""


def library_prep_hint(state: str) -> str:
    if state in {"checking", "preparing"}:
        return t("images.prep.hint")
    return ""


def status_folder_path(status) -> Path | None:
    raw = getattr(status, "folder_path", None)
    if not raw:
        return None
    try:
        return Path(raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


class ImagesAnalysisBar(QFrame):
    """Expose only analysis readiness and progress; diagnostics stay in Settings."""

    analysis_completed = Signal()
    analysis_summary_changed = Signal(object)
    analysis_progress_changed = Signal(object)
    library_prep_changed = Signal(object)
    retry_needed_changed = Signal(bool)

    def __init__(self, controller, parent=None, *, auto_start: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("imagesAnalysisBar")
        self._controller = controller
        self._auto_start = auto_start
        self._folder: Path | None = None
        self._preview = None
        self._preview_running = False
        self._preview_stale = False
        self._start_after_preview = False
        self._auto_start_blocked = False
        self._retry_needed = False
        self._auto_retry_attempt = 0
        self._auto_retry_timer = QTimer(self)
        self._auto_retry_timer.setSingleShot(True)
        self._auto_retry_timer.timeout.connect(self._on_auto_retry_timeout)
        self._semantic_followup_pending = False
        self._last_state = "idle"
        self._summary_total = 0
        self._summary_analyzed = 0
        self._summary_pending = 0
        self._ocr_pending = 0
        self._last_details: dict[str, dict] = {}
        self._semantic_run_active = False
        self._prep_failed = False
        self._checking = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        top_row = QWidget(self)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        self._status_label = QLabel(t("images.analysis.checking"), top_row)
        self._status_label.setObjectName("mutedLabel")
        top_layout.addWidget(self._status_label, 1)
        self._progress = QProgressBar(top_row)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(100)
        self._progress.hide()
        top_layout.addWidget(self._progress)
        self._analyze_btn = QPushButton(t("images.analysis.action"), top_row)
        self._analyze_btn.setObjectName("secondaryButton")
        self._analyze_btn.setIcon(icon_analyze())
        self._analyze_btn.setIconSize(QSize(16, 16))
        self._analyze_btn.clicked.connect(self._on_action_clicked)
        top_layout.addWidget(self._analyze_btn)
        if self._auto_start:
            self._analyze_btn.hide()
        layout.addWidget(top_row)

        total_row = QWidget(self)
        total_layout = QHBoxLayout(total_row)
        total_layout.setContentsMargins(0, 0, 0, 0)
        total_layout.setSpacing(6)
        self._summary_labels = {}
        total_label = QLabel(total_row)
        total_label.setObjectName("analysisStatusChip")
        total_layout.addWidget(total_label)
        self._summary_labels["total"] = total_label
        total_layout.addStretch(1)
        layout.addWidget(total_row)
        for section, keys in (
            ("images.analysis.semantic_section", ("semantic_ready", "semantic_pending", "semantic_failed")),
            ("images.analysis.ocr_section", ("ocr_ready", "ocr_pending", "ocr_failed")),
        ):
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            heading = QLabel(t(section), row)
            heading.setObjectName("mutedLabel")
            row_layout.addWidget(heading)
            for key in keys:
                label = QLabel(row)
                label.setObjectName("analysisStatusChip")
                row_layout.addWidget(label)
                self._summary_labels[key] = label
            row_layout.addStretch(1)
            layout.addWidget(row)
        self._set_counts({key: 0 for key in self._summary_labels})

        controller.preview_finished.connect(self._on_preview_finished)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start()

    def set_folder(self, folder: Path | None, *, force: bool = False) -> None:
        resolved = folder.resolve() if folder and folder.exists() else None
        folder_changed = resolved != self._folder
        if folder_changed:
            self._auto_start_blocked = False
            self._reset_auto_retry()
            self._semantic_followup_pending = False
            self._semantic_run_active = False
            self._prep_failed = False
            self._cancel_foreign_analysis(resolved)
        if not force and not folder_changed and self._preview is not None:
            return
        self._folder = resolved
        self._preview = None
        self._start_after_preview = False
        if self._folder is None:
            self._checking = False
            self._status_label.setText(t("images.analysis.no_folder"))
            self._analyze_btn.setEnabled(False)
            self._progress.hide()
            self._set_retry_needed(False)
            self._reset_auto_retry()
            self._publish_library_prep()
            return
        self._checking = True
        self._summary_total = 0
        self._summary_analyzed = 0
        self._publish_library_prep()
        self._request_preview()

    def _cancel_foreign_analysis(self, folder: Path | None) -> None:
        """Stop a previous folder's run so this folder can start without mixed UI."""
        if folder is None or not self._controller.is_running():
            return
        running = status_folder_path(self._controller.status())
        if running is None or running == folder:
            return
        cancel = getattr(self._controller, "cancel", None)
        if callable(cancel):
            cancel()

    def _request_preview(self) -> None:
        if self._folder is None:
            return
        if self._preview_running or self._controller.is_running():
            self._preview_stale = True
            return
        started = bool(self._controller.preview(self._folder))
        self._preview_running = started
        if started:
            self._checking = True
            self._status_label.setText(t("images.analysis.checking"))
            self._analyze_btn.setEnabled(False)
            self._publish_library_prep()
        else:
            self._preview_stale = True

    def _on_preview_finished(self, result, error) -> None:
        self._preview_running = False
        if result is not None and self._folder is not None:
            if Path(result.folder_path).resolve() != self._folder:
                if self._preview_stale:
                    self._preview_stale = False
                    self._request_preview()
                return
        if self._preview_stale:
            self._preview_stale = False
            self._request_preview()
            return
        if error is not None or result is None:
            self._preview = None
            self._checking = False
            self._prep_failed = True
            self._status_label.setText(t("images.analysis.check_failed"))
            self._analyze_btn.setEnabled(True)
            self._start_after_preview = False
            self._set_retry_needed(True)
            self._publish_library_prep()
            return
        self._preview = result
        self._checking = False
        self._prep_failed = False
        self._ocr_pending = result.reindex_required_count
        pending_names = {
            Path(item.new_path).name
            for item in result.items
            if item.requires_ocr and item.new_path
        }
        semantic_pending = (
            self._controller.semantic_pending_names(self._folder)
            if hasattr(self._controller, "semantic_pending_names")
            else set()
        )
        pending_names |= semantic_pending
        details = (
            self._controller.analysis_details(self._folder)
            if hasattr(self._controller, "analysis_details") else {}
        )
        self._last_details = details if isinstance(details, dict) else {}
        count = len(pending_names)
        counts = aggregate_analysis_states(details, result.total_files)
        analyzed = counts["semantic_ready"]
        if not details:
            counts["semantic_ready"] = analyzed
            counts["ocr_ready"] = max(0, result.total_files - self._ocr_pending)
            counts["semantic_pending"] = len(pending_names)
            counts["ocr_pending"] = self._ocr_pending
        self._set_counts(counts)
        self._summary_total = result.total_files
        self._summary_analyzed = counts["semantic_ready"]
        self._summary_pending = len(pending_names)
        self.analysis_summary_changed.emit(
            {
                "total": result.total_files,
                "analyzed": analyzed,
                "pending": len(pending_names),
                "pending_names": pending_names,
                "details": details,
                "counts": counts,
            }
        )
        incremental = has_auto_start_work(result, details)
        retry_needed = needs_analysis_retry(None, details, counts)
        ocr_usable = self._ocr_environment_usable()
        semantic_work = has_semantic_auto_start_work(details)
        if incremental:
            self._auto_start_blocked = False
            self._reset_auto_retry()
        can_auto_start = (
            bool(count)
            and self._auto_start
            and not self._auto_start_blocked
            and incremental
        )
        if count:
            self._status_label.setText(t(
                "images.analysis.summary_by_type", total=result.total_files,
                semantic_ready=counts["semantic_ready"], ocr_ready=counts["ocr_ready"],
            ))
            self._analyze_btn.setText(t("images.analysis.action"))
            self._analyze_btn.setEnabled(ocr_usable or semantic_work)
            if not ocr_usable:
                self._analyze_btn.setToolTip(t("images.analysis.unavailable"))
            if can_auto_start:
                if not self._begin_if_needed():
                    retry_needed = True
        else:
            self._status_label.setText(t(
                "images.analysis.summary_by_type", total=result.total_files,
                semantic_ready=counts["semantic_ready"], ocr_ready=counts["ocr_ready"],
            ))
            self._analyze_btn.setEnabled(False)
        if self._start_after_preview:
            self._start_after_preview = False
            if not self._begin_if_needed():
                retry_needed = True
        self._set_retry_needed(
            retry_needed and not self._controller.is_running()
        )
        self._publish_library_prep()

    def _start_analysis(self) -> None:
        if self._preview is None:
            self._start_after_preview = True
            self._request_preview()
            return
        if not self._begin_if_needed():
            self._set_retry_needed(True)

    def _on_action_clicked(self) -> None:
        if self._controller.is_running():
            cancel = getattr(self._controller, "cancel", None)
            if callable(cancel):
                cancel()
                self._analyze_btn.setText(t("images.analysis.cancelling"))
                self._analyze_btn.setEnabled(False)
            return
        self._start_analysis()

    def start_analysis(self) -> None:
        """Public entry point shared by Images and the Home dashboard."""
        self._start_analysis()

    def _ocr_environment_usable(self) -> bool:
        try:
            return bool(self._controller.environment_status()["usable"])
        except Exception:
            return False

    def _semantic_available(self) -> bool:
        available = getattr(self._controller, "semantic_available", None)
        if callable(available):
            try:
                return bool(available())
            except Exception:
                return False
        return True

    def _publish_library_prep(self, *, running: bool | None = None, ready: int | None = None) -> None:
        semantic_ready = self._summary_analyzed if ready is None else ready
        is_running = self._controller.is_running() if running is None else running
        ocr_ready, ocr_pending, semantic_pending = self._library_prep_counts()
        if ocr_pending > 0:
            display_ready = ocr_ready
        else:
            display_ready = semantic_ready
        state = resolve_library_prep_state(
            folder=self._folder,
            bundle_available=self._semantic_available(),
            checking=self._checking,
            running=is_running,
            semantic_ready=semantic_ready,
            total=self._summary_total,
            failed=self._prep_failed,
        )
        activity = library_prep_activity(
            ocr_pending=ocr_pending,
            semantic_pending=semantic_pending,
            running=is_running and state == "preparing",
        ) if state == "preparing" else ""
        payload = {
            "state": state,
            "ready": max(0, int(display_ready)),
            "total": max(0, int(self._summary_total)),
            "ocr_ready": max(0, int(ocr_ready)),
            "ocr_pending": max(0, int(ocr_pending)),
            "semantic_ready": max(0, int(semantic_ready)),
            "semantic_pending": max(0, int(semantic_pending)),
            "folder": str(self._folder) if self._folder is not None else "",
            "activity": activity,
            "hint": library_prep_hint(state),
            "text": library_prep_text(
                state,
                ready=display_ready,
                total=self._summary_total,
                activity=activity,
            ),
        }
        self.library_prep_changed.emit(payload)

    def _library_prep_counts(self) -> tuple[int, int, int]:
        total = max(0, int(self._summary_total or 0))
        details = self._last_details
        if details:
            counts = aggregate_analysis_states(details, total)
            return (
                int(counts["ocr_ready"]),
                int(counts["ocr_pending"]),
                int(counts["semantic_pending"]),
            )
        ocr_pending = max(0, int(self._ocr_pending or 0))
        ocr_ready = max(0, total - ocr_pending)
        semantic_pending = max(0, total - int(self._summary_analyzed or 0))
        return ocr_ready, ocr_pending, semantic_pending

    def tour_local_snapshot(self) -> dict:
        total = max(0, int(self._summary_total or 0))
        details = self._last_details
        getter = getattr(self._controller, "analysis_details", None)
        if self._folder is not None and callable(getter):
            live = getter(self._folder)
            if isinstance(live, dict) and live:
                details = live
                self._last_details = details
        running = bool(self._checking or self._controller.is_running())
        failed = 0
        if details:
            counts = aggregate_analysis_states(details, total)
            ready = int(counts["ocr_ready"])
            pending = int(counts["ocr_pending"])
            failed = int(counts["ocr_failed"])
        else:
            ocr_label = self._summary_labels.get("ocr_ready")
            failed_label = self._summary_labels.get("ocr_failed")
            ready = (
                int(ocr_label.property("count") or 0)
                if ocr_label is not None
                else int(self._summary_analyzed or 0)
            )
            failed = int(failed_label.property("count") or 0) if failed_label is not None else 0
            pending = max(0, total - ready - failed)
        if running and not self._semantic_run_active:
            status = self._controller.status()
            state = str(getattr(status, "state", "") or "").lower() if status is not None else ""
            if state in ACTIVE_STATES:
                ready = min(total, ready + max(0, int(getattr(status, "completed", 0) or 0)))
                pending = max(0, total - ready - failed)
        return {
            "ready": max(0, ready),
            "total": total,
            "needed": 0 if not running else max(0, pending),
            "running": running,
            "error": bool(getattr(self, "_prep_failed", False)) and ready <= 0,
            "failed": max(0, failed),
        }

    def _begin_if_needed(self) -> bool:
        """Start pending work. False only when starting fails."""
        if self._folder is None or not self._preview:
            return False
        if self._summary_pending <= 0:
            self._show_summary()
            self._publish_library_prep()
            return True
        ocr_usable = self._ocr_environment_usable()
        try:
            if self._ocr_pending > 0 and ocr_usable:
                self._controller.start(self._folder)
                self._semantic_followup_pending = True
                self._semantic_run_active = False
            elif hasattr(self._controller, "start_semantic"):
                started = bool(self._controller.start_semantic(self._folder))
                if not started:
                    if self._controller.is_running():
                        return False
                    self._show_summary()
                    self._publish_library_prep()
                    return True
                self._semantic_run_active = True
            elif ocr_usable:
                self._controller.start(self._folder)
                self._semantic_followup_pending = True
                self._semantic_run_active = False
            else:
                self._show_summary()
                self._publish_library_prep()
                return True
        except OCRIndexAlreadyRunningError:
            return False
        except Exception:
            self._status_label.setText(t("images.analysis.start_failed"))
            self._analyze_btn.setEnabled(True)
            if self._auto_start:
                self._auto_start_blocked = True
            self._publish_library_prep()
            return False
        self.refresh_status()
        return True

    def refresh_status(self) -> None:
        status = self._controller.status()
        if status is None:
            return
        running_folder = status_folder_path(status)
        if (
            self._folder is not None
            and running_folder is not None
            and running_folder != self._folder
        ):
            return
        self.analysis_progress_changed.emit(status)
        state = status.state
        active = state in ACTIVE_STATES or self._controller.is_running()
        if active:
            self._set_retry_needed(False)
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
            self._analyze_btn.setText(t("images.analysis.cancel"))
            self._analyze_btn.setEnabled(hasattr(self._controller, "cancel"))
            ready = self._summary_analyzed
            if self._semantic_run_active:
                ready = min(
                    self._summary_total,
                    self._summary_analyzed + max(0, int(status.completed or 0)),
                )
            self._publish_library_prep(running=True, ready=ready)
        elif state == "completed":
            if self._start_semantic_followup():
                self._last_state = "initializing_worker"
                self._publish_library_prep(running=True)
                return
            self._semantic_run_active = False
            self._progress.hide()
            semantic_pending = (
                self._controller.semantic_pending_names(self._folder)
                if hasattr(self._controller, "semantic_pending_names")
                and self._folder is not None
                else set()
            )
            if status.failed:
                self._summary_pending = len(semantic_pending)
                self._summary_analyzed = max(
                    0, self._summary_total - self._summary_pending
                )
                self._show_summary()
                self._status_label.setToolTip(t(
                    "images.analysis.completed_with_failures",
                    succeeded=status.succeeded,
                    failed=status.failed,
                ))
                self._analyze_btn.setEnabled(True)
                self._set_retry_needed(True)
            else:
                self._summary_pending = len(semantic_pending)
                self._summary_analyzed = max(
                    0, self._summary_total - self._summary_pending
                )
                self._show_summary()
                self._analyze_btn.setEnabled(bool(self._summary_pending))
                self._reset_auto_retry()
                self._set_retry_needed(False)
            self._analyze_btn.setText(t("images.analysis.action"))
            self._publish_library_prep(running=False)
            if self._last_state in ACTIVE_STATES:
                self._preview = None
                self.analysis_completed.emit()
        elif state in {"failed", "cancelled"}:
            if self._start_semantic_followup():
                self._last_state = "initializing_worker"
                self._publish_library_prep(running=True)
                return
            self._semantic_run_active = False
            self._prep_failed = True
            self._progress.hide()
            self._status_label.setText(t("images.analysis.failed"))
            self._analyze_btn.setText(t("images.analysis.action"))
            self._analyze_btn.setEnabled(True)
            self._set_retry_needed(True)
            self._publish_library_prep(running=False)
        self._last_state = state

    def _start_semantic_followup(self) -> bool:
        """Run embeddings once after OCR, including failed/cancelled OCR."""
        if not self._semantic_followup_pending:
            return False
        self._semantic_followup_pending = False
        if not hasattr(self._controller, "start_semantic") or self._folder is None:
            return False
        started = bool(self._controller.start_semantic(self._folder))
        self._semantic_run_active = started
        return started

    def retry_unresolved(self) -> None:
        """Retry failed/cancelled leftovers without a full-folder reanalysis."""
        self._auto_start_blocked = False
        if self._folder is None:
            return
        details = self._last_details
        if hasattr(self._controller, "analysis_details"):
            details = self._controller.analysis_details(self._folder) or details
        paths = unresolved_analysis_paths(details)
        if paths and hasattr(self._controller, "retry_analysis_paths"):
            if self._controller.retry_analysis_paths(paths):
                self.refresh_status()
                return
        self._start_analysis()

    def _reset_auto_retry(self) -> None:
        self._auto_retry_attempt = 0
        self._auto_retry_timer.stop()

    def _schedule_silent_retry(self) -> None:
        if not self._auto_start or self._folder is None:
            return
        if self._controller.is_running() or self._auto_retry_timer.isActive():
            return
        delays = AUTO_RETRY_DELAYS_MS
        if self._auto_retry_attempt >= len(delays):
            return
        delay = max(0, int(delays[self._auto_retry_attempt]))
        self._auto_retry_attempt += 1
        self._auto_retry_timer.start(delay)

    def _on_auto_retry_timeout(self) -> None:
        if self._controller.is_running() or self._folder is None:
            return
        self.retry_unresolved()

    def _set_retry_needed(self, needed: bool) -> None:
        needed = bool(needed)
        if self._auto_start:
            if needed:
                self._schedule_silent_retry()
            else:
                self._auto_retry_timer.stop()
            needed = False
        if needed == self._retry_needed:
            return
        self._retry_needed = needed
        self.retry_needed_changed.emit(needed)

    def _show_summary(self) -> None:
        ocr_label = self._summary_labels.get("ocr_ready")
        self._status_label.setText(t(
            "images.analysis.summary_by_type", total=self._summary_total,
            semantic_ready=self._summary_analyzed,
            ocr_ready=int(ocr_label.property("count") or 0) if ocr_label else 0,
        ))

    def _set_counts(self, counts: dict[str, int]) -> None:
        labels = {
            "total": "images.analysis.total",
            "semantic_ready": "images.analysis.state_ready",
            "semantic_pending": "images.analysis.state_pending",
            "semantic_failed": "images.analysis.state_failed",
            "ocr_ready": "images.analysis.state_ready",
            "ocr_pending": "images.analysis.state_pending",
            "ocr_failed": "images.analysis.state_issues",
        }
        for key, label in self._summary_labels.items():
            count = max(0, int(counts.get(key, 0)))
            label.setProperty("count", count)
            label.setText(t(labels[key], count=count))

    def stop_polling(self) -> None:
        self._timer.stop()
        self._auto_retry_timer.stop()
