"""Auth domain types. UI and Supabase stay outside this module."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class AuthStatus(str, Enum):
    SIGNED_OUT = "SIGNED_OUT"
    SIGNING_IN = "SIGNING_IN"
    SIGNED_IN = "SIGNED_IN"
    OFFLINE_SESSION = "OFFLINE_SESSION"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    ERROR = "ERROR"


class AuthErrorCode(str, Enum):
    INVALID_CREDENTIALS = "invalid_credentials"
    NOT_CONFIRMED = "not_confirmed"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    CANCELLED = "cancelled"
    INVALID_CALLBACK = "invalid_callback"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class OAuthProvider(str, Enum):
    GOOGLE = "google"
    GITHUB = "github"


def email_account_name(email: str, fallback: str = "") -> str:
    """Nav username is the registered email local-part, before @."""
    text = str(email or "").strip()
    if "@" in text:
        local = text.split("@", 1)[0].strip()
        if local:
            return local
    return text or str(fallback or "").strip()


@dataclass(frozen=True)
class AuthUser:
    """Stable Capixe identity is the Auth UUID, never email."""

    user_id: str
    email: str = ""
    display_name: str = ""
    is_anonymous: bool = False


@dataclass(frozen=True)
class Entitlement:
    plan: str = "free"
    account_status: str = "active"
    ai_allowed: bool = True

    @property
    def plan_label(self) -> str:
        """User-facing plan name. Internal IDs such as free stay unchanged."""
        from app.i18n import t

        return t("account.plan.prototype")


@dataclass(frozen=True)
class StoredSession:
    """Tokens live only inside CredentialStore. Never log this object."""

    access_token: str
    refresh_token: str
    user: AuthUser
    expires_at: float = 0.0
    token_type: str = "bearer"


@dataclass(frozen=True)
class AccountSession:
    status: AuthStatus = AuthStatus.SIGNED_OUT
    user: AuthUser | None = None
    entitlement: Entitlement = field(default_factory=Entitlement)
    message_key: str = ""
    access_token: str = ""

    @property
    def user_id(self) -> str:
        return self.user.user_id if self.user is not None else ""

    @property
    def email(self) -> str:
        return self.user.email if self.user is not None else ""

    @property
    def is_authenticated(self) -> bool:
        return self.status in {AuthStatus.SIGNED_IN, AuthStatus.OFFLINE_SESSION}

    @property
    def is_anonymous(self) -> bool:
        return bool(self.user is not None and self.user.is_anonymous)

    def without_secrets(self) -> AccountSession:
        return replace(self, access_token="")

    def bearer_token(self) -> str:
        """For a future Capixe Backend. Empty when signed out."""
        return self.access_token if self.is_authenticated else ""


LOCAL_FEATURES_ALWAYS_AVAILABLE = frozenset(
    {
        "browse",
        "filename_search",
        "ocr_search",
        "tag",
        "move",
        "rename",
        "create_folder",
        "local_metadata",
    }
)


def local_features_available(_session: AccountSession | None = None) -> bool:
    """Auth state does not lock local library features."""
    return True
