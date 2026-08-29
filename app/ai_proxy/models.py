from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AiProxyResponse:
    result: Any
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    provider_response_id: str = ""
    stale_chain_retry: bool = False


FORBIDDEN_CLIENT_FIELDS = (
    "user_id",
    "plan",
    "account_status",
    "ai_allowed",
    "budget",
    "used",
    "reserved",
    "actual_cost",
    "model",
    "endpoint",
    "raw_url",
    "headers",
    "api_key",
    "url",
    "authorization",
)
