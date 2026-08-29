"""Local Semantic Index scoring shared by product Meaning Search and eval.

Thresholds are the Phase E frozen hybrid_v1 search config. Hold-out must
not retune these values.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset({
    "a", "an", "the", "of", "with", "and", "or", "in", "on", "for", "to",
    "from", "at", "by", "is", "are",
})
GENERIC_MEDIA_TOKENS = frozenset({
    "screenshot", "photo", "photograph", "image", "picture", "pictures",
    "screen", "capture", "window",
})


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def token_forms(token: str) -> set[str]:
    forms = {token}
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        forms.add(token[:-1])
    return forms


def content_tokens(query: str) -> list[str]:
    tokens = [token for token in tokenize(query) if token not in STOPWORDS]
    distinctive = [token for token in tokens if token not in GENERIC_MEDIA_TOKENS]
    if distinctive:
        return distinctive
    return tokens


def primary_terms(record: dict) -> list[str]:
    terms = []
    for name in (
        "searchable_concepts",
        "ui_interface_concepts",
        "objects_entities",
        "visible_activities",
        "visual_attributes",
    ):
        terms.extend(str(item) for item in (record.get(name) or []) if item)
    for name in ("visual_summary", "scene_environment"):
        value = record.get(name)
        if value:
            terms.append(str(value))
    return terms


def lexical_text(record: dict) -> str:
    return " ".join(primary_terms(record)).lower()


def incidental_text(record: dict) -> str:
    return str(record.get("incidental_notes") or "").lower()


def _has_phrase(needle: str, haystack: str) -> bool:
    needle_tokens = tokenize(needle)
    hay_tokens = tokenize(haystack)
    if not needle_tokens or not hay_tokens:
        return False
    if needle_tokens == hay_tokens:
        return True
    width = len(needle_tokens)
    for index in range(len(hay_tokens) - width + 1):
        if hay_tokens[index:index + width] == needle_tokens:
            return True
    return False


def _coverage(query_tokens: Sequence[str], haystack_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    hits = 0
    for token in query_tokens:
        forms = token_forms(token)
        if forms & haystack_tokens:
            hits += 1
    return hits / len(query_tokens)


def lexical_score(query: str, record: dict) -> float:
    if record.get("unknown_reason"):
        return 0.0
    query_l = query.lower().strip()
    if not query_l:
        return 0.0
    concepts = [
        str(item).lower()
        for item in (
            list(record.get("searchable_concepts") or [])
            + list(record.get("ui_interface_concepts") or [])
            + list(record.get("objects_entities") or [])
        )
        if item
    ]
    primary = lexical_text(record)
    primary_token_set: set[str] = set()
    for token in tokenize(primary):
        primary_token_set.update(token_forms(token))
    incidental_token_set: set[str] = set()
    for token in tokenize(incidental_text(record)):
        incidental_token_set.update(token_forms(token))
    phrase = 0.0
    for concept in concepts:
        if len(concept) < 3:
            continue
        if _has_phrase(query_l, concept) or _has_phrase(concept, query_l):
            phrase = 1.0
            break
    if phrase == 0.0 and len(query_l) >= 4 and _has_phrase(query_l, primary):
        phrase = 0.85
    tokens = content_tokens(query_l)
    if not tokens:
        return 0.0
    coverage = _coverage(tokens, primary_token_set)
    incidental_only = _coverage(
        tokens,
        incidental_token_set - primary_token_set,
    )
    if phrase == 0.0 and coverage < 0.34:
        return 0.0
    score = max(phrase, coverage)
    if incidental_only > coverage:
        score *= 0.4
    return min(1.0, score)


def cosine(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if not left or not right:
        return 0.0
    return float(math.fsum(a * b for a, b in zip(left, right)))


@dataclass(frozen=True)
class SearchConfig:
    name: str
    lex_include: float
    lex_support: float
    txt_min: float
    img_min: float
    combined_min: float
    img_weight: float = 0.30
    txt_weight: float = 0.30
    lex_weight: float = 0.40


PRODUCT_SEARCH_CONFIG = SearchConfig("hybrid_v1", 0.50, 0.34, 0.22, 0.18, 0.0)
PRIMARY_SEARCH = PRODUCT_SEARCH_CONFIG.name


def combined_score(img: float, txt: float, lex: float, config: SearchConfig) -> float:
    return (
        config.img_weight * img
        + config.txt_weight * txt
        + config.lex_weight * lex
    )


def include_hit(img: float, txt: float, lex: float, config: SearchConfig) -> bool:
    if lex >= config.lex_include:
        return True
    if (
        lex >= config.lex_support
        and txt >= config.txt_min
        and img >= config.img_min
    ):
        return True
    if config.combined_min > 0 and combined_score(img, txt, lex, config) >= config.combined_min:
        return True
    return False


def index_judgement(
    query: str,
    record: dict,
    *,
    query_vector: Sequence[float] | None,
    image_vector: Sequence[float] | None,
    text_vector: Sequence[float] | None,
    config: SearchConfig = PRODUCT_SEARCH_CONFIG,
) -> dict:
    """Build the lex/txt/img payload used by Hybrid decide_hybrid."""
    if record.get("unknown_reason"):
        return {
            "relevant": None,
            "relevance_score": None,
            "confidence": None,
            "reason": record.get("unknown_reason"),
            "unknown_reason": record.get("unknown_reason"),
        }
    lex = lexical_score(query, record)
    img = cosine(query_vector, image_vector)
    txt = cosine(query_vector, text_vector)
    combined = combined_score(img, txt, lex, config)
    return {
        "relevant": include_hit(img, txt, lex, config),
        "relevance_score": combined,
        "confidence": lex,
        "reason": f"lex={lex:.3f} txt={txt:.3f} img={img:.3f}",
        "lex": lex,
        "txt": txt,
        "img": img,
    }
