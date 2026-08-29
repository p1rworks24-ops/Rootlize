"""Product AI boundary. Callers send operation + payload, never provider secrets."""

from app.ai_proxy.client import (
    AiProxyClient,
    bind_ai_proxy_client,
    get_ai_proxy_client,
    invoke_ai_proxy,
    reset_ai_proxy_client_for_tests,
)
from app.ai_proxy.config import DIRECT_PROVIDER_ENV, use_direct_ai_provider
from app.ai_proxy.errors import AiProxyError
from app.ai_proxy.models import AiProxyResponse

__all__ = [
    "AiProxyClient",
    "AiProxyError",
    "AiProxyResponse",
    "DIRECT_PROVIDER_ENV",
    "bind_ai_proxy_client",
    "get_ai_proxy_client",
    "invoke_ai_proxy",
    "reset_ai_proxy_client_for_tests",
    "use_direct_ai_provider",
]
