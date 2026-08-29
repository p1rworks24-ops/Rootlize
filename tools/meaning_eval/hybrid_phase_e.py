"""Phase E freeze analysis for Semantic Index Hybrid vs the product Judge.

Eval-only. Does not select a new Hybrid band. Hold-out must not retune
thresholds. Frozen band and decision logic are the product Hybrid module.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from app.semantic_index.hybrid import (
    HybridBand,
    PRODUCT_HYBRID_BAND as FROZEN_BAND,
    PRODUCT_HYBRID_POLICY as FROZEN_POLICY,
)
from app.semantic_index.scoring import (
    SearchConfig,
    combined_score,
    content_tokens,
    include_hit,
    incidental_text,
    lexical_text,
    tokenize,
)

CATEGORY_OBJECT = "object"
CATEGORY_CONCRETE_UI = "concrete_ui"
CATEGORY_BROAD_UI = "broad_ui"
CATEGORY_ABSTRACT_STYLE = "abstract_style"
CATEGORY_ORDER = (
    CATEGORY_OBJECT,
    CATEGORY_CONCRETE_UI,
    CATEGORY_BROAD_UI,
    CATEGORY_ABSTRACT_STYLE,
)
CATEGORY_LABELS = {
    CATEGORY_OBJECT: "object",
    CATEGORY_CONCRETE_UI: "concrete UI",
    CATEGORY_BROAD_UI: "broad UI",
    CATEGORY_ABSTRACT_STYLE: "abstract/style",
}

QUERY_CATEGORIES = {
    "dog": CATEGORY_OBJECT,
    "a dog": CATEGORY_OBJECT,
    "dog photo": CATEGORY_OBJECT,
    "orange brown dog": CATEGORY_OBJECT,
    "sitting orange brown dog": CATEGORY_OBJECT,
    "cat": CATEGORY_OBJECT,
    "people": CATEGORY_OBJECT,
    "code editor": CATEGORY_CONCRETE_UI,
    "browser window": CATEGORY_CONCRETE_UI,
    "Google Chrome": CATEGORY_CONCRETE_UI,
    "ChatGPT in a browser": CATEGORY_CONCRETE_UI,
    "settings screen": CATEGORY_CONCRETE_UI,
    "command prompt": CATEGORY_CONCRETE_UI,
    "file explorer window": CATEGORY_CONCRETE_UI,
    "terminal window": CATEGORY_CONCRETE_UI,
    "tag management screen": CATEGORY_CONCRETE_UI,
    "login screen": CATEGORY_CONCRETE_UI,
    "folder selection screen": CATEGORY_CONCRETE_UI,
    "software installation screen": CATEGORY_CONCRETE_UI,
    "screen capture settings": CATEGORY_CONCRETE_UI,
    "Windows desktop": CATEGORY_BROAD_UI,
    "Windows desktop screenshot": CATEGORY_BROAD_UI,
    "Google Chrome in Windows desktop": CATEGORY_BROAD_UI,
    "desktop with application windows": CATEGORY_BROAD_UI,
    "screenshot manager application": CATEGORY_BROAD_UI,
    "image search application": CATEGORY_BROAD_UI,
    "image gallery": CATEGORY_BROAD_UI,
    "video game screenshot": CATEGORY_BROAD_UI,
    "mountain desktop wallpaper": CATEGORY_BROAD_UI,
    "dark themed application": CATEGORY_ABSTRACT_STYLE,
    "empty state": CATEGORY_ABSTRACT_STYLE,
    "empty folder in screenshot manager": CATEGORY_ABSTRACT_STYLE,
    "anime": CATEGORY_ABSTRACT_STYLE,
    "sitting": CATEGORY_ABSTRACT_STYLE,
    "application error message": CATEGORY_ABSTRACT_STYLE,
}

# Queries whose useful match is a product identity, theme, or empty layout
# rather than a named object the index prompt asks for directly.
SCHEMA_RISK_QUERIES = frozenset({
    "screenshot manager application",
    "image search application",
    "dark themed application",
    "empty state",
    "empty folder in screenshot manager",
    "sitting",
    "application error message",
    "people",
    "anime",
})

CAUSE_INDEX_CONTENT = "index_content_insufficient"
CAUSE_MATCHING = "matching_logic"
CAUSE_THRESHOLD = "threshold"
CAUSE_PROMPT_SCHEMA = "index_prompt_schema"
CAUSE_RETRIEVER = "retriever"
CAUSE_MIXED = "mixed"
FN_CAUSES = (
    CAUSE_INDEX_CONTENT,
    CAUSE_MATCHING,
    CAUSE_THRESHOLD,
    CAUSE_PROMPT_SCHEMA,
    CAUSE_RETRIEVER,
    CAUSE_MIXED,
)

NEAR_NEG_LEX = 0.18
NEAR_NEG_COMBINED = 0.20
LIVE_SAMPLE_MAX_IMAGES = 12
LIVE_SAMPLE_MAX_QUERIES = 4

GO = "GO"
CONDITIONAL_GO = "CONDITIONAL GO"
NO_GO = "NO-GO"
# Still a large Hybrid cost win vs sending every image. Not a hold-out fit.
MIN_GO_VISION_REDUCTION = 0.60

PREVIOUS_NEW_FNS = (
    ("image search application", "20260718_202750.png"),
    ("screenshot manager application", "20260801_135518.png"),
    ("image gallery", "20260801_132030.png"),
    ("dark themed application", "20260718_160651_001.png"),
    ("dark themed application", "20260720_234601.png"),
)


def query_category(query: str) -> str:
    try:
        return QUERY_CATEGORIES[query]
    except KeyError as exc:
        raise KeyError(f"Phase E category missing for query {query!r}") from exc


def _token_set(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in tokenize(text):
        tokens.add(token)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            tokens.add(token[:-1])
        if token.endswith("ed") and len(token) > 5:
            tokens.add(token[:-2])
        if token.endswith("ing") and len(token) > 6:
            tokens.add(token[:-3])
    return tokens


def _coverage(query_tokens: list[str], haystack: set[str]) -> float:
    if not query_tokens:
        return 0.0
    hits = 0
    for token in query_tokens:
        forms = {token}
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            forms.add(token[:-1])
        if forms & haystack:
            hits += 1
    return hits / len(query_tokens)


def _index_excerpt(record: dict | None) -> dict:
    item = record or {}
    return {
        "visual_summary": item.get("visual_summary") or "",
        "objects_entities": list(item.get("objects_entities") or []),
        "ui_interface_concepts": list(item.get("ui_interface_concepts") or []),
        "visual_attributes": list(item.get("visual_attributes") or []),
        "searchable_concepts": list(item.get("searchable_concepts") or []),
        "visible_activities": list(item.get("visible_activities") or []),
        "scene_environment": item.get("scene_environment") or "",
        "incidental_notes": item.get("incidental_notes") or "",
        "unknown_reason": item.get("unknown_reason"),
    }


def classify_new_fn(
    *,
    query: str,
    name: str,
    judgement: dict | None,
    record: dict | None,
    decision: str | None,
    ranking: list[str],
    search_config: SearchConfig,
    band: HybridBand = FROZEN_BAND,
) -> dict:
    """Classify one A-TP / C-FN. Does not change the frozen Hybrid band."""
    excerpt = _index_excerpt(record)
    query_tokens = content_tokens(query)
    primary = _token_set(lexical_text(record or {}))
    incidental = _token_set(incidental_text(record or {}))
    found = [
        token for token in query_tokens
        if _token_set(token) & primary
    ]
    missing = [token for token in query_tokens if token not in found]
    coverage = _coverage(query_tokens, primary)
    incidental_coverage = _coverage(query_tokens, incidental - primary)
    lex = float((judgement or {}).get("lex") or 0.0)
    txt = float((judgement or {}).get("txt") or 0.0)
    img = float((judgement or {}).get("img") or 0.0)
    combined = combined_score(img, txt, lex, search_config)
    hit = include_hit(img, txt, lex, search_config) if judgement and "lex" in judgement else False
    unknown = bool((record or {}).get("unknown_reason") or (judgement or {}).get("unknown_reason"))
    in_ranking = name in ranking
    near_threshold = (
        decision == "negative"
        and not hit
        and (lex >= NEAR_NEG_LEX or combined >= NEAR_NEG_COMBINED)
    )
    high_embedding = txt >= 0.45 and lex < 0.34 and decision == "negative"
    token_overlap = coverage > 0 or incidental_coverage > 0
    matching_gate = (
        decision == "negative"
        and not hit
        and (token_overlap or high_embedding)
    )
    schema_risk = query in SCHEMA_RISK_QUERIES
    no_tokens = not token_overlap

    if not in_ranking:
        cause = CAUSE_RETRIEVER
        unique = [CAUSE_RETRIEVER]
    elif unknown:
        cause = CAUSE_INDEX_CONTENT
        unique = [CAUSE_INDEX_CONTENT]
    elif matching_gate:
        cause = CAUSE_MATCHING
        unique = [CAUSE_MATCHING]
        if near_threshold:
            unique.append(CAUSE_THRESHOLD)
            cause = CAUSE_MIXED
    elif near_threshold:
        cause = CAUSE_THRESHOLD
        unique = [CAUSE_THRESHOLD]
    elif no_tokens and schema_risk:
        cause = CAUSE_PROMPT_SCHEMA
        unique = [CAUSE_PROMPT_SCHEMA]
    else:
        cause = CAUSE_INDEX_CONTENT
        unique = [CAUSE_INDEX_CONTENT]
    return {
        "query": query,
        "name": name,
        "category": query_category(query),
        "cause": cause,
        "causes": unique,
        "decision": decision,
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
        "near_negative_threshold": near_threshold,
        "schema_risk_query": schema_risk,
        "in_ranking": in_ranking,
        "index": excerpt,
    }


def collect_a_tp_c_fn(
    *,
    spec,
    a_row: dict,
    c_row: dict,
    records: dict[str, dict],
    ranking: list[str],
    search_config: SearchConfig,
) -> list[dict]:
    a_pred = set(a_row.get("predicted") or [])
    c_pred = set(c_row.get("predicted") or [])
    judgements = c_row.get("judgements") or {}
    decisions = c_row.get("decisions") or {}
    items = []
    for name in spec.must_include:
        if name in a_pred and name not in c_pred:
            items.append(classify_new_fn(
                query=spec.query,
                name=name,
                judgement=judgements.get(name),
                record=records.get(name),
                decision=decisions.get(name),
                ranking=ranking,
                search_config=search_config,
            ))
    return items


def collect_reduced_fp(a_row: dict, c_row: dict) -> list[dict]:
    a_fp = set(a_row.get("fp_names") or [])
    c_fp = set(c_row.get("fp_names") or [])
    decisions = c_row.get("decisions") or {}
    judgements = c_row.get("judgements") or {}
    rows = []
    for name in sorted(a_fp - c_fp):
        item = judgements.get(name) or {}
        rows.append({
            "query": a_row["query"],
            "split": a_row.get("split"),
            "name": name,
            "decision": decisions.get(name),
            "lex": item.get("lex"),
            "txt": item.get("txt"),
            "img": item.get("img"),
        })
    return rows


def summarize_rows(rows: list[dict], *, baseline_sent: float) -> dict:
    from tools.meaning_eval.evaluate_index_hybrid import _summarize_method
    return _summarize_method(rows, baseline_sent=baseline_sent)


def category_summary(a_rows: list[dict], c_rows: list[dict], new_fns: list[dict]) -> list[dict]:
    a_by_query = {row["query"]: row for row in a_rows}
    c_by_query = {row["query"]: row for row in c_rows}
    fn_by_cat = Counter(item["category"] for item in new_fns)
    grouped: dict[str, list[str]] = defaultdict(list)
    for query in a_by_query:
        grouped[query_category(query)].append(query)
    out = []
    for category in CATEGORY_ORDER:
        queries = grouped[category]
        a_sub = [a_by_query[query] for query in queries]
        c_sub = [c_by_query[query] for query in queries]
        a_sent = sum(float(row.get("vision_sent_images") or 0) for row in a_sub) / len(a_sub) if a_sub else 0.0
        a_sum = summarize_rows(a_sub, baseline_sent=a_sent)
        c_sum = summarize_rows(c_sub, baseline_sent=a_sent)
        out.append({
            "category": category,
            "label": CATEGORY_LABELS[category],
            "n_queries": len(queries),
            "queries": queries,
            "A": {
                "macro_precision": a_sum["macro_precision"],
                "macro_recall": a_sum["macro_recall"],
                "macro_f1": a_sum["macro_f1"],
                "micro_fp": a_sum["micro_fp"],
                "micro_fn": a_sum["micro_fn"],
                "mean_vision_sent": a_sum["mean_vision_sent"],
            },
            "C": {
                "macro_precision": c_sum["macro_precision"],
                "macro_recall": c_sum["macro_recall"],
                "macro_f1": c_sum["macro_f1"],
                "micro_fp": c_sum["micro_fp"],
                "micro_fn": c_sum["micro_fn"],
                "mean_vision_sent": c_sum["mean_vision_sent"],
                "vision_reduction": c_sum["vision_reduction"],
            },
            "new_fn": fn_by_cat[category],
        })
    return out


def select_live_sample(
    *,
    new_fns: list[dict],
    c_rows: list[dict],
    a_rows: list[dict],
    reduced_fps: list[dict],
    max_images: int = LIVE_SAMPLE_MAX_IMAGES,
    max_queries: int = LIVE_SAMPLE_MAX_QUERIES,
) -> list[dict]:
    """Small product-Judge sample. Prefer new FNs, then object/concrete UI replay."""
    a_by_query = {row["query"]: row for row in a_rows}
    c_by_query = {row["query"]: row for row in c_rows}
    selected: list[dict] = []
    seen: set[tuple[str, str]] = set()
    query_counts: Counter[str] = Counter()

    def add(query: str, name: str, role: str, *, force: bool = False) -> None:
        key = (query, name)
        if not name or key in seen:
            return
        if len(selected) >= max_images:
            return
        if (
            not force
            and query not in query_counts
            and len(query_counts) >= max_queries
        ):
            return
        seen.add(key)
        query_counts[query] += 1
        a_row = a_by_query[query]
        c_row = c_by_query[query]
        selected.append({
            "query": query,
            "name": name,
            "role": role,
            "category": query_category(query),
            "split": a_row.get("split"),
            "replay_relevant": name in set(a_row.get("predicted") or []),
            "hybrid_decision": (c_row.get("decisions") or {}).get(name),
        })

    for item in new_fns:
        add(item["query"], item["name"], "a_tp_c_fn", force=True)
    preferred_queries = []
    for query in ("cat", "terminal window", "login screen", "dog"):
        if query in c_by_query:
            preferred_queries.append(query)
    for row in c_rows:
        if row["query"] not in preferred_queries:
            continue
        a_pred = set(a_by_query[row["query"]].get("predicted") or [])
        decisions = row.get("decisions") or {}
        uncertain_true = [
            name for name, decision in decisions.items()
            if decision == "uncertain" and name in a_pred
        ]
        uncertain_false = [
            name for name, decision in decisions.items()
            if decision == "uncertain" and name not in a_pred
        ]
        for name in uncertain_true[:2]:
            add(row["query"], name, "uncertain_replay_true")
        for name in uncertain_false[:2]:
            add(row["query"], name, "uncertain_replay_false")
    for item in reduced_fps:
        if len(selected) >= max_images:
            break
        add(item["query"], item["name"], "a_fp_cleared_by_c")
    return selected


def count_negative_rescues(c_rows: list[dict]) -> dict:
    reason_counts: Counter[str] = Counter()
    images = 0
    for row in c_rows:
        for item in (row.get("judgements") or {}).values():
            reasons = item.get("negative_rescue_reasons") or []
            if not reasons:
                continue
            images += 1
            reason_counts.update(reasons)
    return {"images": images, "reasons": dict(reason_counts)}


def previous_fn_outcomes(
    *,
    c_rows: list[dict],
    new_fns: list[dict],
    previous: tuple[tuple[str, str], ...] = PREVIOUS_NEW_FNS,
) -> list[dict]:
    still_fn = {(item["query"], item["name"]) for item in new_fns}
    c_by_query = {row["query"]: row for row in c_rows}
    out = []
    for query, name in previous:
        row = c_by_query.get(query) or {}
        judgement = (row.get("judgements") or {}).get(name) or {}
        decision = (row.get("decisions") or {}).get(name)
        predicted = name in set(row.get("predicted") or [])
        out.append({
            "query": query,
            "name": name,
            "still_fn": (query, name) in still_fn,
            "decision": decision,
            "predicted": predicted,
            "uncertain_reason": judgement.get("uncertain_reason"),
            "negative_rescue_reasons": list(
                judgement.get("negative_rescue_reasons") or []
            ),
        })
    return out


def returned_reduced_fps(
    previous_reduced: list[dict] | None,
    current_reduced: list[dict],
) -> list[dict]:
    previous = {
        (item["query"], item["name"]): item
        for item in (previous_reduced or [])
    }
    current = {(item["query"], item["name"]) for item in current_reduced}
    returned = []
    for key, item in previous.items():
        if key not in current:
            returned.append({
                "query": item.get("query"),
                "name": item.get("name"),
                "split": item.get("split"),
            })
    returned.sort(key=lambda item: (item["query"] or "", item["name"] or ""))
    return returned


def compact_method_metrics(payload: dict | None) -> dict | None:
    if not payload:
        return None
    keys = (
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "micro_tp",
        "micro_fp",
        "micro_fn",
        "mean_vision_sent",
        "mean_api_requests",
        "vision_reduction",
        "mean_estimated_usd",
        "mean_estimated_latency_seconds",
        "total_vision_sent",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def snapshot_previous_phase_e(payload: dict | None) -> dict | None:
    if not payload:
        return None
    methods = payload.get("methods") or {}
    c_all = (methods.get("C") or {}).get("all") or {}
    if not c_all:
        return None
    return {
        "C_all": compact_method_metrics(c_all),
        "A_all": compact_method_metrics((methods.get("A") or {}).get("all") or {}),
        "new_fns": [
            {"query": item.get("query"), "name": item.get("name")}
            for item in (payload.get("new_fns") or [])
        ],
        "reduced_fps": [
            {
                "query": item.get("query"),
                "name": item.get("name"),
                "split": item.get("split"),
            }
            for item in (payload.get("reduced_fps") or [])
        ],
        "verdict": (payload.get("verdict") or {}).get("decision"),
    }


def verdict_from_metrics(
    *,
    new_fns: list[dict],
    category_rows: list[dict],
    live: dict | None,
    a_all: dict,
    c_all: dict,
    a_hold: dict,
    c_hold: dict,
) -> dict:
    """Connection verdict. Uses frozen band metrics only; does not retune."""
    cause_counts = Counter(item["cause"] for item in new_fns)
    by_cat = {item["category"]: item for item in category_rows}
    object_new = by_cat[CATEGORY_OBJECT]["new_fn"]
    concrete_new = by_cat[CATEGORY_CONCRETE_UI]["new_fn"]
    live_rate = None
    live_n = 0
    if live and live.get("compared"):
        live_n = int(live["compared"])
        live_rate = live.get("agreement_rate")
    live_ok = live_rate is None or live_n == 0 or live_rate >= 0.80
    object_safe = object_new == 0
    recall_drop = a_all["macro_recall"] - c_all["macro_recall"]
    hold_recall_drop = a_hold["macro_recall"] - c_hold["macro_recall"]
    vision_reduction = c_all.get("vision_reduction")
    reduction_ok = (
        vision_reduction is None or vision_reduction + 1e-12 >= MIN_GO_VISION_REDUCTION
    )
    reasons = []
    if not object_safe:
        reasons.append(f"object queries gained {object_new} new FN")
    if concrete_new:
        reasons.append(f"concrete UI gained {concrete_new} new FN")
    if new_fns:
        reasons.append(
            f"A→C new FN={len(new_fns)} "
            f"(content={cause_counts[CAUSE_INDEX_CONTENT]}, "
            f"matching={cause_counts[CAUSE_MATCHING]}, "
            f"schema={cause_counts[CAUSE_PROMPT_SCHEMA]}, "
            f"threshold={cause_counts[CAUSE_THRESHOLD]}, "
            f"mixed={cause_counts[CAUSE_MIXED]})"
        )
    if live_rate is not None and live_n:
        reasons.append(f"live vs replay agreement {live_rate:.0%} on {live_n} compared images")
    if vision_reduction is not None:
        reasons.append(f"Vision reduction {vision_reduction:.1%}")
    if not live_ok:
        decision = NO_GO
    elif not new_fns and live_ok and reduction_ok:
        decision = GO
    elif object_safe and concrete_new <= 1 and hold_recall_drop <= 0.05:
        decision = CONDITIONAL_GO
        if new_fns:
            reasons.append(
                "object search is intact and hold-out recall drop stays within 5%, "
                "but Hybrid clear-negatives still drop Vision true positives"
            )
        elif not reduction_ok:
            reasons.append(
                "new FN is gone, but Vision reduction fell below 60% so the "
                "Hybrid cost win is no longer large enough for GO"
            )
    else:
        decision = NO_GO
    if decision == GO:
        next_task = (
            "Wire the frozen precision_first Hybrid band, including the "
            "clear-negative rescue gate, into Ask AI / Meaning Search behind "
            "the existing Vision Judge replay path."
        )
    elif decision == CONDITIONAL_GO:
        if new_fns:
            next_task = (
                "Do not connect Ask AI. Keep the frozen band. Inspect remaining "
                "clear-negative FN, then rerun Phase E on the same Ground Truth."
            )
        else:
            next_task = (
                "Do not connect Ask AI yet. Keep the frozen band. Tighten the "
                "clear-negative rescue so Vision send stays low without bringing "
                "the previous FN back, then rerun Phase E."
            )
    else:
        next_task = (
            "Keep Ask AI on the current Vision Judge. Next: repair Index "
            "clear-negative FN on the frozen band before any product connection."
        )
    return {
        "decision": decision,
        "reasons": reasons,
        "object_new_fn": object_new,
        "concrete_ui_new_fn": concrete_new,
        "new_fn": len(new_fns),
        "cause_counts": dict(cause_counts),
        "recall_drop_all": round(recall_drop, 4),
        "recall_drop_holdout": round(hold_recall_drop, 4),
        "live_agreement_rate": live_rate,
        "next_task": next_task,
        "band": FROZEN_BAND.name,
        "policy": FROZEN_POLICY,
    }
