"""Eval-only helpers for document-oriented free-form matching analysis."""

from __future__ import annotations

from collections import Counter

from tools.meaning_eval.analyze_index_coverage import CHROME_QUERIES
from tools.meaning_eval.freeform_doc_matching import BROAD_UI_QUERIES, DocMatchConfig
from tools.meaning_eval.freeform_index import search_document
from tools.meaning_eval.hybrid_phase_e import CONDITIONAL_GO, GO, NO_GO, SCHEMA_RISK_QUERIES
from tools.meaning_eval.index_only_freeform import (
    CAUSE_AMBIGUOUS,
    CAUSE_GT_GAP,
    CAUSE_MATCHING,
    CAUSE_MISSING,
    FN_CAUSES,
    RELATED_TERMS,
    _token_forms,
    chrome_in_document,
    document_has_query_tokens,
    document_has_related_terms,
)
from tools.meaning_eval.index_only_v3 import _fmt, _pct

FP_CAUSE_ENVIRONMENT = "environment_background_word"
FP_CAUSE_GENERIC_UI = "generic_ui_word"
FP_CAUSE_SEMANTIC = "semantic_overmatch"
FP_CAUSE_LEXICAL = "lexical_overmatch"

FP_CAUSES = (
    FP_CAUSE_ENVIRONMENT,
    FP_CAUSE_GENERIC_UI,
    FP_CAUSE_SEMANTIC,
    FP_CAUSE_LEXICAL,
)

