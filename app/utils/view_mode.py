"""Thumbnail / list view modes for the Images page."""

DEFAULT_THUMBNAIL_MODE = "large"
DEFAULT_GALLERY_LAYOUT = "grid"

# small/medium/large = icon grids; list is a compact filename-first row
VALID_THUMBNAIL_MODES = {"large", "medium", "small"}
VALID_GALLERY_LAYOUTS = {"grid", "list"}

# (mode, i18n message key)
THUMBNAIL_MODE_OPTIONS = [
    ("large", "view.large"),
    ("medium", "view.medium"),
    ("small", "view.small"),
]

# IconMode gap between cards — same with/without Group By (no fixed grid).
THUMBNAIL_LIST_SPACING = 10
# Matches QListWidget#screenshotList[captionMode="icon"]::item { margin: 2px }
ICON_ITEM_MARGIN = 2
GRID_VIEWPORT_SAFETY = 2

# Comfortable min card width: filename / tags / date / Favorite star stay readable,
# and a standard desktop Images workspace (nav expanded, preview at usual width)
# lands on 5 columns. There is no max column cap — extra width adds columns
# instead of stretching a card far past this size.
GRID_CARD_MIN_WIDTH = 204

# icon_size, min grid_width, grid_height
# Height includes a reserved filename band. Media is sized from leftover space.
# Columns come from compute_responsive_grid(available, min_width); no max_columns.
THUMBNAIL_MODE_SIZES = {
    "large": (160, GRID_CARD_MIN_WIDTH, 198),
    "medium": (148, 192, 184),
    "small": (136, 180, 172),
    "list": (32, 520, 48),
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


def normalize_gallery_layout(mode: str | None) -> str:
    if mode in VALID_GALLERY_LAYOUTS:
        return mode
    return DEFAULT_GALLERY_LAYOUT


def thumbnail_mode_labels() -> list[tuple[str, str]]:
    """Return (mode, localized label) pairs for UI menus."""
    from app.i18n import t

    return [(mode, t(key)) for mode, key in THUMBNAIL_MODE_OPTIONS]


def is_list_mode(mode: str | None) -> bool:
    return normalize_gallery_layout(mode) == "list"


def compute_responsive_grid(
    viewport_width: int,
    min_card_width: int,
    *,
    gap: int = THUMBNAIL_LIST_SPACING,
    item_margin: int = ICON_ITEM_MARGIN,
    safety: int = GRID_VIEWPORT_SAFETY,
    reserve_scrollbar: int = 0,
) -> tuple[int, int, int]:
    """Fit as many min-width cards as possible, then stretch them to the row.

    Column count is not capped. A wider gallery adds another column once
    another min-width card plus spacing fits; a narrower gallery drops
    columns the same way.

    Returns (columns, card_width, header_width). header_width is the full
    row that still fits after item margins, so a group header sits alone
    without growing a horizontal scroll range.
    """
    available = max(1, int(viewport_width) - safety - max(0, int(reserve_scrollbar)))
    # IconMode places each cell at (card + item margins + leading spacing).
    cell_extra = 2 * item_margin + gap
    stride = max(int(min_card_width) + cell_extra, 1)
    columns = max(1, available // stride)
    card_width = max(1, (available - columns * cell_extra) // columns)
    header_width = max(1, available - cell_extra)
    return columns, card_width, header_width


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
