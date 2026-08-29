"""PKCE + loopback OAuth. Callback handling stays out of UI widgets."""

from __future__ import annotations

import hashlib
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.auth.config import CALLBACK_PATH, LOOPBACK_HOST, LOOPBACK_PORT, OAUTH_TIMEOUT_SEC
from app.auth.errors import AuthError, AuthErrorCode
from app.auth.models import OAuthProvider
from app.utils.logger import setup_logger

logger = setup_logger()
OpenUrl = Callable[[str], None]


def _b64url(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


LOOPBACK_NONCE_PARAM = "capixe_nonce"


def generate_loopback_nonce() -> str:
    """CSRF token for Supabase → loopback only. Never sent as /authorize state."""
    return secrets.token_urlsafe(24)


def generate_state() -> str:
    """Loopback nonce helper. Do not pass the result to /auth/v1/authorize."""
    return generate_loopback_nonce()


def attach_loopback_nonce(redirect_uri: str, nonce: str) -> str:
    parsed = urlparse(redirect_uri)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("state", None)
    query[LOOPBACK_NONCE_PARAM] = [nonce]
    encoded = urlencode({key: values[-1] for key, values in query.items()})
    return urlunparse(parsed._replace(query=encoded))


def build_authorize_url(
    auth_url: str,
    *,
    provider: OAuthProvider,
    redirect_to: str,
    code_challenge: str,
) -> str:
    """Build /authorize. Never include state — GoTrue owns Google/GitHub OAuth state."""
    query = urlencode(
        {
            "provider": provider.value,
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{auth_url.rstrip('/')}/authorize?{query}"


@dataclass
class OAuthCallback:
    code: str = ""
    nonce: str = ""
    provider_state: str = ""
    error: str = ""


class LoopbackOAuthServer:
    """http://127.0.0.1:<fixed-port>/auth/callback — packaged EXE safe, no URI scheme."""

    def __init__(self, *, port: int = LOOPBACK_PORT, timeout_sec: float = OAUTH_TIMEOUT_SEC) -> None:
        self.port = port
        self.timeout_sec = timeout_sec
        self.redirect_uri = f"http://{LOOPBACK_HOST}:{port}{CALLBACK_PATH}"
        self._result: OAuthCallback | None = None
        self._event = threading.Event()
        self._httpd: HTTPServer | None = None

    def start(self) -> None:
        handler = self._make_handler()
        self._httpd = HTTPServer((LOOPBACK_HOST, self.port), handler)
        self._httpd.allow_reuse_address = True
        thread = threading.Thread(target=self._serve, name="capixe-oauth-loopback", daemon=True)
        thread.start()

    def wait(self) -> OAuthCallback:
        finished = self._event.wait(self.timeout_sec)
        self.shutdown()
        if not finished or self._result is None:
            raise AuthError(AuthErrorCode.CANCELLED)
        result = self._result
        if result.error:
            if result.error in {"access_denied", "cancelled", "user_cancelled"}:
                raise AuthError(AuthErrorCode.CANCELLED)
            raise AuthError(AuthErrorCode.INVALID_CALLBACK)
        if not result.code:
            raise AuthError(AuthErrorCode.INVALID_CALLBACK)
        return result

    def cancel(self) -> None:
        self._result = OAuthCallback(error="cancelled")
        self._event.set()
        self.shutdown()

    def _serve(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        httpd.serve_forever(poll_interval=0.2)

    def shutdown(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is None:
            return
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass

    def _make_handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path.rstrip("/") != CALLBACK_PATH.rstrip("/"):
                    self._write(404, "Not found.")
                    return
                query = parse_qs(parsed.query)
                callback = OAuthCallback(
                    code=(query.get("code") or [""])[0],
                    nonce=(query.get(LOOPBACK_NONCE_PARAM) or [""])[0],
                    provider_state=(query.get("state") or [""])[0],
                    error=(query.get("error") or [""])[0],
                )
                owner._result = callback
                owner._event.set()
                if callback.error:
                    self._write(400, "Sign-in was cancelled. You can close this window.")
                else:
                    self._write(200, "Signed in. You can close this window and return to Rootlize.")

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                logger.info("OAuth loopback callback received.")

            def _write(self, status: int, body: str) -> None:
                payload = (
                    "<!doctype html><html><body style='font-family:sans-serif;padding:32px'>"
                    f"<p>{body}</p></body></html>"
                ).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler
