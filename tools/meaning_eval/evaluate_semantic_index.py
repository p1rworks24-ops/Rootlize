"""Eval-only PoC: query-independent semantic index + local search.

Does not change product Meaning Search. Does not overwrite
artifacts/meaning-eval/latest. Search makes no Vision API calls.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING, QUERY_EMBEDDING_RAW
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.describe_judge import estimate_usd
from tools.meaning_eval.failure import empty_mode_counts
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.metrics import summarize_end_to_end, summarize_retriever
from tools.meaning_eval.report import compare_runs, write_report
from tools.meaning_eval.scoring import end_to_end_row, retriever_row
from tools.meaning_eval.semantic_index import (
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    PRIMARY_SEARCH,
    SEARCH_CONFIGS,
    SEARCH_VERSION,
    clip_index_text,
    dropped_must_include,
    load_or_index_paths,
    measure_index_storage,
    search_records,
)
from tools.retriever_eval import (
    encode_query,
    list_images,
    load_runtime,
    rank_names,
)
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-v3.json"
DEFAULT_COMPARE = ROOT / "artifacts" / "meaning-eval" / "latest" / "results.json"
DEFAULT_CORPUS_NAMES = (
    ROOT / "artifacts" / "meaning-eval" / "runs"
    / "phase-e-describe-text-judge-smoke" / "descriptions.json"
)
KEY_QUERIES = (
    "dog",
    "cat",
    "code editor",
    "empty state",
    "settings screen",
    "Windows desktop screenshot",
    "image search application",
    "browser window",
)


def _load_name_set(path: Path | None) -> set[str] | None:
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {str(name) for name in payload if name}
    if isinstance(payload, dict):
        by_name = payload.get("by_name")
        if isinstance(by_name, dict):
            return set(by_name)
        names = payload.get("names")
        if isinstance(names, list):
            return {str(name) for name in names if name}
    return None


def _encode_corpus(runtime, paths: list[Path]) -> tuple[list[str], list[list[float]], list[str]]:
    names = []
    vectors = []
    failed = []
    for path in paths:
        try:
            vectors.append(runtime.embed_image(path))
            names.append(path.name)
        except Exception:
            failed.append(path.name)
    return names, vectors, failed


def _add_modes(total: dict[str, int], row: dict) -> None:
    for mode, count in row["failure_mode_counts"].items():
        total[mode] = total.get(mode, 0) + int(count)


def _config_by_name() -> dict:
    return {config.name: config for config in SEARCH_CONFIGS}


def _search_split_rows(
    *,
    selected,
    rankings,
    records,
    query_vectors,
    image_vector_map,
    text_vectors,
    embedded_set,
    config,
) -> tuple[list[dict], dict[str, int]]:
    rows = []
    modes = empty_mode_counts()
    for spec in selected:
        judged = search_records(
            spec.query,
            rankings[spec.query],
            records,
            query_vector=query_vectors[spec.query],
            image_vectors=image_vector_map,
            text_vectors=text_vectors,
            config=config,
        )
        row = end_to_end_row(
            spec,
            ranking=rankings[spec.query],
            predicted=judged["predicted"],
            judgements=judged["judgements"],
            cancelled=False,
            failed_names=set(judged["failed_names"]),
            embedded_names=embedded_set,
        )
        _add_modes(modes, row)
        rows.append(row)
    return rows, modes


def _variant_summary(rows: list[dict]) -> dict:
    return {
        "dev": summarize_end_to_end([row for row in rows if row["split"] == "dev"]),
        "holdout": summarize_end_to_end([row for row in rows if row["split"] == "holdout"]),
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
            }
            for row in rows
        ],
    }


def _must_include_drop_rows(selected, baseline: dict | None, poc_rows: list[dict]) -> list[dict]:
    if not baseline:
        return []
    prev = {
        row["query"]: row
        for row in (baseline.get("end_to_end") or {}).get("queries") or []
    }
    poc = {row["query"]: row for row in poc_rows}
    drops = []
    for spec in selected:
        other = prev.get(spec.query)
        current = poc.get(spec.query)
        if other is None or current is None:
            continue
        names = dropped_must_include(
            spec=spec,
            baseline_predicted=other.get("predicted") or [],
            poc_predicted=current.get("predicted") or [],
        )
        drops.append({
            "query": spec.query,
            "split": spec.split,
            "kind": spec.kind,
            "baseline_tp": other.get("tp"),
            "poc_tp": current.get("tp"),
            "baseline_fn": other.get("fn"),
            "poc_fn": current.get("fn"),
            "dropped_must_include": names,
            "dropped_count": len(names),
        })
    drops.sort(key=lambda item: (-item["dropped_count"], item["query"]))
    return drops


def _render_poc_analysis(report: dict) -> str:
    identity = report["identity"]
    e2e = report["end_to_end"]
    storage = report.get("storage") or {}
    cost = report.get("cost") or {}
    drops = report.get("must_include_drops") or []
    variants = report.get("search_variants") or {}
    lines = [
        "# Semantic index PoC",
        "",
        "## Setup",
        "",
        f"- index prompt: `{identity.get('vision_prompt_version')}`",
        f"- index schema: `{identity.get('vision_schema_version')}`",
        f"- search: `{identity.get('judge_candidate')}` / `{report.get('primary_search')}`",
        f"- images indexed: {identity.get('corpus_count')}",
        f"- Vision API at search time: {cost.get('search_vision_requests', 0)}",
        f"- index API reused cache: {cost.get('index_cache_reused')}",
        "",
        "## Storage (no JPEG persistence)",
        "",
        f"- JSON mean: {storage.get('json_bytes_mean')} bytes",
        f"- JSON median: {storage.get('json_bytes_median')} bytes",
        f"- text embedding float32: {storage.get('text_embedding_float32_bytes')} bytes",
        f"- new per image (JSON + text vector): {storage.get('per_image_new_bytes_mean')} bytes",
        f"- with existing OpenCLIP image vector: {storage.get('per_image_total_with_existing_image_embedding')} bytes",
        "",
        "| images | new index | + existing image embedding |",
        "|---:|---:|---:|",
    ]
    scale_new = storage.get("scale_new_bytes") or {}
    scale_all = storage.get("scale_total_with_existing_image_embedding") or {}
    for key in ("1000", "10000", "100000"):
        lines.append(f"| {key} | {scale_new.get(key)} | {scale_all.get(key)} |")
    lines.extend(["", "## Primary search vs product Meaning Search", ""])
    for split_name in ("dev", "holdout"):
        summary = e2e["splits"][split_name]
        lines.append(
            f"- {split_name}: P={summary['macro_precision']:.3f} "
            f"R={summary['macro_recall']:.3f} FN={summary['micro_fn']} "
            f"FP={summary['micro_fp']}"
        )
    lines.extend(["", "### Key queries", ""])
    lines.append("| query | split | P | R | TP | FP | FN |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    by_query = {row["query"]: row for row in e2e["queries"]}
    for name in KEY_QUERIES:
        row = by_query.get(name)
        if row is None:
            continue
        lines.append(
            f"| `{name}` | {row['split']} | {row['precision']:.3f} | "
            f"{row['recall']:.3f} | {row['tp']} | {row['fp']} | {row['fn']} |"
        )
    lines.extend(["", "### must_include dropped vs product baseline", ""])
    dropped_any = [item for item in drops if item["dropped_count"]]
    if not dropped_any:
        lines.append("None.")
    else:
        for item in dropped_any:
            names = ", ".join(f"`{name}`" for name in item["dropped_must_include"])
            lines.append(
                f"- `{item['query']}` ({item['split']}): "
                f"baseline TP {item['baseline_tp']}→{item['poc_tp']}; dropped {names}"
            )
    lines.extend(["", "## Local search variants (same index, no extra Vision)", ""])
    lines.append("| config | dev macro R | dev macro P | dev FN | holdout macro R | holdout FN |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for name, payload in variants.items():
        dev = payload["dev"]
        hold = payload["holdout"]
        mark = " ← primary" if name == report.get("primary_search") else ""
        lines.append(
            f"| `{name}`{mark} | {dev['macro_recall']:.3f} | {dev['macro_precision']:.3f} | "
            f"{dev['micro_fn']} | {hold['macro_recall']:.3f} | {hold['micro_fn']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic-index Meaning Search PoC")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--split", choices=("dev", "holdout", "both"), default="both")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--compare-with", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument(
        "--match-corpus-from",
        type=Path,
        default=DEFAULT_CORPUS_NAMES,
        help="Keep the same image names as a previous 119-image eval cache.",
    )
    parser.add_argument(
        "--search",
        default=PRIMARY_SEARCH,
        choices=tuple(config.name for config in SEARCH_CONFIGS),
    )
    parser.add_argument("--index-only", action="store_true")
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
    output_dir = args.output_dir or (RUNS_DIR / "semantic-index-poc")

    print(f"indexing {len(paths)} images cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    unknown = sum(1 for item in records.values() if item.get("unknown_reason"))
    print(
        json.dumps({
            "stage": "index",
            "images": len(paths),
            "cached_names": len(records),
            "unknown": unknown,
            "cache_reused": cache_reused,
            "request_count": index_usage.get("request_count"),
            "input_tokens": index_usage.get("input_tokens"),
            "output_tokens": index_usage.get("output_tokens"),
            "sent_image_count": index_usage.get("sent_image_count"),
        }, ensure_ascii=False),
        flush=True,
    )
    if args.index_only:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index-usage.json").write_text(
            json.dumps(index_usage, indent=2), encoding="utf-8"
        )
        print(output_dir / "index-usage.json")
        return 0

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

    retriever_rows = []
    rankings = {}
    for spec in selected:
        ranking = rank_names(query_vectors[spec.query], embedded_names, image_vectors)
        rankings[spec.query] = ranking
        retriever_rows.append(retriever_row(spec, ranking))

    configs = _config_by_name()
    primary = configs[args.search]
    embedded_set = set(embedded_names)
    e2e_rows, mode_totals = _search_split_rows(
        selected=selected,
        rankings=rankings,
        records=records,
        query_vectors=query_vectors,
        image_vector_map=image_vector_map,
        text_vectors=text_vectors,
        embedded_set=embedded_set,
        config=primary,
    )
    variants = {}
    for config in SEARCH_CONFIGS:
        rows, _modes = _search_split_rows(
            selected=selected,
            rankings=rankings,
            records=records,
            query_vectors=query_vectors,
            image_vector_map=image_vector_map,
            text_vectors=text_vectors,
            embedded_set=embedded_set,
            config=config,
        )
        variants[config.name] = _variant_summary(rows)
        print(
            json.dumps({
                "variant": config.name,
                "dev_fn": variants[config.name]["dev"]["micro_fn"],
                "dev_fp": variants[config.name]["dev"]["micro_fp"],
                "dev_r": variants[config.name]["dev"]["macro_recall"],
                "holdout_fn": variants[config.name]["holdout"]["micro_fn"],
                "holdout_r": variants[config.name]["holdout"]["macro_recall"],
            }, ensure_ascii=False),
            flush=True,
        )

    splits = dataset.by_split()
    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=INDEX_PROMPT_VERSION,
        schema_version=INDEX_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = SEARCH_VERSION
    run_identity["judge_structure"] = "local_index_search"
    storage = measure_index_storage({
        path.name: records[path.name]
        for path in paths
        if path.name in records
    })
    describe_usd = estimate_usd(
        int(index_usage.get("input_tokens") or 0),
        int(index_usage.get("output_tokens") or 0),
    )
    previous = None
    if args.compare_with.is_file():
        previous = json.loads(args.compare_with.read_text(encoding="utf-8"))
    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": embed_failed,
        "splits": {
            "dev": [spec.query for spec in splits["dev"]],
            "holdout": [spec.query for spec in splits["holdout"]],
        },
        "gt_corrections": list(dataset.gt_corrections),
        "acceptable_policy": dataset.acceptable_policy,
        "primary_search": primary.name,
        "retriever": {
            "splits": {
                "dev": summarize_retriever([row for row in retriever_rows if row["split"] == "dev"]),
                "holdout": summarize_retriever([row for row in retriever_rows if row["split"] == "holdout"]),
            },
            "queries": retriever_rows,
        },
        "end_to_end": {
            "splits": {
                "dev": summarize_end_to_end([row for row in e2e_rows if row["split"] == "dev"]),
                "holdout": summarize_end_to_end([row for row in e2e_rows if row["split"] == "holdout"]),
            },
            "failure_mode_counts": mode_totals,
            "queries": e2e_rows,
        },
        "search_variants": variants,
        "storage": storage,
        "must_include_drops": _must_include_drop_rows(selected, previous, e2e_rows),
        "cost": {
            "candidate": SEARCH_VERSION,
            "structure": "local_index_search",
            "index_cache_reused": cache_reused,
            "search_vision_requests": 0,
            "requests_per_image_judgement": {
                "describe": 1,
                "judge": 0,
                "stage2_sent_images": 0,
                "notes": (
                    "Stage 1 is one shared query-independent semantic index "
                    "per image. Search is local OpenCLIP + stored metadata; "
                    "images are not resent per query."
                ),
            },
            "describe": index_usage,
            "judge": {
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "api_seconds": 0.0,
                "sent_image_count": 0,
            },
            "total": index_usage,
            "this_run": index_usage if not cache_reused else {
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "api_seconds": 0.0,
                "sent_image_count": 0,
            },
            "estimated_usd": {
                "input_per_million": 0.75,
                "output_per_million": 4.50,
                "describe": round(describe_usd, 4),
                "judge": 0.0,
                "total": round(describe_usd, 4),
                "this_run": 0.0 if cache_reused else round(describe_usd, 4),
                "steady_state_cached_descriptions": 0.0,
            },
            "latency_seconds": {
                "describe": 0.0 if cache_reused else index_usage.get("api_seconds"),
                "judge": 0.0,
                "total": 0.0 if cache_reused else index_usage.get("api_seconds"),
            },
            "high_detail_image_count": 0,
            "stage2_sent_image_count": 0,
        },
    }
    report["comparison"] = compare_runs(report, previous)
    report["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json_path, md_path = write_report(output_dir, report)
    analysis_path = output_dir / "poc-analysis.md"
    analysis_path.write_text(_render_poc_analysis(report), encoding="utf-8")
    print(json_path)
    print(md_path)
    print(analysis_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
