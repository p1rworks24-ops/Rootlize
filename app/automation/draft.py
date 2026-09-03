"""Automation AI drafts a Workflow. It never searches images or executes Actions."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from app.actions.models import (
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
)
from app.ai_budget import AiBudgetExceeded
from app.ai_proxy.errors import AiProxyError
from app.automation.blocks import BUILDER_ACTION_IDS, action_label
from app.i18n import t
from app.image_facts.query import meaning_query_target
from app.workspace.capabilities import action_capabilities, format_capability_catalog
from app.workspace.context import ORIGIN_BROWSE, ORIGIN_MEANING, ORIGIN_TEXT, SearchResultContext
from app.workspace.intent import (
    KIND_ACT,
    KIND_ACT_PLAN,
    KIND_FIND,
    KIND_NARROW,
    KIND_UNSUPPORTED,
    classify_ask_ai_turn,
    parse_simple_turn,
)
from app.workspace.plan import (
    PLAN_STATUS_CLARIFY,
    PLAN_STATUS_PLAN,
    PLAN_STATUS_REJECTED,
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    ActPlan,
    PlanStep,
    assign_step_ids,
    parse_plan_payload,
)
from app.workspace.planner import post_act_plan_json, try_local_act_plan
from app.utils.tag_format import parse_tag_names

CompleteJson = Callable[..., dict[str, Any]]

_TEXT_SEARCH_HINT = re.compile(
    r"filename|file name|ocr|text in image|named\b|名前|ファイル名|画像内の文字|テキスト検索",
    re.I,
)
_ALL_IMAGES_QUERY = re.compile(
    r"^(?:all(?:\s+(?:the\s+)?)?(?:images?|screenshots?|photos?|pictures?)?|"
    r"every(?:\s+image)?|すべて|全部|全ての画像|すべての画像)$",
    re.I,
)
_WEAK_TAGS = frozenset({"a", "an", "the", "tag", "tags", "them", "these", "those", "it", "this"})
_UNSUPPORTED_ACTION_IDS = frozenset(
    {
        ACTION_CREATE_FOLDER,
        ACTION_RENAME,
        "add_favorite",
        "remove_favorite",
        "remove_all_tags",
        "replace_tags",
        "delete",
        "favorites_add",
        "copy",
        "export",
        "undo",
    }
)
_CREATE_FOLDER_REQUIRED = re.compile(
    r"\bcreate\s+(?:an?\s+)?(?:new\s+)?(?:folder\b|(?:folder\s+(?:named|called)\s+\S+)|"
    r"[\"']?[\w-]+[\"']?\s+folder\b)|"
    r"(?:フォルダ|フォルダー)を?(?:作って|作成)",
    re.I,
)
_CREATED_FOLDER_NAME = re.compile(
    r"create\s+(?:an?\s+)?(?:new\s+)?"
    r"(?:folder\s+(?:named|called)\s+[\"']?(?P<called>[\w-]+)[\"']?"
    r"|[\"']?(?P<before>[\w-]+)[\"']?\s+folder)",
    re.I,
)
_MOVE_SUBJECT = re.compile(
    r"(?:^|\band\s+)?(?:please\s+)?move\s+(?:all(?:\s+(?:of\s+)?(?:the\s+)?)?)?(?P<subject>.+?)\s+"
    r"(?:to\s+|into\s+)",
    re.I,
)
_DEICTIC_MOVE_SUBJECT = re.compile(
    r"^(?:(?:all(?:\s+the)?\s+)?(?:these|those|them|the results?|selected)(?:\s+images?)?|"
    r"this(?:\s+image)?)$",
    re.I,
)
_EXISTING_DESTINATION = re.compile(r"^(?:the\s+)?existing\s+", re.I)
_BUILDER_PARAM_KEYS = {
    ACTION_ADD_TAG: frozenset({"tag"}),
    ACTION_REMOVE_TAG: frozenset({"tag"}),
    ACTION_MOVE: frozenset({"destination_name"}),
}

WORKFLOW_DRAFT_PROMPT = """You are generating a reusable Rootlize Automation Workflow. You do not execute anything. You cannot access the filesystem, shell, database, or image files. You cannot skip Preview / Confirm / Execute.

This is not Ask AI Chat. Do not search images now. The user will review editable blocks, then Run through the existing Automation safety path.

