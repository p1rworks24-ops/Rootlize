"""AI-first Ask AI turn routing.

Classifies a chat message into search / narrow / action / find_and_action /
clarify / unsupported. Does not execute Actions, search, or skip confirmation.
Meaning Search is invoked by the caller only after a validated search intent.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from app.workspace.capabilities import allowed_action_ids
from app.workspace.context import (
    SOURCE_FOLDER,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
)
from app.workspace.intent import (
    KIND_ACT,
    KIND_ACT_PLAN,
    KIND_CLARIFY,
    KIND_FIND,
    KIND_HELP,
    KIND_NARROW,
    KIND_QUESTION,
    KIND_UNSUPPORTED,
    AskAiTurn,
    classify_ask_ai_turn,
    looks_like_prompt_injection,
)
from app.workspace.plan import (
    PLAN_STATUS_CLARIFY,
    PLAN_STATUS_PLAN,
    PLAN_STATUS_REJECTED,
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    ActPlan,
    parse_plan_payload,
    validate_act_plan,
)
from app.workspace.planner import (
    CompleteJson,
    NameGenerator,
    PlannerOutcome,
    _fill_generated_names,
    request_plan_payload,
)
from app.workspace.semantic_safety import (
    PLAN_STATUS_CLARIFY as SAFETY_CLARIFY,
    message_key_for_instruction,
    validate_semantic_safety,
)
from app.workspace.tag_semantics import apply_tag_removal_semantics

ALLOWED_INTENTS = (
    "search",
    "narrow",
    "question",
    "action",
    "find_and_action",
    "clarify",
    "unsupported",
    "help",
)

_SEARCH_INTENTS = frozenset({"search"})
_ACTION_INTENTS = frozenset({"action", "find_and_action"})


def route_ask_ai_turn(
    instruction: str,
    context: SearchResultContext | None = None,
    *,
    complete_json: CompleteJson | None = None,
    name_generator: NameGenerator | None = None,
    images: tuple[dict[str, Any], ...] | None = None,
    allow_ai: bool = True,
    conversation: Mapping[str, Any] | None = None,
) -> AskAiTurn:
    """Route one Ask AI message through the Planner, then local validation.

    Intent is not classified by local regex on the product path. Preview mode
    (`allow_ai=False` without a planner stub) still uses the local parser.
    Does not execute Actions, search, or skip confirmation.
    """
    ctx = context or SearchResultContext()
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return AskAiTurn(KIND_CLARIFY, message_key="images.ai.need_instruction", reasons=("empty",))

    if not allow_ai and complete_json is None:
        return classify_ask_ai_turn(raw, ctx)

    extra = dict(conversation or {})
    payload, response_id = request_plan_payload(
        raw,
        ctx,
        images=images,
        complete_json=complete_json,
        conversation=extra,
    )
    payload = _payload_with_generated_names(
        payload,
        raw,
        ctx,
        name_generator=name_generator,
        images=images,
        complete_json=complete_json,
    )
    turn = turn_from_planner_payload(payload, raw, ctx, used_ai=True)
    if response_id:
        turn = replace(turn, planner_response_id=response_id)
    return turn


def _payload_with_generated_names(
    payload: Mapping[str, Any] | None,
    instruction: str,
    context: SearchResultContext,
    *,
    name_generator: NameGenerator | None,
    images: tuple[dict[str, Any], ...] | None,
    complete_json: CompleteJson | None,
) -> dict[str, Any]:
    data = dict(payload or {})
    plan = parse_plan_payload(data, instruction=instruction)
    if not plan.steps:
        return data
    filled = _fill_generated_names(
        PlannerOutcome(PLAN_STATUS_PLAN, plan=plan),
        context,
        name_generator=name_generator,
        images=images,
        complete_json=complete_json,
        allow_ai=True,
    )
    if filled.status != PLAN_STATUS_PLAN or filled.plan is None:
        return {
            "intent": "clarify",
            "status": PLAN_STATUS_CLARIFY,
            "clarify_message": str(filled.message or ""),
            "steps": [],
        }
    if filled.plan is plan:
        return data
    data["steps"] = [
        {
            "id": step.step_id,
            "type": step.type,
            "query": step.query,
            "action_id": step.action_id,
            "target_source": step.target_source,
            "parameters": dict(step.parameters),
        }
        for step in filled.plan.steps
    ]
    return data


def turn_from_planner_payload(
    payload: Mapping[str, Any] | None,
    instruction: str,
    context: SearchResultContext,
    *,
    used_ai: bool = False,
) -> AskAiTurn:
    """Validate planner JSON locally. Unknown Actions never become search."""
    data = dict(payload or {})
    intent = str(data.get("intent") or "").strip().lower()
    status = str(data.get("status") or "").strip().lower()
    message = str(data.get("clarify_message") or "").strip()
    raw = " ".join(str(instruction or "").strip().split())

    if looks_like_prompt_injection(raw) and not _library_intent(intent, data):
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key="images.ai.not_understood",
            reasons=("prompt_injection", "role_locked"),
            used_ai=used_ai,
        )

    if intent not in ALLOWED_INTENTS:
        if status == PLAN_STATUS_CLARIFY or not data.get("steps"):
            reasons = ("unknown_intent",)
            if not intent and not status:
                reasons = ("invalid_schema",) + reasons
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                message_key="images.ai.not_understood",
                message=message,
                reasons=reasons,
                used_ai=used_ai,
            )
        intent = _intent_from_steps(data)

    plan = parse_plan_payload(data, instruction=raw)
    plan, tag_reasons = apply_tag_removal_semantics(plan)
    if "guessed_tag" in tag_reasons:
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            plan=plan,
            message_key="images.ai.which_tag_remove",
            reasons=("guessed_tag",) + tag_reasons,
            used_ai=used_ai,
        )
    safety = validate_semantic_safety(
        raw,
        intent=intent,
        action_ids=tuple(step.action_id for step in plan.action_steps() if step.action_id),
        destination_name=_first_destination_name(plan),
        context=context,
    )
    if safety is not None and not safety.ok:
        if safety.status == SAFETY_CLARIFY:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                plan=plan,
                message_key=safety.message_key or "images.ai.which_destination",
                reasons=safety.reasons,
                used_ai=used_ai,
            )
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            plan=plan,
            message_key=safety.message_key or message_key_for_instruction(raw, safety.reasons),
            reasons=safety.reasons,
            used_ai=used_ai,
        )

    if intent == "help":
        return AskAiTurn(KIND_HELP, query=raw, used_ai=used_ai)
    if intent == "question":
        return AskAiTurn(
            KIND_QUESTION,
            query=raw,
            message_key="images.ai.question_not_search",
            message=message,
            reasons=("question",),
            used_ai=used_ai,
        )
    if intent == "unsupported":
        key = _unsupported_message_key(raw, ("unsupported_action",))
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            message_key=key,
            message=message,
            reasons=("unsupported_action",),
            used_ai=used_ai,
        )
    if intent == "clarify" or status in {PLAN_STATUS_CLARIFY, PLAN_STATUS_REJECTED}:
        key = "images.ai.missing_parameter" if status == PLAN_STATUS_CLARIFY else "images.ai.not_understood"
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key=key,
            message=message,
            reasons=("ai_clarify",),
            used_ai=used_ai,
        )

    if intent == "search":
        query = _search_query(data, raw)
        if not query:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                message_key="images.ai.clarify_search",
                message=message,
                reasons=("search_query_missing",),
                used_ai=used_ai,
            )
        return AskAiTurn(KIND_FIND, query=query, target_source=SOURCE_FOLDER, used_ai=used_ai)

    if intent == "narrow":
        query = _search_query(data, raw)
        source = _payload_target_source(data, context)
        if not context.has_targets(source):
            return AskAiTurn(
                KIND_CLARIFY,
                query=query or raw,
                target_source=source,
                message_key="images.ai.missing_target",
                reasons=("no_targets",),
                used_ai=used_ai,
            )
        if not query:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.describe_target",
                reasons=("narrow_query_missing",),
                used_ai=used_ai,
            )
        return AskAiTurn(KIND_NARROW, query=query, target_source=source, used_ai=used_ai)

    unknown = _unknown_actions(plan)
    if unknown:
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            plan=plan,
            message_key=_unsupported_message_key(raw, ("unknown_action",) + unknown),
            message=message,
            reasons=("unknown_action",) + unknown,
            used_ai=used_ai,
        )

    if intent == "action":
        validation = validate_act_plan(plan, context, allow_unresolved_search=True)
        if not validation.ok:
            return _validation_turn(raw, plan, validation, used_ai=used_ai)
        action_steps = plan.action_steps()
        search_steps = plan.search_steps()
        if search_steps:
            intent = "find_and_action"
        elif len(action_steps) == 1:
            step = action_steps[0]
            names = step.parameters.get("names")
            if isinstance(names, dict) and names:
                return AskAiTurn(
                    KIND_ACT_PLAN,
                    query=raw,
                    target_source=plan.target_source,
                    plan=plan,
                    used_ai=used_ai,
                )
            from app.workspace.act import ActionProposal

            return AskAiTurn(
                KIND_ACT,
                query=raw,
                target_source=step.target_source,
                proposal=ActionProposal(
                    action_id=step.action_id,
                    target_source=step.target_source,
                    parameters=dict(step.parameters),
                    instruction=raw,
                ),
                plan=plan,
                used_ai=used_ai,
            )
        return AskAiTurn(
            KIND_ACT_PLAN,
            query=raw,
            target_source=plan.target_source,
            plan=plan,
            used_ai=used_ai,
        )

    if intent == "find_and_action":
        validation = validate_act_plan(plan, context, allow_unresolved_search=True)
        if not validation.ok:
            return _validation_turn(raw, plan, validation, used_ai=used_ai)
        if not plan.search_steps() or not plan.action_steps():
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                plan=plan,
                message_key="images.ai.missing_parameter",
                message=message,
                reasons=("incomplete_find_and_action",),
                used_ai=used_ai,
            )
        return AskAiTurn(
            KIND_ACT_PLAN,
            query=raw,
            target_source=plan.target_source,
            plan=plan,
            used_ai=used_ai,
        )

    return AskAiTurn(
        KIND_CLARIFY,
        query=raw,
        message_key="images.ai.not_understood",
        reasons=("unplanned",),
        used_ai=used_ai,
    )


def planner_conversation_context(
    context: SearchResultContext,
    *,
    conversation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    extra = dict(conversation or {})
    return {
        "folder": context.scope_folder or "",
        "result_count": len(context.result_image_ids or context.result_paths),
        "result_query": context.query or "",
        "find_query": context.find_query or "",
        "narrow_query": context.narrow_query or "",
        "narrowed": bool(context.narrowed),
        "selection_count": len(context.selected_image_ids or context.selected_paths),
        "pending_action": str(extra.get("pending_action") or ""),
        "last_confirmed_action": str(extra.get("last_confirmed_action") or ""),
        "planner_response_id": str(extra.get("planner_response_id") or ""),
    }


def _unsupported_message_key(raw: str, reasons: tuple[str, ...] | list[str]) -> str:
    return message_key_for_instruction(raw, reasons)


def _library_intent(intent: str, data: Mapping[str, Any]) -> bool:
    if intent in _SEARCH_INTENTS | _ACTION_INTENTS | {"narrow"}:
        return True
    steps = data.get("steps") or ()
    return isinstance(steps, list) and any(
        isinstance(item, dict) and str(item.get("type") or "") in {STEP_FIND, STEP_NARROW, STEP_ACTION}
        for item in steps
    )


def _intent_from_steps(data: Mapping[str, Any]) -> str:
    plan = parse_plan_payload(data)
    has_search = bool(plan.search_steps())
    has_action = bool(plan.action_steps())
    if has_search and has_action:
        return "find_and_action"
    if has_action:
        return "action"
    if has_search:
        first = plan.search_steps()[0]
        return "narrow" if first.type == STEP_NARROW else "search"
    return "clarify"


def _search_query(data: Mapping[str, Any], fallback: str) -> str:
    search = data.get("search")
    if isinstance(search, dict) and str(search.get("query") or "").strip():
        return str(search.get("query")).strip()
    plan = parse_plan_payload(data)
    for step in plan.search_steps():
        if step.query:
            return step.query
    return ""


def _payload_target_source(data: Mapping[str, Any], context: SearchResultContext) -> str:
    search = data.get("search")
    if isinstance(search, dict):
        source = str(search.get("target_source") or "").strip()
        if source in {SOURCE_RESULT_SET, SOURCE_SELECTION, SOURCE_FOLDER}:
            return source
    plan = parse_plan_payload(data)
    for step in plan.steps:
        if step.target_source in {SOURCE_RESULT_SET, SOURCE_SELECTION}:
            return step.target_source
    if context.has_selection() and not context.has_result_set():
        return SOURCE_SELECTION
    return SOURCE_RESULT_SET


def _unknown_actions(plan: ActPlan) -> tuple[str, ...]:
    allowed = set(allowed_action_ids())
    found = []
    for step in plan.action_steps():
        if step.action_id and step.action_id not in allowed:
            found.append(step.action_id)
    return tuple(dict.fromkeys(found))


def _validation_turn(
    raw: str,
    plan: ActPlan,
    validation,
    *,
    used_ai: bool,
) -> AskAiTurn:
    reasons = validation.reasons
    if "unknown_action" in reasons or "semantic_mismatch" in reasons or "delete_unsupported" in reasons or "unsafe_tool" in reasons or "unsupported_capability" in reasons:
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            plan=plan,
            message_key=validation.message_key or _unsupported_message_key(raw, reasons),
            reasons=reasons,
            used_ai=used_ai,
        )
    kind = KIND_CLARIFY if validation.status == PLAN_STATUS_CLARIFY else KIND_CLARIFY
    return AskAiTurn(
        kind,
        query=raw,
        plan=plan,
        message_key=validation.message_key or "images.ai.not_understood",
        message=validation.message if validation.status == PLAN_STATUS_CLARIFY else "",
        reasons=reasons,
        used_ai=used_ai,
    )


def _first_destination_name(plan: ActPlan) -> str:
    for step in plan.action_steps():
        name = str(step.parameters.get("destination_name") or "").strip()
        if name:
            return name
    return ""
