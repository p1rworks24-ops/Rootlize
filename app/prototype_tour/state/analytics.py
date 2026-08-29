"""Prototype funnel events. Event name + time only. No query/image/path/facts."""

from __future__ import annotations

import json
from pathlib import Path

from app.paths import ensure_dir, get_local_app_data_dir
from app.prototype_tour.models import (
    ALLOWED_ANALYTICS_EVENTS,
    LEGACY_ANALYTICS_EVENTS,
    AnalyticsEvent,
)
from app.prototype_tour.state.store import utc_now

ANALYTICS_FILENAME = "prototype-analytics.jsonl"


def prototype_analytics_path() -> Path:
    return get_local_app_data_dir() / ANALYTICS_FILENAME


class TourAnalytics:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else prototype_analytics_path()
        self.events: list[AnalyticsEvent] = []

    def record(
        self,
        event_name: str,
        *,
        session_id: str,
        user_id: str = "",
        occurred_at: str = "",
    ) -> AnalyticsEvent | None:
        name = LEGACY_ANALYTICS_EVENTS.get(str(event_name or "").strip(), str(event_name or "").strip())
        if name not in ALLOWED_ANALYTICS_EVENTS:
            return None
        event = AnalyticsEvent(
            event_name=name,
            occurred_at=occurred_at or utc_now(),
            session_id=str(session_id or ""),
            user_id=str(user_id or ""),
        )
        self.events.append(event)
        self._append(event)
        return event

    def _append(self, event: AnalyticsEvent) -> None:
        ensure_dir(self.path.parent)
        line = json.dumps(
            {
                "event_name": event.event_name,
                "occurred_at": event.occurred_at,
                "prototype_session_id": event.session_id,
                "user_id": event.user_id,
            },
            ensure_ascii=True,
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
