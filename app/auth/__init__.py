"""Public auth boundary. UI imports from here, never from supabase clients."""

from app.auth.config import AuthClientConfig, load_auth_client_config
from app.auth.credentials import CredentialStore, MemoryCredentialStore, default_credential_store
from app.auth.device import DeviceService
from app.auth.entitlements import EntitlementService
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.models import (
    LOCAL_FEATURES_ALWAYS_AVAILABLE,
    AccountSession,
    AuthStatus,
    AuthUser,
    Entitlement,
    OAuthProvider,
    email_account_name,
    local_features_available,
)
from app.auth.oauth import (
    attach_loopback_nonce,
    build_authorize_url,
    generate_loopback_nonce,
    generate_pkce,
    generate_state,
)
from app.auth.service import AuthService, build_auth_service

__all__ = [
    "AccountSession",
    "AuthClientConfig",
    "AuthError",
    "AuthErrorCode",
    "AuthService",
    "AuthStatus",
    "AuthUser",
    "CredentialStore",
    "DeviceService",
    "Entitlement",
    "EntitlementService",
    "LOCAL_FEATURES_ALWAYS_AVAILABLE",
    "MemoryCredentialStore",
    "OAuthProvider",
    "email_account_name",
    "build_auth_service",
    "attach_loopback_nonce",
    "build_authorize_url",
    "default_credential_store",
    "generate_loopback_nonce",
    "generate_pkce",
    "generate_state",
    "load_auth_client_config",
    "local_features_available",
]
from app.auth.credentials import CredentialStore, MemoryCredentialStore, default_credential_store
from app.auth.device import DeviceService
from app.auth.entitlements import EntitlementService
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.models import (
    LOCAL_FEATURES_ALWAYS_AVAILABLE,
    AccountSession,
    AuthStatus,
    AuthUser,
    Entitlement,
    OAuthProvider,
    email_account_name,
    local_features_available,
)
from app.auth.oauth import (
    attach_loopback_nonce,
    build_authorize_url,
    generate_loopback_nonce,
    generate_pkce,
    generate_state,
)
from app.auth.service import AuthService, build_auth_service

__all__ = [
    "AccountSession",
    "AuthClientConfig",
    "AuthError",
    "AuthErrorCode",
    "AuthService",
    "AuthStatus",
    "AuthUser",
    "CredentialStore",
    "DeviceService",
    "Entitlement",
    "EntitlementService",
    "LOCAL_FEATURES_ALWAYS_AVAILABLE",
    "MemoryCredentialStore",
    "OAuthProvider",
    "email_account_name",
    "build_auth_service",
    "attach_loopback_nonce",
    "build_authorize_url",
    "default_credential_store",
    "generate_loopback_nonce",
    "generate_pkce",
    "generate_state",
    "load_auth_client_config",
    "local_features_available",
]
