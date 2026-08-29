"""Group-by modes for the Images list (display only; does not move files).

Stored in project.json as display.group_by.
Future modes (AI category, OCR, etc.) can be added to VALID_GROUP_BY / GROUP_BY_OPTIONS
and handled inside build_groups().
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.utils.sort_order import sort_png_files

GROUP_BY_NONE = "none"
GROUP_BY_DATE = "date"
GROUP_BY_TAG = "tag"
GROUP_BY_ANALYSIS = "analysis"

DEFAULT_GROUP_BY = GROUP_BY_NONE

# Stamped onto project.json display after leftover old-UI prefs are migrated.
# Projects without this key are treated as pre-new-UI and reset to defaults.
DISPLAY_SCHEMA_KEY = "display_schema"
DISPLAY_SCHEMA_VERSION = 1

VALID_GROUP_BY = {
    GROUP_BY_NONE,
    GROUP_BY_DATE,
    GROUP_BY_TAG,
    GROUP_BY_ANALYSIS,
}

# (value stored in project.json, i18n key)
GROUP_BY_OPTIONS = [
    (GROUP_BY_NONE, "group_by.none"),
    (GROUP_BY_DATE, "group_by.date"),
    (GROUP_BY_TAG, "group_by.tag"),
    (GROUP_BY_ANALYSIS, "group_by.analysis"),
]

# Internal key for images with no tags (label resolved via i18n when building UI)
NO_TAG_GROUP_KEY = "__no_tag__"
ANALYZED_GROUP_KEY = "__analyzed__"
UNANALYZED_GROUP_KEY = "__unanalyzed__"
SEMANTIC_MISSING_GROUP_KEY = "__semantic_missing__"
SEMANTIC_STALE_GROUP_KEY = "__semantic_stale__"
SEMANTIC_FAILED_GROUP_KEY = "__semantic_failed__"
SEMANTIC_CORRUPT_GROUP_KEY = "__semantic_corrupt__"
OCR_MISSING_GROUP_KEY = "__ocr_missing__"
PROCESSING_GROUP_KEY = "__processing__"


def normalize_group_by(group_by: str | None) -> str:
    """Return a valid group_by value, falling back to the default."""
    if group_by in VALID_GROUP_BY:
        return group_by
    return DEFAULT_GROUP_BY


def migrate_legacy_display(display: dict | None) -> tuple[dict, bool]:
    """Move leftover old-UI display prefs to the new defaults once.

    Old Images UI persisted group_by=date as a common leftover. The new
    workspace default is none. After display_schema is stamped, an explicit
    user choice is kept.
    """
    out = dict(display or {})
    if out.get(DISPLAY_SCHEMA_KEY) == DISPLAY_SCHEMA_VERSION:
        return out, False
    changed = False
    if out.get("group_by") != DEFAULT_GROUP_BY:
        out["group_by"] = DEFAULT_GROUP_BY
        changed = True
    if out.get(DISPLAY_SCHEMA_KEY) != DISPLAY_SCHEMA_VERSION:
        out[DISPLAY_SCHEMA_KEY] = DISPLAY_SCHEMA_VERSION
        changed = True
    return out, changed


def group_by_option_labels(*, include_analysis: bool = False) -> list[tuple[str, str]]:
    """Return (mode, localized label) pairs for UI combos."""
    from app.i18n import t

    return [
        (mode, t(key))
        for mode, key in GROUP_BY_OPTIONS
        if include_analysis or mode != GROUP_BY_ANALYSIS
    ]


def format_date_group_label(file_path: Path) -> str:
    """Date heading from file mtime, e.g. 2026/07/15."""
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
    return mtime.strftime("%Y/%m/%d")


def build_groups(
    files: list[Path],
    group_by: str,
    metadata: dict,
    sort_mode: str,
    unanalyzed_names: set[str] | dict[str, str] | None = None,
) -> list[tuple[str, list[Path]]]:
    """
    Build ordered (group_key, files) sections for the list.

    - none: one anonymous section with all files sorted
    - date: one section per calendar day (newest day first); sort within each day
    - tag: one section per tag (A–Z), then No Tag; images with multiple tags
      appear in each matching section (display only)

    group_key for tags is the tag name, or NO_TAG_GROUP_KEY for untagged images.
    For date, group_key is the 'YYYY/MM/DD' label. For none, group_key is ''.
    """
    mode = normalize_group_by(group_by)
    images_meta = metadata.get("images", {}) if metadata else {}
    from app.utils.image_favorite import (
        favorite_names as favorite_file_names,
        visible_tags,
    )

    fav_names = favorite_file_names(metadata)

    if mode == GROUP_BY_NONE:
        return [("", sort_png_files(files, sort_mode, favorite_names=fav_names))]

    if mode == GROUP_BY_DATE:
        buckets: dict[str, list[Path]] = {}
        for path in files:
            label = format_date_group_label(path)
            buckets.setdefault(label, []).append(path)

        # Newest date first
        ordered_keys = sorted(buckets.keys(), reverse=True)
        return [
            (key, sort_png_files(buckets[key], sort_mode, favorite_names=fav_names)) for key in ordered_keys
        ]

    if mode == GROUP_BY_TAG:
        tag_buckets: dict[str, list[Path]] = {}
        no_tag: list[Path] = []

        for path in files:
            tags = visible_tags(list(images_meta.get(path.name, {}).get("tags", [])))
            if not tags:
                no_tag.append(path)
                continue
            for tag in tags:
                tag_buckets.setdefault(tag, []).append(path)

        ordered_tags = sorted(tag_buckets.keys(), key=str.lower)
        result: list[tuple[str, list[Path]]] = [
            (tag, sort_png_files(tag_buckets[tag], sort_mode, favorite_names=fav_names)) for tag in ordered_tags
        ]
        if no_tag:
            result.append((NO_TAG_GROUP_KEY, sort_png_files(no_tag, sort_mode, favorite_names=fav_names)))
        return result

    if mode == GROUP_BY_ANALYSIS:
        legacy_pending = not isinstance(unanalyzed_names, dict)
        if isinstance(unanalyzed_names, dict):
            state_by_name = unanalyzed_names
        else:
            pending = unanalyzed_names or set()
            state_by_name = {name: "missing_embedding" for name in pending}
        group_for_state = {
            "missing_embedding": (
                UNANALYZED_GROUP_KEY if legacy_pending else SEMANTIC_MISSING_GROUP_KEY
            ),
            "modified": SEMANTIC_MISSING_GROUP_KEY,
            "stale_model": SEMANTIC_MISSING_GROUP_KEY,
            "failed": SEMANTIC_FAILED_GROUP_KEY,
            "corrupt": SEMANTIC_FAILED_GROUP_KEY,
            "semantic_failed": SEMANTIC_FAILED_GROUP_KEY,
            "ocr_missing": OCR_MISSING_GROUP_KEY,
            "ocr_issue": OCR_MISSING_GROUP_KEY,
            "ocr_pending": PROCESSING_GROUP_KEY,
            "pending": PROCESSING_GROUP_KEY,
            "running": PROCESSING_GROUP_KEY,
            "processing": PROCESSING_GROUP_KEY,
        }
        buckets: dict[str, list[Path]] = {}
        analyzed = []
        for path in files:
            group = group_for_state.get(state_by_name.get(path.name, ""))
            if group is None:
                analyzed.append(path)
            else:
                buckets.setdefault(group, []).append(path)
        result = []
        for key in (
            SEMANTIC_FAILED_GROUP_KEY,
            PROCESSING_GROUP_KEY,
            OCR_MISSING_GROUP_KEY,
            SEMANTIC_MISSING_GROUP_KEY,
            UNANALYZED_GROUP_KEY,
        ):
            if buckets.get(key):
                result.append((key, sort_png_files(buckets[key], sort_mode, favorite_names=fav_names)))
        if analyzed:
            result.append((ANALYZED_GROUP_KEY, sort_png_files(analyzed, sort_mode, favorite_names=fav_names)))
        return result

    # Future modes fall back to flat list
    return [("", sort_png_files(files, sort_mode, favorite_names=fav_names))]
