"""Capixe Action foundation used by UI, Ask AI, and Automation."""

from .context import ActionContext
from .models import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_IDS,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
    ActionIssue,
    ActionItemPlan,
    ActionItemResult,
    ActionNotFoundError,
    ActionPlan,
    ActionRequest,
    ActionResult,
    ActionTarget,
)
from .registry import ActionRegistry, default_registry
from .service import ActionService

__all__ = [
    "ACTION_ADD_FAVORITE",
    "ACTION_ADD_TAG",
    "ACTION_CREATE_FOLDER",
    "ACTION_IDS",
    "ACTION_MOVE",
    "ACTION_REMOVE_ALL_TAGS",
    "ACTION_REMOVE_FAVORITE",
    "ACTION_REMOVE_TAG",
    "ACTION_RENAME",
    "ACTION_REPLACE_TAGS",
    "ActionContext",
    "ActionIssue",
    "ActionItemPlan",
    "ActionItemResult",
    "ActionNotFoundError",
    "ActionPlan",
    "ActionRegistry",
    "ActionRequest",
    "ActionResult",
    "ActionService",
    "ActionTarget",
    "default_registry",
]
