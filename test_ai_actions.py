from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.ai_actions import AIActionService, ActionType


@dataclass(frozen=True)
class Result:
    image_id: int
    score: float


@dataclass(frozen=True)
class Page:
    results: tuple[Result, ...]


class HybridSearchSpy:
    def __init__(self, ids=(11, 22)):
        self.ids = ids
        self.calls = []

    def search(self, query, top_k, **kwargs):
        self.calls.append((query, top_k, kwargs))
        return Page(tuple(Result(value, 1 / (60 + rank)) for rank, value in enumerate(self.ids, 1)))


@pytest.mark.parametrize(
    ("instruction", "query"),
    [
        ("GitHubのスクショを探して", "GitHubのスクショ"),
        ("この前保存した料金表を探して", "この前保存した料金表"),
        ("Cursorのエラー画面を探して", "Cursorのエラー画面"),
        ("Find the GitHub screenshot", "the GitHub screenshot"),
    ],
)
def test_search_intents_use_hybrid_search(instruction, query):
    hybrid = HybridSearchSpy()
    plan = AIActionService(hybrid).plan(instruction)
    assert plan.action is ActionType.SEARCH
    assert plan.search_query == query
    assert plan.matched_image_ids == (11, 22)
    assert plan.confirmation_required is False
    assert hybrid.calls[0][0] == query


@pytest.mark.parametrize(
    ("instruction", "action", "query", "parameter"),
    [
        ("GitHubのスクショにworkタグを付けたい", ActionType.TAG, "GitHubのスクショ", ("tag", "work")),
        ("料金表の画像をFinanceフォルダに移動したい", ActionType.MOVE, "料金表", ("destination_folder", "Finance")),
        ("Tag Cursor error screens with work", ActionType.TAG, "Cursor error screens", ("tag", "work")),
        ("Move pricing table images to Finance folder", ActionType.MOVE, "pricing table images", ("destination_folder", "Finance")),
    ],
)
def test_mutations_are_planned_but_always_require_confirmation(
    instruction, action, query, parameter
):
    hybrid = HybridSearchSpy((7,))
    plan = AIActionService(hybrid).plan(instruction)
    assert plan.action is action
    assert plan.search_query == query
    assert getattr(plan.action_parameters, parameter[0]) == parameter[1]
    assert plan.matched_image_ids == (7,)
    assert plan.confirmation_required is True
    assert not hasattr(AIActionService, "execute")


def test_no_matches_and_unknown_instruction_fail_safe():
    no_match = AIActionService(HybridSearchSpy(())).plan("GitHubのスクショにworkタグを付けたい")
    assert no_match.confirmation_required
    assert no_match.clarification_required
    assert no_match.match_state == "no_match"
    assert "no_matches" in no_match.ambiguity_reasons

    hybrid = HybridSearchSpy()
    unknown = AIActionService(hybrid).plan("いい感じに整理して")
    assert unknown.action is ActionType.UNKNOWN
    assert unknown.clarification_required
    assert unknown.matched_image_ids == ()
    assert hybrid.calls == []


def test_candidate_scores_preserve_review_information():
    plan = AIActionService(HybridSearchSpy((4, 9))).plan("Find errors")
    assert plan.match_state == "multiple_candidates"
    assert [image_id for image_id, _ in plan.candidate_scores] == [4, 9]

