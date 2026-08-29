"""Save, validate, preview, and execute Workflows through existing Action APIs."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.actions.models import STATUS_FAILED
from app.actions.service import ActionService
from app.workspace.context import ORIGIN_BROWSE, ORIGIN_MEANING, SearchResultContext
from app.workspace.plan import (
    PLAN_STATUS_REJECTED,
    CombinedResult,
    PlanValidation,
    PreparedActPlan,
    STEP_FIND,
    STEP_NARROW,
    execute_act_plan,
    prepare_act_plan,
    validate_act_plan,
)

from .models import Workflow, utc_now, workflow_step_issues
from .store import WorkflowStore


class SearchEvaluator(Protocol):
    """Re-evaluate Find / Narrow. Must not execute Actions."""

    def evaluate_find(
        self, query: str, scope_folder: str | None, origin: str
    ) -> SearchResultContext: ...

    def evaluate_narrow(self, query: str, context: SearchResultContext) -> SearchResultContext: ...


class AutomationService:
    """Workflow CRUD plus prepare/execute. File changes go through ActionService."""

    def __init__(self, store: WorkflowStore | None = None) -> None:
        self.store = store or WorkflowStore()

    def list_workflows(self) -> tuple[Workflow, ...]:
        return tuple(sorted(self.store.list(), key=lambda item: item.updated_at or item.created_at, reverse=True))

    def get(self, workflow_id: str) -> Workflow | None:
        return self.store.get(workflow_id)

    def save(self, workflow: Workflow) -> Workflow:
        validation = validate_workflow(workflow)
        if not validation.ok:
            raise WorkflowValidationError(validation)
        return self.store.save(workflow)

    def save_draft(self, workflow: Workflow) -> Workflow:
        """Persist an editor document. Rejects unsafe types; allows incomplete steps."""
        from app.automation.models import workflow_step_issues
        from app.workspace.plan import PLAN_STATUS_REJECTED, PlanValidation

        label = str(workflow.name or "").strip()
        if not label:
            raise WorkflowValidationError(
                PlanValidation(
                    False,
                    PLAN_STATUS_REJECTED,
                    ("missing_name",),
                    "automation.name_required",
                    "missing_name",
                )
            )
        blocked = [
            reason
            for reason in workflow_step_issues(workflow)
            if reason in {"unknown_step_type", "unknown_action", "forbidden_parameter"}
        ]
        if blocked:
            raise WorkflowValidationError(
                PlanValidation(
                    False,
                    PLAN_STATUS_REJECTED,
                    tuple(blocked),
                    "images.ai.plan_rejected",
                    blocked[0],
                )
            )
        return self.store.save(workflow)

    def rename(self, workflow_id: str, name: str, *, description: str | None = None) -> Workflow | None:
        label = str(name or "").strip()
        if not label:
            return None
        return self.store.rename(workflow_id, label, description=description)

    def delete(self, workflow_id: str) -> bool:
        return self.store.delete(workflow_id)

    def record_run(self, workflow_id: str, *, at: str | None = None) -> Workflow | None:
        current = self.get(workflow_id)
        if current is None:
            return None
        return self.store.save(current.with_last_run(at or utc_now()))

    def evaluate_search(
        self,
        workflow: Workflow,
        evaluator: SearchEvaluator,
    ) -> tuple[SearchResultContext, PlanValidation]:
        """Re-run Find / Narrow. Never reuses stored image_id / path sets."""
        structural = validate_workflow(workflow)
        if not structural.ok:
            return SearchResultContext(scope_folder=workflow.scope_folder, origin=workflow.origin), structural
        if workflow.scope_folder:
            folder = Path(workflow.scope_folder)
            try:
                exists = folder.is_dir()
            except OSError:
                exists = False
            if not exists:
                return SearchResultContext(
                    scope_folder=workflow.scope_folder, origin=workflow.origin
                ), PlanValidation(
                    False,
                    PLAN_STATUS_REJECTED,
                    ("missing_folder",),
                    "automation.missing_folder",
                    "missing_folder",
                )
        origin = workflow.origin or ORIGIN_MEANING
        context = SearchResultContext(
            scope_folder=workflow.scope_folder,
            origin=origin,
        )
        search_steps = [step for step in workflow.steps if step.type in {STEP_FIND, STEP_NARROW}]
        if not search_steps:
            context = evaluator.evaluate_find("", workflow.scope_folder, ORIGIN_BROWSE)
        for step in workflow.steps:
            if step.type == STEP_FIND:
                context = evaluator.evaluate_find(step.query, workflow.scope_folder, origin)
            elif step.type == STEP_NARROW:
                context = evaluator.evaluate_narrow(step.query, context)
        if not context.has_targets() and any(
            step.type != STEP_FIND and step.type != STEP_NARROW and step.action_id != "create_folder"
            for step in workflow.steps
        ):
            return context, PlanValidation(
                False,
                PLAN_STATUS_REJECTED,
                ("no_targets",),
                "images.ai.no_matches",
                "no_targets",
            )
        return context, PlanValidation(True, "plan")

    def prepare(
        self,
        workflow: Workflow,
        context: SearchResultContext,
        service: ActionService,
        *,
        current_folder: Path | str | None = None,
        screenshot_root: Path | str | None = None,
        preview_text=None,
    ) -> PreparedActPlan:
        validation = validate_workflow(workflow, context)
        prepared = prepare_act_plan(
            workflow.plan,
            context,
            service,
            current_folder=current_folder or workflow.scope_folder,
            screenshot_root=screenshot_root,
            preview_text=preview_text,
        )
        if not validation.ok:
            return PreparedActPlan(
                plan=prepared.plan,
                requests=prepared.requests,
                action_plans=prepared.action_plans,
                preview=prepared.preview,
                validation=validation,
            )
        return prepared

    def execute(
        self,
        prepared: PreparedActPlan,
        service: ActionService,
        *,
        confirmed: bool = False,
        current_folder: Path | str | None = None,
        screenshot_root: Path | str | None = None,
        context: SearchResultContext | None = None,
    ) -> CombinedResult:
        if not confirmed:
            return execute_act_plan(
                prepared,
                service,
                confirmed=False,
                current_folder=current_folder,
                screenshot_root=screenshot_root,
                context=context,
            )
        if not prepared.validation.ok:
            return CombinedResult(status=STATUS_FAILED, summary=prepared.validation.message or "rejected")
        return execute_act_plan(
            prepared,
            service,
            confirmed=True,
            current_folder=current_folder,
            screenshot_root=screenshot_root,
            context=context,
        )


class WorkflowValidationError(ValueError):
    def __init__(self, validation: PlanValidation) -> None:
        super().__init__(validation.message or validation.reasons[0] if validation.reasons else "invalid_workflow")
        self.validation = validation


def validate_workflow(
    workflow: Workflow,
    context: SearchResultContext | None = None,
) -> PlanValidation:
    reasons = list(workflow_step_issues(workflow))
    if reasons:
        key = {
            "unknown_action": "images.ai.plan_rejected",
            "unknown_step_type": "images.ai.plan_rejected",
            "forbidden_parameter": "images.ai.plan_rejected",
            "empty_plan": "images.ai.not_understood",
            "no_action": "images.ai.plan_rejected",
            "missing_name": "automation.name_required",
        }.get(reasons[0], "images.ai.plan_rejected")
        return PlanValidation(False, PLAN_STATUS_REJECTED, tuple(reasons), key, reasons[0])
    if not workflow.enabled:
        return PlanValidation(
            False, PLAN_STATUS_REJECTED, ("disabled",), "automation.disabled", "disabled"
        )
    return validate_act_plan(workflow.plan, context, allow_unresolved_search=True)


STATUS_REASON_KEYS = {
    "no_action": "automation.status_need_action",
    "empty_plan": "automation.status_need_action",
    "missing_query": "automation.status_need_query",
    "missing_name": "automation.name_required",
    "missing_folder": "automation.missing_folder",
    "disabled": "automation.disabled",
}


def workflow_run_status(workflow: Workflow) -> tuple[str, str]:
    """User-facing runnability. Returns ('ready'|'blocked', message_key)."""
    if workflow.scope_folder:
        try:
            if not Path(workflow.scope_folder).is_dir():
                return "blocked", "automation.missing_folder"
        except OSError:
            return "blocked", "automation.missing_folder"
    elif not workflow.scope_folder:
        return "blocked", "automation.status_need_folder"
    validation = validate_workflow(workflow)
    if validation.ok:
        return "ready", "automation.status_ready"
    reason = validation.reasons[0] if validation.reasons else "invalid"
    return "blocked", STATUS_REASON_KEYS.get(reason, validation.message_key or "automation.invalid")


LIST_STATUS_LABELS = {
    "ready": "automation.status_ready",
    "running": "automation.status_running",
    "needs_action": "automation.status_needs_action",
    "error": "automation.status_error",
    "disabled": "automation.status_disabled",
}

LIST_STATUS_HINTS = {
    "automation.status_ready": "automation.status_ready_hint",
    "automation.status_need_action": "automation.status_need_action_hint",
    "automation.status_need_query": "automation.status_need_query_hint",
    "automation.status_need_folder": "automation.status_need_folder_hint",
    "automation.missing_folder": "automation.missing_folder",
    "automation.invalid": "automation.invalid",
    "automation.disabled": "automation.disabled",
    "automation.name_required": "automation.name_required",
}

_ERROR_STATUS_KEYS = frozenset(
    {
        "automation.missing_folder",
        "automation.invalid",
    }
)


_LIST_STATUS_DISPLAY = {
    "automation.status_need_action": "automation.status_need_action",
    "automation.status_need_query": "automation.status_need_query",
    "automation.status_need_folder": "automation.status_need_folder",
    "automation.missing_folder": "automation.status_folder_missing",
    "automation.invalid": "automation.invalid",
    "automation.disabled": LIST_STATUS_LABELS["disabled"],
    "automation.name_required": "automation.name_required",
}


def workflow_list_status(workflow: Workflow) -> tuple[str, str, str]:
    """List badge: (kind, label_key, hint_key). kind is ready|running|needs_action|error|disabled."""
    if not workflow.enabled:
        return "disabled", LIST_STATUS_LABELS["disabled"], "automation.disabled"
    code, reason_key = workflow_run_status(workflow)
    hint_key = LIST_STATUS_HINTS.get(reason_key, reason_key)
    if code == "ready":
        return "ready", LIST_STATUS_LABELS["ready"], hint_key
    if reason_key == "automation.disabled":
        return "disabled", LIST_STATUS_LABELS["disabled"], hint_key
    label_key = _LIST_STATUS_DISPLAY.get(reason_key, reason_key)
    if reason_key in _ERROR_STATUS_KEYS:
        return "error", label_key, hint_key
    return "needs_action", label_key, hint_key


class FilenameSearchEvaluator:
    """Deterministic local evaluator for tests. Product UI uses Meaning Search."""

    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    def evaluate_find(
        self, query: str, scope_folder: str | None, origin: str
    ) -> SearchResultContext:
        folder = Path(scope_folder) if scope_folder else None
        if folder is None:
            return SearchResultContext(query=query, origin=origin)
        try:
            exists = folder.is_dir()
        except OSError:
            exists = False
        if not exists:
            return SearchResultContext(query=query, scope_folder=str(folder), origin=origin)
        needle = str(query or "").casefold()
        paths: list[Path] = []
        for path in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
            try:
                if not path.is_file() or path.suffix.lower() not in self.IMAGE_SUFFIXES:
                    continue
            except OSError:
                continue
            if needle and needle not in path.name.casefold():
                continue
            paths.append(path)
        return self._context_from_paths(paths, query=query, folder=folder, origin=origin, narrowed=False)

    def evaluate_narrow(self, query: str, context: SearchResultContext) -> SearchResultContext:
        needle = str(query or "").casefold()
        kept_paths = []
        kept_ids = []
        for index, path in enumerate(context.result_paths):
            name = Path(path).name.casefold()
            if needle and needle not in name:
                continue
            kept_paths.append(path)
            if index < len(context.result_image_ids):
                kept_ids.append(context.result_image_ids[index])
        if not kept_ids:
            kept_ids = [
                context.path_to_image_id[path]
                for path in kept_paths
                if path in context.path_to_image_id
            ]
        return context.with_results(
            image_ids=tuple(kept_ids),
            paths=kept_paths,
            query=query,
            scope_folder=context.scope_folder,
            origin=context.origin or ORIGIN_MEANING,
            narrowed=True,
            path_to_image_id=context.path_to_image_id,
        )

    def _context_from_paths(
        self,
        paths: list[Path],
        *,
        query: str,
        folder: Path,
        origin: str,
        narrowed: bool,
    ) -> SearchResultContext:
        mapping = {str(path.resolve()): index + 1 for index, path in enumerate(paths)}
        return SearchResultContext().with_results(
            image_ids=tuple(mapping[str(path.resolve())] for path in paths),
            paths=[str(path) for path in paths],
            query=query,
            scope_folder=folder,
            origin=origin,
            narrowed=narrowed,
            path_to_image_id=mapping,
        )
