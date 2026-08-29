"""Proxy failures mapped to Capixe user-facing codes. No provider text."""

from __future__ import annotations

from urllib.error import HTTPError, URLError

from app.ai_budget import AiBudgetExceeded, AiBudgetUnavailable

UNAUTHENTICATED = "unauthenticated"
ACCOUNT_INACTIVE = "account_inactive"
AI_DISABLED = "ai_disabled"
BUDGET_UNAVAILABLE = "budget_unavailable"
BUDGET_EXCEEDED = "budget_exceeded"
INVALID_OPERATION = "invalid_operation"
INVALID_PAYLOAD = "invalid_payload"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_RATE_LIMITED = "provider_rate_limited"
PROVIDER_TIMEOUT = "provider_timeout"
PROVIDER_REJECTED = "provider_rejected"
PROXY_INTERNAL_ERROR = "proxy_internal_error"

KNOWN_CODES = (
    UNAUTHENTICATED,
    ACCOUNT_INACTIVE,
    AI_DISABLED,
    BUDGET_UNAVAILABLE,
    BUDGET_EXCEEDED,
    INVALID_OPERATION,
    INVALID_PAYLOAD,
    PROVIDER_UNAVAILABLE,
    PROVIDER_RATE_LIMITED,
    PROVIDER_TIMEOUT,
    PROVIDER_REJECTED,
    PROXY_INTERNAL_ERROR,
)

FAILURE_AUTH = "auth"
FAILURE_NETWORK = "network"
FAILURE_PROVIDER = "provider"
FAILURE_RATE_LIMIT = "rate_limit"
FAILURE_CONVERSATION_STATE = "conversation_state"
FAILURE_SCHEMA = "schema"
FAILURE_VALIDATION = "validation"
FAILURE_BUDGET = "budget"
FAILURE_UNKNOWN = "unknown"

FAILURE_CATEGORIES = (
    FAILURE_AUTH,
    FAILURE_NETWORK,
    FAILURE_PROVIDER,
    FAILURE_RATE_LIMIT,
    FAILURE_CONVERSATION_STATE,
    FAILURE_SCHEMA,
    FAILURE_VALIDATION,
    FAILURE_BUDGET,
    FAILURE_UNKNOWN,
)

_MESSAGE_KEYS = {
    UNAUTHENTICATED: "account.ai.sign_in_required",
    ACCOUNT_INACTIVE: "account.ai.inactive",
    AI_DISABLED: "account.ai.disabled",
    BUDGET_UNAVAILABLE: "account.ai.verification_unavailable",
    BUDGET_EXCEEDED: "account.ai.limit_reached",
    INVALID_OPERATION: "images.ai.temporarily_unavailable",
    INVALID_PAYLOAD: "images.ai.temporarily_unavailable",
    PROVIDER_UNAVAILABLE: "images.ai.temporarily_unavailable",
    PROVIDER_RATE_LIMITED: "images.ai.temporarily_unavailable",
    PROVIDER_TIMEOUT: "images.ai.temporarily_unavailable",
    PROVIDER_REJECTED: "images.ai.temporarily_unavailable",
    PROXY_INTERNAL_ERROR: "images.ai.temporarily_unavailable",
}


class AiProxyError(Exception):
    def __init__(
        self,
        code: str = PROXY_INTERNAL_ERROR,
        *,
        reset_at: str = "",
        status: int = 0,
        stale_chain_retry: bool = False,
        retry_attempted: bool = False,
        auth_retry: bool = False,
    ) -> None:
        normalized = code if code in KNOWN_CODES else PROXY_INTERNAL_ERROR
        self.code = normalized
        self.reset_at = reset_at
        self.status = status
        self.stale_chain_retry = bool(stale_chain_retry)
        self.retry_attempted = bool(retry_attempted)
        self.auth_retry = bool(auth_retry)
        self.message_key = _MESSAGE_KEYS[normalized]
        super().__init__(self.message_key)


def describe_ai_failure(
    exc: BaseException,
    *,
    operation: str = "",
    configured: bool | None = None,
    authenticated: bool | None = None,
    facts_needed: int | None = None,
    facts_generated: int | None = None,
    facts_failed: int | None = None,
    facts_shortlist: int | None = None,
) -> str:
    """Safe job-failure fields. Never include tokens, keys, images, or query/facts text."""
    from app.ai_budget import AiBudgetExceeded

    proxy_code = "-"
    status = 0
    if isinstance(exc, AiProxyError):
        proxy_code = exc.code or "-"
        status = int(exc.status or 0)
    elif isinstance(exc, AiBudgetExceeded):
        proxy_code = exc.reason or "-"
        status = int(getattr(exc, "status", 0) or 0)
    parts = [
        f"error_class={type(exc).__name__}",
        f"proxy_code={proxy_code}",
        f"http_status={status}",
        f"operation={operation or '-'}",
    ]
    if configured is not None:
        parts.append(f"configured={bool(configured)}")
    if authenticated is not None:
        parts.append(f"authenticated={bool(authenticated)}")
    if facts_needed is not None:
        parts.append(f"facts_needed={int(facts_needed)}")
    if facts_generated is not None:
        parts.append(f"facts_generated={int(facts_generated)}")
    if facts_failed is not None:
        parts.append(f"facts_failed={int(facts_failed)}")
    if facts_shortlist is not None:
        parts.append(f"facts_shortlist={int(facts_shortlist)}")
    return " ".join(parts)


