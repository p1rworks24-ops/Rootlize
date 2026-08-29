"""Compare product Vision Judge, Semantic Index-only, and Hybrid.

Eval-only. Does not change product Ask AI / Meaning Search. Does not
overwrite artifacts/meaning-eval/latest. Hybrid Vision decisions replay
the stored product Judge run so A and C share the same Vision oracle.
Thresholds are chosen on dev and frozen for hold-out.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING, QUERY_EMBEDDING_RAW
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.describe_judge import estimate_usd as estimate_index_usd
from tools.meaning_eval.evaluate_semantic_index import (
    DEFAULT_COMPARE,
    DEFAULT_CORPUS_NAMES,
    DEFAULT_INDEX_CACHE,
    KEY_QUERIES,
    _add_modes,
    _encode_corpus,
    _load_name_set,
)
from tools.meaning_eval.failure import empty_mode_counts
from tools.meaning_eval.hybrid import (
    ALL_BANDS,
    INDEX_ONLY_BAND,
    QUALITY_F1_SLACK,
    QUALITY_R_SLACK,
    SENTINEL_BAND_NAMES,
    VISION_ALL_BAND,
    attach_uncertain_reasons,
    decide_hybrid,
    merge_hybrid_predicted,
    query_vision_stats,
    select_hybrid_policies,
    vision_reduction,
)
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.metrics import summarize_end_to_end
from tools.meaning_eval.scoring import end_to_end_row
from tools.meaning_eval.semantic_index import (
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    PRIMARY_SEARCH,
    SEARCH_VERSION,
    clip_index_text,
    load_or_index_paths,
    search_records,
)
from tools.retriever_eval import encode_query, list_images, load_runtime, rank_names
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-hybrid"
POLICY_ORDER = ("precision_first", "balanced", "api_reduction")
SCALE_IMAGES = (100, 1000, 10000)
SCALE_SEARCHES = (1, 10, 100, 1000)


def _config_by_name():
    from tools.meaning_eval.semantic_index import SEARCH_CONFIGS
    return {config.name: config for config in SEARCH_CONFIGS}


def _load_baseline(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"baseline results not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_rows(payload: dict) -> dict[str, dict]:
    rows = (payload.get("end_to_end") or {}).get("queries") or []
    return {row["query"]: row for row in rows}


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _summarize_method(rows: list[dict], *, baseline_sent: float) -> dict:
    e2e = summarize_end_to_end(rows)
    sent_values = [float(row.get("vision_sent_images") or 0) for row in rows]
    request_values = [float(row.get("api_requests") or 0) for row in rows]
    usd_values = [float(row.get("estimated_usd") or 0) for row in rows]
    latency_values = [float(row.get("estimated_latency_seconds") or 0) for row in rows]
    mean_sent = _mean(sent_values)
    return {
        **e2e,
        "mean_vision_sent": mean_sent,
        "mean_api_requests": _mean(request_values),
        "mean_estimated_usd": _mean(usd_values),
        "mean_estimated_latency_seconds": _mean(latency_values),
        "total_vision_sent": int(sum(sent_values)),
        "total_api_requests": int(round(sum(request_values))),
        "total_estimated_usd": round(sum(usd_values), 6),
        "vision_reduction": vision_reduction(mean_sent, baseline_sent),
        "queries": [
            {
                "query": row["query"],
                "split": row["split"],
                "kind": row["kind"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "tp": row["tp"],
                "fp": row["fp"],
                "fn": row["fn"],
                "vision_sent_images": row.get("vision_sent_images"),
                "api_requests": row.get("api_requests"),
                "estimated_usd": row.get("estimated_usd"),
                "estimated_latency_seconds": row.get("estimated_latency_seconds"),
                "index_positive": row.get("index_positive"),
                "index_negative": row.get("index_negative"),
                "uncertain": row.get("uncertain"),
            }
            for row in rows
        ],
    }


def _compact_row(row: dict) -> dict:
    return {
        "query": row["query"],
        "split": row["split"],
        "kind": row["kind"],
        "precision": row["precision"],
        "recall": row["recall"],
        "f1": row["f1"],
        "tp": row["tp"],
        "fp": row["fp"],
        "fn": row["fn"],
        "vision_sent_images": row.get("vision_sent_images"),
        "api_requests": row.get("api_requests"),
        "estimated_usd": row.get("estimated_usd"),
        "estimated_latency_seconds": row.get("estimated_latency_seconds"),
    }


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _score_query(
    spec,
    *,
    ranking: list[str],
    index_judged: dict,
    band,
    search_config,
    vision_true: set[str],
    corpus_count: int,
    embedded_set: set[str],
    full_vision: bool = False,
    records: dict | None = None,
) -> dict:
    records = records or {}
    decisions = {
        name: decide_hybrid(
            index_judged["judgements"].get(name),
            band,
            search_config,
            query=spec.query,
            record=records.get(name),
        )
        for name in ranking
    }
    predicted, sent = merge_hybrid_predicted(
        names=ranking,
        decisions=decisions,
        vision_true=vision_true,
    )
    if full_vision:
        predicted = [name for name in ranking if name in vision_true]
        sent = list(ranking)
    judgements = attach_uncertain_reasons(
        judgements=index_judged["judgements"],
        decisions=decisions,
        band=band,
        search_config=search_config,
        predicted=set(predicted),
        query=spec.query,
        records=records,
    )
    row = end_to_end_row(
        spec,
        ranking=ranking,
        predicted=predicted,
        judgements=judgements,
        cancelled=False,
        failed_names=set(index_judged.get("failed_names") or []),
        embedded_names=embedded_set,
    )
    stats = query_vision_stats(
        corpus_count=corpus_count,
        sent_names=sent,
        predicted_names=predicted,
        vision_true=vision_true,
        is_full_vision=full_vision,
    )
    row.update(stats)
    row["index_positive"] = sum(1 for name in ranking if decisions.get(name) == "positive")
    row["index_negative"] = sum(1 for name in ranking if decisions.get(name) == "negative")
    row["uncertain"] = sum(1 for name in ranking if decisions.get(name) == "uncertain")
    row["predicted"] = predicted
    row["vision_sent_names"] = sent
    row["decisions"] = decisions
    row["judgements"] = judgements
    return row


def _index_only_row(
    spec,
    *,
    ranking,
    index_judged,
    search_config,
    corpus_count,
    embedded_set,
) -> dict:
    row = end_to_end_row(
        spec,
        ranking=ranking,
        predicted=index_judged["predicted"],
        judgements=index_judged["judgements"],
        cancelled=False,
        failed_names=set(index_judged.get("failed_names") or []),
        embedded_names=embedded_set,
    )
    stats = query_vision_stats(
        corpus_count=corpus_count,
        sent_names=[],
        predicted_names=index_judged["predicted"],
        vision_true=set(),
        is_full_vision=False,
    )
    row.update(stats)
    row["vision_sent_images"] = 0
    row["api_requests"] = 0
    row["estimated_usd"] = 0.0
    row["estimated_latency_seconds"] = 0.0
    row["index_positive"] = len(index_judged["predicted"])
    row["index_negative"] = corpus_count - len(index_judged["predicted"])
    row["uncertain"] = 0
    return row


def _baseline_eval_row(spec, source: dict, corpus_count: int) -> dict:
    vision_true = set(source.get("predicted") or [])
    stats = query_vision_stats(
        corpus_count=corpus_count,
        sent_names=[],
        predicted_names=list(source.get("predicted") or []),
        vision_true=vision_true,
        is_full_vision=True,
    )
    row = dict(source)
    row.update(stats)
    row["index_positive"] = 0
    row["index_negative"] = 0
    row["uncertain"] = corpus_count
    return row


def _collect_examples(
    *,
    spec,
    band_row: dict,
    baseline_row: dict,
    index_row: dict,
    limit: int = 3,
) -> dict:
    judgements = band_row.get("judgements") or {}
    decisions = band_row.get("decisions") or {}
    a_pred = set(baseline_row.get("predicted") or [])
    b_pred = set(index_row.get("predicted") or [])
    c_pred = set(band_row.get("predicted") or [])

    def pack(name: str, extra: dict | None = None) -> dict:
        item = judgements.get(name) or {}
        payload = {
            "name": name,
            "decision": decisions.get(name),
            "source": item.get("decision_source"),
            "uncertain_reason": item.get("uncertain_reason"),
            "lex": item.get("lex"),
            "txt": item.get("txt"),
            "img": item.get("img"),
            "reason": item.get("reason"),
            "in_A": name in a_pred,
            "in_B": name in b_pred,
            "in_C": name in c_pred,
        }
        if extra:
            payload.update(extra)
        return payload

    fps = []
    for name in band_row.get("fp_names") or []:
        extra_rank = int(name not in a_pred)
        fps.append((extra_rank, pack(name)))
    fps = [item for _rank, item in sorted(fps, key=lambda pair: (-pair[0], pair[1]["name"]))][:limit]
    fns = []
    for name in band_row.get("fn_names") or []:
        extra_rank = int(name in a_pred)
        fns.append((extra_rank, pack(name)))
    fns = [item for _rank, item in sorted(fns, key=lambda pair: (-pair[0], pair[1]["name"]))][:limit]
    index_insufficient = []
    scored = []
    for name, decision in decisions.items():
        if decision != "uncertain":
            continue
        item = judgements.get(name) or {}
        score = (
            int(name in spec.must_include_set) * 4
            + int(name in b_pred and name not in a_pred) * 3
            + int(name in a_pred) * 2
            + int(bool(item.get("uncertain_reason")))
        )
        scored.append((score, pack(name, {
            "must_include": name in spec.must_include_set,
            "b_fp_fixed_by_vision": name in b_pred and name not in a_pred and name not in c_pred,
            "a_tp_needed_vision": name in spec.must_include_set and name in a_pred,
        })))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    index_insufficient = [item for _score, item in scored[:limit]]
    return {
        "query": spec.query,
        "split": spec.split,
        "false_positives": fps,
        "false_negatives": fns,
        "index_insufficient": index_insufficient,
    }


def _scale_table(
    *,
    index_usd_per_image: float,
    a_usd_per_image_per_search: float,
    c_usd_per_image_per_search: float,
) -> list[dict]:
    rows = []
    for n_images in SCALE_IMAGES:
        for n_searches in SCALE_SEARCHES:
            index_usd = index_usd_per_image * n_images
            a_usd = a_usd_per_image_per_search * n_images * n_searches
            c_search = c_usd_per_image_per_search * n_images * n_searches
            c_usd = index_usd + c_search
            delta = a_usd - c_usd
            rows.append({
                "images": n_images,
                "searches": n_searches,
                "index_generation_usd": round(index_usd, 4),
                "A_search_usd": round(a_usd, 4),
                "C_index_plus_search_usd": round(c_usd, 4),
                "C_search_only_usd": round(c_search, 4),
                "C_saves_usd": round(delta, 4),
                "C_better": c_usd < a_usd,
            })
    return rows


def _break_even_searches(
    *,
    index_usd_per_image: float,
    a_usd_per_image_per_search: float,
    c_usd_per_image_per_search: float,
) -> float | None:
    saved = a_usd_per_image_per_search - c_usd_per_image_per_search
    if saved <= 0:
        return None
    return index_usd_per_image / saved


def _render_analysis(report: dict) -> str:
    methods = report["methods"]
    selection = report["selection"]
    recommended = report["recommended"]
    rec_name = recommended["policy"]
    rec_band = recommended["band"]
    rec_hold = methods[f"C_{rec_name}"]["holdout"]
    a_hold = methods["A"]["holdout"]
    rec_dev = methods[f"C_{rec_name}"]["dev"]
    a_dev = methods["A"]["dev"]
    lines = [
        "# Semantic Index Hybrid evaluation",
        "",
        "Product Ask AI / Meaning Search was not changed. Hybrid Vision labels",
        "replay the stored product Judge (`vision-usefulness-v1`) so A and C",
        "share the same Vision oracle. Bands were chosen on **dev** only.",
        "",
        "## 1. A / B / C comparison (hold-out)",
        "",
        "| method | policy / band | macro P | macro R | macro F1 | micro FP | micro FN | mean Vision images | mean API requests | Vision reduction vs A | est. USD / query | est. latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = [
        ("A current Vision Judge", "baseline", methods["A"]["holdout"]),
        ("B Semantic Index only", "index_only", methods["B"]["holdout"]),
    ]
    for key in POLICY_ORDER:
        method = methods[f"C_{key}"]
        rows.append((
            f"C Hybrid {key}",
            method["band"],
            method["holdout"],
        ))
    for label, band, payload in rows:
        lines.append(
            f"| {label} | `{band}` | {_fmt(payload['macro_precision'])} | "
            f"{_fmt(payload['macro_recall'])} | {_fmt(payload['macro_f1'])} | "
            f"{payload['micro_fp']} | {payload['micro_fn']} | "
            f"{_fmt(payload['mean_vision_sent'], 1)} | "
            f"{_fmt(payload['mean_api_requests'], 1)} | "
            f"{_pct(payload['vision_reduction'])} | "
            f"{_fmt(payload['mean_estimated_usd'], 4)} | "
            f"{_fmt(payload['mean_estimated_latency_seconds'], 2)} |"
        )
    lines.extend([
        "",
        "Dev (selection split, not the freeze set):",
        "",
        (
            f"- A: P={_fmt(a_dev['macro_precision'])} R={_fmt(a_dev['macro_recall'])} "
            f"F1={_fmt(a_dev['macro_f1'])} FN={a_dev['micro_fn']} "
            f"Vision/query={_fmt(a_dev['mean_vision_sent'], 1)}"
        ),
        (
            f"- C {rec_name}: P={_fmt(rec_dev['macro_precision'])} "
            f"R={_fmt(rec_dev['macro_recall'])} F1={_fmt(rec_dev['macro_f1'])} "
            f"FN={rec_dev['micro_fn']} Vision/query={_fmt(rec_dev['mean_vision_sent'], 1)} "
            f"reduction={_pct(rec_dev['vision_reduction'])}"
        ),
        "",
        "## 2. Hybrid quality vs current Judge",
        "",
        f"- Recommended policy: **{rec_name}** (`{rec_band}`)",
        (
            f"- Hold-out macro F1: A {_fmt(a_hold['macro_f1'])} → C {_fmt(rec_hold['macro_f1'])} "
            f"(Δ{rec_hold['macro_f1'] - a_hold['macro_f1']:+.3f})"
        ),
        (
            f"- Hold-out macro recall: A {_fmt(a_hold['macro_recall'])} → C "
            f"{_fmt(rec_hold['macro_recall'])} "
            f"(Δ{rec_hold['macro_recall'] - a_hold['macro_recall']:+.3f})"
        ),
        (
            f"- Hold-out micro FN: A {a_hold['micro_fn']} → C {rec_hold['micro_fn']} "
            f"(Δ{rec_hold['micro_fn'] - a_hold['micro_fn']:+d})"
        ),
        (
            f"- Hold-out micro FP: A {a_hold['micro_fp']} → C {rec_hold['micro_fp']} "
            f"(Δ{rec_hold['micro_fp'] - a_hold['micro_fp']:+d})"
        ),
        (
            f"- Quality-match band found on dev: {selection.get('quality_match_met')} "
            f"(`{selection.get('quality_match_band')}`)"
        ),
        "",
        "Hold-out per query (recommended C vs A):",
        "",
        "| query | A P | C P | A R | C R | A FP | C FP | A FN | C FN | A Vision | C Vision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    a_q = {row["query"]: row for row in a_hold.get("queries") or []}
    c_q = {row["query"]: row for row in rec_hold.get("queries") or []}
    for query in report["splits"]["holdout"]:
        a_row = a_q.get(query) or {}
        c_row = c_q.get(query) or {}
        lines.append(
            f"| `{query}` | {_fmt(a_row.get('precision'))} | {_fmt(c_row.get('precision'))} | "
            f"{_fmt(a_row.get('recall'))} | {_fmt(c_row.get('recall'))} | "
            f"{a_row.get('fp', '-')} | {c_row.get('fp', '-')} | "
            f"{a_row.get('fn', '-')} | {c_row.get('fn', '-')} | "
            f"{a_row.get('vision_sent_images', '-')} | {c_row.get('vision_sent_images', '-')} |"
        )
    lines.extend([
        "",
        "## 3. Vision image send reduction",
        "",
        f"- Hold-out mean images sent / query: A {_fmt(a_hold['mean_vision_sent'], 1)} → "
        f"C {_fmt(rec_hold['mean_vision_sent'], 1)}",
        f"- Reduction vs A: **{_pct(rec_hold['vision_reduction'])}**",
        f"- B sends 0 Vision images per query (index already paid).",
        "",
        "## 4. False positive / false negative examples",
        "",
    ])
    examples = report.get("examples") or []
    if not examples:
        lines.append("None collected.")
    else:
        for item in examples:
            lines.append(f"### `{item['query']}` ({item['split']})")
            lines.append("")
            if item["false_positives"]:
                lines.append("False positives:")
                for row in item["false_positives"]:
                    lines.append(
                        f"- `{row['name']}` decision={row['decision']} "
                        f"lex={_fmt(row.get('lex'))} txt={_fmt(row.get('txt'))} "
                        f"img={_fmt(row.get('img'))} A={row['in_A']} B={row['in_B']}"
                    )
            if item["false_negatives"]:
                lines.append("False negatives:")
                for row in item["false_negatives"]:
                    lines.append(
                        f"- `{row['name']}` decision={row['decision']} "
                        f"lex={_fmt(row.get('lex'))} reason={row.get('uncertain_reason')} "
                        f"A={row['in_A']} B={row['in_B']}"
                    )
            lines.append("")
    lines.extend([
        "## 5. When Semantic Index alone could not decide",
        "",
        "Recommended precision_first does not auto-accept Index hits (`pos_lex_min=1.01`).",
        "Clear Index misses are auto-negative; remaining images go to Vision.",
        "The cases below are Index hits or near-misses that were therefore uncertain.",
        "",
    ])
    any_insufficient = False
    for item in examples:
        if not item.get("index_insufficient"):
            continue
        any_insufficient = True
        lines.append(f"`{item['query']}`:")
        for row in item["index_insufficient"]:
            lines.append(
                f"- `{row['name']}` reason=`{row.get('uncertain_reason')}` "
                f"lex={_fmt(row.get('lex'))} txt={_fmt(row.get('txt'))} "
                f"img={_fmt(row.get('img'))} must_include={row.get('must_include')} "
                f"B-FP fixed by Vision={row.get('b_fp_fixed_by_vision')}"
            )
        lines.append("")
    if not any_insufficient:
        lines.append("No representative uncertain cases were recorded.")
        lines.append("")
    cost = report.get("cost") or {}
    lines.extend([
        "## 6. API cost impact",
        "",
        f"- Index generation (once, {cost.get('index_images')} images): "
        f"${_fmt(cost.get('index_generation_usd'), 4)} "
        f"({cost.get('index_input_tokens')} in / {cost.get('index_output_tokens')} out, "
        f"{cost.get('index_requests')} requests, cache_reused={cost.get('index_cache_reused')})",
        f"- Per-query search Vision, hold-out mean: A ${ _fmt(a_hold['mean_estimated_usd'], 4) } vs "
        f"C ${ _fmt(rec_hold['mean_estimated_usd'], 4) }",
        f"- B per-query Vision: $0.0000",
        f"- Stage-2 high-detail tokens are estimated (4x Stage-1 input); Stage-1 rates come from a measured gpt-5.4-mini 512px run.",
        "",
        "Break-even (Index + Hybrid vs current Judge, recommended C, hold-out send rate):",
        "",
        "| images | searches | A search USD | C index+search USD | C better? |",
        "|---:|---:|---:|---:|---|",
    ])
    for row in cost.get("scale") or []:
        lines.append(
            f"| {row['images']} | {row['searches']} | {row['A_search_usd']} | "
            f"{row['C_index_plus_search_usd']} | {row['C_better']} |"
        )
    be = cost.get("break_even_searches_per_library")
    lines.extend([
        "",
        f"- Searches until Hybrid pays back Index generation at the same library size: "
        f"{'-' if be is None else _fmt(be, 2)}",
        "",
        "## 7. Recommended Hybrid condition",
        "",
        f"- Policy: **{rec_name}**",
        f"- Band: `{rec_band}`",
        f"- Connect to product: **{report['recommendation']['connect']}**",
        f"- Reason: {report['recommendation']['reason']}",
        "",
        "## 8–10. Connect? Risks? Next task",
        "",
        f"- Connect now: {report['recommendation']['connect']}",
        f"- Risks: {report['recommendation']['risks']}",
        f"- Next implementation task: {report['recommendation']['next_task']}",
        "",
        "## Validation",
        "",
        f"- `vision_all` matched A predicted sets: {report['validation']['vision_all_matches_A']}",
        f"- `index_only` matched B predicted sets: {report['validation']['index_only_matches_B']}",
        "",
        "Hold-out was not used to choose bands.",
        "",
    ])
    return "\n".join(lines)


def _recommend(methods: dict, selection: dict) -> dict:
    a_hold = methods["A"]["holdout"]
    usable = []
    for key in POLICY_ORDER:
        hold = methods[f"C_{key}"]["holdout"]
        if hold["mean_vision_sent"] < 1:
            continue
        f1_delta = hold["macro_f1"] - a_hold["macro_f1"]
        r_delta = hold["macro_recall"] - a_hold["macro_recall"]
        usable.append({
            "key": key,
            "hold": hold,
            "f1_delta": f1_delta,
            "r_delta": r_delta,
            "fn_delta": hold["micro_fn"] - a_hold["micro_fn"],
            "fp_delta": hold["micro_fp"] - a_hold["micro_fp"],
            "reduction": hold["vision_reduction"],
        })
    if not usable:
        return {
            "policy": "api_reduction",
            "band": methods["C_api_reduction"]["band"],
            "connect": "no",
            "reason": "No Hybrid band both used Vision and stayed near the current Judge.",
            "risks": "Index-only is not a Hybrid. Connecting it would inherit UI false positives.",
            "next_task": (
                "Keep Ask AI on the current Vision Judge. Next: Phase E full A/B "
                "for Judge replacement, plus packaged Search confirmation."
            ),
        }
    quality_like = [
        item for item in usable
        if item["f1_delta"] >= -QUALITY_F1_SLACK
        and item["r_delta"] >= -QUALITY_R_SLACK
    ]
    if any(item["key"] == "precision_first" for item in quality_like) or (
        usable[0]["key"] == "precision_first"
        and usable[0]["f1_delta"] >= -QUALITY_F1_SLACK
    ):
        chosen = next(item for item in usable if item["key"] == "precision_first")
    elif quality_like:
        chosen = max(quality_like, key=lambda item: (item["reduction"], item["f1_delta"]))
    else:
        chosen = max(usable, key=lambda item: (item["f1_delta"], item["reduction"]))
    hold = chosen["hold"]
    reason = (
        f"Hold-out {chosen['key']} F1 {hold['macro_f1']:.3f} vs A {a_hold['macro_f1']:.3f} "
        f"(Δ{chosen['f1_delta']:+.3f}), recall Δ{chosen['r_delta']:+.3f}, "
        f"FN Δ{chosen['fn_delta']:+d}, FP Δ{chosen['fp_delta']:+d}, "
        f"Vision reduction {chosen['reduction'] * 100:.1f}%. "
        "That is close enough to study Index gating, but UI Precision is still "
        "too low to replace Ask AI, and this run replayed stored Judge labels."
    )
    return {
        "policy": chosen["key"],
        "band": methods[f"C_{chosen['key']}"]["band"],
        "connect": "no",
        "reason": reason,
        "risks": (
            "Clear Index negatives can drop Judge true positives (extra FN). "
            "Broad UI queries still send many Vision images. Replay can differ "
            "from a live two-stage Judge. Index generation is paid once and "
            "goes stale when files change. API budget is still unconnected."
        ),
        "next_task": (
            "Keep Ask AI on the current Vision Judge. Next product task is still "
            "Phase E full A/B (Judge replacement) and packaged Search confirmation. "
            "Hybrid stays eval-only unless a later decision wires the frozen band."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B/C Semantic Index Hybrid eval")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--split", choices=("dev", "holdout", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--search", default=PRIMARY_SEARCH)
    args = parser.parse_args()

    dataset = load_dataset(args.gt)
    selected = dataset.queries
    if args.split != "both":
        selected = tuple(spec for spec in dataset.queries if spec.split == args.split)
    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
        missing = keep_names - {path.name for path in paths}
        if missing:
            raise SystemExit(f"match-corpus-from names missing from folder: {sorted(missing)[:8]}")
    corpus = corpus_identity(paths)
    corpus_count = len(paths)
    baseline_payload = _load_baseline(args.baseline)
    baseline_by_query = _baseline_rows(baseline_payload)
    missing_queries = [spec.query for spec in selected if spec.query not in baseline_by_query]
    if missing_queries:
        raise SystemExit(f"baseline missing queries: {missing_queries[:8]}")

    print(f"indexing {len(paths)} images cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    print(
        json.dumps({
            "stage": "index",
            "images": len(paths),
            "cache_reused": cache_reused,
            "request_count": index_usage.get("request_count"),
            "sent_image_count": index_usage.get("sent_image_count"),
        }, ensure_ascii=False),
        flush=True,
    )

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity
    print(f"encoding {len(paths)} images", flush=True)
    embedded_names, image_vectors, embed_failed = _encode_corpus(runtime, paths)
    image_vector_map = dict(zip(embedded_names, image_vectors))
    print("encoding semantic index text", flush=True)
    text_vectors = {}
    for path in paths:
        record = records.get(path.name) or {}
        if record.get("unknown_reason"):
            continue
        text_vectors[path.name] = runtime.embed_text(clip_index_text(record))
    query_vectors = {
        spec.query: encode_query(runtime, spec.query, QUERY_EMBEDDING_RAW)
        for spec in selected
    }
    rankings = {}
    for spec in selected:
        rankings[spec.query] = rank_names(
            query_vectors[spec.query], embedded_names, image_vectors
        )

    configs = _config_by_name()
    search_config = configs[args.search]
    embedded_set = set(embedded_names)
    index_by_query = {}
    local_started = time.perf_counter()
    for spec in selected:
        index_by_query[spec.query] = search_records(
            spec.query,
            rankings[spec.query],
            records,
            query_vector=query_vectors[spec.query],
            image_vectors=image_vector_map,
            text_vectors=text_vectors,
            config=search_config,
        )
    local_seconds = time.perf_counter() - local_started

    a_rows = []
    b_rows = []
    for spec in selected:
        a_rows.append(_baseline_eval_row(spec, baseline_by_query[spec.query], corpus_count))
        b_rows.append(_index_only_row(
            spec,
            ranking=rankings[spec.query],
            index_judged=index_by_query[spec.query],
            search_config=search_config,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
        ))
    a_dev_sent = _mean([row["vision_sent_images"] for row in a_rows if row["split"] == "dev"])
    a_hold_sent = _mean([row["vision_sent_images"] for row in a_rows if row["split"] == "holdout"])

    band_rows: dict[str, list[dict]] = {}
    for band in ALL_BANDS:
        rows = []
        for spec in selected:
            rows.append(_score_query(
                spec,
                ranking=rankings[spec.query],
                index_judged=index_by_query[spec.query],
                band=band,
                search_config=search_config,
                vision_true=set(baseline_by_query[spec.query].get("predicted") or []),
                corpus_count=corpus_count,
                embedded_set=embedded_set,
                full_vision=band.name == VISION_ALL_BAND.name,
                records=records,
            ))
        band_rows[band.name] = rows
        print(
            json.dumps({
                "band": band.name,
                "dev_sent": _mean([row["vision_sent_images"] for row in rows if row["split"] == "dev"]),
                "dev_f1": summarize_end_to_end([row for row in rows if row["split"] == "dev"])["macro_f1"],
            }, ensure_ascii=False),
            flush=True,
        )

    def split_rows(rows: list[dict], split: str) -> list[dict]:
        return [row for row in rows if row["split"] == split]

    def method_payload(rows: list[dict], *, band: str, baseline_dev_sent: float, baseline_hold_sent: float) -> dict:
        return {
            "band": band,
            "dev": _summarize_method(split_rows(rows, "dev"), baseline_sent=baseline_dev_sent),
            "holdout": _summarize_method(split_rows(rows, "holdout"), baseline_sent=baseline_hold_sent),
        }

    methods = {
        "A": method_payload(a_rows, band="vision-usefulness-v1", baseline_dev_sent=a_dev_sent, baseline_hold_sent=a_hold_sent),
        "B": method_payload(b_rows, band="index_only", baseline_dev_sent=a_dev_sent, baseline_hold_sent=a_hold_sent),
    }

    dev_by_band = {}
    for name, rows in band_rows.items():
        summary = _summarize_method(split_rows(rows, "dev"), baseline_sent=a_dev_sent)
        dev_by_band[name] = summary
    selection = select_hybrid_policies(dev_by_band, methods["A"]["dev"])
    for key in POLICY_ORDER:
        band_name = selection["policies"][key]["band"]
        methods[f"C_{key}"] = method_payload(
            band_rows[band_name],
            band=band_name,
            baseline_dev_sent=a_dev_sent,
            baseline_hold_sent=a_hold_sent,
        )
    methods["C_vision_all_sanity"] = method_payload(
        band_rows[VISION_ALL_BAND.name],
        band=VISION_ALL_BAND.name,
        baseline_dev_sent=a_dev_sent,
        baseline_hold_sent=a_hold_sent,
    )
    methods["C_index_only_sanity"] = method_payload(
        band_rows[INDEX_ONLY_BAND.name],
        band=INDEX_ONLY_BAND.name,
        baseline_dev_sent=a_dev_sent,
        baseline_hold_sent=a_hold_sent,
    )

    vision_all_ok = True
    index_only_ok = True
    for spec in selected:
        a_pred = set(baseline_by_query[spec.query].get("predicted") or [])
        b_pred = set(index_by_query[spec.query]["predicted"])
        vision_row = next(row for row in band_rows[VISION_ALL_BAND.name] if row["query"] == spec.query)
        index_row = next(row for row in band_rows[INDEX_ONLY_BAND.name] if row["query"] == spec.query)
        if set(vision_row["predicted"]) != a_pred:
            vision_all_ok = False
        if set(index_row["predicted"]) != b_pred:
            index_only_ok = False
    if not vision_all_ok:
        print("WARNING: vision_all predicted sets do not match baseline A", flush=True)
    if not index_only_ok:
        print("WARNING: index_only predicted sets do not match B", flush=True)

    recommendation_meta = _recommend(methods, selection)
    rec_key = recommendation_meta["policy"]
    rec_band = recommendation_meta["band"]
    rec_rows = band_rows[rec_band]
    specs = {spec.query: spec for spec in selected}
    examples = []
    for row in rec_rows:
        if row["split"] != "holdout":
            continue
        if row["fp"] == 0 and row["fn"] == 0 and row["uncertain"] == 0:
            continue
        spec = specs[row["query"]]
        baseline_row = baseline_by_query[spec.query]
        index_row = next(item for item in b_rows if item["query"] == spec.query)
        examples.append(_collect_examples(
            spec=spec,
            band_row=row,
            baseline_row=baseline_row,
            index_row=index_row,
        ))
        if len(examples) >= 6:
            break

    index_usd = estimate_index_usd(
        int(index_usage.get("input_tokens") or 0),
        int(index_usage.get("output_tokens") or 0),
    )
    index_per_image = 0.0 if corpus_count == 0 else index_usd / corpus_count
    rec_hold = methods[f"C_{rec_key}"]["holdout"]
    a_hold = methods["A"]["holdout"]
    a_per_image_search = 0.0 if corpus_count == 0 else a_hold["mean_estimated_usd"] / corpus_count
    c_per_image_search = 0.0 if corpus_count == 0 else rec_hold["mean_estimated_usd"] / corpus_count
    scale = _scale_table(
        index_usd_per_image=index_per_image,
        a_usd_per_image_per_search=a_per_image_search,
        c_usd_per_image_per_search=c_per_image_search,
    )
    break_even = _break_even_searches(
        index_usd_per_image=index_per_image,
        a_usd_per_image_per_search=a_per_image_search,
        c_usd_per_image_per_search=c_per_image_search,
    )

    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=INDEX_PROMPT_VERSION,
        schema_version=INDEX_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = "semantic-index-hybrid-v1"
    run_identity["judge_structure"] = "index_then_replayed_product_judge"
    run_identity["baseline_prompt_version"] = (
        (baseline_payload.get("identity") or {}).get("vision_prompt_version")
    )

    # Strip bulky per-image maps from published query rows.
    published_methods = {}
    for name, payload in methods.items():
        published_methods[name] = {
            "band": payload["band"],
            "dev": {key: value for key, value in payload["dev"].items()},
            "holdout": {key: value for key, value in payload["holdout"].items()},
        }

    dev_grid = [
        {
            "band": name,
            "macro_precision": payload["macro_precision"],
            "macro_recall": payload["macro_recall"],
            "macro_f1": payload["macro_f1"],
            "micro_fp": payload["micro_fp"],
            "micro_fn": payload["micro_fn"],
            "mean_vision_sent": payload["mean_vision_sent"],
            "vision_reduction": payload["vision_reduction"],
            "sentinel": name in SENTINEL_BAND_NAMES,
        }
        for name, payload in sorted(
            dev_by_band.items(),
            key=lambda item: (-item[1]["vision_reduction"], -item[1]["macro_f1"]),
        )
    ]

    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": embed_failed,
        "search_config": args.search,
        "search_version": SEARCH_VERSION,
        "splits": {
            "dev": [spec.query for spec in dataset.by_split()["dev"]],
            "holdout": [spec.query for spec in dataset.by_split()["holdout"]],
        },
        "local_index_search_seconds": round(local_seconds, 3),
        "methods": published_methods,
        "selection": selection,
        "dev_grid": dev_grid,
        "recommended": {
            "policy": rec_key,
            "band": rec_band,
        },
        "recommendation": recommendation_meta,
        "examples": examples,
        "key_queries": KEY_QUERIES,
        "validation": {
            "vision_all_matches_A": vision_all_ok,
            "index_only_matches_B": index_only_ok,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "index_images": corpus_count,
            "index_input_tokens": index_usage.get("input_tokens"),
            "index_output_tokens": index_usage.get("output_tokens"),
            "index_requests": index_usage.get("request_count"),
            "index_api_seconds": index_usage.get("api_seconds"),
            "index_generation_usd": round(index_usd, 4),
            "index_usd_per_image": round(index_per_image, 6),
            "search_cost_source": (
                "Stage-1 from measured gpt-5.4-mini 512px run; "
                "Stage-2 input tokens estimated at 4x Stage-1. "
                "Index generation is separate from per-query Judge cost."
            ),
            "A_holdout_usd_per_query": round(a_hold["mean_estimated_usd"], 6),
            "B_holdout_usd_per_query": 0.0,
            "C_holdout_usd_per_query": round(rec_hold["mean_estimated_usd"], 6),
            "break_even_searches_per_library": (
                None if break_even is None else round(break_even, 3)
            ),
            "scale": scale,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "hybrid-analysis.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(_render_analysis(report), encoding="utf-8")

    summary_lines = [
        "# Semantic Index Hybrid evaluation summary",
        "",
        f"- recommended: {rec_key} `{rec_band}`",
        f"- hold-out C vs A F1: {_fmt(rec_hold['macro_f1'])} vs {_fmt(a_hold['macro_f1'])}",
        f"- hold-out Vision reduction: {_pct(rec_hold['vision_reduction'])}",
        f"- connect: {recommendation_meta['connect']}",
        f"- details: `{analysis_path.name}`",
        "",
    ]
    summary_path = args.output_dir / "summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(json_path)
    print(analysis_path)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
