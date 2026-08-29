"""urllib JSON client used only for Auth / entitlement metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.auth.errors import AuthError, AuthErrorCode, classify_auth_http_error
from app.auth.redact import redact_secrets
from app.utils.logger import setup_logger

logger = setup_logger()
TIMEOUT_SEC = 20
UrlOpen = Callable[..., object]


@dataclass
class HttpResponse:
    status: int
    body: str
    payload: dict | list | None


class AuthHttpClient:
    def __init__(self, *, urlopen_fn: UrlOpen | None = None) -> None:
        self._urlopen = urlopen_fn or urlopen

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> HttpResponse:
        data = None if json_body is None else json.dumps(json_body).encode("utf-8")
        request = Request(url, data=data, method=method.upper())
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if json_body is not None and "Content-Type" not in (headers or {}):
            request.add_header("Content-Type", "application/json")
        try:
            with self._urlopen(request, timeout=TIMEOUT_SEC) as response:
                raw = response.read().decode("utf-8")
                status = int(getattr(response, "status", 200) or 200)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.info("Auth HTTP %s failed status=%s", method, exc.code)
            raise AuthError(
                classify_auth_http_error(int(exc.code or 0), raw),
                detail=raw,
                status=int(exc.code or 0),
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            logger.info("Auth HTTP network failure: %s", type(exc).__name__)
            raise AuthError(AuthErrorCode.NETWORK) from None
        payload: dict | list | None = None
        if raw.strip():
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = None
            payload = decoded if isinstance(decoded, (dict, list)) else None
        return HttpResponse(status=status, body=redact_secrets(raw), payload=payload)
