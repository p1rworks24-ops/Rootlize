"""Product Semantic Index Hybrid gate for Ask AI / Meaning Search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.catalog import MODEL_IDS, OPENCLIP_MODEL_KEY
from app.semantic.embedding import encode_embedding
from app.semantic.models import SourceSnapshot
from app.semantic_index.gate import (
    REASON_GATE_FAILURE,
    REASON_UNAVAILABLE,
    split_meaning_candidates,
)
from app.semantic_index.hybrid import (
    DECISION_NEGATIVE,
    DECISION_POSITIVE,
    DECISION_UNCERTAIN,
    PRODUCT_HYBRID_BAND,
    PRODUCT_SEARCH_CONFIG,
    RESCUE_COMPOUND,
    RESCUE_HIGH_TXT,
    decide_hybrid,
    decide_product_hybrid,
)
from app.semantic_index.models import SemanticIndexState, default_index_identity
from app.semantic_index.repository import SemanticIndexRepository
from app.semantic_index.scoring import lexical_score
from app.semantic_index.service import SemanticIndexService
from app.semantic_index.schema import index_record
from app.ui.images_search import VisionRelevanceImagesSearchProvider

from test_progressive_vision_search import _MockFactsMatcher, _MockRelevance, _provider
from test_semantic_index import IDENTITY, NOW, add_image, sample_record


@pytest.fixture
def repositories(tmp_path):
    database = OCRDatabase(tmp_path / "hybrid.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database)
    indexes = SemanticIndexRepository(database)
    yield database, images, indexes
    database.close()

ROOT = Path(__file__).resolve().parent
PHASE_E_RESULTS = ROOT / "artifacts" / "meaning-eval" / "runs" / "semantic-index-hybrid-phase-e" / "results.json"
INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-v1.json"
RANKING_MODEL_ID = MODEL_IDS[OPENCLIP_MODEL_KEY]


def _axis(index: int, dim: int = 512) -> tuple[float, ...]:
    values = [0.0] * dim
    values[index] = 1.0
    return tuple(values)


def _blob(index: int) -> bytes:
    return encode_embedding(_axis(index), dimension=512)


def _store(indexes, image, record, axis: int):
    indexes.upsert_index(
        image.image_id,
        record,
        _blob(axis),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )


def _split(indexes, query, candidates, query_axis=0, ranking_model_id=RANKING_MODEL_ID):
    return split_meaning_candidates(
        query=query,
        query_vector=_axis(query_axis),
        candidates=candidates,
        repository=indexes,
        identity=IDENTITY,
        ranking_model_id=ranking_model_id,
    )


def _miss_record():
    return index_record(
        visual_summary="A mountain landscape at dusk",
        objects_entities=["mountain"],
        scene_environment="outdoor range",
        media_type="photograph",
        searchable_concepts=["mountain", "landscape"],
        ui_interface_concepts=[],
        visual_attributes=["sunset"],
        visible_activities=[],
        incidental_notes="",
    )


def _dark_record():
    return index_record(
        visual_summary="A dark file manager window",
        objects_entities=[],
        scene_environment="desktop",
        media_type="screenshot",
        searchable_concepts=["file manager"],
        ui_interface_concepts=["file manager"],
        visual_attributes=["dark theme"],
        visible_activities=[],
        incidental_notes="",
    )


def test_fresh_clear_negative_is_not_sent_to_vision(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "skip.png")
    _store(indexes, image, _miss_record(), axis=1)
    split = _split(indexes, "dog", ((image.image_id, 0.10),))
    assert split.negative_ids == (image.image_id,)
    assert split.vision_ids == ()
    assert split.positive_ids == ()
    assert split.decisions[image.image_id] == DECISION_NEGATIVE


def test_uncertain_is_sent_to_vision(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "maybe.png")
    _store(indexes, image, sample_record(), axis=1)
    split = _split(indexes, "dog", ((image.image_id, 0.20),))
    assert image.image_id in split.vision_ids
    assert image.image_id not in split.negative_ids
    assert split.decisions[image.image_id] == DECISION_UNCERTAIN
    assert split.decisions[image.image_id] != DECISION_POSITIVE


def test_high_text_embedding_rescue_is_sent_not_auto_positive(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "rescue-txt.png")
    sim = 0.72
    other = (1.0 - sim * sim) ** 0.5
    text_values = [0.0] * 512
    text_values[0] = sim
    text_values[1] = other
    indexes.upsert_index(
        image.image_id,
        _miss_record(),
        encode_embedding(text_values, dimension=512),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    split = _split(indexes, "dog", ((image.image_id, 0.10),), query_axis=0)
    assert image.image_id in split.vision_ids
    assert split.positive_ids == ()
    assert split.decisions[image.image_id] == DECISION_UNCERTAIN
    assert split.reasons[image.image_id] == RESCUE_HIGH_TXT


def test_compound_concept_rescue_is_sent_not_auto_positive(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dark.png")
    _store(indexes, image, _dark_record(), axis=1)
    split = _split(
        indexes,
        "dark themed application",
        ((image.image_id, 0.20),),
        query_axis=0,
    )
    assert image.image_id in split.vision_ids
    assert split.positive_ids == ()
    assert split.decisions[image.image_id] == DECISION_UNCERTAIN
    assert split.reasons[image.image_id] == RESCUE_COMPOUND


def test_frozen_band_does_not_auto_accept_index_positive():
    judgement = {"lex": 1.0, "txt": 1.0, "img": 1.0}
    assert decide_hybrid(judgement, PRODUCT_HYBRID_BAND, PRODUCT_SEARCH_CONFIG) != DECISION_POSITIVE
    assert decide_product_hybrid(judgement) == DECISION_UNCERTAIN


def test_missing_index_falls_back_to_vision(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "pending.png")
    split = _split(indexes, "dog", ((image.image_id, 0.40),))
    assert split.vision_ids == (image.image_id,)
    assert split.negative_ids == ()
    assert split.reasons[image.image_id] == REASON_UNAVAILABLE


def test_stale_index_falls_back_to_vision(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "stale.png", fingerprint="same")
    _store(indexes, image, _miss_record(), axis=1)
    images.upsert_image(
        image.path,
        size_bytes=image.size_bytes + 10,
        mtime_ns=image.mtime_ns + 1,
        quick_fingerprint="changed",
    )
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.STALE
    split = _split(indexes, "dog", ((image.image_id, 0.10),))
    assert split.vision_ids == (image.image_id,)
    assert split.negative_ids == ()


def test_corrupt_index_falls_back_to_vision(repositories, tmp_path):
    database, images, indexes = repositories
    image = add_image(images, tmp_path, "corrupt.png")
    _store(indexes, image, _miss_record(), axis=1)
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    database.connection.execute(
        "UPDATE semantic_indexes SET text_embedding=? WHERE image_id=?",
        (b"short", image.image_id),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")
    split = _split(indexes, "dog", ((image.image_id, 0.10),))
    assert split.vision_ids == (image.image_id,)
    assert split.negative_ids == ()


def test_gate_failure_falls_back_without_dropping_candidates():
    class _Boom:
        def classify(self, *_args, **_kwargs):
            raise RuntimeError("db exploded")

    split = split_meaning_candidates(
        query="dog",
        query_vector=_axis(0),
        candidates=((11, 0.10), (12, 0.90)),
        repository=_Boom(),
        identity=IDENTITY,
        ranking_model_id=RANKING_MODEL_ID,
    )
    assert split.vision_ids == (11, 12)
    assert split.negative_ids == ()
    assert set(split.reasons.values()) == {REASON_GATE_FAILURE}


def test_missing_query_vector_falls_back_to_vision(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "fresh.png")
    _store(indexes, image, _miss_record(), axis=1)
    split = split_meaning_candidates(
        query="dog",
        query_vector=None,
        candidates=((image.image_id, 0.10),),
        repository=indexes,
        identity=IDENTITY,
        ranking_model_id=RANKING_MODEL_ID,
    )
    assert split.vision_ids == (image.image_id,)
    assert split.negative_ids == ()


def test_gate_does_not_generate_indexes(repositories, tmp_path, monkeypatch):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "pending.png")

    def fail_index(*_args, **_kwargs):
        raise AssertionError("Hybrid gate must not wait for index generation")

    monkeypatch.setattr(SemanticIndexService, "index_images", fail_index)
    split = _split(indexes, "dog", ((image.image_id, 0.50),))
    assert split.vision_ids == (image.image_id,)
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.PENDING


def test_second_lookup_reuses_fresh_index(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "reuse.png")
    _store(indexes, image, _miss_record(), axis=1)
    first = _split(indexes, "dog", ((image.image_id, 0.10),))
    second = _split(indexes, "dog", ((image.image_id, 0.10),))
    assert first.negative_ids == second.negative_ids == (image.image_id,)
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FRESH


def test_folder_candidates_do_not_mix_other_indexes(repositories, tmp_path):
    _, images, indexes = repositories
    folder_a = tmp_path / "A"
    folder_b = tmp_path / "B"
    folder_a.mkdir()
    folder_b.mkdir()
    old = add_image(images, folder_a, "old.png")
    current = add_image(images, folder_b, "current.png")
    _store(indexes, old, _miss_record(), axis=1)
    split = _split(indexes, "dog", ((current.image_id, 0.40),))
    assert old.image_id not in split.decisions
    assert split.vision_ids == (current.image_id,)


def test_mismatch_ranking_model_falls_back(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "fresh.png")
    _store(indexes, image, _miss_record(), axis=1)
    split = _split(
        indexes, "dog", ((image.image_id, 0.10),), ranking_model_id="other-model"
    )
    assert split.vision_ids == (image.image_id,)
    assert split.negative_ids == ()


def test_provider_matches_shortlist_facts_and_skips_pending(monkeypatch, tmp_path):
    matcher = _MockFactsMatcher({2})
    provider, candidates = _provider(monkeypatch, tmp_path, 2, matcher, facts_ids=(2,))
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert [item for chunk in matcher.calls for item in chunk] == [2]
    assert [path.name for path in paths] == ["2.png"]
    assert provider.last_vision_request_count == 0


def test_provider_without_facts_sends_no_vision_and_returns_empty(monkeypatch, tmp_path):
    matcher = _MockFactsMatcher()
    provider, candidates = _provider(monkeypatch, tmp_path, 3, matcher, facts_ids=())
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert matcher.calls == []
    assert paths == ()
    assert provider.last_run.sent_image_count == 0
    assert provider.last_vision_request_count == 0


def test_eval_and_product_hybrid_are_the_same_function():
    from tools.meaning_eval.hybrid import decide_hybrid as eval_decide
    from tools.meaning_eval.hybrid_phase_e import FROZEN_BAND
    from tools.meaning_eval.semantic_index import PRIMARY_SEARCH, SEARCH_CONFIGS, lexical_score as eval_lex

    assert eval_decide is decide_hybrid
    assert FROZEN_BAND is PRODUCT_HYBRID_BAND
    assert PRIMARY_SEARCH == PRODUCT_SEARCH_CONFIG.name
    assert SEARCH_CONFIGS[0] is PRODUCT_SEARCH_CONFIG
    assert eval_lex is lexical_score
    assert default_index_identity().vision_model == IDENTITY.vision_model


def test_phase_e_artifact_decisions_match_product_hybrid():
    payload = json.loads(PHASE_E_RESULTS.read_text(encoding="utf-8"))
    cache = json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
    records = cache["by_name"]
    new_fns = payload.get("new_fns") or []
    assert new_fns, "Phase E artifact is missing new_fns"
    matched = 0
    for item in new_fns:
        judgement = {
            "lex": item["lex"],
            "txt": item["txt"],
            "img": item["img"],
        }
        record = item.get("index") or records.get(item["name"])
        decision = decide_product_hybrid(
            judgement, query=item["query"], record=record,
        )
        assert decision == item["decision"], (
            f"{item['query']} / {item['name']}: product={decision} "
            f"phase_e={item['decision']}"
        )
        matched += 1
    cache_pairs = 0
    lex_matches = 0
    from tools.meaning_eval.dataset import load_dataset
    from tools.meaning_eval.hybrid import decide_hybrid as eval_decide
    from tools.meaning_eval.semantic_index import lexical_score as eval_lex

    dataset = load_dataset()
    for spec in dataset.queries:
        for name, record in records.items():
            cache_pairs += 1
            product_lex = lexical_score(spec.query, record)
            eval_value = eval_lex(spec.query, record)
            if product_lex == eval_value:
                lex_matches += 1
            for txt, img in ((0.0, 0.0), (0.20, 0.20), (0.70, 0.25), (1.0, 1.0)):
                judgement = {"lex": product_lex, "txt": txt, "img": img}
                product = decide_product_hybrid(
                    judgement, query=spec.query, record=record,
                )
                evaluated = eval_decide(
                    judgement,
                    PRODUCT_HYBRID_BAND,
                    PRODUCT_SEARCH_CONFIG,
                    query=spec.query,
                    record=record,
                )
                assert product == evaluated
    assert matched == len(new_fns)
    assert lex_matches == cache_pairs
    remaining = [
        item for item in new_fns
        if item["query"] == "image gallery" and item["name"] == "20260801_132030.png"
    ]
    assert remaining
    assert remaining[0]["decision"] == DECISION_NEGATIVE


def test_images_search_does_not_import_eval_hybrid():
    source = Path("app/ui/images_search.py").read_text(encoding="utf-8")
    assert "tools.meaning_eval" not in source
    assert "ProgressiveSemanticIndexer" not in source
    assert "split_meaning_candidates" not in source
    assert "match_records" in source
