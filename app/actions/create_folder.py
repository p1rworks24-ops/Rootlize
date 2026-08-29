"""Create Folder Action. Filesystem only; callers own confirmation UI."""
from __future__ import annotations

from pathlib import Path

from app.utils.folder_ops import create_folder, is_valid_folder_name

from .context import ActionContext
from .filenames import (
    is_managed_hidden_path,
    is_safe_relative_name,
    is_within_root,
    path_too_long,
    reserved_device_stem,
)
from .models import (
    ACTION_CREATE_FOLDER,
    ITEM_BLOCKED,
    ITEM_READY,
    ITEM_SKIPPED,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    STATUS_FAILED,
    ActionItemPlan,
    ActionItemResult,
    ActionPlan,
    ActionRequest,
    ActionResult,
    ActionTarget,
    issue,
    plan_item_to_skipped_or_blocked,
    result_from_items,
    snapshot,
)


def _destination(request: ActionRequest) -> tuple[Path | None, str]:
    parent_raw = request.param("parent_path")
    name = str(request.param("name") or "").strip()
    if not parent_raw:
        return None, name
    return Path(parent_raw), name


class CreateFolderAction:
    action_id = ACTION_CREATE_FOLDER

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan:
        parent, name = _destination(request)
        target = ActionTarget(path=str(parent / name) if parent is not None and name else None)
        issues = []
        status = ITEM_READY
        dest = parent / name if parent is not None and name else None
        if parent is None:
            issues.append(issue("parent_missing", SEVERITY_ERROR, "A parent folder is required."))
            status = ITEM_BLOCKED
        elif not parent.exists() or not parent.is_dir():
            issues.append(
                issue("parent_missing", SEVERITY_ERROR, "The parent folder does not exist.", path=str(parent))
            )
            status = ITEM_BLOCKED
        elif not name:
            issues.append(issue("invalid_folder_name", SEVERITY_ERROR, "A folder name is required."))
            status = ITEM_BLOCKED
        elif not is_valid_folder_name(name) or reserved_device_stem(name):
            issues.append(
                issue("invalid_folder_name", SEVERITY_ERROR, "The folder name is not valid.", path=str(dest))
            )
            status = ITEM_BLOCKED
        elif dest is not None and dest.exists():
            if dest.is_dir() and not is_managed_hidden_path(dest):
                issues.append(
                    issue("folder_exists", SEVERITY_WARNING, "A folder with this name already exists.", path=str(dest))
                )
                status = ITEM_SKIPPED
            else:
                issues.append(
                    issue("folder_exists", SEVERITY_ERROR, "A folder with this name already exists.", path=str(dest))
                )
                status = ITEM_BLOCKED
        elif dest is not None and path_too_long(dest):
            issues.append(issue("path_too_long", SEVERITY_ERROR, "The folder path is too long.", path=str(dest)))
            status = ITEM_BLOCKED
        elif dest is not None and is_managed_hidden_path(dest):
            issues.append(issue("path_not_allowed", SEVERITY_ERROR, "That folder is outside the library.", path=str(dest)))
            status = ITEM_BLOCKED
        else:
            root = context.managed_root or context.app_root
            if dest is not None and root is not None and not is_within_root(dest, root):
                issues.append(
                    issue("path_not_allowed", SEVERITY_ERROR, "That folder is outside the library.", path=str(dest))
                )
                status = ITEM_BLOCKED
            elif name and not is_safe_relative_name(name):
                issues.append(
                    issue("invalid_folder_name", SEVERITY_ERROR, "The folder name is not valid.", path=str(dest))
                )
                status = ITEM_BLOCKED

        item = ActionItemPlan(
            target=target,
            status=status,
            before=snapshot(path=None, name=name),
            after=snapshot(path=str(dest) if dest is not None else None, name=name),
            issues=tuple(issues),
        )
        return ActionPlan(
            action_id=self.action_id,
            item_count=1,
            executable_count=1 if status == ITEM_READY else 0,
            confirmation_required=True,
            items=(item,),
            issues=tuple(issues),
            summary={"name": name, "parent_path": str(parent) if parent is not None else None},
        )

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult:
        item = plan.items[0]
        if item.status != ITEM_READY:
            return result_from_items(self.action_id, [plan_item_to_skipped_or_blocked(item)], issues=plan.issues)

        parent, name = _destination(request)
        try:
            created = create_folder(parent, name)
        except FileExistsError:
            failed = ActionItemResult(
                target=item.target,
                status=STATUS_FAILED,
                before=item.before,
                after=item.after,
                error="folder_exists",
                issues=(issue("folder_exists", SEVERITY_ERROR, path=str(parent / name)),),
            )
            return result_from_items(self.action_id, [failed])
        except ValueError:
            failed = ActionItemResult(
                target=item.target,
                status=STATUS_FAILED,
                before=item.before,
                after=item.after,
                error="invalid_folder_name",
                issues=(issue("invalid_folder_name", SEVERITY_ERROR),),
            )
            return result_from_items(self.action_id, [failed])
        except OSError as exc:
            failed = ActionItemResult(
                target=item.target,
                status=STATUS_FAILED,
                before=item.before,
                after=item.after,
                error=str(exc),
                issues=(issue("create_failed", SEVERITY_ERROR, str(exc)),),
            )
            return result_from_items(self.action_id, [failed])

        after = snapshot(path=str(created), name=created.name)
        return result_from_items(
            self.action_id,
            [
                ActionItemResult(
                    target=ActionTarget(path=str(created)),
                    status="success",
                    before=item.before,
                    after=after,
                )
            ],
        )
