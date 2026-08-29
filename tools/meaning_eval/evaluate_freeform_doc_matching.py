"""PoC evaluation for document-oriented free-form matching.

Eval-only. Reuses existing free-form Index cache and Ground Truth.
Does not change Ask AI / Hybrid / Vision Judge / v4 Index / product DB schema.
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
from tools.meaning_eval.evaluate_index_hybrid import (
    _index_only_row,
    _mean,
    _summarize_method,
)
from tools.meaning_eval.evaluate_semantic_index import DEFAULT_CORPUS_NAMES, _load_name_set
from tools.meaning_eval.freeform_chunking import CHUNK_STRATEGIES, chunk_stats
from tools.meaning_eval.freeform_doc_matching import (
    DOC_MATCH_CONFIGS,
    DocMatchConfig,
    build_chunk_index,
    search_baseline_records,
    search_doc_matching_records,
)
from tools.meaning_eval.freeform_index import (
    FREEFORM_PROMPT_VERSION,
    FREEFORM_SCHEMA_VERSION,
    load_or_index_paths,
    measure_clip_truncation,
    search_document,
)
from tools.meaning_eval.freeform_schema import FREEFORM_SCHEMA_VERSION as _SCHEMA
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.index_only_doc_matching import (
    CAUSE_MATCHING,
    classify_doc_fp,
    classify_doc_fn,
    chrome_db_only_row_doc,
    fn_cause_counts,
    fp_cause_counts,
    render_doc_matching_analysis,
    select_doc_match_policies,
    verdict_from_doc_matching,
)
from tools.meaning_eval.index_only_freeform import fn_cause_counts as baseline_fn_cause_counts
from tools.meaning_eval.index_only_v3 import category_rows, representative_fps
from tools.retriever_eval import encode_query, list_images, load_runtime
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-freeform-doc-matching"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-freeform-v1.json"
PREVIOUS_A_C = RUNS_DIR / "semantic-index-hybrid-phase-e-v3" / "results.json"
PREVIOUS_B_V4 = RUNS_DIR / "semantic-index-v4-only" / "results.json"
PREVIOUS_BASELINE = RUNS_DIR / "semantic-index-freeform-only" / "results.json"
BROAD_UI = (
    "Windows desktop",
    "desktop with application windows",
    "folder selection screen",
    "Windows desktop screenshot",
    "image gallery",
    "image search application",
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
    "image search application",
)


def _config_by_name() -> dict[str, DocMatchConfig]:
    return {config.name: config for config in DOC_MATCH_CONFIGS}


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


def _search_baseline(
    spec,
    *,
    names,
    records,
    query_vector,
    text_vectors,
    corpus_count,
    embedded_set,
) -> dict:
    started = time.perf_counter()
    judged = search_baseline_records(
        spec.query,
        names,
        records,
        query_vector=query_vector,
        text_vectors=text_vectors,
    )
    elapsed = time.perf_counter() - started
    row = _index_only_row(
        spec,
        ranking=names,
        index_judged=judged,
        search_config=None,
        corpus_count=corpus_count,
        embedded_set=embedded_set,
    )
    _attach_local_stats(row, predicted_count=len(judged["predicted"]), latency_s=elapsed)
    row["judgements"] = judged["judgements"]
    row["predicted"] = judged["predicted"]
    return row


def _search_improved(
    spec,
    *,
    names,
    records,
    query_vector,
    chunk_index,
    config,
    corpus_count,
    embedded_set,
) -> dict:
    started = time.perf_counter()
    judged = search_doc_matching_records(
        spec.query,
        names,
        records,
        query_vector=query_vector,
        chunk_index=chunk_index,
        config=config,
    )
    elapsed = time.perf_counter() - started
    row = _index_only_row(
        spec,
        ranking=names,
        index_judged=judged,
        search_config=None,
        corpus_count=corpus_count,
        embedded_set=embedded_set,
    )
    _attach_local_stats(row, predicted_count=len(judged["predicted"]), latency_s=elapsed)
    row["judgements"] = judged["judgements"]
    row["predicted"] = judged["predicted"]
    return row


def _chrome_hits_from_previous(payload: dict) -> int:
    chrome = payload.get("chrome") or {}
    rows = (chrome.get("by_query") or {}).get("Chrome") or []
    if rows:
        return sum(1 for row in rows if row.get("in_result"))
    hit_rate = float(chrome.get("hit_rate") or 0.0)
    return int(round(hit_rate * 12))


def main() -> int:
    parser = argparse.ArgumentParser(description="Free-form document-oriented matching PoC")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--previous-a-c", type=Path, default=PREVIOUS_A_C)
    parser.add_argument("--previous-b-v4", type=Path, default=PREVIOUS_B_V4)
    parser.add_argument("--previous-baseline", type=Path, default=PREVIOUS_BASELINE)
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
    previous_b_v4 = _load_json(args.previous_b_v4)
    previous_baseline = _load_json(args.previous_baseline)

    print(f"loading free-form index cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    if not cache_reused:
        print("WARNING: Index cache was not fully reused; this run may call Vision", flush=True)

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity

    baseline_embed_started = time.perf_counter()
    text_vectors = {}
    for path in paths:
        record = records.get(path.name) or {}
        document = search_document(record) if not record.get("unknown_reason") else ""
        if document:
            text_vectors[path.name] = runtime.embed_text(document)
    baseline_embed_s = time.perf_counter() - baseline_embed_started
    embedded_set = set(text_vectors)

    query_list = [spec.query for spec in selected] + list(CHROME_QUERIES)
    query_vectors = {
        query: encode_query(runtime, query, QUERY_EMBEDDING_RAW)
        for query in dict.fromkeys(query_list)
    }

    configs = _config_by_name()
    unique_strategies = sorted({config.chunk_strategy for config in DOC_MATCH_CONFIGS})
    chunk_indexes: dict[str, dict[str, list[dict]]] = {}
    chunk_build_started = time.perf_counter()
    for strategy in unique_strategies:
        chunk_indexes[strategy] = build_chunk_index(runtime, records, strategy=strategy)
    chunk_build_s = time.perf_counter() - chunk_build_started

    baseline_rows = []
    for spec in selected:
        baseline_rows.append(_search_baseline(
            spec,
            names=names,
            records=records,
            query_vector=query_vectors[spec.query],
            text_vectors=text_vectors,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
        ))

    variant_rows: dict[str, list[dict]] = {}
    for config in DOC_MATCH_CONFIGS:
        rows = []
        chunk_index = chunk_indexes[config.chunk_strategy]
        for spec in selected:
            rows.append(_search_improved(
                spec,
                names=names,
                records=records,
                query_vector=query_vectors[spec.query],
                chunk_index=chunk_index,
                config=config,
                corpus_count=corpus_count,
                embedded_set=embedded_set,
            ))
        variant_rows[config.name] = rows

    a_sent = float((previous_ac.get("methods") or {}).get("A", {}).get("all", {}).get("mean_vision_sent") or corpus_count)
    dev_by_config = {
        name: _summarize_b(_split_rows(rows, "dev"), baseline_sent=0)
        for name, rows in variant_rows.items()
    }
    selection = select_doc_match_policies(dev_by_config)
    primary_name = selection["policies"]["balanced"]["config"]
    primary = configs[primary_name]
    improved_rows = variant_rows[primary_name]
    primary_chunk_index = chunk_indexes[primary.chunk_strategy]

    repeat_mismatch = []
    for spec, first in zip(selected, improved_rows):
        second = _search_improved(
            spec,
            names=names,
            records=records,
            query_vector=query_vectors[spec.query],
            chunk_index=primary_chunk_index,
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

    baseline_all = _summarize_b(baseline_rows, baseline_sent=a_sent)
    baseline_dev = _summarize_b(_split_rows(baseline_rows, "dev"), baseline_sent=a_sent)
    baseline_hold = _summarize_b(_split_rows(baseline_rows, "holdout"), baseline_sent=a_sent)
    improved_all = _summarize_b(improved_rows, baseline_sent=a_sent)
    improved_dev = _summarize_b(_split_rows(improved_rows, "dev"), baseline_sent=a_sent)
    improved_hold = _summarize_b(_split_rows(improved_rows, "holdout"), baseline_sent=a_sent)

    method_a = _method_from_previous(previous_ac, "A")
    method_c = _method_from_previous(previous_ac, "C")
    method_b_v4 = _method_from_previous(previous_b_v4, "B_v4")

    fn_details = []
    fp_details = []
    for spec, row in zip(selected, improved_rows):
        judgements = row.get("judgements") or {}
        for name in row.get("fn_names") or []:
            item = classify_doc_fn(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
                config=primary,
            )
            item["split"] = spec.split
            item["kind"] = spec.kind
            fn_details.append(item)
        for name in row.get("fp_names") or []:
            item = classify_doc_fp(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
            )
            item["split"] = spec.split
            item["kind"] = spec.kind
            fp_details.append(item)
    cause_counts = fn_cause_counts(fn_details)
    fp_counts = fp_cause_counts(fp_details)

    baseline_fn_details = []
    for spec, row in zip(selected, baseline_rows):
        judgements = row.get("judgements") or {}
        for name in row.get("fn_names") or []:
            from tools.meaning_eval.index_only_freeform import classify_freeform_fn
            from tools.meaning_eval.freeform_doc_matching import baseline_search_config
            item = classify_freeform_fn(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
                config=baseline_search_config(),
            )
            item["split"] = spec.split
            item["kind"] = spec.kind
            baseline_fn_details.append(item)
    baseline_cause_counts = baseline_fn_cause_counts(baseline_fn_details)

    chrome = {"by_query": {}}
    for query in CHROME_QUERIES:
        judged = search_doc_matching_records(
            query,
            names,
            records,
            query_vector=query_vectors[query],
            chunk_index=primary_chunk_index,
            config=primary,
        )
        rows = []
        for name in CHROME_VISIBLE:
            rows.append(chrome_db_only_row_doc(
                query=query,
                name=name,
                record=records.get(name) or {},
                judgement=(judged["judgements"] or {}).get(name) or {},
            ))
        chrome["by_query"][query] = rows
    chrome_primary = chrome["by_query"]["Chrome"]
    chrome_hits = sum(1 for row in chrome_primary if row["in_result"])
    chrome["hit_rate"] = chrome_hits / len(chrome_primary) if chrome_primary else 0.0
    baseline_chrome_hits = _chrome_hits_from_previous(previous_baseline)
    chrome_v4_hits = _chrome_hits_from_previous(previous_b_v4)

    baseline_chrome_judged = search_baseline_records(
        "Chrome",
        names,
        records,
        query_vector=query_vectors["Chrome"],
        text_vectors=text_vectors,
    )
    baseline_chrome_rows = [
        chrome_db_only_row_doc(
            query="Chrome",
            name=name,
            record=records.get(name) or {},
            judgement=(baseline_chrome_judged["judgements"] or {}).get(name) or {},
        )
        for name in CHROME_VISIBLE
    ]
    baseline_chrome_hit_count = sum(1 for row in baseline_chrome_rows if row["in_result"])

    published_improved = [_compact_published(row) for row in improved_rows]
    published_baseline = [_compact_published(row) for row in baseline_rows]
    clip = measure_clip_truncation(runtime, {
        path.name: records[path.name] for path in paths if path.name in records
    })
    stats = [chunk_stats(runtime, records, strategy) for strategy in CHUNK_STRATEGIES]
    primary_stats = next(item for item in stats if item["strategy"] == primary.chunk_strategy)

    v4_all = method_b_v4["all"]
    fp_delta_v4 = int(improved_all["micro_fp"]) - int(v4_all["micro_fp"])
    fp_delta_baseline = int(improved_all["micro_fp"]) - int(baseline_all["micro_fp"])
    verdict = verdict_from_doc_matching(
        improved_all=improved_all,
        baseline_all=baseline_all,
        b_v4_all=v4_all,
        a_all=method_a["all"],
        chrome_hit_rate=chrome["hit_rate"],
        stable=bool(stability["identical"]),
        matching_fns=cause_counts[CAUSE_MATCHING],
        baseline_matching_fns=baseline_cause_counts[CAUSE_MATCHING],
        fp_delta_vs_v4=fp_delta_v4,
        fp_delta_vs_baseline=fp_delta_baseline,
    )

    if cause_counts[CAUSE_MATCHING] < baseline_cause_counts[CAUSE_MATCHING] - 10:
        max_risk = (
            "Recall は改善したが、broad UI query の FP と hold-out 安定性が "
            "製品採用前の最後の壁。"
        )
        next_task = (
            "採用候補 matcher を dev で固定し、hold-out と packaged 実機で "
            "broad UI FP を確認する。"
        )
    elif fp_delta_baseline > 80:
        max_risk = "chunk semantic matching が incidental 語を拾い、baseline より FP が増えている。"
        next_task = "background chunk penalty と broad UI gate を dev で再調整する。"
    else:
        max_risk = (
            "document-oriented matching は truncation を回避できるが、"
            "Recall 改善幅がまだ v4 / Hybrid を超えない。"
        )
        next_task = (
            "Recall 改善が大きい chunk 方式を固定し、"
            "製品 DB schema 変更なしで保存可能な chunk index 形式を設計する。"
        )

    baseline_problems = (
        f"- 119 枚中 {clip['truncated_images']} 枚 ({clip['truncation_rate']:.1%}) が "
        f"OpenCLIP {clip['content_token_limit']}-token 制限を超え、全文 embedding が切り詰められる\n"
        f"- baseline free-form (lex_1.00) は macro R {baseline_all['macro_recall']:.3f}、"
        f"matching miss {baseline_cause_counts[CAUSE_MATCHING]}/{baseline_all['micro_fn']} FN\n"
        "- 多語 query は token coverage 100% 必須のため `dark themed application` 等が落ちる\n"
        "- 環境語だけが文書後半にある画像が broad UI query に強く一致する"
    )
    token_avoidance = (
        f"- 各 chunk を {clip['content_token_limit']} token 以下に分割し、chunk ごとに OpenCLIP text embedding\n"
        f"- primary strategy `{primary.chunk_strategy}`: median {primary_stats['chunks_median']:.1f} chunks/image, "
        f"total {primary_stats['total_chunks']} chunks\n"
        "- query は chunk 単位で semantic / lexical 比較し、max / top-k aggregation で image スコア化\n"
        "- opening sentence boost + background chunk penalty で incidental 一致を弱める"
    )
    evaluated_methods = [
        "A. baseline free-form (lex_1.00 full-document)",
        "B. chunked semantic max / top-k mean (sentence / paragraph / overlap_window)",
        "C. lexical + chunked semantic with background/context gates",
    ]
    for config in DOC_MATCH_CONFIGS:
        evaluated_methods.append(
            f"- `{config.name}`: strategy={config.chunk_strategy}, "
            f"agg={config.aggregation}, txt_min={config.txt_min}, "
            f"lex_support={config.lex_support}, bg_penalty={config.background_penalty}"
        )

    corpus = corpus_identity(paths)
    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=FREEFORM_PROMPT_VERSION,
        schema_version=FREEFORM_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = "index-only-freeform-doc-matching"
    run_identity["judge_structure"] = "local_search_document_chunks"
    run_identity["search_config"] = primary.name
    run_identity["chunk_strategy"] = primary.chunk_strategy

    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "methods": {
            "A": method_a,
            "B_v4": method_b_v4,
            "B_freeform_baseline": {
                "band": "index_only_freeform_baseline",
                "search": "lex_1.00",
                "all": baseline_all,
                "dev": baseline_dev,
                "holdout": baseline_hold,
            },
            "B_freeform_improved": {
                "band": "index_only_freeform_doc_matching",
                "search": primary.name,
                "all": improved_all,
                "dev": improved_dev,
                "holdout": improved_hold,
            },
            "C_v3": method_c,
        },
        "matcher": {
            "name": primary.name,
            "chunk_strategy": primary.chunk_strategy,
            "aggregation": primary.aggregation,
            "txt_min": primary.txt_min,
            "lex_support": primary.lex_support,
            "lex_include": primary.lex_include,
            "background_penalty": primary.background_penalty,
            "opening_boost": primary.opening_boost,
        },
        "query_rows": {
            "B_freeform_baseline": published_baseline,
            "B_freeform_improved": published_improved,
        },
        "categories": category_rows(published_improved),
        "focus_queries": [row for row in published_improved if row["query"] in FOCUS_GT],
        "broad_ui": [row for row in published_improved if row["query"] in BROAD_UI],
        "chrome": chrome,
        "chrome_hits": chrome_hits,
        "baseline_chrome_hits": baseline_chrome_hit_count or baseline_chrome_hits,
        "chrome_v4_hits": chrome_v4_hits,
        "fn_details": fn_details,
        "fn_cause_counts": cause_counts,
        "baseline_fn_cause_counts": baseline_cause_counts,
        "fp_details": fp_details,
        "fp_cause_counts": fp_counts,
        "fp_representatives": representative_fps(published_improved),
        "clip_truncation": clip,
        "chunk_stats": stats,
        "selection": selection,
        "variant_dev": {
            name: {
                "macro_precision": payload["macro_precision"],
                "macro_recall": payload["macro_recall"],
                "macro_f1": payload["macro_f1"],
                "micro_fn": payload["micro_fn"],
                "micro_fp": payload["micro_fp"],
            }
            for name, payload in dev_by_config.items()
        },
        "stability": stability,
        "verdict": verdict,
        "baseline_problems": baseline_problems,
        "evaluated_methods": evaluated_methods,
        "token_avoidance": token_avoidance,
        "extra_models": (
            "None required for this PoC. OpenCLIP ViT-B/32 only (~150MB ONNX, "
            "local, MIT-like). No sentence-transformers added."
        ),
        "max_risk": max_risk,
        "next_task": next_task,
        "validation": {
            "holdout_used_for_retune": False,
            "index_cache_reused": cache_reused,
            "prompt_version": FREEFORM_PROMPT_VERSION,
            "schema_version": _SCHEMA,
            "search_uses_document_only": True,
            "search_uses_image_embedding": False,
            "search_uses_vision": False,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "baseline_embed_seconds": round(baseline_embed_s, 3),
            "chunk_index_build_seconds": round(chunk_build_s, 3),
            "baseline_search_latency": round(baseline_all.get("mean_local_latency_seconds") or 0.0, 4),
            "improved_search_latency": round(improved_all.get("mean_local_latency_seconds") or 0.0, 4),
            "primary_total_chunks": primary_stats["total_chunks"],
            "search_usd_per_query": 0.0,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "doc-matching-analysis.md"
    summary_path = args.output_dir / "summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(render_doc_matching_analysis(report), encoding="utf-8")
    summary_path.write_text(
        "\n".join([
            "# Free-form document-oriented matching PoC summary",
            "",
            f"- verdict: {verdict['label']} adopt_doc_matching={verdict['adopt_doc_matching']}",
            f"- matcher: {primary.name} ({primary.chunk_strategy}, {primary.aggregation})",
            f"- baseline macro P/R/F1: {baseline_all['macro_precision']:.3f} / "
            f"{baseline_all['macro_recall']:.3f} / {baseline_all['macro_f1']:.3f}",
            f"- improved macro P/R/F1: {improved_all['macro_precision']:.3f} / "
            f"{improved_all['macro_recall']:.3f} / {improved_all['macro_f1']:.3f}",
            f"- ΔR / ΔP / ΔFN vs baseline: {verdict['recall_vs_baseline']:+.3f} / "
            f"{verdict['precision_vs_baseline']:+.3f} / {verdict['fn_delta_vs_baseline']:+d}",
            f"- matching miss: baseline {baseline_cause_counts[CAUSE_MATCHING]} → "
            f"improved {cause_counts[CAUSE_MATCHING]} "
            f"(Δ {baseline_cause_counts[CAUSE_MATCHING] - cause_counts[CAUSE_MATCHING]})",
            f"- Chrome DB-only: baseline {report['baseline_chrome_hits']}/12 → improved {chrome_hits}/12",
            f"- search latency baseline/improved: "
            f"{report['cost']['baseline_search_latency']:.4f}s / "
            f"{report['cost']['improved_search_latency']:.4f}s",
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
        "adopt_doc_matching": verdict["adopt_doc_matching"],
        "search": primary.name,
        "macro_recall": round(improved_all["macro_recall"], 4),
        "macro_precision": round(improved_all["macro_precision"], 4),
        "baseline_recall": round(baseline_all["macro_recall"], 4),
        "matching_fns": cause_counts[CAUSE_MATCHING],
        "baseline_matching_fns": baseline_cause_counts[CAUSE_MATCHING],
        "chrome_hits": chrome_hits,
        "stable": stability["identical"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
