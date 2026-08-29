"""Eval Hybrid sweep, cost estimates, and Phase E wrappers.

Decision logic lives in app.semantic_index.hybrid so product Meaning Search
and evaluation stay aligned. Thresholds are swept on dev and frozen before
hold-out scoring. Hold-out must not be passed into policy selection.
"""

from __future__ import annotations

import math
from typing import Iterable

from app.semantic_index.hybrid import (  # noqa: F401
    DECISION_NEGATIVE,
    DECISION_POSITIVE,
    DECISION_UNCERTAIN,
    NEG_RESCUE_TXT_MIN,
    PRODUCT_HYBRID_BAND,
    PRODUCT_HYBRID_POLICY,
    RESCUE_COMPOUND,
    RESCUE_HIGH_TXT,
    RESCUE_TOKEN,
    SENTINEL_BAND_NAMES,
    WEAK_QUERY_TOKENS,
    HybridBand,
    _band_negative,
    clear_negative_rescues,
    decide_hybrid,
    uncertain_reason,
)
from app.semantic_index.scoring import SearchConfig
from tools.meaning_eval.pipeline import candidate_chunk_sizes

# Stage-1 token/latency rates measured on gpt-5.4-mini, 512px, detail=low,
# batch 20 / parallel 2 (artifacts/vision-relevance-dog-top40-gpt-5.4-mini-capixe-relevance.json).
STAGE1_INPUT_TOKENS_PER_IMAGE = 6322 / 40
STAGE1_OUTPUT_TOKENS_PER_IMAGE = 1312 / 40
STAGE1_API_SECONDS_PER_IMAGE = 11.296161100035533 / 40
STAGE1_WALL_SECONDS_PER_IMAGE = 10.682727700012038 / 40
# High-detail Stage 2 has no stored token trace in the product baseline run.
# 4x input is an estimate for 2048px tiles vs 512px low; labeled as estimate.
STAGE2_INPUT_MULTIPLIER = 4.0
VISION_BATCH_SIZE = 20
VISION_PARALLEL = 2
INPUT_USD_PER_MILLION = 0.75
OUTPUT_USD_PER_MILLION = 4.50

QUALITY_F1_SLACK = 0.03
QUALITY_R_SLACK = 0.05
QUALITY_P_SLACK = 0.03
QUALITY_FN_SLACK = 3
MIN_HYBRID_VISION_SENT = 1.0
PRECISION_R_SLACK = 0.05
API_F1_SLACK = 0.08
API_R_SLACK = 0.10
API_FN_SLACK = 8
BALANCED_SEND_WEIGHT = 0.20

INDEX_ONLY_BAND = HybridBand(
    name="index_only",
    pos_lex_min=0.0,
    pos_combined_min=0.0,
    neg_lex_max=1.0,
    neg_combined_max=1.0,
)
VISION_ALL_BAND = HybridBand(
    name="vision_all",
    pos_lex_min=2.0,
    pos_combined_min=2.0,
    neg_lex_max=-1.0,
    neg_combined_max=-1.0,
)

POS_LEX_GRID = (0.50, 0.70, 0.85, 1.01)
POS_COMBINED_GRID = (0.0, 0.30, 0.45)
NEG_LEX_GRID = (0.0, 0.20, 0.33)
NEG_COMBINED_GRID = (0.12, 0.22, 0.32)


def band_name(pos_lex: float, pos_combined: float, neg_lex: float, neg_combined: float) -> str:
    return (
        f"posL{pos_lex:.2f}_posC{pos_combined:.2f}_"
        f"negL{neg_lex:.2f}_negC{neg_combined:.2f}"
    )


def sweep_bands() -> tuple[HybridBand, ...]:
    bands = []
    for pos_lex in POS_LEX_GRID:
        for pos_combined in POS_COMBINED_GRID:
            for neg_lex in NEG_LEX_GRID:
                for neg_combined in NEG_COMBINED_GRID:
                    bands.append(HybridBand(
                        name=band_name(pos_lex, pos_combined, neg_lex, neg_combined),
                        pos_lex_min=pos_lex,
                        pos_combined_min=pos_combined,
                        neg_lex_max=neg_lex,
                        neg_combined_max=neg_combined,
                    ))
    return tuple(bands)


ALL_BANDS = (INDEX_ONLY_BAND, VISION_ALL_BAND) + sweep_bands()


