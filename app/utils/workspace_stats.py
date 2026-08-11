"""Aggregate image counts and PNG disk usage by folder or tag (Home dashboard)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.metadata_service import MetadataService
from app.utils.workspace import iter_image_dirs, list_folder_names, resolve_screenshot_root

# Dark gray for the Tags-view "No tags" bar
NO_TAG_ACCENT = "#4b5563"


@dataclass(frozen=True)
class StatBar:
    """One row for a horizontal bar chart."""

    label: str
    count: int
    bytes_total: int
    accent: str | None = None
    apply_prefix: bool = True


def format_bytes_parts(n: int) -> tuple[str, str]:
    """Return (numeric, unit) for Overview styling — e.g. (\"1.2\", \"MB\")."""
    value = float(max(0, n))
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= div or unit == "KB":
            scaled = value / div
            if scaled >= 100 or unit == "KB":
                return f"{scaled:.0f}", unit
            return f"{scaled:.1f}", unit
    return "0", "KB"


def format_bytes(n: int) -> str:
    """Human-readable size (KB / MB / GB)."""
    num, unit = format_bytes_parts(n)
    return f"{num}{unit}"


def _png_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def collect_folder_stats(
    screenshot_dir: str | Path,
    app_root: Path,
    metadata_service: MetadataService | None = None,
) -> list[StatBar]:
    """Per-folder image count and total PNG bytes under the screenshot root."""
    root = resolve_screenshot_root(screenshot_dir, app_root)
    if not root.exists():
        return []

    rows: list[StatBar] = []
    for name in list_folder_names(root, ensure_default=False):
        folder = root / name
        if not folder.is_dir():
            continue
        total = 0
        count = 0
        for png in folder.glob("*.png"):
            count += 1
            total += _png_size(png)
        rows.append(StatBar(label=name, count=count, bytes_total=total))

    rows.sort(key=lambda r: (-r.count, r.label.casefold()))
    return rows


def collect_root_totals(
    screenshot_dir: str | Path,
    app_root: Path,
) -> tuple[int, int]:
    """Total image count and PNG bytes across all folders under Root Folder."""
    rows = collect_folder_stats(screenshot_dir, app_root)
    return (
        sum(r.count for r in rows),
        sum(r.bytes_total for r in rows),
    )


def collect_selected_folder_totals(folder: Path | None) -> tuple[int, int]:
    """Image count and PNG bytes directly inside one selected folder."""
    if folder is None or not folder.is_dir():
        return 0, 0
    png_files = list(folder.glob("*.png"))
    return len(png_files), sum(_png_size(path) for path in png_files)


def collect_selected_folder_stats(folder: Path | None) -> list[StatBar]:
    count, nbytes = collect_selected_folder_totals(folder)
    if folder is None or not folder.is_dir():
        return []
    return [StatBar(label=folder.name or str(folder), count=count, bytes_total=nbytes)]


def collect_selected_folder_tag_stats(
    folder: Path | None,
    metadata_service: MetadataService | None = None,
) -> list[StatBar]:
    """Per-tag counts for PNG files directly inside one selected folder."""
    if folder is None or not folder.is_dir():
        return []
    svc = metadata_service or MetadataService()
    metadata = svc.load_metadata(folder, force_reload=True)
    images = metadata.get("images", {})
    agg: dict[str, list[int]] = {}
    untagged_count = 0
    untagged_bytes = 0
    for png in sorted(folder.glob("*.png")):
        size = _png_size(png)
        tags = (images.get(png.name) or {}).get("tags") or []
        if not tags:
            untagged_count += 1
            untagged_bytes += size
            continue
        for tag in tags:
            row = agg.setdefault(str(tag), [0, 0])
            row[0] += 1
            row[1] += size
    rows = [
        StatBar(label=tag, count=value[0], bytes_total=value[1])
        for tag, value in agg.items()
    ]
    rows.sort(key=lambda row: (-row.count, row.label.casefold()))
    if untagged_count:
        from app.i18n import t

        rows.append(
            StatBar(
                label=t("group_by.no_tag"),
                count=untagged_count,
                bytes_total=untagged_bytes,
                accent=NO_TAG_ACCENT,
                apply_prefix=False,
            )
        )
    return rows


def collect_tag_stats(
    screenshot_dir: str | Path,
    app_root: Path,
    metadata_service: MetadataService | None = None,
) -> list[StatBar]:
    """Per-tag image count and PNG bytes (image may appear under multiple tags).

    Appends a dark-gray \"No tags\" row at the bottom when the Root Folder exists
    and there is at least one untagged image. Hidden when Root Folder is missing.
    """
    if not str(screenshot_dir or "").strip():
        return []

    svc = metadata_service or MetadataService()
    root = resolve_screenshot_root(screenshot_dir, app_root)
    # Root Folder not selected / missing — no tag chart rows (incl. No tags)
    if not root.exists():
        return []

    # tag -> (count, bytes)
    agg: dict[str, list[int]] = {}
    untagged_count = 0
    untagged_bytes = 0
    for folder_dir in iter_image_dirs(root):
        meta = svc.load_metadata(folder_dir, force_reload=True)
        images = meta.get("images", {})
        # Count every PNG on disk so files missing from metadata count as untagged
        seen: set[str] = set()
        for png in sorted(folder_dir.glob("*.png")):
            seen.add(png.name)
            size = _png_size(png)
            entry = images.get(png.name) or {}
            tags = entry.get("tags") or []
            if not tags:
                untagged_count += 1
                untagged_bytes += size
                continue
            for tag in tags:
                key = str(tag)
                if key not in agg:
                    agg[key] = [0, 0]
                agg[key][0] += 1
                agg[key][1] += size
        # Metadata entries without a PNG still contribute to tag totals
        for file_name, entry in images.items():
            if file_name in seen:
                continue
            tags = entry.get("tags") or []
            if not tags:
                continue
            for tag in tags:
                key = str(tag)
                if key not in agg:
                    agg[key] = [0, 0]
                agg[key][0] += 1

    rows = [
        StatBar(label=tag, count=count, bytes_total=nbytes)
        for tag, (count, nbytes) in agg.items()
    ]
    rows.sort(key=lambda r: (-r.count, r.label.casefold()))

    if untagged_count > 0:
        from app.i18n import t

        rows.append(
            StatBar(
                label=t("group_by.no_tag"),
                count=untagged_count,
                bytes_total=untagged_bytes,
                accent=NO_TAG_ACCENT,
                apply_prefix=False,
            )
        )
    return rows
