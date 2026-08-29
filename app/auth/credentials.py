"""OS credential persistence. Tokens never go in settings.json or SQLite."""

from __future__ import annotations

import json
import sys
from typing import Protocol

from app.auth.models import AuthUser, StoredSession
from app.auth.redact import redact_secrets
from app.utils.logger import setup_logger

TARGET_NAME = "Capixe/auth/session"
logger = setup_logger()


class CredentialStore(Protocol):
    def save(self, session: StoredSession) -> None: ...
    def load(self) -> StoredSession | None: ...
    def clear(self) -> None: ...


class MemoryCredentialStore:
    """Tests and non-Windows fallbacks. Process memory only."""

    def __init__(self) -> None:
        self._payload: str | None = None

    def save(self, session: StoredSession) -> None:
        self._payload = _dump_session(session)

    def load(self) -> StoredSession | None:
        if not self._payload:
            return None
        return _load_session(self._payload)

    def clear(self) -> None:
        self._payload = None


def _dump_session(session: StoredSession) -> str:
    return json.dumps(
        {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "expires_at": session.expires_at,
            "token_type": session.token_type,
            "user_id": session.user.user_id,
            "email": session.user.email,
            "display_name": session.user.display_name,
        },
        separators=(",", ":"),
    )


def _load_session(raw: str) -> StoredSession | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    user_id = str(data.get("user_id") or "").strip()
    access = str(data.get("access_token") or "")
    refresh = str(data.get("refresh_token") or "")
    if not user_id or not access or not refresh:
        return None
    return StoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=float(data.get("expires_at") or 0.0),
        token_type=str(data.get("token_type") or "bearer"),
        user=AuthUser(
            user_id=user_id,
            email=str(data.get("email") or ""),
            display_name=str(data.get("display_name") or ""),
        ),
    )


class WindowsCredentialStore:
    """Windows Credential Manager (GENERIC / LOCAL_MACHINE)."""

    def save(self, session: StoredSession) -> None:
        blob = _dump_session(session).encode("utf-8")
        if not _cred_write(blob):
            raise OSError("Could not store the account session.")
        logger.info("Account session stored in the OS credential store.")

    def load(self) -> StoredSession | None:
        blob = _cred_read()
        if not blob:
            return None
        try:
            return _load_session(blob.decode("utf-8"))
        except UnicodeDecodeError:
            logger.warning("Stored account session could not be read.")
            return None

    def clear(self) -> None:
        _cred_delete()
        logger.info("Account session removed from the OS credential store.")


def default_credential_store() -> CredentialStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    logger.warning("OS credential store is unavailable; using in-memory session storage.")
    return MemoryCredentialStore()


def _cred_write(blob: bytes) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(blob)
    cred = CREDENTIAL()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = TARGET_NAME
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.c_void_p).value
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "Capixe"
    ok = bool(advapi.CredWriteW(ctypes.byref(cred), 0))
    if not ok:
        logger.warning("Credential Manager write failed.")
    return ok


def _cred_read() -> bytes | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIAL)),
    ]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(TARGET_NAME, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        cred = pointer.contents
        size = int(cred.CredentialBlobSize)
        if not cred.CredentialBlob or size <= 0:
            return None
        return ctypes.string_at(cred.CredentialBlob, size)
    finally:
        advapi.CredFree(pointer)


def _cred_delete() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    advapi.CredDeleteW(TARGET_NAME, 1, 0)


def describe_store_error(exc: BaseException) -> str:
    return redact_secrets(str(exc))
