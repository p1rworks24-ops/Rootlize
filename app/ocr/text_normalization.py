"""Stable search normalization for OCR index data."""

from __future__ import annotations

import re
import unicodedata

NORMALIZATION_VERSION = 1


def normalize_search_text(value: str | None) -> str:
    """NFKC/case-fold text and collapse whitespace without removing symbols."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_compact_text(value: str | None) -> str:
    """Initial safe compact form; intentionally identical to basic normalization."""
    return normalize_search_text(value)
