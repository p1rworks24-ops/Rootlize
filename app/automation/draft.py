"""Automation AI drafts a Workflow. It never searches images or executes Actions."""
from __future__ import annotations

from dataclasses import dataclass

from app.workspace.context import SearchResultContext
from app.workspace.intent import KIND_FIND, parse_simple_turn
from app.workspace.plan import (
    PLAN_STATUS_CLARIFY,
    PLAN_STATUS_PLAN,
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    ActPlan,
    PlanStep,
    assign_step_ids,
)
from app.workspace.planner import build_act_plan, try_local_act_plan


@dataclass(frozen=True)
class DraftOutcome:
    status: str
    steps: tuple[PlanStep, ...] = ()
    message_key: str = ""
    message: str = ""
    reasons: tuple[str, ...] = ()
    used_ai: bool = False

    @property
    def ok(self) -> bool:
        return self.status == PLAN_STATUS_PLAN and bool(self.steps)


def draft_workflow_from_text(
    instruction: str,
    context: SearchResultContext | None = None,
    *,
    allow_ai: bool = False,
    complete_json=None,
) -> DraftOutcome:
    """Turn natural language into Workflow blocks. No filesystem changes."""
    ctx = context or SearchResultContext()
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_empty",
            reasons=("empty",),
        )

    local = try_local_act_plan(raw, ctx)
    if local is not None and local.status == PLAN_STATUS_PLAN and local.plan is not None:
        return _from_plan(local.plan, used_ai=False)
    if local is not None and local.status == PLAN_STATUS_CLARIFY:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            steps=_safe_steps(local.plan),
            message_key=local.message_key or "automation.draft_clarify",
            message=local.message,
            reasons=local.reasons or ("clarify",),
        )

    single = parse_simple_turn(raw, ctx, require_targets=False)
    if single is not None and single.kind == KIND_FIND and single.query:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            steps=assign_step_ids((PlanStep(step_id="find", type=STEP_FIND, query=single.query),)),
            message_key="automation.draft_need_act",
            reasons=("need_act",),
        )

    if not allow_ai:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            reasons=("unplanned",),
        )

    try:
        built = build_act_plan(
            raw,
            ctx,
            complete_json=complete_json,
            allow_ai=True,
        )
    except Exception:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_unavailable",
            reasons=("ai_unavailable",),
        )
    if built.status == PLAN_STATUS_PLAN and built.plan is not None:
        return _from_plan(built.plan, used_ai=built.used_ai)
    return DraftOutcome(
        PLAN_STATUS_CLARIFY,
        steps=_safe_steps(built.plan),
        message_key=built.message_key or "automation.draft_clarify",
        message=built.message,
        reasons=built.reasons or ("clarify",),
        used_ai=built.used_ai,
    )


def _from_plan(plan: ActPlan, *, used_ai: bool) -> DraftOutcome:
    steps = _safe_steps(plan)
    if not steps:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            reasons=("empty_plan",),
            used_ai=used_ai,
        )
    return DraftOutcome(PLAN_STATUS_PLAN, steps=steps, used_ai=used_ai)


def _safe_steps(plan: ActPlan | None) -> tuple[PlanStep, ...]:
    if plan is None:
        return ()
    kept: list[PlanStep] = []
    for step in plan.steps:
        if step.type in {STEP_FIND, STEP_NARROW, STEP_ACTION}:
            kept.append(step)
    return assign_step_ids(kept)
