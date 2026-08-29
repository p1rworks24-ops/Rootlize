"""Narrow, defensive execution boundary for confirmed AI tag actions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.actions import (
    ACTION_ADD_TAG,
    ActionContext,
    ActionRequest,
    ActionService,
    ActionTarget,
)
from app.utils.tag_format import normalize_tag

from .models import ActionPlan, ActionType


class ActionExecutionRejected(ValueError):
    """Raised when a plan is not eligible for execution."""


@dataclass(frozen=True)
class ActionExecutionResult:
    succeeded_image_ids: tuple[int, ...] = ()
    skipped_image_ids: tuple[int, ...] = ()
    failed_image_ids: tuple[int, ...] = ()


class ActionExecutor:
    """Execute only an explicitly confirmed tag plan using the shared Action layer."""

    def __init__(self, image_repository, metadata_service) -> None:
        self._images = image_repository
        self._metadata = metadata_service

    def execute_tag(
        self,
        plan: ActionPlan,
        *,
        confirmed: bool,
        preview_paths: Mapping[int, str | Path],
    ) -> ActionExecutionResult:
        self._validate(plan, confirmed=confirmed)
        normalized_tag = normalize_tag(plan.action_parameters.tag or "")
        if not normalized_tag:
            raise ActionExecutionRejected("A valid tag parameter is required.")

        planned_ids = tuple(dict.fromkeys(plan.matched_image_ids))
        if set(preview_paths) != set(planned_ids):
            raise ActionExecutionRejected("The preview target set is incomplete or stale.")

        request = ActionRequest(
            action_id=ACTION_ADD_TAG,
            targets=tuple(
                ActionTarget(image_id=image_id, path=str(preview_paths[image_id]))
                for image_id in planned_ids
            ),
            parameters={"tag": normalized_tag},
        )
        result = ActionService(
            ActionContext(metadata=self._metadata, ocr=self._images)
        ).execute(request, confirmed=True)

        succeeded: list[int] = []
        skipped: list[int] = []
        failed: list[int] = []
        for item in result.items:
            image_id = item.target.image_id
            if image_id is None:
                continue
            if item.status == "success":
                succeeded.append(image_id)
            elif item.status == "skipped":
                skipped.append(image_id)
            else:
                failed.append(image_id)

        return ActionExecutionResult(
            succeeded_image_ids=tuple(succeeded),
            skipped_image_ids=tuple(skipped),
            failed_image_ids=tuple(failed),
        )

    @staticmethod
    def _validate(plan: ActionPlan, *, confirmed: bool) -> None:
        if plan.action is not ActionType.TAG:
            raise ActionExecutionRejected("Only tag actions can be executed.")
        if not plan.matched_image_ids:
            raise ActionExecutionRejected("At least one target image is required.")
        if plan.clarification_required:
            raise ActionExecutionRejected("Plans requiring clarification cannot execute.")
        if not plan.confirmation_required or not confirmed:
            raise ActionExecutionRejected("Explicit confirmation is required.")
        if not plan.action_parameters.tag:
            raise ActionExecutionRejected("A tag parameter is required.")
