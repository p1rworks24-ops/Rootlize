"""Display helpers for tags (always show with a leading #)."""

from __future__ import annotations


def normalize_tag(tag: str) -> str:
    """Store form: strip whitespace and a single leading #."""
    text = (tag or "").strip()
    while text.startswith("#"):
        text = text[1:].strip()
    return text


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
