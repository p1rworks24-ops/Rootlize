"""Shared Action request / preview / result models.

UI, Ask AI, and future Automation all pass through these types.
Preview data is UI-agnostic; callers decide whether to confirm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

ACTION_CREATE_FOLDER = "create_folder"
ACTION_MOVE = "move"
ACTION_RENAME = "rename"
ACTION_ADD_TAG = "add_tag"
ACTION_REMOVE_TAG = "remove_tag"
ACTION_REMOVE_ALL_TAGS = "remove_all_tags"
ACTION_REPLACE_TAGS = "replace_tags"
ACTION_ADD_FAVORITE = "add_favorite"
ACTION_REMOVE_FAVORITE = "remove_favorite"

ACTION_IDS = (
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_RENAME,
    ACTION_ADD_TAG,
    ACTION_REMOVE_TAG,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REPLACE_TAGS,
    ACTION_ADD_FAVORITE,
    ACTION_REMOVE_FAVORITE,
)

TAG_ACTION_IDS = (
    ACTION_ADD_TAG,
    ACTION_REMOVE_TAG,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REPLACE_TAGS,
)
RENAME_STRATEGIES = ("prefix", "suffix", "sequential", "numbered")

STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

ITEM_READY = "ready"
ITEM_SKIPPED = "skipped"
ITEM_BLOCKED = "blocked"

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_CONFLICT = "conflict"


class ActionNotFoundError(KeyError):
    """Raised when an Action identifier is not registered."""


@dataclass(frozen=True)
class ActionIssue:
    code: str
    severity: str
    message: str = ""
    path: str | None = None

    def __post_init__(self) -> None:
        if not self.message:
            object.__setattr__(self, "message", self.code)


@dataclass(frozen=True)
class ActionTarget:
    """One Action subject. Prefer Capixe ``image_id``; path is a hint / fallback."""

    image_id: int | None = None
    path: str | None = None

    def identity_key(self) -> str:
        if self.image_id is not None:
            return f"id:{self.image_id}"
        return f"path:{self.path or ''}"


@dataclass(frozen=True)
class ActionRequest:
    """What to run, against which targets, with which parameters."""

    action_id: str
    targets: tuple[ActionTarget, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "parameters", dict(self.parameters or {}))

    def param(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)


@dataclass(frozen=True)
class ActionItemPlan:
    target: ActionTarget
    status: str
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[ActionIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "before", dict(self.before or {}))
        object.__setattr__(self, "after", dict(self.after or {}))
        object.__setattr__(self, "issues", tuple(self.issues))


@dataclass(frozen=True)
class ActionPlan:
    """Executable preview. Callers display this; Action does not show a dialog."""

    action_id: str
    item_count: int
    executable_count: int
    confirmation_required: bool
    items: tuple[ActionItemPlan, ...] = ()
    issues: tuple[ActionIssue, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "summary", dict(self.summary or {}))


@dataclass(frozen=True)
class ActionItemResult:
    target: ActionTarget
    status: str
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    warning: str | None = None
    issues: tuple[ActionIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "before", dict(self.before or {}))
        object.__setattr__(self, "after", dict(self.after or {}))
        object.__setattr__(self, "issues", tuple(self.issues))


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    status: str
    items: tuple[ActionItemResult, ...] = ()
    issues: tuple[ActionIssue, ...] = ()
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def requested_count(self) -> int:
        return len(self.items)

    @property
    def resolved_count(self) -> int:
        return self.succeeded + self.skipped

    @property
    def changed_count(self) -> int:
        return self.succeeded

    @property
    def unchanged_count(self) -> int:
        return self.skipped

    @property
    def failed_count(self) -> int:
        return self.failed


def issue(code: str, severity: str = SEVERITY_ERROR, message: str = "", path: str | None = None) -> ActionIssue:
    return ActionIssue(code=code, severity=severity, message=message or code, path=path)


def snapshot(
    *,
    path: str | None = None,
    name: str | None = None,
    image_id: int | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": path,
        "name": name,
        "image_id": image_id,
        "tags": list(tags) if tags is not None else None,
    }
    if extra:
        data.update(dict(extra))
    return data


def overall_status(items: tuple[ActionItemResult, ...] | list[ActionItemResult]) -> str:
    if not items:
        return STATUS_FAILED
    counts = {STATUS_SUCCESS: 0, STATUS_SKIPPED: 0, STATUS_FAILED: 0, STATUS_BLOCKED: 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    success = counts.get(STATUS_SUCCESS, 0)
    failed = counts.get(STATUS_FAILED, 0) + counts.get(STATUS_BLOCKED, 0)
    if failed and success:
        return STATUS_PARTIAL
    if failed:
        return STATUS_FAILED
    return STATUS_SUCCESS


def count_statuses(items: tuple[ActionItemResult, ...] | list[ActionItemResult]) -> tuple[int, int, int]:
    succeeded = skipped = failed = 0
    for item in items:
        if item.status == STATUS_SUCCESS:
            succeeded += 1
        elif item.status == STATUS_SKIPPED:
            skipped += 1
        else:
            failed += 1
    return succeeded, skipped, failed


def result_from_items(
    action_id: str,
    items: list[ActionItemResult] | tuple[ActionItemResult, ...],
    *,
    issues: tuple[ActionIssue, ...] = (),
    status: str | None = None,
) -> ActionResult:
    packed = tuple(items)
    succeeded, skipped, failed = count_statuses(packed)
    return ActionResult(
        action_id=action_id,
        status=status or overall_status(packed),
        items=packed,
        issues=issues,
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
    )


def blocked_result(action_id: str, plan: ActionPlan, *, code: str = "confirmation_required") -> ActionResult:
    items = [
        ActionItemResult(
            target=item.target,
            status=STATUS_BLOCKED,
            before=item.before,
            after=item.after,
            error=code,
            issues=(issue(code, SEVERITY_ERROR),),
        )
        for item in plan.items
    ]
    if not items:
        items = [
            ActionItemResult(
                target=ActionTarget(),
                status=STATUS_BLOCKED,
                error=code,
                issues=(issue(code, SEVERITY_ERROR),),
            )
        ]
    return result_from_items(
        action_id,
        items,
        issues=plan.issues + (issue(code, SEVERITY_ERROR),),
        status=STATUS_BLOCKED,
    )


def plan_item_to_skipped_or_blocked(item: ActionItemPlan) -> ActionItemResult:
    status = STATUS_SKIPPED if item.status == ITEM_SKIPPED else STATUS_FAILED
    error = None
    warning = None
    for found in item.issues:
        if found.severity == SEVERITY_ERROR and error is None:
            error = found.code
        elif found.severity in {SEVERITY_WARNING, SEVERITY_CONFLICT} and warning is None:
            warning = found.code
    if item.status == ITEM_BLOCKED:
        status = STATUS_FAILED
        error = error or (item.issues[0].code if item.issues else "blocked")
    return ActionItemResult(
        target=item.target,
        status=status,
        before=item.before,
        after=item.after,
        error=error,
        warning=warning,
        issues=item.issues,
    )
