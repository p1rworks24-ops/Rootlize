"""Mechanical failure-mode labels for Meaning-search evaluation.

Classification uses only runtime/evaluation fields. Ambiguous cases stay
`unclassified` instead of being forced into another bucket.
"""

from __future__ import annotations

from collections.abc import Mapping

FAILURE_MODES = (
    "retrieval_miss",
    "judge_fn",
    "judge_fp",
    "batch_fail",
    "cancelled_unjudged",
    "not_embedded",
    "unknown_after_retry",
    "unclassified",
)


def _judged_boolean(judgement: Mapping | None) -> bool:
    if not judgement:
        return False
    return judgement.get("relevant") is True or judgement.get("relevant") is False


def classify_false_negative(
    name: str,
    *,
    ranking: list[str],
    judgement: Mapping | None,
    cancelled: bool = False,
    failed_names: set[str] | None = None,
    embedded_names: set[str] | None = None,
) -> str:
    failed_names = failed_names or set()
    embedded = set(ranking) if embedded_names is None else set(embedded_names)
    if name not in embedded:
        return "not_embedded"
    if cancelled and not _judged_boolean(judgement):
        return "cancelled_unjudged"
    if name in failed_names and not _judged_boolean(judgement):
        return "batch_fail"
    if judgement is None or judgement.get("relevant") is None:
        unknown_reason = "" if judgement is None else str(judgement.get("unknown_reason") or "")
        if unknown_reason:
            return "unknown_after_retry"
        if name in ranking:
            return "retrieval_miss"
        return "unclassified"
    if judgement.get("relevant") is False:
        return "judge_fn"
    return "unclassified"


def classify_false_positive(
    name: str,
    *,
    judgement: Mapping | None,
    failed_names: set[str] | None = None,
) -> str:
    failed_names = failed_names or set()
    if judgement and judgement.get("relevant") is True:
        return "judge_fp"
    if name in failed_names:
        return "batch_fail"
    return "unclassified"


def empty_mode_counts() -> dict[str, int]:
    return {mode: 0 for mode in FAILURE_MODES}