Available workflow blocks only:
- Folder: already chosen in the builder. Do not invent a filesystem path.
- Search: all images, text search (filename / tags / OCR), meaning search (visual/semantic).
- Action: move (destination_name = a simple folder name under the Start Folder. If that folder does not exist, Move creates it there after Confirm. Do not emit create_folder for that.), add_tag (tag), remove_tag (tag).

Unavailable as their own blocks (intent=unsupported only when the request cannot be satisfied with the available blocks): create_folder, rename, favorite, remove_all_tags, replace_tags, delete, filter, similar, duplicates, trigger, condition, shell, SQL, copy, export, undo.

Rules:
- Use only step types find or action. For a new workflow, prefer find over narrow.
- Visual requests such as dog images use find with the named target only (example query: dog), not wrappers like "all dog images in this folder".
- Filename / OCR / text-in-image requests still use find; the app attaches Text search.
- If the user wants every image in the folder, omit find.
- Use only action_id values listed under Available actions. Never invent an Action. Never map an unavailable verb onto a listed Action.
- If the user asks to create a folder AND move images into it, emit find (when a search target is named) and move with destination_name. Do not emit create_folder. Move creates a missing destination under the Start Folder at Run after Confirm.
- If the user asks only to create a folder, with no move or other available action, intent=unsupported.
- A word such as create/folder is not enough to fail when Move already satisfies the request.
- If a truly unavailable action is required to satisfy the request, intent=unsupported and do not emit a partial plan of the remaining available steps.
- Do not invent tag names, destination folder names, or search queries. If a required value is missing, status=clarify and name the missing field. Include only steps whose values were explicit.
- Do not emit destination_path, parent_path, paths, image ids, shell, SQL, skip_confirmation, or execute flags.
- destination_name is a folder name, never an absolute, UNC, or parent-traversal path.

Available actions:
{catalog}

