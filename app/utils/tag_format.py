"""Display helpers for tags (always show with a leading #)."""

from __future__ import annotations

import re

_TAG_SPLIT = re.compile(r"\s*(?:,|、|&| and |と)\s*", re.I)


def normalize_tag(tag: str) -> str:
    """Store form: strip whitespace and a single leading #."""
    text = (tag or "").strip()
    while text.startswith("#"):
        text = text[1:].strip()
    return text


def parse_tag_names(raw: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Split a natural-language or list tag payload. Dedupes, preserves first order."""
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        parts = [str(item) for item in raw]
    else:
        text = str(raw or "").strip().strip("「」\"'")
        if not text:
            return ()
        parts = [piece for piece in _TAG_SPLIT.split(text) if piece.strip()] or [text]
    seen: set[str] = set()
    names: list[str] = []
    for part in parts:
        tag = normalize_tag(str(part).strip(" 「」\"'"))
        tag = re.sub(r"(?:だけ|のみ)$", "", tag).strip()
        if not tag or tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        names.append(tag)
    return tuple(names)


def format_tag(tag: str) -> str:
    """UI form: always '#name'."""
    base = normalize_tag(tag)
    if not base:
        return ""
    return f"#{base}"


def format_tags(tags: list[str] | None, *, empty: str = "-") -> str:
    """Join tags for captions / details lines."""
    if not tags:
        return empty
    parts = [format_tag(t) for t in tags if normalize_tag(t)]
    return ", ".join(parts) if parts else empty
