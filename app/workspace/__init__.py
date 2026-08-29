"""Session workspace for Find → Narrow → Act.

UI, Ask AI, and Automation share this result set and the
ActionProposal / ActPlan → ActionRequest boundary. Nothing here talks
to Qt or mutates the filesystem.
"""

from .act import (
    ActionProposal,
    bind_action_proposal,
    bound_proposal,
    proposal_to_request,
    resolve_destination_folder,
)
from .context import (
    FOCUS_RESULTS,
    FOCUS_SELECTION,
    ORIGIN_BROWSE,
    ORIGIN_MEANING,
    ORIGIN_TEXT,
    SOURCE_FOLDER,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    WorkspaceSession,
)
from .intent import (
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
    looks_like_act_plan,
)
from .plan import (
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    ActPlan,
    CombinedPreview,
    CombinedResult,
    PlanStep,
    PreparedActPlan,
    execute_act_plan,
    parse_plan_payload,
    prepare_act_plan,
    summarize_action_result,
    summarize_combined_result,
    validate_act_plan,
)
from .planner import PlannerOutcome, build_act_plan
from .router import route_ask_ai_turn
from .targets import TargetResolution, resolve_action_targets

__all__ = [
    "ActionProposal",
    "ActPlan",
    "AskAiTurn",
    "CombinedPreview",
    "CombinedResult",
    "KIND_ACT",
    "KIND_ACT_PLAN",
    "KIND_CLARIFY",
    "KIND_FIND",
    "KIND_HELP",
    "KIND_NARROW",
    "KIND_QUESTION",
    "KIND_UNSUPPORTED",
    "FOCUS_RESULTS",
    "FOCUS_SELECTION",
    "ORIGIN_BROWSE",
    "ORIGIN_MEANING",
    "ORIGIN_TEXT",
    "PlanStep",
    "PlannerOutcome",
    "PreparedActPlan",
    "SOURCE_FOLDER",
    "SOURCE_RESULT_SET",
    "SOURCE_SELECTION",
    "STEP_ACTION",
    "STEP_FIND",
    "STEP_NARROW",
    "SearchResultContext",
    "TargetResolution",
    "WorkspaceSession",
    "bind_action_proposal",
    "bound_proposal",
    "build_act_plan",
    "classify_ask_ai_turn",
    "execute_act_plan",
    "looks_like_act_plan",
    "parse_plan_payload",
    "prepare_act_plan",
    "proposal_to_request",
    "resolve_action_targets",
    "resolve_destination_folder",
    "route_ask_ai_turn",
    "summarize_action_result",
    "summarize_combined_result",
    "validate_act_plan",
]
