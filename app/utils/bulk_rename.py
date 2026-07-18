"""Bulk rename helpers for the Work page."""

from __future__ import annotations

from pathlib import Path


def sort_paths_oldest_first(paths: list[Path]) -> list[Path]:
    """Sort by file mtime ascending (oldest capture first)."""
    def key(path: Path):
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(paths, key=key)


def build_sequential_names(
    paths: list[Path],
    prefix: str,
    digits: int = 3,
) -> list[tuple[Path, str]]:
    """
    Map paths → new filenames: ``{prefix}{n:0{digits}d}.png``.

    Paths are ordered oldest-first. ``digits`` must be >= 3; if the count
    needs more digits, width expands automatically.
    """
    prefix = prefix.strip()
    digits = max(3, int(digits))
    ordered = sort_paths_oldest_first(list(paths))
    if not ordered:
        return []

    width = max(digits, len(str(len(ordered))))
    result: list[tuple[Path, str]] = []
    for i, path in enumerate(ordered, start=1):
        new_name = f"{prefix}{i:0{width}d}.png"
        result.append((path, new_name))
    return result
