"""Create preview-only action plans using the existing hybrid search."""
from __future__ import annotations

from pathlib import Path

from .models import ActionPlan, ActionType, MUTATING_ACTIONS
from .parser import LocalActionParser


class AIActionService:
    def __init__(self, hybrid_search, parser: LocalActionParser | None = None):
        self.hybrid_search = hybrid_search
        self.parser = parser or LocalActionParser()

    def plan(
        self,
        instruction: str,
        *,
        top_k: int = 20,
        folder_path: str | Path | None = None,
    ) -> ActionPlan:
        parsed = self.parser.parse(instruction)
        reasons = list(parsed.ambiguity_reasons)
        results = ()
        if parsed.search_query:
            page = self.hybrid_search.search(
                parsed.search_query, top_k, folder_path=folder_path
            )
            results = tuple(page.results)

        if not results and parsed.search_query:
            reasons.append("no_matches")
        if parsed.action is ActionType.UNKNOWN:
            reasons.append("clarification_needed")

        ids = tuple(result.image_id for result in results)
        scores = tuple((result.image_id, float(result.score)) for result in results)
        match_state = "no_match" if not ids else "single_candidate" if len(ids) == 1 else "multiple_candidates"
        clarification_required = bool(reasons)

        return ActionPlan(
            instruction=str(instruction or ""),
            action=parsed.action,
            search_query=parsed.search_query,
            matched_image_ids=ids,
            confidence=parsed.confidence,
            match_state=match_state,
            action_parameters=parsed.parameters,
            confirmation_required=parsed.action in MUTATING_ACTIONS,
            clarification_required=clarification_required,
            ambiguity_reasons=tuple(dict.fromkeys(reasons)),
            candidate_scores=scores,
        )

