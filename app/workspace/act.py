"""Structured Act proposals. Never execute; callers use ActionService."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from app.actions.filenames import is_safe_relative_name, is_within_root
from app.actions.models import (
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ActionRequest,
    ActionTarget,
)

from .context import SOURCE_RESULT_SET, SearchResultContext, path_key
from .targets import TargetResolution, resolve_action_targets


@dataclass(frozen=True)
class ActionProposal:
    """LLM/parser output. Must pass ActionRequest validation before execute."""

    action_id: str
    target_source: str = SOURCE_RESULT_SET
    parameters: Mapping[str, Any] = field(default_factory=dict)
    instruction: str = ""
    image_ids: tuple[int, ...] = ()
    paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", dict(self.parameters or {}))
        object.__setattr__(self, "image_ids", tuple(self.image_ids))
        object.__setattr__(self, "paths", tuple(self.paths))


def bound_proposal(
    proposal: ActionProposal,
    context: SearchResultContext,
    *,
    current_folder: Path | str | None = None,
) -> ActionProposal:
    """Fill image_ids / paths from SearchResultContext. Parser never embeds IDs."""
    bound, _resolution = bind_action_proposal(
        proposal, context, current_folder=current_folder,
    )
    return bound


def bind_action_proposal(
    proposal: ActionProposal,
    context: SearchResultContext,
    *,
    current_folder: Path | str | None = None,
) -> tuple[ActionProposal, TargetResolution]:
    """Resolve concrete targets without changing UI selection."""
    if proposal.action_id == ACTION_CREATE_FOLDER:
        empty = TargetResolution(ok=True, source_used=proposal.target_source)
        return proposal, empty
    params = dict(proposal.parameters or {})
    try:
        requested_count = int(params.get("target_count") or 0) or None
    except (TypeError, ValueError):
        requested_count = None
    resolution = resolve_action_targets(
        proposal.target_source,
        context,
        current_folder=current_folder,
        instruction=proposal.instruction or "",
        requested_count=requested_count,
        requested_from=str(params.get("target_from") or ""),
    )
    if not resolution.ok:
        return replace(proposal, image_ids=(), paths=()), resolution
    return (
        replace(
            proposal,
            image_ids=resolution.image_ids,
            paths=resolution.paths,
            target_source=resolution.source_used or proposal.target_source,
        ),
        resolution,
    )


def resolve_destination_folder(
    name: str,
    *,
    current_folder: Path | str | None,
    screenshot_root: Path | str | None = None,
) -> Path | None:
    """Resolve a relative folder name under the Start Folder.

    Existing folders at the Start Folder's parent are not used. Missing
    destinations stay under the Start Folder so Move can create them later.
    """
    raw = str(name or "").strip().strip("「」\"'")
    if not raw or not is_safe_relative_name(raw):
        return None
    if Path(raw).is_absolute():
        return None
    if not current_folder:
        return None
    dest = Path(current_folder) / raw
    bound = screenshot_root or current_folder
    if bound and not is_within_root(dest, bound):
        return None
    return dest


def proposal_to_request(
    proposal: ActionProposal,
    *,
    current_folder: Path | str | None = None,
    screenshot_root: Path | str | None = None,
) -> ActionRequest:
    """Map a proposal to ActionRequest. Does not plan or execute."""
    parameters = dict(proposal.parameters)
    if proposal.action_id == ACTION_MOVE:
        dest_name = parameters.pop("destination_name", None)
        if dest_name and not parameters.get("destination_path"):
            dest = resolve_destination_folder(
                str(dest_name),
                current_folder=current_folder,
                screenshot_root=screenshot_root,
            )
            if dest is not None:
                parameters["destination_path"] = str(dest)
    elif proposal.action_id == ACTION_CREATE_FOLDER:
        name = str(parameters.get("name") or "").strip()
        if name and not is_safe_relative_name(name):
            parameters["name"] = ""
        if current_folder and not parameters.get("parent_path"):
            parameters["parent_path"] = str(Path(current_folder))
        if parameters.get("name") and not parameters.get("new_name"):
            parameters["name"] = str(parameters["name"]).strip()

    targets: list[ActionTarget] = []
    if proposal.action_id != ACTION_CREATE_FOLDER:
        used: set[str] = set()
        leftover = list(proposal.paths)
        if proposal.image_ids:
            for index, image_id in enumerate(proposal.image_ids):
                path = leftover[index] if index < len(leftover) else None
                identity = f"id:{image_id}"
                if identity in used:
                    continue
                used.add(identity)
                targets.append(ActionTarget(image_id=int(image_id), path=str(path) if path else None))
            leftover = leftover[len(proposal.image_ids):]
        for path in leftover:
            key = path_key(path)
            if not key or key in used:
                continue
            used.add(key)
            targets.append(ActionTarget(path=str(path)))

    return ActionRequest(
        action_id=proposal.action_id,
        targets=tuple(targets),
        parameters=parameters,
    )
