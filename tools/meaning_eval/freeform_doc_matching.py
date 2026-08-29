"""Eval-only document-oriented matching for free-form search documents.

Matches queries against chunked search documents instead of one truncated
OpenCLIP embedding. Does not change product search paths.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from app.semantic_index.scoring import STOPWORDS, cosine, tokenize
from tools.meaning_eval.describe_judge import empty_usage
from tools.meaning_eval.freeform_index import (
    _coverage,
    _has_phrase,
    document_token_set,
    empty_freeform_record,
    freeform_index_judgement,
    search_document,
)
from tools.meaning_eval.freeform_chunking import CHUNK_STRATEGIES, split_document

BACKGROUND_MARKERS = (
    "background",
    "incidental",
    "behind it",
    "behind the",
    "in the background",
    "wallpaper",
    "taskbar",
    "along the bottom",
    "bottom of the screen",
    "desktop wallpaper",
    "visible at the bottom",
    "soft-focus",
    "blurred",
    "behind the main",
    "secondary content",
    "no open application windows",
    "no browser",
    "no active window",
    "aside from",
)

BROAD_UI_QUERIES = frozenset({
    "Windows desktop",
    "Windows desktop screenshot",
    "desktop with application windows",
    "folder selection screen",
    "image search application",
    "image gallery",
})

GENERIC_QUERY_TOKENS = frozenset({
    "desktop", "windows", "window", "application", "screen", "screenshot",
    "folder", "gallery", "search", "image", "manager",
})

# Generic UI vocabulary for density gating. Query names are not hardcoded.
GENERIC_UI_TOKENS = frozenset({
    "desktop", "window", "windows", "application", "app", "screen", "screenshot",
    "image", "search", "setting", "settings", "gallery", "folder", "manager",
    "ui", "interface",
})

_SHOWN_WITH_RE = re.compile(r"\bis shown with\b|\bshown with\b", re.I)
_FOREGROUND_RE = re.compile(
    r"\bin the foreground\b|"
    r"\bfilling the (?:screen|page|window)\b|"
    r"\bfills the (?:screen|page|window)\b|"
    r"\bfilling most of the\b",
    re.I,
)
_INCIDENTAL_SUBJECT_RE = re.compile(
    r"\bin the background\b|\bbehind it\b|\bbehind the\b|\bincidental\b",
    re.I,
)


@dataclass(frozen=True)
class DocMatchConfig:
    name: str
    chunk_strategy: str
    aggregation: str
    txt_min: float
    lex_support: float
    lex_include: float
    combined_min: float = 0.0
    txt_weight: float = 0.55
    lex_weight: float = 0.45
    background_penalty: float = 0.40
    opening_boost: float = 1.15
    require_non_bg_for_broad: bool = True
    top_k: int = 2
    generic_density_min: float = 1.01
    generic_txt_boost: float = 0.0
    generic_lex_min: float = 0.0
    opening_gate: bool = False
    min_evidence: int = 1
    short_generic_full_coverage: bool = False


DOC_MATCH_CONFIGS: tuple[DocMatchConfig, ...] = (
    DocMatchConfig(
        "sent_max_0.24", "sentence", "max", txt_min=0.24, lex_support=0.34,
        lex_include=1.0, combined_min=0.0,
    ),
    DocMatchConfig(
        "sent_max_0.20", "sentence", "max", txt_min=0.20, lex_support=0.34,
        lex_include=1.0, combined_min=0.0,
    ),
    DocMatchConfig(
        "sent_lex_0.22", "sentence", "max", txt_min=0.22, lex_support=0.50,
        lex_include=0.67, combined_min=0.0,
    ),
    DocMatchConfig(
        "sent_ctx_0.22", "sentence", "max", txt_min=0.22, lex_support=0.50,
        lex_include=0.67, combined_min=0.0, background_penalty=0.35,
        opening_boost=1.20, require_non_bg_for_broad=True,
    ),
    DocMatchConfig(
        "sent_top2_0.22", "sentence", "top2_mean", txt_min=0.22, lex_support=0.50,
        lex_include=0.67, combined_min=0.0, background_penalty=0.40,
        opening_boost=1.15, require_non_bg_for_broad=True, top_k=2,
    ),
    DocMatchConfig(
        "para_ctx_0.22", "paragraph", "max", txt_min=0.22, lex_support=0.50,
        lex_include=0.67, combined_min=0.0, background_penalty=0.35,
        opening_boost=1.20, require_non_bg_for_broad=True,
    ),
    DocMatchConfig(
        "ovlp_ctx_0.20", "overlap_window", "max", txt_min=0.20, lex_support=0.50,
        lex_include=0.67, combined_min=0.0, background_penalty=0.35,
        opening_boost=1.10, require_non_bg_for_broad=True,
    ),
    DocMatchConfig(
        "sent_combo_0.20", "sentence", "max", txt_min=0.20, lex_support=0.34,
        lex_include=0.67, combined_min=0.24, background_penalty=0.40,
        opening_boost=1.15, require_non_bg_for_broad=True,
    ),
)

PRIMARY_DOC_MATCH_NAME = "sent_ctx_0.22"
RECALL_FOCUS_NAME = "ovlp_ctx_0.20"
FP_BASELINE_NAME = "sent_top2_0.22"

_SENT_TOP2 = DOC_MATCH_CONFIGS[4]
_OVLP_CTX = DOC_MATCH_CONFIGS[6]


def _gated(name: str, base: DocMatchConfig, **overrides) -> DocMatchConfig:
    values = {
        "name": name,
        "chunk_strategy": base.chunk_strategy,
        "aggregation": base.aggregation,
        "txt_min": base.txt_min,
        "lex_support": base.lex_support,
        "lex_include": base.lex_include,
        "combined_min": base.combined_min,
        "txt_weight": base.txt_weight,
        "lex_weight": base.lex_weight,
        "background_penalty": base.background_penalty,
        "opening_boost": base.opening_boost,
        "require_non_bg_for_broad": base.require_non_bg_for_broad,
        "top_k": base.top_k,
        "generic_density_min": 2 / 3,
    }
    values.update(overrides)
    return DocMatchConfig(**values)


FP_GATE_CONFIGS: tuple[DocMatchConfig, ...] = (
    _gated(
        "sent_open_gate", _SENT_TOP2,
        opening_gate=True,
    ),
    _gated(
        "sent_gen_thr", _SENT_TOP2,
        generic_txt_boost=0.08,
        generic_lex_min=0.67,
        short_generic_full_coverage=True,
    ),
    _gated(
        "sent_multi_ev", _SENT_TOP2,
        min_evidence=2,
    ),
    _gated(
        "sent_open_gen", _SENT_TOP2,
        opening_gate=True,
        generic_txt_boost=0.08,
        generic_lex_min=0.67,
        short_generic_full_coverage=True,
    ),
    _gated(
        "sent_open_multi", _SENT_TOP2,
        opening_gate=True,
        min_evidence=2,
    ),
    _gated(
        "sent_fp_all", _SENT_TOP2,
        opening_gate=True,
        generic_txt_boost=0.08,
        generic_lex_min=0.67,
        short_generic_full_coverage=True,
        min_evidence=2,
    ),
    _gated(
        "ovlp_open_gate", _OVLP_CTX,
        opening_gate=True,
    ),
    _gated(
        "ovlp_gen_thr", _OVLP_CTX,
        generic_txt_boost=0.08,
        generic_lex_min=0.67,
        short_generic_full_coverage=True,
    ),
    _gated(
        "ovlp_open_multi", _OVLP_CTX,
        opening_gate=True,
        min_evidence=2,
    ),
    _gated(
        "ovlp_fp_all", _OVLP_CTX,
        opening_gate=True,
        generic_txt_boost=0.08,
        generic_lex_min=0.67,
        short_generic_full_coverage=True,
        min_evidence=2,
    ),
)


def fp_eval_configs() -> tuple[DocMatchConfig, ...]:
    by_name = {config.name: config for config in DOC_MATCH_CONFIGS}
    return (by_name[FP_BASELINE_NAME], by_name[RECALL_FOCUS_NAME], *FP_GATE_CONFIGS)


def _chunk_is_background(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in BACKGROUND_MARKERS)


def _chunk_lexical_score(query: str, chunk_text: str) -> float:
    query_l = query.lower().strip()
    document = chunk_text.lower()
    if not document or not query_l:
        return 0.0
    phrase = 1.0 if _has_phrase(query_l, document) else 0.0
    tokens = [token for token in tokenize(query_l) if token]
    if not tokens:
        return 0.0
    haystack = set()
    for token in tokenize(document):
        haystack.add(token)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            haystack.add(token[:-1])
    coverage = _coverage(tokens, haystack)
    if phrase == 0.0 and coverage < 0.34:
        return 0.0
    return min(1.0, max(phrase, coverage))


def _position_weight(
    *,
    index: int,
    total: int,
    chunk_text: str,
    config: DocMatchConfig,
) -> float:
    weight = 1.0
    if index == 0:
        weight *= config.opening_boost
    if _chunk_is_background(chunk_text):
        weight *= config.background_penalty
    if total > 1 and index == total - 1 and _chunk_is_background(chunk_text):
        weight *= 0.85
    return weight


def _aggregate(values: list[float], aggregation: str, top_k: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values, reverse=True)
    if aggregation == "max":
        return ordered[0]
    if aggregation == "top2_mean":
        picked = ordered[: max(1, top_k)]
        return sum(picked) / len(picked)
    if aggregation == "top3_mean":
        picked = ordered[: max(1, min(3, top_k))]
        return sum(picked) / len(picked)
    raise ValueError(f"unknown aggregation: {aggregation}")


def query_content_tokens(query: str) -> list[str]:
    return [token for token in tokenize(query.lower()) if token and token not in STOPWORDS]


def _is_generic_ui_token(token: str) -> bool:
    forms = {token}
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        forms.add(token[:-1])
    return bool(forms & GENERIC_UI_TOKENS)


def generic_token_density(query: str) -> float:
    tokens = query_content_tokens(query)
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if _is_generic_ui_token(token))
    return hits / len(tokens)


def extract_primary_span(text: str) -> str:
    """Prefer the main-subject clause over scene-setting prefixes."""
    text = (text or "").strip()
    if not text:
        return text
    shown = _SHOWN_WITH_RE.search(text)
    if shown:
        after = text[shown.end():].strip(" ,")
        if after:
            text = after
    else:
        foreground = _FOREGROUND_RE.search(text)
        if foreground:
            start = max(0, foreground.start() - 80)
            window = text[start:foreground.end()].strip(" ,")
            comma = window.rfind(",")
            if comma >= 0 and comma < len(window) - 8:
                window = window[comma + 1:].strip()
            if window:
                text = window
    return strip_incidental_clauses(text)


def strip_incidental_clauses(text: str) -> str:
    parts = re.split(r"(?:,\s*|\s+(?:while|and)\s+)", text)
    kept = []
    for part in parts:
        part = part.strip(" ,")
        if not part or _INCIDENTAL_SUBJECT_RE.search(part):
            continue
        kept.append(part)
    return " ".join(kept)


def _is_broad_ui_query(query: str) -> bool:
    return query in BROAD_UI_QUERIES


def _query_is_generic(query: str) -> bool:
    tokens = set(tokenize(query.lower()))
    if not tokens:
        return False
    generic_hits = tokens & GENERIC_QUERY_TOKENS
    return len(generic_hits) >= max(1, len(tokens) - 1)


def _is_high_generic_density(query: str, config: DocMatchConfig) -> bool:
    return generic_token_density(query) + 1e-12 >= config.generic_density_min


def _effective_thresholds(query: str, config: DocMatchConfig) -> tuple[float, float, bool]:
    density = generic_token_density(query)
    high = density + 1e-12 >= config.generic_density_min
    txt_min = config.txt_min
    lex_support = config.lex_support
    if high:
        txt_min = config.txt_min + config.generic_txt_boost
        if config.generic_lex_min > lex_support:
            lex_support = config.generic_lex_min
        tokens = query_content_tokens(query)
        if config.short_generic_full_coverage and len(tokens) <= 2 and density + 1e-12 >= 0.99:
            lex_support = max(lex_support, 1.0)
    return txt_min, lex_support, high


def build_chunk_index(
    runtime,
    records: dict[str, dict],
    *,
    strategy: str,
) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for name, record in records.items():
        if record.get("unknown_reason"):
            continue
        document = search_document(record)
        if not document:
            continue
        chunks = split_document(document, strategy, runtime)
        built = []
        for position, chunk_text in enumerate(chunks):
            built.append({
                "text": chunk_text,
                "vector": runtime.embed_text(chunk_text),
                "position": position,
                "is_background": _chunk_is_background(chunk_text),
            })
        index[name] = built
    return index


def doc_match_judgement(
    query: str,
    record: dict,
    *,
    query_vector: Sequence[float] | None,
    chunks: Sequence[dict],
    config: DocMatchConfig,
) -> dict:
    if record.get("unknown_reason"):
        return {
            "relevant": None,
            "relevance_score": None,
            "confidence": None,
            "reason": record.get("unknown_reason"),
            "unknown_reason": record.get("unknown_reason"),
        }
    if not chunks:
        return {
            "relevant": False,
            "relevance_score": 0.0,
            "confidence": 0.0,
            "reason": "no_chunks",
            "lex": 0.0,
            "txt": 0.0,
            "img": 0.0,
            "best_chunk": None,
            "chunk_hits": 0,
        }

    weighted_txt: list[float] = []
    weighted_lex: list[float] = []
    best_chunk = None
    best_score = -1.0
    chunk_details = []
    total = len(chunks)
    for chunk in chunks:
        position = int(chunk["position"])
        text = str(chunk["text"])
        weight = _position_weight(
            index=position,
            total=total,
            chunk_text=text,
            config=config,
        )
        lex = _chunk_lexical_score(query, text)
        txt = cosine(query_vector, chunk.get("vector"))
        weighted_txt.append(txt * weight)
        weighted_lex.append(lex * weight)
        combined = config.txt_weight * txt + config.lex_weight * lex
        score = combined * weight
        chunk_details.append({
            "position": position,
            "is_background": bool(chunk.get("is_background")),
            "lex": round(lex, 4),
            "txt": round(txt, 4),
            "weight": round(weight, 4),
            "text": text,
            "text_preview": text[:160],
        })
        if score > best_score:
            best_score = score
            best_chunk = chunk_details[-1]

    txt = _aggregate(weighted_txt, config.aggregation, config.top_k)
    lex = _aggregate(weighted_lex, config.aggregation, config.top_k)
    combined = (
        (config.txt_weight * txt + config.lex_weight * lex)
        / (config.txt_weight + config.lex_weight)
        if (config.txt_weight + config.lex_weight) > 0
        else 0.0
    )

    phrase_any = any(
        item["lex"] >= 1.0 or _has_phrase(query, item.get("text") or "")
        for item in chunk_details
    )
    non_bg_lex = max(
        (item["lex"] for item in chunk_details if not item["is_background"]),
        default=0.0,
    )
    non_bg_txt = max(
        (item["txt"] for item in chunk_details if not item["is_background"]),
        default=0.0,
    )
    opening_lex = chunk_details[0]["lex"] if chunk_details else 0.0
    opening_txt = chunk_details[0]["txt"] if chunk_details else 0.0
    txt_min, lex_support, high_generic = _effective_thresholds(query, config)

    broad = _is_broad_ui_query(query) or _query_is_generic(query)
    hit = False
    if lex >= config.lex_include or phrase_any:
        if broad and config.require_non_bg_for_broad:
            hit = non_bg_lex >= config.lex_support or opening_lex >= config.lex_include
        else:
            hit = True
    elif lex >= lex_support and txt >= txt_min:
        if broad and config.require_non_bg_for_broad:
            hit = (
                non_bg_lex >= lex_support
                and non_bg_txt >= txt_min
            ) or (
                opening_lex >= lex_support
                and opening_txt >= txt_min
            )
        else:
            hit = True
    elif config.combined_min > 0 and combined >= config.combined_min:
        if broad and config.require_non_bg_for_broad:
            hit = non_bg_txt >= txt_min or opening_txt >= txt_min
        else:
            hit = True

    primary_needed = lex_support
    if high_generic and config.opening_gate:
        tokens = query_content_tokens(query)
        if len(tokens) <= 2 and generic_token_density(query) + 1e-12 >= 0.99:
            primary_needed = max(primary_needed, 1.0)
    opening_region = chunk_details[: min(2, len(chunk_details))]
    opening_relevant = False
    primary_span = ""
    primary_lex = 0.0
    primary_phrase = False
    for item in opening_region:
        span = extract_primary_span(str(item.get("text") or ""))
        if not span:
            continue
        span_lex = _chunk_lexical_score(query, span)
        span_phrase = _has_phrase(query, span)
        if not primary_span:
            primary_span = span
            primary_lex = span_lex
            primary_phrase = span_phrase
        if span_lex > primary_lex:
            primary_span = span
            primary_lex = span_lex
            primary_phrase = span_phrase
        if span_lex + 1e-12 >= primary_needed or span_phrase:
            opening_relevant = True
            break
    non_bg_chunk_hits = [
        item for item in chunk_details
        if not item["is_background"]
        and (item["lex"] >= lex_support or item["txt"] >= txt_min)
    ]
    lexical_hits_non_bg = [
        item for item in chunk_details
        if not item["is_background"] and item["lex"] >= lex_support
    ]
    multi_chunk = len(non_bg_chunk_hits) >= 2
    multi_lexical = len(lexical_hits_non_bg) >= 2
    lexical_evidence = non_bg_lex >= lex_support or phrase_any
    evidence = {
        "lexical": lexical_evidence,
        "opening": opening_relevant,
        "multi_chunk": multi_chunk,
        "phrase": phrase_any,
    }
    evidence_count = sum(1 for value in evidence.values() if value)

    if high_generic and config.opening_gate and hit:
        if not (opening_relevant or multi_lexical):
            hit = False
    if high_generic and config.min_evidence > 1 and hit:
        if evidence_count < config.min_evidence:
            hit = False

    published_best = None
    if best_chunk is not None:
        published_best = {key: value for key, value in best_chunk.items() if key != "text"}

    return {
        "relevant": hit,
        "relevance_score": combined,
        "confidence": lex,
        "reason": f"lex={lex:.3f} txt={txt:.3f} img=0.000 chunks={len(chunks)}",
        "lex": lex,
        "txt": txt,
        "img": 0.0,
        "best_chunk": published_best,
        "chunk_hits": sum(
            1 for item in chunk_details
            if item["lex"] >= lex_support or item["txt"] >= txt_min
        ),
        "chunk_details": [
            {key: value for key, value in item.items() if key != "text"}
            for item in chunk_details
        ],
        "non_bg_lex": round(non_bg_lex, 4),
        "non_bg_txt": round(non_bg_txt, 4),
        "opening_lex": round(opening_lex, 4),
        "opening_txt": round(opening_txt, 4),
        "generic_density": round(generic_token_density(query), 4),
        "high_generic": high_generic,
        "primary_span": primary_span[:180],
        "primary_lex": round(primary_lex, 4),
        "opening_relevant": opening_relevant,
        "evidence": evidence,
        "evidence_count": evidence_count,
        "effective_txt_min": txt_min,
        "effective_lex_support": lex_support,
    }


def search_doc_matching_records(
    query: str,
    names: Sequence[str],
    records: dict[str, dict],
    *,
    query_vector: Sequence[float] | None,
    chunk_index: dict[str, list[dict]],
    config: DocMatchConfig,
) -> dict:
    scored = []
    judgements = {}
    failed_names = []
    for name in names:
        record = records.get(name) or empty_freeform_record(unknown_reason="missing")
        if record.get("unknown_reason"):
            failed_names.append(name)
            judgements[name] = {
                "relevant": None,
                "relevance_score": None,
                "confidence": None,
                "reason": record.get("unknown_reason"),
                "unknown_reason": record.get("unknown_reason"),
                "low_relevant": None,
                "high_relevant": None,
            }
            continue
        judged = doc_match_judgement(
            query,
            record,
            query_vector=query_vector,
            chunks=chunk_index.get(name) or [],
            config=config,
        )
        judged["low_relevant"] = None
        judged["high_relevant"] = None
        judgements[name] = judged
        if judged.get("relevant"):
            scored.append((judged["relevance_score"], name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    predicted = [name for _, name in scored]
    return {
        "predicted": predicted,
        "judgements": judgements,
        "failed_names": failed_names,
        "cancelled": False,
        "usage": empty_usage(),
    }


def baseline_search_config():
    from tools.meaning_eval.freeform_index import FREEFORM_SEARCH_CONFIGS
    return next(
        config for config in FREEFORM_SEARCH_CONFIGS if config.name == "lex_1.00"
    )


def search_baseline_records(
    query: str,
    names: Sequence[str],
    records: dict[str, dict],
    *,
    query_vector: Sequence[float] | None,
    text_vectors: dict[str, Sequence[float]],
) -> dict:
    from tools.meaning_eval.freeform_index import search_freeform_records
    return search_freeform_records(
        query,
        names,
        records,
        query_vector=query_vector,
        text_vectors=text_vectors,
        config=baseline_search_config(),
    )
