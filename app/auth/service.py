"""AuthService: the only module that talks to Supabase Auth."""

from __future__ import annotations

import base64
import json
import threading
import time
import webbrowser
from typing import Callable

from app.auth.config import (
    AuthClientConfig,
    allow_anonymous_prototype_session,
    load_auth_client_config_or_unconfigured,
)
from app.auth.credentials import CredentialStore, default_credential_store
from app.auth.device import DeviceService
from app.auth.entitlements import DEFAULT, EntitlementService
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.http import AuthHttpClient
from app.auth.models import (
    AccountSession,
    AuthStatus,
    AuthUser,
    Entitlement,
    OAuthProvider,
    StoredSession,
)
from app.auth.oauth import (
    LoopbackOAuthServer,
    OpenUrl,
    build_authorize_url,
    generate_pkce,
)
from app.utils.logger import setup_logger

logger = setup_logger()
OpenUrlFn = OpenUrl
TOKEN_REFRESH_SKEW_SEC = 60


def _jwt_exp(token: str) -> float:
    """Read exp from a JWT payload. Never logs claims or the token."""
    try:
        parts = str(token or "").split(".")
        if len(parts) < 2:
            return 0.0
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return float(data.get("exp") or 0.0)
    except Exception:
        return 0.0


def _truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_anonymous_from_payload(payload: dict, user: dict) -> bool:
    if _truthy_flag(user.get("is_anonymous")):
        return True
    if _truthy_flag(payload.get("is_anonymous")):
        return True
    token = str(payload.get("access_token") or "")
    if not token:
        return False
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return False
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except Exception:
        return False
    if _truthy_flag(claims.get("is_anonymous")):
        return True
    metadata = claims.get("app_metadata") if isinstance(claims.get("app_metadata"), dict) else {}
    return _truthy_flag(metadata.get("is_anonymous"))


def _user_from_payload(payload: dict) -> AuthUser:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else payload
    user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip()
    metadata = user.get("user_metadata") if isinstance(user.get("user_metadata"), dict) else {}
    display = str(metadata.get("full_name") or metadata.get("name") or email.split("@")[0] or "")
    if not user_id:
        raise AuthError(AuthErrorCode.UNKNOWN)
    return AuthUser(
        user_id=user_id,
        email=email,
        display_name=display,
        is_anonymous=_is_anonymous_from_payload(payload, user if isinstance(user, dict) else {}),
    )


def _session_from_payload(payload: dict) -> StoredSession:
    access = str(payload.get("access_token") or "")
    refresh = str(payload.get("refresh_token") or "")
    if not access or not refresh:
        raise AuthError(AuthErrorCode.UNKNOWN)
    expires_in = float(payload.get("expires_in") or 0)
    return StoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=time.time() + expires_in if expires_in else 0.0,
        token_type=str(payload.get("token_type") or "bearer"),
        user=_user_from_payload(payload),
    )


