"""Saved Find → Narrow → Act workflows. Execution stays in app.actions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from app.actions.models import ACTION_IDS
from app.workspace.context import ORIGIN_MEANING
from app.workspace.plan import (
    ALLOWED_ACTION_IDS,
    ALLOWED_STEP_TYPES,
    PARAM_ALLOWLIST,
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    ActPlan,
    PlanStep,
    assign_step_ids,
    parse_plan_payload,
)

WORKFLOW_FORMAT_VERSION = 1
FORBIDDEN_PARAM_KEYS = frozenset(
    {
        "destination_path",
        "parent_path",
        "paths",
        "image_ids",
        "code",
        "shell",
        "sql",
        "command",
        "script",
    }
)
FORBIDDEN_STEP_TYPES = frozenset({"shell", "sql", "code", "python", "loop", "if", "else"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def format_list_date(stamp: str, *, with_time: bool = False) -> str:
    text = str(stamp or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10] if len(text) >= 10 else text
    if with_time:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return parsed.strftime("%Y-%m-%d")


def new_workflow_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class Workflow:
    """Named ActPlan plus folder/origin metadata. Not an execution engine."""

    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    enabled: bool = True
    scope_folder: str | None = None
    origin: str = ORIGIN_MEANING
    steps: tuple[PlanStep, ...] = ()
    last_run_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", assign_step_ids(self.steps))
        object.__setattr__(self, "name", str(self.name or "").strip())
        object.__setattr__(self, "description", str(self.description or "").strip())
        object.__setattr__(self, "origin", str(self.origin or ORIGIN_MEANING))
        folder = str(self.scope_folder or "").strip() or None
        object.__setattr__(self, "scope_folder", folder)

    @property
    def plan(self) -> ActPlan:
        return ActPlan(steps=self.steps, instruction=self.name)

    def with_last_run(self, last_run_at: str | None = None) -> Workflow:
        return replace(self, last_run_at=str(last_run_at or utc_now()))

    def with_name(self, name: str, *, description: str | None = None) -> Workflow:
        return replace(
            self,
            name=str(name or "").strip(),
            description=self.description if description is None else str(description or "").strip(),
            updated_at=utc_now(),
        )

    def with_document(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        steps: tuple[PlanStep, ...] | None = None,
        scope_folder: str | None | bool = False,
    ) -> Workflow:
        folder = self.scope_folder if scope_folder is False else (str(scope_folder or "").strip() or None)
        return replace(
            self,
            name=self.name if name is None else str(name or "").strip(),
            description=self.description if description is None else str(description or "").strip(),
            steps=self.steps if steps is None else assign_step_ids(steps),
            scope_folder=folder,
            updated_at=utc_now(),
        )


def sanitize_step_parameters(action_id: str, parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    allowed = PARAM_ALLOWLIST.get(action_id, frozenset())
    cleaned: dict[str, Any] = {}
    for key, value in dict(parameters or {}).items():
        if key in FORBIDDEN_PARAM_KEYS:
            continue
        if key not in allowed:
            continue
        if key == "generate_names":
            if value:
                cleaned[key] = True
            continue
        if key == "except_favorites":
            if value:
                cleaned[key] = True
            continue
        if key == "tags" and isinstance(value, (list, tuple)):
            cleaned[key] = [str(item) for item in value if str(item).strip()]
            continue
        if value in ("", None, [], {}):
            continue
        cleaned[key] = value
    if action_id == "move":
        dest_name = str(cleaned.get("destination_name") or "").strip()
        if dest_name:
            cleaned["destination_name"] = dest_name
        cleaned.pop("destination_path", None)
    return cleaned


def workflow_to_payload(workflow: Workflow) -> dict[str, Any]:
    steps = []
    for step in workflow.steps:
        item: dict[str, Any] = {
            "id": step.step_id,
            "type": step.type,
        }
        if step.query:
            item["query"] = step.query
        if step.action_id:
            item["action_id"] = step.action_id
        if step.target_source:
            item["target_source"] = step.target_source
        parameters = sanitize_step_parameters(step.action_id, step.parameters) if step.type == STEP_ACTION else {}
        if parameters:
            item["parameters"] = parameters
        if step.depends_on:
            item["depends_on"] = list(step.depends_on)
        steps.append(item)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "last_run_at": workflow.last_run_at,
        "enabled": bool(workflow.enabled),
        "scope_folder": workflow.scope_folder,
        "origin": workflow.origin,
        "steps": steps,
    }


def workflow_from_payload(payload: Mapping[str, Any] | None) -> Workflow | None:
    data = dict(payload or {})
    workflow_id = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not workflow_id or not name:
        return None
    plan = parse_plan_payload({"steps": data.get("steps") or []}, instruction=name)
    steps: list[PlanStep] = []
    for step in plan.steps:
        if step.type == STEP_ACTION:
            steps.append(
                replace(
                    step,
                    parameters=sanitize_step_parameters(step.action_id, step.parameters),
                    unsafe_parameters=False,
                )
            )
        else:
            steps.append(step)
    return Workflow(
        id=workflow_id,
        name=name,
        description=str(data.get("description") or "").strip(),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        last_run_at=str(data.get("last_run_at") or ""),
        enabled=bool(data.get("enabled", True)),
        scope_folder=str(data.get("scope_folder") or "").strip() or None,
        origin=str(data.get("origin") or ORIGIN_MEANING),
        steps=tuple(steps),
    )


def default_workflow_name(plan: ActPlan) -> str:
    parts: list[str] = []
    for step in plan.steps:
        if step.type == STEP_FIND and step.query:
            parts.append(step.query)
        elif step.type == STEP_NARROW and step.query:
            parts.append(step.query)
        elif step.type == STEP_ACTION:
            if step.action_id == "add_tag":
                parts.append(str(step.parameters.get("tag") or "tag"))
            elif step.action_id == "remove_tag":
                parts.append(str(step.parameters.get("tag") or "tag"))
            elif step.action_id == "move":
                parts.append(str(step.parameters.get("destination_name") or "move"))
            elif step.action_id == "create_folder":
                parts.append(str(step.parameters.get("name") or "folder"))
            elif step.action_id == "rename":
                parts.append("rename")
    text = " · ".join(part for part in parts if part).strip()
    return (text or "Automation")[:80]


def search_steps_from_context(context) -> list[PlanStep]:
    steps: list[PlanStep] = []
    find_query = str(getattr(context, "find_query", "") or "").strip()
    narrow_query = str(getattr(context, "narrow_query", "") or "").strip()
    latest = str(getattr(context, "query", "") or "").strip()
    if not find_query:
        find_query = latest if not getattr(context, "narrowed", False) else ""
    if getattr(context, "narrowed", False) and not narrow_query:
        narrow_query = latest
    if find_query:
        steps.append(PlanStep(step_id="find", type=STEP_FIND, query=find_query))
    if narrow_query:
        steps.append(PlanStep(step_id="narrow", type=STEP_NARROW, query=narrow_query))
    return steps


def workflow_from_session(
    *,
    name: str,
    description: str = "",
    context,
    plan: ActPlan | None = None,
    action_id: str = "",
    parameters: Mapping[str, Any] | None = None,
    target_source: str = "result_set",
) -> Workflow:
    """Build a reusable Workflow from the current Find / Narrow / Act session."""
    steps: list[PlanStep] = []
    if plan is not None and plan.steps:
        if not plan.search_steps():
            steps.extend(search_steps_from_context(context))
        for step in plan.steps:
            if step.type == STEP_ACTION:
                steps.append(
                    replace(step, parameters=sanitize_step_parameters(step.action_id, step.parameters))
                )
            else:
                steps.append(step)
    else:
        steps.extend(search_steps_from_context(context))
        if action_id:
            steps.append(
                PlanStep(
                    step_id="action",
                    type=STEP_ACTION,
                    action_id=action_id,
                    target_source=target_source,
                    parameters=sanitize_step_parameters(action_id, parameters),
                )
            )
    stamp = utc_now()
    resolved = ActPlan(steps=assign_step_ids(steps), instruction=name)
    label = str(name or "").strip() or default_workflow_name(resolved)
    return Workflow(
        id=new_workflow_id(),
        name=label,
        description=str(description or "").strip(),
        created_at=stamp,
        updated_at=stamp,
        enabled=True,
        scope_folder=getattr(context, "scope_folder", None),
        origin=getattr(context, "origin", None) or ORIGIN_MEANING,
        steps=resolved.steps,
    )


def workflow_step_issues(workflow: Workflow) -> tuple[str, ...]:
    reasons: list[str] = []
    if not workflow.name:
        reasons.append("missing_name")
    if not workflow.steps:
        reasons.append("empty_plan")
    has_action = False
    for step in workflow.steps:
        if step.type in FORBIDDEN_STEP_TYPES or step.type not in ALLOWED_STEP_TYPES:
            reasons.append("unknown_step_type")
            continue
        if step.type != STEP_ACTION:
            if step.type in {STEP_FIND, STEP_NARROW} and not step.query:
                reasons.append("missing_query")
            continue
        has_action = True
        if step.action_id not in ALLOWED_ACTION_IDS or step.action_id not in ACTION_IDS:
            reasons.append("unknown_action")
            continue
        extra = set(step.parameters) - PARAM_ALLOWLIST.get(step.action_id, frozenset())
        if extra & FORBIDDEN_PARAM_KEYS:
            reasons.append("forbidden_parameter")
    if not has_action:
        reasons.append("no_action")
    return tuple(dict.fromkeys(reasons))
