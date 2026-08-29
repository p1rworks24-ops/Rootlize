from pathlib import Path

from tools.meaning_eval.dataset import load_dataset
from tools.retriever_eval import (
    evaluate_ranking,
    mean_reciprocal_rank,
    recall_at_k,
    relevant_ranks,
    summarize_split,
)


def test_recall_mrr_and_per_image_ranks_on_fixed_ranking():
    relevant = {"hero-icon.png", "app-icon.png"}
    ranking = [
        "unrelated.png", "hero-icon.png", "other.png", "app-icon.png",
        *([f"pad-{index}.png" for index in range(40)]),
    ]
    assert recall_at_k(relevant, ranking, 10) == 1.0
    assert recall_at_k({"hero-icon.png"}, ranking, 1) == 0.0
    assert mean_reciprocal_rank(relevant, ranking) == 0.5
    assert relevant_ranks(relevant, ranking) == {
        "app-icon.png": 4,
        "hero-icon.png": 2,
    }
    row = evaluate_ranking("icon", relevant, ranking, "dev")
    assert row["best_relevant_rank"] == 2
    assert row["recall_at_10"] == 1.0
    assert summarize_split([row])["mrr"] == 0.5


def test_login_and_folder_gt_corrections_are_eval_only():
    dataset = load_dataset()
    corrected = {item["query"] for item in dataset.gt_corrections}
    assert {"login screen", "folder selection screen"} <= corrected
    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py")
    )
    assert "login screen" not in app_source
    assert "folder selection screen" not in app_source