def merge_hybrid_predicted(
    *,
    names: Iterable[str],
    decisions: dict[str, str],
    vision_true: set[str],
) -> tuple[list[str], list[str]]:
    predicted = []
    sent = []
    for name in names:
        decision = decisions.get(name, DECISION_UNCERTAIN)
        if decision == DECISION_UNCERTAIN:
            sent.append(name)
            if name in vision_true:
                predicted.append(name)
        elif decision == DECISION_POSITIVE:
            predicted.append(name)
    return predicted, sent


def attach_uncertain_reasons(
    *,
    judgements: dict[str, dict],
    decisions: dict[str, str],
    band: HybridBand,
    search_config: SearchConfig,
    predicted: set[str],
    query: str = "",
    records: dict[str, dict] | None = None,
) -> dict[str, dict]:
    records = records or {}
    out = {}
    for name, source in judgements.items():
        item = dict(source)
        decision = decisions.get(name, DECISION_UNCERTAIN)
        item["hybrid_decision"] = decision
        item["relevant"] = name in predicted
        record = records.get(name)
        if decision == DECISION_POSITIVE:
            item["decision_source"] = "index_positive"
        elif decision == DECISION_NEGATIVE:
            item["decision_source"] = "index_negative"
        else:
            item["decision_source"] = "vision_replay"
            item["uncertain_reason"] = uncertain_reason(
                source, band, search_config, query=query, record=record,
            )
            if (
                band.name not in SENTINEL_BAND_NAMES
                and "lex" in source
                and not source.get("unknown_reason")
                and _band_negative(source, band, search_config)
            ):
                rescues = clear_negative_rescues(
                    source, query=query, record=record,
                )
                if rescues:
                    item["negative_rescue_reasons"] = list(rescues)
        out[name] = item
    return out


def stage1_request_count(
    n_images: int,
    *,
    batch_size: int = VISION_BATCH_SIZE,
) -> int:
    if n_images <= 0:
        return 0
    total = 0
    for size in candidate_chunk_sizes(n_images):
        total += math.ceil(size / batch_size)
    return total


def stage2_request_count(
    n_images: int,
    *,
    batch_size: int = VISION_BATCH_SIZE,
) -> int:
    if n_images <= 0:
        return 0
    return math.ceil(n_images / batch_size)


def vision_reduction(sent: float, baseline_sent: float) -> float:
    if baseline_sent <= 0:
        return 0.0
    return 1.0 - (sent / baseline_sent)


def estimate_tokens(n_stage1: int, n_stage2: int) -> dict:
    input_tokens = (
        n_stage1 * STAGE1_INPUT_TOKENS_PER_IMAGE
        + n_stage2 * STAGE1_INPUT_TOKENS_PER_IMAGE * STAGE2_INPUT_MULTIPLIER
    )
    output_tokens = (
        n_stage1 * STAGE1_OUTPUT_TOKENS_PER_IMAGE
        + n_stage2 * STAGE1_OUTPUT_TOKENS_PER_IMAGE
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "stage1_images": n_stage1,
        "stage2_images": n_stage2,
        "stage2_tokens": "estimate",
    }


def estimate_usd(input_tokens: float, output_tokens: float) -> float:
    return (
        input_tokens / 1_000_000 * INPUT_USD_PER_MILLION
        + output_tokens / 1_000_000 * OUTPUT_USD_PER_MILLION
    )


def estimate_wall_seconds(n_stage1: int, n_stage2: int) -> float:
    return (
        n_stage1 * STAGE1_WALL_SECONDS_PER_IMAGE
        + n_stage2 * STAGE1_WALL_SECONDS_PER_IMAGE * STAGE2_INPUT_MULTIPLIER
    )


def query_vision_stats(
    *,
    corpus_count: int,
    sent_names: list[str],
    predicted_names: list[str],
    vision_true: set[str],
    is_full_vision: bool = False,
) -> dict:
    sent = corpus_count if is_full_vision else len(sent_names)
    stage2_lower = len(vision_true) if is_full_vision else len(set(sent_names) & vision_true)
    requests = stage1_request_count(sent) + stage2_request_count(stage2_lower)
    tokens = estimate_tokens(sent, stage2_lower)
    usd = estimate_usd(tokens["input_tokens"], tokens["output_tokens"])
    return {
        "vision_sent_images": sent,
        "vision_stage2_lower_bound": stage2_lower,
        "api_requests": requests,
        "api_requests_stage1": stage1_request_count(sent),
        "api_requests_stage2_lower_bound": stage2_request_count(stage2_lower),
        "estimated_usd": round(usd, 6),
        "estimated_latency_seconds": round(estimate_wall_seconds(sent, stage2_lower), 3),
        "predicted_count": len(predicted_names),
        "corpus_count": corpus_count,
        "tokens": {
            "input": round(tokens["input_tokens"], 1),
            "output": round(tokens["output_tokens"], 1),
            "stage2": tokens["stage2_tokens"],
        },
    }


