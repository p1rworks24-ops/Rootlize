"""Resolve stored Ask AI result references to current image paths.

No Meaning Search, Vision, LLM, Semantic Index, or quota. Path and local
OCR image_id lookups only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

ASK_AI_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def is_existing_image_file(path: Path | str) -> bool:
    candidate = Path(path)
    try:
        return (
            candidate.is_file()
            and candidate.suffix.casefold() in ASK_AI_IMAGE_SUFFIXES
        )
    except OSError:
        return False


def result_path_key(path: Path | str) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve())
    except OSError:
        return str(candidate)


def _unique_existing(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        if not is_existing_image_file(path):
            continue
        key = result_path_key(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(Path(path))
    return unique


def resolve_stored_result_paths(
    stored_paths: Iterable[Path | str],
    *,
    ocr_ids: dict[str, int] | None = None,
    ocr_records: Iterable[object] | None = None,
    lookup_folders: Iterable[Path | str] | None = None,
) -> list[Path]:
    """Map stored references to files that exist now. Skip missing ones."""
    id_map = dict(ocr_ids or {})
    by_id: dict[int, object] = {}
    for record in ocr_records or ():
        image_id = getattr(record, "image_id", None)
        if image_id is not None:
            by_id[int(image_id)] = record

    folders = [Path(folder) for folder in lookup_folders or ()]
    resolved: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str) -> bool:
        candidate = Path(path)
        if not is_existing_image_file(candidate):
            return False
        key = result_path_key(candidate)
        if key in seen:
            return False
        seen.add(key)
        resolved.append(candidate)
        return True

    for stored in stored_paths:
        original = Path(stored)
        if add(original):
            continue
        key = result_path_key(original)
        image_id = id_map.get(key)
        if image_id is None:
            image_id = id_map.get(str(original))
        if image_id is not None:
            record = by_id.get(int(image_id))
            record_path = getattr(record, "path", None) if record is not None else None
            if record_path is not None and add(record_path):
                continue
        folder_hits = [Path(folder) / original.name for folder in folders]
        unique_folders = _unique_existing(folder_hits)
        if len(unique_folders) == 1:
            add(unique_folders[0])
    return resolved


def primary_result_folder(
    paths: Iterable[Path | str],
    original_folder: Path | str | None = None,
) -> Path | None:
    """Folder that currently holds the most resolved images (B: folder-unit Grid)."""
    existing = [Path(path) for path in paths if is_existing_image_file(path)]
    if not existing:
        return None
    counts: dict[str, int] = {}
    folders: dict[str, Path] = {}
    order: list[str] = []
    for path in existing:
        folder = Path(path).parent
        key = result_path_key(folder)
        if key not in folders:
            folders[key] = folder
            order.append(key)
        counts[key] = counts.get(key, 0) + 1
    best = max(counts.values())
    winners = {key for key, count in counts.items() if count == best}
    if original_folder is not None:
        original_key = result_path_key(Path(original_folder))
        if original_key in winners:
            return folders[original_key]
    for key in order:
        if key in winners:
            return folders[key]
    return existing[0].parent


def paths_in_folder(paths: Iterable[Path | str], folder: Path | str) -> list[Path]:
    target = result_path_key(Path(folder))
    matched: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        candidate = Path(path)
        if not is_existing_image_file(candidate):
            continue
        if result_path_key(candidate.parent) != target:
            continue
        key = result_path_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        matched.append(candidate)
    return matched
