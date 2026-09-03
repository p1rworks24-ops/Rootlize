"""Reusable Find / Narrow / Action plan for Ask AI and future Automation.

AI and parsers produce this structure. They never execute. Callers confirm,
then ActionService runs each Action step in order.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from app.actions.models import (
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
    ITEM_READY,
    ITEM_SKIPPED,
    RENAME_STRATEGIES,
    TAG_ACTION_IDS,
    SEVERITY_ERROR,
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    ActionPlan,
    ActionRequest,
    ActionResult,
    ActionTarget,
    issue,
)
from app.actions.service import ActionService
from app.utils.tag_format import parse_tag_names

from .act import ActionProposal, bound_proposal, proposal_to_request
from .tag_semantics import apply_tag_removal_semantics
from .context import (
    SOURCE_FOLDER,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
)
from .semantic_safety import validate_semantic_safety
from .targets import resolve_action_targets

STEP_FIND = "find"
STEP_NARROW = "narrow"
STEP_ACTION = "action"

ALLOWED_STEP_TYPES = (STEP_FIND, STEP_NARROW, STEP_ACTION)
ALLOWED_TARGET_SOURCES = (SOURCE_RESULT_SET, SOURCE_SELECTION, SOURCE_FOLDER)
ALLOWED_ACTION_IDS = ACTION_IDS

TARGET_FILTER_KEYS = frozenset(
    {"target_count", "target_from", "except_favorites", "except_extensions"}
)

PARAM_ALLOWLIST = {
    ACTION_ADD_TAG: frozenset({"tag", "tags"}) | TARGET_FILTER_KEYS,
    ACTION_REMOVE_TAG: frozenset({"tag", "tags"}) | TARGET_FILTER_KEYS,
    ACTION_REMOVE_ALL_TAGS: TARGET_FILTER_KEYS,
    ACTION_REPLACE_TAGS: frozenset({"tag", "tags"}) | TARGET_FILTER_KEYS,
    ACTION_MOVE: frozenset({"destination_name", "destination_ref"}) | TARGET_FILTER_KEYS,
    ACTION_CREATE_FOLDER: frozenset({"name"}),
    ACTION_RENAME: frozenset(
        {
            "new_name",
            "names",
            "generate_names",
            "rename_strategy",
            "prefix",
            "suffix",
            "base_name",
            "start",
            "digits",
        }
    )
    | TARGET_FILTER_KEYS,
    ACTION_ADD_FAVORITE: TARGET_FILTER_KEYS,
    ACTION_REMOVE_FAVORITE: TARGET_FILTER_KEYS,
}
_ALLOWED_PARAM_KEYS = frozenset().union(*PARAM_ALLOWLIST.values())
_BYPASS_PARAM_KEYS = frozenset({
    "skip_confirmation",
    "execute",
    "confirmation_required",
})
_FORBIDDEN_PARAM_KEYS = frozenset({
    "destination_path",
    "parent_path",
    "paths",
    "image_ids",
    "code",
    "shell",
    "sql",
}) | _BYPASS_PARAM_KEYS

MAX_PLAN_STEPS = 8

PLAN_STATUS_PLAN = "plan"
PLAN_STATUS_CLARIFY = "clarify"
PLAN_STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class PlanStep:
    """One Find, Narrow, or registered Action. Identifiers are stable for Automation."""

    step_id: str
    type: str
    query: str = ""
    action_id: str = ""
    target_source: str = SOURCE_RESULT_SET
    parameters: Mapping[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    unsafe_parameters: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", dict(self.parameters or {}))
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

    def destination_ref(self) -> str:
        return str(self.parameters.get("destination_ref") or "").strip()


@dataclass(frozen=True)
class ActPlan:
    """Ordered Find / Narrow / Action steps. Not Ask AI specific."""

    steps: tuple[PlanStep, ...] = ()
    instruction: str = ""
    target_source: str = SOURCE_RESULT_SET

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))

    def action_steps(self) -> tuple[PlanStep, ...]:
        return tuple(step for step in self.steps if step.type == STEP_ACTION)

    def search_steps(self) -> tuple[PlanStep, ...]:
        return tuple(step for step in self.steps if step.type in {STEP_FIND, STEP_NARROW})

    def step_by_id(self, step_id: str) -> PlanStep | None:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None


@dataclass(frozen=True)
class PlanValidation:
    ok: bool
    status: str = PLAN_STATUS_PLAN
    reasons: tuple[str, ...] = ()
    message_key: str = ""
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class CombinedPreview:
    """UI-agnostic multi-step preview. Callers only display this."""

    summary: str
    detail: str
    confirm_label: str
    item_count: int
    executable: bool
    lines: tuple[str, ...] = ()
    rename_pairs: tuple[tuple[str, str], ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(self, "rename_pairs", tuple(self.rename_pairs))
        object.__setattr__(self, "issues", tuple(self.issues))


@dataclass(frozen=True)
class PreparedActPlan:
    """Validated plan plus ActionRequest / ActionPlan pairs. Still unexecuted."""

    plan: ActPlan
    requests: tuple[ActionRequest | None, ...]
    action_plans: tuple[ActionPlan | None, ...]
    preview: CombinedPreview
    validation: PlanValidation

    def __post_init__(self) -> None:
        object.__setattr__(self, "requests", tuple(self.requests))
        object.__setattr__(self, "action_plans", tuple(self.action_plans))


@dataclass(frozen=True)
class CombinedResult:
    status: str
    steps: tuple[tuple[PlanStep, ActionResult | None], ...] = ()
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))


def assign_step_ids(steps: list[PlanStep] | tuple[PlanStep, ...]) -> tuple[PlanStep, ...]:
    numbered: list[PlanStep] = []
    used: set[str] = set()
    for index, step in enumerate(steps, start=1):
        step_id = str(step.step_id or "").strip() or f"step_{index}"
        if step_id in used:
            step_id = f"step_{index}"
        used.add(step_id)
        numbered.append(replace(step, step_id=step_id))
    return tuple(numbered)


def parse_plan_payload(payload: Mapping[str, Any] | None, *, instruction: str = "") -> ActPlan:
    """Accept AI/local JSON. Does not validate capability; callers must validate."""
    data = dict(payload or {})
    raw_steps = data.get("steps") or ()
    steps: list[PlanStep] = []
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            raw_parameters = item.get("parameters")
            parameters = _coerce_parameters(raw_parameters)
            depends = item.get("depends_on") or ()
            if item.get("destination_ref") and not parameters.get("destination_ref"):
                parameters["destination_ref"] = str(item.get("destination_ref"))
            if parameters.get("destination_ref"):
                depends = tuple(depends) + (str(parameters["destination_ref"]),)
            steps.append(
                PlanStep(
                    step_id=str(item.get("id") or item.get("step_id") or f"step_{index}"),
                    type=str(item.get("type") or "").strip().lower(),
                    query=str(item.get("query") or "").strip(),
                    action_id=str(item.get("action_id") or "").strip().lower(),
                    target_source=str(item.get("target_source") or SOURCE_RESULT_SET).strip()
                    or SOURCE_RESULT_SET,
                    parameters=parameters,
                    depends_on=tuple(str(value) for value in depends if value),
                    unsafe_parameters=_has_forbidden_filesystem_params(raw_parameters),
                )
            )
    return ActPlan(
        steps=assign_step_ids(steps),
        instruction=str(instruction or data.get("instruction") or ""),
        target_source=str(data.get("target_source") or SOURCE_RESULT_SET),
    )


def _plan_destination_name(plan: ActPlan) -> str:
    for step in plan.action_steps():
        name = str(step.parameters.get("destination_name") or "").strip()
        if name:
            return name
    return ""


def _has_forbidden_filesystem_params(raw: Any) -> bool:
    if not isinstance(raw, dict):
        return False
    return bool(set(raw) & (_FORBIDDEN_PARAM_KEYS - _BYPASS_PARAM_KEYS))


def _coerce_parameters(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    parameters = dict(raw)
    names = parameters.get("names")
    if isinstance(names, list):
        mapping: dict[str, str] = {}
        for item in names:
            if not isinstance(item, dict):
                continue
            image_id = item.get("image_id")
            new_name = str(item.get("new_name") or "").strip()
            if image_id is None or not new_name:
                continue
            mapping[f"id:{int(image_id)}"] = new_name
        parameters["names"] = mapping
    elif isinstance(names, dict):
        parameters["names"] = {str(key): str(value) for key, value in names.items() if str(value).strip()}
    cleaned: dict[str, Any] = {}
    for key, value in parameters.items():
        if key in _FORBIDDEN_PARAM_KEYS or key not in _ALLOWED_PARAM_KEYS:
            continue
        if key in {"generate_names", "except_favorites"}:
            if value:
                cleaned[key] = True
            continue
        if key == "tags":
            tags = parse_tag_names(value)
            if tags:
                cleaned[key] = list(tags)
            continue
        if key in {"start", "digits", "target_count"}:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                cleaned[key] = number
            continue
        if key == "target_from":
            raw = str(value or "").strip().lower()
            if raw in {"first", "last", "all"}:
                cleaned[key] = raw
            continue
        if key == "rename_strategy":
            raw = str(value or "").strip().lower()
            if raw in RENAME_STRATEGIES:
                cleaned[key] = raw
            continue
        if key == "except_extensions":
            if isinstance(value, (list, tuple)):
                parts = [str(item).strip().lstrip(".").lower() for item in value if str(item).strip()]
            else:
                parts = [
                    piece.strip().lstrip(".").lower()
                    for piece in str(value or "").replace(";", ",").split(",")
                    if piece.strip()
                ]
            if parts:
                cleaned[key] = ",".join(parts)
            continue
        if value in ("", None, [], {}):
            continue
        cleaned[key] = value
    return cleaned


def validate_act_plan(
    plan: ActPlan,
    context: SearchResultContext | None = None,
    *,
    allow_unresolved_search: bool = False,
) -> PlanValidation:
    """Reject unknown types, unregistered Actions, bad refs, and unsafe plans."""
    ctx = context or SearchResultContext()
    reasons: list[str] = []
    if not plan.steps:
        return PlanValidation(
            False, PLAN_STATUS_REJECTED, ("empty_plan",),
            "images.ai.not_understood", "empty_plan",
        )
    if len(plan.steps) > MAX_PLAN_STEPS:
        return PlanValidation(
            False, PLAN_STATUS_REJECTED, ("too_many_steps",),
            "images.ai.plan_rejected", "too_many_steps",
        )

    safety = validate_semantic_safety(
        plan.instruction,
        intent="action",
        action_ids=tuple(step.action_id for step in plan.action_steps() if step.action_id),
        destination_name=_plan_destination_name(plan),
        context=ctx,
    )
    if safety is not None and not safety.ok:
        return PlanValidation(
            False,
            PLAN_STATUS_CLARIFY if safety.status == PLAN_STATUS_CLARIFY else PLAN_STATUS_REJECTED,
            safety.reasons,
            safety.message_key or "images.ai.plan_rejected",
            "",
        )

    plan, tag_reasons = apply_tag_removal_semantics(plan)
    if "guessed_tag" in tag_reasons:
        return PlanValidation(
            False, PLAN_STATUS_CLARIFY, ("guessed_tag",) + tuple(tag_reasons),
            "images.ai.which_tag_remove", "guessed_tag",
        )

    seen_ids: set[str] = set()
    has_search = False
    has_action = False
    for index, step in enumerate(plan.steps):
        if step.step_id in seen_ids:
            reasons.append("duplicate_step_id")
        seen_ids.add(step.step_id)
        if step.type not in ALLOWED_STEP_TYPES:
            reasons.append("unknown_step_type")
            continue
        if step.target_source not in ALLOWED_TARGET_SOURCES:
            reasons.append("invalid_target_source")
        if step.type in {STEP_FIND, STEP_NARROW}:
            has_search = True
            if not step.query:
                reasons.append("missing_query")
            if step.action_id:
                reasons.append("search_step_has_action")
            continue
        has_action = True
        if step.action_id not in ALLOWED_ACTION_IDS:
            reasons.append("unknown_action")
            continue
        if step.action_id in {ACTION_ADD_TAG, ACTION_REMOVE_TAG, ACTION_REPLACE_TAGS}:
            tags = parse_tag_names(step.parameters.get("tags") or step.parameters.get("tag"))
            if not tags:
                reasons.append("missing_parameter")
        if step.action_id == ACTION_CREATE_FOLDER and not str(step.parameters.get("name") or "").strip():
            reasons.append("missing_parameter")
        if step.action_id == ACTION_MOVE:
            dest_name = str(step.parameters.get("destination_name") or "").strip()
            dest_ref = step.destination_ref()
            if not dest_name and not dest_ref:
                reasons.append("destination_unresolved")
            if dest_ref:
                prior = plan.step_by_id(dest_ref)
                prior_index = next((i for i, item in enumerate(plan.steps) if item.step_id == dest_ref), -1)
                if prior is None or prior_index < 0 or prior_index >= index:
                    reasons.append("broken_step_reference")
                elif prior.type != STEP_ACTION or prior.action_id != ACTION_CREATE_FOLDER:
                    reasons.append("broken_step_reference")
        if step.action_id == ACTION_RENAME:
            names = step.parameters.get("names") or {}
            new_name = str(step.parameters.get("new_name") or "").strip()
            generate = bool(step.parameters.get("generate_names"))
            strategy = str(step.parameters.get("rename_strategy") or "").strip().lower()
            if not names and not new_name and not generate and strategy not in RENAME_STRATEGIES:
                reasons.append("missing_parameter")
        count = step.parameters.get("target_count")
        origin = str(step.parameters.get("target_from") or "").strip().lower()
        if count and not origin:
            reasons.append("ambiguous_quantity")
        extra = set(step.parameters) - PARAM_ALLOWLIST.get(step.action_id, frozenset())
        if step.unsafe_parameters or extra & _FORBIDDEN_PARAM_KEYS:
            reasons.append("forbidden_parameter")
        for dep in step.depends_on:
            prior_index = next((i for i, item in enumerate(plan.steps) if item.step_id == dep), -1)
            if prior_index < 0 or prior_index >= index:
                reasons.append("broken_step_reference")

    if not has_action:
        reasons.append("no_action")

    needs_targets = any(
        step.type == STEP_ACTION and step.action_id != ACTION_CREATE_FOLDER
        for step in plan.steps
    )
    if needs_targets and not has_search and not allow_unresolved_search:
        missing = False
        ambiguous = False
        for step in plan.steps:
            if step.type != STEP_ACTION or step.action_id == ACTION_CREATE_FOLDER:
                continue
            resolution = resolve_action_targets(
                step.target_source,
                ctx,
                instruction=plan.instruction,
                requested_count=_step_requested_count(step),
                requested_from=str(step.parameters.get("target_from") or ""),
            )
            if resolution.ok:
                continue
            if resolution.ambiguous:
                ambiguous = True
            else:
                missing = True
        if ambiguous:
            return PlanValidation(
                False, PLAN_STATUS_CLARIFY, ("ambiguous_targets",) + tuple(reasons),
                "images.ai.ambiguous_target", "ambiguous_targets",
            )
        if missing:
            return PlanValidation(
                False, PLAN_STATUS_CLARIFY, ("no_targets",) + tuple(reasons),
                "images.ai.missing_target", "no_targets",
            )

    if reasons:
        status = PLAN_STATUS_CLARIFY if set(reasons) <= {
            "missing_parameter",
            "destination_unresolved",
            "ambiguous_quantity",
            "ambiguous_targets",
            "ambiguous_trash_destination",
            "no_targets",
        } else PLAN_STATUS_REJECTED
        key = {
            "unknown_action": "images.ai.plan_rejected",
            "unknown_step_type": "images.ai.plan_rejected",
            "broken_step_reference": "images.ai.plan_rejected",
            "forbidden_parameter": "images.ai.plan_rejected",
            "missing_parameter": "images.ai.missing_parameter",
            "destination_unresolved": "images.ai.which_destination",
            "ambiguous_quantity": "images.ai.clarify_quantity",
            "ambiguous_targets": "images.ai.ambiguous_target",
            "no_targets": "images.ai.missing_target",
            "ambiguous_trash_destination": "images.ai.which_destination",
            "semantic_mismatch": "images.ai.not_available",
            "delete_unsupported": "images.ai.not_available_delete",
            "unsafe_tool": "images.ai.not_available_script",
        }.get(reasons[0], "images.ai.plan_rejected")
        return PlanValidation(False, status, tuple(dict.fromkeys(reasons)), key, reasons[0])
    return PlanValidation(True, PLAN_STATUS_PLAN)


def _step_depends(step: PlanStep) -> tuple[str, ...]:
    deps = list(step.depends_on)
    ref = step.destination_ref()
    if ref and ref not in deps:
        deps.append(ref)
    return tuple(deps)


def _step_requested_count(step: PlanStep) -> int | None:
    try:
        count = int(step.parameters.get("target_count") or 0)
    except (TypeError, ValueError):
        return None
    return count or None


def resolve_step_request(
    step: PlanStep,
    context: SearchResultContext,
    *,
    current_folder: Path | str | None,
    screenshot_root: Path | str | None = None,
    created_paths: Mapping[str, str] | None = None,
    instruction: str = "",
) -> ActionRequest | None:
    """Map one Action step to ActionRequest. Search steps return None."""
    if step.type != STEP_ACTION:
        return None
    parameters = {
        key: value
        for key, value in dict(step.parameters).items()
        if key in PARAM_ALLOWLIST.get(step.action_id, frozenset()) and key != "generate_names"
    }
    created = dict(created_paths or {})
    if step.action_id == ACTION_MOVE:
        ref = step.destination_ref()
        if ref and created.get(ref):
            parameters["destination_name"] = Path(created[ref]).name
            parameters.pop("destination_ref", None)
            request_params = dict(parameters)
            proposal = bound_proposal(
                ActionProposal(
                    action_id=step.action_id,
                    target_source=step.target_source,
                    parameters=request_params,
                    instruction=instruction,
                ),
                context,
                current_folder=current_folder,
            )
            request = proposal_to_request(
                proposal, current_folder=current_folder, screenshot_root=screenshot_root,
            )
            merged = dict(request.parameters)
            merged["destination_path"] = created[ref]
            return ActionRequest(action_id=request.action_id, targets=request.targets, parameters=merged)
        if ref and not created.get(ref):
            prior_name = parameters.get("destination_name")
            if not prior_name:
                parameters["destination_name"] = parameters.get("name") or ""
        parameters.pop("destination_ref", None)
    proposal = bound_proposal(
        ActionProposal(
            action_id=step.action_id,
            target_source=step.target_source,
            parameters=parameters,
            instruction=instruction,
        ),
        context,
        current_folder=current_folder,
    )
    request = proposal_to_request(
        proposal, current_folder=current_folder, screenshot_root=screenshot_root,
    )
    if step.action_id == ACTION_RENAME and isinstance(parameters.get("names"), dict):
        merged = dict(request.parameters)
        merged["names"] = dict(parameters["names"])
        request = ActionRequest(action_id=request.action_id, targets=request.targets, parameters=merged)
    return request


def apply_target_filters(request: ActionRequest, action_context) -> ActionRequest:
    """Slice / exclude targets using current UI order. Does not invent a new order."""
    if request.action_id == ACTION_CREATE_FOLDER or not request.targets:
        return request
    params = dict(request.parameters)
    targets = list(request.targets)
    except_fav = bool(params.get("except_favorites"))
    except_ext = {
        f".{piece.strip().lstrip('.').lower()}"
        for piece in str(params.get("except_extensions") or "").split(",")
        if piece.strip()
    }
    if except_fav or except_ext:
        kept: list[ActionTarget] = []
        for target in targets:
            path = Path(target.path) if target.path else None
            if path is None:
                kept.append(target)
                continue
            if except_ext and path.suffix.lower() in except_ext:
                continue
            if except_fav and getattr(action_context, "metadata", None) is not None:
                try:
                    if action_context.metadata.is_image_favorite(path.parent, path.name):
                        continue
                except OSError:
                    pass
            kept.append(target)
        targets = kept
    origin = str(params.get("target_from") or "").strip().lower()
    try:
        count = int(params.get("target_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0 and origin == "first":
        targets = targets[:count]
    elif count > 0 and origin == "last":
        targets = targets[-count:]
    return ActionRequest(request.action_id, tuple(targets), request.parameters)


def planned_create_path(
    step: PlanStep, *, current_folder: Path | str | None
) -> str | None:
    if step.action_id != ACTION_CREATE_FOLDER:
        return None
    name = str(step.parameters.get("name") or "").strip()
    if not name or not current_folder:
        return None
    return str(Path(current_folder) / name)


def prepare_act_plan(
    plan: ActPlan,
    context: SearchResultContext,
    service: ActionService,
    *,
    current_folder: Path | str | None,
    screenshot_root: Path | str | None = None,
    preview_text=None,
) -> PreparedActPlan:
    """Resolve targets and build ActionPlans. Does not execute."""
    validation = validate_act_plan(plan, context)
    requests: list[ActionRequest | None] = []
    action_plans: list[ActionPlan | None] = []
    created_paths: dict[str, str] = {}
    for step in plan.steps:
        if step.type != STEP_ACTION:
            requests.append(None)
            action_plans.append(None)
            continue
        planned = planned_create_path(step, current_folder=current_folder)
        if planned:
            created_paths[step.step_id] = planned
        request = resolve_step_request(
            step,
            context,
            current_folder=current_folder,
            screenshot_root=screenshot_root,
            created_paths=created_paths,
            instruction=plan.instruction,
        )
        if request is not None:
            request = apply_target_filters(request, service.context)
        requests.append(request)
        if request is None:
            action_plans.append(None)
            continue
        try:
            action_plans.append(service.plan(request))
        except Exception:
            action_plans.append(None)
            validation = PlanValidation(
                False, PLAN_STATUS_REJECTED, validation.reasons + ("plan_failed",),
                "images.ai.plan_rejected", "plan_failed",
            )
    preview = (preview_text or build_combined_preview)(plan, requests, action_plans, context)
    if validation.ok and not preview.executable:
        empty_targets = any(
            step.type == STEP_ACTION
            and step.action_id != ACTION_CREATE_FOLDER
            and request is not None
            and not request.targets
            for step, request in zip(plan.steps, requests)
        )
        if empty_targets:
            validation = PlanValidation(
                False, PLAN_STATUS_CLARIFY, validation.reasons + ("no_targets",),
                "images.ai.missing_target", "no_targets",
            )
        else:
            validation = PlanValidation(
                False, PLAN_STATUS_REJECTED, validation.reasons + ("not_executable",),
                "images.ai.plan_rejected", "not_executable",
            )
    return PreparedActPlan(
        plan=plan,
        requests=tuple(requests),
        action_plans=tuple(action_plans),
        preview=preview,
        validation=validation,
    )


def build_combined_preview(
    plan: ActPlan,
    requests: tuple[ActionRequest | None, ...] | list[ActionRequest | None],
    action_plans: tuple[ActionPlan | None, ...] | list[ActionPlan | None],
    context: SearchResultContext,
    *,
    t=None,
) -> CombinedPreview:
    """Structured preview. Translation is injected so this module stays UI-free."""
    translate = t or (lambda key, **kwargs: _default_preview_copy(key, kwargs))
    lines: list[str] = []
    rename_pairs: list[tuple[str, str]] = []
    issues: list[str] = []
    image_count = 0
    executable = True
    for step, request, action_plan in zip(plan.steps, requests, action_plans):
        if step.type == STEP_FIND:
            lines.append(translate("images.ai.plan_find", query=step.query))
            continue
        if step.type == STEP_NARROW:
            lines.append(translate("images.ai.plan_narrow", query=step.query))
            continue
        if request is None or action_plan is None:
            executable = False
            issues.append("missing_action_plan")
            lines.append(translate("images.ai.plan_rejected"))
            continue
        if action_plan.issues:
            for found in action_plan.issues:
                if found.severity == SEVERITY_ERROR:
                    issues.append(found.code)
        for item in action_plan.items:
            for found in item.issues:
                if found.severity == SEVERITY_ERROR:
                    issues.append(found.code)
        count = action_plan.item_count or action_plan.executable_count
        if step.action_id != ACTION_CREATE_FOLDER:
            image_count = max(image_count, count)
        runnable = sum(
            1 for item in action_plan.items if item.status in {ITEM_READY, ITEM_SKIPPED}
        )
        if runnable <= 0 and step.action_id != ACTION_CREATE_FOLDER:
            executable = False
        lines.append(_action_preview_line(step, request, action_plan, count, translate))
        if step.action_id == ACTION_MOVE and _move_will_create(action_plan):
            dest = Path(str(action_plan.summary.get("destination_path") or request.param("destination_path") or ""))
            name = dest.name or str(step.parameters.get("destination_name") or "")
            if name:
                lines.append(translate("images.ai.will_create_destination", name=name))
        if step.action_id == ACTION_REMOVE_ALL_TAGS and count:
            lines.append(translate("images.ai.plan_image_count", count=count))
        if step.action_id in TAG_ACTION_IDS:
            lines.extend(_tag_preview_detail_lines(action_plan, translate, action_id=step.action_id))
        if step.action_id == ACTION_RENAME:
            pairs = []
            for item in action_plan.items:
                before = str(item.before.get("name") or "")
                after = str(item.after.get("name") or "")
                if before or after:
                    pairs.append((before, after))
            rename_pairs.extend(pairs)
            shown = pairs[:8]
            for before, after in shown:
                lines.append(translate("images.ai.rename_from_to", before=before, after=after))
            leftover = len(pairs) - len(shown)
            if leftover > 0:
                lines.append(translate("images.ai.rename_more", count=leftover))
        if action_plan.executable_count <= 0 and step.action_id == ACTION_CREATE_FOLDER:
            skipped_ok = any(item.status == ITEM_SKIPPED for item in action_plan.items)
            if not skipped_ok:
                executable = False
    if image_count <= 0:
        image_count = len(context.result_image_ids or context.result_paths)
    summary = translate("images.ai.will_update_count", count=image_count) if image_count else translate(
        "images.ai.will_run_plan"
    )
    numbered = tuple(f"{index}. {line}" for index, line in enumerate(lines, start=1))
    return CombinedPreview(
        summary=summary,
        detail="\n".join(numbered),
        confirm_label=translate("images.ai.confirm_run"),
        item_count=image_count,
        executable=executable and bool(plan.action_steps()),
        lines=numbered,
        rename_pairs=tuple(rename_pairs),
        issues=tuple(dict.fromkeys(issues)),
    )


def _preview_tags(request) -> str:
    from app.actions.tags import format_tag_list, requested_tags

    tags = requested_tags(request)
    return format_tag_list(tags) or str(request.param("tag") or "")


def _tag_preview_detail_lines(action_plan, translate, *, action_id: str = "") -> list[str]:
    removed: list[str] = []
    added: list[str] = []
    seen_removed: set[str] = set()
    seen_added: set[str] = set()
    no_tags = 0
    for item in action_plan.items:
        if action_id == ACTION_REMOVE_ALL_TAGS and getattr(item, "status", "") == ITEM_SKIPPED:
            no_tags += 1
        for tag in item.after.get("removed_tags") or ():
            if tag and tag not in seen_removed:
                seen_removed.add(tag)
                removed.append(str(tag))
        for tag in item.after.get("added_tags") or ():
            if tag and tag not in seen_added:
                seen_added.add(tag)
                added.append(str(tag))
    lines: list[str] = []
    if removed:
        key = "images.ai.plan_tags_to_remove" if action_id == ACTION_REMOVE_ALL_TAGS else "images.ai.plan_remove_tags_detail"
        shown = removed[:8]
        lines.append(translate(key, tags=", ".join(shown)))
        leftover = len(removed) - len(shown)
        if leftover > 0:
            lines.append(translate("images.ai.plan_tags_more", count=leftover))
    if added:
        lines.append(translate("images.ai.plan_add_tags_detail", tags=", ".join(added)))
    if no_tags:
        lines.append(translate("images.ai.plan_no_tags_count", count=no_tags))
    return lines


def _action_preview_line(step, request, action_plan, count: int, translate) -> str:
    if step.action_id == ACTION_ADD_TAG:
        return translate("images.ai.plan_add_tag", tag=_preview_tags(request))
    if step.action_id == ACTION_REMOVE_TAG:
        return translate("images.ai.plan_remove_tag", tag=_preview_tags(request))
    if step.action_id == ACTION_REMOVE_ALL_TAGS:
        return translate("images.ai.preview_remove_all_tags")
    if step.action_id == ACTION_REPLACE_TAGS:
        return translate("images.ai.plan_replace_tags", tags=_preview_tags(request), count=count)
    if step.action_id == ACTION_CREATE_FOLDER:
        return translate(
            "images.ai.plan_create_folder",
            name=str(request.param("name") or step.parameters.get("name") or ""),
        )
    if step.action_id == ACTION_MOVE:
        dest = Path(str(action_plan.summary.get("destination_path") or request.param("destination_path") or ""))
        name = dest.name or str(step.parameters.get("destination_name") or "")
        return translate("images.ai.plan_move", count=count, name=name)
    if step.action_id == ACTION_RENAME:
        return translate("images.ai.plan_rename", count=count)
    if step.action_id == ACTION_ADD_FAVORITE:
        return translate("images.ai.plan_add_favorite", count=count)
    if step.action_id == ACTION_REMOVE_FAVORITE:
        return translate("images.ai.plan_remove_favorite", count=count)
    return translate("images.ai.not_understood")


def _move_will_create(action_plan) -> bool:
    summary = getattr(action_plan, "summary", None) or {}
    if summary.get("destination_will_create"):
        return True
    return any(
        getattr(found, "code", "") == "destination_will_create"
        for found in getattr(action_plan, "issues", ()) or ()
    )


def _default_preview_copy(key: str, kwargs: Mapping[str, Any]) -> str:
    templates = {
        "images.ai.will_update_count": "{count} images will be updated",
        "images.ai.will_run_plan": "These steps will run",
        "images.ai.plan_find": "Find: {query}",
        "images.ai.plan_narrow": "Narrow to: {query}",
        "images.ai.plan_add_tag": "Add tag: {tag}",
        "images.ai.plan_remove_tag": "Remove tag: {tag}",
        "images.ai.plan_remove_all_tags": "Remove all tags from {count} images",
        "images.ai.preview_remove_all_tags": "Remove all tags",
        "images.ai.plan_tags_to_remove": "Tags to remove: {tags}",
        "images.ai.plan_tags_more": "…and {count} more",
        "images.ai.plan_no_tags_count": "{count} image has no tags",
        "images.ai.plan_image_count": "{count} images",
        "images.ai.plan_replace_tags": "Replace tags with {tags} on {count} images",
        "images.ai.plan_add_tags_detail": "Add: {tags}",
        "images.ai.plan_remove_tags_detail": "Remove: {tags}",
        "images.ai.plan_create_folder": "Create folder: {name}",
        "images.ai.will_create_destination": "Folder “{name}” does not exist yet and will be created.",
        "images.ai.plan_move": "Move {count} images to {name}",
        "images.ai.plan_rename": "Rename {count} images",
        "images.ai.plan_add_favorite": "Add favorite to {count} images",
        "images.ai.plan_remove_favorite": "Remove favorite from {count} images",
        "images.ai.rename_from_to": "{before} → {after}",
        "images.ai.rename_more": "…and {count} more",
        "images.ai.confirm_run": "Run",
        "images.ai.plan_rejected": "That plan is not safe to run.",
        "images.ai.not_understood": "The requested action was not understood.",
    }
    text = templates.get(key, key)
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def _result_failed(result: ActionResult | None) -> bool:
    if result is None:
        return True
    return result.status in {STATUS_FAILED, STATUS_BLOCKED} and result.succeeded <= 0


def _request_for_step(
    step: PlanStep,
    prepared: PreparedActPlan,
    ctx: SearchResultContext,
    *,
    current_folder: Path | str | None,
    screenshot_root: Path | str | None,
    created_paths: Mapping[str, str],
) -> ActionRequest | None:
    """Prefer the previewed request so Confirm executes the same targets."""
    prepared_by_id = {
        plan_step.step_id: request
        for plan_step, request in zip(prepared.plan.steps, prepared.requests)
    }
    request = prepared_by_id.get(step.step_id)
    if request is None:
        return resolve_step_request(
            step,
            ctx,
            current_folder=current_folder,
            screenshot_root=screenshot_root,
            created_paths=created_paths,
        )
    if step.action_id == ACTION_MOVE:
        ref = step.destination_ref()
        if ref and created_paths.get(ref):
            merged = dict(request.parameters)
            merged["destination_path"] = created_paths[ref]
            return ActionRequest(
                action_id=request.action_id,
                targets=request.targets,
                parameters=merged,
            )
    return request


def _remap_request_paths(
    request: ActionRequest,
    *,
    id_paths: Mapping[int, str],
    path_map: Mapping[str, str],
) -> ActionRequest:
    if not request.targets or (not id_paths and not path_map):
        return request
    remapped: list[ActionTarget] = []
    for target in request.targets:
        path = target.path
        if target.image_id is not None and int(target.image_id) in id_paths:
            path = id_paths[int(target.image_id)]
        elif path:
            path = path_map.get(str(Path(path)), path)
        remapped.append(ActionTarget(image_id=target.image_id, path=path))
    return ActionRequest(request.action_id, tuple(remapped), request.parameters)


def _remember_path_changes(
    result: ActionResult,
    *,
    id_paths: dict[int, str],
    path_map: dict[str, str],
) -> None:
    if result.action_id not in {ACTION_MOVE, ACTION_RENAME}:
        return
    for item in result.items:
        if item.status != STATUS_SUCCESS:
            continue
        before = str((item.before or {}).get("path") or "")
        after = str((item.after or {}).get("path") or "")
        if not after:
            continue
        image_id = item.target.image_id
        if image_id is None:
            image_id = (item.after or {}).get("image_id") or (item.before or {}).get("image_id")
        if image_id is not None:
            id_paths[int(image_id)] = after
        if before:
            path_map[before] = after
            try:
                path_map[str(Path(before))] = after
            except OSError:
                pass


_IN_FLIGHT_PREPARED: list[PreparedActPlan] = []


def execute_act_plan(
    prepared: PreparedActPlan,
    service: ActionService,
    *,
    confirmed: bool = False,
    current_folder: Path | str | None = None,
    screenshot_root: Path | str | None = None,
    context: SearchResultContext | None = None,
) -> CombinedResult:
    """Run Action steps in order after caller confirmation. Search steps are skipped.

    Prerequisite failures skip dependent steps. Independent steps still run.
    Path-changing steps remap later targets. Re-entrant execute of the same
    prepared plan is rejected; sequential Confirm is guarded in the UI.
    """
    ctx = context or SearchResultContext()
    if not confirmed:
        blocked = []
        for step, request in zip(prepared.plan.steps, prepared.requests):
            if step.type != STEP_ACTION or request is None:
                blocked.append((step, None))
                continue
            blocked.append((step, service.execute(request, confirmed=False)))
        return CombinedResult(status=STATUS_BLOCKED, steps=tuple(blocked), summary="confirmation_required")

    if any(item is prepared for item in _IN_FLIGHT_PREPARED):
        return CombinedResult(status=STATUS_FAILED, summary="already_executed")
    _IN_FLIGHT_PREPARED.append(prepared)
    try:
        return _execute_act_plan_confirmed(
            prepared,
            service,
            current_folder=current_folder,
            screenshot_root=screenshot_root,
            ctx=ctx,
        )
    finally:
        _IN_FLIGHT_PREPARED.remove(prepared)


def _execute_act_plan_confirmed(
    prepared: PreparedActPlan,
    service: ActionService,
    *,
    current_folder: Path | str | None,
    screenshot_root: Path | str | None,
    ctx: SearchResultContext,
) -> CombinedResult:
    results: dict[str, ActionResult | None] = {}
    skipped: set[str] = set()
    created_paths: dict[str, str] = {}
    id_paths: dict[int, str] = {}
    path_map: dict[str, str] = {}
    ordered: list[tuple[PlanStep, ActionResult | None]] = []
    succeeded = skipped_count = failed = 0

    for step in prepared.plan.steps:
        if step.type != STEP_ACTION:
            ordered.append((step, None))
            continue
        deps = _step_depends(step)
        blocked_by_dep = False
        for dep in deps:
            if dep in skipped or _result_failed(results.get(dep)):
                blocked_by_dep = True
                break
        if blocked_by_dep:
            skipped.add(step.step_id)
            skipped_count += 1
            skip_result = ActionResult(
                action_id=step.action_id,
                status=STATUS_SKIPPED,
                issues=(issue("prerequisite_failed", SEVERITY_ERROR, "A required earlier step failed."),),
                skipped=1,
            )
            results[step.step_id] = skip_result
            ordered.append((step, skip_result))
            continue
        request = _request_for_step(
            step,
            prepared,
            ctx,
            current_folder=current_folder,
            screenshot_root=screenshot_root,
            created_paths=created_paths,
        )
        if request is None:
            failed += 1
            ordered.append((step, None))
            continue
        request = _remap_request_paths(request, id_paths=id_paths, path_map=path_map)
        result = service.execute(request, confirmed=True)
        results[step.step_id] = result
        ordered.append((step, result))
        if step.action_id == ACTION_CREATE_FOLDER:
            for item in result.items:
                path = (item.after or {}).get("path")
                if path:
                    created_paths[step.step_id] = str(path)
        _remember_path_changes(result, id_paths=id_paths, path_map=path_map)
        if result.status == STATUS_SUCCESS or result.succeeded:
            succeeded += 1
        elif result.status == STATUS_SKIPPED and not result.failed:
            skipped_count += 1
        else:
            failed += 1
            skipped.add(step.step_id)

    if failed and succeeded:
        status = "partial"
    elif failed:
        status = STATUS_FAILED
    else:
        status = STATUS_SUCCESS
    return CombinedResult(
        status=status,
        steps=tuple(ordered),
        succeeded=succeeded,
        skipped=skipped_count,
        failed=failed,
    )


_ACTION_MESSAGES = {
    ACTION_MOVE: {
        "done": "images.ai.act_done_move",
        "partial": "images.ai.act_done_move_partial",
        "unchanged": "images.ai.act_already_moved",
    },
    ACTION_RENAME: {
        "done": "images.ai.act_done_rename",
        "partial": "images.ai.act_done_rename_partial",
        "unchanged": "images.ai.act_already_renamed",
    },
    ACTION_ADD_TAG: {
        "done": "images.ai.act_done_tag",
        "partial": "images.ai.act_done_tag_partial",
        "unchanged": "images.ai.act_already_tag",
    },
    ACTION_REMOVE_TAG: {
        "done": "images.ai.act_done_remove_tag",
        "partial": "images.ai.act_done_remove_tag_partial",
        "unchanged": "images.ai.act_already_untag",
    },
    ACTION_REMOVE_ALL_TAGS: {
        "done": "images.ai.act_done_remove_all_tags",
        "partial": "images.ai.act_done_remove_all_tags_partial",
        "unchanged": "images.ai.act_already_no_tags",
    },
    ACTION_REPLACE_TAGS: {
        "done": "images.ai.act_done_replace_tags",
        "partial": "images.ai.act_done_replace_tags_partial",
        "unchanged": "images.ai.act_already_replace_tags",
    },
    ACTION_CREATE_FOLDER: {
        "done": "images.ai.act_done_folder",
        "failed": "images.ai.act_folder_exists",
    },
    ACTION_ADD_FAVORITE: {
        "done": "images.ai.act_done_favorite",
        "partial": "images.ai.act_done_favorite_partial",
        "unchanged": "images.ai.act_already_favorite",
    },
    ACTION_REMOVE_FAVORITE: {
        "done": "images.ai.act_done_unfavorite",
        "partial": "images.ai.act_done_unfavorite_partial",
        "unchanged": "images.ai.act_already_unfavorite",
    },
}


def _default_result_copy(key: str, kwargs: Mapping[str, Any]) -> str:
    templates = {
        "images.ai.act_done_move": "Moved {count} images.",
        "images.ai.act_done_move_partial": (
            "Moved {changed} of {requested} images. {failed} image could not be moved."
        ),
        "images.ai.act_already_moved": "No images needed to be moved.",
        "images.ai.act_done_tag": 'Added "{tag}" to {count} images.',
        "images.ai.act_done_tag_partial": (
            'Added "{tag}" to {changed} of {requested} images. {failed} image could not be updated.'
        ),
        "images.ai.act_already_tag": 'All {count} images already have the "{tag}" tag.',
        "images.ai.act_done_remove_tag": 'Removed "{tag}" from {count} images.',
        "images.ai.act_done_remove_tag_partial": (
            'Removed "{tag}" from {changed} of {requested} images. {failed} image could not be updated.'
        ),
        "images.ai.act_already_untag": 'None of the selected images had the "{tag}" tag.',
        "images.ai.act_done_remove_all_tags": "Removed all tags from {count} images.",
        "images.ai.act_done_remove_all_tags_partial": (
            "Removed all tags from {changed} of {requested} images. {failed} image could not be updated."
        ),
        "images.ai.act_already_no_tags": "None of the {count} images had tags to remove.",
        "images.ai.act_no_tags_note": "{count} image already had no tags.",
        "images.ai.act_done_replace_tags": "Replaced tags with {tag} on {count} images.",
        "images.ai.act_done_replace_tags_partial": (
            "Replaced tags on {changed} of {requested} images. {failed} image could not be updated."
        ),
        "images.ai.act_already_replace_tags": "All {count} images already had those tags.",
        "images.ai.act_done_rename": "Renamed {count} images.",
        "images.ai.act_done_rename_partial": (
            "Renamed {changed} of {requested} images. {failed} image could not be renamed."
        ),
        "images.ai.act_already_renamed": "The image already has that name.",
        "images.ai.act_done_folder": 'Created folder "{name}".',
        "images.ai.act_folder_exists": 'Folder "{name}" already exists.',
        "images.ai.act_done_favorite": "Added Favorite to {count} images.",
        "images.ai.act_done_unfavorite": "Removed Favorite from {count} images.",
        "images.ai.act_done_favorite_partial": (
            "Added Favorite to {changed} of {requested} images. {failed} image could not be updated."
        ),
        "images.ai.act_done_unfavorite_partial": (
            "Removed Favorite from {changed} of {requested} images. {failed} image could not be updated."
        ),
        "images.ai.act_already_favorite": "All {count} images were already favorited.",
        "images.ai.act_already_unfavorite": "None of the {count} images were favorites.",
        "images.ai.act_no_changes": "No changes were needed.",
        "images.ai.act_no_targets": "I couldn't find any images to update.",
        "images.ai.act_done_plan": "Finished {succeeded} steps.",
        "images.ai.act_done_plan_partial": "Finished {succeeded} steps. Skipped {skipped}. Failed {failed}.",
        "images.ai.execute_failed": "The images could not be updated.",
        "images.ai.plan_rejected": "That plan is not safe to run.",
    }
    text = templates.get(key, key)
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def combined_item_counts(result: CombinedResult) -> tuple[int, int, int]:
    """Sum ActionResult item counts. CombinedResult.succeeded stays step-level."""
    succeeded = skipped = failed = 0
    for step, item in result.steps:
        if item is None:
            if step.type == STEP_ACTION:
                failed += 1
            continue
        succeeded += item.succeeded
        skipped += item.skipped
        failed += item.failed
    return succeeded, skipped, failed


def action_result_is_user_failure(result: ActionResult) -> bool:
    """True when the user should not see a completed-change message."""
    if result.changed_count > 0:
        return False
    if result.unchanged_count > 0 and result.failed_count == 0:
        return False
    return True


def combined_result_is_user_failure(result: CombinedResult) -> bool:
    changed, unchanged, failed = combined_item_counts(result)
    if result.status == STATUS_BLOCKED:
        return True
    if changed > 0:
        return False
    if unchanged > 0 and failed == 0:
        return False
    return bool(failed or result.failed or not result.succeeded)


def _result_message_kwargs(result: ActionResult, parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    params = dict(parameters or {})
    tags = parse_tag_names(params.get("tags") or params.get("tag"))
    tag = ", ".join(tags) if tags else str(params.get("tag") or "").strip()
    name = str(params.get("name") or params.get("new_name") or "").strip()
    if not name and result.items:
        name = str((result.items[0].after or {}).get("name") or (result.items[0].before or {}).get("name") or "")
    count = result.changed_count or result.unchanged_count or result.requested_count
    return {
        "count": count,
        "changed": result.changed_count,
        "requested": result.requested_count,
        "failed": result.failed_count,
        "skipped": result.unchanged_count,
        "succeeded": result.changed_count,
        "tag": tag,
        "name": name,
    }


def summarize_action_result(result: ActionResult, *, t=None, parameters: Mapping[str, Any] | None = None) -> str:
    """Completion text from executed ActionResult counts, not the planned preview."""
    translate = t or (lambda key, **kwargs: _default_result_copy(key, kwargs))
    copy = _ACTION_MESSAGES.get(result.action_id, {})
    kwargs = _result_message_kwargs(result, parameters)
    changed = result.changed_count
    unchanged = result.unchanged_count
    failed = result.failed_count
    requested = result.requested_count

    if result.action_id == ACTION_CREATE_FOLDER:
        if changed:
            return translate(copy["done"], **kwargs)
        codes = {item.error for item in result.items} | {found.code for found in result.issues}
        for item in result.items:
            codes.update(found.code for found in item.issues)
        if "folder_exists" in codes:
            return translate("images.ai.act_folder_exists", **kwargs)
        return translate("images.ai.execute_failed")

    if requested <= 0 or (changed == 0 and unchanged == 0):
        return translate("images.ai.act_no_targets")
    if changed == 0 and failed == 0:
        return translate(copy.get("unchanged") or "images.ai.act_no_changes", **kwargs)
    if changed and failed:
        return translate(
            copy.get("partial") or "images.ai.act_done_plan_partial",
            **kwargs,
        )
    text = translate(copy.get("done") or "images.ai.act_done_plan", **kwargs)
    if changed and unchanged and not failed and result.action_id == ACTION_REMOVE_ALL_TAGS:
        note = translate("images.ai.act_no_tags_note", count=unchanged)
        return f"{text} {note}".strip()
    return text


def summarize_combined_result(result: CombinedResult, *, t=None) -> str:
    translate = t or (lambda key, **kwargs: _default_result_copy(key, kwargs))
    if result.status == STATUS_BLOCKED:
        return translate("images.ai.plan_rejected")
    action_results = [
        (step, item)
        for step, item in result.steps
        if step.type == STEP_ACTION and item is not None
    ]
    if not action_results:
        return translate("images.ai.act_no_targets")
    if len(action_results) == 1:
        step, item = action_results[0]
        return summarize_action_result(item, t=translate, parameters=step.parameters)
    return " ".join(
        summarize_action_result(item, t=translate, parameters=step.parameters)
        for step, item in action_results
    )
