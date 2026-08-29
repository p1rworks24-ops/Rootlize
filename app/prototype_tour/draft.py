"""Tutorial-safe Automation draft. Starts from Folder Start only."""

from __future__ import annotations

from app.automation.models import Workflow, new_workflow_id
from app.workspace.context import ORIGIN_BROWSE

SUGGESTED_SEARCH = "screenshot"


def tour_automation_workflow(
    *,
    folder: str | None = None,
    query: str = "",
    origin: str = ORIGIN_BROWSE,
) -> Workflow:
    """Folder Start only. The tour asks the user to add Search and Action."""
    del folder, query, origin
    return Workflow(
        id=new_workflow_id(),
        name="",
        steps=(),
        scope_folder=None,
        origin=ORIGIN_BROWSE,
    )
