from pathlib import Path

# Values stored in project.json display.sort_mode
SORT_MODIFIED_DESC = "modified_desc"
SORT_MODIFIED_ASC = "modified_asc"
SORT_FILENAME_ASC = "filename_asc"
SORT_FILENAME_DESC = "filename_desc"
SORT_FAVORITES_FIRST = "favorites_first"

DEFAULT_SORT_MODE = SORT_MODIFIED_DESC

VALID_SORT_MODES = {
    SORT_MODIFIED_DESC,
    SORT_MODIFIED_ASC,
    SORT_FILENAME_ASC,
    SORT_FILENAME_DESC,
    SORT_FAVORITES_FIRST,
}

# (sort_mode value, i18n message key)
SORT_OPTIONS = [
    (SORT_MODIFIED_DESC, "sort.modified_desc"),
    (SORT_MODIFIED_ASC, "sort.modified_asc"),
    (SORT_FILENAME_ASC, "sort.filename_asc"),
    (SORT_FILENAME_DESC, "sort.filename_desc"),
    (SORT_FAVORITES_FIRST, "sort.favorites_first"),
]

# Images page Sort combo: Date/Tags/Favorites replace Group By + Filter.
IMAGES_SORT_DATE = "date"
IMAGES_SORT_TAG = "tag"
IMAGES_SORT_FAVORITES = "favorites"
DEFAULT_IMAGES_SORT = IMAGES_SORT_DATE
IMAGES_SORT_KEY = "images_sort"
IMAGES_SORT_OPTIONS = [
    (IMAGES_SORT_DATE, "sort.date"),
    (IMAGES_SORT_TAG, "sort.tags"),
    (IMAGES_SORT_FAVORITES, "sort.favorites"),
    (SORT_FILENAME_ASC, "sort.filename_asc"),
    (SORT_FILENAME_DESC, "sort.filename_desc"),
]
VALID_IMAGES_SORT_MODES = {mode for mode, _key in IMAGES_SORT_OPTIONS}
_IMAGES_SORT_LEGACY = {
    SORT_MODIFIED_DESC: IMAGES_SORT_DATE,
    SORT_MODIFIED_ASC: IMAGES_SORT_DATE,
    SORT_FAVORITES_FIRST: IMAGES_SORT_FAVORITES,
    "date_group": IMAGES_SORT_DATE,
    "tag_group": IMAGES_SORT_TAG,
}


def normalize_sort_mode(sort_mode: str | None) -> str:
    """Return a valid sort mode, falling back to the default."""
    if sort_mode in VALID_SORT_MODES:
        return sort_mode
    return DEFAULT_SORT_MODE


def sort_option_labels() -> list[tuple[str, str]]:
    """Return (mode, localized label) pairs for UI combos."""
    from app.i18n import t

    return [(mode, t(key)) for mode, key in SORT_OPTIONS]


def images_sort_option_labels() -> list[tuple[str, str]]:
    from app.i18n import t

    return [(mode, t(key)) for mode, key in IMAGES_SORT_OPTIONS]


def normalize_images_sort(mode: str | None) -> str:
    if mode in _IMAGES_SORT_LEGACY:
        return _IMAGES_SORT_LEGACY[mode]
    if mode in VALID_IMAGES_SORT_MODES:
        return mode
    return DEFAULT_IMAGES_SORT


def expand_images_sort(arrangement: str) -> tuple[str, str, str]:
    """Map Images Sort combo → (file sort, group_by, filter_mode)."""
    mode = normalize_images_sort(arrangement)
    if mode == IMAGES_SORT_DATE:
        return SORT_MODIFIED_DESC, "date", "all"
    if mode == IMAGES_SORT_TAG:
        return SORT_MODIFIED_DESC, "tag", "all"
    if mode == IMAGES_SORT_FAVORITES:
        return SORT_MODIFIED_DESC, "none", "favorites_only"
    if mode == SORT_FILENAME_DESC:
        return SORT_FILENAME_DESC, "none", "all"
    return SORT_FILENAME_ASC, "none", "all"


def arrangement_from_display(display: dict | None) -> str:
    """Infer Images Sort combo value from persisted display prefs."""
    data = display or {}
    stored = data.get(IMAGES_SORT_KEY)
    if stored in VALID_IMAGES_SORT_MODES:
        return stored
    sort_mode = data.get("sort_mode")
    if sort_mode in VALID_IMAGES_SORT_MODES:
        return sort_mode
    if data.get("filter_mode") == "favorites_only" or sort_mode == SORT_FAVORITES_FIRST:
        return IMAGES_SORT_FAVORITES
    group_by = data.get("group_by")
    if group_by == "tag":
        return IMAGES_SORT_TAG
    if group_by == "date":
        return IMAGES_SORT_DATE
    if sort_mode in _IMAGES_SORT_LEGACY:
        return _IMAGES_SORT_LEGACY[sort_mode]
    return DEFAULT_IMAGES_SORT


def sort_png_files(
    files: list[Path],
    sort_mode: str,
    *,
    favorite_names: set[str] | None = None,
) -> list[Path]:
    """Return PNG paths sorted by the selected mode (does not rename files)."""
    mode = normalize_sort_mode(sort_mode)
    ranked = files
    if mode == SORT_MODIFIED_ASC:
        ranked = sorted(files, key=lambda p: p.stat().st_mtime)
    elif mode == SORT_FILENAME_ASC:
        ranked = sorted(files, key=lambda p: p.name.lower())
    elif mode == SORT_FILENAME_DESC:
        ranked = sorted(files, key=lambda p: p.name.lower(), reverse=True)
    else:
        # SORT_MODIFIED_DESC and SORT_FAVORITES_FIRST share newest-first ranking.
        ranked = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    if mode == SORT_FAVORITES_FIRST:
        names = favorite_names or set()
        favorites = [path for path in ranked if path.name in names]
        others = [path for path in ranked if path.name not in names]
        return favorites + others
    return ranked


def should_insert_before(new_path: Path, existing_path: Path, sort_mode: str) -> bool:
    """True if new_path should appear before existing_path under sort_mode."""
    mode = normalize_sort_mode(sort_mode)

    if mode == SORT_FILENAME_ASC:
        return new_path.name.lower() < existing_path.name.lower()
    if mode == SORT_FILENAME_DESC:
        return new_path.name.lower() > existing_path.name.lower()
    if mode == SORT_MODIFIED_ASC:
        return new_path.stat().st_mtime < existing_path.stat().st_mtime

    # newest first
    return new_path.stat().st_mtime > existing_path.stat().st_mtime
