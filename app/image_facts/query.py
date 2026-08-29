"""Strip library-search wrappers from Meaning Search queries.

Ask AI / Automation often send “search for X images from this folder”.
Those wrappers are request phrasing, not extra visual conditions. Ranking
and matching should use the named target only.
"""

from __future__ import annotations

import re

from app.image_facts.format import normalize_condition_label

_LEADIN_RE = re.compile(
    r"^(?:please\s+)?(?:search\s+for|find(?:\s+me)?|show\s+me|look\s+for|"
    r"get\s+me|list)\s+",
    re.IGNORECASE,
)
_JA_LEADIN_RE = re.compile(r"^(?:探して|検索して|見つけて|表示して)\s*")
_SCOPE_RE = re.compile(
    r"\s+(?:from|in)\s+(?:this|the\s+current)\s+folder\s*$",
    re.IGNORECASE,
)
_JA_SCOPE_RE = re.compile(r"(?:\s*)(?:このフォルダ(?:から|の中|内)?)\s*$")
_OF_COLLECTION_RE = re.compile(
    r"^(?:images|screenshots|photos|pictures|pics)\s+"
    r"(?:of|showing|with|containing)\s+",
    re.IGNORECASE,
)
_TRAILING_COLLECTION_RE = re.compile(
    r"\s+(?:images|screenshots|photos|pictures|pics)\s*$",
    re.IGNORECASE,
)
_JA_TRAILING_RE = re.compile(r"(?:の)?画像(?:を(?:探して|検索して|見つけて|表示して)?)?\s*$")
_LEADING_ARTICLE_RE = re.compile(r"^(?:an?|the)\s+", re.IGNORECASE)

WEAK_TARGETS = frozenset({
    "",
    "all",
    "related",
    "these",
    "those",
    "my",
    "some",
    "the",
    "a",
    "an",
    "this",
    "current",
    "folder",
})

SEARCH_WRAPPER_LABELS = frozenset({
    "images",
    "screenshots",
    "photos",
    "pictures",
    "pics",
    "search",
    "find",
    "show me",
    "look for",
    "this folder",
    "current folder",
    "the current folder",
    "folder",
})


def meaning_query_target(query: str) -> str:
    """Return the visual target of a library-search request.

    Wrappers such as “search for”, trailing “images”, and “from this folder”
    are removed. Compound product names such as “screenshot manager” stay.
    If stripping would leave only a generic remainder, the original text is
    kept.
    """
    text = " ".join(str(query or "").strip().split())
    if not text:
        return ""
    original = text
    changed = True
    while changed:
        changed = False
        for pattern in (
            _LEADIN_RE,
            _JA_LEADIN_RE,
            _SCOPE_RE,
            _JA_SCOPE_RE,
            _OF_COLLECTION_RE,
            _TRAILING_COLLECTION_RE,
            _JA_TRAILING_RE,
        ):
            stripped = pattern.sub("", text).strip()
            if stripped != text:
                text = stripped
                changed = True
        article = _LEADING_ARTICLE_RE.sub("", text).strip()
        if article != text:
            text = article
            changed = True
    target = " ".join(text.split())
    if normalize_condition_label(target) in WEAK_TARGETS:
        return original
    return target or original


def is_search_wrapper_condition(label: str, query: str) -> bool:
    """True when a listed condition is request phrasing, not a visual target."""
    label_n = normalize_condition_label(label)
    if label_n not in SEARCH_WRAPPER_LABELS:
        return False
    target_n = normalize_condition_label(meaning_query_target(query))
    if not target_n:
        return False
    if label_n == target_n or label_n in target_n.split():
        return False
    return True
