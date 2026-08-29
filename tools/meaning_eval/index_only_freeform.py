"""Eval-only helpers for free-form search-document DB-only (B-freeform)."""

from __future__ import annotations

from collections import Counter

from app.semantic_index.scoring import SearchConfig, content_tokens, tokenize
from tools.meaning_eval.analyze_index_coverage import CHROME_QUERIES
from tools.meaning_eval.freeform_index import document_token_set, search_document
from tools.meaning_eval.hybrid_phase_e import CONDITIONAL_GO, GO, NO_GO, SCHEMA_RISK_QUERIES
from tools.meaning_eval.index_only_v3 import _fmt, _pct

CAUSE_MISSING = "missing_from_document"
CAUSE_MATCHING = "present_but_matching_miss"
CAUSE_AMBIGUOUS = "query_ambiguous"
CAUSE_GT_GAP = "gt_interpretation_gap"
FN_CAUSES = (CAUSE_MISSING, CAUSE_MATCHING, CAUSE_AMBIGUOUS, CAUSE_GT_GAP)

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
)
BROAD_UI_QUERIES = (
    "Windows desktop",
    "desktop with application windows",
    "folder selection screen",
    "Windows desktop screenshot",
    "image gallery",
    "image search application",
)

RELATED_TERMS = {
    "dog": ("dog", "puppy", "canine", "shiba"),
    "a dog": ("dog", "puppy", "canine", "shiba"),
    "dog photo": ("dog", "puppy", "canine", "shiba"),
    "orange brown dog": ("dog", "puppy", "shiba", "brown", "orange"),
    "cat": ("cat", "kitten", "feline", "calico"),
    "people": ("people", "person", "human", "character", "girl", "boy", "man", "woman", "figure"),
    "sitting": ("sit", "sits", "sitting", "seated"),
    "code editor": ("editor", "ide", "vscode", "cursor", "code"),
    "browser window": ("browser", "chrome", "tab"),
    "Google Chrome": ("chrome", "google"),
    "Chrome": ("chrome",),
    "dark themed application": ("dark", "theme", "themed"),
    "screenshot manager application": ("screenshot", "gallery", "capixe", "manager"),
    "Windows desktop": ("desktop", "wallpaper", "taskbar", "windows"),
    "video game screenshot": ("game", "gameplay", "hud"),
    "folder selection screen": ("folder", "browse", "directory"),
    "desktop with application windows": ("desktop", "window"),
    "image search application": ("gallery", "search", "thumbnail"),
    "image gallery": ("gallery", "thumbnail", "grid"),
}


