"""Machine-readable Action capabilities for the Ask AI Planner.

The Action registry is the allowlist. This module only describes registered
Actions so prompts are not a second source of truth for which Actions exist.
"""
from __future__ import annotations

from typing import Any

from app.actions.models import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
)
from app.actions.registry import ActionRegistry, default_registry
from app.workspace.plan import PARAM_ALLOWLIST

_SPECS: dict[str, dict[str, Any]] = {
    ACTION_ADD_TAG: {
        "summary": "Add one or more tags to target images in a single Confirm. Does not replace other tags.",
        "required": (),
        "notes": "Use tag or tags. Favorite is not a tag. Do not map change/replace tags to this Action.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Requires tag or tags. Duplicate names are ignored. Already-tagged images are no-op.",
        "changes_user_data": True,
    },
    ACTION_REMOVE_TAG: {
        "summary": "Remove one or more named tags from target images in a single Confirm.",
        "required": (),
        "notes": "Use tag or tags named by the user. Missing tags on an image are no-op. Do not guess a tag from the catalog. If the user did not name a tag and asked to remove tags as a set, use remove_all_tags.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Requires tag or tags. Do not pass tag=all.",
        "changes_user_data": True,
    },
    ACTION_REMOVE_ALL_TAGS: {
        "summary": "Remove every tag from target images. Images with no tags are no-op.",
        "required": (),
        "notes": "This is a distinct Action. Do not encode it as remove_tag with tag=all. Prefer this when the user asks to remove tags without naming one.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "No tag parameter. Preview lists tags that will be removed.",
        "changes_user_data": True,
    },
    ACTION_REPLACE_TAGS: {
        "summary": "Replace the current tag set with the given tags.",
        "required": (),
        "notes": "Use tags. Empty replacement is not allowed; clarify instead of mapping to remove_all_tags or add_tag.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Requires tags. Identical sets are no-op. Preview shows Remove and Add diffs.",
        "changes_user_data": True,
    },
    ACTION_MOVE: {
        "summary": "Move target images into a folder identified by destination_name.",
        "required": ("destination_name",),
        "notes": "Use destination_ref when moving into a folder created earlier in this plan. Same-folder moves are no-op. If destination_name does not exist, Move creates that folder under the current Start Folder after Confirm.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Folder names only. No absolute, UNC, or parent-traversal paths.",
        "changes_user_data": True,
    },
    ACTION_RENAME: {
        "summary": "Rename target images. Prefer a local rename_strategy instead of inventing filenames.",
        "required": (),
        "notes": "rename_strategy is prefix, suffix, sequential, or numbered with prefix/suffix/base_name/start/digits. Keep extensions out of stems. generate_names is only for descriptive names.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "No duplicate generated names, no illegal Windows characters, no reserved names, keep extensions.",
        "changes_user_data": True,
    },
    ACTION_CREATE_FOLDER: {
        "summary": "Create a folder in the current folder.",
        "required": ("name",),
        "notes": "Does not move images by itself. If the folder already exists, that is a no-op; use it rather than inventing another name.",
        "target_types": ("folder",),
        "multiplicity": "one",
        "constraints": "Simple folder name only. Existing folder is no-op, not a renamed copy.",
        "changes_user_data": True,
    },
    ACTION_ADD_FAVORITE: {
        "summary": "Mark target images as favorites. Independent of tags. Supports many images.",
        "required": (),
        "notes": "No extra parameters. Confirmation is still required.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Already-favorited images are no-op.",
        "changes_user_data": True,
    },
    ACTION_REMOVE_FAVORITE: {
        "summary": "Remove the favorite mark from target images. Supports many images.",
        "required": (),
        "notes": "No extra parameters. Confirmation is still required.",
        "target_types": ("images",),
        "multiplicity": "many",
        "constraints": "Images that are not favorites are no-op.",
        "changes_user_data": True,
    },
}


def action_capabilities(registry: ActionRegistry | None = None) -> tuple[dict[str, Any], ...]:
    """Registered Actions with parameters and constraints. Unregistered IDs are omitted."""
    source = registry or default_registry()
    items: list[dict[str, Any]] = []
    for action_id in source.action_ids():
        spec = _SPECS.get(action_id, {})
        allowed = tuple(sorted(PARAM_ALLOWLIST.get(action_id, ())))
        required = tuple(name for name in spec.get("required", ()) if name in set(allowed) or not allowed)
        items.append(
            {
                "action_id": action_id,
                "parameters": allowed,
                "required": required,
                "summary": str(spec.get("summary") or action_id),
                "notes": str(spec.get("notes") or ""),
                "target_types": tuple(spec.get("target_types") or ("images",)),
                "multiplicity": str(spec.get("multiplicity") or "many"),
                "constraints": str(spec.get("constraints") or ""),
                "confirmation_required": True,
                "changes_user_data": bool(spec.get("changes_user_data", True)),
                "can_execute": False,
            }
        )
    return tuple(items)


def allowed_action_ids(registry: ActionRegistry | None = None) -> tuple[str, ...]:
    source = registry or default_registry()
    return tuple(source.action_ids())


def format_capability_catalog(capabilities: tuple[dict[str, Any], ...] | None = None) -> str:
    rows = []
    for item in capabilities or action_capabilities():
        params = ", ".join(item["parameters"]) or "(none)"
        required = ", ".join(item["required"]) or "(none)"
        targets = ", ".join(item.get("target_types") or ()) or "images"
        extra = str(item.get("constraints") or "").strip()
        rows.append(
            f"- {item['action_id']}: {item['summary']} "
            f"parameters=[{params}] required=[{required}] "
            f"targets=[{targets}] multiplicity={item.get('multiplicity') or 'many'} "
            f"confirmation_required=true executes=false. {item['notes']} {extra}".strip()
        )
    return "\n".join(rows) if rows else "(no actions)"


def action_id_schema_enum(registry: ActionRegistry | None = None) -> list[str]:
    return [""] + list(allowed_action_ids(registry))
