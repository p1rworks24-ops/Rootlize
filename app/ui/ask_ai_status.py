"""User-facing Ask AI status while first-time screenshot analysis is running.

Does not mention facts, Vision, OpenCLIP, or other internals.
First Meaning Search waits for preparation; this copy must not imply
partial results from already-ready screenshots.
"""

from __future__ import annotations

from app.i18n import t


def ask_ai_phase_copy(phase: str, *, count: int = 0, done: int | None = None) -> str:
    if phase == "understanding":
        return t("images.ai.understanding")
    if phase == "searching":
        return t("images.ai.searching_status")
    if phase == "refining":
        return t("images.ai.refining_status")
    if phase == "preparing":
        return t("images.ai.preparing_changes")
    if phase == "updating":
        if done is not None and count:
            return t("images.ai.updating_progress", done=done, total=count)
        if count:
            return t("images.ai.updating_count", count=count)
        return t("images.ai.preparing_changes")
    return t("images.ai.understanding")


def ask_ai_preparing_copy(*, ready: int = 0, total: int = 0) -> str:
    if total > 0:
        return t("images.ai.preparing_progress", ready=ready, total=total)
    return t("images.ai.preparing")


def ask_ai_grid_preparing_copy(*, query: str, ready: int = 0, total: int = 0) -> str:
    if total > 0:
        return t(
            "images.ai.grid_preparing_progress",
            query=query,
            ready=ready,
            total=total,
        )
    return t("images.ai.grid_preparing", query=query)


def ask_ai_chat_status(
    *,
    searching: bool,
    count: int = 0,
    preparing: bool = False,
    ready: int = 0,
    total: int = 0,
) -> str:
    if preparing:
        return ask_ai_preparing_copy(ready=ready, total=total)
    if searching:
        return t("images.ai.searching_status")
    if count == 1:
        return t("images.ai.found_one")
    if count:
        return t("images.ai.found", count=count)
    return t("images.ai.no_matches")


def ask_ai_grid_status(
    *,
    query: str,
    count: int = 0,
    searching: bool,
    preparing: bool = False,
    ready: int = 0,
    total: int = 0,
) -> str:
    if preparing:
        return ask_ai_grid_preparing_copy(query=query, ready=ready, total=total)
    if searching:
        return t("images.ai.grid_searching", query=query)
    return t("images.ai.grid_results", query=query, count=count)
