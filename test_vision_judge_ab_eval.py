from pathlib import Path

from tools.vision_judge_ab_eval import (
    DEV_QUERIES,
    compare_query,
    failure_reasons,
    load_labels,
    metrics,
    ranked_names,
    split_queries,
)


def test_ab_metrics_and_failure_reasons_on_fixed_candidates():
    expected = {"hero-icon.png", "app-icon.png"}
    predicted = {"hero-icon.png", "screenshot-with-tiny-icon.png"}
    judgements = {
        "hero-icon.png": {"relevant": True, "reason": "primary icon", "relevance_score": 0.95},
        "app-icon.png": {"relevant": False, "reason": "not useful", "relevance_score": 0.2},
        "screenshot-with-tiny-icon.png": {
            "relevant": True, "reason": "tiny chrome icon", "relevance_score": 0.15,
        },
        "unrelated.png": {"relevant": None, "unknown_reason": "omitted"},
    }
    scores = metrics(expected, predicted)
    assert scores["tp"] == 1
    assert scores["fp"] == 1
    assert scores["fn"] == 1
    failures = failure_reasons(expected, predicted, judgements)
    assert failures["false_positives"][0]["name"] == "screenshot-with-tiny-icon.png"
    assert failures["false_negatives"][0]["name"] == "app-icon.png"


def test_new_judge_ranks_incidental_below_primary_on_same_candidates():
    order = ["screenshot-with-tiny-icon.png", "hero-icon.png", "unrelated.png"]
    old = {
        "screenshot-with-tiny-icon.png": {"relevant": True, "relevance_score": None},
        "hero-icon.png": {"relevant": True, "relevance_score": None},
        "unrelated.png": {"relevant": False, "relevance_score": None},
    }
    new = {
        "screenshot-with-tiny-icon.png": {"relevant": True, "relevance_score": 0.18},
        "hero-icon.png": {"relevant": True, "relevance_score": 0.94},
        "unrelated.png": {"relevant": False, "relevance_score": 0.05},
    }
    assert ranked_names(old, order) == [
        "screenshot-with-tiny-icon.png", "hero-icon.png",
    ]
    assert ranked_names(new, order) == [
        "hero-icon.png", "screenshot-with-tiny-icon.png",
    ]
    report = compare_query("icon", {"hero-icon.png"}, old, new, order, "dev")
    assert report["old"]["fp"] == 1
    assert report["new"]["fp"] == 1
    assert report["new"]["ranked"][0] == "hero-icon.png"


def test_unlabeled_query_skips_precision_against_empty_labels():
    order = ["test3.jpg", "title.png"]
    judgements = {
        "test3.jpg": {"relevant": True, "relevance_score": 0.9},
        "title.png": {"relevant": False, "relevance_score": 0.1},
    }
    report = compare_query("anime", None, judgements, judgements, order, "adhoc")
    assert report["labeled"] is False
    assert report["new"]["precision"] is None
    assert report["new"]["ranked"] == ["test3.jpg"]


def test_unknown_positive_is_not_converted_to_false_negative_reason():
    expected = {"A2.png"}
    predicted = set()
    judgements = {"A2.png": {"relevant": None, "unknown_reason": "timeout"}}
    failures = failure_reasons(expected, predicted, judgements)
    assert failures["false_negatives"] == []
    assert failures["unknown"][0]["unknown_reason"] == "timeout"


def test_holdout_split_reuses_existing_labels_and_stays_out_of_product():
    labels = load_labels(
        Path("tools/semantic_search_benchmark/real_images/queries.json")
    )
    splits = split_queries(list(labels))
    assert "dog" in splits["dev"]
    assert "login screen" in splits["holdout"]
    assert "folder selection screen" in splits["holdout"]
    assert not set(splits["dev"]) & set(splits["holdout"])
    app_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app").rglob("*.py")
    )
    assert "login screen" not in app_source
    assert "folder selection screen" not in app_source
    assert "DEV_QUERIES" not in app_source
    assert "dog" in DEV_QUERIES
