"""Add Favorite / Remove Favorite Actions. Metadata only; not a Tag."""
from __future__ import annotations

from pathlib import Path

from .context import ActionContext
from .models import (
    ACTION_ADD_FAVORITE,
    ACTION_REMOVE_FAVORITE,
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
from .resolve import resolve_target


class _FavoriteAction:
    action_id = ""
    _adding = True

    def plan(self, request: ActionRequest, context: ActionContext) -> ActionPlan:
        request_issues = []
        if not request.targets:
            request_issues.append(issue("target_required", SEVERITY_ERROR, "At least one image is required."))
        param_blocked = any(item.severity == SEVERITY_ERROR for item in request_issues)
        items: list[ActionItemPlan] = []
        for target in request.targets:
            resolved = resolve_target(target, context)
            before_fav = False
            if resolved.path is not None:
                try:
                    before_fav = context.metadata.is_image_favorite(
                        resolved.path.parent, resolved.path.name
                    )
                except OSError:
                    before_fav = False
            before = snapshot(
                path=str(resolved.path) if resolved.path is not None else target.path,
                name=resolved.path.name if resolved.path is not None else None,
                image_id=resolved.image_id,
                extra={"favorite": before_fav},
            )
            item_issues = list(resolved.issues)
            status = ITEM_READY
            after_fav = True if self._adding else False
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
            elif self._adding and before_fav:
                status = ITEM_SKIPPED
                item_issues.append(issue("already_favorite", SEVERITY_WARNING, "The image is already a favorite."))
            elif not self._adding and not before_fav:
                status = ITEM_SKIPPED
                item_issues.append(issue("not_favorite", SEVERITY_WARNING, "The image is not a favorite."))
            items.append(
                ActionItemPlan(
                    target=resolved.target,
                    status=status,
                    before=before,
                    after=snapshot(
                        path=before["path"],
                        name=before["name"],
                        image_id=resolved.image_id,
                        extra={"favorite": after_fav if status == ITEM_READY else before_fav},
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
            summary={"favorite": self._adding},
        )

    def execute(self, request: ActionRequest, context: ActionContext, plan: ActionPlan) -> ActionResult:
        results: list[ActionItemResult] = []
        for item in plan.items:
            if item.status != ITEM_READY:
                results.append(plan_item_to_skipped_or_blocked(item))
                continue
            path = Path(item.before["path"])
            try:
                changed = context.metadata.set_image_favorite(path.parent, path.name, self._adding)
            except OSError as exc:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_FAILED,
                        before=item.before,
                        after=item.after,
                        error=str(exc),
                        issues=(issue("favorite_failed", SEVERITY_ERROR, str(exc), path=str(path)),),
                    )
                )
                continue
            after_fav = context.metadata.is_image_favorite(path.parent, path.name)
            after = snapshot(
                path=str(path),
                name=path.name,
                image_id=item.target.image_id,
                extra={"favorite": after_fav},
            )
            if not changed:
                results.append(
                    ActionItemResult(
                        target=item.target,
                        status=STATUS_SKIPPED,
                        before=item.before,
                        after=after,
                        warning="already_favorite" if self._adding else "not_favorite",
                    )
                )
                continue
            results.append(
                ActionItemResult(
                    target=item.target,
                    status=STATUS_SUCCESS,
                    before=item.before,
                    after=after,
                )
            )
        return result_from_items(self.action_id, results, issues=plan.issues)


class AddFavoriteAction(_FavoriteAction):
    action_id = ACTION_ADD_FAVORITE
    _adding = True


class RemoveFavoriteAction(_FavoriteAction):
    action_id = ACTION_REMOVE_FAVORITE
    _adding = False
