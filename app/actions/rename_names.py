"""Deterministic batch-rename filename generation. Planner supplies strategy; local code builds names."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .filenames import is_valid_file_stem, normalize_rename_filename, path_too_long
from .models import RENAME_STRATEGIES

STRATEGY_PREFIX = "prefix"
STRATEGY_SUFFIX = "suffix"
STRATEGY_SEQUENTIAL = "sequential"
STRATEGY_NUMBERED = "numbered"


def rename_strategy_of(parameters: Mapping[str, Any] | None) -> str:
    raw = str((parameters or {}).get("rename_strategy") or "").strip().lower()
    return raw if raw in RENAME_STRATEGIES else ""


def _int_param(parameters: Mapping[str, Any], key: str, default: int) -> int:
    raw = (parameters or {}).get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def needed_digits(count: int, start: int) -> int:
    last = max(1, start + max(count, 1) - 1)
    return max(1, len(str(last)))


def resolve_digits(*, count: int, start: int, requested: int, strategy: str) -> int | None:
    needed = needed_digits(count, start)
    if requested > 0:
        if requested < needed:
            return None
        return requested
    if strategy == STRATEGY_NUMBERED:
        return max(3, needed)
    return 0


def format_sequence(base_name: str, number: int, digits: int) -> str:
    stem = (base_name or "").strip()
    token = f"{number:0{digits}d}" if digits > 0 else str(number)
    if not stem:
        return token
    if stem.endswith(("-", "_")):
        return f"{stem}{token}"
    return f"{stem} {token}"


def generate_strategy_names(
    current_names: tuple[str, ...] | list[str],
    parameters: Mapping[str, Any] | None,
    *,
    parent: Path | None = None,
) -> tuple[dict[int, str], str]:
    """Return {index: new filename} and an error code (empty if ok).

    Does not invent suffixes on collision. Caller maps indexes to targets.
    """
    params = dict(parameters or {})
    strategy = rename_strategy_of(params)
    if not strategy:
        return {}, "missing_parameter"
    count = len(current_names)
    if count <= 0:
        return {}, "target_required"
    start = max(1, _int_param(params, "start", 1))
    requested_digits = max(0, _int_param(params, "digits", 0))
    digits = resolve_digits(count=count, start=start, requested=requested_digits, strategy=strategy)
    if digits is None:
        return {}, "numbering_overflow"
    prefix = str(params.get("prefix") or "")
    suffix = str(params.get("suffix") or "")
    base_name = str(params.get("base_name") or params.get("new_name") or "").strip()
    if strategy == STRATEGY_PREFIX and not prefix:
        return {}, "missing_parameter"
    if strategy == STRATEGY_SUFFIX and not suffix:
        return {}, "missing_parameter"
    if strategy in {STRATEGY_SEQUENTIAL, STRATEGY_NUMBERED} and not base_name:
        return {}, "missing_parameter"

    generated: dict[int, str] = {}
    claimed: set[str] = set()
    for index, old_name in enumerate(current_names):
        old = Path(old_name).name
        if strategy == STRATEGY_PREFIX:
            requested = f"{prefix}{Path(old).stem}"
        elif strategy == STRATEGY_SUFFIX:
            requested = f"{Path(old).stem}{suffix}"
        else:
            requested = format_sequence(base_name, start + index, digits)
        final_name = normalize_rename_filename(old, requested)
        stem = Path(final_name).stem if final_name else ""
        if not requested.strip() or not final_name or not is_valid_file_stem(stem):
            from .filenames import reserved_device_stem

            return {}, "reserved_name" if reserved_device_stem(requested or final_name) else "invalid_filename"
        dest = (parent / final_name) if parent is not None else Path(final_name)
        if path_too_long(dest):
            return {}, "path_too_long"
        key = final_name.casefold()
        if key in claimed:
            return {}, "duplicate_generated_name"
        claimed.add(key)
        generated[index] = final_name
    return generated, ""
