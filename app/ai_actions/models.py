"""Domain models for safe, preview-only AI action planning."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    SEARCH = "search"
    TAG = "tag"
    MOVE = "move"
    RENAME = "rename"
    DELETE = "delete"
    UNKNOWN = "unknown"


MUTATING_ACTIONS = frozenset({
    ActionType.TAG, ActionType.MOVE, ActionType.RENAME, ActionType.DELETE,
})


@dataclass(frozen=True)
class ActionParameters:
    tag: str | None = None
    destination_folder: str | None = None
    new_name: str | None = None


@dataclass(frozen=True)
class ActionPlan:
    """A description of work to review; it never performs the action."""

    instruction: str
    action: ActionType
    search_query: str
    matched_image_ids: tuple[int, ...]
    confidence: float
    match_state: str
    action_parameters: ActionParameters
    confirmation_required: bool
    clarification_required: bool
    ambiguity_reasons: tuple[str, ...] = ()
    candidate_scores: tuple[tuple[int, float], ...] = ()

