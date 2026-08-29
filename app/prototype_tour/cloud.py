"""Optional Supabase write for feedback / analytics. Never sends library data."""

from __future__ import annotations

from app.auth.errors import AuthError
from app.auth.http import AuthHttpClient
from app.prototype_tour.models import AnalyticsEvent, FeedbackPayload
from app.utils.logger import setup_logger

logger = setup_logger()


def _headers(config, access_token: str = "") -> dict[str, str]:
    headers = {
        "apikey": config.publishable_key,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    token = str(access_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def post_feedback(
    payload: FeedbackPayload,
    *,
    config=None,
    access_token: str = "",
    http: AuthHttpClient | None = None,
) -> bool:
    if config is None or not getattr(config, "configured", False):
        return False
    body = payload.public_fields()
    if not str(access_token or "").strip():
        body["user_id"] = None
    elif not body.get("user_id"):
        body["user_id"] = None
    return _post(
        f"{config.rest_url}/prototype_feedback",
        body,
        config=config,
        access_token=access_token,
        http=http,
    )


def post_analytics(
    event: AnalyticsEvent,
    *,
    config=None,
    access_token: str = "",
    http: AuthHttpClient | None = None,
) -> bool:
    if config is None or not getattr(config, "configured", False):
        return False
    user_id = event.user_id if str(access_token or "").strip() else ""
    body = {
        "prototype_session_id": event.session_id,
        "event_name": event.event_name,
        "occurred_at": event.occurred_at,
        "user_id": user_id or None,
    }
    return _post(
        f"{config.rest_url}/prototype_analytics",
        body,
        config=config,
        access_token=access_token,
        http=http,
    )


def _post(
    url: str,
    body: dict,
    *,
    config,
    access_token: str,
    http: AuthHttpClient | None,
) -> bool:
    client = http or AuthHttpClient()
    try:
        client.request(
            url,
            method="POST",
            headers=_headers(config, access_token),
            json_body=body,
        )
        return True
    except AuthError:
        logger.info("Prototype cloud write skipped: auth/network")
        return False
    except Exception:
        logger.info("Prototype cloud write failed")
        return False
