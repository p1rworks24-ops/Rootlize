"""Prototype feedback persist. Local first; optional Supabase. No library data."""

from __future__ import annotations

import json
from pathlib import Path

from app.branding import APP_VERSION
from app.paths import ensure_dir, get_local_app_data_dir
from app.prototype_tour.models import (
    EASIER_CHOICES,
    FEEDBACK_VERSION,
    LEGACY_MOST_USEFUL,
    MOST_USEFUL_CHOICES,
    PAYMENT_CHOICES,
    WOULD_USE_CHOICES,
    FeedbackPayload,
)
from app.prototype_tour.state.store import utc_now
from app.utils.logger import setup_logger

logger = setup_logger()

FEEDBACK_FILENAME = "prototype-feedback.jsonl"
_TEXT_LIMIT = 2000


def prototype_feedback_path() -> Path:
    return get_local_app_data_dir() / FEEDBACK_FILENAME


def _clean_choice(value: str, allowed: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    return text if text in allowed else ""


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:_TEXT_LIMIT]


def _first(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def build_feedback(
    *,
    session_id: str,
    most_useful: str = "",
    most_useful_step: str = "",
    would_use: str = "",
    easier_than_current: str = "",
    willingness_to_pay: str = "",
    payment_interest: str = "",
    confusing_text: str = "",
    confusing_feedback: str = "",
    feature_feedback: str = "",
    user_id: str = "",
    app_version: str = "",
    completed_at: str = "",
    feedback_version: str = "",
) -> FeedbackPayload:
    del feature_feedback
    useful = _first(most_useful, most_useful_step)
    return FeedbackPayload(
        prototype_session_id=str(session_id or ""),
        completed_at=completed_at or utc_now(),
        most_useful=_clean_choice(
            LEGACY_MOST_USEFUL.get(useful, useful),
            MOST_USEFUL_CHOICES,
        ),
        would_use=_clean_choice(would_use, WOULD_USE_CHOICES),
        easier_than_current=_clean_choice(easier_than_current, EASIER_CHOICES),
        willingness_to_pay=_clean_choice(
            _first(willingness_to_pay, payment_interest),
            PAYMENT_CHOICES,
        ),
        confusing_text=_clean_text(_first(confusing_text, confusing_feedback)),
        app_version=str(app_version or APP_VERSION),
        user_id=str(user_id or ""),
        feedback_version=str(feedback_version or FEEDBACK_VERSION),
    )


class FeedbackStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else prototype_feedback_path()
        self.entries: list[FeedbackPayload] = []

    def has_entries(self) -> bool:
        if self.entries:
            return True
        try:
            return self.path.is_file() and self.path.stat().st_size > 0
        except OSError:
            return False

    def save(self, payload: FeedbackPayload) -> FeedbackPayload:
        self.entries.append(payload)
        ensure_dir(self.path.parent)
        line = json.dumps(payload.public_fields(), ensure_ascii=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return payload
