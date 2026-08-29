"""Entitlement lookup. UI and AI must not query Supabase tables directly."""

from __future__ import annotations

import json
from pathlib import Path

from app.auth.errors import AuthError
from app.auth.http import AuthHttpClient
from app.auth.models import Entitlement
from app.paths import ensure_dir, get_local_app_data_dir
from app.utils.logger import setup_logger

logger = setup_logger()
CACHE_NAME = "entitlement-cache.json"
DEFAULT = Entitlement(plan="free", account_status="active", ai_allowed=True)


class EntitlementService:
    def __init__(
        self,
        *,
        rest_url: str = "",
        publishable_key: str = "",
        http: AuthHttpClient | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self._rest_url = rest_url.rstrip("/")
        self._key = publishable_key
        self._http = http or AuthHttpClient()
        self._cache_path = cache_path or (get_local_app_data_dir() / CACHE_NAME)
        self._current = self._read_cache() or DEFAULT

    @property
    def current(self) -> Entitlement:
        return self._current

    def peek(self) -> Entitlement:
        return self._current

    def use_cached_or_default(self) -> Entitlement:
        self._current = self._read_cache() or DEFAULT
        return self._current

    def refresh(self, access_token: str, user_id: str) -> Entitlement:
        if not self._rest_url or not self._key or not access_token:
            return self.use_cached_or_default()
        try:
            response = self._http.request(
                f"{self._rest_url}/entitlements?select=plan,account_status,ai_allowed&user_id=eq.{user_id}",
                headers=self._headers(access_token),
            )
        except AuthError:
            logger.info("Entitlement refresh skipped (offline or unavailable).")
            return self.use_cached_or_default()
        rows = response.payload if isinstance(response.payload, list) else []
        if not rows:
            entitlement = DEFAULT
        else:
            row = rows[0] if isinstance(rows[0], dict) else {}
            entitlement = Entitlement(
                plan=str(row.get("plan") or "free"),
                account_status=str(row.get("account_status") or "active"),
                ai_allowed=bool(row.get("ai_allowed", True)),
            )
        self._current = entitlement
        self._write_cache(entitlement)
        return entitlement

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def _read_cache(self) -> Entitlement | None:
        if not self._cache_path.is_file():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return Entitlement(
            plan=str(data.get("plan") or "free"),
            account_status=str(data.get("account_status") or "active"),
            ai_allowed=bool(data.get("ai_allowed", True)),
        )

    def _write_cache(self, entitlement: Entitlement) -> None:
        try:
            ensure_dir(self._cache_path.parent)
            self._cache_path.write_text(
                json.dumps(
                    {
                        "plan": entitlement.plan,
                        "account_status": entitlement.account_status,
                        "ai_allowed": entitlement.ai_allowed,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.info("Could not cache entitlement locally.")
