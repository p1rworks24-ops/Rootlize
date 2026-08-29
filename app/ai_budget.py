"""Shared pre-request gate for API budget / quota.

Product code must call ``check_ai_budget`` immediately before an outbound
AI HTTP request. After the request, call ``finalize_ai_usage`` on success
or ``release_ai_reservation`` on failure.

The default gate allows every request (tests and unsigned tooling).
The packaged app installs ``CloudAiBudgetGate``, which reserves against
the Supabase budget via BudgetService.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

OPERATION_FACTS_GENERATE = "facts_generate"
OPERATION_MEANING_SEARCH = "meaning_search"
OPERATION_ACT_PLAN = "act_plan"
OPERATION_OTHER = "other"
KIND_VISION = "vision"
KIND_TEXT_LLM = "text_llm"


class AiBudgetExceeded(Exception):
    """Raised when a configured budget gate refuses an API request."""

    def __init__(
        self,
        message: str = "",
        *,
        reason: str = "limit_reached",
        reset_at: date | None = None,
        message_key: str = "",
        status: int = 0,
    ) -> None:
        self.reason = reason
        self.reset_at = reset_at
        self.message_key = message_key
        self.status = int(status or 0)
        super().__init__(message or message_key or reason)


class AiBudgetUnavailable(AiBudgetExceeded):
    """Cloud budget could not be verified. AI is unavailable; local is not."""

    def __init__(self, message: str = "", *, reset_at: date | None = None) -> None:
        super().__init__(message, reason="unavailable", reset_at=reset_at)


@dataclass(frozen=True)
class AiRequestIntent:
    """Non-PII description of the API request about to be sent."""

    operation: str
    kind: str
    model: str = ""
    request_count: int = 1


class AiBudgetGate:
    def allow(self, intent: AiRequestIntent) -> None:
        """Raise ``AiBudgetExceeded`` to block the request. Default allows."""


class AllowAllAiBudgetGate(AiBudgetGate):
    def allow(self, intent: AiRequestIntent) -> None:
        del intent


_gate: AiBudgetGate = AllowAllAiBudgetGate()
_reservations = threading.local()


def _reservation_stack() -> list[Any]:
    stack = getattr(_reservations, "items", None)
    if stack is None:
        stack = []
        _reservations.items = stack
    return stack


def push_budget_reservation(reservation: Any) -> None:
    _reservation_stack().append(reservation)


def pop_budget_reservation() -> Any | None:
    stack = _reservation_stack()
    return stack.pop() if stack else None


def peek_budget_reservation() -> Any | None:
    stack = _reservation_stack()
    return stack[-1] if stack else None


def get_ai_budget_gate() -> AiBudgetGate:
    return _gate


def set_ai_budget_gate(gate: AiBudgetGate | None) -> None:
    global _gate
    _gate = gate if gate is not None else AllowAllAiBudgetGate()


def reset_ai_budget_gate_for_tests() -> None:
    set_ai_budget_gate(None)
    _reservation_stack().clear()


def check_ai_budget(intent: AiRequestIntent) -> None:
    """Run the active gate. Call immediately before the HTTP request."""
    _gate.allow(intent)


def finalize_ai_usage(
    *,
    actual_cost_micros: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    usage: dict | None = None,
    model: str = "",
    kind: str = "",
) -> None:
    """Settle the reservation opened by the last ``check_ai_budget`` on this thread."""
    reservation = pop_budget_reservation()
    if reservation is None:
        return
    closer = getattr(_gate, "finalize", None)
    if closer is None:
        return
    try:
        closer(
            reservation,
            actual_cost_micros=actual_cost_micros,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage=usage,
            model=model,
            kind=kind,
        )
    except Exception:
        push_budget_reservation(reservation)
        raise


def release_ai_reservation() -> None:
    """Release the reservation opened by the last ``check_ai_budget`` on this thread."""
    reservation = pop_budget_reservation()
    if reservation is None:
        return
    closer = getattr(_gate, "release", None)
    if closer is None:
        return
    try:
        closer(reservation)
    except Exception:
        push_budget_reservation(reservation)
        raise


def format_budget_user_message(exc: AiBudgetExceeded) -> str:
    from app.i18n import t

    if exc.reason == "unavailable":
        return t("account.ai.verification_unavailable")
    if exc.reason == "not_authenticated":
        if int(getattr(exc, "status", 0) or 0) == 401:
            return t("account.ai.session_expired")
        return t("account.ai.sign_in_required")
    if exc.reason == "inactive":
        return t("account.ai.inactive")
    if exc.reason == "not_allowed":
        return t("account.ai.disabled")
    return f"{t('account.ai.limit_reached')}\n{t('account.ai.limit_reached_body')}"


def format_ai_user_message(error: BaseException) -> str:
    from app.ai_proxy.errors import AiProxyError
    from app.i18n import t
    from app.relevance.provider import RelevanceProviderError

    if isinstance(error, AiBudgetExceeded):
        return format_budget_user_message(error)
    if isinstance(error, AiProxyError):
        if error.code == "unauthenticated":
            if int(error.status or 0) == 401:
                return t("account.ai.session_expired")
            return t("account.ai.sign_in_required")
        return t(error.message_key)
    if isinstance(error, RelevanceProviderError) and "OPENAI_API_KEY" in str(error):
        return t("images.ai.temporarily_unavailable")
    return t("images.ai.temporarily_unavailable")
