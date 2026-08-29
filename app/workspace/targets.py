"""Resolve Ask AI Action targets from Planner intent + SearchResultContext.

The Planner says what the user is pointing at. This module maps that intent
onto the current local result set / selection. It does not change UI selection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .context import (
    FOCUS_RESULTS,
    FOCUS_SELECTION,
    SOURCE_FOLDER,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    path_key,
)

INTENT_CURRENT = "current"

REASON_OK = ""
REASON_NO_TARGETS = "no_targets"
REASON_MISSING_SELECTION = "missing_selection"
REASON_MISSING_RESULTS = "missing_results"
REASON_AMBIGUOUS = "ambiguous_targets"
REASON_STALE_FOLDER = "stale_folder"

_EXPLICIT_SELECTION = re.compile(
    r"(選択した(?:画像|もの)?|選んだ(?:画像|もの)?|"
    r"\bthe selection\b|\bselected(?:\s+images?)?\b)",
    re.I,
)
_EXPLICIT_RESULTS = re.compile(
    r"(この結果|さっきの結果|この検索結果|これらの結果|"
    r"\bthese results\b|\bthis result\b|\bthe (?:current |last |previous )?results?\b)",
    re.I,
)


@dataclass(frozen=True)
class TargetResolution:
    """Concrete image IDs/paths, or a clarification instead of a guess."""

    ok: bool
    image_ids: tuple[int, ...] = ()
    paths: tuple[str, ...] = ()
    source_used: str = ""
    resolved_count: int = 0
    ambiguous: bool = False
    reason: str = REASON_OK
    message_key: str = ""
    hint_key: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "image_ids", tuple(self.image_ids))
        object.__setattr__(self, "paths", tuple(self.paths))
        count = len(self.image_ids or self.paths)
        object.__setattr__(self, "resolved_count", count)


def resolve_action_targets(
    intent_source: str,
    context: SearchResultContext,
    *,
    current_folder: Path | str | None = None,
    instruction: str = "",
    requested_count: int | None = None,
    requested_from: str = "",
) -> TargetResolution:
    """Map Planner target intent onto SearchResultContext.

    Does not invent IDs from chat text, and does not copy results into
    UI selection. Stale result sets from another folder are ignored.
    """
    del requested_from  # quantity slicing stays in apply_target_filters
    ctx = context or SearchResultContext()
    stale = _folder_is_stale(ctx, current_folder)
    results = _empty_pair() if stale else _pair(ctx.result_image_ids, ctx.result_paths)
    selection = _empty_pair() if stale else _pair(ctx.selected_image_ids, ctx.selected_paths)
    intent = _normalize_intent(intent_source, instruction, ctx)
    wants_one = requested_count == 1
    focus = "" if stale else str(ctx.last_target_focus or "")

    if intent == SOURCE_SELECTION:
        if _has_pair(selection):
            return _ok(selection, SOURCE_SELECTION)
        if is_explicit_selection_request(instruction):
            return _clarify(
                REASON_MISSING_SELECTION,
                stale=stale,
            )
        rescued = _continuation_results(results, wants_one=wants_one)
        if rescued is not None:
            return _ok(rescued, SOURCE_RESULT_SET)
        return _clarify(REASON_MISSING_SELECTION, stale=stale)

    if intent == SOURCE_RESULT_SET:
        if _has_pair(results):
            return _ok(results, SOURCE_RESULT_SET)
        return _clarify(REASON_MISSING_RESULTS, stale=stale)

    if _has_pair(results) and not _has_pair(selection):
        return _ok(results, SOURCE_RESULT_SET)
    if _has_pair(selection) and not _has_pair(results):
        return _ok(selection, SOURCE_SELECTION)
    if _has_pair(results) and _has_pair(selection):
        if _same_pair(results, selection):
            return _ok(results, SOURCE_RESULT_SET)
        if focus == FOCUS_SELECTION:
            return _ok(selection, SOURCE_SELECTION)
        if focus == FOCUS_RESULTS:
            return _ok(results, SOURCE_RESULT_SET)
        if _result_count(results) == 1 and wants_one:
            return _ok(results, SOURCE_RESULT_SET)
        return _clarify(REASON_AMBIGUOUS, stale=stale)
    return _clarify(REASON_NO_TARGETS, stale=stale)


def _normalize_intent(
    intent_source: str,
    instruction: str,
    context: SearchResultContext,
) -> str:
    raw = str(intent_source or "").strip().lower()
    if is_explicit_selection_request(instruction):
        return SOURCE_SELECTION
    if _EXPLICIT_RESULTS.search(instruction or "") and context.has_result_set():
        return SOURCE_RESULT_SET
    if raw in {SOURCE_SELECTION, SOURCE_RESULT_SET}:
        return raw
    if raw in {"", INTENT_CURRENT, SOURCE_FOLDER}:
        return INTENT_CURRENT
    return INTENT_CURRENT


def is_explicit_selection_request(instruction: str) -> bool:
    return bool(_EXPLICIT_SELECTION.search(instruction or ""))


def _continuation_results(
    results: tuple[tuple[int, ...], tuple[str, ...]],
    *,
    wants_one: bool,
) -> tuple[tuple[int, ...], tuple[str, ...]] | None:
    if not _has_pair(results):
        return None
    count = _result_count(results)
    if wants_one and count != 1:
        return None
    return results


def _folder_is_stale(context: SearchResultContext, current_folder: Path | str | None) -> bool:
    if not current_folder or not context.scope_folder:
        return False
    return path_key(current_folder) != path_key(context.scope_folder)


def _pair(ids: tuple[int, ...], paths: tuple[str, ...]) -> tuple[tuple[int, ...], tuple[str, ...]]:
    return tuple(int(item) for item in ids or ()), tuple(str(item) for item in paths or () if item)


def _empty_pair() -> tuple[tuple[int, ...], tuple[str, ...]]:
    return (), ()


def _has_pair(pair: tuple[tuple[int, ...], tuple[str, ...]]) -> bool:
    ids, paths = pair
    return bool(ids or paths)


def _result_count(pair: tuple[tuple[int, ...], tuple[str, ...]]) -> int:
    ids, paths = pair
    return len(ids or paths)


def _same_pair(
    left: tuple[tuple[int, ...], tuple[str, ...]],
    right: tuple[tuple[int, ...], tuple[str, ...]],
) -> bool:
    left_ids, left_paths = left
    right_ids, right_paths = right
    if left_ids and right_ids:
        return tuple(left_ids) == tuple(right_ids)
    return tuple(left_paths) == tuple(right_paths)


def _ok(
    pair: tuple[tuple[int, ...], tuple[str, ...]],
    source: str,
) -> TargetResolution:
    ids, paths = pair
    return TargetResolution(
        ok=True,
        image_ids=ids,
        paths=paths,
        source_used=source,
    )


def _clarify(reason: str, *, stale: bool) -> TargetResolution:
    if stale:
        reason = REASON_STALE_FOLDER
    if reason == REASON_AMBIGUOUS:
        return TargetResolution(
            ok=False,
            ambiguous=True,
            reason=reason,
            message_key="images.ai.ambiguous_target",
        )
    return TargetResolution(
        ok=False,
        reason=reason,
        message_key="images.ai.missing_target",
        hint_key="images.ai.clarify_target",
    )
