from pathlib import Path

from app.relevance import RelevanceResult, RelevanceRun
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.failure import classify_false_negative, classify_false_positive
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.metrics import (
    end_to_end_counts,
    mean_reciprocal_rank,
    recall_at_k,
    recall_from_ranks,
    summarize_end_to_end,
    summarize_retriever,
)
from tools.meaning_eval.pipeline import candidate_chunk_sizes, judge_ranked_paths
from tools.meaning_eval.report import compare_runs, render_summary
from tools.meaning_eval.scoring import end_to_end_row, retriever_row
from tools.retriever_eval import evaluate_ranking
from tools.vision_judge_ab_eval import DEV_QUERIES, load_labels, split_queries


class _FakeProvider:
    def __init__(self, relevant_ids=(), *, fail_ids=(), scores=None, unknown_ids=None):
        self.relevant_ids = set(relevant_ids)
        self.fail_ids = set(fail_ids)
        self.unknown_ids = set(unknown_ids or ())
        self.scores = dict(scores or {})
        self.calls = []

    def classify(self, _query, images, cancelled=None):
        ids = tuple(item.image_id for item in images)
        self.calls.append(ids)
        failed = tuple(value for value in ids if value in self.fail_ids)
        results = []
        for item in images:
            if item.image_id in self.fail_ids:
                continue
            if item.image_id in self.unknown_ids:
                results.append(RelevanceResult(
                    item.image_id, None, 0.0, unknown_reason="omitted",
                ))
                continue
            relevant = item.image_id in self.relevant_ids
            results.append(RelevanceResult(
                item.image_id,
                relevant,
                0.9 if relevant else 0.1,
                reason="ok" if relevant else "no",
                relevance_score=self.scores.get(item.image_id, 0.9 if relevant else 0.1),
            ))
        return RelevanceRun(results=tuple(results), failed_image_ids=failed)


def test_dev_and_holdout_are_disjoint_and_explicit():
    dataset = load_dataset()
    splits = dataset.by_split()
    dev = {spec.query for spec in splits["dev"]}
    holdout = {spec.query for spec in splits["holdout"]}
    assert dev and holdout
    assert not (dev & holdout)
    assert all(spec.split in {"dev", "holdout"} for spec in dataset.queries)
    kinds = {spec.kind for spec in dataset.queries}
    assert kinds >= {
        "object", "person", "place", "ui", "style", "color", "activity", "state", "abstract",
    }
    labels = load_labels(Path("tools/semantic_search_benchmark/real_images/queries.json"))
    legacy = split_queries(list(labels))
    assert not set(legacy["dev"]) & set(legacy["holdout"])
    assert set(legacy["dev"]) <= dev
    assert "login screen" in holdout
    assert "folder selection screen" in holdout
    assert "dog" in DEV_QUERIES


def test_recall_at_k_and_mrr_match_fixed_ranking():
    relevant = {"hero-icon.png", "app-icon.png"}
    ranking = [
        "unrelated.png", "hero-icon.png", "other.png", "app-icon.png",
        *([f"pad-{index}.png" for index in range(40)]),
    ]
    assert recall_at_k(relevant, ranking, 10) == 1.0
    assert recall_at_k({"hero-icon.png"}, ranking, 1) == 0.0
    assert mean_reciprocal_rank(relevant, ranking) == 0.5
    row = evaluate_ranking("icon", relevant, ranking, "dev")
    assert row["best_relevant_rank"] == 2
    assert summarize_retriever([row])["mrr"] == 0.5
    assert recall_from_ranks({"a.png": 2, "b.png": 12}, 10) == 0.5
    assert recall_from_ranks({}, 10) == 1.0
    scored = retriever_row(
        load_dataset().spec("dog"),
        [
            "images.jpg",
            "A2.png",
            "20260813_225929.png",
            "20260815_221055.png",
            "20260815_231828.png",
        ],
    )
    assert scored["recall_at_20"] == 1.0
    assert scored["worst_relevant_rank"] == 5


def test_precision_recall_ignore_acceptable_on_both_sides():
    counts = end_to_end_counts(
        must_include={"must.png"},
        acceptable={"gray.png"},
        predicted={"must.png", "gray.png", "noise.png"},
    )
    assert counts["tp"] == 1
    assert counts["fp"] == 1
    assert counts["fn"] == 0
    assert counts["fp_names"] == ["noise.png"]
    assert counts["acceptable_hits"] == ["gray.png"]
    assert counts["precision"] == 0.5
    assert counts["recall"] == 1.0
    missed = end_to_end_counts(
        must_include={"must.png"},
        acceptable={"gray.png"},
        predicted=set(),
    )
    assert missed["fn"] == 1
    assert missed["tp"] == 0
    assert missed["recall"] == 0.0
    empty_positive = end_to_end_counts(
        must_include=set(),
        acceptable={"gray.png"},
        predicted={"gray.png"},
    )
    assert empty_positive["tp"] == 0
    assert empty_positive["fp"] == 0
    assert empty_positive["fn"] == 0
    assert empty_positive["precision"] == 1.0
    assert empty_positive["recall"] == 1.0


def test_micro_macro_end_to_end_aggregates():
    first = end_to_end_counts(
        must_include={"a.png"}, acceptable=set(), predicted={"a.png", "b.png"},
    )
    second = end_to_end_counts(
        must_include={"c.png", "d.png"}, acceptable=set(), predicted={"c.png"},
    )
    summary = summarize_end_to_end([first, second])
    assert summary["micro_tp"] == 2
    assert summary["micro_fp"] == 1
    assert summary["micro_fn"] == 1
    assert summary["micro_precision"] == 2 / 3
    assert summary["micro_recall"] == 2 / 3
    assert summary["macro_precision"] == (0.5 + 1.0) / 2
    assert summary["macro_recall"] == (1.0 + 0.5) / 2