FOCUS_QUERIES = (
    "Google Chrome",
    "Chrome",
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


def classify_doc_fn(
    *,
    query: str,
    name: str,
    judgement: dict | None,
    record: dict | None,
    config: DocMatchConfig,
) -> dict:
    record = record or {}
    document = search_document(record)
    found, missing, coverage = document_has_query_tokens(record, query)
    related = document_has_related_terms(record, query)
    lex = float((judgement or {}).get("lex") or 0.0)
    txt = float((judgement or {}).get("txt") or 0.0)
    hit = bool((judgement or {}).get("relevant"))
    unknown = bool(record.get("unknown_reason") or (judgement or {}).get("unknown_reason"))
    ambiguous = query in SCHEMA_RISK_QUERIES
    phrase = query.lower().strip() in document.lower() if document else False
    best_chunk = (judgement or {}).get("best_chunk") or {}
    non_bg_lex = float((judgement or {}).get("non_bg_lex") or 0.0)
    non_bg_txt = float((judgement or {}).get("non_bg_txt") or 0.0)

    if unknown:
        cause = CAUSE_MISSING
        subtype = "unknown_index"
    elif hit:
        cause = CAUSE_MATCHING
        subtype = "false_negative_labeling_error"
    elif coverage > 0 or phrase:
        if txt >= config.txt_min or non_bg_txt >= config.txt_min:
            cause = CAUSE_MATCHING
            subtype = "semantic_or_ranking_miss"
        elif lex >= config.lex_support or non_bg_lex >= config.lex_support:
            cause = CAUSE_MATCHING
            subtype = "threshold_miss"
        else:
            cause = CAUSE_MATCHING
            subtype = "query_tokens_present"
    elif related:
        cause = CAUSE_MATCHING
        subtype = "related_terms_present"
    elif ambiguous:
        cause = CAUSE_AMBIGUOUS
        subtype = "schema_risk_query"
    elif txt >= config.txt_min or non_bg_txt >= config.txt_min:
        cause = CAUSE_GT_GAP
        subtype = "embedding_related_without_terms"
    else:
        cause = CAUSE_MISSING
        subtype = "no_query_evidence"

    return {
        "query": query,
        "name": name,
        "cause": cause,
        "subtype": subtype,
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "include_hit": hit,
        "query_tokens": found + missing,
        "token_coverage": round(coverage, 3),
        "tokens_found": found,
        "tokens_missing": missing,
        "related_terms_found": related,
        "schema_risk_query": ambiguous,
        "unknown_reason": record.get("unknown_reason"),
        "document_chars": len(document),
        "document_preview": document[:360],
        "best_chunk": best_chunk,
        "non_bg_lex": round(non_bg_lex, 4),
        "non_bg_txt": round(non_bg_txt, 4),
    }


def classify_doc_fp(
    *,
    query: str,
    name: str,
    judgement: dict | None,
    record: dict | None,
) -> dict:
    record = record or {}
    document = search_document(record).lower()
    lex = float((judgement or {}).get("lex") or 0.0)
    txt = float((judgement or {}).get("txt") or 0.0)
    best_chunk = (judgement or {}).get("best_chunk") or {}
    chunk_text = str(best_chunk.get("text_preview") or "").lower()
    is_background = bool(best_chunk.get("is_background"))
    query_tokens = [token for token in query.lower().split() if token]

    env_markers = ("background", "wallpaper", "taskbar", "incidental", "behind")
    env_hit = any(marker in chunk_text for marker in env_markers) or is_background
    generic_hit = query in BROAD_UI_QUERIES or all(
        token in {"desktop", "windows", "window", "application", "screen", "folder", "gallery", "search", "image", "manager", "screenshot"}
        for token in query_tokens
    )

    if env_hit and generic_hit:
        cause = FP_CAUSE_ENVIRONMENT
        subtype = "background_chunk_match"
    elif generic_hit:
        cause = FP_CAUSE_GENERIC_UI
        subtype = "generic_ui_match"
    elif lex >= 0.67 and txt < 0.24:
        cause = FP_CAUSE_LEXICAL
        subtype = "lexical_only_match"
    elif txt >= 0.24:
        cause = FP_CAUSE_SEMANTIC
        subtype = "semantic_chunk_match"
    else:
        cause = FP_CAUSE_LEXICAL
        subtype = "mixed_match"

    return {
        "query": query,
        "name": name,
        "cause": cause,
        "subtype": subtype,
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "best_chunk": best_chunk,
        "document_preview": document[:280],
    }


def fp_cause_counts(fp_details: list[dict]) -> dict:
    counts = Counter(item["cause"] for item in fp_details)
    return {cause: int(counts.get(cause, 0)) for cause in FP_CAUSES}


def fn_cause_counts(fn_details: list[dict]) -> dict:
    counts = Counter(item["cause"] for item in fn_details)
    return {cause: int(counts.get(cause, 0)) for cause in FN_CAUSES}


def chrome_db_only_row_doc(
    *,
    query: str,
    name: str,
    record: dict,
    judgement: dict,
) -> dict:
    evidence = chrome_in_document(record)
    lex = float(judgement.get("lex") or 0.0)
    txt = float(judgement.get("txt") or 0.0)
    hit = bool(judgement.get("relevant"))
    if record.get("unknown_reason"):
        reason = f"missing_index:{record.get('unknown_reason')}"
    elif hit:
        reason = "include_hit"
    elif evidence["has_product_name"]:
        reason = "recognized_but_matching_miss"
    elif evidence["has_ui_chrome_only"]:
        reason = "ui_chrome_phrase_only"
    else:
        reason = "not_in_document"
    return {
        "query": query,
        "name": name,
        "in_result": hit,
        "index_has_chrome": evidence["has_product_name"],
        "index_ui_chrome_only": evidence["has_ui_chrome_only"],
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "reason": reason,
        "document_preview": search_document(record)[:280],
        "best_chunk": judgement.get("best_chunk"),
    }


def select_doc_match_policies(dev_by_config: dict[str, dict]) -> dict:
    if not dev_by_config:
        raise ValueError("dev_by_config is empty")

    def recall_key(item: tuple[str, dict]) -> tuple:
        name, payload = item
        return (
            payload["macro_recall"],
            -int(payload["micro_fn"]),
            payload["macro_f1"],
            name,
        )

    def balanced_key(item: tuple[str, dict]) -> tuple:
        name, payload = item
        return (
            payload["macro_f1"],
            payload["macro_recall"],
            -int(payload["micro_fp"]),
            name,
        )

    def precision_key(item: tuple[str, dict], floor: float) -> tuple:
        name, payload = item
        meets = payload["macro_recall"] + 1e-12 >= floor
        return (
            int(meets),
            payload["macro_precision"],
            payload["macro_f1"],
            payload["macro_recall"],
            name,
        )

    items = list(dev_by_config.items())
    recall_name = sorted(items, key=recall_key, reverse=True)[0][0]
    balanced_name = sorted(items, key=balanced_key, reverse=True)[0][0]
    recall_floor = dev_by_config[recall_name]["macro_recall"] - 0.10
    precision_name = sorted(
        items, key=lambda item: precision_key(item, recall_floor), reverse=True,
    )[0][0]
    return {
        "selection_split": "dev",
        "holdout_used_for_retune": False,
        "policies": {
            "recall_first": {
                "config": recall_name,
                "dev": _compact_summary(dev_by_config[recall_name]),
            },
            "balanced": {
                "config": balanced_name,
                "dev": _compact_summary(dev_by_config[balanced_name]),
            },
            "precision_first": {
                "config": precision_name,
                "dev": _compact_summary(dev_by_config[precision_name]),
            },
        },
        "notes": (
            "Compared document-oriented matching configs on dev only. "
            "Hold-out was not used to choose thresholds."
        ),
    }


def _compact_summary(payload: dict) -> dict:
    return {
        "macro_precision": payload["macro_precision"],
        "macro_recall": payload["macro_recall"],
        "macro_f1": payload["macro_f1"],
        "micro_tp": payload.get("micro_tp"),
        "micro_fp": payload["micro_fp"],
        "micro_fn": payload["micro_fn"],
        "micro_precision": payload.get("micro_precision"),
        "micro_recall": payload.get("micro_recall"),
        "micro_f1": payload.get("micro_f1"),
    }


def verdict_from_doc_matching(
    *,
    improved_all: dict,
    baseline_all: dict,
    b_v4_all: dict,
    a_all: dict,
    chrome_hit_rate: float,
    stable: bool,
    matching_fns: int,
    baseline_matching_fns: int,
    fp_delta_vs_v4: int,
    fp_delta_vs_baseline: int,
) -> dict:
    recall_vs_baseline = improved_all["macro_recall"] - baseline_all["macro_recall"]
    recall_vs_v4 = improved_all["macro_recall"] - b_v4_all["macro_recall"]
    precision_vs_v4 = improved_all["macro_precision"] - b_v4_all["macro_precision"]
    precision_floor = 0.20
    soup = fp_delta_vs_v4 >= 150 and precision_vs_v4 < -0.05

    if not stable:
        label = NO_GO
        why = "same DB + same query is not deterministic"
        adopt = False
    elif improved_all["macro_precision"] + 1e-12 < precision_floor:
        label = NO_GO
        why = "macro Precision collapsed below a usable floor of 0.20"
        adopt = False
    elif soup:
        label = NO_GO
        why = "document-oriented matching still produces broad UI soup"
        adopt = False
    elif (
        recall_vs_baseline >= 0.05
        and matching_fns <= baseline_matching_fns - 10
        and chrome_hit_rate + 1e-12 >= (12 / 12)
        and fp_delta_vs_baseline <= 80
    ):
        label = GO
        why = (
            "Chunked document matching materially reduces matching misses "
            "without collapsing Chrome recall"
        )
        adopt = True
    elif recall_vs_baseline >= 0.02 and matching_fns < baseline_matching_fns:
        label = CONDITIONAL_GO
        why = (
            "Document-oriented matching improves Recall, but Precision or "
            "broad UI FP still need tuning before product adoption"
        )
        adopt = False
    else:
        label = NO_GO
        why = "Document-oriented matching did not beat the free-form baseline enough"
        adopt = False

    return {
        "label": label,
        "adopt_doc_matching": adopt,
        "why": why,
        "recall_vs_baseline": round(recall_vs_baseline, 4),
        "recall_vs_v4": round(recall_vs_v4, 4),
        "precision_vs_v4": round(precision_vs_v4, 4),
        "precision_vs_baseline": round(
            improved_all["macro_precision"] - baseline_all["macro_precision"], 4
        ),
        "fp_delta_vs_v4": fp_delta_vs_v4,
        "fp_delta_vs_baseline": fp_delta_vs_baseline,
        "fn_delta_vs_baseline": int(improved_all["micro_fn"]) - int(baseline_all["micro_fn"]),
        "matching_fns": matching_fns,
        "baseline_matching_fns": baseline_matching_fns,
        "chrome_hit_rate": round(chrome_hit_rate, 4),
        "stable": stable,
    }


def _method_row(label: str, key: str, payload: dict) -> str:
    return (
        f"| {label} | `{key}` | {_fmt(payload['macro_precision'])} | "
        f"{_fmt(payload['macro_recall'])} | {_fmt(payload['macro_f1'])} | "
        f"{_fmt(payload.get('micro_precision'))} | {_fmt(payload.get('micro_recall'))} | "
        f"{_fmt(payload.get('micro_f1'))} | {payload['micro_tp']} | {payload['micro_fp']} | "
        f"{payload['micro_fn']} | {_fmt(payload.get('mean_vision_sent'), 1)} | "
        f"{_fmt(payload.get('mean_api_requests'), 1)} | "
        f"{_fmt(payload.get('mean_estimated_usd'), 4)} | "
        f"{_fmt(payload.get('mean_local_latency_seconds') or payload.get('mean_estimated_latency_seconds'), 3)} |"
    )


def render_doc_matching_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_v4 = methods["B_v4"]["all"]
    baseline = methods["B_freeform_baseline"]["all"]
    improved = methods["B_freeform_improved"]["all"]
    c_all = methods["C_v3"]["all"]
    verdict = report["verdict"]
    causes = report["fn_cause_counts"]
    fp_causes = report["fp_cause_counts"]
    baseline_causes = report["baseline_fn_cause_counts"]
    lines = [
        "# Free-form document-oriented matching PoC",
        "",
        "製品 Ask AI / Hybrid / Vision Judge / v4 Index / UI は変更していない。",
        "既存 free-form search document を chunk 分割し、document-oriented matching を dev で選定、hold-out は凍結確認のみ。",
        "",
        "## 1. 現行 matching の問題",
        "",
        report.get("baseline_problems") or "",
        "",
        "## 2. 評価した matching 方式",
        "",
    ]
    for item in report.get("evaluated_methods") or []:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 3. 採用候補アルゴリズム",
        "",
        f"- primary matcher: `{report['matcher']['name']}`",
        f"- chunk strategy: `{report['matcher']['chunk_strategy']}`",
        f"- aggregation: `{report['matcher']['aggregation']}`",
        f"- txt_min={report['matcher']['txt_min']} lex_support={report['matcher']['lex_support']} "
        f"lex_include={report['matcher']['lex_include']}",
        f"- background_penalty={report['matcher']['background_penalty']} "
        f"opening_boost={report['matcher']['opening_boost']}",
        "",
        "## 4. chunk 方式",
        "",
    ])
    for stat in report.get("chunk_stats") or []:
        lines.append(
            f"- `{stat['strategy']}`: images={stat['images']} chunks "
            f"min/median/max={stat['chunks_min']}/{stat['chunks_median']:.1f}/{stat['chunks_max']} "
            f"total={stat['total_chunks']}"
        )
    lines.extend([
        "",
        "## 5. OpenCLIP token 制限の回避",
        "",
        report.get("token_avoidance") or "",
        "",
        "## 6. A / v4 / baseline / improved / Hybrid 比較",
        "",
        "| method | source | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN | Vision/query | API req/query | USD/query | latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        _method_row("A Vision Judge", "A", a_all),
        _method_row("B-v4 fixed-schema", "B_v4", b_v4),
        _method_row("B-freeform baseline", "B_freeform_baseline", baseline),
        _method_row("B-freeform improved matching", "B_freeform_improved", improved),
        _method_row("C Hybrid", "C_v3", c_all),
        "",
        f"- selection split: {report['selection']['selection_split']}; hold-out retune: {report['selection']['holdout_used_for_retune']}",
        "",
        "## 7. Precision / Recall / F1",
        "",
        f"- improved all: P {_fmt(improved['macro_precision'])} / R {_fmt(improved['macro_recall'])} / F1 {_fmt(improved['macro_f1'])}",
        f"- baseline all: P {_fmt(baseline['macro_precision'])} / R {_fmt(baseline['macro_recall'])} / F1 {_fmt(baseline['macro_f1'])}",
        f"- improved dev: P {_fmt(methods['B_freeform_improved']['dev']['macro_precision'])} / "
        f"R {_fmt(methods['B_freeform_improved']['dev']['macro_recall'])} / "
        f"F1 {_fmt(methods['B_freeform_improved']['dev']['macro_f1'])}",
        f"- improved hold-out: P {_fmt(methods['B_freeform_improved']['holdout']['macro_precision'])} / "
        f"R {_fmt(methods['B_freeform_improved']['holdout']['macro_recall'])} / "
        f"F1 {_fmt(methods['B_freeform_improved']['holdout']['macro_f1'])}",
        f"- vs baseline: ΔP {verdict['precision_vs_baseline']:+.3f} / ΔR {verdict['recall_vs_baseline']:+.3f} / "
        f"ΔFN {verdict['fn_delta_vs_baseline']:+d}",
        "",
        "## 8. Chrome 12件",
        "",
        f"- DB-only Chrome hits: **{report['chrome_hits']}/12** (baseline {report['baseline_chrome_hits']}/12, v4 {report['chrome_v4_hits']}/12)",
        "",
    ])
    for query in CHROME_QUERIES:
        hits = sum(1 for row in report["chrome"]["by_query"][query] if row["in_result"])
        named = sum(1 for row in report["chrome"]["by_query"][query] if row["index_has_chrome"])
        lines.append(f"- `{query}`: result {hits}/12, named in document {named}/12")
    lines.extend([
        "",
        "## 9. matching miss 59件の削減",
        "",
        f"- baseline matching miss: **{baseline_causes[CAUSE_MATCHING]}**",
        f"- improved matching miss: **{causes[CAUSE_MATCHING]}**",
        f"- reduction: **{baseline_causes[CAUSE_MATCHING] - causes[CAUSE_MATCHING]}**",
        "",
        "## 10. broad UI FP",
        "",
    ])
    for row in report.get("broad_ui") or []:
        lines.append(
            f"- `{row['query']}` ({row['split']}): FP {row['fp']} / TP {row['tp']} / "
            f"P {_fmt(row['precision'])} / predicted {row.get('predicted_count')}"
        )
    lines.extend([
        "",
        "## 11. 新規 FN / FP 原因",
        "",
        "FN:",
        f"- missing_from_document: {causes[CAUSE_MISSING]}",
        f"- present_but_matching_miss: {causes[CAUSE_MATCHING]}",
        f"- query_ambiguous: {causes[CAUSE_AMBIGUOUS]}",
        f"- gt_interpretation_gap: {causes[CAUSE_GT_GAP]}",
        "",
        "FP:",
        f"- environment/background: {fp_causes[FP_CAUSE_ENVIRONMENT]}",
        f"- generic UI: {fp_causes[FP_CAUSE_GENERIC_UI]}",
        f"- semantic overmatch: {fp_causes[FP_CAUSE_SEMANTIC]}",
        f"- lexical overmatch: {fp_causes[FP_CAUSE_LEXICAL]}",
        "",
        "## 12. latency / index size / 生成時間",
        "",
        f"- chunk index build: {report['cost']['chunk_index_build_seconds']:.3f}s",
        f"- baseline embed (full doc): {report['cost']['baseline_embed_seconds']:.3f}s",
        f"- mean search latency/query baseline: {report['cost']['baseline_search_latency']:.4f}s",
        f"- mean search latency/query improved: {report['cost']['improved_search_latency']:.4f}s",
        f"- total chunks (primary strategy): {report['cost']['primary_total_chunks']}",
        f"- search USD/query: ${report['cost']['search_usd_per_query']:.4f}",
        "",
        "## 13. 追加モデル",
        "",
        report.get("extra_models") or "None required. OpenCLIP ViT-B/32 only.",
        "",
        "## 14. DB-only 採用可否",
        "",
        f"- verdict: **{verdict['label']}** adopt_doc_matching={verdict['adopt_doc_matching']}",
        f"- why: {verdict['why']}",
        "",
        "## 15. 最大の残課題",
        "",
        report.get("max_risk") or "",
        "",
        "## 16. 次にやる 1 タスク",
        "",
        report.get("next_task") or "",
        "",
    ])
    return "\n".join(lines)
