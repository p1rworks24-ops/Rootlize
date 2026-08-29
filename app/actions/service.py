"""Plan and execute registered Actions. No confirmation UI lives here."""
from __future__ import annotations

from .context import ActionContext
from .models import (
    ActionPlan,
    ActionRequest,
    ActionResult,
    blocked_result,
)
from .registry import ActionRegistry, default_registry


class ActionService:
    """Shared Action gateway: Request → Validate/Preview → Execute → Result."""

    def __init__(self, context: ActionContext, registry: ActionRegistry | None = None) -> None:
        self.context = context
        self.registry = registry or default_registry()

    def plan(self, request: ActionRequest) -> ActionPlan:
        action = self.registry.get(request.action_id)
        return action.plan(request, self.context)

    def execute(self, request: ActionRequest, *, confirmed: bool = False) -> ActionResult:
        action = self.registry.get(request.action_id)
        plan = action.plan(request, self.context)
        if plan.confirmation_required and not confirmed:
            return blocked_result(request.action_id, plan)
        return action.execute(request, self.context, plan)
