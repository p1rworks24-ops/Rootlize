"""API budget gate runs immediately before an outbound AI HTTP request."""

from __future__ import annotations

import pytest

from app.ai_budget import (
    KIND_TEXT_LLM,
    KIND_VISION,
    OPERATION_FACTS_GENERATE,
    OPERATION_MEANING_SEARCH,
    AiBudgetExceeded,
    AiRequestIntent,
    AllowAllAiBudgetGate,
    check_ai_budget,
    reset_ai_budget_gate_for_tests,
    set_ai_budget_gate,
)
from app.image_facts.provider import ImageFactsProvider
from app.image_facts.search import ImageFactsSearchMatcher
from app.relevance.openai_provider import OpenAIImageRelevanceProvider


@pytest.fixture(autouse=True)
def _reset_budget_gate():
    reset_ai_budget_gate_for_tests()
    yield
    reset_ai_budget_gate_for_tests()


class _BlockingGate:
    def __init__(self):
        self.intents: list[AiRequestIntent] = []

    def allow(self, intent: AiRequestIntent) -> None:
        self.intents.append(intent)
        raise AiBudgetExceeded("blocked")


def test_default_gate_allows_requests():
    check_ai_budget(AiRequestIntent(operation="meaning_search", kind="text_llm", model="x"))


def test_facts_and_search_providers_expose_budget_operations():
    assert ImageFactsProvider.budget_operation == OPERATION_FACTS_GENERATE
    assert ImageFactsProvider.budget_kind == KIND_VISION
    assert ImageFactsSearchMatcher.budget_operation == OPERATION_MEANING_SEARCH
    assert ImageFactsSearchMatcher.budget_kind == KIND_TEXT_LLM
    assert OpenAIImageRelevanceProvider.budget_operation == "other"


def test_budget_check_runs_before_http(monkeypatch):
    gate = _BlockingGate()
    set_ai_budget_gate(gate)
    opened = []

    def fake_urlopen(*_args, **_kwargs):
        opened.append(1)
        raise AssertionError("HTTP must not run after a budget denial")

    monkeypatch.setattr("app.relevance.openai_provider.urlopen", fake_urlopen)
    matcher = ImageFactsSearchMatcher(api_key="test", retries=0, timeout_seconds=1)
    with pytest.raises(AiBudgetExceeded, match="blocked"):
        matcher._post_with_retry({"model": "gpt-test", "messages": []})
    assert opened == []
    assert len(gate.intents) == 1
    assert gate.intents[0].operation == OPERATION_MEANING_SEARCH
    assert gate.intents[0].kind == KIND_TEXT_LLM
    assert gate.intents[0].model == "gpt-test"


def test_facts_provider_budget_denial_does_not_send_http(monkeypatch, tmp_path):
    from PIL import Image

    from app.relevance import RelevanceImage

    gate = _BlockingGate()
    set_ai_budget_gate(gate)
    opened = []
    monkeypatch.setattr(
        "app.relevance.openai_provider.urlopen",
        lambda *_args, **_kwargs: opened.append(1),
    )
    path = tmp_path / "one.png"
    Image.new("RGB", (32, 24), "red").save(path)
    provider = ImageFactsProvider(api_key="test", retries=0, timeout_seconds=1, unknown_retries=0)
    with pytest.raises(AiBudgetExceeded):
        provider.index([RelevanceImage(1, path)])
    assert opened == []
    assert gate.intents[0].operation == OPERATION_FACTS_GENERATE
    assert gate.intents[0].kind == KIND_VISION


def test_allow_all_gate_can_be_restored():
    set_ai_budget_gate(_BlockingGate())
    with pytest.raises(AiBudgetExceeded):
        check_ai_budget(AiRequestIntent(operation="other", kind="vision"))
    set_ai_budget_gate(AllowAllAiBudgetGate())
    check_ai_budget(AiRequestIntent(operation="other", kind="vision"))
