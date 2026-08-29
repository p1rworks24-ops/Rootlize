import json
from pathlib import Path

import pytest
from PIL import Image

from app.relevance import RelevanceImage, RelevanceProviderError, rank_relevant_ids
from app.relevance.openai_provider import OpenAIImageRelevanceProvider, relevance_schema
import app.relevance.openai_provider as openai_provider


def test_relevance_requires_environment_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIImageRelevanceProvider(api_key="")
    with pytest.raises(RelevanceProviderError, match="OPENAI_API_KEY"):
        provider.classify("dog", [])


def test_relevance_schema_is_strict_and_id_bounded():
    schema = relevance_schema([4, 9])
    item = schema["properties"]["results"]["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["image_id"]["enum"] == [4, 9]
    assert "relevance_score" in item["properties"]
    assert item["properties"]["relevance_score"]["minimum"] == 0
    assert item["properties"]["relevance_score"]["maximum"] == 1
    assert set(item["required"]) == {
        "image_id", "relevant", "confidence", "relevance_score", "reason",
    }
    assert set(item["properties"]) == {
        "image_id", "relevant", "confidence", "relevance_score", "reason",
    }


def test_provider_resizes_without_modifying_source(tmp_path):
    source = tmp_path / "large.png"
    Image.new("RGB", (1200, 600), "red").save(source)
    original = source.read_bytes()
    provider = OpenAIImageRelevanceProvider(api_key="test", max_edge=512)
    data_url = provider._encode_image(source)
    assert data_url.startswith("data:image/jpeg;base64,")
    assert source.read_bytes() == original


def test_high_detail_provider_uses_high_resolution_from_original(tmp_path):
    source = tmp_path / "large.png"
    Image.new("RGB", (3000, 1500), "red").save(source)
    provider = OpenAIImageRelevanceProvider(
        api_key="test", max_edge=2048, image_detail="high"
    )
    encoded = provider._prepare_image(source)
    assert (encoded.width, encoded.height) == (2048, 1024)
    assert provider.image_detail == "high"


def test_request_includes_temperature_and_logs_reproducibility_diagnostics(
    tmp_path, monkeypatch, caplog
):
    source = tmp_path / "sample.png"
    Image.new("RGB", (640, 320), "red").save(source)
    captured = {}

    class FakeResponse:
        headers = {"x-request-id": "req_test_123"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "model": "gpt-5.4-mini-2026-08-01",
                "system_fingerprint": "fp_test",
                "choices": [{"message": {"content": json.dumps({
                    "results": [{
                        "image_id": 7, "relevant": True,
                        "confidence": 0.9, "relevance_score": 0.88, "reason": "visible",
                    }]
                })}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            }).encode("utf-8")

    def fake_urlopen(request, **_kwargs):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(openai_provider, "urlopen", fake_urlopen)
    caplog.set_level("INFO")
    provider = OpenAIImageRelevanceProvider(api_key="test", retries=0)
    run = provider.classify("dog", [RelevanceImage(7, source)])

    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["messages"][0]["content"] == openai_provider.SYSTEM_PROMPT
    assert "confirmability" in captured["payload"]["messages"][0]["content"]
    user_text = captured["payload"]["messages"][1]["content"][0]["text"].lower()
    assert "independent" in user_text
    assert "noun phrases" in user_text
    assert "compound concepts" in user_text
    schema = captured["payload"]["response_format"]["json_schema"]["schema"]
    required = schema["properties"]["results"]["items"]["required"]
    assert "relevance_score" in required
    assert "confidence" in required
    assert run.results[0].relevance_score == 0.88
    assert run.results[0].confidence == 0.9
    assert run.results[0].relevance_score != run.results[0].confidence
    assert captured["payload"]["messages"][1]["content"][-1]["image_url"]["detail"] == "low"
    assert run.input_tokens == 12
    assert run.output_tokens == 5
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "request_model=gpt-5.4-mini" in diagnostics
    assert "response_model=gpt-5.4-mini-2026-08-01" in diagnostics
    assert "request_id=req_test_123" in diagnostics
    assert "system_fingerprint=fp_test" in diagnostics
    assert "image_ids=[7]" in diagnostics
    assert "jpeg_sha256" in diagnostics
    assert "jpeg_width': 512" in diagnostics
    assert "jpeg_height': 256" in diagnostics
    assert "prompt_tokens=12 completion_tokens=5 total_tokens=17" in diagnostics


def test_structured_results_restore_requested_order():
    parsed = {
        "results": [
            {"image_id": 9, "relevant": False, "confidence": 0.8, "relevance_score": 0.1, "reason": "cat"},
            {"image_id": 4, "relevant": True, "confidence": 0.9, "relevance_score": 0.95, "reason": "dog"},
        ]
    }
    results = OpenAIImageRelevanceProvider._validate_results(parsed, [4, 9])
    assert [item.image_id for item in results] == [4, 9]
    assert results[0].relevant is True
    assert results[0].relevance_score == 0.95
    assert results[0].confidence == 0.9
    assert results[1].relevant is False
    assert results[1].relevance_score == 0.1


def test_partial_omit_keeps_judged_true_false_and_marks_unknown():
    parsed = {
        "results": [
            {"image_id": 4, "relevant": True, "confidence": 0.9, "relevance_score": 0.9, "reason": "dog"},
            {"image_id": 9, "relevant": False, "confidence": 0.8, "relevance_score": 0.1, "reason": "cat"},
        ]
    }
    results = OpenAIImageRelevanceProvider._validate_results(parsed, [4, 9, 1])
    by_id = {item.image_id: item for item in results}
    assert by_id[4].relevant is True
    assert by_id[4].relevance_score == 0.9
    assert by_id[9].relevant is False
    assert by_id[1].relevant is None
    assert by_id[1].unknown_reason == "omitted"
    assert by_id[1].relevant is not False
    assert by_id[1].relevance_score is None


class _FakeResponse:
    headers = {"x-request-id": "req_test"}

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


def _png(tmp_path, name, image_id=None):
    path = tmp_path / name
    Image.new("RGB", (64, 64), "red").save(path)
    return path


def _judgement(image_id, relevant, reason="visible", *, relevance_score=None, confidence=None):
    if relevance_score is None:
        relevance_score = 0.9 if relevant else 0.1
    if confidence is None:
        confidence = 0.9 if relevant else 0.1
    return {
        "image_id": image_id,
        "relevant": relevant,
        "confidence": confidence,
        "relevance_score": relevance_score,
        "reason": reason,
    }


def _completion(results):
    return {
        "model": "gpt-5.4-mini-2026-08-01",
        "choices": [{"message": {"content": json.dumps({"results": results})}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _requested_ids(payload):
    ids = []
    for part in payload["messages"][1]["content"]:
        text = part.get("text", "")
        if part.get("type") == "text" and text.startswith("image_id:"):
            ids.append(int(text.split(":", 1)[1]))
    return ids


class _ScriptedUrlOpen:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def __call__(self, request, **_kwargs):
        self.calls.append(json.loads(request.data.decode("utf-8")))
        if not self.payloads:
            raise AssertionError("unexpected extra Vision request")
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


def _provider(api_key="test", **kwargs):
    return OpenAIImageRelevanceProvider(
        api_key=api_key,
        retries=0,
        timeout_seconds=1,
        **kwargs,
    )


def test_batch_omit_retries_only_unknown_and_keeps_true_false(tmp_path, monkeypatch, caplog):
    paths = [_png(tmp_path, f"{image_id}.png") for image_id in (1, 2, 3)]
    images = [RelevanceImage(image_id, path) for image_id, path in zip((1, 2, 3), paths)]
    script = _ScriptedUrlOpen([
        _completion([_judgement(1, True, "dog"), _judgement(3, False, "cat")]),
        _completion([_judgement(2, True, "dog")]),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    caplog.set_level("INFO")
    run = _provider().classify("dog", images)

    assert [item.relevant for item in run.results] == [True, True, False]
    assert run.failed_image_ids == ()
    assert [_requested_ids(call) for call in script.calls] == [[1, 2, 3], [2]]
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "batch-omitted" in diagnostics
    assert "omitted_ids=[2]" in diagnostics
    assert "Vision-relevance retry image_ids=[2]" in diagnostics
    assert "kept_ids=[1, 3]" in diagnostics


def test_unknown_retry_limit_does_not_convert_to_false(tmp_path, monkeypatch, caplog):
    paths = [_png(tmp_path, f"{image_id}.png") for image_id in (4, 9)]
    images = [RelevanceImage(image_id, path) for image_id, path in zip((4, 9), paths)]
    script = _ScriptedUrlOpen([
        _completion([_judgement(4, True, "dog")]),
        _completion([]),
        _completion([]),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    caplog.set_level("INFO")
    run = _provider(unknown_retries=2).classify("dog", images)

    by_id = {item.image_id: item for item in run.results}
    assert by_id[4].relevant is True
    assert by_id[9].relevant is None
    assert by_id[9].relevant is not False
    assert by_id[9].unknown_reason == "retry_exhausted"
    assert by_id[9].relevance_score is None
    assert run.failed_image_ids == (9,)
    assert [_requested_ids(call) for call in script.calls] == [[4, 9], [9], [9]]
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "retry-exhausted" in diagnostics
    assert script.payloads == []


def test_api_failure_is_unknown_not_false(tmp_path, monkeypatch, caplog):
    from io import BytesIO
    from urllib.error import HTTPError

    path = _png(tmp_path, "1.png")
    script = _ScriptedUrlOpen([
        HTTPError("https://api.openai.com/v1/chat/completions", 500, "err", None, BytesIO(b"fail")),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    caplog.set_level("INFO")
    run = _provider(unknown_retries=0).classify("dog", [RelevanceImage(1, path)])

    assert run.results[0].relevant is None
    assert run.results[0].relevant is not False
    assert run.results[0].unknown_reason == "api_failure"
    assert run.results[0].relevance_score is None
    assert run.failed_image_ids == (1,)
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "batch-failure reason=api_failure" in diagnostics


def test_timeout_is_unknown_not_false(tmp_path, monkeypatch):
    path = _png(tmp_path, "1.png")
    script = _ScriptedUrlOpen([TimeoutError("timed out")])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    run = _provider(unknown_retries=0).classify("cat", [RelevanceImage(7, path)])
    assert run.results[0].relevant is None
    assert run.results[0].unknown_reason == "timeout"
    assert run.results[0].relevance_score is None


def test_malformed_item_does_not_drop_sibling_results(tmp_path, monkeypatch, caplog):
    paths = [_png(tmp_path, f"{image_id}.png") for image_id in (1, 2, 3)]
    images = [RelevanceImage(image_id, path) for image_id, path in zip((1, 2, 3), paths)]
    script = _ScriptedUrlOpen([
        _completion([
            _judgement(1, True, "dog"),
            "not-an-object",
            _judgement(3, False, "cat"),
        ]),
        _completion([_judgement(2, False, "unrelated")]),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    caplog.set_level("INFO")
    run = _provider().classify("dog", images)

    assert [item.relevant for item in run.results] == [True, False, False]
    assert [_requested_ids(call) for call in script.calls] == [[1, 2, 3], [2]]
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "batch-omitted" in diagnostics
    assert "omitted_ids=[2]" in diagnostics


def test_malformed_payload_retries_without_marking_false(tmp_path, monkeypatch, caplog):
    path = _png(tmp_path, "8.png")
    script = _ScriptedUrlOpen([
        {"choices": [{"message": {"content": "not-json"}}]},
        _completion([_judgement(8, True, "dog")]),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    caplog.set_level("INFO")
    run = _provider(unknown_retries=1).classify("dog", [RelevanceImage(8, path)])
    assert run.results[0].relevant is True
    assert [_requested_ids(call) for call in script.calls] == [[8], [8]]
    diagnostics = "\n".join(record.getMessage() for record in caplog.records)
    assert "batch-failure reason=malformed" in diagnostics or "batch-malformed" in diagnostics


def test_cancelled_request_does_not_retry(tmp_path, monkeypatch):
    paths = [_png(tmp_path, f"{image_id}.png") for image_id in (1, 2)]
    images = [RelevanceImage(image_id, path) for image_id, path in zip((1, 2), paths)]
    cancelled = {"value": False}
    calls = []

    def fake_urlopen(request, **_kwargs):
        calls.append(json.loads(request.data.decode("utf-8")))
        cancelled["value"] = True
        return _FakeResponse(_completion([_judgement(1, True, "dog")]))

    monkeypatch.setattr(openai_provider, "urlopen", fake_urlopen)
    run = _provider(unknown_retries=3).classify(
        "dog", images, cancelled=lambda: cancelled["value"],
    )
    by_id = {item.image_id: item for item in run.results}
    assert [_requested_ids(call) for call in calls] == [[1, 2]]
    assert by_id[1].relevant is True
    assert by_id[2].relevant is None
    assert by_id[2].relevant is not False
    assert by_id[2].unknown_reason == "omitted"


def test_dog_and_cat_complete_responses_still_separate_true_false(tmp_path, monkeypatch):
    dog, cat = _png(tmp_path, "dog.png"), _png(tmp_path, "cat.png")
    script = _ScriptedUrlOpen([
        _completion([_judgement(1, True, "dog"), _judgement(2, False, "cat")]),
    ])
    monkeypatch.setattr(openai_provider, "urlopen", script)
    run = _provider().classify(
        "dog", [RelevanceImage(1, dog), RelevanceImage(2, cat)],
    )
    assert [item.relevant for item in run.results] == [True, False]
    assert [item.relevance_score for item in run.results] == [0.9, 0.1]
    assert run.failed_image_ids == ()
    assert len(script.calls) == 1


def test_missing_relevance_score_is_unknown_not_zero_or_false():
    parsed = {
        "results": [
            {"image_id": 4, "relevant": True, "confidence": 0.9, "reason": "dog"},
            {
                "image_id": 9, "relevant": False, "confidence": 0.8,
                "relevance_score": 0.05, "reason": "unrelated",
            },
        ]
    }
    results = OpenAIImageRelevanceProvider._validate_results(parsed, [4, 9])
    by_id = {item.image_id: item for item in results}
    assert by_id[4].relevant is None
    assert by_id[4].relevant is not False
    assert by_id[4].relevance_score is None
    assert by_id[4].unknown_reason == "malformed"
    assert by_id[9].relevant is False
    assert by_id[9].relevance_score == 0.05


def test_confidence_and_relevance_score_are_separate_fields():
    parsed = {
        "results": [{
            "image_id": 1,
            "relevant": True,
            "confidence": 0.4,
            "relevance_score": 0.95,
            "reason": "primary match, low certainty",
        }]
    }
    result = OpenAIImageRelevanceProvider._validate_results(parsed, [1])[0]
    assert result.confidence == 0.4
    assert result.relevance_score == 0.95
    assert result.confidence != result.relevance_score


def test_unknown_is_not_ranked_as_score_zero():
    ordered = rank_relevant_ids(
        [1, 2, 3],
        relevant_ids={1, 3},
        relevance_scores={1: 0.4, 2: None, 3: 0.9},
        embedding_ranks={1: 1, 2: 2, 3: 3},
    )
    assert ordered == (3, 1)
    assert 2 not in ordered


def test_equal_relevance_scores_tie_break_by_embedding_rank():
    ordered = rank_relevant_ids(
        [5, 1, 9, 3],
        relevant_ids={5, 9, 3},
        relevance_scores={5: 0.7, 9: 0.7, 3: 0.7},
        embedding_ranks={5: 2, 1: 1, 9: 4, 3: 3},
    )
    assert ordered == (5, 3, 9)


def test_meaning_prompt_has_no_query_special_cases():
    text = openai_provider.SYSTEM_PROMPT.lower()
    for word in ("anime", "icon", "dog", "cat"):
        assert word not in text
    assert "confirmability" in text
    assert "every condition specified" in text
    assert "primary subject" in text
    assert "bag of words" in text
    assert "noun phrase" in text
    assert "compound concept" in text
    assert "word-by-word" in text
    assert "independent" in text
    assert openai_provider.PROMPT_VERSION == "vision-meaning-v1"


def test_legacy_object_presence_schema_does_not_require_score():
    parsed = {
        "results": [
            {"image_id": 1, "relevant": True, "confidence": 0.9, "reason": "present"},
        ]
    }
    result = OpenAIImageRelevanceProvider._validate_results(
        parsed, [1], require_relevance_score=False,
    )[0]
    assert result.relevant is True
    assert result.relevance_score is None
    schema = relevance_schema([1], include_relevance_score=False)
    assert "relevance_score" not in schema["properties"]["results"]["items"]["required"]

