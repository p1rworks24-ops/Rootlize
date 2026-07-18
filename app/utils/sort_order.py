from pathlib import Path

# Values stored in project.json display.sort_mode
SORT_MODIFIED_DESC = "modified_desc"
SORT_MODIFIED_ASC = "modified_asc"
SORT_FILENAME_ASC = "filename_asc"
SORT_FILENAME_DESC = "filename_desc"

DEFAULT_SORT_MODE = SORT_MODIFIED_DESC

VALID_SORT_MODES = {
    SORT_MODIFIED_DESC,
    SORT_MODIFIED_ASC,
    SORT_FILENAME_ASC,
    SORT_FILENAME_DESC,
}

# (sort_mode value, i18n message key)
SORT_OPTIONS = [
    (SORT_MODIFIED_DESC, "sort.modified_desc"),
    (SORT_MODIFIED_ASC, "sort.modified_asc"),
    (SORT_FILENAME_ASC, "sort.filename_asc"),
    (SORT_FILENAME_DESC, "sort.filename_desc"),
]


def normalize_sort_mode(sort_mode: str | None) -> str:
    """Return a valid sort mode, falling back to the default."""
    if sort_mode in VALID_SORT_MODES:
        return sort_mode
    return DEFAULT_SORT_MODE


def sort_option_labels() -> list[tuple[str, str]]:
    """Return (mode, localized label) pairs for UI combos."""
    from app.i18n import t

    return [(mode, t(key)) for mode, key in SORT_OPTIONS]


def sort_png_files(files: list[Path], sort_mode: str) -> list[Path]:
    """Return PNG paths sorted by the selected mode (does not rename files)."""
    mode = normalize_sort_mode(sort_mode)

    if mode == SORT_MODIFIED_ASC:
        return sorted(files, key=lambda p: p.stat().st_mtime)

    if mode == SORT_FILENAME_ASC:
        return sorted(files, key=lambda p: p.name.lower())

    if mode == SORT_FILENAME_DESC:
        return sorted(files, key=lambda p: p.name.lower(), reverse=True)

    # SORT_MODIFIED_DESC (default)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


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
