"""Eval-only helpers for Semantic Index v3 DB-only (B-v3) scoring.

Reuses the existing Index-only matcher (`hybrid_v1` / include_hit). Does not
change product Ask AI, Hybrid thresholds, or Index generation.
Hold-out numbers may be reported after a freeze; they must not select configs.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from app.semantic_index.schema import CLIP_INDEX_TEXT_LIMIT, INDEX_FIELDS, clip_index_text
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
from tools.meaning_eval.metrics import summarize_end_to_end

PRIMARY_SEARCH_NAME = PRODUCT_SEARCH_CONFIG.name
SCALE_IMAGES = (100, 1_000, 10_000, 100_000)
SCALE_SEARCHES = (10, 100, 1_000)

# Phrase match in lexical_score uses only these lists.
LEX_PHRASE_FIELDS = (
    "searchable_concepts",
    "ui_interface_concepts",
    "objects_entities",
)
# Token coverage uses primary_terms: phrase lists plus activities/attributes/summary/scene.
LEX_COVERAGE_FIELDS = LEX_PHRASE_FIELDS + (
    "visible_activities",
    "visual_attributes",
    "visual_summary",
    "scene_environment",
)
CLIP_ONLY_FIELDS = ("media_type",)
INCIDENTAL_FIELD = "incidental_notes"

REPORT_CATEGORIES = (
    (
        "object",
        "object",
        ("dog", "a dog", "dog photo", "orange brown dog", "cat", "people"),
    ),
    (
        "application_product",
        "application / product",
        ("image search application", "screenshot manager application"),
    ),
    (
        "concrete_ui",
        "concrete UI",
        (
            "code editor",
            "browser window",
            "settings screen",
            "command prompt",
            "file explorer window",
            "terminal window",
            "tag management screen",
            "login screen",
            "folder selection screen",
            "software installation screen",
            "screen capture settings",
        ),
    ),
    (
        "broad_ui",
        "broad UI",
        (
            "Windows desktop",
            "Windows desktop screenshot",
            "desktop with application windows",
            "screenshot manager application",
            "image search application",
            "image gallery",
        ),
    ),
    (
        "game",
        "game",
        ("video game screenshot",),
    ),
    (
        "scene",
        "scene",
        (
            "Windows desktop",
            "Windows desktop screenshot",
            "mountain desktop wallpaper",
            "desktop with application windows",
        ),
    ),
    (
        "visual_attribute_style",
        "visual attribute / style",
        (
            "dark themed application",
            "anime",
            "empty state",
            "application error message",
        ),
    ),
    (
        "secondary_incidental",
        "secondary / incidental information",
        ("sitting",),
    ),
)


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{100.0 * value:.1f}%"


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in tokenize(text):
        tokens.add(token)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            tokens.add(token[:-1])
    return tokens


def field_token_hits(record: dict, query: str) -> dict[str, list[str]]:
    tokens = content_tokens(query)
    hits = {}
    for name in INDEX_FIELDS:
        value = record.get(name)
        if isinstance(value, list):
            text = " ".join(str(item) for item in value if item)
        else:
            text = str(value or "")
        found = [token for token in tokens if _token_set(token) & _token_set(text)]
        hits[name] = found
    return hits


def promote_incidental(record: dict) -> dict:
    """Eval-only diagnostic: treat incidental_notes as primary text."""
    promoted = dict(record)
    extra = str(record.get("incidental_notes") or "").strip()
    if not extra:
        return promoted
    summary = str(promoted.get("visual_summary") or "").strip()
    promoted["visual_summary"] = f"{summary} {extra}".strip()
    concepts = [str(item) for item in (promoted.get("searchable_concepts") or []) if item]
    if extra not in concepts:
        promoted["searchable_concepts"] = [*concepts, extra]
    return promoted


def would_hit_if_incidental_primary(
    query: str,
    record: dict,
    *,
    img: float,
    txt: float,
    config: SearchConfig = PRODUCT_SEARCH_CONFIG,
) -> bool:
    lex = lexical_score(query, promote_incidental(record))
    return include_hit(img, txt, lex, config)


def classify_index_only_fn(
    *,
    query: str,
    name: str,
    judgement: dict | None,
    record: dict | None,
    config: SearchConfig = PRODUCT_SEARCH_CONFIG,
) -> dict:
    """Why a GT must_include missed B-v3. Does not retune thresholds."""
    record = record or {}
    query_tokens = content_tokens(query)
    primary = _token_set(lexical_text(record))
    incidental = _token_set(incidental_text(record))
    found = [token for token in query_tokens if _token_set(token) & primary]
    missing = [token for token in query_tokens if token not in found]
    coverage = (len(found) / len(query_tokens)) if query_tokens else 0.0
    incidental_found = [
        token for token in query_tokens if _token_set(token) & (incidental - primary)
    ]
    incidental_coverage = (
        (len(incidental_found) / len(query_tokens)) if query_tokens else 0.0
    )
    lex = float((judgement or {}).get("lex") or 0.0)
    txt = float((judgement or {}).get("txt") or 0.0)
    img = float((judgement or {}).get("img") or 0.0)
    combined = combined_score(img, txt, lex, config)
    hit = bool((judgement or {}).get("relevant"))
    unknown = bool(record.get("unknown_reason") or (judgement or {}).get("unknown_reason"))
    fields = field_token_hits(record, query)
    schema_risk = query in SCHEMA_RISK_QUERIES
    incidental_primary_hit = would_hit_if_incidental_primary(
        query, record, img=img, txt=txt, config=config,
    ) and not hit

    if unknown:
        cause = CAUSE_INDEX_CONTENT
        causes = [CAUSE_INDEX_CONTENT]
    elif incidental_coverage > 0 and coverage == 0:
        cause = CAUSE_MATCHING
        causes = [CAUSE_MATCHING]
    elif coverage > 0 and not hit:
        cause = CAUSE_MATCHING
        causes = [CAUSE_MATCHING]
        if 0 < lex < config.lex_include or (
            lex >= config.lex_support and (txt < config.txt_min or img < config.img_min)
        ):
            causes.append(CAUSE_THRESHOLD)
            cause = CAUSE_MIXED
    elif coverage == 0 and incidental_coverage == 0 and schema_risk:
        cause = CAUSE_PROMPT_SCHEMA
        causes = [CAUSE_PROMPT_SCHEMA]
    else:
        cause = CAUSE_INDEX_CONTENT
        causes = [CAUSE_INDEX_CONTENT]

    return {
        "query": query,
        "name": name,
        "cause": cause,
        "causes": causes,
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "img": round(img, 4),
        "combined": round(combined, 4),
        "include_hit": hit,
        "query_tokens": query_tokens,
        "token_coverage": round(coverage, 3),
        "incidental_coverage": round(incidental_coverage, 3),
        "tokens_found": found,
        "tokens_missing": missing,
        "tokens_incidental_only": incidental_found,
        "field_hits": {key: value for key, value in fields.items() if value},
        "would_hit_if_incidental_primary": incidental_primary_hit,
        "schema_risk_query": schema_risk,
        "unknown_reason": record.get("unknown_reason"),
        "visual_summary": record.get("visual_summary") or "",
        "searchable_concepts": list(record.get("searchable_concepts") or []),
        "objects_entities": list(record.get("objects_entities") or []),
        "ui_interface_concepts": list(record.get("ui_interface_concepts") or []),
        "incidental_notes": record.get("incidental_notes") or "",
    }


def select_dev_policies(dev_by_config: dict[str, dict]) -> dict:
    """Pick recall / balanced / precision configs from DEV summaries only."""
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
        return (payload["macro_f1"], payload["macro_recall"], -int(payload["micro_fp"]), name)

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
        "primary_existing_B": PRIMARY_SEARCH_NAME,
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
            "Compared existing SEARCH_CONFIGS on dev only. Did not invent a "
            "new matcher. Hold-out was not used to choose a config."
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


def analyze_unused_fields(
    *,
    records: dict[str, dict],
    query_field_hits: Iterable[dict],
    clip_truncated: int,
    clip_total: int,
) -> dict:
    stored_nonempty = Counter()
    for record in records.values():
        if record.get("unknown_reason"):
            continue
        for name in INDEX_FIELDS:
            value = record.get(name)
            if isinstance(value, list):
                nonempty = any(str(item).strip() for item in value)
            else:
                nonempty = bool(str(value or "").strip())
            if nonempty:
                stored_nonempty[name] += 1
    lexical_hits = Counter()
    incidental_only_queries = 0
    for item in query_field_hits:
        fields = item.get("field_hits") or {}
        for name, tokens in fields.items():
            if tokens:
                lexical_hits[name] += 1
        if fields.get(INCIDENTAL_FIELD) and not any(
            fields.get(name) for name in LEX_COVERAGE_FIELDS
        ):
            incidental_only_queries += 1
    unused = []
    underused = []
    for name in INDEX_FIELDS:
        stored = stored_nonempty[name]
        used = lexical_hits[name]
        if name in CLIP_ONLY_FIELDS:
            unused.append({
                "field": name,
                "stored_images": stored,
                "lexical_query_hits": used,
                "reason": "clip_index_text only; lexical_score ignores media_type",
            })
        elif name == INCIDENTAL_FIELD:
            underused.append({
                "field": name,
                "stored_images": stored,
                "lexical_query_hits": used,
                "reason": (
                    "incidental_notes is down-weighted and never creates a hit "
                    "when primary coverage is 0 (lexical_score returns 0 before "
                    "the incidental multiplier)"
                ),
            })
        elif name in ("visible_activities", "visual_attributes"):
            underused.append({
                "field": name,
                "stored_images": stored,
                "lexical_query_hits": used,
                "reason": (
                    "token coverage only; not in lexical phrase-match lists "
                    f"{list(LEX_PHRASE_FIELDS)}"
                ),
            })
        elif stored and used == 0:
            unused.append({
                "field": name,
                "stored_images": stored,
                "lexical_query_hits": used,
                "reason": "stored on images but never matched a query token in this run",
            })
    return {
        "index_fields": list(INDEX_FIELDS),
        "lexical_phrase_fields": list(LEX_PHRASE_FIELDS),
        "lexical_coverage_fields": list(LEX_COVERAGE_FIELDS),
        "clip_fields": list(INDEX_FIELDS),
        "clip_char_limit": CLIP_INDEX_TEXT_LIMIT,
        "clip_truncated_images": clip_truncated,
        "clip_total_images": clip_total,
        "stored_nonempty_images": dict(stored_nonempty),
        "lexical_query_image_hits": dict(lexical_hits),
        "incidental_only_query_image_pairs": incidental_only_queries,
        "unused_or_clip_only": unused,
        "underused": underused,
        "notes": (
            "Search uses lexical_score + OpenCLIP query-vs-image and "
            "query-vs-clip_index_text. include_hit is lex>=0.50 or "
            "(lex>=0.34 and txt>=0.22 and img>=0.18). Hybrid clear-negative "
            "rescues are not used by Index-only."
        ),
    }


def _field_blob(record: dict, name: str) -> str:
    value = record.get(name)
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item).lower()
    return str(value or "").lower()


def chrome_product_evidence(record: dict) -> dict:
    """Distinguish Google Chrome the product from UI 'browser chrome'."""
    product_fields = []
    ui_chrome_fields = []
    for name in INDEX_FIELDS:
        text = _field_blob(record, name)
        if not text:
            continue
        has_product = (
            "google chrome" in text
            or "chrome browser" in text
            or "chromebrowser" in text
        )
        has_ui_phrase = "browser chrome" in text
        has_chrome_token = "chrome" in tokenize(text)
        if has_product:
            product_fields.append(name)
        elif has_ui_phrase and has_chrome_token:
            ui_chrome_fields.append(name)
        elif has_chrome_token:
            product_fields.append(name)
    return {
        "product_fields": product_fields,
        "ui_chrome_fields": ui_chrome_fields,
        "has_product_name": bool(product_fields),
        "has_ui_chrome_only": bool(ui_chrome_fields) and not product_fields,
    }


def chrome_db_only_row(
    *,
    query: str,
    name: str,
    record: dict,
    judgement: dict,
    config: SearchConfig = PRODUCT_SEARCH_CONFIG,
) -> dict:
    placement = _placement(record, query)
    evidence = chrome_product_evidence(record)
    lex = float(judgement.get("lex") or 0.0)
    txt = float(judgement.get("txt") or 0.0)
    img = float(judgement.get("img") or 0.0)
    hit = bool(judgement.get("relevant"))
    incidental_primary_hit = would_hit_if_incidental_primary(
        query, record, img=img, txt=txt, config=config,
    ) and not hit
    if record.get("unknown_reason"):
        reason = f"missing_index:{record.get('unknown_reason')}"
    elif hit:
        reason = "include_hit"
    elif evidence["has_ui_chrome_only"]:
        reason = "index_says_browser_chrome_not_google_chrome"
    elif not evidence["has_product_name"]:
        reason = "index_missing_chrome_product_name"
    elif placement["band"] == "incidental":
        reason = "chrome_only_in_incidental_notes"
    elif lex < config.lex_support:
        reason = "matching_lex_below_support"
    elif txt < config.txt_min or img < config.img_min:
        reason = "matching_support_branch_failed"
    else:
        reason = "matching_include_hit_false"
    return {
        "query": query,
        "name": name,
        "index_has_chrome": evidence["has_product_name"],
        "index_ui_chrome_only": evidence["has_ui_chrome_only"],
        "product_fields": evidence["product_fields"],
        "ui_chrome_fields": evidence["ui_chrome_fields"],
        "placement_band": placement["band"],
        "primary_fields": placement["primary_fields"],
        "incidental_fields": placement["incidental_fields"],
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "img": round(img, 4),
        "combined": round(combined_score(img, txt, lex, config), 4),
        "score": round(float(judgement.get("relevance_score") or combined_score(img, txt, lex, config)), 4),
        "in_result": hit,
        "reason_if_miss": None if hit else reason,
        "would_hit_if_incidental_primary": incidental_primary_hit,
        "visual_summary": record.get("visual_summary") or "",
        "objects_entities": list(record.get("objects_entities") or []),
        "searchable_concepts": list(record.get("searchable_concepts") or []),
        "incidental_notes": record.get("incidental_notes") or "",
    }


def category_rows(query_rows: list[dict]) -> list[dict]:
    by_query = {row["query"]: row for row in query_rows}
    out = []
    for key, label, queries in REPORT_CATEGORIES:
        present = [by_query[query] for query in queries if query in by_query]
        summary = summarize_end_to_end(present) if present else summarize_end_to_end([])
        misses = [
            {
                "query": row["query"],
                "split": row.get("split"),
                "recall": row["recall"],
                "fn": row["fn"],
                "tp": row["tp"],
                "fp": row["fp"],
            }
            for row in present
            if row["fn"] > 0 or row["recall"] < 1.0
        ]
        out.append({
            "key": key,
            "label": label,
            "n_queries": len(present),
            "queries": [row["query"] for row in present],
            **_compact_summary(summary),
            "mean_predicted": (
                sum(int(row.get("predicted_count") or row.get("tp", 0) + row.get("fp", 0)) for row in present)
                / len(present)
                if present else 0.0
            ),
            "queries_with_fn": misses,
        })
    return out


def scale_costs(
    *,
    index_usd_per_image: float,
    a_usd_per_image_per_search: float,
    c_usd_per_image_per_search: float,
) -> list[dict]:
    rows = []
    for n_images in SCALE_IMAGES:
        index_usd = index_usd_per_image * n_images
        for n_searches in SCALE_SEARCHES:
            a_search = a_usd_per_image_per_search * n_images * n_searches
            c_search = c_usd_per_image_per_search * n_images * n_searches
            rows.append({
                "images": n_images,
                "searches": n_searches,
                "index_generation_usd": round(index_usd, 4),
                "A_search_usd": round(a_search, 4),
                "B_v3_index_usd": round(index_usd, 4),
                "B_v3_search_usd": 0.0,
                "B_v3_total_usd": round(index_usd, 4),
                "C_v3_index_plus_search_usd": round(index_usd + c_search, 4),
                "C_v3_search_only_usd": round(c_search, 4),
            })
    return rows


def measure_clip_truncation(records: dict[str, dict]) -> tuple[int, int]:
    truncated = 0
    total = 0
    for record in records.values():
        if record.get("unknown_reason"):
            continue
        total += 1
        text = clip_index_text(record)
        if len(text) >= CLIP_INDEX_TEXT_LIMIT:
            truncated += 1
    return truncated, total


def verdict_from_b_v3(
    *,
    b_all: dict,
    a_all: dict,
    chrome_hit_rate: float,
    stable: bool,
    incidental_matching_fns: int,
    content_fns: int,
) -> dict:
    recall_vs_a = b_all["macro_recall"] - a_all["macro_recall"]
    precision_vs_a = b_all["macro_precision"] - a_all["macro_precision"]
    precision_floor = 0.25
    recall_ok = b_all["macro_recall"] + 1e-12 >= a_all["macro_recall"] - 0.05
    precision_usable = b_all["macro_precision"] + 1e-12 >= precision_floor
    chrome_ok = chrome_hit_rate + 1e-12 >= (10 / 12)
    if not stable:
        label = NO_GO
        why = "same DB + same query is not deterministic"
    elif not precision_usable:
        label = NO_GO
        why = "macro Precision is below a usable floor of 0.25"
    elif (
        recall_ok
        and chrome_ok
        and precision_vs_a >= -0.05
        and incidental_matching_fns == 0
        and content_fns == 0
    ):
        label = GO
        why = "Recall holds vs A, Chrome DB-only hits, Precision stays usable, matching uses stored names"
    elif recall_ok and precision_usable:
        label = CONDITIONAL_GO
        why = (
            "DB-only Recall is competitive with Vision Judge, but matching or "
            "named-container coverage still drops true images, or Precision "
            "still dumps extra broad-UI hits"
        )
    else:
        label = NO_GO
        why = "Recall or Precision is not good enough to drop Vision Judge"
    return {
        "verdict": label,
        "why": why,
        "recall_vs_A": round(recall_vs_a, 4),
        "precision_vs_A": round(precision_vs_a, 4),
        "chrome_hit_rate": round(chrome_hit_rate, 4),
        "stable": stable,
        "incidental_matching_fns": incidental_matching_fns,
        "content_fns": content_fns,
    }


def representative_fps(query_rows: list[dict], *, per_query: int = 3) -> list[dict]:
    rows = []
    for row in sorted(query_rows, key=lambda item: (-int(item.get("fp") or 0), item["query"])):
        if not row.get("fp"):
            continue
        rows.append({
            "query": row["query"],
            "split": row.get("split"),
            "fp": row["fp"],
            "tp": row["tp"],
            "precision": row["precision"],
            "examples": list(row.get("fp_names") or [])[:per_query],
        })
    return rows[:12]


def render_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_old = methods["B_old"]["all"]
    b_v3 = methods["B_v3"]["all"]
    c_v3 = methods["C_v3"]["all"]
    b_dev = methods["B_v3"]["dev"]
    b_hold = methods["B_v3"]["holdout"]
    selection = report["selection"]
    chrome = report["chrome"]
    unused = report["unused_fields"]
    fns = report["fn_details"]
    verdict = report["verdict"]
    stability = report["stability"]
    cost = report["cost"]
    lines = [
        "# Semantic Index v3 only (B-v3)",
        "",
        "製品 Ask AI / Meaning Search / Hybrid / Vision Judge / Index prompt は変更していない。",
        "B-v3 は保存済み `semantic-index-v3` と既存 local matcher（`hybrid_v1` include_hit）だけ。",
        "検索時の画像 Vision 送信は 0。hold-out で閾値は選んでいない。",
        "",
        "## 1. A / B-old / B-v3 / C-v3",
        "",
        "全 Ground Truth（dev + hold-out）:",
        "",
        "| method | source | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN | Vision/query | API req/query | USD/query | latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, key, payload in (
        ("A current Vision Judge", "A", a_all),
        ("B-old Index v1 only", "B_old", b_old),
        ("B-v3 Index v3 only", "B_v3", b_v3),
        ("C-v3 Hybrid", "C_v3", c_v3),
    ):
        lines.append(
            f"| {label} | `{key}` | {_fmt(payload['macro_precision'])} | "
            f"{_fmt(payload['macro_recall'])} | {_fmt(payload['macro_f1'])} | "
            f"{_fmt(payload.get('micro_precision'))} | {_fmt(payload.get('micro_recall'))} | "
            f"{_fmt(payload.get('micro_f1'))} | {payload['micro_tp']} | {payload['micro_fp']} | "
            f"{payload['micro_fn']} | {_fmt(payload.get('mean_vision_sent'), 1)} | "
            f"{_fmt(payload.get('mean_api_requests'), 1)} | "
            f"{_fmt(payload.get('mean_estimated_usd'), 4)} | "
            f"{_fmt(payload.get('mean_estimated_latency_seconds'), 2)} |"
        )
    lines.extend([
        "",
        "B-old は `semantic-index-hybrid-phase-e` の Index v1 `index_only` を再利用（再APIなし）。",
        "A と C-v3 は `semantic-index-hybrid-phase-e-v3` を再利用。B-v3 は同一 GT で local 再スコア。",
        "",
        f"- GT 正解画像の拾い率（micro Recall）: A {_pct(a_all.get('micro_recall'))} → "
        f"B-v3 **{_pct(b_v3.get('micro_recall'))}**（TP {b_v3['micro_tp']} / "
        f"{b_v3['micro_tp'] + b_v3['micro_fn']}）",
        f"- B-v3 vs B-old macro R: {_fmt(b_old['macro_recall'])} → {_fmt(b_v3['macro_recall'])}",
        f"- B-v3 vs A macro R: {_fmt(a_all['macro_recall'])} → {_fmt(b_v3['macro_recall'])} "
        f"（Recall 重視では A より{'良い' if b_v3['macro_recall'] >= a_all['macro_recall'] else '悪い'}）",
        "",
        "Dev / hold-out（B-v3、hold-out は確認のみ）:",
        "",
        f"- dev: P={_fmt(b_dev['macro_precision'])} R={_fmt(b_dev['macro_recall'])} "
        f"F1={_fmt(b_dev['macro_f1'])} FN={b_dev['micro_fn']} FP={b_dev['micro_fp']}",
        f"- hold-out: P={_fmt(b_hold['macro_precision'])} R={_fmt(b_hold['macro_recall'])} "
        f"F1={_fmt(b_hold['macro_f1'])} FN={b_hold['micro_fn']} FP={b_hold['micro_fp']}",
        "",
        "## 2. B-v3 macro / micro Precision / Recall / F1",
        "",
        "| split | n | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN | hits mean | Vision | API | USD | local latency s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for split_name, payload in (
        ("all", b_v3),
        ("dev", b_dev),
        ("holdout", b_hold),
    ):
        lines.append(
            f"| {split_name} | {payload.get('n', '-')} | {_fmt(payload['macro_precision'])} | "
            f"{_fmt(payload['macro_recall'])} | {_fmt(payload['macro_f1'])} | "
            f"{_fmt(payload.get('micro_precision'))} | {_fmt(payload.get('micro_recall'))} | "
            f"{_fmt(payload.get('micro_f1'))} | {payload['micro_tp']} | {payload['micro_fp']} | "
            f"{payload['micro_fn']} | {_fmt(payload.get('mean_predicted_count'), 1)} | "
            f"{_fmt(payload.get('mean_vision_sent'), 1)} | {_fmt(payload.get('mean_api_requests'), 1)} | "
            f"{_fmt(payload.get('mean_estimated_usd'), 4)} | "
            f"{_fmt(payload.get('mean_local_latency_seconds'), 3)} |"
        )
    lines.extend([
        "",
        "Query 別:",
        "",
        "| query | split | category-ish kind | P | R | F1 | TP | FP | FN | hits | Vision | API | USD |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report["query_rows"]["B_v3"]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | {row.get('kind', '')} | "
            f"{_fmt(row['precision'])} | {_fmt(row['recall'])} | {_fmt(row['f1'])} | "
            f"{row['tp']} | {row['fp']} | {row['fn']} | {row.get('predicted_count')} | "
            f"{row.get('vision_sent_images')} | {row.get('api_requests')} | "
            f"{_fmt(row.get('estimated_usd'), 4)} |"
        )
    lines.extend(["", "## 3. Query カテゴリ別（B-v3）", ""])
    lines.append("| category | n | macro P | macro R | macro F1 | micro R | TP | FP | FN | queries with FN |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for item in report["categories"]:
        missed = ", ".join(
            f"`{row['query']}` FN={row['fn']}" for row in item["queries_with_fn"]
        ) or "none"
        lines.append(
            f"| {item['label']} | {item['n_queries']} | {_fmt(item['macro_precision'])} | "
            f"{_fmt(item['macro_recall'])} | {_fmt(item['macro_f1'])} | "
            f"{_fmt(item.get('micro_recall'))} | {item['micro_tp']} | {item['micro_fp']} | "
            f"{item['micro_fn']} | {missed} |"
        )
    lines.extend([
        "",
        "Chrome 実機 12 件は GT に無いのでカテゴリ表外。application / product の実機確認は §4。",
        "",
        "## 4. Chrome 12 件の DB-only",
        "",
        "Vision に送れば拾えるかではなく、`include_hit` で result になるか。",
        "",
    ])
    for query in CHROME_QUERIES:
        rows = chrome["by_query"][query]
        hits = sum(1 for row in rows if row["in_result"])
        indexed = sum(1 for row in rows if row["index_has_chrome"])
        lines.extend([
            f"### `{query}`: result {hits}/12, Google Chrome 製品名あり {indexed}/12",
            "",
            "| image | product name | UI chrome only | band | lex | txt | img | score | result | miss reason |",
            "|---|---|---|---|---:|---:|---:|---:|---|---|",
        ])
        for row in rows:
            lines.append(
                f"| `{row['name']}` | {row.get('index_has_chrome')} | "
                f"{row.get('index_ui_chrome_only')} | {row['placement_band']} | "
                f"{_fmt(row['lex'], 3)} | {_fmt(row['txt'], 3)} | {_fmt(row['img'], 3)} | "
                f"{_fmt(row['score'], 3)} | {row['in_result']} | "
                f"{row.get('reason_if_miss') or ''} |"
            )
        lines.append("")
    lines.extend([
        f"- Google Chrome 製品名あり → result: "
        f"{chrome.get('product_named_hits', 0)} / "
        f"{chrome.get('product_named_hits', 0) + chrome.get('product_named_misses', 0)}",
        f"- 製品名なし（generic browser）: {chrome['missing_index']}",
        f"- `browser chrome`（UI 枠の意味）のみ: {chrome.get('ui_chrome_only', 0)}",
        f"- incidental を primary 扱いした診断で追加 hit: "
        f"{chrome['diagnostic_incidental_promoted_hits']} "
        f"（YouTube の 'browser chrome' 誤ヒットを含む）",
        "",
        "## 5. B-v3 で落ちる GT 画像",
        "",
        f"- FN 件数: **{len(fns)}**",
        "",
        "原因分類:",
        "",
    ])
    cause_counts = Counter(item["cause"] for item in fns)
    for cause, count in cause_counts.most_common():
        lines.append(f"- `{cause}`: {count}")
    lines.extend([
        "",
        "| query | split | image | cause | lex | txt | img | primary tokens | incidental-only | incidental→primary なら hit |",
        "|---|---|---|---|---:|---:|---:|---|---|---|",
    ])
    for item in fns:
        lines.append(
            f"| `{item['query']}` | {item.get('split', '')} | `{item['name']}` | "
            f"{item['cause']} | {_fmt(item['lex'], 3)} | {_fmt(item['txt'], 3)} | "
            f"{_fmt(item['img'], 3)} | {', '.join(item.get('tokens_found') or []) or '-'} | "
            f"{', '.join(item.get('tokens_incidental_only') or []) or '-'} | "
            f"{item.get('would_hit_if_incidental_primary')} |"
        )
    lines.extend(["", "## 6. B-v3 で増える FP の代表", ""])
    extra = report.get("fp_vs_A") or []
    if extra:
        lines.append("A では出ず B-v3 で出る FP（query あたり最大 3 件）:")
        lines.append("")
        for item in extra[:10]:
            examples = ", ".join(f"`{name}`" for name in item.get("examples") or [])
            lines.append(
                f"- `{item['query']}`: +{item['extra_fp']} "
                f"(B FP={item['b_fp']}, A FP={item['a_fp']}) {examples}"
            )
        lines.append("")
    lines.append("B-v3 FP が多い query:")
    lines.append("")
    for item in report.get("fp_representatives") or []:
        examples = ", ".join(f"`{name}`" for name in item.get("examples") or [])
        lines.append(
            f"- `{item['query']}` ({item['split']}): FP={item['fp']} P={_fmt(item['precision'])} {examples}"
        )
    lines.extend(["", "## 7. v3 に保存しているが検索判定で弱い情報", ""])
    lines.append(unused.get("notes") or "")
    lines.append("")
    lines.append(
        f"- `clip_index_text` 300 字で切れている画像: "
        f"{unused['clip_truncated_images']} / {unused['clip_total_images']}"
    )
    lines.append("")
    if unused.get("unused_or_clip_only"):
        lines.append("使っていない / CLIP のみ:")
        for item in unused["unused_or_clip_only"]:
            lines.append(
                f"- `{item['field']}` stored={item['stored_images']} "
                f"lexical_hits={item['lexical_query_hits']}: {item['reason']}"
            )
        lines.append("")
    if unused.get("underused"):
        lines.append("保存されているが matching が弱い:")
        for item in unused["underused"]:
            lines.append(
                f"- `{item['field']}` stored={item['stored_images']} "
                f"lexical_hits={item['lexical_query_hits']}: {item['reason']}"
            )
        lines.append("")
    lines.extend([
        "既存 B matcher が実際に使うもの:",
        "",
        "- lexical phrase: `searchable_concepts` / `ui_interface_concepts` / `objects_entities`",
        "- lexical coverage: 上記 + `visible_activities` / `visual_attributes` / `visual_summary` / `scene_environment`",
        "- semantic text: OpenCLIP(`clip_index_text`)",
        "- image/text: OpenCLIP image embedding vs raw `{q}`",
        "- incidental: `incidental_notes` は coverage=0 のとき **hit にならない**",
        "- Hybrid rescue（txt≥0.70 / compound）は Index-only では使わない",
        "",
        "## 8. Recall 優先条件（dev で選定、hold-out は凍結確認）",
        "",
        selection["notes"],
        "",
        f"- 既存 B（凍結 primary）: `{selection['primary_existing_B']}`",
        "",
        "| policy | config | selected on | dev P | dev R | dev F1 | dev FN | hold-out P | hold-out R | hold-out F1 | hold-out FN |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    hold_by_config = report.get("variant_holdout") or {}
    for policy in ("recall_first", "balanced", "precision_first"):
        item = selection["policies"][policy]
        hold = hold_by_config.get(item["config"]) or {}
        mark = " ← primary B" if item["config"] == selection["primary_existing_B"] else ""
        lines.append(
            f"| {policy}{mark} | `{item['config']}` | dev | "
            f"{_fmt(item['dev']['macro_precision'])} | {_fmt(item['dev']['macro_recall'])} | "
            f"{_fmt(item['dev']['macro_f1'])} | {item['dev']['micro_fn']} | "
            f"{_fmt(hold.get('macro_precision'))} | {_fmt(hold.get('macro_recall'))} | "
            f"{_fmt(hold.get('macro_f1'))} | {hold.get('micro_fn', '-')} |"
        )
    recall_cfg = selection["policies"]["recall_first"]["config"]
    recall_dev = selection["policies"]["recall_first"]["dev"]
    lines.extend([
        "",
        f"既存 SEARCH_CONFIGS の Recall 優先は `{recall_cfg}`。",
        f"dev Precision={_fmt(recall_dev['macro_precision'])} は実用不能なので、",
        "B-v3 の本表は既存 matcher `hybrid_v1` のまま。新アルゴリズムは実装していない。",
        "hold-out は選定後に一度だけ確認している。",
        "",
        "## 9. 同一 query の安定性",
        "",
        f"- repeats: {stability['repeats']}",
        f"- identical predicted sets: {stability['identical']}",
        f"- mismatched queries: {stability['mismatched_queries'] or 'none'}",
        "",
        "DB-only は同じ Index + 同じ OpenCLIP query ベクトルなら決定的。Vision Judge のような温度ゆらぎはない。",
        "",
        "## 10. 初期 Index 費用と検索費用",
        "",
        f"- Index 初期生成（119 images, `semantic-index-v3`）: **${_fmt(cost['index_generation_usd'], 4)}** "
        f"（cache_reused={cost['index_cache_reused']}。今回の評価 run では再課金していない）",
        f"- Index USD / image: ${_fmt(cost['index_usd_per_image'], 6)}",
        f"- B-v3 検索 Vision 画像送信: **0**",
        f"- B-v3 検索 API request: **0**",
        f"- B-v3 検索 USD / query: **$0**",
        f"- B-v3 検索 local latency mean: {_fmt(cost.get('b_local_latency_mean'), 3)} s "
        f"（query embed + 119 件スコア。Vision 待ち時間ではない）",
        f"- A 検索 USD / query（119 images）: ${_fmt(cost['A_usd_per_query'], 4)}",
        f"- C-v3 検索 USD / query: ${_fmt(cost['C_usd_per_query'], 4)}",
        "",
        "## 11. 100〜100,000 画像のコスト推定",
        "",
        "検索費用は A/C がライブラリサイズに比例、B-v3 は $0。初期 Index は 1 回。",
        "",
        "| images | searches | Index USD | A search USD | B-v3 total USD | C-v3 total USD |",
        "|---:|---:|---:|---:|---:|---:|",
    ])
    for row in cost["scale"]:
        lines.append(
            f"| {row['images']} | {row['searches']} | {row['index_generation_usd']} | "
            f"{row['A_search_usd']} | {row['B_v3_total_usd']} | "
            f"{row['C_v3_index_plus_search_usd']} |"
        )
    lines.extend([
        "",
        "## 12. DB-only にすると製品構造をどこまで簡略化できるか",
        "",
        "B-v3 を製品検索の最終判定にした場合に外せるもの / 残るもの（実装はしていない）:",
        "",
        "- 外せる: query ごとの Vision Judge、Hybrid uncertain 帯、Credits を検索回数で消費する経路、検索レイテンシの API 待ち",
        "- 残る: 画像 1 回の Index 生成、stale 再生成、OpenCLIP image/text embedding、Ask AI 同意（生成時）、失敗時 fallback",
        "- まだ残る理由: Index 欠落・stale・failure では今の製品は Vision へ落とす。DB-only にするならその fallback 方針を決める必要がある",
        "",
        "## 13. 採用判定",
        "",
        f"- **{verdict['verdict']}**",
        f"- {verdict['why']}",
        f"- Recall vs A: {verdict['recall_vs_A']:+.3f}",
        f"- Precision vs A: {verdict['precision_vs_A']:+.3f}",
        f"- Chrome DB-only hit rate: {_pct(verdict['chrome_hit_rate'])}",
        f"- 安定性: {verdict['stable']}",
        "",
        "## 14. DB-only へ移行する場合の最大リスク",
        "",
        report.get("max_risk") or "",
        "",
        "## 15. 次にやるべき 1 タスク",
        "",
        report.get("next_task") or "",
        "",
        "## Validation",
        "",
        f"- B-v3 predicted sets match previous Hybrid-eval B: {report['validation']['matches_previous_B']}",
        f"- hold-out used to retune: {report['validation']['holdout_used_for_retune']}",
        f"- primary matcher: `{PRIMARY_SEARCH_NAME}`",
        "",
    ])
    return "\n".join(lines) + "\n"
