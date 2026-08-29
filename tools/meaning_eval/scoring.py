"""Per-query retriever + end-to-end scoring used by the Phase D runner and tests."""

from __future__ import annotations

from .dataset import QuerySpec
from .failure import classify_false_negative, classify_false_positive, empty_mode_counts
from .metrics import (
    end_to_end_counts,
    f1_score,
    mean_reciprocal_rank,
    recall_at_k,
    relevant_ranks,
)


def retriever_row(spec: QuerySpec, ranking: list[str]) -> dict:
    relevant = spec.must_include_set
    ranks = relevant_ranks(relevant, ranking)
    present = [rank for rank in ranks.values() if rank is not None]
    return {
        "query": spec.query,
        "split": spec.split,
        "kind": spec.kind,
        "notes": spec.notes,
        "recall_at_10": recall_at_k(relevant, ranking, 10),
        "recall_at_20": recall_at_k(relevant, ranking, 20),
        "recall_at_40": recall_at_k(relevant, ranking, 40),
        "recall_at_80": recall_at_k(relevant, ranking, 80),
        "mrr": mean_reciprocal_rank(relevant, ranking),
        "best_relevant_rank": min(present, default=None),
        "worst_relevant_rank": max(present, default=None),
        "relevant_ranks": ranks,
        "missing_from_corpus": sorted(name for name, rank in ranks.items() if rank is None),
        "top10": ranking[:10],
    }


def end_to_end_row(
    spec: QuerySpec,
    *,
    ranking: list[str],
    predicted: list[str],
    judgements: dict[str, dict],
    cancelled: bool = False,
    failed_names: set[str] | None = None,
    embedded_names: set[str] | None = None,
) -> dict:
    failed_names = failed_names or set()
    embedded = set(ranking) if embedded_names is None else set(embedded_names)
    predicted_set = set(predicted)
    counts = end_to_end_counts(
        must_include=spec.must_include_set,
        acceptable=spec.acceptable_set,
        predicted=predicted_set,
    )
    modes = empty_mode_counts()
    false_negatives = []
    for name in counts["fn_names"]:
        judgement = judgements.get(name)
        mode = classify_false_negative(
            name,
            ranking=ranking,
            judgement=judgement,
            cancelled=cancelled,
            failed_names=failed_names,
            embedded_names=embedded,
        )
        modes[mode] += 1
        false_negatives.append({
            "name": name,
            "query": spec.query,
            "split": spec.split,
            "retrieval_rank": None if name not in ranking else ranking.index(name) + 1,
            "vision": None if judgement is None else {
                "relevant": judgement.get("relevant"),
                "low_relevant": judgement.get("low_relevant"),
                "high_relevant": judgement.get("high_relevant"),
                "relevance_score": judgement.get("relevance_score"),
                "confidence": judgement.get("confidence"),
                "reason": judgement.get("reason"),
                "unknown_reason": judgement.get("unknown_reason"),
                "high_skipped_reason": judgement.get("high_skipped_reason"),
                "description": judgement.get("description"),
            },
            "failure_mode": mode,
        })
    false_positives = []
    for name in counts["fp_names"]:
        judgement = judgements.get(name)
        mode = classify_false_positive(
            name, judgement=judgement, failed_names=failed_names
        )
        if name in spec.must_exclude_set and mode == "unclassified":
            mode = "judge_fp" if judgement and judgement.get("relevant") is True else mode
        modes[mode] += 1
        false_positives.append({
            "name": name,
            "query": spec.query,
            "split": spec.split,
            "must_exclude": name in spec.must_exclude_set,
            "retrieval_rank": None if name not in ranking else ranking.index(name) + 1,
            "vision": None if judgement is None else {
                "relevant": judgement.get("relevant"),
                "relevance_score": judgement.get("relevance_score"),
                "confidence": judgement.get("confidence"),
                "reason": judgement.get("reason"),
                "description": judgement.get("description"),
            },
            "failure_mode": mode,
        })
    return {
        "query": spec.query,
        "split": spec.split,
        "kind": spec.kind,
        "notes": spec.notes,
        "predicted": list(predicted),
        **counts,
        "f1": f1_score(counts["precision"], counts["recall"]),
        "failure_mode_counts": modes,
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "cancelled": cancelled,
    }