def test_failure_mode_classification_uses_runtime_fields():
    ranking = ["keep.png", "miss.png", "unknown.png", "fail.png", "skip.png"]
    assert classify_false_negative(
        "absent.png", ranking=ranking, judgement=None, embedded_names=set(ranking),
    ) == "not_embedded"
    assert classify_false_negative(
        "skip.png",
        ranking=ranking,
        judgement=None,
        cancelled=True,
        embedded_names=set(ranking),
    ) == "cancelled_unjudged"
    assert classify_false_negative(
        "fail.png",
        ranking=ranking,
        judgement=None,
        failed_names={"fail.png"},
        embedded_names=set(ranking),
    ) == "batch_fail"
    assert classify_false_negative(
        "unknown.png",
        ranking=ranking,
        judgement={"relevant": None, "unknown_reason": "retry_exhausted"},
        embedded_names=set(ranking),
    ) == "unknown_after_retry"
    assert classify_false_negative(
        "skip.png",
        ranking=ranking,
        judgement=None,
        embedded_names=set(ranking),
    ) == "retrieval_miss"
    assert classify_false_negative(
        "miss.png",
        ranking=ranking,
        judgement={"relevant": False, "reason": "not useful"},
        embedded_names=set(ranking),
    ) == "judge_fn"
    assert classify_false_positive(
        "noise.png", judgement={"relevant": True, "relevance_score": 0.2},
    ) == "judge_fp"
    assert classify_false_negative(
        "odd.png",
        ranking=["odd.png"],
        judgement={"relevant": True},
        embedded_names={"odd.png"},
    ) == "unclassified"


def test_false_negative_details_include_rank_judge_and_mode():
    spec = load_dataset().spec("dog")
    ranking = [
        "images.jpg", "noise.png", "A2.png", "20260813_225929.png",
        "20260815_221055.png", "20260815_231828.png",
    ]
    row = end_to_end_row(
        spec,
        ranking=ranking,
        predicted=[
            "images.jpg", "20260813_225929.png",
            "20260815_221055.png", "20260815_231828.png",
        ],
        judgements={
            "images.jpg": {"relevant": True, "relevance_score": 0.9, "low_relevant": True, "high_relevant": True},
            "20260813_225929.png": {"relevant": True, "relevance_score": 0.8, "low_relevant": True, "high_relevant": True},
            "20260815_221055.png": {"relevant": True, "relevance_score": 0.9, "low_relevant": True, "high_relevant": True},
            "20260815_231828.png": {"relevant": True, "relevance_score": 0.9, "low_relevant": True, "high_relevant": True},
            "A2.png": {
                "relevant": False, "relevance_score": 0.1, "low_relevant": False,
                "high_relevant": None, "reason": "not a useful dog result",
                "high_skipped_reason": "low_false",
            },
        },
    )
    assert row["fn"] == 1
    detail = row["false_negatives"][0]
    assert detail["name"] == "A2.png"
    assert detail["retrieval_rank"] == 3
    assert detail["vision"]["relevant"] is False
    assert detail["vision"]["low_relevant"] is False
    assert detail["failure_mode"] == "judge_fn"


def test_run_identity_records_query_and_gt_hashes(tmp_path):
    dataset = load_dataset()
    image = tmp_path / "A2.png"
    image.write_bytes(b"png")
    corpus = corpus_identity([image])
    identity = build_identity(dataset=dataset, corpus=corpus)
    assert identity["query_set_version"] == dataset.query_set_version
    assert identity["gt_version"] == dataset.gt_version
    assert identity["query_set_hash"] == dataset.query_set_hash
    assert identity["gt_hash"] == dataset.gt_hash
    assert len(identity["query_set_hash"]) == 64
    assert identity["retrieval_model_id"] == "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
    assert identity["query_embedding"] == "raw"
    assert identity["vision_prompt_version"]
    assert identity["vision_schema_version"]
    assert identity["corpus_count"] == 1


def test_gt_corrections_match_pixels_not_current_results():
    dataset = load_dataset()
    login = dataset.spec("login screen")
    assert login.must_include == ()
    assert login.must_exclude_set == {"20260721_210812.png", "20260729_234504.png"}
    folder = dataset.spec("folder selection screen")
    assert "20260718_163013.png" in folder.must_exclude_set
    assert "20260720_233733.png" in folder.must_exclude_set
    assert folder.must_include_set == {
        "20260811_113411.png", "20260811_112305.png", "20260811_113536.png",
        "20260811_125253.png", "20260811_174317.png", "20260816_204701_001.png",
        "20260815_235357.png", "20260816_180634_001.png", "20260817_140337_001.png",
    }
    labels = load_labels(Path("tools/semantic_search_benchmark/real_images/queries.json"))
    assert labels["login screen"] == set()
    code_editor = dataset.spec("code editor")
    assert {"20260718_201711.png", "20260718_201716.png", "20260718_201717.png"} <= code_editor.must_exclude_set
    assert dataset.spec("software installation screen").must_include == ()
    assert {"20260721_203931.png", "20260721_203957.png"} <= dataset.spec("software installation screen").must_exclude_set
    error = dataset.spec("application error message")
    assert {"20260718_175748.png", "20260718_180103.png"} <= error.must_exclude_set
    assert "20260721_203901.png" in dataset.spec("settings screen").must_exclude_set
    assert "20260718_210026.png" in dataset.spec("video game screenshot").must_exclude_set
    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py")
    )
    assert "login screen" not in app_source
    assert "folder selection screen" not in app_source
    assert "DEV_QUERIES" not in app_source
    assert "meaning_eval" not in app_source
    assert "must_include" not in app_source


