from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.semantic_index.provider import IndexRun
from app.semantic_index.schema import INDEX_PROMPT_VERSION, INDEX_SCHEMA_VERSION
from app.semantic_index.scoring import PRODUCT_SEARCH_CONFIG
from tools.meaning_eval.freeform_index import (
    FREEFORM_PROMPT_VERSION,
    document_length_stats,
    freeform_include_hit,
    freeform_lexical_score,
    load_freeform_cache,
    load_or_index_paths,
    search_freeform_records,
)
from tools.meaning_eval.freeform_schema import (
    FREEFORM_PROMPT,
    FREEFORM_SCHEMA_VERSION,
    validate_freeform_payload,
)
from tools.meaning_eval.hybrid_phase_e import CAUSE_INDEX_CONTENT
from tools.meaning_eval.index_only_freeform import (
    CAUSE_MATCHING,
    CAUSE_MISSING,
    chrome_in_document,
    classify_freeform_fn,
    fn_cause_counts,
)


def test_product_semantic_index_versions_unchanged():
    assert INDEX_PROMPT_VERSION == "semantic-index-v4"
    assert INDEX_SCHEMA_VERSION == "image-semantic-index-v3"
    assert FREEFORM_PROMPT_VERSION == "semantic-index-freeform-v1"
    assert FREEFORM_SCHEMA_VERSION == "image-search-document-v1"
    assert "short summary" in FREEFORM_PROMPT.lower()
    assert "search document" in FREEFORM_PROMPT.lower()
    assert "Do not infer queries" in FREEFORM_PROMPT


def test_freeform_schema_requires_a_document():
    parsed = validate_freeform_payload(
        {"results": [{"image_id": 1, "search_document": "A brown dog sits on grass near a window."}]},
        [1],
    )
    assert parsed[0]["unknown_reason"] is None
    assert "dog" in parsed[0]["search_document"]
    empty = validate_freeform_payload(
        {"results": [{"image_id": 1, "search_document": "   "}]},
        [1],
    )
    assert empty[0]["unknown_reason"] == "malformed"
    omitted = validate_freeform_payload({"results": []}, [1, 2])
    assert [item["unknown_reason"] for item in omitted] == ["omitted", "omitted"]


def test_freeform_lexical_score_uses_document_only():
    record = {
        "search_document": (
            "Google Chrome is open to ChatGPT. A dark chat interface fills the "
            "page, with tabs and an address bar visible. A brown dog photo is "
            "incidental on the desktop wallpaper."
        )
    }
    assert freeform_lexical_score("dog", record) == 1.0
    assert freeform_lexical_score("Google Chrome", record) == 1.0
    assert freeform_lexical_score("ChatGPT", record) == 1.0
    assert freeform_lexical_score("giraffe", record) == 0.0
    assert freeform_lexical_score("dog", {"searchable_concepts": ["dog"]}) == 0.0


def test_freeform_include_hit_ignores_image_cosine():
    assert freeform_include_hit(0.0, 0.50, PRODUCT_SEARCH_CONFIG) is True
    assert freeform_include_hit(0.30, 0.40, PRODUCT_SEARCH_CONFIG) is True
    assert freeform_include_hit(0.10, 0.40, PRODUCT_SEARCH_CONFIG) is False
    assert freeform_include_hit(0.90, 0.0, PRODUCT_SEARCH_CONFIG) is False


def test_fn_classifier_splits_matching_from_missing():
    document = {
        "search_document": "A dark code editor is open. Google Chrome sits behind it."
    }
    matching = classify_freeform_fn(
        query="code editor",
        name="editor.png",
        judgement={"lex": 0.5, "txt": 0.10, "relevant": False},
        record=document,
        config=PRODUCT_SEARCH_CONFIG,
    )
    missing = classify_freeform_fn(
        query="cat",
        name="editor.png",
        judgement={"lex": 0.0, "txt": 0.05, "relevant": False},
        record=document,
        config=PRODUCT_SEARCH_CONFIG,
    )
    assert matching["cause"] == CAUSE_MATCHING
    assert missing["cause"] == CAUSE_MISSING
    counts = fn_cause_counts([matching, missing])
    assert counts[CAUSE_MATCHING] == 1
    assert counts[CAUSE_MISSING] == 1
    assert CAUSE_INDEX_CONTENT not in counts


def test_chrome_product_vs_browser_chrome_phrase():
    product = chrome_in_document({
        "search_document": "ChatGPT is open inside a Google Chrome window."
    })
    ui_only = chrome_in_document({
        "search_document": "A YouTube broadcast fills the page. The browser chrome is visible at the top."
    })
    assert product["has_product_name"] is True
    assert ui_only["has_product_name"] is False
    assert ui_only["has_ui_chrome_only"] is True


def test_freeform_cache_rejects_v4_payload(tmp_path: Path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps({
        "prompt_version": "semantic-index-v4",
        "schema_version": "image-semantic-index-v3",
        "usage": {},
        "by_name": {"a.png": {"search_document": "dog"}},
    }), encoding="utf-8")
    assert load_freeform_cache(path) is None


def test_load_or_index_paths_reuses_fresh_cache(tmp_path: Path):
    image = tmp_path / "dog.png"
    Image.new("RGB", (24, 16), "red").save(image)
    cache = tmp_path / "cache.json"
    calls = []

    class FakeProvider:
        def index(self, images, *, cancelled=None):
            calls.append([item.path.name for item in images])
            results = []
            for item in images:
                results.append({
                    "image_id": item.image_id,
                    "search_document": (
                        "A red test image used as a placeholder photograph. "
                        "The frame is empty of UI, logos, or readable text."
                    ),
                    "unknown_reason": None,
                })
            return IndexRun(results=tuple(results), input_tokens=8, output_tokens=12)

    records, usage, reused = load_or_index_paths(
        [image], cache, provider=FakeProvider(),
    )
    assert reused is False
    assert "dog.png" in records
    assert usage["input_tokens"] == 8
    records2, _, reused2 = load_or_index_paths(
        [image], cache, provider=FakeProvider(),
    )
    assert reused2 is True
    assert records2["dog.png"]["search_document"] == records["dog.png"]["search_document"]
    assert calls == [["dog.png"]]


def test_search_freeform_records_is_deterministic():
    records = {
        "a.png": {"search_document": "A sitting brown dog on grass."},
        "b.png": {"search_document": "A mountain wallpaper on a Windows desktop."},
    }
    text_vectors = {
        "a.png": [1.0] + [0.0] * 511,
        "b.png": [0.0, 1.0] + [0.0] * 510,
    }
    query_vector = [1.0] + [0.0] * 511
    first = search_freeform_records(
        "dog",
        ["b.png", "a.png"],
        records,
        query_vector=query_vector,
        text_vectors=text_vectors,
        config=PRODUCT_SEARCH_CONFIG,
    )
    second = search_freeform_records(
        "dog",
        ["b.png", "a.png"],
        records,
        query_vector=query_vector,
        text_vectors=text_vectors,
        config=PRODUCT_SEARCH_CONFIG,
    )
    assert first["predicted"] == ["a.png"]
    assert first["predicted"] == second["predicted"]


def test_document_length_stats_flags_short_captions():
    stats = document_length_stats({
        "short.png": {"search_document": "A dog."},
        "long.png": {"search_document": " ".join(["visible content"] * 120)},
    })
    assert stats["too_short_images"] == 1
    assert stats["images"] == 2
