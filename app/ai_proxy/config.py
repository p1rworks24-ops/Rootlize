"""When Capixe may call a provider directly. Packaged EXE never does."""

from __future__ import annotations

import os

from app.paths import is_frozen

DIRECT_PROVIDER_ENV = "CAPIXE_AI_DIRECT_PROVIDER"
FUNCTION_NAME = "ai-proxy"


def use_direct_ai_provider() -> bool:
    if is_frozen():
        return False
    flag = os.environ.get(DIRECT_PROVIDER_ENV, "").strip().lower()
    return flag in {"1", "true", "yes"}


def functions_url(supabase_url: str, *, name: str = FUNCTION_NAME) -> str:
    return supabase_url.rstrip("/") + f"/functions/v1/{name}"
