"""Tag Actions. Reuse MetadataService; batch-safe; one Confirm for many tags."""
from __future__ import annotations

from pathlib import Path

from app.utils.image_favorite import is_favorite_tag_name
from app.utils.tag_format import normalize_tag, parse_tag_names

from .context import ActionContext
from .models import (
    ACTION_ADD_TAG,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_TAG,
    ACTION_REPLACE_TAGS,
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
from .resolve import resolve_target, sync_tags

MODE_ADD = "add"
MODE_REMOVE = "remove"
MODE_REMOVE_ALL = "remove_all"
MODE_REPLACE = "replace"


def requested_tags(request: ActionRequest) -> tuple[str, ...]:
    raw = request.param("tags")
    if raw in (None, "", [], ()):
        raw = request.param("tag")
    names = parse_tag_names(raw)
    return tuple(name for name in names if not is_favorite_tag_name(name))


def format_tag_list(tags: tuple[str, ...] | list[str]) -> str:
    return ", ".join(str(tag) for tag in tags if str(tag).strip())


def _current_tags(context: ActionContext, path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        return list(context.metadata.get_image_tags(path.parent, path.name))
    except OSError:
        return []


def _same_tag_set(left: list[str], right: list[str] | tuple[str, ...]) -> bool:
    return {normalize_tag(item) for item in left} == {normalize_tag(item) for item in right}


class _TagSetAction:
    action_id = ""
    mode = MODE_ADD

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan:
        tags = requested_tags(request)
        request_issues = []
        if not request.targets:
            request_issues.append(issue("target_required", SEVERITY_ERROR, "At least one image is required."))
        if self.mode in {MODE_ADD, MODE_REMOVE, MODE_REPLACE} and not tags:
            request_issues.append(issue("invalid_tag", SEVERITY_ERROR, "A valid tag is required."))
        param_blocked = any(item.severity == SEVERITY_ERROR for item in request_issues)
        items: list[ActionItemPlan] = []
        for target in request.targets:
            resolved = resolve_target(target, context)
            tags_before = _current_tags(context, resolved.path)
            before = snapshot(
                path=str(resolved.path) if resolved.path is not None else target.path,
                name=resolved.path.name if resolved.path is not None else None,
                image_id=resolved.image_id,
                tags=tags_before,
            )
            item_issues = list(resolved.issues)
            status = ITEM_READY
            tags_after = list(tags_before)
            removed: list[str] = []
            added: list[str] = []
            if param_blocked:
                status = ITEM_BLOCKED
                item_issues.extend(request_issues)
            elif resolved.blocked or resolved.path is None:
                status = ITEM_BLOCKED
            elif resolved.record is not None and getattr(resolved.record, "file_state", "present") != "present":
                item_issues.append(
                    issue(
                        "source_missing",
                        SEVERITY_ERROR,
                        "The indexed image is not present.",
                        path=str(resolved.path),
                    )
                )
                status = ITEM_BLOCKED
            elif not resolved.path.exists() or not resolved.path.is_file():
                item_issues.append(
                    issue("source_missing", SEVERITY_ERROR, "The source image was not found.", path=str(resolved.path))
                )
                status = ITEM_BLOCKED
            elif self.mode == MODE_ADD:
                added = [tag for tag in tags if tag not in tags_before]
                if not added:
                    status = ITEM_SKIPPED
                    item_issues.append(issue("tag_already_present", SEVERITY_WARNING, "The tag is already assigned."))
                else:
                    tags_after = tags_before + added
            elif self.mode == MODE_REMOVE:
                removed = [tag for tag in tags if tag in tags_before]
                if not removed:
                    status = ITEM_SKIPPED
                    item_issues.append(issue("tag_not_present", SEVERITY_WARNING, "The tag is not assigned."))
                else:
                    drop = set(removed)
                    tags_after = [tag for tag in tags_before if tag not in drop]
            elif self.mode == MODE_REMOVE_ALL:
                if not tags_before:
                    status = ITEM_SKIPPED
                    item_issues.append(issue("no_tags", SEVERITY_WARNING, "The image has no tags."))
                    tags_after = []
                else:
                    removed = list(tags_before)
                    tags_after = []
            else:
                if _same_tag_set(tags_before, tags):
                    status = ITEM_SKIPPED
                    item_issues.append(issue("tags_unchanged", SEVERITY_WARNING, "The image already has those tags."))
                    tags_after = list(tags_before)
                else:
                    before_set = set(tags_before)
                    after_set = set(tags)
                    removed = [tag for tag in tags_before if tag not in after_set]
                    added = [tag for tag in tags if tag not in before_set]
                    tags_after = list(tags)
            extra = {"removed_tags": removed, "added_tags": added}
            items.append(
                ActionItemPlan(
                    target=resolved.target,
                    status=status,
                    before=before,
                    after=snapshot(
                        path=before["path"],
                        name=before["name"],
                        image_id=resolved.image_id,
                        tags=tags_after,
                        extra=extra,
                    ),
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
            summary={"tag": tags[0] if len(tags) == 1 else "", "tags": list(tags)},
        )

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult:
        tags = requested_tags(request)
        results: list[ActionItemResult] = []
        for item in plan.items:
            if item.status != ITEM_READY:
                results.append(plan_item_to_skipped_or_blocked(item))
                continue
            path = Path(item.before["path"])
            try:
                changed = self._apply(context, path, tags, item)
            except OSError as exc:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error=str(exc),
                        issues=(issue("tag_failed", SEVERITY_ERROR, str(exc), path=str(path)),),
                    )
                )
                continue
            tags_after = _current_tags(context, path)
            after = snapshot(
                path=str(path),
                name=path.name,
                image_id=item.target.image_id,
                tags=tags_after,
                extra={
                    "removed_tags": item.after.get("removed_tags") or [],
                    "added_tags": item.after.get("added_tags") or [],
                },
            )
            if not changed:
                warning = {
                    MODE_ADD: "tag_already_present",
                    MODE_REMOVE: "tag_not_present",
                    MODE_REMOVE_ALL: "no_tags",
                    MODE_REPLACE: "tags_unchanged",
                }.get(self.mode, "unchanged")
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_SKIPPED,
                        before=item.before,
                        after=after,
                        warning=warning,
                    )
                )
                continue
            warning = None
            sync_issue = sync_tags(context, item.target.image_id, tags_after)
            issues = (sync_issue,) if sync_issue is not None else ()
            if sync_issue is not None:
                warning = sync_issue.code
            results.append(
                ActionItemResult(
                    target=item.target,
                    status=STATUS_SUCCESS,
                    before=item.before,
                    after=after,
                    warning=warning,
                    issues=issues,
                )
            )
        return result_from_items(self.action_id, results, issues=plan.issues)

    def _apply(
        self, context: ActionContext, path: Path, tags: tuple[str, ...], item: ActionItemPlan
    ) -> bool:
        if self.mode == MODE_ADD:
            changed = False
            for tag in tags:
                if context.metadata.add_image_tag(path.parent, path.name, tag):
                    changed = True
            return changed
        if self.mode == MODE_REMOVE:
            changed = False
            for tag in tags:
                if context.metadata.remove_image_tag(path.parent, path.name, tag):
                    changed = True
            return changed
        wanted: list[str] = [] if self.mode == MODE_REMOVE_ALL else list(tags)
        return context.metadata.set_image_tags(path.parent, path.name, wanted)


class AddTagAction(_TagSetAction):
    action_id = ACTION_ADD_TAG
    mode = MODE_ADD


class RemoveTagAction(_TagSetAction):
    action_id = ACTION_REMOVE_TAG
    mode = MODE_REMOVE


class RemoveAllTagsAction(_TagSetAction):
    action_id = ACTION_REMOVE_ALL_TAGS
    mode = MODE_REMOVE_ALL


class ReplaceTagsAction(_TagSetAction):
    action_id = ACTION_REPLACE_TAGS
    mode = MODE_REPLACE
