"""Frozen Semantic Index Hybrid used by product Meaning Search and eval.

precision_first band `posL1.01_posC0.45_negL0.33_negC0.32` never auto-accepts
Index positives (lex cannot reach 1.01). Clear-negatives skip Vision unless
rescued as uncertain. Rescues never mark positive.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.semantic_index.scoring import (
    GENERIC_MEDIA_TOKENS,
    PRODUCT_SEARCH_CONFIG,
    STOPWORDS,
    SearchConfig,
    combined_score,
    include_hit,
    incidental_text,
    lexical_text,
    tokenize,
)

DECISION_POSITIVE = "positive"
DECISION_NEGATIVE = "negative"
DECISION_UNCERTAIN = "uncertain"

# Clear-negative rescues. These do not auto-accept Index hits and do not
# retune the frozen Hybrid band. 0.45 was the Phase E analysis label for
# "high embedding" but matches a large share of the corpus, so it is not
# "sufficiently high" as a negative gate. 0.70 is the round floor of the
# previous matching FNs that had lex=0 and no token overlap (0.704, 0.717).
NEG_RESCUE_TXT_MIN = 0.70
WEAK_QUERY_TOKENS = frozenset({"application", "app", "software", "program"})
RESCUE_HIGH_TXT = "rescue_high_text_embedding"
RESCUE_TOKEN = "rescue_important_token_overlap"  # evaluated; not used (too broad)
RESCUE_COMPOUND = "rescue_compound_concept"
SENTINEL_BAND_NAMES = frozenset({"index_only", "vision_all"})


@dataclass(frozen=True)
class HybridBand:
    name: str
    pos_lex_min: float
    pos_combined_min: float
    neg_lex_max: float
    neg_combined_max: float
    require_include_hit_for_positive: bool = True
    require_not_hit_for_negative: bool = True


PRODUCT_HYBRID_BAND = HybridBand(
    name="posL1.01_posC0.45_negL0.33_negC0.32",
    pos_lex_min=1.01,
    pos_combined_min=0.45,
    neg_lex_max=0.33,
    neg_combined_max=0.32,
)
PRODUCT_HYBRID_POLICY = "precision_first"


def _rescue_token_forms(token: str) -> set[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        forms.add(token[:-1])
    if len(token) > 4 and token.endswith("ed"):
        forms.add(token[:-1])  # themed → theme
    return forms


def _index_token_set(record: dict | None) -> set[str]:
    if not record:
        return set()
    haystack = f"{lexical_text(record)} {incidental_text(record)}"
    tokens: set[str] = set()
    for token in tokenize(haystack):
        tokens.update(_rescue_token_forms(token))
    return tokens


def _compound_query_pairs(query: str) -> list[tuple[str, str]]:
    tokens = [token for token in tokenize(query) if token not in STOPWORDS]
    pairs = []
    for left, right in zip(tokens, tokens[1:]):
        if left in WEAK_QUERY_TOKENS or right in WEAK_QUERY_TOKENS:
            continue
        if left in GENERIC_MEDIA_TOKENS and right in GENERIC_MEDIA_TOKENS:
            continue
        pairs.append((left, right))
    return pairs


def clear_negative_rescues(
    judgement: dict | None,
    *,
    query: str = "",
    record: dict | None = None,
) -> tuple[str, ...]:
    """Reasons to withhold a Hybrid clear-negative. Never marks positive."""
    if not judgement or "lex" not in judgement:
        return ()
    reasons: list[str] = []
    txt = float(judgement.get("txt") or 0.0)
    if txt >= NEG_RESCUE_TXT_MIN:
        reasons.append(RESCUE_HIGH_TXT)
    index_tokens = _index_token_set(record)
    if index_tokens:
        for left, right in _compound_query_pairs(query):
            if (
                _rescue_token_forms(left) & index_tokens
                and _rescue_token_forms(right) & index_tokens
            ):
                reasons.append(RESCUE_COMPOUND)
                break
    return tuple(reasons)


def _band_negative(
    judgement: dict,
    band: HybridBand,
    search_config: SearchConfig,
) -> bool:
    lex = float(judgement.get("lex") or 0.0)
    txt = float(judgement.get("txt") or 0.0)
    img = float(judgement.get("img") or 0.0)
    combined = combined_score(img, txt, lex, search_config)
    hit = include_hit(img, txt, lex, search_config)
    negative = lex <= band.neg_lex_max and combined <= band.neg_combined_max
    if band.require_not_hit_for_negative:
        negative = negative and (not hit)
    return negative


def decide_hybrid(
    judgement: dict | None,
    band: HybridBand,
    search_config: SearchConfig,
    *,
    query: str = "",
    record: dict | None = None,
) -> str:
    if not judgement or judgement.get("unknown_reason"):
        return DECISION_UNCERTAIN
    if "lex" not in judgement:
        return DECISION_UNCERTAIN
    lex = float(judgement.get("lex") or 0.0)
    txt = float(judgement.get("txt") or 0.0)
    img = float(judgement.get("img") or 0.0)
    combined = combined_score(img, txt, lex, search_config)
    hit = include_hit(img, txt, lex, search_config)
    positive = lex >= band.pos_lex_min and combined >= band.pos_combined_min
    if band.require_include_hit_for_positive:
        positive = positive and hit
    if positive:
        return DECISION_POSITIVE
    negative = lex <= band.neg_lex_max and combined <= band.neg_combined_max
    if band.require_not_hit_for_negative:
        negative = negative and (not hit)
    if negative:
        if (
            band.name not in SENTINEL_BAND_NAMES
            and clear_negative_rescues(judgement, query=query, record=record)
        ):
            return DECISION_UNCERTAIN
        return DECISION_NEGATIVE
    return DECISION_UNCERTAIN


def uncertain_reason(
    judgement: dict | None,
    band: HybridBand,
    search_config: SearchConfig,
    *,
    query: str = "",
    record: dict | None = None,
) -> str:
    if not judgement or judgement.get("unknown_reason"):
        return "missing_or_unknown_index"
    if "lex" not in judgement:
        return "missing_or_unknown_index"
    if (
        band.name not in SENTINEL_BAND_NAMES
        and _band_negative(judgement, band, search_config)
    ):
        rescues = clear_negative_rescues(judgement, query=query, record=record)
        if rescues:
            return rescues[0]
    lex = float(judgement.get("lex") or 0.0)
    txt = float(judgement.get("txt") or 0.0)
    img = float(judgement.get("img") or 0.0)
    combined = combined_score(img, txt, lex, search_config)
    hit = include_hit(img, txt, lex, search_config)
    if hit and lex < band.pos_lex_min:
        return "index_hit_not_auto_positive"
    if hit and combined < band.pos_combined_min:
        return "index_hit_weak_combined"
    if (not hit) and lex > band.neg_lex_max:
        return "near_miss_lexical"
    if (not hit) and combined > band.neg_combined_max:
        return "near_miss_combined"
    if hit:
        return "borderline_positive"
    return "borderline_negative"


def decide_product_hybrid(
    judgement: dict | None,
    *,
    query: str = "",
    record: dict | None = None,
) -> str:
    """Product Meaning Search entry. Frozen band + hybrid_v1 scoring."""
    return decide_hybrid(
        judgement,
        PRODUCT_HYBRID_BAND,
        PRODUCT_SEARCH_CONFIG,
        query=query,
        record=record,
    )