def test_two_stage_pipeline_ranks_by_score_then_embedding(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    low = _FakeProvider({1, 2}, scores={1: 0.2, 2: 0.2})
    high = _FakeProvider({1, 2}, scores={1: 0.4, 2: 0.9})
    result = judge_ranked_paths("dog", [first, second], low, high)
    assert result["predicted"] == ["second.png", "first.png"]
    assert candidate_chunk_sizes(50)[0] == 8


def test_eval_chunk_sizes_match_product():
    from app.ui.images_search import vision_candidate_chunk_sizes
    from tools.meaning_eval.pipeline import candidate_chunk_sizes

    assert candidate_chunk_sizes(0) == []
    assert candidate_chunk_sizes(99) == vision_candidate_chunk_sizes(99)
    assert candidate_chunk_sizes(8) == [8]
    assert candidate_chunk_sizes(9) == [8, 1]


def test_summary_keeps_dev_holdout_and_false_negatives():
    dataset = load_dataset()
    spec = dataset.spec("dog")
    retriever = retriever_row(spec, ["images.jpg", "A2.png"])
    e2e = end_to_end_row(
        spec,
        ranking=["images.jpg", "A2.png"],
        predicted=["images.jpg"],
        judgements={
            "images.jpg": {"relevant": True, "relevance_score": 0.9},
            "A2.png": {"relevant": False, "relevance_score": 0.1, "low_relevant": False},
        },
    )
    report = {
        "identity": {
            "timestamp": "t", "git_commit": "abc", "git_dirty": False,
            "retrieval_model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
            "query_embedding": "raw",
            "vision_prompt_version": "vision-usefulness-v1",
            "vision_schema_version": "image-relevance-v2",
            "query_set_version": dataset.query_set_version,
            "query_set_hash": dataset.query_set_hash,
            "gt_version": dataset.gt_version,
            "gt_hash": dataset.gt_hash,
            "corpus_count": 2,
            "corpus_sha256": "x",
        },
        "splits": {"dev": ["dog"], "holdout": ["login screen"]},
        "retriever": {
            "splits": {"dev": summarize_retriever([retriever]), "holdout": summarize_retriever([])},
            "queries": [retriever],
        },
        "end_to_end": {
            "splits": {
                "dev": summarize_end_to_end([e2e]),
                "holdout": summarize_end_to_end([]),
            },
            "failure_mode_counts": e2e["failure_mode_counts"],
            "queries": [e2e],
        },
        "comparison": compare_runs({}, None),
    }
    text = render_summary(report)
    assert "hold-out" in text
    assert "`dog`" in text
    assert "judge_fn" in text
    assert "A2.png" in text
    assert dataset.query_set_hash in text
    assert "No previous Phase D run" in text


_BANNED_PROMPT_WORDS = ("anime", "icon", "dog", "cat")
_BANNED_QUERY_PHRASES = (
    "windows desktop",
    "screenshot manager",
    "settings screen",
    "code editor",
    "mountain",
    "login screen",
    "image gallery",
    "tag management",
)


def test_phase_e_candidate_prompts_are_generic_and_role_split():
    from tools.meaning_eval.describe_judge import (
        DESCRIBE_PROMPT,
        DESCRIBE_USER_PREFIX,
        EVIDENCE_USER_INSTRUCTIONS,
        TEXT_JUDGE_PROMPT,
        TEXT_JUDGE_USER_INSTRUCTIONS,
    )
    from tools.meaning_eval.judge_candidates import (
        CANDIDATES,
        STAGE1_SCREENING_PROMPT,
        STAGE2_USEFULNESS_PROMPT,
        STRUCTURE_DESCRIBE_THEN_JUDGE,
        STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE,
    )

    baseline = CANDIDATES["baseline"]
    candidate = CANDIDATES["usefulness-v2"]
    describe = CANDIDATES["describe-judge-v1"]
    text_judge = CANDIDATES["describe-text-judge-v1"]
    assert baseline.version == "vision-meaning-v1"
    assert baseline.low_prompt is None
    assert baseline.high_prompt is None
    assert candidate.version == "vision-usefulness-v2"
    assert candidate.low_prompt == STAGE1_SCREENING_PROMPT
    assert candidate.high_prompt == STAGE2_USEFULNESS_PROMPT
    assert candidate.low_prompt != candidate.high_prompt
    assert describe.structure == STRUCTURE_DESCRIBE_THEN_JUDGE
    assert describe.version == "vision-describe-judge-v1"
    assert describe.describe_prompt == DESCRIBE_PROMPT
    assert text_judge.structure == STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE
    assert text_judge.version == "vision-describe-text-judge-v1"
    assert text_judge.describe_prompt == DESCRIBE_PROMPT

    screening = STAGE1_SCREENING_PROMPT.lower()
    confirmation = STAGE2_USEFULNESS_PROMPT.lower()
    describe_text = "\n".join([
        DESCRIBE_PROMPT, DESCRIBE_USER_PREFIX, EVIDENCE_USER_INSTRUCTIONS,
        TEXT_JUDGE_PROMPT, TEXT_JUDGE_USER_INSTRUCTIONS,
    ]).lower()
    for word in _BANNED_PROMPT_WORDS:
        assert word not in screening
        assert word not in confirmation
        assert word not in describe_text
    for phrase in _BANNED_QUERY_PHRASES:
        assert phrase not in screening
        assert phrase not in confirmation
        assert phrase not in describe_text

    assert "search query" not in DESCRIBE_PROMPT.lower()
    assert "search query" not in DESCRIBE_USER_PREFIX.lower()
    assert "do not infer a user query" in DESCRIBE_PROMPT.lower()
    assert "primary_subject" in DESCRIBE_PROMPT
    assert "visual_contents" in DESCRIBE_PROMPT
    assert "presentation" in DESCRIBE_PROMPT
    assert "prominent_elements" in DESCRIBE_PROMPT
    assert "primary_vs_background" in DESCRIBE_PROMPT
    assert "query-independent visual description" in EVIDENCE_USER_INSTRUCTIONS.lower()
    assert "the original image is not attached" in TEXT_JUDGE_USER_INSTRUCTIONS.lower()
    assert "result_decision" in TEXT_JUDGE_PROMPT
    assert "include_in_results" in TEXT_JUDGE_PROMPT
    assert "exclude_from_results" in TEXT_JUDGE_PROMPT
    assert "must agree" in TEXT_JUDGE_PROMPT
    assert "screening" in screening
    assert "ordinary visual equivalent" in screening
    assert "when you are uncertain, relevant is true" in screening
    assert "search-result usefulness" in confirmation
    assert "incidental" in confirmation
    assert "nested pictures" in confirmation
    assert "treat capture medium as medium" in confirmation
    assert "shared computer-screen" in confirmation
    assert "object presence alone is not enough" in confirmation
    assert "relevant must agree" in confirmation


def test_phase_e_providers_keep_baseline_product_prompt():
    from app.relevance.openai_provider import PROMPT_VERSION, SYSTEM_PROMPT
    from tools.meaning_eval.evaluate import _providers
    from tools.meaning_eval.judge_candidates import (
        STAGE1_SCREENING_PROMPT,
        STAGE2_USEFULNESS_PROMPT,
    )

    low, high = _providers("baseline")
    assert low.system_prompt == SYSTEM_PROMPT
    assert high.system_prompt == SYSTEM_PROMPT
    assert low.prompt_version == PROMPT_VERSION
    assert high.prompt_version == PROMPT_VERSION
    assert low.image_detail == "low"
    assert high.image_detail == "high"

    low_v2, high_v2 = _providers("usefulness-v2")
    assert low_v2.system_prompt == STAGE1_SCREENING_PROMPT
    assert high_v2.system_prompt == STAGE2_USEFULNESS_PROMPT
    assert low_v2.prompt_version == "vision-usefulness-v2"
    assert high_v2.prompt_version == "vision-usefulness-v2"
    assert low_v2.image_detail == "low"
    assert high_v2.image_detail == "high"

    import pytest
    with pytest.raises(ValueError, match="describe-judge-v1"):
        _providers("describe-judge-v1")
    with pytest.raises(ValueError, match="describe-text-judge-v1"):
        _providers("describe-text-judge-v1")


def test_describe_then_judge_pipeline_skips_unknown_description(tmp_path):
    from tools.meaning_eval.describe_judge import (
        description_record,
        format_evidence,
        judge_ranked_paths_described,
        make_describe_provider,
        make_evidence_judge_provider,
    )
    from app.relevance.openai_provider import SYSTEM_PROMPT

    keep = tmp_path / "keep.png"
    missing = tmp_path / "unknown.png"
    keep.write_bytes(b"1")
    missing.write_bytes(b"2")
    descriptions = {
        "keep.png": description_record(
            primary_subject="a photograph of an animal",
            visual_contents="an animal on grass",
            presentation="photograph",
            prominent_elements="one animal filling the frame",
            primary_vs_background="the animal is primary; grass is background",
        ),
        "unknown.png": description_record(unknown_reason="api_failure"),
    }
    high = _FakeProvider({1}, scores={1: 0.91})
    result = judge_ranked_paths_described(
        "dog", [keep, missing], descriptions, judge_provider=high
    )
    assert result["predicted"] == ["keep.png"]
    assert result["judgements"]["keep.png"]["relevant"] is True
    assert result["judgements"]["keep.png"]["confidence"] == 0.9
    assert result["judgements"]["keep.png"]["description"]["primary_subject"] == "a photograph of an animal"
    assert result["judgements"]["unknown.png"]["relevant"] is None
    assert result["judgements"]["unknown.png"]["high_skipped_reason"] == "describe_unknown"
    assert result["failed_names"] == ["unknown.png"]
    assert high.calls == [(1,)]
    assert "primary_subject: a photograph of an animal" in format_evidence(descriptions["keep.png"])

    describe = make_describe_provider()
    judge = make_evidence_judge_provider({})
    assert describe.prompt_version == "vision-describe-v1"
    assert describe.image_detail == "low"
    assert describe.max_edge == 512
    assert judge.system_prompt == SYSTEM_PROMPT
    assert judge.prompt_version == "vision-describe-judge-v1"
    assert judge.image_detail == "high"
    assert judge.max_edge == 2048
    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py")
    )
    assert "vision-describe-judge-v1" not in app_source
    assert "vision-describe-text-judge-v1" not in app_source
    assert "primary_vs_background" not in app_source
    assert "describe_judge" not in app_source


