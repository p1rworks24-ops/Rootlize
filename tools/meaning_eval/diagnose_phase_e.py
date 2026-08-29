"""Phase E diagnostic: FP/FN by query, image, stage, score, and reason.

Read-only over a Phase D results.json. Does not call the Vision API.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = ROOT / "artifacts" / "meaning-eval" / "latest" / "results.json"

UIISH = {
    "Windows desktop",
    "Windows desktop screenshot",
    "desktop with application windows",
    "screenshot manager application",
    "settings screen",
    "screen capture settings",
    "browser window",
    "image search application",
    "image gallery",
    "tag management screen",
    "file explorer window",
}

WATCH_FN = {
    "settings screen",
    "screenshot manager application",
    "dark themed application",
    "mountain desktop wallpaper",
    "code editor",
}

REASON_KEYS = (
    "screenshot",
    "desktop",
    "window",
    "ui",
    "app",
    "application",
    "settings",
    "wallpaper",
    "incidental",
    "background",
    "partial",
    "primary",
    "subject",
    "contains",
    "visible",
    "chrome",
    "icon",
    "taskbar",
    "browser",
    "code",
    "editor",
    "theme",
    "dark",
    "mountain",
    "scene",
    "style",
    "anime",
    "dog",
    "cat",
)


def _stage(vision: dict | None) -> str:
    if not vision:
        return "no_vision"
    low = vision.get("low_relevant")
    high = vision.get("high_relevant")
    if low is False and high is None:
        return "s1_false"
    if low is True and high is False:
        return "s1_true_s2_false"
    if low is True and high is True:
        return "s1_true_s2_true"
    if low is True and high is None:
        return "s1_true_s2_missing"
    if low is None and high is None:
        return "unjudged"
    return f"other:low={low}:high={high}"


def _score_bucket(score) -> str:
    if score is None:
        return "none"
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "none"
    if value < 0.20:
        return "0.00-0.19"
    if value < 0.40:
        return "0.20-0.39"
    if value < 0.60:
        return "0.40-0.59"
    if value < 0.80:
        return "0.60-0.79"
    return "0.80-1.00"


def _reason_keys(reason: str) -> list[str]:
    text = (reason or "").lower()
    hits = [key for key in REASON_KEYS if key in text]
    return hits or ["(no keyword)"]


def diagnose(report: dict) -> dict:
    e2e = report["end_to_end"]
    queries = e2e["queries"]
    fn_stage = Counter()
    fp_score = Counter()
    fn_score = Counter()
    fp_reason = Counter()
    fn_reason = Counter()
    fp_by_query = []
    fn_by_query = []
    low_score_true_fp = []
    high_score_fn = []
    ui_fp = Counter()
    watch_fn_rows = []
    fp_reason_examples = defaultdict(list)
    fn_reason_examples = defaultdict(list)
    tp_score = Counter()
    fp_must_exclude = 0

    for row in queries:
        query = row["query"]
        split = row["split"]
        fp_items = row.get("false_positives") or []
        fn_items = row.get("false_negatives") or []
        tp = int(row["tp"])
        fp = int(row["fp"])
        fn = int(row["fn"])
        fp_by_query.append({
            "query": query, "split": split, "kind": row.get("kind"),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": row["precision"], "recall": row["recall"],
        })
        for item in fp_items:
            vision = item.get("vision") or {}
            score = vision.get("relevance_score")
            reason = vision.get("reason") or ""
            fp_score[_score_bucket(score)] += 1
            for key in _reason_keys(reason):
                fp_reason[key] += 1
                if len(fp_reason_examples[key]) < 3:
                    fp_reason_examples[key].append({
                        "query": query, "name": item["name"],
                        "score": score, "reason": reason,
                    })
            if score is not None and float(score) < 0.40:
                low_score_true_fp.append({
                    "query": query, "split": split, "name": item["name"],
                    "score": score, "reason": reason,
                    "must_exclude": item.get("must_exclude"),
                })
            if query in UIISH:
                ui_fp[query] += 1
            if item.get("must_exclude"):
                fp_must_exclude += 1
        for item in fn_items:
            vision = item.get("vision") or {}
            stage = _stage(vision)
            fn_stage[stage] += 1
            score = vision.get("relevance_score")
            reason = vision.get("reason") or ""
            fn_score[_score_bucket(score)] += 1
            for key in _reason_keys(reason):
                fn_reason[key] += 1
                if len(fn_reason_examples[key]) < 4:
                    fn_reason_examples[key].append({
                        "query": query, "name": item["name"],
                        "stage": stage, "score": score, "reason": reason,
                        "low": vision.get("low_relevant"),
                        "high": vision.get("high_relevant"),
                        "rank": item.get("retrieval_rank"),
                    })
            if score is not None and float(score) >= 0.40:
                high_score_fn.append({
                    "query": query, "name": item["name"], "stage": stage,
                    "score": score, "reason": reason,
                    "low": vision.get("low_relevant"),
                    "high": vision.get("high_relevant"),
                    "rank": item.get("retrieval_rank"),
                })
            if query in WATCH_FN:
                watch_fn_rows.append({
                    "query": query, "name": item["name"], "stage": stage,
                    "score": score, "reason": reason,
                    "low": vision.get("low_relevant"),
                    "high": vision.get("high_relevant"),
                    "rank": item.get("retrieval_rank"),
                    "mode": item.get("failure_mode"),
                })
        # TP scores are not stored separately; skip unless predicted ∩ must_include
        # is reconstructable. Predicted names that are not FP and not acceptable
        # are TP.
        predicted = set(row.get("predicted") or [])
        fp_names = {item["name"] for item in fp_items}
        # remaining predicted are TP or acceptable; we only have FP/FN lists.
        # Approximate TP score from absence of FP list only if we had judgements.
        _ = (tp, predicted, fp_names)

    # Mountain wallpaper detail
    mountain_fn = [row for row in watch_fn_rows if row["query"] == "mountain desktop wallpaper"]

    return {
        "failure_mode_counts": e2e.get("failure_mode_counts"),
        "note": (
            "Final judge_fp all passed Stage 1 and Stage 2 (product requires both true). "
            "Stage 1 FPs that Stage 2 correctly removed are not in this artifact "
            "(full per-image judgements were not persisted)."
        ),
        "fn_stage": dict(fn_stage),
        "fp_score": dict(fp_score),
        "fn_score": dict(fn_score),
        "fp_reason_keywords": dict(fp_reason.most_common()),
        "fn_reason_keywords": dict(fn_reason.most_common()),
        "fp_reason_examples": dict(fp_reason_examples),
        "fn_reason_examples": dict(fn_reason_examples),
        "low_score_true_fp_count": len(low_score_true_fp),
        "low_score_true_fp_by_query": dict(Counter(item["query"] for item in low_score_true_fp)),
        "low_score_true_fp_samples": low_score_true_fp[:25],
        "high_score_fn": high_score_fn,
        "fp_must_exclude": fp_must_exclude,
        "ui_fp": dict(ui_fp),
        "watch_fn": watch_fn_rows,
        "mountain_fn": mountain_fn,
        "per_query": fp_by_query,
        "tp_score": dict(tp_score),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    report = json.loads(args.results.read_text(encoding="utf-8"))
    out = diagnose(report)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
