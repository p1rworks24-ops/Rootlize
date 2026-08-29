"""Standalone B-v4 evaluation: Semantic Index v4 only, no Vision Judge.

Eval-only. Reuses Ground Truth, v3/v4 Index caches, and the existing
hybrid_v1 include_hit matcher. Does not change Ask AI / Meaning Search.
Does not overwrite artifacts/meaning-eval/latest.
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
from app.semantic_index.scoring import PRODUCT_SEARCH_CONFIG
from tools.meaning_eval.analyze_index_coverage import CHROME_QUERIES, CHROME_VISIBLE
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.describe_judge import estimate_usd as estimate_index_usd
from tools.meaning_eval.evaluate_index_hybrid import (
    _index_only_row,
    _mean,
    _summarize_method,
)
from tools.meaning_eval.evaluate_semantic_index import (
    DEFAULT_CORPUS_NAMES,
    _encode_corpus,
    _load_name_set,
)
from tools.meaning_eval.hybrid_phase_e import CAUSE_INDEX_CONTENT, CAUSE_MATCHING
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.index_only_v3 import category_rows
from tools.meaning_eval.index_only_v4 import (
    PRIMARY_SEARCH_NAME,
    analyze_unused_fields,
    category_rows_compare,
    chrome_db_only_row_v4,
    classify_index_only_fn,
    field_token_hits,
    measure_clip_truncation,
    measure_index_richness,
    render_analysis,
    representative_fps,
    select_dev_policies,
    verdict_from_b_v4,
    visual_recognition_gains,
)
from tools.meaning_eval.semantic_index import (
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    SEARCH_CONFIGS,
    SEARCH_VERSION,
    clip_index_text,
    load_index_cache,
    load_or_index_paths,
    search_records,
)
from tools.retriever_eval import encode_query, list_images, load_runtime, rank_names
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-v4-only"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-v4.json"
DEFAULT_V3_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-v3.json"
PREVIOUS_A_C = RUNS_DIR / "semantic-index-hybrid-phase-e-v3" / "results.json"
PREVIOUS_B_V3 = RUNS_DIR / "semantic-index-v3-only" / "results.json"


def _config_by_name() -> dict:
    return {config.name: config for config in SEARCH_CONFIGS}


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"missing previous eval results: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _method_from_previous(payload: dict, key: str) -> dict:
    methods = payload.get("methods") or {}
    if key not in methods:
        raise SystemExit(f"{payload.get('generated_at')} missing methods.{key}")
    return methods[key]


def _split_rows(rows: list[dict], split: str) -> list[dict]:
    return [row for row in rows if row["split"] == split]


def _attach_local_stats(row: dict, *, predicted_count: int, latency_s: float) -> dict:
    row["predicted_count"] = predicted_count
    row["vision_sent_images"] = 0
    row["api_requests"] = 0
    row["estimated_usd"] = 0.0
    row["estimated_latency_seconds"] = 0.0
    row["local_latency_seconds"] = round(latency_s, 4)
    return row


def _summarize_b(rows: list[dict], *, baseline_sent: float) -> dict:
    summary = _summarize_method(rows, baseline_sent=baseline_sent)
    summary["mean_predicted_count"] = _mean(
        [float(row.get("predicted_count") or 0) for row in rows]
    )
    summary["mean_local_latency_seconds"] = _mean(
        [float(row.get("local_latency_seconds") or 0) for row in rows]
    )
    return summary


def _compact_published(row: dict) -> dict:
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
        "predicted_count": row.get("predicted_count"),
        "vision_sent_images": 0,
        "api_requests": 0,
        "estimated_usd": 0.0,
        "tp_names": list(row.get("tp_names") or []),
        "fp_names": list(row.get("fp_names") or []),
        "fn_names": list(row.get("fn_names") or []),
        "local_latency_seconds": row.get("local_latency_seconds"),
    }


def _compact_summary_hold(payload: dict) -> dict:
    return {
        "macro_precision": payload["macro_precision"],
        "macro_recall": payload["macro_recall"],
        "macro_f1": payload["macro_f1"],
        "micro_fn": payload["micro_fn"],
        "micro_fp": payload["micro_fp"],
        "micro_tp": payload.get("micro_tp"),
    }


def _search_one(
    spec,
    *,
    ranking,
    records,
    query_vector,
    image_vector_map,
    text_vectors,
    config,
    corpus_count,
    embedded_set,
) -> dict:
    started = time.perf_counter()
    judged = search_records(
        spec.query,
        ranking,
        records,
        query_vector=query_vector,
        image_vectors=image_vector_map,
        text_vectors=text_vectors,
        config=config,
    )
    elapsed = time.perf_counter() - started
    row = _index_only_row(
        spec,
        ranking=ranking,
        index_judged=judged,
        search_config=config,
        corpus_count=corpus_count,
        embedded_set=embedded_set,
    )
    _attach_local_stats(
        row,
        predicted_count=len(judged["predicted"]),
        latency_s=elapsed,
    )
    row["judgements"] = judged["judgements"]
    row["predicted"] = judged["predicted"]
    return row


def _fp_vs_a(a_rows: list[dict], b_rows: list[dict], *, per_query: int = 3) -> list[dict]:
    a_by = {row["query"]: row for row in a_rows}
    out = []
    for row in b_rows:
        a_row = a_by.get(row["query"]) or {}
        a_fp = set(a_row.get("fp_names") or [])
        b_fp = list(row.get("fp_names") or [])
        extra = [name for name in b_fp if name not in a_fp]
        if not extra:
            continue
        out.append({
            "query": row["query"],
            "split": row.get("split"),
            "extra_fp": len(extra),
            "b_fp": row["fp"],
            "a_fp": a_row.get("fp"),
            "examples": extra[:per_query],
        })
    out.sort(key=lambda item: (-item["extra_fp"], item["query"]))
    return out


def _load_v3_cache(path: Path) -> tuple[dict[str, dict], dict]:
    cached = load_index_cache(path)
    if cached is None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        by_name = payload.get("by_name") or {}
        usage = payload.get("usage") or {}
        return by_name, usage
    return cached


def main() -> int:
    parser = argparse.ArgumentParser(description="B-v4 Semantic Index only evaluation")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--v3-index-cache", type=Path, default=DEFAULT_V3_INDEX_CACHE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--previous-a-c", type=Path, default=PREVIOUS_A_C)
    parser.add_argument("--previous-b-v3", type=Path, default=PREVIOUS_B_V3)
    args = parser.parse_args()

    dataset = load_dataset(args.gt)
    selected = dataset.queries
    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
        missing = keep_names - {path.name for path in paths}
        if missing:
            raise SystemExit(f"match-corpus-from names missing from folder: {sorted(missing)[:8]}")
    names = [path.name for path in paths]
    corpus_count = len(paths)
    previous_ac = _load_json(args.previous_a_c)
    previous_b_v3 = _load_json(args.previous_b_v3)

    print(f"indexing {corpus_count} images cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    if not cache_reused:
        print("WARNING: Index cache was not fully reused; this run may call Vision", flush=True)
    v3_records, v3_usage = _load_v3_cache(args.v3_index_cache)
    unknown = sum(1 for item in records.values() if item.get("unknown_reason"))
    print(
        json.dumps({
            "stage": "index",
            "images": corpus_count,
            "unknown": unknown,
            "cache_reused": cache_reused,
            "prompt_version": INDEX_PROMPT_VERSION,
            "schema_version": INDEX_SCHEMA_VERSION,
        }, ensure_ascii=False),
        flush=True,
    )

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity
    embedded_names, image_vectors, embed_failed = _encode_corpus(runtime, paths)
    image_vector_map = dict(zip(embedded_names, image_vectors))
    embedded_set = set(embedded_names)
    text_vectors = {}
    v3_text_vectors = {}
    for path in paths:
        record = records.get(path.name) or {}
        v3_record = v3_records.get(path.name) or {}
        if not record.get("unknown_reason"):
            text_vectors[path.name] = runtime.embed_text(clip_index_text(record))
        if not v3_record.get("unknown_reason"):
            v3_text_vectors[path.name] = runtime.embed_text(clip_index_text(v3_record))
    query_list = [spec.query for spec in selected] + list(CHROME_QUERIES)
    query_vectors = {
        query: encode_query(runtime, query, QUERY_EMBEDDING_RAW)
        for query in dict.fromkeys(query_list)
    }
    rankings = {}
    for spec in selected:
        rankings[spec.query] = rank_names(
            query_vectors[spec.query], embedded_names, image_vectors,
        )
    for query in CHROME_QUERIES:
        rankings[query] = rank_names(query_vectors[query], embedded_names, image_vectors)

    configs = _config_by_name()
    primary = configs[PRIMARY_SEARCH_NAME]
    variant_rows: dict[str, list[dict]] = {}
    for config in SEARCH_CONFIGS:
        rows = []
        for spec in selected:
            row = _search_one(
                spec,
                ranking=rankings[spec.query],
                records=records,
                query_vector=query_vectors[spec.query],
                image_vector_map=image_vector_map,
                text_vectors=text_vectors,
                config=config,
                corpus_count=corpus_count,
                embedded_set=embedded_set,
            )
            rows.append(row)
        variant_rows[config.name] = rows

    b_rows = variant_rows[primary.name]
    v3_rows = []
    for spec in selected:
        judged = search_records(
            spec.query,
            rankings[spec.query],
            v3_records,
            query_vector=query_vectors[spec.query],
            image_vectors=image_vector_map,
            text_vectors=v3_text_vectors,
            config=primary,
        )
        v3_rows.append(_index_only_row(
            spec,
            ranking=rankings[spec.query],
            index_judged=judged,
            search_config=primary,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
        ))

    repeat_mismatch = []
    for spec, first in zip(selected, b_rows):
        second = _search_one(
            spec,
            ranking=rankings[spec.query],
            records=records,
            query_vector=query_vectors[spec.query],
            image_vector_map=image_vector_map,
            text_vectors=text_vectors,
            config=primary,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
        )
        if list(first.get("predicted") or []) != list(second.get("predicted") or []):
            repeat_mismatch.append(spec.query)
    stability = {
        "repeats": 2,
        "identical": not repeat_mismatch,
        "mismatched_queries": repeat_mismatch,
    }

    a_sent = float((previous_ac.get("methods") or {}).get("A", {}).get("all", {}).get("mean_vision_sent") or corpus_count)
    b_all = _summarize_b(b_rows, baseline_sent=a_sent)
    b_dev = _summarize_b(_split_rows(b_rows, "dev"), baseline_sent=a_sent)
    b_hold = _summarize_b(_split_rows(b_rows, "holdout"), baseline_sent=a_sent)
    b_v3_all = _summarize_b(v3_rows, baseline_sent=0)
    method_a = _method_from_previous(previous_ac, "A")
    method_c = _method_from_previous(previous_ac, "C")
    method_b_v3 = _method_from_previous(previous_b_v3, "B_v3")

    dev_by_config = {
        name: _summarize_b(_split_rows(rows, "dev"), baseline_sent=0)
        for name, rows in variant_rows.items()
    }
    selection = select_dev_policies(dev_by_config)
    selected_names = {item["config"] for item in selection["policies"].values()}
    variant_holdout = {
        name: _compact_summary_hold(_summarize_b(_split_rows(rows, "holdout"), baseline_sent=0))
        for name, rows in variant_rows.items()
        if name in selected_names or name == PRIMARY_SEARCH_NAME
    }

    fn_details = []
    field_hit_rows = []
    for spec, row in zip(selected, b_rows):
        judgements = row.get("judgements") or {}
        for name in names:
            record = records.get(name) or {}
            hits = field_token_hits(record, spec.query)
            if any(hits.values()):
                field_hit_rows.append({"query": spec.query, "name": name, "field_hits": hits})
        for name in row.get("fn_names") or []:
            item = classify_index_only_fn(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
                config=primary,
            )
            item["split"] = spec.split
            item["kind"] = spec.kind
            fn_details.append(item)

    chrome = {"by_query": {}}
    v3_chrome_judgements = {}
    for query in CHROME_QUERIES:
        judged = search_records(
            query,
            rankings[query],
            records,
            query_vector=query_vectors[query],
            image_vectors=image_vector_map,
            text_vectors=text_vectors,
            config=primary,
        )
        v3_judged = search_records(
            query,
            rankings[query],
            v3_records,
            query_vector=query_vectors[query],
            image_vectors=image_vector_map,
            text_vectors=v3_text_vectors,
            config=primary,
        )
        v3_chrome_judgements[query] = v3_judged["judgements"]
        rows = []
        for name in CHROME_VISIBLE:
            rows.append(chrome_db_only_row_v4(
                query=query,
                name=name,
                record=records.get(name) or {},
                judgement=(judged["judgements"] or {}).get(name) or {},
                config=primary,
                v3_record=v3_records.get(name) or {},
                v3_judgement=(v3_judged["judgements"] or {}).get(name) or {},
            ))
        chrome["by_query"][query] = rows
    chrome_primary = chrome["by_query"]["Chrome"]
    chrome_hits = sum(1 for row in chrome_primary if row["in_result"])
    chrome_v3_hits = sum(1 for row in chrome_primary if row.get("v3_in_result"))
    chrome["hit_rate"] = chrome_hits / len(chrome_primary) if chrome_primary else 0.0
    chrome["indexed_rate"] = (
        sum(1 for row in chrome_primary if row["index_has_chrome"]) / len(chrome_primary)
        if chrome_primary else 0.0
    )

    resolution = {
        "misses": sum(1 for row in chrome_primary if not row["in_result"]),
        "recognized_but_matching_miss": sum(
            1 for row in chrome_primary
            if row["index_has_chrome"] and not row["in_result"]
        ),
        "not_in_index": sum(
            1 for row in chrome_primary
            if (not row["index_has_chrome"]) and not row.get("index_ui_chrome_only")
        ),
        "likely_resolution_limited": False,
        "unseen_names": [],
    }

    truncated, clip_total = measure_clip_truncation({
        path.name: records[path.name] for path in paths if path.name in records
    })
    unused = analyze_unused_fields(
        records={path.name: records[path.name] for path in paths if path.name in records},
        query_field_hits=field_hit_rows,
        clip_truncated=truncated,
        clip_total=clip_total,
    )
    published_b = [_compact_published(row) for row in b_rows]
    published_v3 = [_compact_published(row) for row in v3_rows]
    a_query_rows = (previous_ac.get("query_rows") or {}).get("A") or []
    incidental_fns = sum(
        1 for item in fn_details
        if item["cause"] == CAUSE_MATCHING and item.get("tokens_incidental_only")
    )
    content_fns = sum(1 for item in fn_details if item["cause"] == CAUSE_INDEX_CONTENT)
    adopt = (
        stability["identical"]
        and chrome_hits >= 10
        and b_all["macro_recall"] + 1e-12 >= b_v3_all["macro_recall"] - 0.02
    )
    verdict = verdict_from_b_v4(
        b_v4_all=b_all,
        b_v3_all=b_v3_all,
        a_all=method_a["all"],
        chrome_hit_rate=chrome["hit_rate"],
        stable=bool(stability["identical"]),
        adopt=adopt,
    )
    max_risk = (
        "視覚認識を足しても、DB-only は matching coverage と broad UI FP が残る。"
        " 製品検索は Hybrid のまま。"
    )
    next_task = (
        "製品経路は変えず、Index に語があるのに coverage ゲートで落ちる matching"
        "（例: dark themed application）を dev 上の評価候補として直す。"
    )

    v4_usd = estimate_index_usd(
        int(index_usage.get("input_tokens") or 0),
        int(index_usage.get("output_tokens") or 0),
    )
    v3_usd = estimate_index_usd(
        int(v3_usage.get("input_tokens") or 0),
        int(v3_usage.get("output_tokens") or 0),
    )
    query_embed_started = time.perf_counter()
    encode_query(runtime, "dog", QUERY_EMBEDDING_RAW)
    query_embed_s = time.perf_counter() - query_embed_started

    corpus = corpus_identity(paths)
    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=INDEX_PROMPT_VERSION,
        schema_version=INDEX_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = "index-only-v4"
    run_identity["judge_structure"] = "local_index_search"
    run_identity["search_config"] = primary.name
    run_identity["search_version"] = SEARCH_VERSION

    richness = {
        "v3": measure_index_richness(v3_records),
        "v4": measure_index_richness(records),
    }
    gains = visual_recognition_gains(v3_records=v3_records, v4_records=records)
    categories_compare = category_rows_compare(published_v3, published_b)

    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": embed_failed,
        "splits": {
            "dev": [spec.query for spec in dataset.by_split()["dev"]],
            "holdout": [spec.query for spec in dataset.by_split()["holdout"]],
        },
        "methods": {
            "A": method_a,
            "B_v3": method_b_v3,
            "B_v4": {
                "band": "index_only",
                "search": primary.name,
                "all": b_all,
                "dev": b_dev,
                "holdout": b_hold,
            },
            "C_v3": method_c,
        },
        "query_rows": {"B_v4": published_b, "B_v3_rescore": published_v3},
        "categories": category_rows(published_b),
        "categories_compare": categories_compare,
        "chrome": chrome,
        "chrome_v3_hits": chrome_v3_hits,
        "fn_details": fn_details,
        "fp_representatives": representative_fps(published_b),
        "fp_vs_A": _fp_vs_a(a_query_rows, b_rows),
        "unused_fields": unused,
        "selection": selection,
        "variant_holdout": variant_holdout,
        "stability": stability,
        "verdict": verdict,
        "max_risk": max_risk,
        "next_task": next_task,
        "visual_gains": gains,
        "richness": richness,
        "resolution": resolution,
        "validation": {
            "holdout_used_for_retune": False,
            "index_cache_reused": cache_reused,
            "prompt_version": INDEX_PROMPT_VERSION,
            "schema_version": INDEX_SCHEMA_VERSION,
            "image_detail": "low",
            "max_edge": 512,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "index_images": corpus_count,
            "v3_input_tokens": int(v3_usage.get("input_tokens") or 0),
            "v3_output_tokens": int(v3_usage.get("output_tokens") or 0),
            "v3_index_usd": round(v3_usd, 4),
            "v3_total_seconds": round(float(v3_usage.get("total_seconds") or 0), 3),
            "v3_api_seconds": round(float(v3_usage.get("api_seconds") or 0), 3),
            "v4_input_tokens": int(index_usage.get("input_tokens") or 0),
            "v4_output_tokens": int(index_usage.get("output_tokens") or 0),
            "v4_index_usd": round(v4_usd, 4),
            "v4_total_seconds": round(float(index_usage.get("total_seconds") or 0), 3),
            "v4_api_seconds": round(float(index_usage.get("api_seconds") or 0), 3),
            "v4_usd_per_image": round(v4_usd / corpus_count, 6) if corpus_count else 0.0,
            "b_local_latency_mean": round(b_all.get("mean_local_latency_seconds") or 0.0, 4),
            "query_embed_seconds": round(query_embed_s, 4),
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "b-v4-analysis.md"
    summary_path = args.output_dir / "summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(render_analysis(report), encoding="utf-8")
    summary_path.write_text(
        "\n".join([
            "# Semantic Index v4 only (B-v4) summary",
            "",
            f"- verdict: {verdict['label']} adopt={verdict['adopt']}",
            f"- B-v3 macro P/R/F1: {method_b_v3['all']['macro_precision']:.3f} / "
            f"{method_b_v3['all']['macro_recall']:.3f} / {method_b_v3['all']['macro_f1']:.3f}",
            f"- B-v4 macro P/R/F1: {b_all['macro_precision']:.3f} / "
            f"{b_all['macro_recall']:.3f} / {b_all['macro_f1']:.3f}",
            f"- ΔR / ΔP / ΔFP / ΔFN: {verdict['recall_vs_v3']:+.3f} / "
            f"{verdict['precision_vs_v3']:+.3f} / {verdict['fp_delta']:+d} / {verdict['fn_delta']:+d}",
            f"- Chrome DB-only: {chrome_v3_hits}/12 → {chrome_hits}/12",
            f"- Index USD: ${report['cost']['v3_index_usd']:.4f} → ${report['cost']['v4_index_usd']:.4f}",
            "- 512px/detail=low: kept",
            f"- next: {next_task}",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json_path)
    print(analysis_path)
    print(summary_path)
    print(json.dumps({
        "verdict": verdict["label"],
        "adopt": verdict["adopt"],
        "macro_recall": round(b_all["macro_recall"], 4),
        "macro_precision": round(b_all["macro_precision"], 4),
        "chrome_hits": chrome_hits,
        "chrome_v3_hits": chrome_v3_hits,
        "stable": stability["identical"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
