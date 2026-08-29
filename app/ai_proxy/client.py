"""Authenticated AI proxy boundary. UI must not call Edge Functions directly."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai_proxy.config import functions_url, use_direct_ai_provider
from app.ai_proxy.errors import AiProxyError, as_budget_error, code_from_http
from app.ai_proxy.models import FORBIDDEN_CLIENT_FIELDS, AiProxyResponse
from app.auth.config import AuthClientConfig, load_auth_client_config_or_unconfigured
from app.auth.models import AuthStatus
from app.auth.service import AuthService
from app.budget.models import AIUsageStatus
from app.utils.logger import setup_logger

logger = setup_logger()
TIMEOUT_SEC = 120
UsageListener = Callable[[dict[str, Any]], None]

_client: AiProxyClient | None = None
_on_usage: UsageListener | None = None


def _strip_forbidden(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if str(key).lower() not in FORBIDDEN_CLIENT_FIELDS
    }


class AiProxyClient:
    def __init__(
        self,
        auth: AuthService,
        *,
        config: AuthClientConfig | None = None,
        timeout_seconds: float = TIMEOUT_SEC,
        urlopen_fn=None,
        on_usage: UsageListener | None = None,
    ) -> None:
        self._auth = auth
        if config is not None:
            self._config = config
        else:
            existing = getattr(auth, "client_config", None)
            self._config = (
                existing
                if isinstance(existing, AuthClientConfig)
                else load_auth_client_config_or_unconfigured()
            )
        self._timeout = timeout_seconds
        self._urlopen = urlopen_fn or urlopen
        self._on_usage = on_usage

    def invoke(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        request_id: str = "",
        _auth_retry: bool = False,
    ) -> AiProxyResponse:
        session = self._auth.session
        if not session.is_authenticated:
            expired = session.status == AuthStatus.SESSION_EXPIRED
            logger.info(
                "AI-proxy skipped operation=%s reason=%s configured=%s authenticated=False",
                operation,
                "session_expired" if expired else "unauthenticated",
                bool(self._config.configured),
            )
            raise AiProxyError("unauthenticated", status=401 if expired else 0)
        if session.status == AuthStatus.OFFLINE_SESSION:
            logger.info(
                "AI-proxy skipped operation=%s reason=offline_session configured=%s authenticated=True",
                operation,
                bool(self._config.configured),
            )
            raise AiProxyError("budget_unavailable")
        ensure = getattr(self._auth, "ensure_fresh_access_token", None)
        if callable(ensure) and not _auth_retry:
            token = ensure(force=False) or ""
        else:
            token = self._auth.bearer_token()
        if not token or not self._config.configured:
            session = self._auth.session
            expired = session.status == AuthStatus.SESSION_EXPIRED
            reason = "unauthenticated" if not token else "unconfigured"
            logger.info(
                "AI-proxy skipped operation=%s reason=%s configured=%s authenticated=%s",
                operation,
                "session_expired" if expired else reason,
                bool(self._config.configured),
                bool(token),
            )
            if not token:
                raise AiProxyError("unauthenticated", status=401 if expired else 0)
            raise AiProxyError("budget_unavailable")
        request_id = request_id or uuid.uuid4().hex
        body = {
            "operation": operation,
            "payload": _strip_forbidden(dict(payload or {})),
            "request_id": request_id,
        }
        url = functions_url(self._config.supabase_url)
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=raw,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": self._config.publishable_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        logger.info("AI-proxy request operation=%s request_id=%s", operation, request_id)
        try:
            with self._urlopen(request, timeout=self._timeout) as response:
                text = response.read().decode("utf-8")
                status = int(getattr(response, "status", 200) or 200)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            parsed = _parse_json(detail)
            code = code_from_http(int(exc.code or 0), parsed if isinstance(parsed, dict) else None)
            reset = ""
            stale_chain = False
            if isinstance(parsed, dict):
                error = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
                reset = str((error or {}).get("reset_at") or parsed.get("reset_at") or "")
                stale_chain = bool((error or {}).get("stale_chain_retry") or parsed.get("stale_chain_retry"))
            logger.info(
                "AI-proxy HTTP error operation=%s request_id=%s code=%s http_status=%s configured=True authenticated=True auth_retry=%s stale_chain_retry=%s",
                operation,
                request_id,
                code,
                int(exc.code or 0),
                bool(_auth_retry),
                stale_chain,
            )
            if int(exc.code or 0) == 401 and not _auth_retry and callable(ensure):
                new_token = ensure(force=True) or ""
                if new_token and new_token != token:
                    logger.info(
                        "AI-proxy auth retry operation=%s request_id=%s",
                        operation,
                        request_id,
                    )
                    try:
                        result = self.invoke(
                            operation, payload, request_id=request_id, _auth_retry=True
                        )
                        return result
                    except AiProxyError as retry_exc:
                        retry_exc.auth_retry = True
                        retry_exc.retry_attempted = True
                        raise
            raise AiProxyError(
                code,
                reset_at=reset,
                status=int(exc.code or 0),
                stale_chain_retry=stale_chain,
                retry_attempted=_auth_retry or stale_chain,
                auth_retry=_auth_retry,
            ) from None
        except TimeoutError:
            logger.info(
                "AI-proxy timeout operation=%s request_id=%s configured=True authenticated=True",
                operation,
                request_id,
            )
            raise AiProxyError("provider_timeout") from None
        except (URLError, OSError):
            logger.info(
                "AI-proxy network failure operation=%s request_id=%s configured=True authenticated=True",
                operation,
                request_id,
            )
            raise AiProxyError("provider_unavailable") from None
        parsed = _parse_json(text)
        if not isinstance(parsed, dict) or not parsed.get("ok"):
            code = code_from_http(status, parsed if isinstance(parsed, dict) else None)
            stale_chain = bool(
                isinstance(parsed, dict)
                and (
                    parsed.get("stale_chain_retry")
                    or (
                        isinstance(parsed.get("error"), dict)
                        and parsed["error"].get("stale_chain_retry")
                    )
                )
            )
            raise AiProxyError(code, status=status, stale_chain_retry=stale_chain)
        usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        if usage and self._on_usage is not None:
            self._on_usage(usage)
        return AiProxyResponse(
            result=parsed.get("result"),
            usage=usage,
            request_id=str(parsed.get("request_id") or request_id),
            provider_response_id=str(parsed.get("response_id") or ""),
            stale_chain_retry=bool(parsed.get("stale_chain_retry")),
        )


def _parse_json(text: str) -> object | None:
    if not (text or "").strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def bind_ai_proxy_client(
    auth: AuthService,
    *,
    config: AuthClientConfig | None = None,
    on_usage: UsageListener | None = None,
) -> AiProxyClient:
    global _client, _on_usage
    _on_usage = on_usage
    _client = AiProxyClient(auth, config=config, on_usage=on_usage)
    return _client


def get_ai_proxy_client() -> AiProxyClient | None:
    return _client


def reset_ai_proxy_client_for_tests() -> None:
    global _client, _on_usage
    _client = None
    _on_usage = None


def invoke_ai_proxy(operation: str, payload: dict[str, Any], *, request_id: str = "") -> AiProxyResponse:
    if use_direct_ai_provider():
        raise AiProxyError("proxy_internal_error")
    client = _client
    if client is None:
        raise AiProxyError("unauthenticated")
    try:
        return client.invoke(operation, payload, request_id=request_id)
    except AiProxyError as exc:
        budget = as_budget_error(exc)
        if budget is not None:
            raise budget from exc
        raise


def apply_usage_snapshot(budget, payload: dict[str, Any]):
    status = AIUsageStatus.from_payload(payload)
    apply = getattr(budget, "apply_status", None)
    if apply is not None:
        apply(status)
    return status
