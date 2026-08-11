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


def normalize_group_by(group_by: str | None) -> str:
    """Return a valid group_by value, falling back to the default."""
    if group_by in VALID_GROUP_BY:
        return group_by
    return DEFAULT_GROUP_BY


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
    unanalyzed_names: set[str] | None = None,
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

    if mode == GROUP_BY_NONE:
        return [("", sort_png_files(files, sort_mode))]

    if mode == GROUP_BY_DATE:
        buckets: dict[str, list[Path]] = {}
        for path in files:
            label = format_date_group_label(path)
            buckets.setdefault(label, []).append(path)

        # Newest date first
        ordered_keys = sorted(buckets.keys(), reverse=True)
        return [
            (key, sort_png_files(buckets[key], sort_mode)) for key in ordered_keys
        ]

    if mode == GROUP_BY_TAG:
        tag_buckets: dict[str, list[Path]] = {}
        no_tag: list[Path] = []

        for path in files:
            tags = list(images_meta.get(path.name, {}).get("tags", []))
            if not tags:
                no_tag.append(path)
                continue
            for tag in tags:
                tag_buckets.setdefault(tag, []).append(path)

        ordered_tags = sorted(tag_buckets.keys(), key=str.lower)
        result: list[tuple[str, list[Path]]] = [
            (tag, sort_png_files(tag_buckets[tag], sort_mode)) for tag in ordered_tags
        ]
        if no_tag:
            result.append((NO_TAG_GROUP_KEY, sort_png_files(no_tag, sort_mode)))
        return result

    if mode == GROUP_BY_ANALYSIS:
        pending = unanalyzed_names or set()
        analyzed = [path for path in files if path.name not in pending]
        unanalyzed = [path for path in files if path.name in pending]
        result = []
        if unanalyzed:
            result.append(
                (UNANALYZED_GROUP_KEY, sort_png_files(unanalyzed, sort_mode))
            )
        if analyzed:
            result.append((ANALYZED_GROUP_KEY, sort_png_files(analyzed, sort_mode)))
        return result

    # Future modes fall back to flat list
    return [("", sort_png_files(files, sort_mode))]