def test_text_judge_maps_result_decision_and_does_not_send_images(tmp_path, monkeypatch):
    import json

    from app.relevance import RelevanceImage
    from tools.meaning_eval.describe_judge import (
        RESULT_DECISION_EXCLUDE,
        RESULT_DECISION_INCLUDE,
        TEXT_JUDGE_PROMPT,
        TEXT_JUDGE_VERSION,
        description_record,
        judge_ranked_paths_described,
        make_text_judge_provider,
        text_judge_schema,
        validate_text_judge_results,
    )

    parsed = validate_text_judge_results(
        {
            "results": [
                {
                    "image_id": 1,
                    "result_decision": RESULT_DECISION_INCLUDE,
                    "relevance_score": 0.91,
                    "confidence": 0.8,
                    "reason": "primary subject matches the query",
                },
                {
                    "image_id": 2,
                    "result_decision": RESULT_DECISION_EXCLUDE,
                    "relevance_score": 0.02,
                    "confidence": 0.99,
                    "reason": "described as a different subject, not what was asked for",
                },
            ]
        },
        [1, 2],
    )
    assert parsed[0].relevant is True
    assert parsed[0].relevance_score == 0.91
    assert parsed[1].relevant is False
    assert parsed[1].relevance_score == 0.02
    schema = text_judge_schema([1])
    properties = schema["properties"]["results"]["items"]["properties"]
    assert "relevant" not in properties
    assert properties["result_decision"]["enum"] == [
        RESULT_DECISION_INCLUDE, RESULT_DECISION_EXCLUDE,
    ]

    captured = {}

    def fake_post(self, payload, image_diagnostics=()):
        captured["payload"] = payload
        captured["image_diagnostics"] = list(image_diagnostics)
        return {
            "choices": [{"message": {"content": json.dumps({
                "results": [{
                    "image_id": 1,
                    "result_decision": RESULT_DECISION_EXCLUDE,
                    "relevance_score": 0.02,
                    "confidence": 0.99,
                    "reason": "described primary subject is a different animal",
                }]
            })}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }

    def refuse_images(self, paths):
        raise AssertionError("description-only judge must not prepare images")

    monkeypatch.setattr(
        "tools.meaning_eval.describe_judge.DescriptionOnlyJudgeProvider._post_with_retry",
        fake_post,
    )
    monkeypatch.setattr(
        "tools.meaning_eval.describe_judge.DescriptionOnlyJudgeProvider._prepare_images",
        refuse_images,
    )
    image = tmp_path / "keep.png"
    image.write_bytes(b"1")
    provider = make_text_judge_provider({
        1: description_record(
            primary_subject="a photograph of an animal",
            visual_contents="an animal on grass",
            presentation="photograph",
            prominent_elements="one animal filling the frame",
            primary_vs_background="the animal is primary; grass is background",
        )
    })
    provider.api_key = "test-key"
    run = provider.classify("query", [RelevanceImage(1, image)])
    assert run.sent_image_count == 0
    assert run.resize_seconds == 0.0
    assert captured["image_diagnostics"] == []
    content = captured["payload"]["messages"][1]["content"]
    assert all(part.get("type") != "image_url" for part in content)
    assert run.results[0].relevant is False
    assert run.results[0].relevance_score == 0.02
    assert provider.system_prompt == TEXT_JUDGE_PROMPT
    assert provider.prompt_version == TEXT_JUDGE_VERSION

    result = judge_ranked_paths_described(
        "query",
        [image],
        {"keep.png": description_record(primary_subject="an animal")},
        text_only=True,
        judge_provider=provider,
    )
    assert result["judgements"]["keep.png"]["relevant"] is False
    assert result["usage"]["sent_image_count"] == 0


def test_semantic_index_prompt_is_query_independent_and_owned_by_product():
    from app.semantic_index.schema import (
        INDEX_PROMPT as APP_INDEX_PROMPT,
        INDEX_PROMPT_VERSION as APP_PROMPT_VERSION,
        INDEX_SCHEMA_VERSION as APP_SCHEMA_VERSION,
    )
    from tools.meaning_eval.dataset import QuerySpec
    from tools.meaning_eval.semantic_index import (
        INDEX_PROMPT,
        INDEX_USER_PREFIX,
        PRIMARY_SEARCH,
        SEARCH_CONFIGS,
        SEARCH_VERSION,
        clip_index_text,
        content_tokens,
        dropped_must_include,
        include_hit,
        index_record,
        lexical_score,
        make_index_provider,
        measure_index_storage,
        search_records,
    )

    prompt = f"{INDEX_PROMPT}\n{INDEX_USER_PREFIX}".lower()
    for word in _BANNED_PROMPT_WORDS:
        assert word not in prompt
    for phrase in _BANNED_QUERY_PHRASES:
        assert phrase not in prompt
    assert "do not infer queries" in prompt
    assert "searchable_concepts" in INDEX_PROMPT
    assert "ui_interface_concepts" in INDEX_PROMPT
    assert "named programs" in INDEX_PROMPT.lower()
    assert "secondary" in INDEX_PROMPT.lower()
    assert "surrounding chrome" not in prompt
    assert "chrome" not in prompt
    assert INDEX_PROMPT == APP_INDEX_PROMPT
    assert APP_PROMPT_VERSION == "semantic-index-v3"
    assert APP_SCHEMA_VERSION == "image-semantic-index-v2"
    assert PRIMARY_SEARCH == "hybrid_v1"

    search_source = Path("app/ui/images_search.py").read_text(encoding="utf-8")
    analysis_source = Path("app/ui/images_analysis.py").read_text(encoding="utf-8")
    assert SEARCH_VERSION not in search_source
    assert "semantic-index-local-v1" not in search_source
    assert "SemanticIndexService" not in search_source
    assert "SemanticIndexService" not in analysis_source

    provider = make_index_provider()
    assert provider.prompt_version == "semantic-index-v3"
    assert provider.image_detail == "low"
    assert provider.batch_size == 8
    try:
        provider.classify("dog", [])
        raise AssertionError("index provider must not accept a search query")
    except RuntimeError as exc:
        assert "index()" in str(exc)

    editor = index_record(
        visual_summary="a dark development workspace with source files open",
        objects_entities=["file tree", "text pane"],
        media_type="screenshot",
        ui_interface_concepts=["editor", "development environment"],
        searchable_concepts=["source code", "text editor", "ide"],
        incidental_notes="a tiny game preview",
    )
    chat = index_record(
        visual_summary="a chat conversation page in a browser",
        media_type="screenshot",
        ui_interface_concepts=["chat", "browser"],
        searchable_concepts=["chat", "conversation"],
        incidental_notes="a small code snippet inside one message",
    )
    dog = index_record(
        visual_summary="a brown dog sitting on grass",
        objects_entities=["dog"],
        media_type="photograph",
        searchable_concepts=["dog", "puppy", "canine"],
        visible_activities=["sitting"],
        visual_attributes=["orange brown"],
    )
    blank = index_record(
        visual_summary="a form whose main content area shows unused placeholders",
        media_type="screenshot",
        ui_interface_concepts=["form", "dialog"],
        searchable_concepts=["blank", "placeholder", "no items", "unused"],
    )
    assert lexical_score("code editor", editor) >= 0.5
    assert lexical_score("code editor", chat) < 0.34
    assert lexical_score("dog", dog) >= 0.5
    assert lexical_score("sitting", dog) >= 0.5
    assert lexical_score("orange brown dog", dog) >= 0.5
    assert lexical_score("screenshot", editor) == 0.0
    assert lexical_score(
        "cat",
        index_record(
            visual_summary="a screenshot manager application window",
            media_type="screenshot",
            searchable_concepts=["screenshot manager application"],
            ui_interface_concepts=["gallery"],
        ),
    ) == 0.0
    assert content_tokens("dog photo") == ["dog"]
    assert "desktop" in content_tokens("Windows desktop screenshot")
    assert "screenshot" not in content_tokens("Windows desktop screenshot")
    assert "placeholder" in clip_index_text(blank)

    configs = {config.name: config for config in SEARCH_CONFIGS}
    judged = search_records(
        "code editor",
        ["editor.png", "chat.png", "dog.png", "blank.png"],
        {
            "editor.png": editor,
            "chat.png": chat,
            "dog.png": dog,
            "blank.png": blank,
        },
        query_vector=None,
        image_vectors={},
        text_vectors={},
        config=configs["lex_0.50"],
    )
    assert judged["predicted"] == ["editor.png"]
    assert judged["usage"]["sent_image_count"] == 0
    assert judged["judgements"]["chat.png"]["relevant"] is False

    spec = QuerySpec(
        query="code editor",
        split="dev",
        kind="ui",
        must_include=("editor.png", "chat.png"),
        must_exclude=(),
        acceptable=(),
    )
    assert dropped_must_include(
        spec=spec,
        baseline_predicted=["editor.png", "chat.png"],
        poc_predicted=["editor.png"],
    ) == ["chat.png"]

    storage = measure_index_storage({
        "editor.png": editor,
        "chat.png": chat,
        "dog.png": dog,
        "blank.png": blank,
    })
    assert storage["images"] == 4
    assert storage["text_embedding_float32_bytes"] == 2048
    assert storage["json_bytes_mean"] > 50
    assert storage["scale_new_bytes"]["1000"] > 0
    assert include_hit(0.1, 0.1, 0.6, configs["hybrid_v1"]) is True


def test_hybrid_bands_replay_vision_without_using_holdout_for_selection():
    import inspect
    from tools.meaning_eval.hybrid import (
        INDEX_ONLY_BAND,
        VISION_ALL_BAND,
        decide_hybrid,
        merge_hybrid_predicted,
        select_hybrid_policies,
        stage1_request_count,
    )
    from tools.meaning_eval.semantic_index import SEARCH_CONFIGS

    search = {config.name: config for config in SEARCH_CONFIGS}["hybrid_v1"]
    hit = {"lex": 0.9, "txt": 0.4, "img": 0.3, "relevant": True}
    miss = {"lex": 0.0, "txt": 0.05, "img": 0.05, "relevant": False}
    weak = {"lex": 0.4, "txt": 0.2, "img": 0.2, "relevant": False}
    assert decide_hybrid(hit, INDEX_ONLY_BAND, search) == "positive"
    assert decide_hybrid(miss, INDEX_ONLY_BAND, search) == "negative"
    assert decide_hybrid(hit, VISION_ALL_BAND, search) == "uncertain"
    assert decide_hybrid(miss, VISION_ALL_BAND, search) == "uncertain"
    assert decide_hybrid({"unknown_reason": "missing"}, INDEX_ONLY_BAND, search) == "uncertain"
    assert decide_hybrid(weak, INDEX_ONLY_BAND, search) == "negative"

    predicted, sent = merge_hybrid_predicted(
        names=["keep.png", "skip.png", "ask.png"],
        decisions={
            "keep.png": "positive",
            "skip.png": "negative",
            "ask.png": "uncertain",
        },
        vision_true={"ask.png", "skip.png"},
    )
    assert predicted == ["keep.png", "ask.png"]
    assert sent == ["ask.png"]

    signature = inspect.signature(select_hybrid_policies)
    assert "holdout" not in signature.parameters
    assert "hold_out" not in signature.parameters

    baseline_dev = {
        "macro_precision": 0.50,
        "macro_recall": 0.80,
        "macro_f1": 0.62,
        "micro_fn": 10,
        "micro_fp": 100,
        "mean_vision_sent": 119.0,
    }
    close = {
        "macro_precision": 0.49,
        "macro_recall": 0.79,
        "macro_f1": 0.61,
        "micro_fn": 11,
        "micro_fp": 90,
        "mean_vision_sent": 40.0,
    }
    cheaper = {
        "macro_precision": 0.47,
        "macro_recall": 0.76,
        "macro_f1": 0.55,
        "micro_fn": 14,
        "micro_fp": 80,
        "mean_vision_sent": 15.0,
    }
    precise = {
        "macro_precision": 0.70,
        "macro_recall": 0.78,
        "macro_f1": 0.74,
        "micro_fn": 12,
        "micro_fp": 20,
        "mean_vision_sent": 70.0,
    }
    selected = select_hybrid_policies(
        {
            "index_only": cheaper,
            "vision_all": baseline_dev,
            "zero_band": {
                "macro_precision": 0.44,
                "macro_recall": 0.85,
                "macro_f1": 0.60,
                "micro_fn": 13,
                "micro_fp": 368,
                "mean_vision_sent": 0.0,
            },
            "close_band": close,
            "cheap_band": cheaper,
            "precise_band": precise,
        },
        baseline_dev,
    )
    assert selected["selection_split"] == "dev"
    assert selected["policies"]["precision_first"]["band"] == "precise_band"
    assert selected["policies"]["api_reduction"]["band"] == "cheap_band"
    assert selected["quality_match_met"] is True
    picked = {item["band"] for item in selected["policies"].values()}
    assert "zero_band" not in picked
    assert "index_only" not in picked
    assert stage1_request_count(0) == 0
    assert stage1_request_count(8) == 1
    assert stage1_request_count(119) == 7

    search_source = Path("app/ui/images_search.py").read_text(encoding="utf-8")
    assert "evaluate_index_hybrid" not in search_source
    assert "tools.meaning_eval.hybrid" not in search_source
    assert "evaluate_hybrid_phase_e" not in search_source
    assert "tools.meaning_eval.hybrid_phase_e" not in search_source


def test_hybrid_clear_negative_rescue_sends_to_vision_without_auto_positive():
    from app.semantic_index.hybrid import (
        PRODUCT_HYBRID_BAND,
        decide_hybrid as product_decide_hybrid,
    )
    from tools.meaning_eval.hybrid import (
        INDEX_ONLY_BAND,
        RESCUE_COMPOUND,
        RESCUE_HIGH_TXT,
        RESCUE_TOKEN,
        clear_negative_rescues,
        decide_hybrid,
        merge_hybrid_predicted,
        uncertain_reason,
    )
    from tools.meaning_eval.hybrid_phase_e import FROZEN_BAND as PHASE_E_BAND
    from tools.meaning_eval.semantic_index import SEARCH_CONFIGS

    assert decide_hybrid is product_decide_hybrid
    assert PHASE_E_BAND is PRODUCT_HYBRID_BAND

    search = {config.name: config for config in SEARCH_CONFIGS}["hybrid_v1"]
    frozen = PHASE_E_BAND
    assert frozen.name == "posL1.01_posC0.45_negL0.33_negC0.32"
    assert frozen.pos_lex_min == 1.01
    assert frozen.neg_lex_max == 0.33
    assert frozen.neg_combined_max == 0.32

    def record(**overrides):
        item = {
            "visual_summary": "",
            "visual_attributes": [],
            "searchable_concepts": [],
            "ui_interface_concepts": [],
            "objects_entities": [],
            "visible_activities": [],
            "scene_environment": "",
            "incidental_notes": "",
        }
        item.update(overrides)
        return item

    high_txt = {"lex": 0.0, "txt": 0.70, "img": 0.25}
    assert decide_hybrid(high_txt, INDEX_ONLY_BAND, search) == "negative"
    assert decide_hybrid(high_txt, frozen, search) == "uncertain"
    assert decide_hybrid(high_txt, frozen, search) != "positive"
    assert RESCUE_HIGH_TXT in clear_negative_rescues(high_txt)
    mid_txt = {"lex": 0.0, "txt": 0.50, "img": 0.25}
    assert decide_hybrid(mid_txt, frozen, search) == "negative"
    assert RESCUE_HIGH_TXT not in clear_negative_rescues(mid_txt)
    predicted, sent = merge_hybrid_predicted(
        names=["rescued.png"],
        decisions={"rescued.png": "uncertain"},
        vision_true={"rescued.png"},
    )
    assert predicted == ["rescued.png"]
    assert sent == ["rescued.png"]

    dark = record(
        visual_summary="A dark file manager window",
        visual_attributes=["dark theme"],
        ui_interface_concepts=["file manager"],
    )
    low_txt = {"lex": 0.0, "txt": 0.20, "img": 0.20}
    assert decide_hybrid(
        low_txt, frozen, search,
        query="dark themed application",
        record=dark,
    ) == "uncertain"
    rescues = clear_negative_rescues(
        low_txt, query="dark themed application", record=dark,
    )
    assert RESCUE_COMPOUND in rescues
    assert RESCUE_TOKEN not in rescues
    assert RESCUE_HIGH_TXT not in rescues
    assert uncertain_reason(
        low_txt, frozen, search,
        query="dark themed application",
        record=dark,
    ) == RESCUE_COMPOUND

    application_only = record(
        visual_summary="An application window",
        ui_interface_concepts=["application window"],
        searchable_concepts=["application"],
    )
    assert decide_hybrid(
        low_txt, frozen, search,
        query="screenshot manager application",
        record=application_only,
    ) == "negative"

    true_miss = {"lex": 0.0, "txt": 0.10, "img": 0.10}
    assert decide_hybrid(
        true_miss, frozen, search,
        query="dog",
        record=record(visual_summary="A landscape photo", objects_entities=["tree"]),
    ) == "negative"


def test_hybrid_phase_e_freezes_precision_first_and_covers_gt_queries():
    from tools.meaning_eval.hybrid import band_name
    from tools.meaning_eval.hybrid_phase_e import (
        CAUSE_INDEX_CONTENT,
        CAUSE_MATCHING,
        CAUSE_PROMPT_SCHEMA,
        FROZEN_BAND,
        FROZEN_POLICY,
        QUERY_CATEGORIES,
        classify_new_fn,
        query_category,
        verdict_from_metrics,
    )
    from tools.meaning_eval.semantic_index import SEARCH_CONFIGS

    dataset = load_dataset()
    assert FROZEN_POLICY == "precision_first"
    assert FROZEN_BAND.name == band_name(1.01, 0.45, 0.33, 0.32)
    assert set(QUERY_CATEGORIES) == {spec.query for spec in dataset.queries}
    assert query_category("dog") == "object"
    assert query_category("Google Chrome") == "concrete_ui"
    assert query_category("terminal window") == "concrete_ui"
    assert query_category("Google Chrome in Windows desktop") == "broad_ui"
    assert query_category("screenshot manager application") == "broad_ui"
    assert query_category("dark themed application") == "abstract_style"
    assert query_category("empty folder in screenshot manager") == "abstract_style"
    assert query_category("sitting orange brown dog") == "object"

    search = {config.name: config for config in SEARCH_CONFIGS}["hybrid_v1"]
    matching = classify_new_fn(
        query="dark themed application",
        name="dark.png",
        judgement={"lex": 0.0, "txt": 0.50, "img": 0.20},
        record={
            "visual_summary": "A dark code editor window",
            "visual_attributes": ["dark theme"],
            "searchable_concepts": ["editor"],
            "ui_interface_concepts": ["editor"],
            "objects_entities": [],
            "visible_activities": [],
            "scene_environment": "",
            "incidental_notes": "",
        },
        decision="negative",
        ranking=["dark.png"],
        search_config=search,
    )
    assert matching["cause"] in {CAUSE_MATCHING, "mixed"}
    content = classify_new_fn(
        query="dog",
        name="dog.png",
        judgement={"lex": 0.0, "txt": 0.10, "img": 0.10},
        record={
            "visual_summary": "A landscape photo",
            "visual_attributes": ["bright"],
            "searchable_concepts": ["mountain"],
            "ui_interface_concepts": [],
            "objects_entities": ["tree"],
            "visible_activities": [],
            "scene_environment": "outdoors",
            "incidental_notes": "",
        },
        decision="negative",
        ranking=["dog.png"],
        search_config=search,
    )
    assert content["cause"] == CAUSE_INDEX_CONTENT
    schema = classify_new_fn(
        query="empty state",
        name="blank.png",
        judgement={"lex": 0.0, "txt": 0.12, "img": 0.10},
        record={
            "visual_summary": "A web form with several labeled fields",
            "visual_attributes": [],
            "searchable_concepts": ["form"],
            "ui_interface_concepts": ["form"],
            "objects_entities": [],
            "visible_activities": [],
            "scene_environment": "",
            "incidental_notes": "",
        },
        decision="negative",
        ranking=["blank.png"],
        search_config=search,
    )
    assert schema["cause"] == CAUSE_PROMPT_SCHEMA

    empty_cat = {
        "category": "object",
        "new_fn": 0,
        "A": {"macro_recall": 1.0},
        "C": {"macro_recall": 1.0},
    }
    summary = {"macro_precision": 0.5, "macro_recall": 0.8, "macro_f1": 0.6, "micro_fn": 10}
    go = verdict_from_metrics(
        new_fns=[],
        category_rows=[
            {**empty_cat, "category": "object"},
            {**empty_cat, "category": "concrete_ui"},
            {**empty_cat, "category": "broad_ui"},
            {**empty_cat, "category": "abstract_style"},
        ],
        live={"compared": 4, "agreement_rate": 1.0},
        a_all=summary,
        c_all=summary,
        a_hold=summary,
        c_hold=summary,
    )
    assert go["decision"] == "GO"
    eroded = verdict_from_metrics(
        new_fns=[],
        category_rows=[
            {**empty_cat, "category": "object"},
            {**empty_cat, "category": "concrete_ui"},
            {**empty_cat, "category": "broad_ui"},
            {**empty_cat, "category": "abstract_style"},
        ],
        live=None,
        a_all=summary,
        c_all={**summary, "vision_reduction": 0.40},
        a_hold=summary,
        c_hold=summary,
    )
    assert eroded["decision"] == "CONDITIONAL GO"
    no_go = verdict_from_metrics(
        new_fns=[{"cause": "matching_logic", "category": "object"}],
        category_rows=[
            {"category": "object", "new_fn": 1},
            {"category": "concrete_ui", "new_fn": 0},
            {"category": "broad_ui", "new_fn": 0},
            {"category": "abstract_style", "new_fn": 0},
        ],
        live=None,
        a_all=summary,
        c_all={**summary, "macro_recall": 0.7},
        a_hold=summary,
        c_hold={**summary, "macro_recall": 0.7},
    )
    assert no_go["decision"] == "NO-GO"


def test_index_only_v3_selects_policies_from_dev_only():
    from tools.meaning_eval.index_only_v3 import (
        classify_index_only_fn,
        select_dev_policies,
        would_hit_if_incidental_primary,
    )
    from tools.meaning_eval.semantic_index import index_record

    dev = {
        "hybrid_v1": {
            "macro_precision": 0.40,
            "macro_recall": 0.80,
            "macro_f1": 0.53,
            "micro_fn": 20,
            "micro_fp": 400,
        },
        "lex_0.34": {
            "macro_precision": 0.30,
            "macro_recall": 0.90,
            "macro_f1": 0.45,
            "micro_fn": 10,
            "micro_fp": 700,
        },
        "lex_0.50": {
            "macro_precision": 0.55,
            "macro_recall": 0.70,
            "macro_f1": 0.62,
            "micro_fn": 30,
            "micro_fp": 200,
        },
    }
    picked = select_dev_policies(dev)
    assert picked["selection_split"] == "dev"
    assert picked["holdout_used_for_retune"] is False
    assert picked["policies"]["recall_first"]["config"] == "lex_0.34"
    assert picked["policies"]["balanced"]["config"] == "lex_0.50"
    assert picked["policies"]["precision_first"]["config"] == "hybrid_v1"

    record = index_record(
        visual_summary="A game screenshot fills the monitor.",
        objects_entities=["game character"],
        searchable_concepts=["video game"],
        incidental_notes="Google Chrome is visible on the taskbar.",
    )
    classified = classify_index_only_fn(
        query="Chrome",
        name="game.png",
        judgement={"lex": 0.0, "txt": 0.68, "img": 0.26, "relevant": False},
        record=record,
    )
    assert classified["cause"] == "matching_logic"
    assert classified["tokens_incidental_only"] == ["chrome"]
    assert classified["would_hit_if_incidental_primary"] is True
    assert would_hit_if_incidental_primary(
        "Chrome", record, img=0.26, txt=0.68,
    ) is True


def test_chrome_product_evidence_ignores_browser_chrome_phrase():
    from tools.meaning_eval.index_only_v3 import chrome_product_evidence
    from tools.meaning_eval.semantic_index import index_record

    ui_only = index_record(
        visual_summary="A YouTube VALORANT broadcast.",
        objects_entities=["YouTube", "VALORANT"],
        searchable_concepts=["YouTube", "esports broadcast"],
        incidental_notes="The browser chrome is visible at the top.",
    )
    product = index_record(
        visual_summary="A Chrome browser window is open to ChatGPT.",
        objects_entities=["Chrome browser", "ChatGPT"],
        searchable_concepts=["ChatGPT", "Chrome", "browser"],
    )
    ui = chrome_product_evidence(ui_only)
    named = chrome_product_evidence(product)
    assert ui["has_ui_chrome_only"] is True
    assert ui["has_product_name"] is False
    assert named["has_product_name"] is True
    assert named["has_ui_chrome_only"] is False

