"""Search-only text normalization for the OCR PoC."""

from __future__ import annotations

import re
import unicodedata


def normalize_search_text(value: str) -> str:
    """Normalize width, case, line breaks, and repeated whitespace."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def parse_keywords(value: str | None) -> list[str]:
    """Parse a comma-separated list while preserving user-facing spellings."""
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        keyword = part.strip()
        key = normalize_search_text(keyword)
        if keyword and key and key not in seen:
            seen.add(key)
            result.append(keyword)
    return result


def match_keywords(full_text: str, keywords: list[str]) -> dict[str, bool]:
    haystack = normalize_search_text(full_text)
    return {
        keyword: normalize_search_text(keyword) in haystack
        for keyword in keywords
    }
