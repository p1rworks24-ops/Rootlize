"""Move images into a destination folder. Reuses MetadataService; batch-safe."""
from __future__ import annotations

import os
from pathlib import Path

from app.utils.file_copy_name import make_unique_copy_filename

from .context import ActionContext
from .filenames import is_managed_hidden_path, is_within_root, path_too_long
from .models import (
    ACTION_MOVE,
    ITEM_BLOCKED,
    ITEM_READY,
    ITEM_SKIPPED,
    SEVERITY_CONFLICT,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    ActionItemPlan,
    ActionItemResult,
    ActionPlan,
    ActionRequest,
    ActionResult,
    issue,
    plan_item_to_skipped_or_blocked,
    result_from_items,
    snapshot,
)
from .resolve import resolve_target, sync_path_change


def _destination(request: ActionRequest) -> Path | None:
    raw = request.param("destination_path")
    if not raw:
        return None
    return Path(raw)


def _existing_png_names(folder: Path) -> set[str]:
    try:
        return {path.name for path in folder.glob("*.png")}
    except OSError:
        return set()


def _writable_dir(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False


class MoveAction:
    action_id = ACTION_MOVE

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan:
        dest = _destination(request)
        request_issues = []
        items: list[ActionItemPlan] = []
        if dest is None:
            request_issues.append(
                issue("destination_missing", SEVERITY_ERROR, "A destination folder is required.")
            )
        dest_exists = dest is not None and dest.exists()
        dest_is_dir = dest_exists and dest.is_dir()
        will_create = dest is not None and not dest_exists
        if dest is not None and dest_exists and not dest_is_dir:
            request_issues.append(
                issue(
                    "destination_not_directory",
                    SEVERITY_ERROR,
                    "The destination is not a folder.",
                    path=str(dest),
                )
            )
        elif dest is not None and dest_is_dir and not _writable_dir(dest):
            request_issues.append(
                issue(
                    "destination_not_writable",
                    SEVERITY_ERROR,
                    "The destination folder is not writable.",
                    path=str(dest),
                )
            )
        elif will_create:
            parent = dest.parent
            if not parent.exists() or not parent.is_dir():
                request_issues.append(
                    issue(
                        "destination_missing",
                        SEVERITY_ERROR,
                        "The destination folder does not exist.",
                        path=str(dest),
                    )
                )
            else:
                request_issues.append(
                    issue(
                        "destination_missing",
                        SEVERITY_WARNING,
                        "The destination folder will be created.",
                        path=str(dest),
                    )
                )

        dest_blocked = any(item.severity == SEVERITY_ERROR for item in request_issues)
        root = context.managed_root or context.app_root
        name_bound = bool(str(request.param("destination_name") or "").strip())
        if dest is not None and not dest_blocked:
            if is_managed_hidden_path(dest):
                request_issues.append(
                    issue("path_not_allowed", SEVERITY_ERROR, "That folder is outside the library.", path=str(dest))
                )
            elif root is not None and dest.exists() and not is_within_root(dest, root) and name_bound:
                request_issues.append(
                    issue("path_not_allowed", SEVERITY_ERROR, "That folder is outside the library.", path=str(dest))
                )
            elif root is not None and not dest.exists() and not is_within_root(dest.parent, root) and not is_within_root(dest, root):
                request_issues.append(
                    issue("path_not_allowed", SEVERITY_ERROR, "That folder is outside the library.", path=str(dest))
                )
            elif dest_is_dir and path_too_long(dest):
                request_issues.append(
                    issue("path_too_long", SEVERITY_ERROR, "The destination path is too long.", path=str(dest))
                )

        dest_blocked = any(item.severity == SEVERITY_ERROR for item in request_issues)
        claimed = _existing_png_names(dest) if dest_is_dir else set()
        dest_resolved = None
        if dest_is_dir:
            try:
                dest_resolved = dest.resolve()
            except OSError:
                dest_resolved = dest

        if not request.targets:
            request_issues.append(issue("target_required", SEVERITY_ERROR, "At least one image is required."))

        for target in request.targets:
            resolved = resolve_target(target, context)
            before = snapshot(
                path=str(resolved.path) if resolved.path is not None else target.path,
                name=resolved.path.name if resolved.path is not None else None,
                image_id=resolved.image_id,
            )
            item_issues = list(resolved.issues)
            status = ITEM_READY
            after_path = None
            after_name = None
            if dest_blocked or dest is None:
                status = ITEM_BLOCKED
                item_issues.extend(request_issues)
            elif resolved.blocked or resolved.path is None:
                status = ITEM_BLOCKED
            elif not resolved.path.exists() or not resolved.path.is_file():
                item_issues.append(
                    issue("source_missing", SEVERITY_ERROR, "The source image was not found.", path=str(resolved.path))
                )
                status = ITEM_BLOCKED
            else:
                try:
                    source_dir = resolved.path.parent.resolve()
                except OSError:
                    source_dir = resolved.path.parent
                if dest_resolved is not None and source_dir == dest_resolved:
                    status = ITEM_SKIPPED
                    item_issues.append(
                        issue("same_location", SEVERITY_WARNING, "Source and destination are the same folder.")
                    )
                    after_path = str(resolved.path)
                    after_name = resolved.path.name
                else:
                    name = resolved.path.name
                    final_name = name
                    if name in claimed:
                        final_name = make_unique_copy_filename(name, claimed)
                        item_issues.append(
                            issue(
                                "name_conflict",
                                SEVERITY_CONFLICT,
                                "A file with that name exists; a copy name will be used.",
                                path=str(dest / final_name),
                            )
                        )
                    claimed.add(final_name)
                    after_path = str(dest / final_name)
                    after_name = final_name
            items.append(
                ActionItemPlan(
                    target=resolved.target,
                    status=status,
                    before=before,
                    after=snapshot(path=after_path, name=after_name, image_id=resolved.image_id),
                    issues=tuple(item_issues),
                )
            )

        executable = sum(1 for item in items if item.status == ITEM_READY)
        return ActionPlan(
            action_id=self.action_id,
            item_count=len(items),
            executable_count=executable,
            confirmation_required=True,
            items=tuple(items),
            issues=tuple(request_issues),
            summary={"destination_path": str(dest) if dest is not None else None},
        )

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult:
        dest = _destination(request)
        results: list[ActionItemResult] = []
        for item in plan.items:
            if item.status != ITEM_READY:
                results.append(plan_item_to_skipped_or_blocked(item))
                continue
            source = Path(item.before["path"])
            try:
                dest.mkdir(parents=True, exist_ok=True)
                context.metadata.ensure_sstool(dest)
                moved = context.metadata.move_image_to_project(source, dest)
            except FileNotFoundError:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error="source_missing",
                        issues=(issue("source_missing", SEVERITY_ERROR, path=str(source)),),
                    )
                )
                continue
            except OSError as exc:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error=str(exc),
                        issues=(issue("move_failed", SEVERITY_ERROR, str(exc), path=str(source)),),
                    )
                )
                continue

            try:
                same = source.resolve() == moved.resolve()
            except OSError:
                same = str(source) == str(moved)
            if same:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_SKIPPED,
                        before=item.before,
                        after=snapshot(path=str(moved), name=moved.name, image_id=item.target.image_id),
                        warning="same_location",
                    )
                )
                continue

            warning = None
            sync_issue = sync_path_change(context, item.target.image_id, moved)
            issues = (sync_issue,) if sync_issue is not None else ()
            if sync_issue is not None:
                warning = sync_issue.code
            results.append(
                ActionItemResult(
                    target=item.target,
                    status=STATUS_SUCCESS,
                    before=item.before,
                    after=snapshot(path=str(moved), name=moved.name, image_id=item.target.image_id),
                    warning=warning,
                    issues=issues,
                )
            )
        return result_from_items(self.action_id, results, issues=plan.issues)
