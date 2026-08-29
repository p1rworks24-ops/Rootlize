"""Public Supabase client settings. Secrets never belong here."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.paths import get_resource_root, is_frozen

PUBLISHABLE_ENV = "CAPIXE_SUPABASE_PUBLISHABLE_KEY"
URL_ENV = "CAPIXE_SUPABASE_URL"
# Legacy alias for the *publishable* key only. Never read a service_role env.
ANON_ENV_ALIAS = "CAPIXE_SUPABASE_ANON_KEY"
AUTH_SOURCE_NAME = "auth-source.json"
AUTH_LOCAL_NAME = "auth-source.local.json"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 47831
CALLBACK_PATH = "/auth/callback"
OAUTH_TIMEOUT_SEC = 300


class AuthConfigError(RuntimeError):
    """Publishable configuration is missing or unsafe."""

    def __init__(self, message: str, *, reason: str = "rejected") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class AuthClientConfig:
    supabase_url: str
    publishable_key: str

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.publishable_key)

    @property
    def auth_url(self) -> str:
        return self.supabase_url.rstrip("/") + "/auth/v1"

    @property
    def rest_url(self) -> str:
        return self.supabase_url.rstrip("/") + "/rest/v1"

    @property
    def loopback_redirect(self) -> str:
        return f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}{CALLBACK_PATH}"


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_service_role_key(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return _decode_jwt_payload(text).get("role") == "service_role"


def is_provider_secret_value(value: str) -> bool:
    """True for OpenAI-style / webhook secrets. Publishable JWT and sb_publishable_ are safe."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text.startswith("sk-") or "sk_live" in text or "whsec_" in text


def _load_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _repo_resource_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_file_candidates() -> list[Path]:
    """Local unpublished file first, then the bundled / template file."""
    names: list[str] = []
    if not is_frozen():
        names.append(AUTH_LOCAL_NAME)
    names.append(AUTH_SOURCE_NAME)
    roots: list[Path] = []
    if not is_frozen():
        roots.append(_repo_resource_root())
    roots.append(get_resource_root())
    seen: set[str] = set()
    paths: list[Path] = []
    for root in roots:
        for name in names:
            path = root / "resources" / name
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return paths


def _read_source_file() -> dict:
    merged: dict[str, str] = {}
    for path in _source_file_candidates():
        if not path.is_file():
            continue
        data = _load_json_object(path)
        for key in ("supabase_url", "publishable_key", "anon_key"):
            if str(merged.get(key) or "").strip():
                continue
            value = str(data.get(key) or "").strip()
            if value:
                merged[key] = value
    return merged


def _config_source_labels() -> tuple[str, str]:
    """Where URL / key came from. Labels only — never the values."""
    source = _read_source_file()
    if (os.environ.get(URL_ENV) or "").strip():
        url_source = "env"
    elif str(source.get("supabase_url") or "").strip():
        url_source = "file"
    else:
        url_source = "none"
    if (os.environ.get(PUBLISHABLE_ENV) or "").strip():
        key_source = "publishable_env"
    elif (os.environ.get(ANON_ENV_ALIAS) or "").strip():
        key_source = "anon_env"
    elif str(source.get("publishable_key") or "").strip():
        key_source = "file_publishable"
    elif str(source.get("anon_key") or "").strip():
        key_source = "file_anon"
    else:
        key_source = "none"
    return url_source, key_source


def _publishable_key_candidates(source: dict) -> list[tuple[str, str]]:
    return [
        ((os.environ.get(PUBLISHABLE_ENV) or "").strip(), "publishable_env"),
        ((os.environ.get(ANON_ENV_ALIAS) or "").strip(), "anon_env"),
        (str(source.get("publishable_key") or "").strip(), "file_publishable"),
        (str(source.get("anon_key") or "").strip(), "file_anon"),
    ]


def _select_publishable_key(source: dict) -> tuple[str, str, list[tuple[str, str]]]:
    skipped: list[tuple[str, str]] = []
    for value, label in _publishable_key_candidates(source):
        if not value:
            continue
        if is_service_role_key(value):
            skipped.append((label, "service_role"))
            continue
        if is_provider_secret_value(value):
            skipped.append((label, "provider_secret"))
            continue
        return value, label, skipped
    return "", "none", skipped


def load_auth_client_config() -> AuthClientConfig:
    source = _read_source_file()
    url = (os.environ.get(URL_ENV) or source.get("supabase_url") or "").strip()
    key, key_source, skipped = _select_publishable_key(source)
    if skipped:
        from app.utils.logger import setup_logger

        setup_logger().warning(
            "Auth publishable source skipped; trying next source. skipped=%s selected=%s",
            ",".join(f"{label}:{reason}" for label, reason in skipped),
            key_source,
        )
    if not key and skipped:
        reason = skipped[0][1]
        raise AuthConfigError(
            "Refusing to load a service_role key into the desktop client."
            if reason == "service_role"
            else "Refusing to load a provider secret into the desktop client.",
            reason=reason,
        )
    return AuthClientConfig(supabase_url=url.rstrip("/"), publishable_key=key)


def load_auth_client_config_or_unconfigured() -> AuthClientConfig:
    """Product startup: rejected secrets become unconfigured. Local UI still starts."""
    try:
        return load_auth_client_config()
    except AuthConfigError as exc:
        from app.utils.logger import setup_logger

        url_source, key_source = _config_source_labels()
        setup_logger().warning(
            "Auth client configuration rejected; continuing unconfigured. "
            "reason=%s url_source=%s key_source=%s",
            getattr(exc, "reason", "rejected"),
            url_source,
            key_source,
        )
        return AuthClientConfig(supabase_url="", publishable_key="")


def classify_supabase_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "empty"
    lowered = text.lower()
    if lowered.startswith("https://") and ".supabase.co" in lowered:
        return "supabase_https"
    if "localhost" in lowered or "127.0.0.1" in lowered:
        return "local"
    return "other"


def classify_publishable_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "empty"
    if is_service_role_key(text):
        return "service_role"
    if is_provider_secret_value(text):
        return "provider_secret"
    if text.startswith("eyJ"):
        return "jwt"
    if text.startswith("sb_publishable_"):
        return "sb_publishable"
    return "other"


@dataclass(frozen=True)
class AuthConfigStatus:
    configured: bool
    url_source: str
    key_source: str
    url_kind: str
    key_kind: str
    proxy_functions_readable: bool


def describe_auth_config(config: AuthClientConfig | None = None) -> AuthConfigStatus:
    """Secret-free status for startup logs and official build preflight."""
    cfg = config if config is not None else load_auth_client_config_or_unconfigured()
    url_source, key_source = _config_source_labels()
    proxy_ok = False
    if cfg.configured:
        from app.ai_proxy.config import functions_url

        proxy = functions_url(cfg.supabase_url)
        proxy_ok = proxy.startswith("https://") and proxy.endswith("/functions/v1/ai-proxy")
    return AuthConfigStatus(
        configured=cfg.configured,
        url_source=url_source,
        key_source=key_source,
        url_kind=classify_supabase_url(cfg.supabase_url),
        key_kind=classify_publishable_key(cfg.publishable_key),
        proxy_functions_readable=proxy_ok,
    )
