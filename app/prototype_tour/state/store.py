"""Local prototype-tour state. Not mixed with the image / OCR database."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.paths import ensure_dir, get_local_app_data_dir
from app.prototype_tour.models import (
    LEGACY_STEP_IDS,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_SKIPPED,
    STEP_AI_ACTION,
    STEP_AI_CONSENT,
    STEP_AI_DONE,
    STEP_AI_IMAGES_RETURN,
    STEP_AI_INTRO,
    STEP_AI_PREP,
    STEP_AI_PREVIEW,
    STEP_AI_RESULT,
    STEP_AI_TAG,
    STEP_ASK_AI_OPEN,
    STEP_AUTOMATE,
    STEP_AUTOMATE_IMAGES_RETURN,
    STEP_AUTOMATE_INTRO,
    STEP_AUTOMATE_NAV,
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_CHAPTER1_DONE,
    STEP_CHAPTER2_DONE,
    STEP_COMPLETE,
    STEP_FEEDBACK,
    STEP_FOLDER,
    STEP_IDLE,
    STEP_IMAGES_GUIDE,
    STEP_LOCAL_PREP,
    STEP_MEANING_CONFIRM,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    STEP_THANKS,
    TUTORIAL_AI,
    TUTORIAL_AUTOMATION,
    TUTORIAL_CORE,
    TourRecord,
    TourStatus,
)

STORE_FILENAME = "prototype-tour.json"
_VALID_STATUS = {
    STATUS_NOT_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_SKIPPED,
}

_CORE_STEPS = {STEP_FOLDER, STEP_LOCAL_PREP, STEP_IMAGES_GUIDE}
_AI_STEPS = {
    STEP_ASK_AI_OPEN,
    STEP_AI_INTRO,
    STEP_AI_CONSENT,
    STEP_AI_PREP,
    STEP_MEANING_EXPLAIN,
    STEP_MEANING_SEARCH,
    STEP_MEANING_CONFIRM,
    STEP_AI_ACTION,
    STEP_AI_TAG,
    STEP_AI_PREVIEW,
    STEP_AI_DONE,
    STEP_AI_IMAGES_RETURN,
    STEP_AI_RESULT,
}
_AUTOMATION_STEPS = {
    STEP_AUTOMATE_PAGE,
    STEP_AUTOMATE,
    STEP_AUTOMATE_SAVE_CONFIRM,
    STEP_AUTOMATE_RUN,
    STEP_AUTOMATE_IMAGES_RETURN,
}
_LEGACY_AI_DONE = {
    STEP_AI_IMAGES_RETURN,
    STEP_CHAPTER2_DONE,
    STEP_AUTOMATE_INTRO,
    STEP_AUTOMATE_NAV,
}
_LEGACY_AUTOMATION_DONE = {
    STEP_AUTOMATE_IMAGES_RETURN,
    STEP_COMPLETE,
    STEP_FEEDBACK,
    STEP_THANKS,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def prototype_tour_path() -> Path:
    return get_local_app_data_dir() / STORE_FILENAME


def new_session_id() -> str:
    return str(uuid.uuid4())


def _status(value: object) -> TourStatus:
    text = str(value or "")
    if text in _VALID_STATUS:
        return text  # type: ignore[return-value]
    return STATUS_NOT_STARTED


def retire_ask_ai_tutorial(raw: dict) -> dict:
    """Collapse a leftover long Ask AI tour onto the first-open intro."""
    if not isinstance(raw, dict):
        return {}
    migrated = dict(raw)
    if _status(migrated.get("ai_status")) == STATUS_IN_PROGRESS:
        step = str(migrated.get("ai_step") or STEP_IDLE)
        if step not in {STEP_AI_INTRO, STEP_IDLE}:
            migrated["ai_step"] = STEP_AI_INTRO
    return migrated


def migrate_legacy_record(raw: dict) -> dict:
    """Map a one-track tour file onto independent Core / AI / Automation states."""
    if not isinstance(raw, dict):
        return {}
    if "ai_status" in raw or "automation_status" in raw:
        return retire_ask_ai_tutorial(dict(raw))
    status = _status(raw.get("status"))
    original = str(raw.get("current_step") or STEP_IDLE)
    step = LEGACY_STEP_IDS.get(original, original)
    migrated = dict(raw)
    migrated["ai_status"] = STATUS_NOT_STARTED
    migrated["ai_step"] = STEP_IDLE
    migrated["automation_status"] = STATUS_NOT_STARTED
    migrated["automation_step"] = STEP_IDLE
    if status == STATUS_COMPLETED:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_COMPLETED
        migrated["automation_status"] = STATUS_COMPLETED
        return retire_ask_ai_tutorial(migrated)
    if status == STATUS_SKIPPED:
        migrated["status"] = STATUS_SKIPPED
        migrated["current_step"] = STEP_IDLE
        return retire_ask_ai_tutorial(migrated)
    if status != STATUS_IN_PROGRESS:
        migrated["status"] = STATUS_NOT_STARTED
        migrated["current_step"] = STEP_IDLE
        return retire_ask_ai_tutorial(migrated)
    if original in {STEP_ASK_AI_OPEN, STEP_CHAPTER1_DONE}:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_NOT_STARTED
        return retire_ask_ai_tutorial(migrated)
    if original in _LEGACY_AI_DONE:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_COMPLETED
        migrated["ai_step"] = STEP_IDLE
        return retire_ask_ai_tutorial(migrated)
    if original in _LEGACY_AUTOMATION_DONE:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_COMPLETED
        migrated["automation_status"] = STATUS_COMPLETED
        return retire_ask_ai_tutorial(migrated)
    if step in _CORE_STEPS:
        migrated["status"] = STATUS_IN_PROGRESS
        migrated["current_step"] = step
        return retire_ask_ai_tutorial(migrated)
    if step in _AI_STEPS:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_IN_PROGRESS
        migrated["ai_step"] = step
        return retire_ask_ai_tutorial(migrated)
    if step in _AUTOMATION_STEPS:
        migrated["status"] = STATUS_COMPLETED
        migrated["current_step"] = STEP_IDLE
        migrated["ai_status"] = STATUS_COMPLETED
        migrated["automation_status"] = STATUS_IN_PROGRESS
        migrated["automation_step"] = step
        return retire_ask_ai_tutorial(migrated)
    migrated["status"] = STATUS_IN_PROGRESS
    migrated["current_step"] = STEP_FOLDER
    return retire_ask_ai_tutorial(migrated)


class TourStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else prototype_tour_path()
        self.record = self._load()

    def _load(self) -> TourRecord:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return TourRecord(session_id=new_session_id())
        if not isinstance(raw, dict):
            return TourRecord(session_id=new_session_id())
        already_split = "ai_status" in raw or "automation_status" in raw
        original_ai = str(raw.get("ai_status") or "")
        raw = migrate_legacy_record(raw)
        self.record = TourRecord(
            status=_status(raw.get("status")),
            session_id=str(raw.get("session_id") or new_session_id()),
            current_step=str(raw.get("current_step") or STEP_IDLE),
            welcome_seen=bool(raw.get("welcome_seen", False)),
            signed_in_offer_done=bool(raw.get("signed_in_offer_done", False)),
            started_at=str(raw.get("started_at") or ""),
            completed_at=str(raw.get("completed_at") or ""),
            skipped_at=str(raw.get("skipped_at") or ""),
            ai_calls=max(0, int(raw.get("ai_calls") or 0)),
            ai_route=str(raw.get("ai_route") or ""),
            ai_prep_started=bool(raw.get("ai_prep_started", False)),
            ai_status=_status(raw.get("ai_status")),
            ai_step=str(raw.get("ai_step") or STEP_IDLE),
            automation_status=_status(raw.get("automation_status")),
            automation_step=str(raw.get("automation_step") or STEP_IDLE),
            feedback_offered=bool(raw.get("feedback_offered", False)),
        )
        if (not already_split) or original_ai != str(raw.get("ai_status") or ""):
            self.save()
        return self.record

    def save(self) -> None:
        ensure_dir(self.path.parent)
        payload = {
            "status": self.record.status,
            "session_id": self.record.session_id,
            "current_step": self.record.current_step,
            "welcome_seen": self.record.welcome_seen,
            "signed_in_offer_done": self.record.signed_in_offer_done,
            "started_at": self.record.started_at,
            "completed_at": self.record.completed_at,
            "skipped_at": self.record.skipped_at,
            "ai_calls": self.record.ai_calls,
            "ai_route": self.record.ai_route,
            "ai_prep_started": self.record.ai_prep_started,
            "ai_status": self.record.ai_status,
            "ai_step": self.record.ai_step,
            "automation_status": self.record.automation_status,
            "automation_step": self.record.automation_step,
            "feedback_offered": self.record.feedback_offered,
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    @property
    def status(self) -> TourStatus:
        return self.record.status

    def should_auto_start(self) -> bool:
        return self.record.status == STATUS_NOT_STARTED

    def has_in_progress(self) -> bool:
        return (
            self.record.status == STATUS_IN_PROGRESS
            or self.record.ai_status == STATUS_IN_PROGRESS
            or self.record.automation_status == STATUS_IN_PROGRESS
        )

    def mark_welcome_seen(self) -> None:
        self.record.welcome_seen = True
        self.save()

    def mark_signed_in_offer_done(self) -> None:
        self.record.signed_in_offer_done = True
        self.save()

    def mark_feedback_offered(self) -> None:
        self.record.feedback_offered = True
        self.save()

    def start(self, step: str) -> None:
        self.start_core(step)

    def start_core(self, step: str) -> None:
        if not self.record.session_id:
            self.record.session_id = new_session_id()
        self.record.status = STATUS_IN_PROGRESS
        self.record.current_step = step
        self.record.started_at = self.record.started_at or utc_now()
        self.record.welcome_seen = True
        self.save()

    def start_ai(self, step: str) -> None:
        if not self.record.session_id:
            self.record.session_id = new_session_id()
        self.record.ai_status = STATUS_IN_PROGRESS
        self.record.ai_step = step
        self.record.ai_prep_started = False
        self.save()

    def start_automation(self, step: str) -> None:
        if not self.record.session_id:
            self.record.session_id = new_session_id()
        self.record.automation_status = STATUS_IN_PROGRESS
        self.record.automation_step = step
        self.save()

    def set_step(self, step: str, tutorial: str = TUTORIAL_CORE) -> None:
        if tutorial == TUTORIAL_AI:
            self.record.ai_step = step
            if self.record.ai_status == STATUS_NOT_STARTED:
                self.record.ai_status = STATUS_IN_PROGRESS
        elif tutorial == TUTORIAL_AUTOMATION:
            self.record.automation_step = step
            if self.record.automation_status == STATUS_NOT_STARTED:
                self.record.automation_status = STATUS_IN_PROGRESS
        else:
            self.record.current_step = step
            if self.record.status == STATUS_NOT_STARTED:
                self.record.status = STATUS_IN_PROGRESS
                self.record.started_at = self.record.started_at or utc_now()
        self.save()

    def complete(self) -> None:
        self.complete_core()

    def complete_core(self) -> None:
        self.record.status = STATUS_COMPLETED
        self.record.current_step = STEP_IDLE
        self.record.completed_at = utc_now()
        self.save()

    def complete_ai(self) -> None:
        self.record.ai_status = STATUS_COMPLETED
        self.record.ai_step = STEP_IDLE
        self.save()

    def complete_automation(self) -> None:
        self.record.automation_status = STATUS_COMPLETED
        self.record.automation_step = STEP_IDLE
        self.save()

    def skip(self) -> None:
        self.skip_core()

    def skip_core(self) -> None:
        self.record.status = STATUS_SKIPPED
        self.record.current_step = STEP_IDLE
        self.record.skipped_at = utc_now()
        self.save()

    def skip_ai(self) -> None:
        self.record.ai_status = STATUS_SKIPPED
        self.record.ai_step = STEP_IDLE
        self.save()

    def skip_automation(self) -> None:
        self.record.automation_status = STATUS_SKIPPED
        self.record.automation_step = STEP_IDLE
        self.save()

    def note_ai_call(self) -> None:
        self.record.ai_calls += 1
        self.save()

    def set_ai_route(self, route: str) -> None:
        self.record.ai_route = str(route or "")
        self.save()

    def set_ai_prep_started(self, started: bool = True) -> None:
        self.record.ai_prep_started = bool(started)
        self.save()

    def reset_core_for_replay(self) -> None:
        self.record.status = STATUS_NOT_STARTED
        self.record.current_step = STEP_IDLE
        self.record.started_at = ""
        self.record.completed_at = ""
        self.record.skipped_at = ""
        self.record.welcome_seen = False
        self.record.signed_in_offer_done = False
        self.save()

    def reset_ai_for_replay(self) -> None:
        self.record.ai_status = STATUS_NOT_STARTED
        self.record.ai_step = STEP_IDLE
        self.record.ai_prep_started = False
        self.save()

    def reset_automation_for_replay(self) -> None:
        self.record.automation_status = STATUS_NOT_STARTED
        self.record.automation_step = STEP_IDLE
        self.save()

    def reset_for_replay(self) -> None:
        session = new_session_id()
        calls = self.record.ai_calls
        self.record = TourRecord(session_id=session, ai_calls=calls)
        self.save()
