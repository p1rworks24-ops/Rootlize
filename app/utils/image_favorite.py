"""Image Favorite is an independent per-image attribute, not a Tag."""

from __future__ import annotations

from pathlib import Path

from app.utils.tag_format import normalize_tag

FAVORITE_TAG = "Favorite"
FILTER_ALL = "all"
FILTER_FAVORITES_ONLY = "favorites_only"
DEFAULT_FILTER_MODE = FILTER_ALL
VALID_FILTER_MODES = {FILTER_ALL, FILTER_FAVORITES_ONLY}


def normalize_filter_mode(mode: str | None) -> str:
    if mode in VALID_FILTER_MODES:
        return mode
    return DEFAULT_FILTER_MODE


def is_favorite_tag_name(tag: str | None) -> bool:
    return normalize_tag(tag or "") == FAVORITE_TAG


def visible_tags(tags: list[str] | None) -> list[str]:
    return [tag for tag in tags or [] if not is_favorite_tag_name(tag)]


def tags_include_favorite(tags: list[str] | None) -> bool:
    return any(is_favorite_tag_name(tag) for tag in tags or [])


def image_entry_is_favorite(entry: dict | None) -> bool:
    if not isinstance(entry, dict):
        return False
    if "favorite" in entry:
        return bool(entry.get("favorite"))
    return tags_include_favorite(entry.get("tags", []))


def image_is_favorite(metadata: dict | None, file_name: str) -> bool:
    images = (metadata or {}).get("images", {})
    return image_entry_is_favorite(images.get(file_name, {}))


def favorite_names(metadata: dict | None) -> set[str]:
    images = (metadata or {}).get("images", {})
    return {
        name
        for name, entry in images.items()
        if image_entry_is_favorite(entry)
    }


def copy_image_entry(entry: dict | None) -> dict:
    source = entry if isinstance(entry, dict) else {}
    copied = {"tags": visible_tags(source.get("tags", []))}
    if image_entry_is_favorite(source):
        copied["favorite"] = True
    return copied


def migrate_favorite_tag_metadata(metadata: dict | None) -> bool:
    """Move leftover Favorite tags onto the favorite attribute. Other tags stay."""
    if not isinstance(metadata, dict):
        return False
    images = metadata.get("images")
    if not isinstance(images, dict):
        return False
    changed = False
    for entry in images.values():
        if not isinstance(entry, dict):
            continue
        tags = list(entry.get("tags", []))
        had_favorite_tag = tags_include_favorite(tags)
        cleaned = visible_tags(tags)
        if cleaned != tags:
            entry["tags"] = cleaned
            changed = True
        if had_favorite_tag and not bool(entry.get("favorite")):
            entry["favorite"] = True
            changed = True
    return changed


def apply_favorite_filter(files: list[Path], metadata: dict | None, mode: str | None) -> list[Path]:
    if normalize_filter_mode(mode) != FILTER_FAVORITES_ONLY:
        return list(files)
    names = favorite_names(metadata)
    return [path for path in files if path.name in names]
