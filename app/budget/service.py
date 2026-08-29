"""BudgetService: the only client that talks to cloud AI budget RPCs.

UI and AI callers must not query usage tables directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.ai_budget import AiBudgetExceeded, AiBudgetUnavailable
from app.auth.config import AuthClientConfig, load_auth_client_config_or_unconfigured
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.http import AuthHttpClient
from app.budget.ledger import InMemoryBudgetLedger
from app.budget.models import AIUsageStatus, BudgetReservation
from app.paths import ensure_dir, get_local_app_data_dir
from app.utils.logger import setup_logger

logger = setup_logger()
CACHE_NAME = "ai-usage-status.json"


def _error_text(exc: AuthError) -> str:
    return f"{exc.detail} {exc.message_key}".lower()


def _raise_from_auth(exc: AuthError) -> None:
    if exc.code == AuthErrorCode.NETWORK:
        raise AiBudgetUnavailable() from exc
    text = _error_text(exc)
    reset_at = None
    try:
        payload = json.loads(exc.detail) if exc.detail.strip().startswith("{") else {}
    except json.JSONDecodeError:
        payload = {}
    hint = ""
    if isinstance(payload, dict):
        hint = str(payload.get("hint") or "")
        text = f"{text} {payload.get('message') or ''}".lower()
    if hint:
        from app.budget.models import _as_date

        reset_at = _as_date(hint)
    if "ai_not_authenticated" in text:
        raise AiBudgetExceeded(reason="not_authenticated") from exc
    if "ai_account_inactive" in text:
        raise AiBudgetExceeded(reason="inactive", reset_at=reset_at) from exc
    if "ai_not_allowed" in text:
        raise AiBudgetExceeded(reason="not_allowed", reset_at=reset_at) from exc
    if "ai_budget_exceeded" in text:
        raise AiBudgetExceeded(reason="limit_reached", reset_at=reset_at) from exc
    raise AiBudgetUnavailable() from exc


class BudgetService:
    def __init__(
        self,
        *,
        rest_url: str = "",
        publishable_key: str = "",
        http: AuthHttpClient | None = None,
        cache_path: Path | None = None,
        ledger: InMemoryBudgetLedger | None = None,
        ledger_user_id: str = "",
    ) -> None:
        self._rest_url = rest_url.rstrip("/")
        self._key = publishable_key
        self._http = http or AuthHttpClient()
        self._cache_path = cache_path or (get_local_app_data_dir() / CACHE_NAME)
        self._ledger = ledger
        self._ledger_user_id = ledger_user_id
        self._current = self._read_cache()

    @classmethod
    def from_config(
        cls,
        config: AuthClientConfig | None = None,
        *,
        http: AuthHttpClient | None = None,
        cache_path: Path | None = None,
    ) -> BudgetService:
        cfg = config if config is not None else load_auth_client_config_or_unconfigured()
        return cls(
            rest_url=cfg.rest_url if cfg.configured else "",
            publishable_key=cfg.publishable_key,
            http=http,
            cache_path=cache_path,
        )

    def apply_status(self, status: AIUsageStatus) -> AIUsageStatus:
        self._current = status
        if not status.unavailable:
            self._write_cache(status)
        return status

    @property
    def current(self) -> AIUsageStatus | None:
        return self._current

    def peek(self) -> AIUsageStatus | None:
        return self._current

    def unavailable_status(self) -> AIUsageStatus:
        cached = self._read_cache()
        if cached is None:
            return AIUsageStatus.unavailable_status()
        return AIUsageStatus(
            used_percent=cached.used_percent,
            remaining_percent=cached.remaining_percent,
            reset_at=cached.reset_at,
            limit_reached=True,
            budget_micros=cached.budget_micros,
            used_micros=cached.used_micros,
            reserved_micros=cached.reserved_micros,
            unavailable=True,
            plan=cached.plan,
            account_status=cached.account_status,
            ai_allowed=False,
        )

    def get_status(self, access_token: str, *, user_id: str = "") -> AIUsageStatus:
        if self._ledger is not None:
            status = self._ledger.status(user_id or self._ledger_user_id)
            self._current = status
            return status
        if not self._rest_url or not self._key or not access_token:
            status = self.unavailable_status()
            self._current = status
            return status
        try:
            response = self._rpc("get_ai_usage_status", access_token, {})
        except AuthError as exc:
            logger.info("AI usage status unavailable.")
            if exc.code == AuthErrorCode.NETWORK:
                status = self.unavailable_status()
                self._current = status
                return status
            _raise_from_auth(exc)
        payload = response.payload if isinstance(response.payload, dict) else {}
        status = AIUsageStatus.from_payload(payload)
        self._current = status
        self._write_cache(status)
        return status

    def reserve(
        self,
        access_token: str,
        *,
        estimated_cost_micros: int,
        operation: str,
        provider: str = "",
        model: str = "",
        request_id: str = "",
        user_id: str = "",
    ) -> BudgetReservation:
        if self._ledger is not None:
            return self._ledger.reserve(
                user_id or self._ledger_user_id,
                estimated_cost_micros,
                operation,
                provider=provider,
                model=model,
                request_id=request_id,
            )
        if not self._rest_url or not self._key or not access_token:
            raise AiBudgetUnavailable()
        try:
            response = self._rpc(
                "reserve_ai_budget",
                access_token,
                {
                    "p_estimated_cost_micros": int(estimated_cost_micros),
                    "p_operation": operation,
                    "p_provider": provider,
                    "p_model": model,
                    "p_request_id": request_id,
                },
            )
        except AuthError as exc:
            _raise_from_auth(exc)
        payload = response.payload if isinstance(response.payload, dict) else {}
        reservation_id = str(payload.get("reservation_id") or "")
        if not reservation_id:
            raise AiBudgetUnavailable()
        return BudgetReservation(
            reservation_id=reservation_id,
            reserved_micros=int(payload.get("reserved_micros") or estimated_cost_micros),
        )

    def finalize(
        self,
        access_token: str,
        reservation_id: str,
        actual_cost_micros: int,
        *,
        user_id: str = "",
    ) -> None:
        if self._ledger is not None:
            self._ledger.finalize(user_id or self._ledger_user_id, reservation_id, actual_cost_micros)
            return
        if not self._rest_url or not self._key or not access_token or not reservation_id:
            return
        try:
            self._rpc(
                "finalize_ai_usage",
                access_token,
                {
                    "p_reservation_id": reservation_id,
                    "p_actual_cost_micros": int(actual_cost_micros),
                },
            )
        except AuthError as exc:
            logger.info("AI usage finalize skipped.")
            if exc.code != AuthErrorCode.NETWORK:
                _raise_from_auth(exc)

    def release(
        self,
        access_token: str,
        reservation_id: str,
        *,
        user_id: str = "",
    ) -> None:
        if self._ledger is not None:
            self._ledger.release(user_id or self._ledger_user_id, reservation_id)
            return
        if not self._rest_url or not self._key or not access_token or not reservation_id:
            return
        try:
            self._rpc(
                "release_ai_reservation",
                access_token,
                {"p_reservation_id": reservation_id},
            )
        except AuthError as exc:
            logger.info("AI usage release skipped.")
            if exc.code != AuthErrorCode.NETWORK:
                _raise_from_auth(exc)

    def _rpc(self, name: str, access_token: str, body: dict) -> object:
        return self._http.request(
            f"{self._rest_url}/rpc/{name}",
            method="POST",
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json_body=body,
        )

    def _read_cache(self) -> AIUsageStatus | None:
        if not self._cache_path.is_file():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return AIUsageStatus.from_payload(data)

    def _write_cache(self, status: AIUsageStatus) -> None:
        try:
            ensure_dir(self._cache_path.parent)
            self._cache_path.write_text(json.dumps(status.to_cache()), encoding="utf-8")
        except OSError:
            logger.info("Could not cache AI usage status locally.")
