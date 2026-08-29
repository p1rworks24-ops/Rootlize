"""In-memory reservation protocol used by tests.

Production enforcement is the Supabase SECURITY DEFINER functions.
This ledger mirrors that contract so reservation / period / plan-change
behavior can be tested without a live database.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.budget.calc import utc_month_bounds
from app.budget.models import AIUsageStatus, BudgetReservation
from app.budget.prototype import (
    HARD_CAP_MICROS,
    ONBOARDING_BUDGET_MICROS,
    REGULAR_MONTHLY_BUDGET_MICROS,
)
from app.ai_budget import AiBudgetExceeded

Clock = Callable[[], datetime]


class BudgetDenied(AiBudgetExceeded):
    """Ledger denial. Same type family as the product gate."""


@dataclass
class _Entitlement:
    plan: str = "free"
    account_status: str = "active"
    ai_allowed: bool = True
    ai_monthly_budget_micros: int = REGULAR_MONTHLY_BUDGET_MICROS
    ai_onboarding_budget_micros: int = ONBOARDING_BUDGET_MICROS
    ai_lifetime_hard_cap_micros: int = HARD_CAP_MICROS


@dataclass
class _Period:
    period_start: object
    period_end: object
    budget_micros: int
    used_micros: int = 0
    reserved_micros: int = 0


@dataclass
class _Lifetime:
    used_micros: int = 0
    reserved_micros: int = 0
    onboarding_used_micros: int = 0
    onboarding_reserved_micros: int = 0


@dataclass
class _Event:
    event_id: str
    user_id: str
    operation: str
    provider: str
    model: str
    reserved_micros: int
    onboarding_reserved_micros: int = 0
    regular_reserved_micros: int = 0
    status: str = "reserved"
    actual_micros: int | None = None
    request_id: str = ""


@dataclass
class InMemoryBudgetLedger:
    clock: Clock = field(default=lambda: datetime.now(timezone.utc))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    entitlements: dict[str, _Entitlement] = field(default_factory=dict)
    periods: dict[tuple[str, object], _Period] = field(default_factory=dict)
    lifetimes: dict[str, _Lifetime] = field(default_factory=dict)
    events: dict[str, _Event] = field(default_factory=dict)

    def set_entitlement(
        self,
        user_id: str,
        *,
        plan: str = "free",
        account_status: str = "active",
        ai_allowed: bool = True,
        ai_monthly_budget_micros: int,
        ai_onboarding_budget_micros: int | None = None,
        ai_lifetime_hard_cap_micros: int | None = None,
    ) -> None:
        with self._lock:
            self.entitlements[user_id] = _Entitlement(
                plan=plan,
                account_status=account_status,
                ai_allowed=ai_allowed,
                ai_monthly_budget_micros=int(ai_monthly_budget_micros),
                ai_onboarding_budget_micros=int(
                    ONBOARDING_BUDGET_MICROS
                    if ai_onboarding_budget_micros is None
                    else ai_onboarding_budget_micros
                ),
                ai_lifetime_hard_cap_micros=int(
                    HARD_CAP_MICROS
                    if ai_lifetime_hard_cap_micros is None
                    else ai_lifetime_hard_cap_micros
                ),
            )
            self.lifetimes.setdefault(user_id, _Lifetime())

    def _lifetime_unlocked(self, user_id: str) -> _Lifetime:
        lifetime = self.lifetimes.get(user_id)
        if lifetime is None:
            lifetime = _Lifetime()
            self.lifetimes[user_id] = lifetime
        return lifetime

    def _current_period_unlocked(self, user_id: str) -> _Period:
        start, end = utc_month_bounds(self.clock())
        key = (user_id, start)
        ent = self.entitlements[user_id]
        period = self.periods.get(key)
        if period is None:
            period = _Period(
                period_start=start,
                period_end=end,
                budget_micros=max(0, ent.ai_monthly_budget_micros),
            )
            self.periods[key] = period
        else:
            period.budget_micros = max(0, ent.ai_monthly_budget_micros)
        return period

    def status(self, user_id: str) -> AIUsageStatus:
        from app.budget.calc import usage_status

        with self._lock:
            ent = self.entitlements.get(user_id)
            if ent is None:
                raise BudgetDenied("ai_not_allowed", reason="not_allowed")
            lifetime = self._lifetime_unlocked(user_id)
            return usage_status(
                budget_micros=ent.ai_lifetime_hard_cap_micros,
                used_micros=lifetime.used_micros,
                reserved_micros=lifetime.reserved_micros,
                reset_at=None,
                ai_allowed=ent.ai_allowed,
                account_status=ent.account_status,
                plan=ent.plan,
            )

    def reserve(
        self,
        user_id: str,
        estimated_cost_micros: int,
        operation: str,
        *,
        provider: str = "",
        model: str = "",
        request_id: str = "",
    ) -> BudgetReservation:
        if not user_id:
            raise BudgetDenied("ai_not_authenticated", reason="not_authenticated")
        if estimated_cost_micros is None or int(estimated_cost_micros) < 0:
            raise BudgetDenied("ai_invalid_estimate", reason="not_allowed")
        estimated = int(estimated_cost_micros)
        with self._lock:
            ent = self.entitlements.get(user_id)
            if ent is None:
                raise BudgetDenied("ai_not_allowed", reason="not_allowed")
            if ent.account_status != "active":
                raise BudgetDenied("ai_account_inactive", reason="inactive")
            if not ent.ai_allowed:
                raise BudgetDenied("ai_not_allowed", reason="not_allowed")
            lifetime = self._lifetime_unlocked(user_id)
            period = self._current_period_unlocked(user_id)
            hard_cap = max(0, ent.ai_lifetime_hard_cap_micros)
            if hard_cap <= 0:
                raise BudgetDenied("ai_budget_exceeded", reason="limit_reached")
            lifetime_remaining = hard_cap - lifetime.used_micros - lifetime.reserved_micros
            onboarding_remaining = (
                max(0, ent.ai_onboarding_budget_micros)
                - lifetime.onboarding_used_micros
                - lifetime.onboarding_reserved_micros
            )
            regular_remaining = (
                max(0, ent.ai_monthly_budget_micros)
                - period.used_micros
                - period.reserved_micros
            )
            available = min(
                max(0, lifetime_remaining),
                max(0, onboarding_remaining) + max(0, regular_remaining),
            )
            if estimated > available:
                raise BudgetDenied("ai_budget_exceeded", reason="limit_reached")
            from_onboarding = min(estimated, max(0, onboarding_remaining))
            from_regular = estimated - from_onboarding
            lifetime.reserved_micros += estimated
            lifetime.onboarding_reserved_micros += from_onboarding
            period.reserved_micros += from_regular
            event_id = str(uuid.uuid4())
            self.events[event_id] = _Event(
                event_id=event_id,
                user_id=user_id,
                operation=operation or "other",
                provider=provider,
                model=model,
                reserved_micros=estimated,
                onboarding_reserved_micros=from_onboarding,
                regular_reserved_micros=from_regular,
                request_id=request_id,
            )
            return BudgetReservation(reservation_id=event_id, reserved_micros=estimated)

    def finalize(self, user_id: str, reservation_id: str, actual_cost_micros: int | None) -> dict:
        with self._lock:
            ev = self.events.get(reservation_id)
            if ev is None or ev.user_id != user_id:
                raise BudgetDenied("ai_reservation_not_found", reason="not_allowed")
            if ev.status == "finalized":
                return {"status": "finalized", "already": True, "actual_micros": ev.actual_micros}
            if ev.status == "released":
                return {"status": "released", "already": True}
            actual = ev.reserved_micros if actual_cost_micros is None or int(actual_cost_micros) < 0 else int(actual_cost_micros)
            lifetime = self._lifetime_unlocked(user_id)
            period = self._current_period_unlocked(user_id)
            onboarding_actual = min(actual, max(0, ev.onboarding_reserved_micros))
            regular_actual = actual - onboarding_actual
            lifetime.reserved_micros = max(0, lifetime.reserved_micros - ev.reserved_micros)
            lifetime.onboarding_reserved_micros = max(
                0, lifetime.onboarding_reserved_micros - ev.onboarding_reserved_micros
            )
            lifetime.used_micros += actual
            lifetime.onboarding_used_micros += onboarding_actual
            period.reserved_micros = max(0, period.reserved_micros - ev.regular_reserved_micros)
            period.used_micros += regular_actual
            ev.status = "finalized"
            ev.actual_micros = actual
            return {"status": "finalized", "already": False, "actual_micros": actual}

    def release(self, user_id: str, reservation_id: str) -> dict:
        with self._lock:
            ev = self.events.get(reservation_id)
            if ev is None or ev.user_id != user_id:
                raise BudgetDenied("ai_reservation_not_found", reason="not_allowed")
            if ev.status == "released":
                return {"status": "released", "already": True}
            if ev.status == "finalized":
                return {"status": "finalized", "already": True}
            lifetime = self._lifetime_unlocked(user_id)
            period = self._current_period_unlocked(user_id)
            lifetime.reserved_micros = max(0, lifetime.reserved_micros - ev.reserved_micros)
            lifetime.onboarding_reserved_micros = max(
                0, lifetime.onboarding_reserved_micros - ev.onboarding_reserved_micros
            )
            period.reserved_micros = max(0, period.reserved_micros - ev.regular_reserved_micros)
            ev.status = "released"
            ev.actual_micros = 0
            return {"status": "released", "already": False}
