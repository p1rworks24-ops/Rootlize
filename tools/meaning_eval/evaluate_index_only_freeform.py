"""Standalone B-freeform evaluation: search-document Index only, no Vision Judge.

Eval-only. Reuses Ground Truth and previous A / B-v3 / B-v4 / C summaries.
Does not change Ask AI / Meaning Search / v4 Index / Hybrid / UI.
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
    _load_name_set,
)
from tools.meaning_eval.freeform_index import (
    FREEFORM_SEARCH_CONFIGS,
    PRIMARY_SEARCH_NAME,
    SEARCH_VERSION,
    document_length_stats,
    load_or_index_paths,
    measure_clip_truncation,
    search_document,
    search_freeform_records,
)
from tools.meaning_eval.freeform_schema import (
    FREEFORM_PROMPT,
    FREEFORM_PROMPT_VERSION,
    FREEFORM_SCHEMA_VERSION,
)
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.index_only_freeform import (
    CAUSE_MATCHING,
    CAUSE_MISSING,
    chrome_db_only_row_freeform,
    classify_freeform_fn,
    fn_cause_counts,
    render_analysis,
    sample_documents,
    verdict_from_b_freeform,
)
from tools.meaning_eval.index_only_v3 import category_rows, representative_fps, select_dev_policies
from tools.retriever_eval import encode_query, list_images, load_runtime
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-freeform-only"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-freeform-v1.json"
PREVIOUS_A_C = RUNS_DIR / "semantic-index-hybrid-phase-e-v3" / "results.json"
PREVIOUS_B_V3 = RUNS_DIR / "semantic-index-v3-only" / "results.json"
PREVIOUS_B_V4 = RUNS_DIR / "semantic-index-v4-only" / "results.json"
SAMPLE_NAMES = (
    "A2.png",
    "20260718_163013.png",
    "20260718_205213.png",
    "20260718_202718.png",
    "test1.jpg",
)
FOCUS_GT = (
    "dark themed application",
    "browser window",
    "code editor",
    "screenshot manager application",
    "Windows desktop",
    "dog",
    "cat",
    "people",
    "video game screenshot",
    "sitting",
    "desktop with application windows",
    "folder selection screen",
)
BROAD_UI = (
    "Windows desktop",
    "desktop with application windows",
    "folder selection screen",
    "Windows desktop screenshot",
    "image gallery",
    "image search application",
)


def _config_by_name() -> dict:
    return {config.name: config for config in FREEFORM_SEARCH_CONFIGS}


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
    names,
    records,
    query_vector,
    text_vectors,
    config,
    corpus_count,
    embedded_set,
) -> dict:
    started = time.perf_counter()
    judged = search_freeform_records(
        spec.query,
        names,
        records,
        query_vector=query_vector,
        text_vectors=text_vectors,
        config=config,
    )
    elapsed = time.perf_counter() - started
    row = _index_only_row(
        spec,
        ranking=names,
        index_judged=judged,
        search_config=config,
        corpus_count=corpus_count,
        embedded_set=embedded_set,
    )
    _attach_local_stats(row, predicted_count=len(judged["predicted"]), latency_s=elapsed)
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


def _chrome_hits_from_previous(payload: dict) -> int:
    chrome = payload.get("chrome") or {}
    rows = (chrome.get("by_query") or {}).get("Chrome") or []
    if rows:
        return sum(1 for row in rows if row.get("in_result"))
    hit_rate = float(chrome.get("hit_rate") or 0.0)
    return int(round(hit_rate * 12))


def main() -> int:
    parser = argparse.ArgumentParser(description="B-freeform Semantic Index only evaluation")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--previous-a-c", type=Path, default=PREVIOUS_A_C)
    parser.add_argument("--previous-b-v3", type=Path, default=PREVIOUS_B_V3)
    parser.add_argument("--previous-b-v4", type=Path, default=PREVIOUS_B_V4)
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
    previous_b_v4 = _load_json(args.previous_b_v4)

    print(f"indexing {corpus_count} images cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    if not cache_reused:
        print("WARNING: Index cache was not fully reused; this run may call Vision", flush=True)
    unknown = sum(1 for item in records.values() if item.get("unknown_reason"))
    print(
        json.dumps({
            "stage": "index",
            "images": corpus_count,
            "unknown": unknown,
            "cache_reused": cache_reused,
            "prompt_version": FREEFORM_PROMPT_VERSION,
            "schema_version": FREEFORM_SCHEMA_VERSION,
        }, ensure_ascii=False),
        flush=True,
    )

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity
    text_vectors = {}
    for path in paths:
        record = records.get(path.name) or {}
        document = search_document(record) if not record.get("unknown_reason") else ""
        if document:
            text_vectors[path.name] = runtime.embed_text(document)
    embedded_set = set(text_vectors)
    query_list = [spec.query for spec in selected] + list(CHROME_QUERIES)
    query_vectors = {
        query: encode_query(runtime, query, QUERY_EMBEDDING_RAW)
        for query in dict.fromkeys(query_list)
    }

    configs = _config_by_name()
    variant_rows: dict[str, list[dict]] = {}
    for config in FREEFORM_SEARCH_CONFIGS:
        rows = []
        for spec in selected:
            row = _search_one(
                spec,
                names=names,
                records=records,
                query_vector=query_vectors[spec.query],
                text_vectors=text_vectors,
                config=config,
                corpus_count=corpus_count,
                embedded_set=embedded_set,
            )
            rows.append(row)
        variant_rows[config.name] = rows

    a_sent = float((previous_ac.get("methods") or {}).get("A", {}).get("all", {}).get("mean_vision_sent") or corpus_count)
    dev_by_config = {
        name: _summarize_b(_split_rows(rows, "dev"), baseline_sent=0)
        for name, rows in variant_rows.items()
    }
    selection = select_dev_policies(dev_by_config)
    balanced_name = selection["policies"]["balanced"]["config"]
    primary = configs[balanced_name]
    b_rows = variant_rows[balanced_name]
    hybrid_rows = variant_rows[PRIMARY_SEARCH_NAME]

    repeat_mismatch = []
    for spec, first in zip(selected, b_rows):
        second = _search_one(
            spec,
            names=names,
            records=records,
            query_vector=query_vectors[spec.query],
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

    b_all = _summarize_b(b_rows, baseline_sent=a_sent)
    b_dev = _summarize_b(_split_rows(b_rows, "dev"), baseline_sent=a_sent)
    b_hold = _summarize_b(_split_rows(b_rows, "holdout"), baseline_sent=a_sent)
    hybrid_all = _summarize_b(hybrid_rows, baseline_sent=a_sent)
    method_a = _method_from_previous(previous_ac, "A")
    method_c = _method_from_previous(previous_ac, "C")
    method_b_v3 = _method_from_previous(previous_b_v3, "B_v3")
    method_b_v4 = _method_from_previous(previous_b_v4, "B_v4")

    selected_names = {item["config"] for item in selection["policies"].values()}
    variant_holdout = {
        name: _compact_summary_hold(_summarize_b(_split_rows(rows, "holdout"), baseline_sent=0))
        for name, rows in variant_rows.items()
        if name in selected_names or name in {PRIMARY_SEARCH_NAME, balanced_name}
    }

    fn_details = []
    for spec, row in zip(selected, b_rows):
        judgements = row.get("judgements") or {}
        for name in row.get("fn_names") or []:
            item = classify_freeform_fn(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
                config=primary,
            )
            item["split"] = spec.split
            item["kind"] = spec.kind
            fn_details.append(item)
    cause_counts = fn_cause_counts(fn_details)

    chrome = {"by_query": {}}
    for query in CHROME_QUERIES:
        judged = search_freeform_records(
            query,
            names,
            records,
            query_vector=query_vectors[query],
            text_vectors=text_vectors,
            config=primary,
        )
        rows = []
        for name in CHROME_VISIBLE:
            rows.append(chrome_db_only_row_freeform(
                query=query,
                name=name,
                record=records.get(name) or {},
                judgement=(judged["judgements"] or {}).get(name) or {},
            ))
        chrome["by_query"][query] = rows
    chrome_primary = chrome["by_query"]["Chrome"]
    chrome_hits = sum(1 for row in chrome_primary if row["in_result"])
    chrome["hit_rate"] = chrome_hits / len(chrome_primary) if chrome_primary else 0.0
    chrome["indexed_rate"] = (
        sum(1 for row in chrome_primary if row["index_has_chrome"]) / len(chrome_primary)
        if chrome_primary else 0.0
    )
    chrome_v4_hits = _chrome_hits_from_previous(previous_b_v4)
    chrome_v3_hits = int(previous_b_v4.get("chrome_v3_hits") or 6)

    published_b = [_compact_published(row) for row in b_rows]
    a_query_rows = (previous_ac.get("query_rows") or {}).get("A") or []
    clip = measure_clip_truncation(runtime, {
        path.name: records[path.name] for path in paths if path.name in records
    })
    density = document_length_stats({
        path.name: records[path.name] for path in paths if path.name in records
    })
    samples = sample_documents(
        {path.name: records[path.name] for path in paths if path.name in records},
        SAMPLE_NAMES,
    )

    v4_all = method_b_v4["all"]
    fp_delta = int(b_all["micro_fp"]) - int(v4_all["micro_fp"])
    verdict = verdict_from_b_freeform(
        b_all=b_all,
        b_v4_all=v4_all,
        b_v3_all=method_b_v3["all"],
        a_all=method_a["all"],
        chrome_hit_rate=chrome["hit_rate"],
        stable=bool(stability["identical"]),
        matching_fns=cause_counts[CAUSE_MATCHING],
        missing_fns=cause_counts[CAUSE_MISSING],
        fp_delta_vs_v4=fp_delta,
    )
    if cause_counts[CAUSE_MATCHING] > cause_counts[CAUSE_MISSING]:
        max_risk = (
            "画像は説明できているのに、長い search document の lexical coverage / "
            "OpenCLIP 77-token truncation が拾いきれていない。"
        )
        next_task = (
            "製品経路は変えず、search document 向け matching（token coverage と "
            "CLIP truncation）を dev 上の評価候補として直す。"
        )
    elif fp_delta >= 150 and verdict["precision_vs_v4"] < -0.05:
        max_risk = "情報量を増やした結果、broad UI query が何でも一致する状態になっている。"
        next_task = (
            "製品経路は変えず、free-form の Precision を落とさずに incidental 情報を残す "
            "matching を dev で試す。"
        )
    else:
        max_risk = (
            "DB-only の最大ボトルネックは、固定 schema でも free-form でも、"
            "画像理解そのものより検索 matching と broad query の FP である。"
        )
        next_task = (
            "製品経路は変えず、Index に語があるのに coverage ゲートで落ちる matching"
            "（例: dark themed application）を dev 上の評価候補として直す。"
        )

    pros_cons = (
        "fixed-schema v4 の長所は field ごとの重みと incidental 抑制、短所は AI 出力を "
        "固定枠に押し込むこと。free-form の長所は未知 query 向けの網羅的な自然言語、"
        "短所は OpenCLIP の短い context と「何でも書かれている」ことによる FP。"
    )

    v4_cost = previous_b_v4.get("cost") or {}
    v3_cost = previous_b_v3.get("cost") or {}
    freeform_usd = estimate_index_usd(
        int(index_usage.get("input_tokens") or 0),
        int(index_usage.get("output_tokens") or 0),
    )
    query_embed_started = time.perf_counter()
    encode_query(runtime, "dog", QUERY_EMBEDDING_RAW)
    query_embed_s = time.perf_counter() - query_embed_started
    usd_per_image = (freeform_usd / corpus_count) if corpus_count else 0.0

    corpus = corpus_identity(paths)
    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=FREEFORM_PROMPT_VERSION,
        schema_version=FREEFORM_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = "index-only-freeform"
    run_identity["judge_structure"] = "local_search_document"
    run_identity["search_config"] = primary.name
    run_identity["search_version"] = SEARCH_VERSION

    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": [path.name for path in paths if path.name not in embedded_set],
        "splits": {
            "dev": [spec.query for spec in dataset.by_split()["dev"]],
            "holdout": [spec.query for spec in dataset.by_split()["holdout"]],
        },
        "methods": {
            "A": method_a,
            "B_v3": method_b_v3,
            "B_v4": method_b_v4,
            "B_freeform": {
                "band": "index_only_freeform",
                "search": primary.name,
                "all": b_all,
                "dev": b_dev,
                "holdout": b_hold,
            },
            "B_freeform_hybrid_v1": {
                "band": "index_only_freeform",
                "search": PRIMARY_SEARCH_NAME,
                "all": hybrid_all,
            },
            "C_v3": method_c,
        },
        "query_rows": {"B_freeform": published_b},
        "categories": category_rows(published_b),
        "focus_queries": [row for row in published_b if row["query"] in FOCUS_GT],
        "broad_ui": [row for row in published_b if row["query"] in BROAD_UI],
        "chrome": chrome,
        "chrome_hits": chrome_hits,
        "chrome_v3_hits": chrome_v3_hits,
        "chrome_v4_hits": chrome_v4_hits,
        "fn_details": fn_details,
        "fn_cause_counts": cause_counts,
        "fp_representatives": representative_fps(published_b),
        "fp_vs_A": _fp_vs_a(a_query_rows, b_rows),
        "document_stats": density,
        "document_samples": samples,
        "clip_truncation": clip,
        "selection": selection,
        "variant_holdout": variant_holdout,
        "stability": stability,
        "verdict": verdict,
        "max_risk": max_risk,
        "next_task": next_task,
        "pros_cons": pros_cons,
        "freeform_prompt": FREEFORM_PROMPT,
        "validation": {
            "holdout_used_for_retune": False,
            "index_cache_reused": cache_reused,
            "prompt_version": FREEFORM_PROMPT_VERSION,
            "schema_version": FREEFORM_SCHEMA_VERSION,
            "image_detail": "low",
            "max_edge": 512,
            "search_uses_document_only": True,
            "search_uses_image_embedding": False,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "index_images": corpus_count,
            "v3_input_tokens": int(v3_cost.get("v3_input_tokens") or v3_cost.get("index_input_tokens") or 36260),
            "v3_output_tokens": int(v3_cost.get("v3_output_tokens") or v3_cost.get("index_output_tokens") or 26413),
            "v3_index_usd": round(float(v3_cost.get("v3_index_usd") or v3_cost.get("index_usd") or 0.1461), 4),
            "v4_input_tokens": int(v4_cost.get("v4_input_tokens") or 43619),
            "v4_output_tokens": int(v4_cost.get("v4_output_tokens") or 39121),
            "v4_index_usd": round(float(v4_cost.get("v4_index_usd") or 0.2088), 4),
            "v4_usd_per_image": round(float(v4_cost.get("v4_usd_per_image") or 0.001755), 6),
            "freeform_input_tokens": int(index_usage.get("input_tokens") or 0),
            "freeform_output_tokens": int(index_usage.get("output_tokens") or 0),
            "freeform_index_usd": round(freeform_usd, 4),
            "freeform_total_seconds": round(float(index_usage.get("total_seconds") or 0), 3),
            "freeform_api_seconds": round(float(index_usage.get("api_seconds") or 0), 3),
            "freeform_usd_per_image": round(usd_per_image, 6),
            "search_usd_per_query": 0.0,
            "b_local_latency_mean": round(b_all.get("mean_local_latency_seconds") or 0.0, 4),
            "query_embed_seconds": round(query_embed_s, 4),
            "scale_usd": {
                "1000": round(usd_per_image * 1000, 4),
                "10000": round(usd_per_image * 10000, 4),
                "100000": round(usd_per_image * 100000, 4),
            },
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "b-freeform-analysis.md"
    summary_path = args.output_dir / "summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(render_analysis(report), encoding="utf-8")
    summary_path.write_text(
        "\n".join([
            "# Semantic Index free-form only (B-freeform) summary",
            "",
            f"- verdict: {verdict['label']} adopt_as_index_center={verdict['adopt_as_index_center']}",
            f"- matcher: {primary.name} (dev balanced); hybrid_v1 also scored",
            f"- B-v3 macro P/R/F1: {method_b_v3['all']['macro_precision']:.3f} / "
            f"{method_b_v3['all']['macro_recall']:.3f} / {method_b_v3['all']['macro_f1']:.3f}",
            f"- B-v4 macro P/R/F1: {v4_all['macro_precision']:.3f} / "
            f"{v4_all['macro_recall']:.3f} / {v4_all['macro_f1']:.3f}",
            f"- B-freeform macro P/R/F1: {b_all['macro_precision']:.3f} / "
            f"{b_all['macro_recall']:.3f} / {b_all['macro_f1']:.3f}",
            f"- ΔR / ΔP / ΔFP / ΔFN vs v4: {verdict['recall_vs_v4']:+.3f} / "
            f"{verdict['precision_vs_v4']:+.3f} / {verdict['fp_delta_vs_v4']:+d} / "
            f"{verdict['fn_delta_vs_v4']:+d}",
            f"- Chrome DB-only: v3 {chrome_v3_hits}/12 → v4 {chrome_v4_hits}/12 → freeform {chrome_hits}/12",
            f"- FN causes matching/missing/ambiguous/gt_gap: "
            f"{cause_counts[CAUSE_MATCHING]}/{cause_counts[CAUSE_MISSING]}/"
            f"{report['fn_cause_counts']['query_ambiguous']}/"
            f"{report['fn_cause_counts']['gt_interpretation_gap']}",
            f"- Index USD: v4 ${report['cost']['v4_index_usd']:.4f} → "
            f"freeform ${report['cost']['freeform_index_usd']:.4f}",
            "- 512px/detail=low: kept; search Vision: 0",
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
        "adopt_as_index_center": verdict["adopt_as_index_center"],
        "search": primary.name,
        "macro_recall": round(b_all["macro_recall"], 4),
        "macro_precision": round(b_all["macro_precision"], 4),
        "chrome_hits": chrome_hits,
        "matching_fns": cause_counts[CAUSE_MATCHING],
        "stable": stability["identical"],
        "cache_reused": cache_reused,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
