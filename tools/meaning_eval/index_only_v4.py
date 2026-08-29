"""Eval-only helpers for Semantic Index v4 DB-only (B-v4) scoring.

Extends B-v3 helpers with identity-aware Chrome analysis and v3/v4
richness comparison. Does not change product search matchers.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from app.semantic_index.schema import (
    CLIP_INDEX_TEXT_LIMIT,
    INDEX_FIELDS,
    clip_index_text,
    searchable_identity_names,
)
from app.semantic_index.scoring import (
    PRODUCT_SEARCH_CONFIG,
    SearchConfig,
    combined_score,
    content_tokens,
    include_hit,
    incidental_text,
    lexical_score,
    lexical_text,
    tokenize,
)
from tools.meaning_eval.analyze_index_coverage import CHROME_QUERIES, CHROME_VISIBLE, _placement
from tools.meaning_eval.hybrid_phase_e import (
    CAUSE_INDEX_CONTENT,
    CAUSE_MATCHING,
    CAUSE_MIXED,
    CAUSE_PROMPT_SCHEMA,
    CAUSE_THRESHOLD,
    CONDITIONAL_GO,
    GO,
    NO_GO,
    SCHEMA_RISK_QUERIES,
)
from tools.meaning_eval.index_only_v3 import (
    PRIMARY_SEARCH_NAME,
    REPORT_CATEGORIES,
    _compact_summary,
    _fmt,
    _pct,
    _token_set,
    analyze_unused_fields,
    category_rows,
    classify_index_only_fn,
    field_token_hits,
    measure_clip_truncation,
    promote_incidental,
    representative_fps,
    scale_costs,
    select_dev_policies,
    would_hit_if_incidental_primary,
)
from tools.meaning_eval.metrics import summarize_end_to_end
from tools.meaning_eval.semantic_index import index_json_bytes

__all__ = [
    "PRIMARY_SEARCH_NAME",
    "REPORT_CATEGORIES",
    "analyze_unused_fields",
    "category_rows",
    "category_rows_compare",
    "chrome_db_only_row_v4",
    "classify_index_only_fn",
    "compare_categories",
    "field_token_hits",
    "measure_clip_truncation",
    "measure_index_richness",
    "render_analysis",
    "representative_fps",
    "scale_costs",
    "select_dev_policies",
    "verdict_from_b_v4",
    "visual_recognition_gains",
]


def _chrome_tokens() -> set[str]:
    tokens: set[str] = set()
    for query in CHROME_QUERIES:
        tokens.update(tokenize(query))
    return tokens


def _identity_matches_chrome(item: dict) -> bool:
    name = str(item.get("name") or "").lower()
    if not name:
        return False
    if "google chrome" in name or name == "chrome":
        return True
    return "chrome" in tokenize(name) and "browser chrome" not in name


def chrome_identities(record: dict) -> list[dict]:
    return [
        item for item in (record.get("identities") or [])
        if isinstance(item, dict) and _identity_matches_chrome(item)
    ]


def best_chrome_identity(record: dict) -> dict | None:
    items = chrome_identities(record)
    if not items:
        return None
    rank = {"high": 0, "likely": 1, "uncertain": 2}
    importance_rank = {"primary": 0, "secondary": 1, "incidental": 2}
    return sorted(
        items,
        key=lambda item: (
            rank.get(str(item.get("confidence") or ""), 9),
            importance_rank.get(str(item.get("importance") or ""), 9),
            str(item.get("name") or ""),
        ),
    )[0]


def chrome_product_evidence_v4(record: dict) -> dict:
    from tools.meaning_eval.index_only_v3 import chrome_product_evidence

    base = chrome_product_evidence(record)
    identity = best_chrome_identity(record)
    if identity and not base["has_product_name"]:
        base = {
            **base,
            "has_product_name": True,
            "product_fields": [*base["product_fields"], "identities"],
        }
    return base


def chrome_db_only_row_v4(
    *,
    query: str,
    name: str,
    record: dict,
    judgement: dict,
    config: SearchConfig = PRODUCT_SEARCH_CONFIG,
    v3_record: dict | None = None,
    v3_judgement: dict | None = None,
) -> dict:
    from tools.meaning_eval.index_only_v3 import chrome_db_only_row

    row = chrome_db_only_row(
        query=query,
        name=name,
        record=record,
        judgement=judgement,
        config=config,
    )
    identity = best_chrome_identity(record)
    row["identities"] = list(record.get("identities") or [])
    row["chrome_identities"] = chrome_identities(record)
    if identity:
        row["identity_name"] = identity.get("name")
        row["identity_kind"] = identity.get("kind")
        row["identity_importance"] = identity.get("importance")
        row["identity_confidence"] = identity.get("confidence")
        row["identity_evidence"] = identity.get("evidence")
    else:
        row["identity_name"] = None
        row["identity_kind"] = None
        row["identity_importance"] = None
        row["identity_confidence"] = None
        row["identity_evidence"] = None
    if v3_judgement is not None:
        row["v3_in_result"] = bool(v3_judgement.get("relevant"))
    else:
        row["v3_in_result"] = None
    if v3_record is not None:
        row["v3_index_has_chrome"] = chrome_product_evidence_v4(v3_record)["has_product_name"]
    else:
        row["v3_index_has_chrome"] = None
    return row


def measure_index_richness(records: dict[str, dict]) -> dict:
    sizes = []
    list_items = []
    identity_counts = []
    concept_counts = []
    clip_chars = []
    kinds: Counter[str] = Counter()
    confidences: Counter[str] = Counter()
    importances: Counter[str] = Counter()
    truncated = 0
    for record in records.values():
        if record.get("unknown_reason"):
            continue
        sizes.append(index_json_bytes(record))
        list_items.append(
            sum(len(record.get(name) or []) for name in INDEX_FIELDS if name != "identities")
        )
        identities = record.get("identities") or []
        identity_counts.append(len(identities))
        concept_counts.append(len(record.get("searchable_concepts") or []))
        text = clip_index_text(record)
        clip_chars.append(len(text))
        if len(text) >= CLIP_INDEX_TEXT_LIMIT:
            truncated += 1
        for item in identities:
            if not isinstance(item, dict):
                continue
            kinds[str(item.get("kind") or "")] += 1
            confidences[str(item.get("confidence") or "")] += 1
            importances[str(item.get("importance") or "")] += 1
    n = len(sizes)
    mean = lambda values: (sum(values) / n) if n else 0.0
    return {
        "images": n,
        "json_bytes_mean": round(mean(sizes), 1),
        "list_items_mean": round(mean(list_items), 2),
        "identities_mean": round(mean(identity_counts), 2),
        "searchable_concepts_mean": round(mean(concept_counts), 2),
        "clip_chars_mean": round(mean(clip_chars), 1),
        "clip_truncated": truncated,
        "identity_kinds": dict(kinds),
        "identity_confidences": dict(confidences),
        "identity_importances": dict(importances),
    }


def _named_terms(record: dict) -> set[str]:
    terms: set[str] = set()
    for name in searchable_identity_names(record):
        terms.add(name.lower())
    for field in ("objects_entities", "searchable_concepts"):
        for item in record.get(field) or []:
            text = str(item).strip().lower()
            if text:
                terms.add(text)
    return terms


def visual_recognition_gains(
    *,
    v3_records: dict[str, dict],
    v4_records: dict[str, dict],
    limit: int = 12,
) -> dict:
    with_identities = 0
    added_images = 0
    added_terms_total = 0
    examples = []
    for name, v4_record in v4_records.items():
        if v4_record.get("unknown_reason"):
            continue
        if v4_record.get("identities"):
            with_identities += 1
        v3_record = v3_records.get(name) or {}
        if v3_record.get("unknown_reason"):
            v3_terms: set[str] = set()
        else:
            v3_terms = _named_terms(v3_record)
        v4_terms = _named_terms(v4_record)
        added = sorted(v4_terms - v3_terms)
        if added:
            added_images += 1
            added_terms_total += len(added)
            if len(examples) < limit:
                examples.append({"name": name, "added_terms": added[:8]})
    return {
        "images_with_identities": with_identities,
        "images_total": len(v4_records),
        "images_with_added_terms": added_images,
        "added_terms_total": added_terms_total,
        "examples": examples,
    }


def compare_categories(v3_rows: list[dict], v4_rows: list[dict]) -> list[dict]:
    v3_by = {row["key"]: row for row in category_rows(v3_rows)}
    v4_by = {row["key"]: row for row in category_rows(v4_rows)}
    out = []
    for key, label, _queries in REPORT_CATEGORIES:
        v3 = v3_by.get(key) or {}
        v4 = v4_by.get(key) or {}
        out.append({
            "key": key,
            "label": label,
            "v3_recall": v3.get("macro_recall"),
            "v4_recall": v4.get("macro_recall"),
            "delta_recall": (v4.get("macro_recall") or 0) - (v3.get("macro_recall") or 0),
            "v3_precision": v3.get("macro_precision"),
            "v4_precision": v4.get("macro_precision"),
            "delta_precision": (v4.get("macro_precision") or 0) - (v3.get("macro_precision") or 0),
            "v3_fn": v3.get("micro_fn"),
            "v4_fn": v4.get("micro_fn"),
            "v3_fp": v3.get("micro_fp"),
            "v4_fp": v4.get("micro_fp"),
        })
    return out


def category_rows_compare(v3_rows: list[dict], v4_rows: list[dict]) -> list[dict]:
    return compare_categories(v3_rows, v4_rows)


def verdict_from_b_v4(
    *,
    b_v4_all: dict,
    b_v3_all: dict,
    a_all: dict,
    chrome_hit_rate: float,
    stable: bool,
    adopt: bool,
) -> dict:
    recall_vs_v3 = b_v4_all["macro_recall"] - b_v3_all["macro_recall"]
    precision_vs_v3 = b_v4_all["macro_precision"] - b_v3_all["macro_precision"]
    fp_delta = int(b_v4_all["micro_fp"]) - int(b_v3_all["micro_fp"])
    fn_delta = int(b_v4_all["micro_fn"]) - int(b_v3_all["micro_fn"])
    if not stable:
        label = NO_GO
        why = "same DB + same query is not deterministic"
    elif adopt:
        label = "GO_INDEX_V4"
        why = (
            "Visual-identity Index improves searchable coverage. Product Ask AI "
            "stays on Hybrid; this adopts the new Index generation only."
        )
    elif b_v4_all["macro_recall"] + 1e-12 >= b_v3_all["macro_recall"] - 0.02:
        label = CONDITIONAL_GO
        why = (
            "Recall is competitive with v3, but Precision cost or Chrome coverage "
            "is not enough for unconditional adoption."
        )
    else:
        label = NO_GO
        why = "Recall regressed vs v3 without enough Chrome or coverage gain."
    return {
        "adopt": adopt,
        "label": label,
        "why": why,
        "recall_vs_v3": round(recall_vs_v3, 4),
        "precision_vs_v3": round(precision_vs_v3, 4),
        "fp_delta": fp_delta,
        "fn_delta": fn_delta,
        "recall_vs_A": round(b_v4_all["macro_recall"] - a_all["macro_recall"], 4),
        "precision_vs_A": round(b_v4_all["macro_precision"] - a_all["macro_precision"], 4),
        "chrome_hit_rate": round(chrome_hit_rate, 4),
        "stable": stable,
    }


def render_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_v3 = methods["B_v3"]["all"]
    b_v4 = methods["B_v4"]["all"]
    b_dev = methods["B_v4"]["dev"]
    b_hold = methods["B_v4"]["holdout"]
    chrome = report["chrome"]
    richness = report["richness"]
    gains = report["visual_gains"]
    verdict = report["verdict"]
    cost = report["cost"]
    lines = [
        "# Semantic Index v4 only (B-v4)",
        "",
        "製品 Ask AI / Meaning Search / Hybrid threshold / Vision Judge / UI / Credits は変更していない。",
        "B-v4 は新規 `semantic-index-v4` / `image-semantic-index-v3` と既存 local matcher（`hybrid_v1` include_hit）だけ。",
        "検索時の画像 Vision 送信は 0。512px / detail=low のまま生成した。",
        "",
        "## 1. Before / after（v3 → v4）",
        "",
        "| method | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| A Vision Judge | {_fmt(a_all['macro_precision'])} | {_fmt(a_all['macro_recall'])} | "
        f"{_fmt(a_all['macro_f1'])} | {_fmt(a_all.get('micro_precision'))} | "
        f"{_fmt(a_all.get('micro_recall'))} | {_fmt(a_all.get('micro_f1'))} | "
        f"{a_all['micro_tp']} | {a_all['micro_fp']} | {a_all['micro_fn']} |",
        f"| B-v3 Index only | {_fmt(b_v3['macro_precision'])} | {_fmt(b_v3['macro_recall'])} | "
        f"{_fmt(b_v3['macro_f1'])} | {_fmt(b_v3.get('micro_precision'))} | "
        f"{_fmt(b_v3.get('micro_recall'))} | {_fmt(b_v3.get('micro_f1'))} | "
        f"{b_v3['micro_tp']} | {b_v3['micro_fp']} | {b_v3['micro_fn']} |",
        f"| B-v4 Index only | {_fmt(b_v4['macro_precision'])} | {_fmt(b_v4['macro_recall'])} | "
        f"{_fmt(b_v4['macro_f1'])} | {_fmt(b_v4.get('micro_precision'))} | "
        f"{_fmt(b_v4.get('micro_recall'))} | {_fmt(b_v4.get('micro_f1'))} | "
        f"{b_v4['micro_tp']} | {b_v4['micro_fp']} | {b_v4['micro_fn']} |",
        "",
        f"- macro Recall v3→v4: {_fmt(b_v3['macro_recall'])} → {_fmt(b_v4['macro_recall'])} "
        f"({verdict['recall_vs_v3']:+.3f})",
        f"- macro Precision v3→v4: {_fmt(b_v3['macro_precision'])} → {_fmt(b_v4['macro_precision'])} "
        f"({verdict['precision_vs_v3']:+.3f})",
        f"- FP v3→v4: {b_v3['micro_fp']} → {b_v4['micro_fp']} ({verdict['fp_delta']:+d})",
        f"- FN v3→v4: {b_v3['micro_fn']} → {b_v4['micro_fn']} ({verdict['fn_delta']:+d})",
        "",
        "Dev / hold-out（B-v4、hold-out は確認のみ）:",
        "",
        f"- dev: P={_fmt(b_dev['macro_precision'])} R={_fmt(b_dev['macro_recall'])} "
        f"F1={_fmt(b_dev['macro_f1'])} FN={b_dev['micro_fn']} FP={b_dev['micro_fp']}",
        f"- hold-out: P={_fmt(b_hold['macro_precision'])} R={_fmt(b_hold['macro_recall'])} "
        f"F1={_fmt(b_hold['macro_f1'])} FN={b_hold['micro_fn']} FP={b_hold['micro_fp']}",
        "",
        "## 2. Query 別（B-v4）",
        "",
        "| query | split | kind | P | R | F1 | TP | FP | FN | hits |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["query_rows"]["B_v4"]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | {row.get('kind', '')} | "
            f"{_fmt(row['precision'])} | {_fmt(row['recall'])} | {_fmt(row['f1'])} | "
            f"{row['tp']} | {row['fp']} | {row['fn']} | {row.get('predicted_count')} |"
        )
    lines.extend(["", "## 3. カテゴリ別 v3 → v4", ""])
    lines.append("| category | v3 R | v4 R | ΔR | v3 P | v4 P | ΔP | v3 FN | v4 FN | v3 FP | v4 FP |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in report["categories_compare"]:
        lines.append(
            f"| {item['label']} | {_fmt(item['v3_recall'])} | {_fmt(item['v4_recall'])} | "
            f"{item['delta_recall']:+.3f} | {_fmt(item['v3_precision'])} | {_fmt(item['v4_precision'])} | "
            f"{item['delta_precision']:+.3f} | {item['v3_fn']} | {item['v4_fn']} | "
            f"{item['v3_fp']} | {item['v4_fp']} |"
        )
    lines.extend([
        "",
        "## 4. Chrome 12 件 before / after",
        "",
        f"- v3 DB-only `Chrome`: {report.get('chrome_v3_hits', 0)}/12",
        f"- v4 DB-only `Chrome`: {sum(1 for row in chrome['by_query']['Chrome'] if row['in_result'])}/12",
        "",
    ])
    for query in CHROME_QUERIES:
        rows = chrome["by_query"][query]
        hits = sum(1 for row in rows if row["in_result"])
        indexed = sum(1 for row in rows if row["index_has_chrome"])
        lines.extend([
            f"### `{query}`: result {hits}/12, product name {indexed}/12",
            "",
            "| image | AI name | evidence | importance | confidence | stored | v3 hit | v4 hit | miss |",
            "|---|---|---|---|---|---|---|---|---|",
        ])
        for row in rows:
            lines.append(
                f"| `{row['name']}` | {row.get('identity_name') or 'no'} | "
                f"{row.get('identity_evidence') or ''} | {row.get('identity_importance') or ''} | "
                f"{row.get('identity_confidence') or ''} | {row.get('index_has_chrome')} | "
                f"{row.get('v3_in_result')} | {row['in_result']} | {row.get('reason_if_miss') or ''} |"
            )
        lines.append("")
    lines.extend([
        "## 5. 視覚認識で増えた情報",
        "",
        f"- identities がある画像: {gains['images_with_identities']}/{gains['images_total']}",
        f"- v3 に無く v4 で増えた固有名がある画像: {gains['images_with_added_terms']}",
        f"- 追加固有名の延べ数: {gains['added_terms_total']}",
        f"- identity kinds: {richness['v4'].get('identity_kinds')}",
        f"- identity confidence: {richness['v4'].get('identity_confidences')}",
        f"- identity importance: {richness['v4'].get('identity_importances')}",
        "",
        "例:",
        "",
    ])
    for item in gains.get("examples") or []:
        terms = ", ".join(f"`{term}`" for term in item.get("added_terms") or [])
        lines.append(f"- `{item['name']}`: {terms}")
    lines.extend([
        "",
        "## 6. Index 情報量 / コスト / latency",
        "",
        "| | v3 | v4 |",
        "|---|---:|---:|",
        f"| JSON bytes mean | {richness['v3']['json_bytes_mean']} | {richness['v4']['json_bytes_mean']} |",
        f"| list items mean | {richness['v3']['list_items_mean']} | {richness['v4']['list_items_mean']} |",
        f"| identities mean | {richness['v3']['identities_mean']} | {richness['v4']['identities_mean']} |",
        f"| searchable_concepts mean | {richness['v3']['searchable_concepts_mean']} | {richness['v4']['searchable_concepts_mean']} |",
        f"| clip chars mean | {richness['v3']['clip_chars_mean']} | {richness['v4']['clip_chars_mean']} |",
        f"| clip truncated | {richness['v3']['clip_truncated']} | {richness['v4']['clip_truncated']} |",
        f"| input tokens | {cost.get('v3_input_tokens')} | {cost.get('v4_input_tokens')} |",
        f"| output tokens | {cost.get('v3_output_tokens')} | {cost.get('v4_output_tokens')} |",
        f"| Index USD | {cost.get('v3_index_usd')} | {cost.get('v4_index_usd')} |",
        f"| Index seconds (wall) | {cost.get('v3_total_seconds')} | {cost.get('v4_total_seconds')} |",
        f"| Index seconds (api sum) | {cost.get('v3_api_seconds')} | {cost.get('v4_api_seconds')} |",
        "",
        f"- 512px / detail=low のまま。cache_reused={cost.get('index_cache_reused')}",
        "",
        "## 7. 512px / detail=low がボトルネックか",
        "",
        f"- Chrome misses: {report['resolution']['misses']}",
        f"- Index に製品名があるのに matching miss: {report['resolution']['recognized_but_matching_miss']}",
        f"- Index に製品名が無い miss: {report['resolution']['not_in_index']}",
        f"- resolution-limited の可能性: {report['resolution']['likely_resolution_limited']}",
        "",
        "## 8. 残 FN",
        "",
        f"- FN 件数: **{len(report.get('fn_details') or [])}**",
        "",
        "## 9. FP の変化",
        "",
        f"A では出ず B-v4 で出る追加 FP の query 数: {len(report.get('fp_vs_A') or [])}。 "
        f"micro FP v3={b_v3['micro_fp']} → v4={b_v4['micro_fp']}。",
        "",
        "## 10. 採用判定",
        "",
        f"- **{verdict['label']}** adopt={verdict['adopt']}",
        f"- {verdict['why']}",
        f"- Chrome hit rate: {_pct(verdict['chrome_hit_rate'])}",
        "",
        "## 11. DB-only に残る最大ボトルネック / 次タスク",
        "",
        report.get("max_risk") or "",
        "",
        report.get("next_task") or "",
        "",
    ])
    return "\n".join(lines) + "\n"
