"""User-facing auth failures. Never carry raw provider exception text into UI."""

from __future__ import annotations

from app.auth.models import AuthErrorCode

_MESSAGE_KEYS = {
    AuthErrorCode.INVALID_CREDENTIALS: "account.error.invalid_credentials",
    AuthErrorCode.NOT_CONFIRMED: "account.error.not_confirmed",
    AuthErrorCode.NETWORK: "account.error.network",
    AuthErrorCode.RATE_LIMITED: "account.error.rate_limited",
    AuthErrorCode.CANCELLED: "account.error.cancelled",
    AuthErrorCode.INVALID_CALLBACK: "account.error.invalid_callback",
    AuthErrorCode.NOT_CONFIGURED: "account.error.not_configured",
    AuthErrorCode.UNKNOWN: "account.error.unknown",
}


class AuthError(Exception):
    def __init__(
        self,
        code: AuthErrorCode,
        *,
        message_key: str = "",
        detail: str = "",
        status: int = 0,
    ) -> None:
        self.code = code
        self.message_key = message_key or _MESSAGE_KEYS.get(code, "account.error.unknown")
        self.detail = detail
        self.status = status
        super().__init__(self.message_key)


def classify_auth_http_error(status: int, body: str) -> AuthErrorCode:
    text = (body or "").lower()
    if status in {0, 408} or "timed out" in text or "urlerror" in text:
        return AuthErrorCode.NETWORK
    if status in {429, 540}:
        return AuthErrorCode.RATE_LIMITED
    if status in {400, 401}:
        if "email not confirmed" in text or "not confirmed" in text:
            return AuthErrorCode.NOT_CONFIRMED
        if "invalid login" in text or "invalid_credentials" in text or "invalid email or password" in text:
            return AuthErrorCode.INVALID_CREDENTIALS
        if "email_not_confirmed" in text:
            return AuthErrorCode.NOT_CONFIRMED
    if "rate" in text and "limit" in text:
        return AuthErrorCode.RATE_LIMITED
    if "email not confirmed" in text or "email_not_confirmed" in text:
        return AuthErrorCode.NOT_CONFIRMED
    if "invalid login" in text or "invalid_credentials" in text:
        return AuthErrorCode.INVALID_CREDENTIALS
    return AuthErrorCode.UNKNOWN