def classify_ask_ai_failure(
    error: BaseException | None,
    *,
    stale_chain_retry: bool = False,
) -> str:
    """Stable diagnostic category. Never derived from user text."""
    if error is None:
        return ""
    if isinstance(error, TimeoutError):
        return FAILURE_NETWORK
    if isinstance(error, URLError):
        return FAILURE_NETWORK
    if isinstance(error, OSError) and not isinstance(error, HTTPError):
        return FAILURE_NETWORK
    if isinstance(error, AiBudgetExceeded):
        if error.reason == "not_authenticated":
            return FAILURE_AUTH
        return FAILURE_BUDGET
    if isinstance(error, AiProxyError):
        code = error.code
        stale = stale_chain_retry or bool(getattr(error, "stale_chain_retry", False))
        if code == UNAUTHENTICATED:
            return FAILURE_AUTH
        if code in {BUDGET_EXCEEDED, BUDGET_UNAVAILABLE, ACCOUNT_INACTIVE, AI_DISABLED}:
            return FAILURE_BUDGET
        if code == PROVIDER_RATE_LIMITED:
            return FAILURE_RATE_LIMIT
        if code == PROVIDER_TIMEOUT:
            return FAILURE_NETWORK
        if code == INVALID_PAYLOAD:
            return FAILURE_SCHEMA
        if code == PROVIDER_REJECTED:
            return FAILURE_CONVERSATION_STATE if stale else FAILURE_PROVIDER
        if code in {PROVIDER_UNAVAILABLE, PROXY_INTERNAL_ERROR}:
            return FAILURE_PROVIDER
        if stale:
            return FAILURE_CONVERSATION_STATE
        return FAILURE_UNKNOWN
    if stale_chain_retry:
        return FAILURE_CONVERSATION_STATE
    return FAILURE_UNKNOWN


def log_ask_ai_turn(
    *,
    request_id: str = "",
    operation: str = "act_plan",
    stage: str = "",
    category: str = "",
    http_status: int = 0,
    proxy_code: str = "-",
    retry_attempted: bool = False,
    previous_response_id_present: bool = False,
    stale_chain_retry: bool = False,
    auth_retry: bool = False,
    structured_output: bool | None = None,
    schema_valid: bool | None = None,
    elapsed_ms: int | None = None,
) -> None:
    """Privacy-safe Ask AI turn trace. Never logs query, path, facts, or tokens."""
    from app.utils.logger import setup_logger

    parts = [
        f"Ask-AI turn request_id={request_id or '-'}",
        f"operation={operation or '-'}",
        f"stage={stage or '-'}",
        f"category={category or '-'}",
        f"http_status={int(http_status or 0)}",
        f"proxy_code={proxy_code or '-'}",
        f"retry_attempted={bool(retry_attempted)}",
        f"previous_response_id_present={bool(previous_response_id_present)}",
        f"stale_chain_retry={bool(stale_chain_retry)}",
        f"auth_retry={bool(auth_retry)}",
    ]
    if structured_output is not None:
        parts.append(f"structured_output={bool(structured_output)}")
    if schema_valid is not None:
        parts.append(f"schema_valid={bool(schema_valid)}")
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={int(elapsed_ms)}")
    setup_logger().info(" ".join(parts))


def proxy_runtime_flags() -> tuple[bool | None, bool | None]:
    """configured / authenticated only. Never tokens or keys."""
    try:
        from app.ai_proxy.client import get_ai_proxy_client

        client = get_ai_proxy_client()
    except Exception:
        return None, None
    if client is None:
        return None, None
    configured = bool(getattr(getattr(client, "_config", None), "configured", False))
    session = getattr(getattr(client, "_auth", None), "session", None)
    authenticated = bool(getattr(session, "is_authenticated", False))
    return configured, authenticated


def code_from_http(status: int, payload: dict | None) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or "")
            if code in KNOWN_CODES:
                return code
        code = str(payload.get("code") or "")
        if code in KNOWN_CODES:
            return code
    if status == 401:
        return UNAUTHENTICATED
    if status == 403:
        return AI_DISABLED
    if status == 429:
        return BUDGET_EXCEEDED
    if status == 408 or status == 504:
        return PROVIDER_TIMEOUT
    if status >= 500:
        return PROVIDER_UNAVAILABLE
    if status >= 400:
        return INVALID_PAYLOAD
    return PROXY_INTERNAL_ERROR


def as_budget_error(exc: AiProxyError) -> AiBudgetExceeded | None:
    if exc.code == UNAUTHENTICATED:
        return AiBudgetExceeded(reason="not_authenticated", status=exc.status)
    if exc.code == BUDGET_UNAVAILABLE:
        return AiBudgetUnavailable()
    if exc.code in {BUDGET_EXCEEDED, ACCOUNT_INACTIVE, AI_DISABLED}:
        reset = None
        if exc.reset_at:
            from app.budget.models import _as_date

            reset = _as_date(exc.reset_at)
        reason = "inactive" if exc.code == ACCOUNT_INACTIVE else (
            "not_allowed" if exc.code == AI_DISABLED else "limit_reached"
        )
        return AiBudgetExceeded(reason=reason, reset_at=reset, status=exc.status)
    return None
