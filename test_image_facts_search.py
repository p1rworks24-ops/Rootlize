from __future__ import annotations

import json

import pytest

from app.image_facts.schema import FACTS_SHORTLIST_SIZE, SEARCH_PROMPT_VERSION
from app.image_facts.search import ImageFactsSearchMatcher
from app.ui.images_search import VisionRelevanceImagesSearchProvider, vision_candidate_chunk_sizes

from test_image_facts_contracts import _app, _entity, _facts
from test_progressive_vision_search import _MockRelevance, _provider, _sample_facts


def test_openclip_shortlist_is_forty_then_facts_chunks():
    sizes = vision_candidate_chunk_sizes(FACTS_SHORTLIST_SIZE)
    assert sizes[0] == 8
    assert sum(sizes) == 40
    assert all(size <= 8 for size in sizes)


def test_search_uses_openclip_shortlist_not_full_library(monkeypatch, tmp_path):
    matcher = _MockRelevance({1})
    provider, candidates = _provider(monkeypatch, tmp_path, 80, matcher)
    paths = provider.search_progressive("dog", tmp_path, candidates)
    judged = [item for chunk in matcher.calls for item in chunk]
    assert judged == list(range(1, 41))
    assert [int(path.stem) for path in paths] == [1]
    assert provider.last_run.sent_image_count == 0
    assert provider.last_vision_request_count == 0


def test_search_skips_images_without_facts(monkeypatch, tmp_path):
    matcher = _MockRelevance({2, 3})
    provider, candidates = _provider(monkeypatch, tmp_path, 3, matcher, facts_ids=(2,))
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert [item for chunk in matcher.calls for item in chunk] == [2]
    assert [path.stem for path in paths] == ["2"]
    assert provider.last_vision_request_count == 0


def test_facts_matcher_sends_text_only_and_applies_contracts(monkeypatch):
    matcher = ImageFactsSearchMatcher(api_key="test", retries=0, timeout_seconds=1)
    posts = []
    record = _facts(
        entities=[_entity("Google Chrome", attributes=["taskbar icon"])],
    )
    record["image_id"] = 1

    def fake_post(self, payload, *, image_diagnostics=()):
        posts.append(payload)
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "results": [{
                            "image_id": 1,
                            "reason": "icon present",
                            "independent_conditions": [
                                {"condition": "Google Chrome", "confirmed": True, "evidence": "taskbar icon"},
                            ],
                        }]
                    })
                }
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    monkeypatch.setattr(ImageFactsSearchMatcher, "_post_with_retry", fake_post)
    run = matcher.match_records("Google Chrome", [record])
    assert len(posts) == 1
    user = posts[0]["messages"][1]["content"]
    assert isinstance(user, str)
    assert "image_url" not in json.dumps(posts[0])
    assert run.sent_image_count == 0
    assert run.request_count == 1
    assert run.results[0].relevant is True
    assert matcher.prompt_version == SEARCH_PROMPT_VERSION


def test_facts_matcher_rejects_weak_mention_after_llm_true(monkeypatch):
    matcher = ImageFactsSearchMatcher(api_key="test", retries=0, timeout_seconds=1)
    record = _facts(notable_text=["Chrome"])
    record["image_id"] = 7

    def fake_post(self, payload, *, image_diagnostics=()):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "results": [{
                            "image_id": 7,
                            "reason": "text says Chrome",
                            "independent_conditions": [
                                {"condition": "Google Chrome", "confirmed": True, "evidence": "notable_text Chrome"},
                            ],
                        }]
                    })
                }
            }],
            "usage": {},
        }

    monkeypatch.setattr(ImageFactsSearchMatcher, "_post_with_retry", fake_post)
    run = matcher.match_records("Google Chrome", [record])
    assert run.sent_image_count == 0
    assert run.results[0].relevant is False


def test_create_meaning_search_provider_wires_facts_lookup():
    from app.ui.images_search import create_meaning_search_provider

    lookup = lambda image_ids: {1: _sample_facts(1)}
    matcher = _MockRelevance({1})
    provider = create_meaning_search_provider(facts_matcher=matcher, facts_lookup=lookup)
    assert isinstance(provider, VisionRelevanceImagesSearchProvider)
    assert provider.facts_matcher is matcher
    assert provider.facts_lookup is lookup


def test_search_normalizes_library_search_wrappers(monkeypatch, tmp_path):
    matcher = _MockRelevance({1})
    seen_queries = []
    original = matcher.match_records

    def capture(query, records, cancelled=None):
        seen_queries.append(query)
        return original(query, records, cancelled=cancelled)

    matcher.match_records = capture
    provider, candidates = _provider(monkeypatch, tmp_path, 3, matcher)
    provider.search_progressive(
        "search for google chrome images from this folder", tmp_path, candidates,
    )
    assert provider.last_raw_query == "search for google chrome images from this folder"
    assert provider.last_query_target == "google chrome"
    assert seen_queries == ["google chrome"]


def test_search_does_not_call_vision_classify(monkeypatch, tmp_path):
    class ForbiddenVision(_MockRelevance):
        def classify(self, query, images, cancelled=None):
            raise AssertionError("search must not send images")

    matcher = ForbiddenVision({1})
    provider, candidates = _provider(monkeypatch, tmp_path, 1, matcher)
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert [path.stem for path in paths] == ["1"]
    assert provider.last_vision_request_count == 0