class AuthService:
    def __init__(
        self,
        config: AuthClientConfig | None = None,
        *,
        store: CredentialStore | None = None,
        devices: DeviceService | None = None,
        entitlements: EntitlementService | None = None,
        http: AuthHttpClient | None = None,
        open_url: OpenUrlFn | None = None,
        loopback_factory: Callable[[], LoopbackOAuthServer] | None = None,
    ) -> None:
        self._config = (
            config if config is not None else load_auth_client_config_or_unconfigured()
        )
        self._store = store or default_credential_store()
        self._devices = devices or DeviceService()
        self.http = http or AuthHttpClient()
        self._http = self.http
        self._entitlements = entitlements or EntitlementService(
            rest_url=self._config.rest_url if self._config.configured else "",
            publishable_key=self._config.publishable_key,
            http=self._http,
        )
        self._open_url = open_url or webbrowser.open
        self._loopback_factory = loopback_factory or LoopbackOAuthServer
        self._session = AccountSession(status=AuthStatus.SIGNED_OUT)
        self._access_expires_at = 0.0
        self._token_lock = threading.Lock()
        self._active_oauth: LoopbackOAuthServer | None = None
        self._devices.get_or_create()

    @property
    def session(self) -> AccountSession:
        return self._session.without_secrets()

    def bearer_token(self) -> str:
        """Access token for Capixe backend RPCs. Empty when signed out."""
        return self._session.access_token if self._session.is_authenticated else ""

    def ensure_fresh_access_token(self, *, force: bool = False) -> str:
        """Refresh when expired or near expiry. Never logs tokens."""
        with self._token_lock:
            return self._ensure_fresh_access_token_locked(force=force)

    def _ensure_fresh_access_token_locked(self, *, force: bool) -> str:
        if not self._session.is_authenticated:
            return ""
        stored = self._store.load()
        current = self._session.access_token
        if stored is None:
            return current
        now = time.time()
        expires_at = float(stored.expires_at or self._access_expires_at or 0.0)
        if not expires_at:
            expires_at = _jwt_exp(stored.access_token or current)
        if not force and expires_at and (expires_at - TOKEN_REFRESH_SKEW_SEC) > now:
            return stored.access_token or current
        try:
            refreshed = self._refresh(stored.refresh_token)
            self._commit(refreshed, online=True)
            logger.info("Account access token refreshed.")
            return self._session.access_token
        except AuthError as exc:
            if exc.code == AuthErrorCode.NETWORK:
                logger.info("Account token refresh skipped (network).")
                return stored.access_token or current
            logger.info("Account token refresh failed; session expired.")
            self._store.clear()
            self._session = AccountSession(
                status=AuthStatus.SESSION_EXPIRED, message_key=exc.message_key
            )
            self._access_expires_at = 0.0
            return ""

    @property
    def client_config(self) -> AuthClientConfig:
        return self._config

    @property
    def configured(self) -> bool:
        return self._config.configured

    @property
    def rest_url(self) -> str:
        return self._config.rest_url if self._config.configured else ""

    @property
    def publishable_key(self) -> str:
        return self._config.publishable_key if self._config.configured else ""

    def device(self):
        return self._devices.get_or_create()

    def require_configured(self) -> None:
        if not self._config.configured:
            raise AuthError(AuthErrorCode.NOT_CONFIGURED)

    def has_stored_session(self) -> bool:
        return self._store.load() is not None

    def restore_or_ensure_session(self) -> AccountSession:
        """Restore a stored session, or mint a Prototype anonymous JWT if allowed."""
        had_stored = self.has_stored_session()
        session = self.restore_session()
        if session.is_authenticated or had_stored:
            return session
        return self.ensure_prototype_session()

    def ensure_prototype_session(self) -> AccountSession:
        """Silent anonymous sign-in for packaged Prototype AI identity."""
        if self._session.is_authenticated:
            return self.session
        if not allow_anonymous_prototype_session() or not self.configured:
            return self.session
        try:
            return self.sign_in_anonymously()
        except AuthError as exc:
            if exc.code == AuthErrorCode.NETWORK:
                logger.info("Prototype anonymous session skipped (network).")
            else:
                logger.info("Prototype anonymous session failed.")
            return self.session

    def sign_in_anonymously(self) -> AccountSession:
        """Create a GoTrue anonymous user. Identity is auth.uid(), not a client user_id."""
        self.require_configured()
        device = self._devices.get_or_create()
        payload = self._auth_json(
            "POST",
            "/signup",
            {"data": {"installation_id": device.device_id}},
        )
        stored = _session_from_payload(payload)
        if not stored.user.is_anonymous:
            stored = StoredSession(
                access_token=stored.access_token,
                refresh_token=stored.refresh_token,
                user=AuthUser(
                    user_id=stored.user.user_id,
                    email=stored.user.email,
                    display_name=stored.user.display_name,
                    is_anonymous=True,
                ),
                expires_at=stored.expires_at,
                token_type=stored.token_type,
            )
        logger.info("Prototype anonymous session created.")
        return self._commit(stored, online=True)

    def restore_session(self) -> AccountSession:
        stored = self._store.load()
        if stored is None:
            self._session = AccountSession(status=AuthStatus.SIGNED_OUT)
            return self.session
        self._session = self._build_session(
            AuthStatus.OFFLINE_SESSION, stored, self._entitlements.use_cached_or_default()
        )
        self._access_expires_at = float(stored.expires_at or 0.0)
        try:
            refreshed = self._refresh(stored.refresh_token)
        except AuthError as exc:
            if exc.code == AuthErrorCode.NETWORK:
                logger.info("Account restore kept offline session.")
                return self.session
            self._store.clear()
            self._session = AccountSession(
                status=AuthStatus.SESSION_EXPIRED, message_key=exc.message_key
            )
            self._access_expires_at = 0.0
            logger.info("Account session expired; signed out locally.")
            return self.session
        return self._commit(refreshed, online=True)

    def sign_up_email(self, email: str, password: str) -> AccountSession:
        self.require_configured()
        payload = self._auth_json(
            "POST",
            "/signup",
            {"email": email.strip(), "password": password},
        )
        if not payload.get("access_token"):
            self._session = AccountSession(
                status=AuthStatus.SIGNED_OUT,
                message_key="account.check_email",
            )
            logger.info("Account signup waiting for email confirmation.")
            return self.session
        stored = _session_from_payload(payload)
        return self._commit(stored, online=True)

    def sign_in_email(self, email: str, password: str) -> AccountSession:
        self.require_configured()
        payload = self._auth_json(
            "POST",
            "/token?grant_type=password",
            {"email": email.strip(), "password": password},
        )
        stored = _session_from_payload(payload)
        return self._commit(stored, online=True)

    def start_oauth(self, provider: OAuthProvider) -> str:
        """Build the provider URL, open the default browser, wait for loopback."""
        self.require_configured()
        verifier, challenge = generate_pkce()
        server = self._loopback_factory()
        self._active_oauth = server
        server.start()
        # Do not send state= to /authorize. GoTrue stores flow_state.id in
        # that parameter for Google/GitHub and rejects a client token_urlsafe
        # value as "OAuth state parameter is invalid".
        url = build_authorize_url(
            self._config.auth_url,
            provider=provider,
            redirect_to=server.redirect_uri,
            code_challenge=challenge,
        )
        logger.info("Starting %s OAuth in the default browser.", provider.value)
        self._open_url(url)
        callback = server.wait()
        self._active_oauth = None
        payload = self._auth_json(
            "POST",
            "/token?grant_type=pkce",
            {"auth_code": callback.code, "code_verifier": verifier},
        )
        stored = _session_from_payload(payload)
        return self._commit(stored, online=True)

    def cancel_oauth(self) -> None:
        server = self._active_oauth
        if server is not None:
            server.cancel()
        self._active_oauth = None

    def sign_out(self) -> AccountSession:
        token = self._session.access_token
        if token and self._config.configured:
            try:
                self._http.request(
                    self._config.auth_url + "/logout",
                    method="POST",
                    headers=self._headers(token),
                )
            except AuthError:
                logger.info("Account logout request skipped.")
        self._store.clear()
        self._session = AccountSession(status=AuthStatus.SIGNED_OUT)
        self._access_expires_at = 0.0
        logger.info("Signed out. Local library is unchanged.")
        return self.session

    def oauth_authorize_url(
        self,
        provider: OAuthProvider,
        *,
        redirect_to: str,
        code_challenge: str,
    ) -> str:
        self.require_configured()
        return build_authorize_url(
            self._config.auth_url,
            provider=provider,
            redirect_to=redirect_to,
            code_challenge=code_challenge,
        )

    def complete_oauth(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str = "",
        received_nonce: str = "",
    ) -> AccountSession:
        self.require_configured()
        if expected_nonce and received_nonce != expected_nonce:
            raise AuthError(AuthErrorCode.INVALID_CALLBACK)
        if not code:
            raise AuthError(AuthErrorCode.INVALID_CALLBACK)
        payload = self._auth_json(
            "POST",
            "/token?grant_type=pkce",
            {"auth_code": code, "code_verifier": code_verifier},
        )
        stored = _session_from_payload(payload)
        return self._commit(stored, online=True)

    def _refresh(self, refresh_token: str) -> StoredSession:
        payload = self._auth_json(
            "POST",
            "/token?grant_type=refresh_token",
            {"refresh_token": refresh_token},
        )
        return _session_from_payload(payload)

    def _commit(self, stored: StoredSession, *, online: bool) -> AccountSession:
        self._store.save(stored)
        entitlement = DEFAULT
        if online:
            entitlement = self._entitlements.refresh(stored.access_token, stored.user.user_id)
            self._touch_cloud_account(stored)
        status = AuthStatus.SIGNED_IN if online else AuthStatus.OFFLINE_SESSION
        self._access_expires_at = float(stored.expires_at or 0.0)
        self._session = self._build_session(status, stored, entitlement)
        logger.info("Account session ready status=%s", status.value)
        return self.session

    def _touch_cloud_account(self, stored: StoredSession) -> None:
        """Best-effort profile/device upsert. Never sends library data."""
        if not self._config.configured:
            return
        device = self._devices.get_or_create()
        headers = {
            **self._headers(stored.access_token),
            "Prefer": "resolution=merge-duplicates,return=minimal",
            "Content-Type": "application/json",
        }
        try:
            self._http.request(
                self._config.rest_url + "/profiles",
                method="POST",
                headers=headers,
                json_body={
                    "user_id": stored.user.user_id,
                    "display_name": stored.user.display_name or stored.user.email,
                },
            )
        except AuthError:
            logger.info("Profile upsert skipped.")
        try:
            self._http.request(
                self._config.rest_url + "/devices?on_conflict=device_id",
                method="POST",
                headers=headers,
                json_body={
                    **device.registration_payload(stored.user.user_id),
                    "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
        except AuthError:
            logger.info("Device upsert skipped.")

    def _build_session(
        self, status: AuthStatus, stored: StoredSession, entitlement: Entitlement
    ) -> AccountSession:
        return AccountSession(
            status=status,
            user=stored.user,
            entitlement=entitlement,
            access_token=stored.access_token,
        )

    def _headers(self, access_token: str = "") -> dict[str, str]:
        headers = {
            "apikey": self._config.publishable_key,
            "Accept": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _auth_json(self, method: str, path: str, body: dict) -> dict:
        response = self._http.request(
            self._config.auth_url + path,
            method=method,
            headers=self._headers(),
            json_body=body,
        )
        payload = response.payload if isinstance(response.payload, dict) else {}
        return payload


def build_auth_service() -> AuthService:
    return AuthService(load_auth_client_config_or_unconfigured())
