"""Thumbnail / list view modes for the Images page."""

DEFAULT_THUMBNAIL_MODE = "small"

# small = former details (list), medium/large = icon grids with caption metadata
VALID_THUMBNAIL_MODES = {"large", "medium", "small"}

# (mode, i18n message key)
THUMBNAIL_MODE_OPTIONS = [
    ("large", "view.large"),
    ("medium", "view.medium"),
    ("small", "view.small"),
]

# IconMode gap between cards — same with/without Group By (no fixed grid).
THUMBNAIL_LIST_SPACING = 6

# icon_size, grid_width, grid_height
# Grid height leaves room for full wrapped filename (+ tags/date on Images).
# Spacing between cells is controlled by QListWidget.setSpacing (constant).
THUMBNAIL_MODE_SIZES = {
    # The compact default follows the dense reference gallery while retaining
    # larger choices for inspection-heavy workflows.
    "large": (120, 176, 216),
    "medium": (88, 140, 174),
    "small": (64, 100, 128),
}

# Map legacy "details" → "small"
_LEGACY_MODE_MAP = {
    "details": "small",
}


def normalize_thumbnail_mode(mode: str | None) -> str:
    if mode in _LEGACY_MODE_MAP:
        mode = _LEGACY_MODE_MAP[mode]
    if mode in VALID_THUMBNAIL_MODES:
        return mode
    return DEFAULT_THUMBNAIL_MODE


def thumbnail_mode_labels() -> list[tuple[str, str]]:
    """Return (mode, localized label) pairs for UI menus."""
    from app.i18n import t

    return [(mode, t(key)) for mode, key in THUMBNAIL_MODE_OPTIONS]


def is_list_mode(mode: str | None) -> bool:
    """Legacy helper: all view modes use icon cards now."""
    return False


def soft_wrap_filename(name: str) -> str:
    """Insert zero-width spaces so long filenames can wrap in IconMode."""
    out: list[str] = []
    for i, ch in enumerate(name):
        out.append(ch)
        if ch in ("_", "-", ".", " ") and i < len(name) - 1:
            out.append("\u200b")
        elif (i + 1) % 12 == 0 and i < len(name) - 1:
            out.append("\u200b")
    return "".join(out)
