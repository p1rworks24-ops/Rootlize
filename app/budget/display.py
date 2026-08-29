"""User-facing budget copy. Percents and reset dates only — never USD."""

from __future__ import annotations

from datetime import date, datetime

from app.i18n import get_locale


def format_reset_date(reset_at: date | datetime | None, locale: str = "") -> str:
    if reset_at is None:
        return ""
    day = reset_at.date() if isinstance(reset_at, datetime) else reset_at
    loc = locale or get_locale()
    if loc == "ja":
        return f"{day.month}月{day.day}日"
    return f"{day.strftime('%b')} {day.day}"