Folder currently selected: {folder}
user_request: {instruction}
"""


@dataclass(frozen=True)
class DraftOutcome:
    status: str
    steps: tuple[PlanStep, ...] = ()
    origin: str = ORIGIN_BROWSE
    message_key: str = ""
    message: str = ""
    reasons: tuple[str, ...] = ()
    used_ai: bool = False
    missing: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == PLAN_STATUS_PLAN and bool(self.steps) and not self.unsupported and not self.missing

    @property
    def apply_steps(self) -> bool:
        """True when validated builder steps may appear on the canvas."""
        if self.status == PLAN_STATUS_REJECTED:
            return False
        if self.unsupported:
            return False
        if "invalid_schema" in self.reasons or "unknown_step_type" in self.reasons:
            return False
        if "forbidden_parameter" in self.reasons:
            return False
        return bool(self.steps)


def draft_workflow_from_text(
    instruction: str,
    context: SearchResultContext | None = None,
    *,
    allow_ai: bool = False,
    complete_json: CompleteJson | None = None,
) -> DraftOutcome:
    """Turn natural language into builder-ready Workflow blocks. No filesystem changes."""
    ctx = context or SearchResultContext()
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_empty",
            reasons=("empty",),
        )

    local = try_local_act_plan(raw, ctx)
    if local is not None and local.plan is not None:
        adapted = adapt_plan_for_builder(local.plan, raw, used_ai=False)
        if adapted.ok:
            return adapted
        created_move = _draft_create_and_move(raw)
        if created_move is not None and created_move.ok:
            return created_move
        if adapted.steps or adapted.unsupported or adapted.missing:
            return adapted
    elif local is not None and local.status == PLAN_STATUS_CLARIFY:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=local.message_key or "automation.draft_clarify",
            message=local.message,
            reasons=local.reasons or ("clarify",),
        )

    created_move = _draft_create_and_move(raw)
    if created_move is not None:
        return created_move

    single = parse_simple_turn(raw, ctx, require_targets=False)
    if single is not None:
        from_single = _from_simple_turn(single, raw)
        if from_single is not None:
            return from_single

    if _instruction_is_create_folder_only(raw):
        return _unsupported_outcome((ACTION_CREATE_FOLDER,))

    classified = classify_ask_ai_turn(raw, ctx)
    if classified.kind == KIND_UNSUPPORTED:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=classified.message_key or "automation.draft_unsupported",
            message=classified.message,
            reasons=classified.reasons or ("unsupported",),
        )

    if not allow_ai:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            reasons=("unplanned",),
        )

    try:
        payload = _request_workflow_json(raw, ctx, complete_json=complete_json)
    except AiBudgetExceeded as exc:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=exc.message_key or "account.ai.limit_reached",
            reasons=("budget",),
            used_ai=True,
        )
    except AiProxyError as exc:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=exc.message_key or "automation.draft_unavailable",
            reasons=(exc.code or "ai_unavailable",),
            used_ai=True,
        )
    except Exception:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_unavailable",
            reasons=("ai_unavailable",),
            used_ai=True,
        )
    return _from_ai_payload(payload, raw)


def adapt_plan_for_builder(
    plan: ActPlan | None,
    instruction: str,
    *,
    used_ai: bool = False,
) -> DraftOutcome:
    """Keep only enabled Automation blocks. Never invent missing values."""
    if plan is None:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            reasons=("empty_plan",),
            used_ai=used_ai,
        )

    created_names = _created_folder_names(plan)
    kept: list[PlanStep] = []
    missing: list[str] = []
    unsupported: list[str] = []
    skipped_creates: list[str] = []
    unsafe = False

    for step in plan.steps:
        if step.type not in {STEP_FIND, STEP_NARROW, STEP_ACTION}:
            if step.type:
                unsafe = True
                unsupported.append(step.type)
            continue
        if step.unsafe_parameters:
            unsafe = True
            continue
        if step.type in {STEP_FIND, STEP_NARROW}:
            query = _clean_query(step.query)
            if _is_all_images_query(query):
                continue
            if not query:
                missing.append("query")
                continue
            kept.append(replace(step, type=STEP_FIND, query=query, action_id="", parameters={}))
            continue
        if step.action_id == ACTION_CREATE_FOLDER:
            name = str(step.parameters.get("name") or "").strip()
            skipped_creates.append(name or ACTION_CREATE_FOLDER)
            continue
        if step.action_id not in BUILDER_ACTION_IDS:
            unsupported.append(step.action_id or "unknown_action")
            if step.action_id in _UNSUPPORTED_ACTION_IDS or step.action_id:
                continue
            unsafe = True
            continue
        parameters = _builder_parameters(step, created_names)
        if step.action_id in {ACTION_ADD_TAG, ACTION_REMOVE_TAG}:
            tags = [
                cleaned
                for cleaned in (
                    _clean_tag(item)
                    for item in parse_tag_names(
                        parameters.get("tag") or step.parameters.get("tags") or step.parameters.get("tag")
                    )
                )
                if cleaned and cleaned.casefold() not in _WEAK_TAGS
            ]
            if not tags:
                missing.append("tag")
                kept.append(replace(step, parameters={}, target_source="result_set", depends_on=()))
                continue
            for tag in tags:
                kept.append(
                    replace(
                        step,
                        parameters={"tag": tag},
                        target_source="result_set",
                        depends_on=(),
                    )
                )
            continue
        if step.action_id == ACTION_MOVE:
            dest = str(parameters.get("destination_name") or "").strip()
            if not dest:
                missing.append("destination")
                kept.append(replace(step, parameters={}, target_source="result_set", depends_on=()))
                continue
            kept.append(
                replace(
                    step,
                    parameters={"destination_name": dest},
                    target_source="result_set",
                    depends_on=(),
                )
            )
            continue
        kept.append(replace(step, parameters=parameters, target_source="result_set", depends_on=()))

    if skipped_creates and not _move_uses_created_folder(kept, created_names, skipped_creates):
        unsupported.append(ACTION_CREATE_FOLDER)

    if not any(step.type == STEP_FIND for step in kept):
        implied = _implied_search_query(instruction)
        if implied:
            kept.insert(0, PlanStep(step_id="find", type=STEP_FIND, query=implied))

    steps = assign_step_ids(tuple(kept))
    origin = infer_builder_origin(instruction, steps)
    missing_unique = tuple(dict.fromkeys(missing))
    unsupported_unique = tuple(dict.fromkeys(item for item in unsupported if item))

    if unsafe:
        return DraftOutcome(
            PLAN_STATUS_REJECTED,
            message_key="automation.draft_invalid",
            reasons=("invalid_schema", "forbidden_parameter") if any(s.unsafe_parameters for s in plan.steps) else ("unknown_step_type",),
            used_ai=used_ai,
            unsupported=unsupported_unique,
        )
    if unsupported_unique:
        return _unsupported_outcome(unsupported_unique, used_ai=used_ai, origin=origin)
    if not steps:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            origin=origin,
            message_key="automation.draft_clarify",
            reasons=("empty_plan",),
            used_ai=used_ai,
            missing=missing_unique,
        )
    if missing_unique:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            steps=steps,
            origin=origin,
            message_key=_missing_message_key(missing_unique),
            reasons=("missing_parameter",) + missing_unique,
            used_ai=used_ai,
            missing=missing_unique,
        )
    if not any(step.type == STEP_ACTION for step in steps):
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            steps=steps,
            origin=origin,
            message_key="automation.draft_need_act",
            reasons=("need_act",),
            used_ai=used_ai,
        )
    return DraftOutcome(PLAN_STATUS_PLAN, steps=steps, origin=origin, used_ai=used_ai)


def infer_builder_origin(instruction: str, steps: tuple[PlanStep, ...] | list[PlanStep]) -> str:
    if not any(step.type == STEP_FIND for step in steps):
        return ORIGIN_BROWSE
    if _TEXT_SEARCH_HINT.search(str(instruction or "")):
        return ORIGIN_TEXT
    return ORIGIN_MEANING


def _from_simple_turn(turn, instruction: str) -> DraftOutcome | None:
    if turn.kind == KIND_UNSUPPORTED:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=turn.message_key or "automation.draft_unsupported",
            message=turn.message,
            reasons=turn.reasons or ("unsupported",),
        )
    if turn.kind == KIND_FIND and turn.query:
        query = _clean_query(turn.query)
        if _is_all_images_query(query):
            return DraftOutcome(
                PLAN_STATUS_CLARIFY,
                message_key="automation.draft_need_act",
                reasons=("need_act",),
            )
        if not query:
            return DraftOutcome(
                PLAN_STATUS_CLARIFY,
                message_key="automation.draft_missing_query",
                reasons=("missing_query", "query"),
                missing=("query",),
            )
        return adapt_plan_for_builder(
            ActPlan(steps=(PlanStep(step_id="find", type=STEP_FIND, query=query),), instruction=instruction),
            instruction,
        )
    if turn.kind == KIND_NARROW and turn.query:
        return adapt_plan_for_builder(
            ActPlan(steps=(PlanStep(step_id="find", type=STEP_FIND, query=_clean_query(turn.query)),), instruction=instruction),
            instruction,
        )
    if turn.kind == KIND_ACT and turn.proposal is not None:
        proposal = turn.proposal
        parameters = dict(proposal.parameters)
        if proposal.action_id == ACTION_MOVE:
            dest = _clean_destination_name(str(parameters.get("destination_name") or ""))
            if dest:
                parameters["destination_name"] = dest
        steps: list[PlanStep] = []
        implied = _implied_search_query(instruction) if proposal.action_id == ACTION_MOVE else ""
        if implied:
            steps.append(PlanStep(step_id="find", type=STEP_FIND, query=implied))
        steps.append(
            PlanStep(
                step_id="action",
                type=STEP_ACTION,
                action_id=proposal.action_id,
                parameters=parameters,
            )
        )
        return adapt_plan_for_builder(
            ActPlan(steps=tuple(steps), instruction=instruction),
            instruction,
        )
    if turn.kind == KIND_ACT_PLAN or "needs_planner" in (turn.reasons or ()):
        return None
    if turn.message_key or turn.reasons:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key=turn.message_key or "automation.draft_clarify",
            message=turn.message,
            reasons=turn.reasons or ("clarify",),
        )
    return None


def _from_ai_payload(payload: Mapping[str, Any] | None, instruction: str) -> DraftOutcome:
    data = dict(payload or {})
    data.pop("_response_id", None)
    if not data or not isinstance(data, dict):
        return DraftOutcome(
            PLAN_STATUS_REJECTED,
            message_key="automation.draft_invalid",
            reasons=("invalid_schema",),
            used_ai=True,
        )
    intent = str(data.get("intent") or "").strip().lower()
    status = str(data.get("status") or "").strip().lower()
    clarify = str(data.get("clarify_message") or "").strip()
    if status not in {"", PLAN_STATUS_PLAN, PLAN_STATUS_CLARIFY, PLAN_STATUS_REJECTED}:
        return DraftOutcome(
            PLAN_STATUS_REJECTED,
            message_key="automation.draft_invalid",
            reasons=("invalid_schema",),
            used_ai=True,
        )
    if intent in {"unsupported", "help"} or status == PLAN_STATUS_REJECTED:
        plan = parse_plan_payload(data, instruction=instruction)
        adapted = adapt_plan_for_builder(plan, instruction, used_ai=True)
        if adapted.ok:
            return adapted
        if adapted.status == PLAN_STATUS_REJECTED:
            return adapted
        unsupported = adapted.unsupported or ("unsupported",)
        return _unsupported_outcome(unsupported, used_ai=True, message=adapted.message or clarify)
    plan = parse_plan_payload(data, instruction=instruction)
    if not plan.steps and status == PLAN_STATUS_CLARIFY:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            message=clarify,
            reasons=("ai_clarify",),
            used_ai=True,
        )
    if not plan.steps and intent in {"question", "clarify"}:
        return DraftOutcome(
            PLAN_STATUS_CLARIFY,
            message_key="automation.draft_clarify",
            message=clarify,
            reasons=("ai_clarify",),
            used_ai=True,
        )
    adapted = adapt_plan_for_builder(plan, instruction, used_ai=True)
    if clarify and not adapted.ok:
        return replace(adapted, message=adapted.message or clarify)
    if not adapted.steps and not adapted.unsupported and not adapted.missing:
        return DraftOutcome(
            PLAN_STATUS_REJECTED,
            message_key="automation.draft_invalid",
            reasons=("invalid_schema",),
            used_ai=True,
        )
    return adapted


def _request_workflow_json(
    instruction: str,
    context: SearchResultContext,
    *,
    complete_json: CompleteJson | None,
) -> dict[str, Any]:
    folder = str(context.scope_folder or "").strip() or "(none — do not invent a path)"
    user_prompt = WORKFLOW_DRAFT_PROMPT.format(
        catalog=_builder_catalog_text(),
        folder=folder,
        instruction=instruction,
    )
    complete = complete_json or post_act_plan_json
    try:
        payload = complete(
            "Return JSON for a reusable Automation Workflow. Do not execute.",
            user_prompt,
            previous_response_id="",
        )
    except TypeError:
        payload = complete(
            "Return JSON for a reusable Automation Workflow. Do not execute.",
            user_prompt,
        )
    if not isinstance(payload, dict):
        raise AiProxyError("invalid_payload")
    return dict(payload)


def _builder_catalog_text() -> str:
    allowed = tuple(item for item in action_capabilities() if item["action_id"] in BUILDER_ACTION_IDS)
    return format_capability_catalog(allowed)


def _created_folder_names(plan: ActPlan) -> dict[str, str]:
    names: dict[str, str] = {}
    for step in plan.steps:
        if step.type == STEP_ACTION and step.action_id == ACTION_CREATE_FOLDER:
            name = str(step.parameters.get("name") or "").strip()
            if name and step.step_id:
                names[step.step_id] = name
    return names


def _builder_parameters(step: PlanStep, created_names: Mapping[str, str]) -> dict[str, str]:
    allowed = _BUILDER_PARAM_KEYS.get(step.action_id, frozenset())
    cleaned: dict[str, str] = {}
    for key, value in dict(step.parameters or {}).items():
        if key not in allowed:
            continue
        text = str(value or "").strip()
        if text:
            cleaned[key] = _clean_destination_name(text) if key == "destination_name" else text
    if step.action_id == ACTION_MOVE and not cleaned.get("destination_name"):
        ref = str(step.parameters.get("destination_ref") or "").strip()
        if ref and created_names.get(ref):
            cleaned["destination_name"] = created_names[ref]
        elif len(created_names) == 1:
            cleaned["destination_name"] = next(iter(created_names.values()))
    return cleaned


def _clean_tag(tag: str) -> str:
    text = str(tag or "").strip().strip("\"'")
    text = re.sub(r"\s+to these results$", "", text, flags=re.I).strip()
    return text


def _clean_query(query: str) -> str:
    text = meaning_query_target(str(query or "").strip())
    text = re.sub(r"^(?:all|every)\s+", "", text, flags=re.I).strip()
    text = re.sub(r"\s+(?:in|from)\s+(?:this|the current)\s+folder$", "", text, flags=re.I).strip()
    return text


def _is_all_images_query(query: str) -> bool:
    text = " ".join(str(query or "").strip().split())
    return bool(text) and bool(_ALL_IMAGES_QUERY.match(text))


def _clean_destination_name(name: str) -> str:
    text = str(name or "").strip()
    text = _EXISTING_DESTINATION.sub("", text).strip()
    text = re.sub(r"(?:フォルダ|フォルダー|folder)$", "", text, flags=re.I).strip()
    return text


def _implied_search_query(instruction: str) -> str:
    text = " ".join(str(instruction or "").strip().split()).rstrip(".!。")
    match = _MOVE_SUBJECT.search(text)
    if not match:
        return ""
    subject = str(match.group("subject") or "").strip()
    if not subject or _DEICTIC_MOVE_SUBJECT.match(subject):
        return ""
    if _is_all_images_query(subject) or _is_all_images_query(f"all {subject}"):
        return ""
    query = _clean_query(subject)
    if not query or _is_all_images_query(query):
        return ""
    return query


def _draft_create_and_move(instruction: str) -> DraftOutcome | None:
    if not _CREATE_FOLDER_REQUIRED.search(instruction):
        return None
    if not re.search(r"\bmove\b|移動", instruction, re.I):
        return None
    match = _CREATED_FOLDER_NAME.search(instruction)
    name = _clean_destination_name(
        str((match.group("called") if match else "") or (match.group("before") if match else "") or "")
    )
    if not name:
        return None
    steps: list[PlanStep] = []
    implied = _implied_search_query(instruction)
    if implied:
        steps.append(PlanStep(step_id="find", type=STEP_FIND, query=implied))
    steps.append(
        PlanStep(
            step_id="action",
            type=STEP_ACTION,
            action_id=ACTION_MOVE,
            parameters={"destination_name": name},
        )
    )
    return adapt_plan_for_builder(ActPlan(steps=tuple(steps), instruction=instruction), instruction)


def _instruction_is_create_folder_only(instruction: str) -> bool:
    text = " ".join(str(instruction or "").strip().split())
    if re.search(r"\bmove\b|移動", text, re.I):
        return False
    return bool(_CREATE_FOLDER_REQUIRED.search(text))


def _move_uses_created_folder(
    steps: list[PlanStep],
    created_names: Mapping[str, str],
    skipped_creates: list[str],
) -> bool:
    names = {str(name).strip() for name in created_names.values() if str(name).strip()}
    names.update(item for item in skipped_creates if item and item != ACTION_CREATE_FOLDER)
    folded = {name.casefold() for name in names}
    if not folded:
        return False
    for step in steps:
        if step.action_id != ACTION_MOVE:
            continue
        dest = str(step.parameters.get("destination_name") or "").strip()
        if dest and dest.casefold() in folded:
            return True
    return False


def _unsupported_notice(unsupported: tuple[str, ...]) -> tuple[str, str]:
    for action_id in unsupported:
        if not action_id or action_id == "unsupported":
            continue
        return (
            "automation.draft_unsupported",
            t("automation.draft_unsupported_block", block=action_label(action_id)),
        )
    return ("automation.draft_unsupported", "")


def _unsupported_outcome(
    unsupported: tuple[str, ...],
    *,
    used_ai: bool = False,
    origin: str = ORIGIN_BROWSE,
    message: str = "",
) -> DraftOutcome:
    key, named = _unsupported_notice(unsupported)
    extra = tuple(item for item in unsupported if item and item != "unsupported")
    return DraftOutcome(
        PLAN_STATUS_CLARIFY,
        origin=origin,
        message_key=key,
        message=message or named,
        reasons=("unsupported",) + extra,
        used_ai=used_ai,
        unsupported=unsupported,
    )


def _missing_message_key(missing: tuple[str, ...]) -> str:
    if "tag" in missing:
        return "automation.draft_missing_tag"
    if "destination" in missing:
        return "automation.draft_missing_destination"
    if "query" in missing:
        return "automation.draft_missing_query"
    return "automation.draft_clarify"
