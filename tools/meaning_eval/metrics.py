"""Retriever and end-to-end metrics for Meaning-search evaluation.

Acceptable images are ignored for both Precision and Recall:
they are never TP, FP, or FN. Retriever Recall@K / MRR use must_include only.
"""

from __future__ import annotations


ACCEPTABLE_POLICY = "lenient_ignore"


def recall_at_k(relevant: set[str], ranking: list[str], k: int) -> float:
    if not relevant:
        return 1.0
    hits = sum(1 for name in ranking[:k] if name in relevant)
    return hits / len(relevant)


def mean_reciprocal_rank(relevant: set[str], ranking: list[str]) -> float:
    for index, name in enumerate(ranking, 1):
        if name in relevant:
            return 1.0 / index
    return 0.0


def relevant_ranks(relevant: set[str], ranking: list[str]) -> dict[str, int | None]:
    positions = {name: index for index, name in enumerate(ranking, 1)}
    return {name: positions.get(name) for name in sorted(relevant)}


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    if denominator == 0:
        return empty
    return numerator / denominator


def end_to_end_counts(
    *,
    must_include: set[str],
    acceptable: set[str],
    predicted: set[str],
) -> dict:
    """Precision/Recall with acceptable images excluded from both sides.

    TP: retrieved must_include
    FN: missing must_include
    FP: retrieved items that are neither must_include nor acceptable
    acceptable hits: retrieved acceptable (listed, not scored)
    """
    tp_names = sorted(must_include & predicted)
    fn_names = sorted(must_include - predicted)
    allowed = must_include | acceptable
    fp_names = sorted(predicted - allowed)
    acceptable_hits = sorted(predicted & acceptable)
    tp = len(tp_names)
    fp = len(fp_names)
    fn = len(fn_names)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": _ratio(tp, tp + fp, empty=1.0),
        "recall": _ratio(tp, tp + fn, empty=1.0),
        "tp_names": tp_names,
        "fp_names": fp_names,
        "fn_names": fn_names,
        "acceptable_hits": acceptable_hits,
        "acceptable_policy": ACCEPTABLE_POLICY,
    }


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def recall_from_ranks(ranks: dict[str, int | None], k: int) -> float:
    """must_include Recall@K from stored ranks. Empty relevant set is 1.0."""
    if not ranks:
        return 1.0
    hits = sum(1 for rank in ranks.values() if rank is not None and rank <= k)
    return hits / len(ranks)


def summarize_retriever(rows: list[dict]) -> dict:
    if not rows:
        return {
            "n": 0,
            "recall_at_10": 0.0,
            "recall_at_20": 0.0,
            "recall_at_40": 0.0,
            "recall_at_80": 0.0,
            "mrr": 0.0,
        }
    return {
        "n": len(rows),
        "recall_at_10": sum(row["recall_at_10"] for row in rows) / len(rows),
        "recall_at_20": sum(
            row.get("recall_at_20", recall_from_ranks(row.get("relevant_ranks") or {}, 20))
            for row in rows
        ) / len(rows),
        "recall_at_40": sum(row["recall_at_40"] for row in rows) / len(rows),
        "recall_at_80": sum(
            row.get("recall_at_80", recall_from_ranks(row.get("relevant_ranks") or {}, 80))
            for row in rows
        ) / len(rows),
        "mrr": sum(row["mrr"] for row in rows) / len(rows),
    }


def summarize_end_to_end(rows: list[dict]) -> dict:
    if not rows:
        return {
            "n": 0,
            "macro_precision": 0.0,
            "macro_recall": 0.0,
            "macro_f1": 0.0,
            "micro_tp": 0,
            "micro_fp": 0,
            "micro_fn": 0,
            "micro_precision": 1.0,
            "micro_recall": 1.0,
            "micro_f1": 0.0,
            "acceptable_policy": ACCEPTABLE_POLICY,
        }
    micro_tp = sum(row["tp"] for row in rows)
    micro_fp = sum(row["fp"] for row in rows)
    micro_fn = sum(row["fn"] for row in rows)
    macro_p = sum(row["precision"] for row in rows) / len(rows)
    macro_r = sum(row["recall"] for row in rows) / len(rows)
    micro_p = _ratio(micro_tp, micro_tp + micro_fp, empty=1.0)
    micro_r = _ratio(micro_tp, micro_tp + micro_fn, empty=1.0)
    return {
        "n": len(rows),
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": f1_score(macro_p, macro_r),
        "micro_tp": micro_tp,
        "micro_fp": micro_fp,
        "micro_fn": micro_fn,
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": f1_score(micro_p, micro_r),
        "acceptable_policy": ACCEPTABLE_POLICY,
    }
