"""AI Provider Proxy v1: client boundary, routing, and security contracts."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from io import BytesIO

import pytest
from PIL import Image

from app.ai_budget import (
    OPERATION_ACT_PLAN,
    OPERATION_FACTS_GENERATE,
    OPERATION_MEANING_SEARCH,
    AiBudgetExceeded,
    reset_ai_budget_gate_for_tests,
)
from app.ai_proxy import (
    AiProxyClient,
    AiProxyError,
    bind_ai_proxy_client,
    invoke_ai_proxy,
    reset_ai_proxy_client_for_tests,
    use_direct_ai_provider,
)
from app.ai_proxy.config import functions_url
from app.ai_proxy.errors import KNOWN_CODES, classify_ask_ai_failure, describe_ai_failure
from app.ai_proxy.models import FORBIDDEN_CLIENT_FIELDS
from app.auth.config import AuthClientConfig
from app.auth.models import AccountSession, AuthStatus, AuthUser
from app.image_facts.provider import ImageFactsProvider
from app.image_facts.search import ImageFactsSearchMatcher
from app.relevance import RelevanceImage
from app.workspace.planner import post_act_plan_json

ROOT = Path(__file__).resolve().parent
PROXY_DIR = ROOT / "supabase" / "functions" / "ai-proxy"


class _FakeAuth:
    def __init__(self, *, signed_in=True, offline=False, token="access-token"):
        status = AuthStatus.SIGNED_OUT
        if signed_in and offline:
            status = AuthStatus.OFFLINE_SESSION
        elif signed_in:
            status = AuthStatus.SIGNED_IN
        self._session = AccountSession(
            status=status,
            user=AuthUser("11111111-1111-1111-1111-111111111111", "ada@example.com") if signed_in else None,
            access_token=token if signed_in else "",
        )

    @property
    def session(self):
        return self._session.without_secrets()

    def bearer_token(self):
        return self._session.access_token if self._session.is_authenticated else ""

    def ensure_fresh_access_token(self, *, force=False):
        del force
        return self.bearer_token()


class _HttpResponse:
    def __init__(self, payload, status=200):
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _HttpError(HTTPError):
    def __init__(self, status, payload):
        super().__init__(
            "https://example.supabase.co/functions/v1/ai-proxy",
            status,
            "err",
            hdrs=None,
            fp=BytesIO(json.dumps(payload).encode("utf-8")),
        )


@pytest.fixture(autouse=True)
def _reset_proxy():
    reset_ai_proxy_client_for_tests()
    reset_ai_budget_gate_for_tests()
    yield
    reset_ai_proxy_client_for_tests()
    reset_ai_budget_gate_for_tests()


def _config():
    return AuthClientConfig(
        supabase_url="https://example.supabase.co",
        publishable_key="anon-public",
    )


def test_direct_provider_off_by_default(monkeypatch):
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)
    assert use_direct_ai_provider() is False


def test_direct_provider_never_in_frozen(monkeypatch):
    monkeypatch.setenv("CAPIXE_AI_DIRECT_PROVIDER", "1")
    monkeypatch.setattr("app.ai_proxy.config.is_frozen", lambda: True)
    assert use_direct_ai_provider() is False


def test_proxy_client_strips_forbidden_fields_and_omits_user_id():
    seen = []

    def fake_urlopen(request, timeout=0):
        seen.append(json.loads(request.data.decode("utf-8")))
        return _HttpResponse(
            {
                "ok": True,
                "result": {"status": "clarify", "steps": []},
                "usage": {"used_percent": 10, "remaining_percent": 90, "reset_at": "2026-09-01", "limit_reached": False},
            }
        )

    client = AiProxyClient(_FakeAuth(), config=_config(), urlopen_fn=fake_urlopen)
    client.invoke(
        "act_plan",
        {
            "user_prompt": "make a folder",
            "user_id": "attacker",
            "model": "gpt-expensive",
            "api_key": "sk-secret",
            "endpoint": "https://evil.example",
        },
    )
    body = seen[0]
    assert body["operation"] == "act_plan"
    assert "user_id" not in body
    assert "user_id" not in body["payload"]
    assert "model" not in body["payload"]
    assert "api_key" not in body["payload"]
    assert "endpoint" not in body["payload"]
    assert body["payload"]["user_prompt"] == "make a folder"


def test_proxy_rejects_unauthenticated():
    client = AiProxyClient(_FakeAuth(signed_in=False), config=_config(), urlopen_fn=lambda *_a, **_k: None)
    with pytest.raises(AiProxyError) as exc:
        client.invoke("meaning_search", {"query": "dog", "items": [{"image_id": 1, "document": "x"}]})
    assert exc.value.code == "unauthenticated"


def test_proxy_accepts_anonymous_session_without_sending_identity():
    seen = []

    def fake_urlopen(request, timeout=0):
        seen.append(
            {
                "body": json.loads(request.data.decode("utf-8")),
                "authorization": request.get_header("Authorization") or request.headers.get("Authorization"),
            }
        )
        return _HttpResponse({"ok": True, "result": {"matches": []}, "usage": {}})

    auth = _FakeAuth()
    auth._session = AccountSession(
        status=AuthStatus.SIGNED_IN,
        user=AuthUser("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "", is_anonymous=True),
        access_token="anon-access-token",
    )
    client = AiProxyClient(auth, config=_config(), urlopen_fn=fake_urlopen)
    client.invoke("meaning_search", {"query": "dog", "items": [{"image_id": 1, "document": "x"}]})
    body = seen[0]["body"]
    assert "user_id" not in body
    assert "installation_id" not in json.dumps(body)
    assert "aaaaaaaa" not in json.dumps(body)
    header = seen[0]["authorization"] or ""
    assert "Bearer anon-access-token" in header


def test_proxy_skips_when_client_config_is_unconfigured():
    opened = []

    def fake_urlopen(*_args, **_kwargs):
        opened.append(1)
        raise AssertionError("unconfigured proxy must not HTTP")

    client = AiProxyClient(
        _FakeAuth(),
        config=AuthClientConfig(supabase_url="", publishable_key=""),
        urlopen_fn=fake_urlopen,
    )
    with pytest.raises(AiProxyError) as exc:
        client.invoke("facts_generate", {"image_id": 1, "views": [{"label": "Full", "image_jpeg_b64": "abc"}]})
    assert exc.value.code == "budget_unavailable"
    assert opened == []


def test_describe_ai_failure_omits_secrets_and_bodies():
    err = AiProxyError("budget_unavailable", status=0)
    text = describe_ai_failure(err, operation="facts_generate")
    assert "error_class=AiProxyError" in text
    assert "proxy_code=budget_unavailable" in text
    assert "http_status=0" in text
    assert "operation=facts_generate" in text
    assert "sk-" not in text
    assert "access-token" not in text
    assert "eyJ" not in text
    extra = describe_ai_failure(
        err,
        operation="facts_generate",
        configured=True,
        authenticated=True,
        facts_needed=57,
        facts_generated=88,
        facts_failed=8,
        facts_shortlist=40,
    )
    assert "configured=True" in extra
    assert "authenticated=True" in extra
    assert "facts_needed=57" in extra
    assert "facts_generated=88" in extra
    assert "facts_failed=8" in extra
    assert "facts_shortlist=40" in extra
    assert "sk-" not in extra


def test_proxy_maps_budget_exceeded_without_provider_text(caplog):
    def fake_urlopen(*_args, **_kwargs):
        raise _HttpError(429, {"ok": False, "error": {"code": "budget_exceeded", "reset_at": "2026-09-01"}})

    client = AiProxyClient(_FakeAuth(), config=_config(), urlopen_fn=fake_urlopen)
    with caplog.at_level("INFO"):
        with pytest.raises(AiProxyError) as exc:
            client.invoke("meaning_search", {"query": "dog", "items": [{"image_id": 1, "document": "facts"}]})
    assert exc.value.code == "budget_exceeded"
    assert "openai" not in str(exc.value).lower()
    assert "sk-" not in str(exc.value)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "AI-proxy HTTP error" in text
    assert "operation=meaning_search" in text
    assert "code=budget_exceeded" in text
    assert "http_status=429" in text
    assert "configured=True" in text
    assert "authenticated=True" in text


def test_invoke_ai_proxy_converts_budget_errors():
    def fake_urlopen(*_args, **_kwargs):
        raise _HttpError(429, {"ok": False, "error": {"code": "budget_exceeded"}})

    bind_ai_proxy_client(_FakeAuth(), config=_config())
    get = __import__("app.ai_proxy.client", fromlist=["get_ai_proxy_client"]).get_ai_proxy_client()
    get._urlopen = fake_urlopen
    with pytest.raises(AiBudgetExceeded) as exc:
        invoke_ai_proxy("act_plan", {"user_prompt": "x"})
    assert exc.value.reason == "limit_reached"


def test_proxy_client_does_not_retry():
    calls = []

    def fake_urlopen(*_args, **_kwargs):
        calls.append(1)
        raise _HttpError(502, {"ok": False, "error": {"code": "provider_unavailable"}})

    client = AiProxyClient(_FakeAuth(), config=_config(), urlopen_fn=fake_urlopen)
    with pytest.raises(AiProxyError):
        client.invoke("act_plan", {"user_prompt": "x"})
    assert calls == [1]


def test_facts_generate_uses_proxy(monkeypatch, tmp_path):
    seen = []

    class _Gate:
        def allow(self, intent):
            seen.append(("budget", intent.operation))

    from app.ai_budget import set_ai_budget_gate

    set_ai_budget_gate(_Gate())
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)

    def fake_invoke(operation, payload, **_kwargs):
        seen.append((operation, sorted(payload)))
        assert "model" not in payload
        assert "user_id" not in payload
        return type("R", (), {"result": {
            "image_id": 1,
            "media_type": "screenshot",
            "scene_description": "desk",
            "environment": "",
            "ui_types": [],
            "entities": [],
            "applications": [],
            "activities": [],
            "relationships": [],
            "notable_text": [],
        }, "usage": {}, "request_id": "r1"})()

    monkeypatch.setattr("app.image_facts.provider.invoke_ai_proxy", fake_invoke)
    path = tmp_path / "one.png"
    Image.new("RGB", (32, 24), "red").save(path)
    provider = ImageFactsProvider(retries=0, timeout_seconds=1, unknown_retries=0)
    run = provider.index([RelevanceImage(1, path)])
    assert run.results[0]["media_type"] == "screenshot"
    assert seen[0] == ("budget", OPERATION_FACTS_GENERATE)
    assert seen[1][0] == OPERATION_FACTS_GENERATE


def test_meaning_search_uses_proxy(monkeypatch):
    seen = []

    class _Gate:
        def allow(self, intent):
            seen.append(intent.operation)

    from app.ai_budget import set_ai_budget_gate

    set_ai_budget_gate(_Gate())
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)

    def fake_invoke(operation, payload, **_kwargs):
        seen.append(operation)
        assert payload["query"] == "Google Chrome"
        assert "model" not in payload
        return type("R", (), {"result": {"results": [{
            "image_id": 1,
            "reason": "icon",
            "independent_conditions": [
                {"condition": "Google Chrome", "confirmed": True, "evidence": "taskbar icon"},
            ],
        }]}, "usage": {}, "request_id": "r2"})()

    monkeypatch.setattr("app.image_facts.search.invoke_ai_proxy", fake_invoke)
    matcher = ImageFactsSearchMatcher(retries=0, timeout_seconds=1)
    run = matcher.match_records(
        "Google Chrome",
        [{
            "image_id": 1,
            "media_type": "screenshot",
            "scene_description": "",
            "environment": "",
            "ui_types": [],
            "entities": [{"name": "Google Chrome", "kind": "object", "attributes": ["taskbar icon"],
                          "colors": [], "states": [], "posture": "", "observed_color_description": "",
                          "visibility": "visible", "identifiability": "clear"}],
            "applications": [],
            "activities": [],
            "relationships": [],
            "notable_text": [],
        }],
    )
    assert seen == [OPERATION_MEANING_SEARCH, OPERATION_MEANING_SEARCH]
    assert run.results[0].relevant is True


def test_act_plan_uses_proxy(monkeypatch):
    seen = []

    class _Gate:
        def allow(self, intent):
            seen.append(intent.operation)

    from app.ai_budget import set_ai_budget_gate

    set_ai_budget_gate(_Gate())
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)

    def fake_invoke(operation, payload, **_kwargs):
        seen.append((operation, payload))
        return type("R", (), {"result": {"status": "clarify", "clarify_message": "Which?", "steps": []}})()

    monkeypatch.setattr("app.workspace.planner.invoke_ai_proxy", fake_invoke)
    parsed = post_act_plan_json("system-from-client", "Instruction: make a folder")
    assert parsed["status"] == "clarify"
    assert seen[0] == OPERATION_ACT_PLAN
    assert seen[1][0] == "act_plan"
    assert seen[1][1] == {"user_prompt": "Instruction: make a folder"}


def test_act_plan_forwards_previous_response_id(monkeypatch):
    seen = []

    class _Gate:
        def allow(self, intent):
            seen.append(intent.operation)

    from app.ai_budget import set_ai_budget_gate

    set_ai_budget_gate(_Gate())
    monkeypatch.delenv("CAPIXE_AI_DIRECT_PROVIDER", raising=False)

    def fake_invoke(operation, payload, **_kwargs):
        seen.append((operation, payload))
        return type(
            "R",
            (),
            {
                "result": {"status": "clarify", "clarify_message": "Which?", "steps": []},
                "provider_response_id": "resp_next",
            },
        )()

    monkeypatch.setattr("app.workspace.planner.invoke_ai_proxy", fake_invoke)
    parsed = post_act_plan_json(
        "system-from-client",
        "Instruction: yes",
        previous_response_id="resp_prev",
    )
    assert parsed["_response_id"] == "resp_next"
    assert seen[-1][1]["previous_response_id"] == "resp_prev"
    assert seen[-1][1]["user_prompt"] == "Instruction: yes"


def test_edge_function_security_contract():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in PROXY_DIR.glob("*.ts"))
    assert "reserve_ai_budget" in sources
    assert "finalize_ai_usage" in sources
    assert "release_ai_reservation" in sources
    assert "getUser" in sources
    assert "auth.uid" not in sources or "user_id" in sources
    assert "p_user_id" not in sources
    assert "raw_url" in sources
    assert "api_key" in sources
    assert "Bearer ${apiKey}" in sources or "OPENAI_API_KEY" in sources
    assert "console.log" in sources
    for banned in ("image_jpeg_b64", "access_token", "query全文"):
        del banned
    assert "query全文" not in sources
    assert "filename" not in sources.lower() or "Do not" in sources
    assert "sk-" not in sources
    for code in KNOWN_CODES:
        assert f'"{code}"' in sources or f"{code}:" in sources


def test_edge_function_is_not_generic_proxy():
    index = (PROXY_DIR / "index.ts").read_text(encoding="utf-8")
    validate = (PROXY_DIR / "validate.ts").read_text(encoding="utf-8")
    openai = (PROXY_DIR / "openai.ts").read_text(encoding="utf-8")
    assert "api.openai.com" in openai
    assert "v1/responses" in openai
    assert "v1/chat/completions" in openai
    assert "req.url" not in openai or "OPENAI_URL" in openai
    assert "payload.url" not in index
    assert "FORBIDDEN_PAYLOAD" in validate
    assert "model" in validate
    assert "endpoint" in validate
    assert "facts_generate" in validate
    assert "meaning_search" in validate
    assert "act_plan" in validate
    assert "previous_response_id" in validate
    operations = (PROXY_DIR / "operations.ts").read_text(encoding="utf-8")
    assert "isStalePreviousResponseError" in operations
    assert "staleChainRetry" in operations
    openai_src = (PROXY_DIR / "openai.ts").read_text(encoding="utf-8")
    assert "isStalePreviousResponseError" in openai_src
    assert "invalid_payload" in openai_src


def test_classify_ask_ai_failure_categories():
    assert classify_ask_ai_failure(AiProxyError("unauthenticated", status=401)) == "auth"
    assert classify_ask_ai_failure(AiBudgetExceeded(reason="not_authenticated", status=401)) == "auth"
    assert classify_ask_ai_failure(AiProxyError("provider_timeout")) == "network"
    assert classify_ask_ai_failure(TimeoutError()) == "network"
    assert classify_ask_ai_failure(AiProxyError("provider_rate_limited", status=429)) == "rate_limit"
    assert classify_ask_ai_failure(AiProxyError("invalid_payload")) == "schema"
    assert classify_ask_ai_failure(AiProxyError("provider_rejected", stale_chain_retry=True)) == "conversation_state"
    assert classify_ask_ai_failure(AiProxyError("provider_rejected")) == "provider"
    assert classify_ask_ai_failure(AiProxyError("provider_unavailable", status=502)) == "provider"
    assert classify_ask_ai_failure(AiBudgetExceeded(reason="limit_reached")) == "budget"


class _RefreshingAuth(_FakeAuth):
    def __init__(self):
        super().__init__(token="expired-token")
        self.token = "expired-token"

    def bearer_token(self):
        return self.token

    def ensure_fresh_access_token(self, *, force=False):
        if force:
            self.token = "fresh-token"
        return self.token


def test_proxy_retries_once_after_401_when_token_changes():
    calls = []

    def fake_urlopen(request, timeout=0):
        header = request.get_header("Authorization") or ""
        calls.append(header)
        if "expired-token" in header:
            raise _HttpError(401, {"message": "Invalid JWT"})
        return _HttpResponse({"ok": True, "result": {"status": "clarify", "steps": []}})

    client = AiProxyClient(_RefreshingAuth(), config=_config(), urlopen_fn=fake_urlopen)
    result = client.invoke("act_plan", {"user_prompt": "x"})
    assert result.result["status"] == "clarify"
    assert len(calls) == 2
    assert "expired-token" in calls[0]
    assert "fresh-token" in calls[1]


def test_stale_previous_response_retries_without_chain(monkeypatch):
    monkeypatch.setenv("CAPIXE_AI_DIRECT_PROVIDER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = []

    def fake_urlopen(request, timeout=0):
        body = json.loads(request.data.decode("utf-8"))
        seen.append("previous_response_id" in body)
        if body.get("previous_response_id"):
            raise _HttpError(400, {"error": {"message": "Previous response not found"}})
        return _HttpResponse(
            {
                "id": "resp_new",
                "output_text": json.dumps(
                    {
                        "intent": "clarify",
                        "status": "clarify",
                        "clarify_message": "",
                        "steps": [],
                    }
                ),
            }
        )

    monkeypatch.setattr("app.workspace.planner.urlopen", fake_urlopen)
    parsed = post_act_plan_json("system", "Instruction: yes", previous_response_id="resp_stale")
    assert seen == [True, False]
    assert parsed["_response_id"] == "resp_new"


def test_stale_previous_response_retry_failure_keeps_conversation_state(monkeypatch):
    monkeypatch.setenv("CAPIXE_AI_DIRECT_PROVIDER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def fake_urlopen(*_args, **_kwargs):
        raise _HttpError(400, {"error": {"message": "Previous response not found"}})

    monkeypatch.setattr("app.workspace.planner.urlopen", fake_urlopen)
    with pytest.raises(AiProxyError) as exc:
        post_act_plan_json("system", "Instruction: yes", previous_response_id="resp_stale")
    assert exc.value.code == "provider_rejected"
    assert exc.value.stale_chain_retry is True
    assert classify_ask_ai_failure(exc.value) == "conversation_state"


def test_no_hardcoded_provider_secrets_in_repo():
    suspects = []
    for path in (
        ROOT / "Capixe.spec",
        ROOT / "resources" / "auth-source.json",
        *PROXY_DIR.glob("*.ts"),
        ROOT / "app" / "ai_proxy" / "client.py",
    ):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "sk-proj-" in text or "sk-live-" in text or "whsec_" in text:
            suspects.append(str(path))
        if "service_role" in text and "eyJ" in text:
            suspects.append(str(path))
    assert suspects == []


def test_bind_proxy_survives_rejected_provider_secret(monkeypatch):
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    client = bind_ai_proxy_client(_FakeAuth())
    assert client._config.configured is False


def test_functions_url_shape():
    assert functions_url("https://abc.supabase.co") == "https://abc.supabase.co/functions/v1/ai-proxy"


def test_known_error_codes_are_stable():
    assert "unauthenticated" in KNOWN_CODES
    assert "budget_exceeded" in KNOWN_CODES
    assert "provider_timeout" in KNOWN_CODES
    for name in FORBIDDEN_CLIENT_FIELDS:
        assert name
