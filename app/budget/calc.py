"""Period and percent math. No I/O. Does not enforce cloud quota."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.budget.models import AIUsageStatus


def utc_month_bounds(when: datetime | None = None) -> tuple[date, date]:
    """UTC calendar month: 2026-08-01 → 2026-09-01."""
    stamp = when or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    else:
        stamp = stamp.astimezone(timezone.utc)
    start = date(stamp.year, stamp.month, 1)
    if stamp.month == 12:
        end = date(stamp.year + 1, 1, 1)
    else:
        end = date(stamp.year, stamp.month + 1, 1)
    return start, end


def usage_status(
    *,
    budget_micros: int,
    used_micros: int,
    reserved_micros: int = 0,
    reset_at: date | None = None,
    ai_allowed: bool = True,
    account_status: str = "active",
    plan: str = "",
) -> AIUsageStatus:
    budget = max(0, int(budget_micros))
    used = max(0, int(used_micros))
    reserved = max(0, int(reserved_micros))
    committed = used + reserved
    if budget <= 0:
        used_percent = 100.0
        remaining_percent = 0.0
        reached = True
    else:
        used_percent = min(100.0, committed * 100.0 / budget)
        remaining_percent = max(0.0, 100.0 - used_percent)
        reached = committed >= budget
    if (not ai_allowed) or account_status != "active":
        reached = True
    return AIUsageStatus(
        used_percent=used_percent,
        remaining_percent=remaining_percent,
        reset_at=reset_at,
        limit_reached=reached,
        budget_micros=budget,
        used_micros=used,
        reserved_micros=reserved,
        plan=plan,
        account_status=account_status,
        ai_allowed=ai_allowed,
    )


def can_reserve(status: AIUsageStatus, estimated_cost_micros: int) -> bool:
    if status.unavailable or not status.ai_allowed or status.account_status != "active":
        return False
    if status.budget_micros <= 0:
        return False
    estimated = max(0, int(estimated_cost_micros))
    return status.used_micros + status.reserved_micros + estimated <= status.budget_micros
