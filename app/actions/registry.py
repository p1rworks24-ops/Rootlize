"""Stable Action identifier lookup for UI, Ask AI, and future Automation."""
from __future__ import annotations

from typing import Protocol

from .models import ActionNotFoundError, ActionPlan, ActionRequest, ActionResult
from .context import ActionContext


class Action(Protocol):
    action_id: str

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan: ...

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult: ...


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        self._actions[str(action.action_id)] = action

    def get(self, action_id: str) -> Action:
        try:
            return self._actions[str(action_id)]
        except KeyError as exc:
            raise ActionNotFoundError(action_id) from exc

    def has(self, action_id: str) -> bool:
        return str(action_id) in self._actions

    def action_ids(self) -> tuple[str, ...]:
        return tuple(self._actions)

    def __contains__(self, action_id: object) -> bool:
        return str(action_id) in self._actions


def build_default_registry() -> ActionRegistry:
    from .create_folder import CreateFolderAction
    from .favorite import AddFavoriteAction, RemoveFavoriteAction
    from .move import MoveAction
    from .rename import RenameAction
    from .tags import AddTagAction, RemoveAllTagsAction, RemoveTagAction, ReplaceTagsAction

    registry = ActionRegistry()
    for action in (
        CreateFolderAction(),
        MoveAction(),
        RenameAction(),
        AddTagAction(),
        RemoveTagAction(),
        RemoveAllTagsAction(),
        ReplaceTagsAction(),
        AddFavoriteAction(),
        RemoveFavoriteAction(),
    ):
        registry.register(action)
    return registry


_DEFAULT_REGISTRY: ActionRegistry | None = None


def default_registry() -> ActionRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY
