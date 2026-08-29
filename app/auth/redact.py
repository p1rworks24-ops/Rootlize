"""Keep tokens and secrets out of logs."""

from __future__ import annotations

import re

_SECRET_KEYS = (
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "code_verifier",
    "code_challenge",
    "password",
    "apikey",
    "anon_key",
    "publishable_key",
    "service_role",
    "openai_api_key",
    "api_key",
)
_PATTERN = re.compile(
    r"(?i)(" + "|".join(re.escape(key) for key in _SECRET_KEYS) + r")(['\"]?\s*[:=]\s*)([^,\s&\"']+)"
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*")


def redact_secrets(text: str) -> str:
    value = str(text or "")
    value = _PATTERN.sub(r"\1\2[redacted]", value)
    value = _BEARER.sub("Bearer [redacted]", value)
    value = _JWT.sub("[redacted-jwt]", value)
    return value


def assert_no_secrets(text: str) -> None:
    lowered = (text or "").lower()
    if "bearer eyj" in lowered or "refresh_token=" in lowered:
        raise AssertionError("secret material must not appear in logs")
