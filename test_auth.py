"""Auth v1: service, credentials, device, oauth, security."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from app.auth.config import (
    AuthClientConfig,
    is_provider_secret_value,
    is_service_role_key,
    load_auth_client_config,
    load_auth_client_config_or_unconfigured,
)
from app.auth.service import AuthService, build_auth_service
from app.auth.credentials import MemoryCredentialStore, TARGET_NAME
from app.auth.device import DeviceService
from app.auth.entitlements import EntitlementService
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.http import HttpResponse
from app.auth.models import (
    AuthStatus,
    AuthUser,
    OAuthProvider,
    StoredSession,
    local_features_available,
)
from app.auth.oauth import (
    LOOPBACK_NONCE_PARAM,
    LoopbackOAuthServer,
    attach_loopback_nonce,
    build_authorize_url,
    generate_loopback_nonce,
    generate_pkce,
)
from app.auth.redact import redact_secrets


def _config() -> AuthClientConfig:
    return AuthClientConfig("https://example.supabase.co", "anon-public")


def _user_payload(
    email="ada@example.com",
    user_id="11111111-1111-1111-1111-111111111111",
    *,
    is_anonymous: bool = False,
):
    user = {"id": user_id, "email": email, "user_metadata": {}, "is_anonymous": is_anonymous}
    return {
        "access_token": "access-token-value",
        "refresh_token": "refresh-token-value",
        "expires_in": 3600,
        "token_type": "bearer",
        "user": user,
    }


class FakeHttp:
    def __init__(self, queue: list) -> None:
        self.queue = list(queue)
        self.calls: list[tuple[str, str]] = []
        self.bodies: list = []

    def request(self, url: str, *, method: str = "GET", headers=None, json_body=None) -> HttpResponse:
        self.calls.append((method.upper(), url))
        self.bodies.append(json_body)
        if json_body:
            dumped = json.dumps(json_body)
            assert "screenshot" not in dumped.lower()
            assert "ocr" not in dumped.lower()
            assert "embedding" not in dumped.lower()
            assert "filename" not in dumped.lower()
            assert "facts" not in dumped.lower()
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, HttpResponse):
            return item
        return HttpResponse(200, "", item)


def _service(tmp_path: Path, http: FakeHttp, **kwargs) -> AuthService:
    store = kwargs.get("store") or MemoryCredentialStore()
    return AuthService(
        _config(),
        store=store,
        devices=DeviceService(tmp_path / "device.json"),
        entitlements=EntitlementService(
            rest_url=_config().rest_url,
            publishable_key="anon-public",
            http=http,
            cache_path=tmp_path / "entitlement-cache.json",
        ),
        http=http,
        open_url=kwargs.get("open_url", lambda _url: None),
        loopback_factory=kwargs.get("loopback_factory"),
    )


def test_email_signup_signin_signout(tmp_path):
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            {},
        ]
    )
    service = _service(tmp_path, http)
    signed = service.sign_up_email("ada@example.com", "secret-pass")
    assert signed.status == AuthStatus.SIGNED_IN
    assert signed.user_id == "11111111-1111-1111-1111-111111111111"
    assert signed.email == "ada@example.com"
    signed_in = service.sign_in_email("ada@example.com", "secret-pass")
    assert signed_in.is_authenticated
    out = service.sign_out()
    assert out.status == AuthStatus.SIGNED_OUT
    assert service.session.user_id == ""


def test_signup_unconfirmed_does_not_create_session(tmp_path):
    http = FakeHttp([{"id": "11111111-1111-1111-1111-111111111111", "email": "ada@example.com"}])
    service = _service(tmp_path, http)
    result = service.sign_up_email("ada@example.com", "secret-pass")
    assert result.status == AuthStatus.SIGNED_OUT
    assert result.message_key == "account.check_email"


def test_invalid_credentials(tmp_path):
    http = FakeHttp([AuthError(AuthErrorCode.INVALID_CREDENTIALS)])
    service = _service(tmp_path, http)
    try:
        service.sign_in_email("ada@example.com", "nope")
        assert False
    except AuthError as exc:
        assert exc.code == AuthErrorCode.INVALID_CREDENTIALS
        assert "invalid" in exc.message_key


def test_session_restore_and_refresh(tmp_path):
    store = MemoryCredentialStore()
    store.save(
        StoredSession(
            access_token="old-access",
            refresh_token="refresh-token-value",
            user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com"),
        )
    )
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = _service(tmp_path, http, store=store)
    restored = service.restore_session()
    assert restored.status == AuthStatus.SIGNED_IN
    assert any("grant_type=refresh_token" in url for _method, url in http.calls)


def test_refresh_failure_signs_out(tmp_path):
    store = MemoryCredentialStore()
    store.save(
        StoredSession(
            access_token="old-access",
            refresh_token="refresh-token-value",
            user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com"),
        )
    )
    http = FakeHttp([AuthError(AuthErrorCode.INVALID_CREDENTIALS)])
    service = _service(tmp_path, http, store=store)
    result = service.restore_session()
    assert result.status == AuthStatus.SESSION_EXPIRED
    assert store.load() is None


def test_refresh_network_keeps_offline_session(tmp_path):
    store = MemoryCredentialStore()
    store.save(
        StoredSession(
            access_token="old-access",
            refresh_token="refresh-token-value",
            user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com"),
        )
    )
    http = FakeHttp([AuthError(AuthErrorCode.NETWORK)])
    service = _service(tmp_path, http, store=store)
    result = service.restore_session()
    assert result.status == AuthStatus.OFFLINE_SESSION
    assert result.is_authenticated
    assert local_features_available(result) is True
    assert store.load() is not None


def test_oauth_urls_include_pkce_but_not_client_state(tmp_path):
    http = FakeHttp([])
    service = _service(tmp_path, http)
    _verifier, challenge = generate_pkce()
    google = service.oauth_authorize_url(
        OAuthProvider.GOOGLE,
        redirect_to="http://127.0.0.1:47831/auth/callback",
        code_challenge=challenge,
    )
    github = service.oauth_authorize_url(
        OAuthProvider.GITHUB,
        redirect_to="http://127.0.0.1:47831/auth/callback",
        code_challenge=challenge,
    )
    for url, provider in ((google, "google"), (github, "github")):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert query["provider"] == [provider]
        assert query["code_challenge_method"] == ["s256"]
        assert query["code_challenge"] == [challenge]
        assert "127.0.0.1:47831" in query["redirect_to"][0]
        assert "state" not in query


def test_start_oauth_authorize_url_omits_state(tmp_path):
    opened: list[str] = []

    class ImmediateLoopback:
        redirect_uri = "http://127.0.0.1:47831/auth/callback"

        def start(self) -> None:
            return None

        def wait(self):
            from app.auth.oauth import OAuthCallback

            return OAuthCallback(code="ok-code")

        def cancel(self) -> None:
            return None

    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = _service(
        tmp_path,
        http,
        open_url=opened.append,
        loopback_factory=ImmediateLoopback,
    )
    session = service.start_oauth(OAuthProvider.GOOGLE)
    assert session.status == AuthStatus.SIGNED_IN
    assert opened
    query = parse_qs(urlparse(opened[0]).query)
    assert "state" not in query
    assert query["provider"] == ["google"]


def test_oauth_callback_success_and_invalid_loopback_nonce(tmp_path):
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = _service(tmp_path, http)
    ok = service.complete_oauth(
        code="ok-code",
        code_verifier="verifier",
        expected_nonce="abc",
        received_nonce="abc",
    )
    assert ok.status == AuthStatus.SIGNED_IN
    try:
        service.complete_oauth(
            code="ok-code",
            code_verifier="verifier",
            expected_nonce="abc",
            received_nonce="zzz",
        )
        assert False
    except AuthError as exc:
        assert exc.code == AuthErrorCode.INVALID_CALLBACK
    try:
        service.complete_oauth(code="", code_verifier="verifier")
        assert False
    except AuthError as exc:
        assert exc.code == AuthErrorCode.INVALID_CALLBACK


def test_loopback_cancel_and_code(tmp_path):
    server = LoopbackOAuthServer(port=47839, timeout_sec=2)
    server.start()
    try:
        urlopen(server.redirect_uri + "?error=access_denied", timeout=2).read()
    except Exception:
        pass
    try:
        server.wait()
        assert False
    except AuthError as exc:
        assert exc.code in {AuthErrorCode.CANCELLED, AuthErrorCode.INVALID_CALLBACK}

    server = LoopbackOAuthServer(port=47838, timeout_sec=2)
    server.start()
    nonce = generate_loopback_nonce()
    urlopen(
        attach_loopback_nonce(server.redirect_uri, nonce) + "&code=abc&state=provider-uuid",
        timeout=2,
    ).read()
    callback = server.wait()
    assert callback.code == "abc"
    assert callback.nonce == nonce
    assert callback.provider_state == "provider-uuid"


def test_credential_store_roundtrip_and_clear():
    store = MemoryCredentialStore()
    session = StoredSession(
        access_token="access-token-value",
        refresh_token="refresh-token-value",
        user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com"),
    )
    store.save(session)
    loaded = store.load()
    assert loaded is not None
    assert loaded.user.user_id == session.user.user_id
    store.clear()
    assert store.load() is None


def test_redact_keeps_tokens_out_of_logs():
    text = redact_secrets("Authorization: Bearer eyJabc.def.ghi refresh_token=super-secret")
    assert "super-secret" not in text
    assert "eyJabc.def.ghi" not in text
    assert "[redacted]" in text or "Bearer [redacted]" in text


def test_device_id_stable_across_restart_and_logout(tmp_path):
    path = tmp_path / "device.json"
    first = DeviceService(path).get_or_create()
    second = DeviceService(path).get_or_create()
    assert first.device_id == second.device_id
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            {},
        ]
    )
    service = _service(tmp_path, http, store=MemoryCredentialStore())
    service.sign_in_email("ada@example.com", "secret-pass")
    before = service.device().device_id
    service.sign_out()
    after = DeviceService(tmp_path / "device.json").get_or_create().device_id
    assert before == after == first.device_id


def test_rejected_provider_secret_does_not_abort_app_config(monkeypatch):
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    try:
        load_auth_client_config()
        assert False
    except Exception as exc:
        assert "provider secret" in str(exc)
    config = load_auth_client_config_or_unconfigured()
    assert config.configured is False
    service = build_auth_service()
    assert service.configured is False
    assert service.client_config.configured is False


def test_provider_secret_env_falls_back_to_file_publishable_key(monkeypatch):
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://env.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(
        "app.auth.config._read_source_file",
        lambda: {
            "supabase_url": "https://file.supabase.co",
            "publishable_key": "anon-from-file",
        },
    )
    assert is_provider_secret_value("sk-test-not-a-real-key") is True
    config = load_auth_client_config()
    assert config.configured is True
    assert config.supabase_url == "https://env.supabase.co"
    assert config.publishable_key == "anon-from-file"


def test_service_role_key_is_rejected(monkeypatch):
    import base64
    import json

    def b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")

    token = f"{b64({'alg': 'none'})}.{b64({'role': 'service_role'})}."
    assert is_service_role_key(token) is True
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", token)
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    try:
        load_auth_client_config()
        assert False
    except Exception as exc:
        assert "service_role" in str(exc)


def test_client_source_has_no_service_role_assignment():
    root = Path(__file__).resolve().parent
    forbidden = []
    for path in (root / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "service_role" in text and "is_service_role_key" not in text and "AuthConfigError" not in text:
            if "SERVICE_ROLE" in text or "service_role_key =" in text:
                forbidden.append(str(path))
    assert forbidden == []


def test_authorize_url_helper():
    url = build_authorize_url(
        "https://example.supabase.co/auth/v1",
        provider=OAuthProvider.GOOGLE,
        redirect_to="http://127.0.0.1:47831/auth/callback",
        code_challenge="abc",
    )
    query = parse_qs(urlparse(url).query)
    assert query["provider"] == ["google"]
    assert query["code_challenge"] == ["abc"]
    assert "state" not in query
    assert LOOPBACK_NONCE_PARAM not in query


def test_loopback_nonce_is_not_authorize_state():
    nonce = generate_loopback_nonce()
    redirect = attach_loopback_nonce("http://127.0.0.1:47831/auth/callback", nonce)
    parsed = urlparse(redirect)
    query = parse_qs(parsed.query)
    assert query[LOOPBACK_NONCE_PARAM] == [nonce]
    assert "state" not in query
    authorize = build_authorize_url(
        "https://example.supabase.co/auth/v1",
        provider=OAuthProvider.GOOGLE,
        redirect_to=redirect,
        code_challenge="abc",
    )
    authorize_query = parse_qs(urlparse(authorize).query)
    assert "state" not in authorize_query
    assert LOOPBACK_NONCE_PARAM in authorize_query["redirect_to"][0]


def test_ensure_fresh_skips_valid_token(tmp_path):
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = _service(tmp_path, http)
    service.sign_in_email("ada@example.com", "secret-pass")
    token = service.ensure_fresh_access_token()
    assert token == "access-token-value"
    assert not any("grant_type=refresh_token" in url for _method, url in http.calls)


def test_ensure_fresh_refreshes_expired_token(tmp_path):
    store = MemoryCredentialStore()
    http = FakeHttp(
        [
            _user_payload(),
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            {**_user_payload(), "access_token": "refreshed-access"},
            [{"plan": "free", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    service = _service(tmp_path, http, store=store)
    service.sign_in_email("ada@example.com", "secret-pass")
    stored = store.load()
    store.save(replace(stored, expires_at=time.time() - 10, access_token="stale-access"))
    service._access_expires_at = time.time() - 10
    service._session = replace(service._session, access_token="stale-access")
    token = service.ensure_fresh_access_token()
    assert token == "refreshed-access"
    assert any("grant_type=refresh_token" in url for _method, url in http.calls)


def test_credential_manager_target_stays_capixe():
    assert TARGET_NAME == "Capixe/auth/session"


def test_oauth_callback_copy_uses_public_brand():
    from app.auth import oauth as oauth_mod

    source = Path(oauth_mod.__file__).read_text(encoding="utf-8")
    assert "return to Rootlize." in source
    assert "return to Capixe." not in source


def test_auth_required_defaults_off_and_env_overrides(monkeypatch):
    from app.auth.config import is_auth_required

    monkeypatch.delenv("CAPIXE_AUTH_REQUIRED", raising=False)
    assert is_auth_required() is False
    monkeypatch.setenv("CAPIXE_AUTH_REQUIRED", "1")
    assert is_auth_required() is True
    monkeypatch.setenv("CAPIXE_AUTH_REQUIRED", "0")
    assert is_auth_required() is False


def test_anonymous_sign_in_persists_and_reuses_installation_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPIXE_PROTOTYPE_ANONYMOUS", "1")
    monkeypatch.delenv("CAPIXE_AUTH_REQUIRED", raising=False)
    user_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    http = FakeHttp(
        [
            _user_payload(email="", user_id=user_id, is_anonymous=True),
            [{"plan": "prototype", "account_status": "active", "ai_allowed": True}],
            {},
            {},
            _user_payload(email="", user_id=user_id, is_anonymous=True),
            [{"plan": "prototype", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    store = MemoryCredentialStore()
    service = _service(tmp_path, http, store=store)
    installation = service.device().device_id
    session = service.sign_in_anonymously()
    assert session.is_authenticated
    assert session.is_anonymous
    assert session.user_id == user_id
    assert session.email == ""
    signup = next(body for body in http.bodies if isinstance(body, dict) and "data" in body)
    assert signup["data"]["installation_id"] == installation
    assert "hostname" not in json.dumps(signup).lower()
    persisted = store.load()
    assert persisted is not None
    assert persisted.user.is_anonymous is True
    assert persisted.user.user_id == user_id

    restored = AuthService(
        _config(),
        store=store,
        devices=DeviceService(tmp_path / "device.json"),
        entitlements=EntitlementService(
            rest_url=_config().rest_url,
            publishable_key="anon-public",
            http=http,
            cache_path=tmp_path / "entitlement-cache.json",
        ),
        http=http,
    ).restore_session()
    assert restored.is_authenticated
    assert restored.is_anonymous
    assert restored.user_id == user_id


def test_two_installations_get_distinct_anonymous_identities(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPIXE_PROTOTYPE_ANONYMOUS", "1")
    payloads = [
        (
            tmp_path / "a",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        ),
        (
            tmp_path / "b",
            "cccccccc-cccc-cccc-cccc-cccccccccccc",
        ),
    ]
    seen_installations = []
    seen_users = []
    for folder, user_id in payloads:
        folder.mkdir()
        http = FakeHttp(
            [
                _user_payload(email="", user_id=user_id, is_anonymous=True),
                [{"plan": "prototype", "account_status": "active", "ai_allowed": True}],
                {},
                {},
            ]
        )
        service = _service(folder, http)
        session = service.sign_in_anonymously()
        seen_users.append(session.user_id)
        seen_installations.append(service.device().device_id)
        signup = next(body for body in http.bodies if isinstance(body, dict) and "data" in body)
        assert signup["data"]["installation_id"] == service.device().device_id
    assert seen_users[0] != seen_users[1]
    assert seen_installations[0] != seen_installations[1]


def test_restore_or_ensure_reuses_stored_anonymous_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPIXE_PROTOTYPE_ANONYMOUS", "1")
    store = MemoryCredentialStore()
    http = FakeHttp(
        [
            _user_payload(
                email="",
                user_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
                is_anonymous=True,
            ),
            [{"plan": "prototype", "account_status": "active", "ai_allowed": True}],
            {},
            {},
        ]
    )
    first = _service(tmp_path, http, store=store)
    first.sign_in_anonymously()
    later = _service(
        tmp_path,
        FakeHttp([AuthError(AuthErrorCode.NETWORK)]),
        store=store,
    )
    session = later.restore_or_ensure_session()
    assert session.is_authenticated
    assert session.status == AuthStatus.OFFLINE_SESSION
    assert session.user_id == "dddddddd-dddd-dddd-dddd-dddddddddddd"


def test_ensure_prototype_session_skipped_when_auth_required(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPIXE_AUTH_REQUIRED", "1")
    monkeypatch.setenv("CAPIXE_PROTOTYPE_ANONYMOUS", "1")
    http = FakeHttp([])
    service = _service(tmp_path, http)
    session = service.ensure_prototype_session()
    assert session.status == AuthStatus.SIGNED_OUT
    assert http.calls == []
