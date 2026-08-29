"""Rename images. Reuses MetadataService; keeps OCR image_id on success."""
from __future__ import annotations

from pathlib import Path

from .context import ActionContext
from .filenames import (
    is_valid_file_stem,
    normalize_rename_filename,
    path_too_long,
    reserved_device_stem,
    same_filesystem_path,
)
from .models import (
    ACTION_RENAME,
    ITEM_BLOCKED,
    ITEM_READY,
    ITEM_SKIPPED,
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
from .rename_names import generate_strategy_names, rename_strategy_of


def _names_for(request: ActionRequest) -> dict[str, str]:
    mapping = request.param("names") or {}
    return {str(key): str(value) for key, value in dict(mapping).items()}


def _requested_name(request: ActionRequest, target_key: str, fallback_key: str | None = None) -> str:
    names = _names_for(request)
    if target_key in names:
        return names[target_key]
    if fallback_key and fallback_key in names:
        return names[fallback_key]
    return str(request.param("new_name") or "")


class RenameAction:
    action_id = ACTION_RENAME

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan:
        request_issues = []
        items: list[ActionItemPlan] = []
        claimed: set[str] = set()
        single_name = str(request.param("new_name") or "").strip()
        names = _names_for(request)
        strategy_names: dict[int, str] = {}
        strategy = rename_strategy_of(request.parameters)
        if not request.targets:
            request_issues.append(issue("target_required", SEVERITY_ERROR, "At least one image is required."))
        if strategy:
            current_names = []
            parent = None
            for target in request.targets:
                resolved = resolve_target(target, context)
                current_names.append(resolved.path.name if resolved.path is not None else (target.path or ""))
                if parent is None and resolved.path is not None:
                    parent = resolved.path.parent
            generated, error = generate_strategy_names(tuple(current_names), request.parameters, parent=parent)
            if error:
                request_issues.append(issue(error, SEVERITY_ERROR, error))
            else:
                strategy_names = generated
        elif len(request.targets) > 1 and single_name and not names:
            request_issues.append(
                issue("ambiguous_new_name", SEVERITY_ERROR, "Batch rename requires a name per image.")
            )

        batch_blocked = any(item.severity == SEVERITY_ERROR for item in request_issues)
        for index, target in enumerate(request.targets):
            resolved = resolve_target(target, context)
            before_path = resolved.path
            before = snapshot(
                path=str(before_path) if before_path is not None else target.path,
                name=before_path.name if before_path is not None else None,
                image_id=resolved.image_id,
            )
            item_issues = list(resolved.issues)
            status = ITEM_READY
            after_name = None
            after_path = None
            requested = strategy_names.get(index) or _requested_name(
                request,
                target.identity_key(),
                f"id:{resolved.image_id}" if resolved.image_id is not None else None,
            )
            if batch_blocked:
                status = ITEM_BLOCKED
                item_issues.extend(request_issues)
            elif resolved.blocked or before_path is None:
                status = ITEM_BLOCKED
            elif not before_path.exists() or not before_path.is_file():
                item_issues.append(
                    issue("source_missing", SEVERITY_ERROR, "The source image was not found.", path=str(before_path))
                )
                status = ITEM_BLOCKED
            else:
                final_name = requested if strategy_names else normalize_rename_filename(before_path.name, requested)
                stem = Path(final_name).stem if final_name else ""
                dest = before_path.with_name(final_name) if final_name else before_path
                if not requested.strip() or not final_name or not is_valid_file_stem(stem):
                    code = "reserved_name" if reserved_device_stem(requested or final_name) else "invalid_filename"
                    item_issues.append(issue(code, SEVERITY_ERROR, "The file name is not valid."))
                    status = ITEM_BLOCKED
                elif path_too_long(dest):
                    item_issues.append(issue("path_too_long", SEVERITY_ERROR, "The file path is too long."))
                    status = ITEM_BLOCKED
                elif final_name == before_path.name:
                    status = ITEM_SKIPPED
                    after_name = before_path.name
                    after_path = str(before_path)
                    item_issues.append(issue("unchanged", SEVERITY_WARNING, "The new name is the same as the current name."))
                else:
                    collision = (dest.exists() and not same_filesystem_path(before_path, dest)) or (
                        final_name.casefold() in claimed
                    )
                    if collision:
                        item_issues.append(
                            issue("name_conflict", SEVERITY_ERROR, "A file with that name already exists.", path=str(dest))
                        )
                        status = ITEM_BLOCKED
                    else:
                        after_name = final_name
                        after_path = str(dest)
                        claimed.add(final_name.casefold())
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
            summary={"rename_strategy": strategy} if strategy else {},
        )

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult:
        results: list[ActionItemResult] = []
        for item in plan.items:
            if item.status != ITEM_READY:
                results.append(plan_item_to_skipped_or_blocked(item))
                continue
            source = Path(item.before["path"])
            new_name = str(item.after.get("name") or "")
            dest = source.with_name(new_name)
            try:
                renamed = context.metadata.rename_image(source.parent, source.name, new_name)
            except FileExistsError:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error="name_conflict",
                        issues=(issue("name_conflict", SEVERITY_ERROR, path=str(dest)),),
                    )
                )
                continue
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
                if dest.exists() and not source.exists():
                    try:
                        dest.rename(source)
                    except OSError:
                        pass
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error=str(exc),
                        issues=(issue("rename_failed", SEVERITY_ERROR, str(exc), path=str(source)),),
                    )
                )
                continue

            if renamed.name == source.name:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_SKIPPED,
                        before=item.before,
                        after=snapshot(path=str(renamed), name=renamed.name, image_id=item.target.image_id),
                        warning="unchanged",
                    )
                )
                continue

            warning = None
            sync_issue = sync_path_change(context, item.target.image_id, renamed)
            issues = (sync_issue,) if sync_issue is not None else ()
            if sync_issue is not None:
                warning = sync_issue.code
            results.append(
                ActionItemResult(
                    target=item.target,
                    status=STATUS_SUCCESS,
                    before=item.before,
                    after=snapshot(path=str(renamed), name=renamed.name, image_id=item.target.image_id),
                    warning=warning,
                    issues=issues,
                )
            )
        return result_from_items(self.action_id, results, issues=plan.issues)