def _token_forms(token: str) -> set[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        forms.add(token[:-1])
    return forms


def document_has_query_tokens(record: dict, query: str) -> tuple[list[str], list[str], float]:
    query_tokens = content_tokens(query)
    haystack = document_token_set(record)
    found = []
    missing = []
    for token in query_tokens:
        if _token_forms(token) & haystack:
            found.append(token)
        else:
            missing.append(token)
    coverage = (len(found) / len(query_tokens)) if query_tokens else 0.0
    return found, missing, coverage


def document_has_related_terms(record: dict, query: str) -> list[str]:
    haystack = document_token_set(record)
    related = []
    for term in RELATED_TERMS.get(query, ()):
        if _token_forms(term) & haystack:
            related.append(term)
    return related


def chrome_in_document(record: dict) -> dict:
    text = search_document(record).lower()
    tokens = tokenize(text)
    has_ui_phrase = "browser chrome" in text
    has_product = (
        "google chrome" in text
        or "chrome browser" in text
        or ("chrome" in tokens and "browser chrome" not in text)
    )
    if has_ui_phrase and "chrome" in tokens and "google chrome" not in text and "chrome browser" not in text:
        has_product = False
    return {
        "has_product_name": has_product,
        "has_ui_chrome_only": has_ui_phrase and not has_product,
        "mentions_chrome_token": "chrome" in tokens,
    }


def classify_freeform_fn(
    *,
    query: str,
    name: str,
    judgement: dict | None,
    record: dict | None,
    config: SearchConfig,
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

    if unknown:
        cause = CAUSE_MISSING
        subtype = "unknown_index"
    elif coverage > 0 or phrase:
        cause = CAUSE_MATCHING
        subtype = "query_tokens_present"
    elif related:
        cause = CAUSE_MATCHING
        subtype = "related_terms_present"
    elif ambiguous:
        cause = CAUSE_AMBIGUOUS
        subtype = "schema_risk_query"
    elif txt >= config.txt_min:
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
        "query_tokens": content_tokens(query),
        "token_coverage": round(coverage, 3),
        "tokens_found": found,
        "tokens_missing": missing,
        "related_terms_found": related,
        "schema_risk_query": ambiguous,
        "unknown_reason": record.get("unknown_reason"),
        "document_chars": len(document),
        "document_preview": document[:360],
    }


def chrome_db_only_row_freeform(
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
    }


def fn_cause_counts(fn_details: list[dict]) -> dict:
    counts = Counter(item["cause"] for item in fn_details)
    return {cause: int(counts.get(cause, 0)) for cause in FN_CAUSES}


def focus_query_rows(published: list[dict]) -> list[dict]:
    wanted = set(FOCUS_QUERIES)
    rows = [row for row in published if row["query"] in wanted]
    extra = [query for query in FOCUS_QUERIES if query not in {row["query"] for row in rows}]
    return rows


def broad_ui_fp_rows(published: list[dict]) -> list[dict]:
    wanted = set(BROAD_UI_QUERIES)
    return [row for row in published if row["query"] in wanted]


def sample_documents(records: dict[str, dict], names: tuple[str, ...]) -> list[dict]:
    samples = []
    for name in names:
        record = records.get(name)
        if not record:
            continue
        document = search_document(record)
        samples.append({
            "name": name,
            "chars": len(document),
            "words": len(document.split()),
            "unknown_reason": record.get("unknown_reason"),
            "document": document,
        })
    if len(samples) >= 4:
        return samples
    extras = []
    for name, record in sorted(records.items()):
        if name in names or record.get("unknown_reason"):
            continue
        document = search_document(record)
        extras.append({
            "name": name,
            "chars": len(document),
            "words": len(document.split()),
            "unknown_reason": record.get("unknown_reason"),
            "document": document,
        })
        if len(samples) + len(extras) >= 4:
            break
    return samples + extras


def verdict_from_b_freeform(
    *,
    b_all: dict,
    b_v4_all: dict,
    b_v3_all: dict,
    a_all: dict,
    chrome_hit_rate: float,
    stable: bool,
    matching_fns: int,
    missing_fns: int,
    fp_delta_vs_v4: int,
) -> dict:
    recall_vs_v4 = b_all["macro_recall"] - b_v4_all["macro_recall"]
    precision_vs_v4 = b_all["macro_precision"] - b_v4_all["macro_precision"]
    precision_floor = 0.20
    soup = fp_delta_vs_v4 >= 150 and precision_vs_v4 < -0.05
    if not stable:
        label = NO_GO
        why = "same DB + same query is not deterministic"
        adopt_center = False
    elif b_all["macro_precision"] + 1e-12 < precision_floor:
        label = NO_GO
        why = "macro Precision collapsed below a usable floor of 0.20"
        adopt_center = False
    elif soup:
        label = NO_GO
        why = "longer documents made too many images match; broad UI FP exploded"
        adopt_center = False
    elif (
        recall_vs_v4 >= -0.02
        and precision_vs_v4 >= -0.03
        and chrome_hit_rate + 1e-12 >= (10 / 12)
        and matching_fns <= missing_fns
    ):
        label = GO
        why = (
            "Free-form documents keep Recall and named-container coverage "
            "without a large Precision collapse"
        )
        adopt_center = True
    elif b_all["macro_recall"] + 1e-12 >= b_v4_all["macro_recall"] - 0.05:
        label = CONDITIONAL_GO
        why = (
            "Free-form is competitive as an Index representation, but matching "
            "or Precision still blocks replacing fixed-schema v4"
        )
        adopt_center = False
    else:
        label = NO_GO
        why = "Recall dropped vs fixed-schema v4 without a compensating gain"
        adopt_center = False
    return {
        "label": label,
        "adopt_as_index_center": adopt_center,
        "why": why,
        "recall_vs_v4": round(recall_vs_v4, 4),
        "precision_vs_v4": round(precision_vs_v4, 4),
        "recall_vs_v3": round(b_all["macro_recall"] - b_v3_all["macro_recall"], 4),
        "precision_vs_v3": round(b_all["macro_precision"] - b_v3_all["macro_precision"], 4),
        "recall_vs_A": round(b_all["macro_recall"] - a_all["macro_recall"], 4),
        "precision_vs_A": round(b_all["macro_precision"] - a_all["macro_precision"], 4),
        "fp_delta_vs_v4": fp_delta_vs_v4,
        "fn_delta_vs_v4": int(b_all["micro_fn"]) - int(b_v4_all["micro_fn"]),
        "chrome_hit_rate": round(chrome_hit_rate, 4),
        "stable": stable,
        "matching_fns": matching_fns,
        "missing_fns": missing_fns,
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


def render_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_v3 = methods["B_v3"]["all"]
    b_v4 = methods["B_v4"]["all"]
    b_ff = methods["B_freeform"]["all"]
    b_dev = methods["B_freeform"]["dev"]
    b_hold = methods["B_freeform"]["holdout"]
    c_all = methods["C_v3"]["all"]
    chrome = report["chrome"]
    fns = report["fn_details"]
    causes = report["fn_cause_counts"]
    verdict = report["verdict"]
    stability = report["stability"]
    cost = report["cost"]
    density = report["document_stats"]
    clip = report["clip_truncation"]
    selection = report["selection"]
    lines = [
        "# Semantic Index free-form only (B-freeform)",
        "",
        "製品 Ask AI / Meaning Search / Hybrid / Vision Judge / v4 Index / 通常 Search / UI / Credits は変更していない。",
        "B-freeform は評価用 `semantic-index-freeform-v1` の自然言語 search document と、その OpenCLIP text embedding と lexical matching だけ。",
        "検索時の画像 Vision 送信は 0。hold-out で閾値は選んでいない。",
        "",
        "## 1. free-form prompt",
        "",
        f"- prompt_version: `{report['validation']['prompt_version']}`",
        f"- schema_version: `{report['validation']['schema_version']}`",
        "- 目的: 未知 query から画像を発見するための検索ドキュメント。短い要約は禁止。",
        "- 固定 field は生成しない。検索は search_document のみ。",
        "",
        "## 2. 説明文の例",
        "",
    ]
    for sample in report.get("document_samples") or []:
        lines.extend([
            f"### {sample['name']} ({sample['words']} words / {sample['chars']} chars)",
            "",
            sample["document"] or "(empty)",
            "",
        ])
    lines.extend([
        "## 3. 説明量のばらつき",
        "",
        f"- chars min/p10/median/p90/max: {density['chars_min']} / {density['chars_p10']:.0f} / "
        f"{density['chars_median']:.0f} / {density['chars_p90']:.0f} / {density['chars_max']}",
        f"- words min/p10/median/p90/max: {density['words_min']} / {density['words_p10']:.0f} / "
        f"{density['words_median']:.0f} / {density['words_p90']:.0f} / {density['words_max']}",
        f"- too short ({density['too_short_rule']}): {density['too_short_images']} / {density['images']}",
        f"- OpenCLIP truncation (> {clip['content_token_limit']} tokens): "
        f"{clip['truncated_images']} / {clip['images']} ({_pct(clip['truncation_rate'])})",
        "",
        "## 4. B-v3 / B-v4 / B-freeform / A / C",
        "",
        "| method | source | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN | Vision/query | API req/query | USD/query | latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        _method_row("A Vision Judge", "A", a_all),
        _method_row("B-v3 Index only", "B_v3", b_v3),
        _method_row("B-v4 fixed-schema", "B_v4", b_v4),
        _method_row("B-freeform document only", "B_freeform", b_ff),
        _method_row(
            "B-freeform hybrid_v1 matcher",
            "B_freeform_hybrid_v1",
            methods["B_freeform_hybrid_v1"]["all"],
        ),
        _method_row("C Hybrid", "C_v3", c_all),
        "",
        f"- B-freeform primary matcher: `{methods['B_freeform']['search']}` (dev balanced)",
        "- `hybrid_v1` is the same include_hit family as B-v4, but document-only (no image cosine)",
        f"- selection split: {selection['selection_split']}; hold-out retune: {selection['holdout_used_for_retune']}",
        "",
        "## 5. Precision / Recall / F1",
        "",
        f"- B-freeform all: P {_fmt(b_ff['macro_precision'])} / R {_fmt(b_ff['macro_recall'])} / "
        f"F1 {_fmt(b_ff['macro_f1'])}",
        f"- B-freeform dev: P {_fmt(b_dev['macro_precision'])} / R {_fmt(b_dev['macro_recall'])} / "
        f"F1 {_fmt(b_dev['macro_f1'])}",
        f"- B-freeform hold-out (frozen, not used to tune): P {_fmt(b_hold['macro_precision'])} / "
        f"R {_fmt(b_hold['macro_recall'])} / F1 {_fmt(b_hold['macro_f1'])}",
        f"- vs B-v4: ΔP {verdict['precision_vs_v4']:+.3f} / ΔR {verdict['recall_vs_v4']:+.3f} / "
        f"ΔFP {verdict['fp_delta_vs_v4']:+d} / ΔFN {verdict['fn_delta_vs_v4']:+d}",
        "",
        "## 6. Chrome 12件",
        "",
        f"- DB-only Chrome hits: **{report['chrome_hits']}/12** (v3 {report['chrome_v3_hits']}/12, v4 {report['chrome_v4_hits']}/12)",
        f"- document has Chrome product name: {_pct(chrome.get('indexed_rate'))}",
        "",
    ])
    for query in CHROME_QUERIES:
        hits = sum(1 for row in chrome["by_query"][query] if row["in_result"])
        named = sum(1 for row in chrome["by_query"][query] if row["index_has_chrome"])
        lines.append(f"- `{query}`: result {hits}/12, named in document {named}/12")
    lines.extend([
        "",
        "## 7. broad UI の FP",
        "",
    ])
    for row in report.get("broad_ui") or []:
        lines.append(
            f"- `{row['query']}` ({row['split']}): FP {row['fp']} / TP {row['tp']} / "
            f"P {_fmt(row['precision'])} / predicted {row.get('predicted_count')}"
        )
    lines.extend([
        "",
        "Representative extra FPs vs A:",
        "",
    ])
    for row in (report.get("fp_vs_A") or [])[:8]:
        lines.append(
            f"- `{row['query']}` extra_fp={row['extra_fp']} examples={row['examples']}"
        )
    lines.extend([
        "",
        "## 8. FN 全件の原因分類",
        "",
        f"- missing_from_document: **{causes[CAUSE_MISSING]}**",
        f"- present_but_matching_miss: **{causes[CAUSE_MATCHING]}**",
        f"- query_ambiguous: **{causes[CAUSE_AMBIGUOUS]}**",
        f"- gt_interpretation_gap: **{causes[CAUSE_GT_GAP]}**",
        f"- FN total: **{len(fns)}**",
        "",
        "## 9. 情報はあるのに matching で落ちる件数",
        "",
        f"- **{causes[CAUSE_MATCHING]}** / {len(fns)} FN",
        "",
    ])
    matching = [item for item in fns if item["cause"] == CAUSE_MATCHING]
    for item in matching[:20]:
        lines.append(
            f"- `{item['query']}` / {item['name']}: {item['subtype']} "
            f"cov={item['token_coverage']} lex={item['lex']} txt={item['txt']} "
            f"found={item['tokens_found']} related={item['related_terms_found']}"
        )
    if not matching:
        lines.append("- none")
    lines.extend([
        "",
        "## 10. DB-only 検索の安定性",
        "",
        f"- repeats: {stability['repeats']}",
        f"- identical: **{stability['identical']}**",
        f"- mismatched queries: {stability['mismatched_queries'] or 'none'}",
        "",
        "## 11. Index 生成コスト",
        "",
        f"- cache reused: {cost['index_cache_reused']}",
        f"- freeform input/output tokens: {cost['freeform_input_tokens']} / {cost['freeform_output_tokens']}",
        f"- freeform USD / 119 images: ${cost['freeform_index_usd']:.4f}",
        f"- freeform USD/image: ${cost['freeform_usd_per_image']:.6f}",
        f"- v4 USD / 119 images: ${cost['v4_index_usd']:.4f} (${cost['v4_usd_per_image']:.6f}/image)",
        f"- v3 USD / 119 images: ${cost['v3_index_usd']:.4f}",
        f"- 1,000 images: ${cost['scale_usd']['1000']:.2f}",
        f"- 10,000 images: ${cost['scale_usd']['10000']:.2f}",
        f"- 100,000 images: ${cost['scale_usd']['100000']:.2f}",
        f"- search USD/query: ${cost['search_usd_per_query']:.4f} (DB-only, Vision 0)",
        "",
        "## 12. fixed-schema と free-form の長所短所",
        "",
        report.get("pros_cons") or "",
        "",
        "## 13. free-form を Semantic Index 中心データとして採用すべきか",
        "",
        f"- verdict: **{verdict['label']}** adopt_as_index_center={verdict['adopt_as_index_center']}",
        f"- why: {verdict['why']}",
        "",
        "## 14. DB-only 実現に残る最大ボトルネック",
        "",
        report.get("max_risk") or "",
        "",
        "## 15. 次にやる 1 タスク",
        "",
        report.get("next_task") or "",
        "",
        "## Focus queries",
        "",
    ])
    for row in report.get("focus_queries") or []:
        lines.append(
            f"- `{row['query']}` ({row['split']}): P {_fmt(row['precision'])} "
            f"R {_fmt(row['recall'])} F1 {_fmt(row['f1'])} "
            f"TP {row['tp']} FP {row['fp']} FN {row['fn']}"
        )
    lines.extend(["", "## Category", ""])
    for row in report.get("categories") or []:
        lines.append(
            f"- {row.get('label') or row.get('category')}: "
            f"P {_fmt(row.get('macro_precision'))} R {_fmt(row.get('macro_recall'))} "
            f"F1 {_fmt(row.get('macro_f1'))}"
        )
    lines.append("")
    return "\n".join(lines)