def _meets(
    summary: dict,
    baseline: dict,
    *,
    f1_slack: float,
    r_slack: float,
    fn_slack: int,
    p_slack: float | None = None,
) -> bool:
    precision_ok = True
    if p_slack is not None:
        precision_ok = (
            summary["macro_precision"] + 1e-12
            >= baseline["macro_precision"] - p_slack
        )
    return (
        precision_ok
        and summary["macro_f1"] + 1e-12 >= baseline["macro_f1"] - f1_slack
        and summary["macro_recall"] + 1e-12 >= baseline["macro_recall"] - r_slack
        and int(summary["micro_fn"]) <= int(baseline["micro_fn"]) + fn_slack
    )


def select_hybrid_policies(dev_by_band: dict[str, dict], baseline_dev: dict) -> dict:
    """Choose Hybrid bands from DEV summaries only. Do not pass hold-out."""
    baseline_sent = float(baseline_dev["mean_vision_sent"])
    candidates = {
        name: payload
        for name, payload in dev_by_band.items()
        if name not in SENTINEL_BAND_NAMES
        and float(payload["mean_vision_sent"]) >= MIN_HYBRID_VISION_SENT
    }
    if not candidates:
        candidates = {
            name: payload
            for name, payload in dev_by_band.items()
            if name not in SENTINEL_BAND_NAMES
        }

    def reduction(payload: dict) -> float:
        return vision_reduction(payload["mean_vision_sent"], baseline_sent)

    def precision_key(item: tuple[str, dict]) -> tuple:
        name, payload = item
        return (
            payload["macro_precision"],
            payload["macro_f1"],
            reduction(payload),
            -payload["micro_fn"],
            name,
        )

    def balanced_score(payload: dict) -> float:
        return payload["macro_f1"] - BALANCED_SEND_WEIGHT * (
            payload["mean_vision_sent"] / baseline_sent if baseline_sent else 0.0
        )

    def balanced_key(item: tuple[str, dict]) -> tuple:
        name, payload = item
        return (balanced_score(payload), reduction(payload), payload["macro_f1"], name)

    def api_key(item: tuple[str, dict]) -> tuple:
        name, payload = item
        return (reduction(payload), payload["macro_f1"], -payload["micro_fn"], name)

    quality_pool = [
        item for item in candidates.items()
        if _meets(
            item[1], baseline_dev,
            f1_slack=QUALITY_F1_SLACK,
            r_slack=QUALITY_R_SLACK,
            fn_slack=QUALITY_FN_SLACK,
            p_slack=QUALITY_P_SLACK,
        )
    ]
    precision_pool = [
        item for item in candidates.items()
        if item[1]["macro_recall"] + 1e-12 >= baseline_dev["macro_recall"] - PRECISION_R_SLACK
    ] or list(candidates.items())
    api_pool = [
        item for item in candidates.items()
        if _meets(
            item[1], baseline_dev,
            f1_slack=API_F1_SLACK,
            r_slack=API_R_SLACK,
            fn_slack=API_FN_SLACK,
        )
    ] or list(candidates.items())

    picked = {}

    def take(key: str, pool: list[tuple[str, dict]], sort_key) -> None:
        ordered = sorted(pool, key=sort_key, reverse=True)
        for name, payload in ordered:
            if name not in picked.values():
                picked[key] = name
                return
        if ordered:
            picked[key] = ordered[0][0]

    take("precision_first", precision_pool, precision_key)
    take("balanced", list(candidates.items()), balanced_key)
    take("api_reduction", api_pool, api_key)

    quality_name = None
    if quality_pool:
        quality_name = sorted(quality_pool, key=lambda item: (reduction(item[1]), item[1]["macro_f1"]), reverse=True)[0][0]

    policies = {}
    for key, name in picked.items():
        payload = candidates[name]
        policies[key] = {
            "band": name,
            "dev": {
                "macro_precision": payload["macro_precision"],
                "macro_recall": payload["macro_recall"],
                "macro_f1": payload["macro_f1"],
                "micro_fn": payload["micro_fn"],
                "micro_fp": payload["micro_fp"],
                "mean_vision_sent": payload["mean_vision_sent"],
                "vision_reduction": reduction(payload),
            },
        }
    return {
        "policies": policies,
        "quality_match_band": quality_name,
        "quality_match_met": quality_name is not None,
        "selection_split": "dev",
        "notes": (
            "Bands were compared on the dev split only. Hold-out was not used "
            "to choose thresholds."
        ),
    }
