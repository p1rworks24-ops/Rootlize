"""Aggregate image counts and PNG disk usage by folder or tag (Home dashboard)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.metadata_service import MetadataService
from app.utils.workspace import iter_image_dirs, list_folder_names, resolve_screenshot_root


@dataclass(frozen=True)
class StatBar:
    """One row for a horizontal bar chart."""

    label: str
    count: int
    bytes_total: int


def format_bytes(n: int) -> str:
    """Human-readable size (KB / MB / GB)."""
    value = float(max(0, n))
    for unit, div in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= div or unit == "KB":
            scaled = value / div
            if scaled >= 100 or unit == "KB":
                return f"{scaled:.0f}{unit}"
            return f"{scaled:.1f}{unit}"
    return "0KB"


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


def collect_tag_stats(
    screenshot_dir: str | Path,
    app_root: Path,
    metadata_service: MetadataService | None = None,
) -> list[StatBar]:
    """Per-tag image count and PNG bytes (image may appear under multiple tags)."""
    svc = metadata_service or MetadataService()
    root = resolve_screenshot_root(screenshot_dir, app_root)
    if not root.exists():
        return []

    # tag -> (count, bytes)
    agg: dict[str, list[int]] = {}
    for folder_dir in iter_image_dirs(root):
        meta = svc.load_metadata(folder_dir, force_reload=True)
        images = meta.get("images", {})
        for file_name, entry in images.items():
            png = folder_dir / file_name
            size = _png_size(png) if png.exists() else 0
            tags = entry.get("tags") or []
            if not tags:
                continue
            for tag in tags:
                key = str(tag)
                if key not in agg:
                    agg[key] = [0, 0]
                agg[key][0] += 1
                agg[key][1] += size

    rows = [
        StatBar(label=tag, count=count, bytes_total=nbytes)
        for tag, (count, nbytes) in agg.items()
    ]
    rows.sort(key=lambda r: (-r.count, r.label.casefold()))
    return rows
