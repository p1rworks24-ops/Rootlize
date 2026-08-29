"""AI budget domain types. UI never sees USD amounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


USD_MICROS = 1_000_000
WARNING_PERCENT = 80.0
CRITICAL_PERCENT = 95.0

REASON_LIMIT_REACHED = "limit_reached"
REASON_UNAVAILABLE = "unavailable"
REASON_NOT_AUTHENTICATED = "not_authenticated"
REASON_NOT_ALLOWED = "not_allowed"
REASON_INACTIVE = "inactive"


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: str
    reserved_micros: int


@dataclass(frozen=True)
class AIUsageStatus:
    used_percent: float = 0.0
    remaining_percent: float = 100.0
    reset_at: date | None = None
    limit_reached: bool = False
    budget_micros: int = 0
    used_micros: int = 0
    reserved_micros: int = 0
    unavailable: bool = False
    plan: str = ""
    account_status: str = "active"
    ai_allowed: bool = True

    @property
    def display_used_percent(self) -> int:
        if self.used_percent <= 0:
            return 0
        if self.used_percent >= 100:
            return 100
        return int(self.used_percent)

    @property
    def display_remaining_percent(self) -> int:
        return max(0, 100 - self.display_used_percent)

    @property
    def warning_level(self) -> str:
        if self.unavailable or self.limit_reached or self.used_percent >= 100:
            return "exhausted"
        if self.used_percent >= CRITICAL_PERCENT:
            return "critical"
        if self.used_percent >= WARNING_PERCENT:
            return "warning"
        return "normal"

    @classmethod
    def unavailable_status(cls, *, reset_at: date | None = None) -> AIUsageStatus:
        return cls(
            used_percent=0.0,
            remaining_percent=0.0,
            reset_at=reset_at,
            limit_reached=True,
            unavailable=True,
            ai_allowed=False,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AIUsageStatus:
        used = float(payload.get("used_percent") or 0)
        remaining = payload.get("remaining_percent")
        if remaining is None:
            remaining = max(0.0, 100.0 - used)
        return cls(
            used_percent=used,
            remaining_percent=float(remaining),
            reset_at=_as_date(payload.get("reset_at")),
            limit_reached=bool(payload.get("limit_reached")),
            budget_micros=int(payload.get("budget_micros") or 0),
            used_micros=int(payload.get("used_micros") or 0),
            reserved_micros=int(payload.get("reserved_micros") or 0),
            unavailable=bool(payload.get("unavailable")),
            plan=str(payload.get("plan") or ""),
            account_status=str(payload.get("account_status") or "active"),
            ai_allowed=bool(payload.get("ai_allowed", True)),
        )

    def to_cache(self) -> dict[str, Any]:
        return {
            "used_percent": self.used_percent,
            "remaining_percent": self.remaining_percent,
            "reset_at": self.reset_at.isoformat() if self.reset_at else "",
            "limit_reached": self.limit_reached,
            "budget_micros": self.budget_micros,
            "used_micros": self.used_micros,
            "reserved_micros": self.reserved_micros,
            "plan": self.plan,
            "account_status": self.account_status,
            "ai_allowed": self.ai_allowed,
        }
