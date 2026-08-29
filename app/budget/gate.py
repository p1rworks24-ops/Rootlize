"""Cloud budget gate installed by the Account session."""

from __future__ import annotations

import uuid

from app.ai_budget import (
    AiBudgetExceeded,
    AiBudgetGate,
    AiBudgetUnavailable,
    AiRequestIntent,
    push_budget_reservation,
    set_ai_budget_gate,
)
from app.ai_proxy.config import use_direct_ai_provider
from app.auth.models import AuthStatus
from app.auth.service import AuthService
from app.budget.models import BudgetReservation
from app.budget.pricing import actual_cost_micros as compute_actual_cost_micros
from app.budget.pricing import estimate_cost_micros
from app.budget.service import BudgetService
from app.utils.logger import setup_logger

logger = setup_logger()


class CloudAiBudgetGate(AiBudgetGate):
    def __init__(self, auth: AuthService, budget: BudgetService) -> None:
        self._auth = auth
        self._budget = budget

    def allow(self, intent: AiRequestIntent) -> None:
        session = self._auth.session
        if not session.is_authenticated:
            raise AiBudgetExceeded(reason="not_authenticated")
        if session.status == AuthStatus.OFFLINE_SESSION:
            raise AiBudgetUnavailable()
        token = self._auth.bearer_token()
        if not token:
            raise AiBudgetUnavailable()
        if not use_direct_ai_provider():
            self._preflight(token)
            return
        reservation = self._budget.reserve(
            token,
            estimated_cost_micros=estimate_cost_micros(intent),
            operation=intent.operation,
            provider="openai",
            model=intent.model,
            request_id=uuid.uuid4().hex,
        )
        push_budget_reservation(reservation)

    def _preflight(self, token: str) -> None:
        status = self._budget.peek()
        if status is None or status.unavailable:
            status = self._budget.get_status(token)
        if status.unavailable:
            raise AiBudgetUnavailable(reset_at=status.reset_at)
        if status.account_status and status.account_status != "active":
            raise AiBudgetExceeded(reason="inactive", reset_at=status.reset_at)
        if not status.ai_allowed:
            raise AiBudgetExceeded(reason="not_allowed", reset_at=status.reset_at)
        if status.limit_reached:
            raise AiBudgetExceeded(reason="limit_reached", reset_at=status.reset_at)

    def finalize(
        self,
        reservation: BudgetReservation,
        *,
        actual_cost_micros: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usage: dict | None = None,
        model: str = "",
        kind: str = "",
    ) -> None:
        token = self._auth.bearer_token()
        cost = actual_cost_micros
        if cost is None:
            cost = compute_actual_cost_micros(
                model=model,
                kind=kind,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usage=usage,
            )
        try:
            self._budget.finalize(token, reservation.reservation_id, int(cost))
        except AiBudgetExceeded:
            logger.info("AI usage finalize denied after request.")

    def release(self, reservation: BudgetReservation) -> None:
        token = self._auth.bearer_token()
        try:
            self._budget.release(token, reservation.reservation_id)
        except AiBudgetExceeded:
            logger.info("AI usage release denied after request.")


def bind_cloud_budget_gate(auth: AuthService, budget: BudgetService) -> CloudAiBudgetGate:
    gate = CloudAiBudgetGate(auth, budget)
    set_ai_budget_gate(gate)
    return gate
