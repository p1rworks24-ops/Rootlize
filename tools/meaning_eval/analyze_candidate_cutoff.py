"""Offline candidate-cutoff analysis for Meaning Search.

Uses an existing meaning_eval results.json for rank / end-to-end simulation.
Optionally re-runs official OpenCLIP ranking to inspect similarity distributions.
Does not change product search logic or call Vision.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import QUERY_EMBEDDING_RAW
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.metrics import recall_from_ranks, summarize_end_to_end
from tools.retriever_eval import encode_query, list_images, load_runtime
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

FIXED_K = (10, 20, 40, 80)
RANK_BUCKETS = (
    ("1-10", 1, 10),
    ("11-20", 11, 20),
    ("21-40", 21, 40),
    ("41-80", 41, 80),
    ("81+", 81, 10_000),
)
REL_TAUS = (0.50, 0.60, 0.70, 0.80, 0.90)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100.0
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def _bucket_label(rank: int) -> str:
    for label, start, end in RANK_BUCKETS:
        if start <= rank <= end:
            return label
    return "81+"


def rank_with_scores(
    query_vector: list[float],
    names: list[str],
    image_vectors: list[list[float]],
) -> list[tuple[str, float]]:
    scores = [
        math.fsum(
            query_value * image_value
            for query_value, image_value in zip(query_vector, image_vector)
        )
        for image_vector in image_vectors
    ]
    order = sorted(range(len(names)), key=lambda index: (-scores[index], names[index]))
    return [(names[index], scores[index]) for index in order]


def dynamic_cutoff_k(
    scores: list[float],
    *,
    min_k: int,
    max_k: int,
    tau: float,
) -> int:
    """Keep at least min_k, then continue while score >= top * tau, cap at max_k."""
    n = len(scores)
    if n == 0:
        return 0
    floor = min(max(min_k, 1), n)
    cap = min(max(max_k, floor), n)
    top = scores[0]
    k = floor
    if top <= 0:
        return cap if tau <= 0 else floor
    for index in range(floor, cap):
        if scores[index] >= top * tau:
            k = index + 1
        else:
            break
    return k


def _query_rows(report: dict) -> list[dict]:
    retriever = {
        row["query"]: row for row in report.get("retriever", {}).get("queries") or []
    }
    e2e = {
        row["query"]: row
        for row in (report.get("end_to_end") or {}).get("queries") or []
    }
    rows = []
    for query, retriever_row in retriever.items():
        e2e_row = e2e.get(query) or {}
        ranks = {
            name: None if rank is None else int(rank)
            for name, rank in (retriever_row.get("relevant_ranks") or {}).items()
        }
        predicted = list(e2e_row.get("predicted") or [])
        predicted_set = set(predicted)
        must_include = set(ranks)
        tp_names = sorted(must_include & predicted_set)
        rows.append({
            "query": query,
            "split": retriever_row["split"],
            "kind": retriever_row.get("kind") or "",
            "ranks": ranks,
            "must_n": len(must_include),
            "predicted": predicted,
            "tp_names": tp_names,
            "current_tp": len(tp_names),
            "current_fn": int(e2e_row.get("fn") or len(must_include - predicted_set)),
            "current_fp": int(e2e_row.get("fp") or 0),
            "current_recall": float(e2e_row.get("recall") if e2e_row else 1.0),
            "best_rank": retriever_row.get("best_relevant_rank"),
            "worst_rank": max(
                (rank for rank in ranks.values() if rank is not None),
                default=None,
            ),
            "missing": list(retriever_row.get("missing_from_corpus") or []),
        })
    return rows


def _retriever_at_k(rows: list[dict], k: int) -> dict:
    recalls = [recall_from_ranks(row["ranks"], k) for row in rows]
    labeled = [row for row in rows if row["must_n"]]
    covered = sum(
        1 for row in labeled
        if row["worst_rank"] is not None and row["worst_rank"] <= k
    )
    return {
        "n": len(rows),
        "macro_recall": _mean(recalls),
        "queries_with_labels": len(labeled),
        "queries_all_must_include_in_topk": covered,
        "all_must_include_coverage": (
            1.0 if not labeled else covered / len(labeled)
        ),
    }


def _e2e_at_k(rows: list[dict], k: int) -> dict:
    simulated = []
    lost_tps = []
    for row in rows:
        kept = [
            name for name in row["tp_names"]
            if (row["ranks"].get(name) or 10**9) <= k
        ]
        lost = [
            name for name in row["tp_names"]
            if (row["ranks"].get(name) or 10**9) > k
        ]
        must_n = row["must_n"]
        tp = len(kept)
        fn = must_n - tp
        simulated.append({
            "query": row["query"],
            "split": row["split"],
            "tp": tp,
            "fp": 0,
            "fn": fn,
            "precision": 1.0 if tp + 0 == tp else 1.0,
            "recall": 1.0 if must_n == 0 else tp / must_n,
        })
        for name in lost:
            lost_tps.append({
                "query": row["query"],
                "split": row["split"],
                "image": name,
                "rank": row["ranks"][name],
            })
    summary = summarize_end_to_end(simulated)
    current_fn = sum(row["current_fn"] for row in rows)
    current_tp = sum(row["current_tp"] for row in rows)
    return {
        "macro_recall": summary["macro_recall"],
        "micro_recall": summary["micro_recall"],
        "micro_tp": summary["micro_tp"],
        "micro_fn": summary["micro_fn"],
        "lost_current_tp": len(lost_tps),
        "fn_increase_vs_full_send": summary["micro_fn"] - current_fn,
        "current_micro_tp": current_tp,
        "current_micro_fn": current_fn,
        "lost_tp_examples": lost_tps[:20],
        "lost_tp_all": lost_tps,
    }


def _send_stats(corpus_count: int, n_queries: int, k: int) -> dict:
    per_query = min(k, corpus_count)
    full = corpus_count * n_queries
    cutoff = per_query * n_queries
    saved = full - cutoff
    return {
        "corpus_count": corpus_count,
        "queries": n_queries,
        "stage1_per_query": per_query,
        "stage1_total": cutoff,
        "full_stage1_total": full,
        "images_saved": saved,
        "reduction_rate": 0.0 if full == 0 else saved / full,
    }


def analyze_ranks(report: dict) -> dict:
    corpus_count = int((report.get("identity") or {}).get("corpus_count") or 0)
    rows = _query_rows(report)
    n_queries = len(rows)
    all_ranks = []
    worst_ranks = []
    for row in rows:
        for name, rank in row["ranks"].items():
            if rank is None:
                continue
            all_ranks.append({
                "query": row["query"],
                "split": row["split"],
                "kind": row["kind"],
                "image": name,
                "rank": rank,
                "is_current_tp": name in row["tp_names"],
            })
        if row["worst_rank"] is not None:
            worst_ranks.append({
                "query": row["query"],
                "split": row["split"],
                "kind": row["kind"],
                "worst_rank": row["worst_rank"],
                "must_n": row["must_n"],
                "best_rank": row["best_rank"],
            })
    bucket_counts = Counter(_bucket_label(item["rank"]) for item in all_ranks)
    k_values = list(FIXED_K)
    if corpus_count and corpus_count not in k_values:
        k_values.append(corpus_count)
    k_values = sorted(set(k_values))
    by_k = {}
    for k in k_values:
        retriever = {
            "all": _retriever_at_k(rows, k),
            "dev": _retriever_at_k([row for row in rows if row["split"] == "dev"], k),
            "holdout": _retriever_at_k(
                [row for row in rows if row["split"] == "holdout"], k
            ),
        }
        e2e = {
            "all": _e2e_at_k(rows, k),
            "dev": _e2e_at_k([row for row in rows if row["split"] == "dev"], k),
            "holdout": _e2e_at_k(
                [row for row in rows if row["split"] == "holdout"], k
            ),
        }
        by_k[str(k)] = {
            "k": k,
            "retriever": retriever,
            "end_to_end": {
                split: {
                    key: value
                    for key, value in payload.items()
                    if key != "lost_tp_all"
                }
                for split, payload in e2e.items()
            },
            "stage1": _send_stats(corpus_count, n_queries, k),
            "lost_current_tp": e2e["all"]["lost_tp_all"],
        }
    current_mrr = {
        "dev": (report.get("retriever") or {}).get("splits", {}).get("dev", {}).get("mrr"),
        "holdout": (report.get("retriever") or {}).get("splits", {}).get("holdout", {}).get("mrr"),
    }
    return {
        "identity": report.get("identity"),
        "corpus_count": corpus_count,
        "n_queries": n_queries,
        "n_must_include_labels": len(all_ranks),
        "n_queries_with_must_include": len(worst_ranks),
        "mrr": current_mrr,
        "must_include_rank_buckets": {
            label: bucket_counts.get(label, 0) for label, _start, _end in RANK_BUCKETS
        },
        "must_include_rank_percentiles": {
            "p50": _percentile([item["rank"] for item in all_ranks], 50),
            "p90": _percentile([item["rank"] for item in all_ranks], 90),
            "p100": _percentile([item["rank"] for item in all_ranks], 100),
        },
        "worst_rank_to_recover_all_must_include": {
            "per_query": worst_ranks,
            "percentiles": {
                "p50": _percentile([item["worst_rank"] for item in worst_ranks], 50),
                "p90": _percentile([item["worst_rank"] for item in worst_ranks], 90),
                "p100": _percentile([item["worst_rank"] for item in worst_ranks], 100),
            },
        },
        "fixed_k": by_k,
        "per_query": [
            {
                "query": row["query"],
                "split": row["split"],
                "kind": row["kind"],
                "must_n": row["must_n"],
                "best_rank": row["best_rank"],
                "worst_rank": row["worst_rank"],
                "retriever_r10": recall_from_ranks(row["ranks"], 10),
                "retriever_r20": recall_from_ranks(row["ranks"], 20),
                "retriever_r40": recall_from_ranks(row["ranks"], 40),
                "retriever_r80": recall_from_ranks(row["ranks"], 80),
                "current_e2e_tp": row["current_tp"],
                "current_e2e_fn": row["current_fn"],
                "current_e2e_recall": row["current_recall"],
                "ranks": row["ranks"],
            }
            for row in rows
        ],
    }


def analyze_scores(
    report: dict,
    folder: Path,
    rank_rows: list[dict],
) -> dict:
    dataset = load_dataset()
    by_query = {spec.query: spec for spec in dataset.queries}
    paths = list_images(folder)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    names = []
    vectors = []
    failed = []
    for path in paths:
        try:
            vectors.append(runtime.embed_image(path))
            names.append(path.name)
        except Exception:
            failed.append(path.name)
    query_rankings = {}
    relative_worst = []
    score_rows = []
    for row in rank_rows:
        spec = by_query.get(row["query"])
        if spec is None:
            continue
        query_vector = encode_query(runtime, spec.query, QUERY_EMBEDDING_RAW)
        ranked = rank_with_scores(query_vector, names, vectors)
        query_rankings[spec.query] = ranked
        scores = [score for _name, score in ranked]
        top = scores[0] if scores else None
        must_scores = []
        for name, rank in row["ranks"].items():
            score = None
            for ranked_name, ranked_score in ranked:
                if ranked_name == name:
                    score = ranked_score
                    break
            if score is None or top in (None, 0):
                rel = None
            else:
                rel = score / top
            must_scores.append({
                "image": name,
                "rank": rank,
                "score": score,
                "score_over_top": rel,
                "is_current_tp": name in set(row.get("tp_names") or []),
            })
        present_rel = [
            item["score_over_top"]
            for item in must_scores
            if item["score_over_top"] is not None
        ]
        worst_rel = min(present_rel) if present_rel else None
        if worst_rel is not None:
            relative_worst.append(worst_rel)
        score_rows.append({
            "query": row["query"],
            "split": row["split"],
            "top_score": top,
            "score_p50": _percentile(scores, 50),
            "score_p10": _percentile(scores, 10),
            "score_min": min(scores) if scores else None,
            "must_include": must_scores,
            "worst_must_include_over_top": worst_rel,
            "worst_rank": row["worst_rank"],
        })
    policies = []
    policy_specs = []
    for min_k in (10, 20, 40):
        for max_k in (40, 80, len(names) or 119):
            if max_k < min_k:
                continue
            for tau in REL_TAUS:
                policy_specs.append((min_k, max_k, tau))
    e2e_rows = _query_rows(report)
    e2e_by_query = {row["query"]: row for row in e2e_rows}
    for min_k, max_k, tau in policy_specs:
        chosen = []
        lost = []
        kept_tp = 0
        total_must = 0
        retriever_recalls = []
        for row in score_rows:
            ranked = query_rankings[row["query"]]
            scores = [score for _name, score in ranked]
            k = dynamic_cutoff_k(scores, min_k=min_k, max_k=max_k, tau=tau)
            chosen.append(k)
            names_k = {name for name, _score in ranked[:k]}
            ranks = {
                item["image"]: item["rank"] for item in row["must_include"]
            }
            retriever_recalls.append(recall_from_ranks(ranks, k))
            e2e_row = e2e_by_query[row["query"]]
            total_must += e2e_row["must_n"]
            for name in e2e_row["tp_names"]:
                if name in names_k:
                    kept_tp += 1
                else:
                    lost.append({
                        "query": row["query"],
                        "image": name,
                        "rank": e2e_row["ranks"].get(name),
                        "k": k,
                    })
        full_stage1 = len(names) * len(score_rows)
        cutoff_stage1 = sum(chosen)
        current_fn = sum(row["current_fn"] for row in e2e_rows)
        micro_fn = total_must - kept_tp
        policies.append({
            "name": f"min{min_k}_rel{tau:.2f}_max{max_k}",
            "min_k": min_k,
            "max_k": max_k,
            "tau": tau,
            "mean_k": _mean([float(value) for value in chosen]),
            "p50_k": _percentile([float(value) for value in chosen], 50),
            "p90_k": _percentile([float(value) for value in chosen], 90),
            "max_chosen_k": max(chosen) if chosen else 0,
            "retriever_macro_recall": _mean(retriever_recalls),
            "e2e_micro_tp": kept_tp,
            "e2e_micro_fn": micro_fn,
            "fn_increase_vs_full_send": micro_fn - current_fn,
            "stage1_total": cutoff_stage1,
            "stage1_reduction_rate": (
                0.0 if full_stage1 == 0 else (full_stage1 - cutoff_stage1) / full_stage1
            ),
            "lost_current_tp_count": len(lost),
            "lost_current_tp_examples": lost[:12],
        })
    policies.sort(key=lambda item: (item["fn_increase_vs_full_send"], -item["stage1_reduction_rate"]))
    return {
        "folder": str(folder),
        "embedded": len(names),
        "embed_failed": failed,
        "worst_must_include_over_top": {
            "p50": _percentile(relative_worst, 50),
            "p90": _percentile(relative_worst, 90),
            "p100": _percentile(relative_worst, 100),
            "min": min(relative_worst) if relative_worst else None,
        },
        "per_query": score_rows,
        "dynamic_policies": policies,
    }


def render_markdown(rank_analysis: dict, score_analysis: dict | None) -> str:
    identity = rank_analysis.get("identity") or {}
    lines = [
        "# Meaning Search candidate cutoff analysis",
        "",
        "Offline analysis. Product search logic was not changed.",
        "",
        f"- corpus images: `{rank_analysis['corpus_count']}`",
        f"- queries: `{rank_analysis['n_queries']}`",
        f"- must_include labels: `{rank_analysis['n_must_include_labels']}`",
        f"- retrieval model: `{identity.get('retrieval_model_id')}`",
        f"- source run: `{identity.get('timestamp')}`",
        "",
        "## must_include OpenCLIP rank distribution",
        "",
        "| bucket | labels |",
        "|---|---:|",
    ]
    for label, _start, _end in RANK_BUCKETS:
        lines.append(
            f"| {label} | {rank_analysis['must_include_rank_buckets'].get(label, 0)} |"
        )
    perc = rank_analysis["must_include_rank_percentiles"]
    worst = rank_analysis["worst_rank_to_recover_all_must_include"]["percentiles"]
    lines.extend([
        "",
        f"All must_include ranks: p50={perc['p50']}, p90={perc['p90']}, max={perc['p100']}.",
        f"Per-query worst rank (needed to recover every must_include): "
        f"p50={worst['p50']}, p90={worst['p90']}, max={worst['p100']}.",
        "",
        "### Per-query worst rank",
        "",
        "| query | split | kind | must_n | best | worst | R@10 | R@20 | R@40 | R@80 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rank_analysis["per_query"]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | {row['kind']} | {row['must_n']} | "
            f"{row['best_rank'] if row['best_rank'] is not None else '-'} | "
            f"{row['worst_rank'] if row['worst_rank'] is not None else '-'} | "
            f"{row['retriever_r10']:.3f} | {row['retriever_r20']:.3f} | "
            f"{row['retriever_r40']:.3f} | {row['retriever_r80']:.3f} |"
        )
    lines.extend([
        "",
        "## Fixed Top-K",
        "",
        "| K | Stage1/query | Stage1 reduction | retriever R (all) | "
        "all-must coverage | E2E micro R | lost current TP | extra FN vs full |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for key in sorted(rank_analysis["fixed_k"], key=lambda value: int(value)):
        item = rank_analysis["fixed_k"][key]
        e2e = item["end_to_end"]["all"]
        retriever = item["retriever"]["all"]
        send = item["stage1"]
        lines.append(
            f"| {item['k']} | {send['stage1_per_query']} | "
            f"{send['reduction_rate']:.1%} | {retriever['macro_recall']:.3f} | "
            f"{retriever['all_must_include_coverage']:.3f} | "
            f"{e2e['micro_recall']:.3f} | {e2e['lost_current_tp']} | "
            f"{e2e['fn_increase_vs_full_send']} |"
        )
    lines.extend(["", "Split detail:", ""])
    for split_name in ("dev", "holdout"):
        lines.append(f"### {split_name}")
        lines.append("")
        lines.append(
            "| K | retriever R | all-must coverage | E2E micro R | extra FN |"
        )
        lines.append("|---:|---:|---:|---:|---:|")
        for key in sorted(rank_analysis["fixed_k"], key=lambda value: int(value)):
            item = rank_analysis["fixed_k"][key]
            lines.append(
                f"| {item['k']} | {item['retriever'][split_name]['macro_recall']:.3f} | "
                f"{item['retriever'][split_name]['all_must_include_coverage']:.3f} | "
                f"{item['end_to_end'][split_name]['micro_recall']:.3f} | "
                f"{item['end_to_end'][split_name]['fn_increase_vs_full_send']} |"
            )
        lines.append("")
    if score_analysis is None:
        lines.extend([
            "## Dynamic cutoff",
            "",
            "Similarity scores were not recomputed in this run.",
            "",
        ])
        return "\n".join(lines) + "\n"
    rel = score_analysis["worst_must_include_over_top"]
    lines.extend([
        "## Dynamic cutoff (min-K + score >= top * tau + max-K)",
        "",
        f"Embedded images: `{score_analysis['embedded']}`.",
        "Worst must_include similarity / top-1 similarity: "
        f"min={rel['min']}, p50={rel['p50']}, p90={rel['p90']}, max={rel['p100']}.",
        "",
        "Lower extra FN is better. Absolute similarity thresholds were not used.",
        "",
        "| policy | mean K | Stage1 reduction | retriever R | extra FN | lost current TP |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    shown = score_analysis["dynamic_policies"][:18]
    zero_fn = [
        item for item in score_analysis["dynamic_policies"]
        if item["fn_increase_vs_full_send"] == 0
    ]
    if zero_fn:
        shown = zero_fn[:8] + [
            item for item in score_analysis["dynamic_policies"]
            if item not in zero_fn
        ][:10]
    for item in shown:
        lines.append(
            f"| `{item['name']}` | {item['mean_k']:.1f} | "
            f"{item['stage1_reduction_rate']:.1%} | "
            f"{item['retriever_macro_recall']:.3f} | "
            f"{item['fn_increase_vs_full_send']} | "
            f"{item['lost_current_tp_count']} |"
        )
    lines.extend([
        "",
        "### Queries whose worst must_include is far from top-1",
        "",
        "| query | split | worst rank | worst/top | top score |",
        "|---|---|---:|---:|---:|",
    ])
    far = sorted(
        (
            row for row in score_analysis["per_query"]
            if row["worst_must_include_over_top"] is not None
        ),
        key=lambda item: item["worst_must_include_over_top"],
    )
    for row in far[:12]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | "
            f"{row['worst_rank'] if row['worst_rank'] is not None else '-'} | "
            f"{row['worst_must_include_over_top']:.3f} | "
            f"{row['top_score']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze Vision Stage 1 candidate cutoffs")
    parser.add_argument(
        "--results",
        type=Path,
        default=ROOT / "artifacts" / "meaning-eval" / "latest" / "results.json",
    )
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument(
        "--with-scores",
        action="store_true",
        help="Re-run official OpenCLIP ranking to evaluate dynamic cutoffs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "meaning-eval" / "candidate-cutoff",
    )
    args = parser.parse_args()
    report = json.loads(args.results.read_text(encoding="utf-8"))
    rank_analysis = analyze_ranks(report)
    score_analysis = None
    if args.with_scores:
        print(f"re-ranking {args.folder} with {OPENCLIP_MODEL_KEY}", flush=True)
        score_analysis = analyze_scores(report, args.folder, _query_rows(report))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ranks": rank_analysis, "scores": score_analysis}
    (args.output_dir / "analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = render_markdown(rank_analysis, score_analysis)
    (args.output_dir / "summary.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
