"""PoC evaluation for free-form matching FP suppression.

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
from tools.meaning_eval.evaluate_freeform_doc_matching import (
    BROAD_UI,
    FOCUS_GT,
    _attach_local_stats,
    _chrome_hits_from_previous,
    _compact_published,
    _load_json,
    _method_from_previous,
    _search_baseline,
    _search_improved,
    _split_rows,
    _summarize_b,
)
from tools.meaning_eval.evaluate_semantic_index import DEFAULT_CORPUS_NAMES, _load_name_set
from tools.meaning_eval.freeform_chunking import chunk_stats
from tools.meaning_eval.freeform_doc_matching import (
    FP_BASELINE_NAME,
    FP_GATE_CONFIGS,
    RECALL_FOCUS_NAME,
    DocMatchConfig,
    build_chunk_index,
    fp_eval_configs,
    search_baseline_records,
    search_doc_matching_records,
)
from tools.meaning_eval.freeform_index import (
    FREEFORM_PROMPT_VERSION,
    FREEFORM_SCHEMA_VERSION,
    load_or_index_paths,
    measure_clip_truncation,
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
)
from tools.meaning_eval.index_only_fp_gate import (
    DEV_GUARD_QUERIES,
    broad_fp_total,
    compare_query_rows,
    query_recall,
    render_fp_gate_analysis,
    select_fp_gate_policies,
    verdict_from_fp_gate,
)
from tools.meaning_eval.index_only_freeform import fn_cause_counts as baseline_fn_cause_counts
from tools.meaning_eval.index_only_v3 import category_rows, representative_fps
from tools.retriever_eval import encode_query, list_images, load_runtime
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-freeform-fp-gate"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-freeform-v1.json"
PREVIOUS_A_C = RUNS_DIR / "semantic-index-hybrid-phase-e-v3" / "results.json"
PREVIOUS_B_V4 = RUNS_DIR / "semantic-index-v4-only" / "results.json"
PREVIOUS_BASELINE = RUNS_DIR / "semantic-index-freeform-only" / "results.json"


def _config_lookup() -> dict[str, DocMatchConfig]:
    return {config.name: config for config in fp_eval_configs()}


def _chrome_hits_for_config(*, names, records, query_vectors, chunk_index, config) -> int:
    judged = search_doc_matching_records(
        "Chrome",
        names,
        records,
        query_vector=query_vectors["Chrome"],
        chunk_index=chunk_index,
        config=config,
    )
    return sum(
        1 for name in CHROME_VISIBLE
        if ((judged["judgements"] or {}).get(name) or {}).get("relevant")
    )


def _chrome_rows(*, query, names, records, query_vectors, chunk_index, config) -> list[dict]:
    judged = search_doc_matching_records(
        query,
        names,
        records,
        query_vector=query_vectors[query],
        chunk_index=chunk_index,
        config=config,
    )
    return [
        chrome_db_only_row_doc(
            query=query,
            name=name,
            record=records.get(name) or {},
            judgement=(judged["judgements"] or {}).get(name) or {},
        )
        for name in CHROME_VISIBLE
    ]


def _index_bytes(chunk_index: dict[str, list[dict]]) -> dict:
    chunks = 0
    vector_bytes = 0
    text_bytes = 0
    for items in chunk_index.values():
        for item in items:
            chunks += 1
            text_bytes += len(str(item.get("text") or ""))
            vector_bytes += len(item.get("vector") or []) * 4
    return {
        "chunks": chunks,
        "vector_bytes": vector_bytes,
        "text_bytes": text_bytes,
        "total_bytes": vector_bytes + text_bytes,
    }


def _matcher_fields(config: DocMatchConfig) -> dict:
    return {
        "name": config.name,
        "chunk_strategy": config.chunk_strategy,
        "aggregation": config.aggregation,
        "txt_min": config.txt_min,
        "lex_support": config.lex_support,
        "lex_include": config.lex_include,
        "background_penalty": config.background_penalty,
        "opening_boost": config.opening_boost,
        "opening_gate": config.opening_gate,
        "min_evidence": config.min_evidence,
        "generic_density_min": config.generic_density_min,
        "generic_txt_boost": config.generic_txt_boost,
        "generic_lex_min": config.generic_lex_min,
        "short_generic_full_coverage": config.short_generic_full_coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Free-form matching FP suppression PoC")
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

    from tools.meaning_eval.freeform_index import search_document
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

    configs = fp_eval_configs()
    unique_strategies = sorted({config.chunk_strategy for config in configs})
    chunk_indexes: dict[str, dict[str, list[dict]]] = {}
    chunk_build_started = time.perf_counter()
    for strategy in unique_strategies:
        print(f"building chunk index strategy={strategy}", flush=True)
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
    for config in configs:
        print(f"searching config={config.name}", flush=True)
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
    configs_by_name = _config_lookup()
    chrome_by_config = {}
    for config in configs:
        chrome_by_config[config.name] = _chrome_hits_for_config(
            names=names,
            records=records,
            query_vectors=query_vectors,
            chunk_index=chunk_indexes[config.chunk_strategy],
            config=config,
        )

    dev_by_config = {}
    broad_fp_dev_by_config = {}
    guard_recall_by_config = {}
    for name, rows in variant_rows.items():
        dev_rows = _split_rows(rows, "dev")
        summary = _summarize_b(dev_rows, baseline_sent=0)
        published = [_compact_published(row) for row in rows]
        dev_by_config[name] = summary
        broad_fp_dev_by_config[name] = broad_fp_total(published, split="dev")
        guard_recall_by_config[name] = {
            query: float(query_recall(published, query) or 0.0)
            for query in DEV_GUARD_QUERIES
        }

    baseline_all = _summarize_b(baseline_rows, baseline_sent=a_sent)
    baseline_dev = _summarize_b(_split_rows(baseline_rows, "dev"), baseline_sent=a_sent)
    baseline_hold = _summarize_b(_split_rows(baseline_rows, "holdout"), baseline_sent=a_sent)
    baseline_published = [_compact_published(row) for row in baseline_rows]
    baseline_guard = {
        query: float(query_recall(baseline_published, query) or 0.0)
        for query in DEV_GUARD_QUERIES
    }
    selection = select_fp_gate_policies(
        dev_by_config=dev_by_config,
        chrome_by_config=chrome_by_config,
        broad_fp_dev_by_config=broad_fp_dev_by_config,
        guard_recall_by_config=guard_recall_by_config,
        baseline_dev=baseline_dev,
        baseline_guard_recall=baseline_guard,
        candidate_names=[config.name for config in FP_GATE_CONFIGS],
    )
    primary_name = selection["selected"]
    primary = configs_by_name[primary_name]
    improved_rows = variant_rows[primary_name]
    primary_chunk_index = chunk_indexes[primary.chunk_strategy]
    recall_rows = variant_rows[RECALL_FOCUS_NAME]
    fp_baseline_rows = variant_rows[FP_BASELINE_NAME]

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

    improved_all = _summarize_b(improved_rows, baseline_sent=a_sent)
    improved_dev = _summarize_b(_split_rows(improved_rows, "dev"), baseline_sent=a_sent)
    improved_hold = _summarize_b(_split_rows(improved_rows, "holdout"), baseline_sent=a_sent)
    recall_all = _summarize_b(recall_rows, baseline_sent=a_sent)
    recall_dev = _summarize_b(_split_rows(recall_rows, "dev"), baseline_sent=a_sent)
    recall_hold = _summarize_b(_split_rows(recall_rows, "holdout"), baseline_sent=a_sent)
    fp_base_all = _summarize_b(fp_baseline_rows, baseline_sent=a_sent)
    fp_base_dev = _summarize_b(_split_rows(fp_baseline_rows, "dev"), baseline_sent=a_sent)
    fp_base_hold = _summarize_b(_split_rows(fp_baseline_rows, "holdout"), baseline_sent=a_sent)

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
        chrome["by_query"][query] = _chrome_rows(
            query=query,
            names=names,
            records=records,
            query_vectors=query_vectors,
            chunk_index=primary_chunk_index,
            config=primary,
        )
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
    baseline_chrome_hit_count = sum(
        1 for name in CHROME_VISIBLE
        if ((baseline_chrome_judged["judgements"] or {}).get(name) or {}).get("relevant")
    )

    published_improved = [_compact_published(row) for row in improved_rows]
    published_recall = [_compact_published(row) for row in recall_rows]
    published_fp_base = [_compact_published(row) for row in fp_baseline_rows]
    v4_query_rows = (previous_b_v4.get("query_rows") or {}).get("B_v4") or []
    clip = measure_clip_truncation(runtime, {
        path.name: records[path.name] for path in paths if path.name in records
    })
    stats = [chunk_stats(runtime, records, strategy) for strategy in unique_strategies]
    primary_stats = next(item for item in stats if item["strategy"] == primary.chunk_strategy)
    index_size = _index_bytes(primary_chunk_index)

    broad_fp_selected = broad_fp_total(published_improved)
    broad_fp_v4 = broad_fp_total(v4_query_rows)
    broad_fp_baseline = broad_fp_total(baseline_published)
    broad_fp_recall = broad_fp_total(published_recall)
    vs_baseline = compare_query_rows(baseline_published, published_improved)
    verdict = verdict_from_fp_gate(
        candidate_all=improved_all,
        baseline_all=baseline_all,
        recall_all=recall_all,
        b_v4_all=method_b_v4["all"],
        chrome_hit_rate=chrome["hit_rate"],
        stable=bool(stability["identical"]),
        matching_fns=cause_counts[CAUSE_MATCHING],
        baseline_matching_fns=baseline_cause_counts[CAUSE_MATCHING],
        broad_fp=broad_fp_selected,
        broad_fp_v4=broad_fp_v4,
        broad_fp_baseline=broad_fp_baseline,
        vision_sent=float(improved_all.get("mean_vision_sent") or 0.0),
    )

    if verdict["label"] == "GO":
        max_risk = "FP gates look usable on this set, but packaged Ask AI still needs a separate product-path check."
        next_task = "製品経路は変えず、packaged 実機で v4 Index の Google Chrome / Chrome 検索を確認する。"
    elif broad_fp_selected > broad_fp_v4 + 30:
        max_risk = "generic UI query の semantic overmatch がまだ残り、broad UI FP が v4 より高い。"
        next_task = "opening-subject / multi-evidence の generic density 規則を dev で再調整する。"
    elif improved_all["macro_recall"] + 1e-12 < baseline_all["macro_recall"] + 0.03:
        max_risk = "FP は減ったが Recall 改善が baseline 対比でまだ小さい。"
        next_task = "product-like 3-token query の Recall を落とさない gate 緩和を dev で試す。"
    else:
        max_risk = "FP 抑制は Recall 寄り matching より Precision が良いが、製品採用条件をまだ満たさない。"
        next_task = "選定 matcher を固定したまま、hold-out の broad UI FP と matching miss を見て次の gate を決める。"

    evaluated_methods = [
        "1. FP抑制baseline `sent_top2_0.22` (re-eval)",
        "2. Opening / primary-context gate (scene-setting prefix を主題にしない)",
        "3. Broad-query stricter semantic threshold (generic UI token density)",
        "4. Multi-evidence requirement (lexical / opening / multi-chunk / phrase)",
        "5. Combinations on sentence top2 and overlap_window recall matcher",
    ]
    for config in configs:
        evaluated_methods.append(
            f"- `{config.name}`: strategy={config.chunk_strategy}, agg={config.aggregation}, "
            f"opening_gate={config.opening_gate}, min_evidence={config.min_evidence}, "
            f"txt_boost={config.generic_txt_boost}, lex_min={config.generic_lex_min}, "
            f"short_full={config.short_generic_full_coverage}"
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
    run_identity["judge_candidate"] = "index-only-freeform-fp-gate"
    run_identity["judge_structure"] = "local_search_document_chunks_fp_gate"
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
            "B_freeform_recall": {
                "band": "index_only_freeform_doc_matching",
                "search": RECALL_FOCUS_NAME,
                "all": recall_all,
                "dev": recall_dev,
                "holdout": recall_hold,
            },
            "B_freeform_fp_baseline": {
                "band": "index_only_freeform_fp_baseline",
                "search": FP_BASELINE_NAME,
                "all": fp_base_all,
                "dev": fp_base_dev,
                "holdout": fp_base_hold,
            },
            "B_freeform_fp_gate": {
                "band": "index_only_freeform_fp_gate",
                "search": primary.name,
                "all": improved_all,
                "dev": improved_dev,
                "holdout": improved_hold,
            },
            "C_v3": method_c,
        },
        "matcher": _matcher_fields(primary),
        "query_rows": {
            "B_freeform_baseline": baseline_published,
            "B_freeform_recall": published_recall,
            "B_freeform_fp_baseline": published_fp_base,
            "B_freeform_fp_gate": published_improved,
        },
        "categories": category_rows(published_improved),
        "focus_queries": [row for row in published_improved if row["query"] in FOCUS_GT],
        "broad_ui": [row for row in published_improved if row["query"] in BROAD_UI],
        "broad_fp_total": broad_fp_selected,
        "broad_fp_v4": broad_fp_v4,
        "broad_fp_baseline": broad_fp_baseline,
        "broad_fp_recall": broad_fp_recall,
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
                "chrome_hits": chrome_by_config[name],
                "broad_fp_dev": broad_fp_dev_by_config[name],
                "guard_recall": guard_recall_by_config[name],
            }
            for name, payload in dev_by_config.items()
        },
        "vs_baseline": vs_baseline,
        "stability": stability,
        "verdict": verdict,
        "evaluated_methods": evaluated_methods,
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
            "product_paths_unchanged": True,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "baseline_embed_seconds": round(baseline_embed_s, 3),
            "chunk_index_build_seconds": round(chunk_build_s, 3),
            "baseline_search_latency": round(baseline_all.get("mean_local_latency_seconds") or 0.0, 4),
            "selected_search_latency": round(improved_all.get("mean_local_latency_seconds") or 0.0, 4),
            "primary_total_chunks": primary_stats["total_chunks"],
            "index_bytes": index_size["total_bytes"],
            "index_vector_bytes": index_size["vector_bytes"],
            "search_usd_per_query": 0.0,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "fp-gate-analysis.md"
    summary_path = args.output_dir / "summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(render_fp_gate_analysis(report), encoding="utf-8")
    summary_path.write_text(
        "\n".join([
            "# Free-form matching FP suppression summary",
            "",
            f"- verdict: {verdict['label']} adopt_fp_gate={verdict['adopt_fp_gate']}",
            f"- matcher: {primary.name} ({primary.chunk_strategy}, {primary.aggregation})",
            f"- baseline macro P/R/F1: {baseline_all['macro_precision']:.3f} / "
            f"{baseline_all['macro_recall']:.3f} / {baseline_all['macro_f1']:.3f}",
            f"- selected macro P/R/F1: {improved_all['macro_precision']:.3f} / "
            f"{improved_all['macro_recall']:.3f} / {improved_all['macro_f1']:.3f}",
            f"- sent_top2 macro P/R/F1: {fp_base_all['macro_precision']:.3f} / "
            f"{fp_base_all['macro_recall']:.3f} / {fp_base_all['macro_f1']:.3f}",
            f"- matching miss: baseline {baseline_cause_counts[CAUSE_MATCHING]} → "
            f"selected {cause_counts[CAUSE_MATCHING]}",
            f"- broad UI FP: selected {broad_fp_selected} / v4 {broad_fp_v4} / "
            f"baseline {broad_fp_baseline} / recall {broad_fp_recall}",
            f"- Chrome DB-only: {chrome_hits}/12",
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
        "adopt_fp_gate": verdict["adopt_fp_gate"],
        "search": primary.name,
        "macro_recall": round(improved_all["macro_recall"], 4),
        "macro_precision": round(improved_all["macro_precision"], 4),
        "macro_f1": round(improved_all["macro_f1"], 4),
        "matching_fns": cause_counts[CAUSE_MATCHING],
        "baseline_matching_fns": baseline_cause_counts[CAUSE_MATCHING],
        "broad_fp": broad_fp_selected,
        "chrome_hits": chrome_hits,
        "stable": stability["identical"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
