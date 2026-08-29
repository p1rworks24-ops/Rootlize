"""Unnamed tag removal is remove_all_tags. Named tags stay remove_tag."""
from __future__ import annotations

from pathlib import Path

from app.actions.models import ACTION_REMOVE_ALL_TAGS, ACTION_REMOVE_TAG
from app.i18n import t
from app.workspace import KIND_ACT, KIND_ACT_PLAN, ORIGIN_MEANING, SearchResultContext, route_ask_ai_turn
from app.workspace.intent import classify_ask_ai_turn
from app.workspace.plan import STEP_ACTION, ActPlan, PlanStep, _tag_preview_detail_lines, summarize_action_result
from app.workspace.planner import SYSTEM_PROMPT
from app.workspace.tag_semantics import (
    apply_tag_removal_semantics,
    looks_like_unnamed_tag_clear,
    named_tags_in_instruction,
)


def _png(path: Path) -> Path:
    path.write_bytes(b"png")
    return path


def _ctx(*paths: Path, query: str = "game") -> SearchResultContext:
    mapping = {str(path.resolve()): index + 1 for index, path in enumerate(paths)}
    return SearchResultContext().with_results(
        image_ids=tuple(mapping[str(path.resolve())] for path in paths),
        paths=[str(path) for path in paths],
        query=query,
        scope_folder=paths[0].parent if paths else None,
        origin=ORIGIN_MEANING,
        path_to_image_id=mapping,
    )


def _ai(payload: dict):
    def complete(_system_prompt: str, _user_prompt: str, **_kwargs) -> dict:
        return dict(payload)

    return complete


def _remove_tag_payload(tag: str = "dog", tags: list[str] | None = None) -> dict:
    parameters = {"tags": list(tags)} if tags is not None else {"tag": tag}
    return {
        "intent": "action",
        "status": "plan",
        "clarify_message": "",
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "query": "",
                "action_id": ACTION_REMOVE_TAG,
                "target_source": "result_set",
                "parameters": parameters,
            }
        ],
    }


def test_unnamed_clear_phrases():
    for text in (
        "remove tags from these images",
        "remove the tags from these",
        "clear the tags",
        "clear all tags",
        "remove all tags",
        "take the tags off these images",
        "タグを外して",
        "タグを全部消して",
        "この画像たちのタグを削除して",
    ):
        assert looks_like_unnamed_tag_clear(text), text
        assert named_tags_in_instruction(text) == ()


def test_named_tag_phrases_are_not_unnamed_clear():
    for text in (
        "remove the dog tag",
        "remove Test from these",
        "delete the Work tag",
        "dogタグを外して",
        "remove dog and anime tags",
    ):
        assert not looks_like_unnamed_tag_clear(text), text
        assert named_tags_in_instruction(text)


def test_guessed_remove_tag_becomes_remove_all():
    plan = ActPlan(
        steps=(
            PlanStep(
                step_id="step_1",
                type=STEP_ACTION,
                action_id=ACTION_REMOVE_TAG,
                target_source="result_set",
                parameters={"tag": "dog"},
            ),
        ),
        instruction="remove tags from these images",
    )
    rewritten, reasons = apply_tag_removal_semantics(plan)
    assert rewritten.steps[0].action_id == ACTION_REMOVE_ALL_TAGS
    assert "tag" not in rewritten.steps[0].parameters
    assert "guessed_tag" not in reasons


def test_named_remove_tag_is_kept():
    plan = ActPlan(
        steps=(
            PlanStep(
                step_id="step_1",
                type=STEP_ACTION,
                action_id=ACTION_REMOVE_TAG,
                target_source="result_set",
                parameters={"tag": "dog"},
            ),
        ),
        instruction="remove dog tag from these images",
    )
    rewritten, reasons = apply_tag_removal_semantics(plan)
    assert rewritten.steps[0].action_id == ACTION_REMOVE_TAG
    assert rewritten.steps[0].parameters["tag"] == "dog"
    assert reasons == ()


def test_planner_guess_is_rewritten_on_product_path(tmp_path):
    paths = [_png(tmp_path / f"{index}.png") for index in range(7)]
    ctx = _ctx(*paths)
    turn = route_ask_ai_turn(
        "remove tags from these images",
        ctx,
        allow_ai=True,
        complete_json=_ai(_remove_tag_payload("dog")),
    )
    assert turn.kind in {KIND_ACT, KIND_ACT_PLAN}
    if turn.proposal is not None:
        assert turn.proposal.action_id == ACTION_REMOVE_ALL_TAGS
        assert not turn.proposal.parameters.get("tag")
    else:
        actions = [step.action_id for step in turn.plan.action_steps()]
        assert actions == [ACTION_REMOVE_ALL_TAGS]


def test_specific_tag_stays_remove_tag(tmp_path):
    paths = [_png(tmp_path / f"{index}.png") for index in range(3)]
    ctx = _ctx(*paths)
    turn = route_ask_ai_turn(
        "remove dog tag from these images",
        ctx,
        allow_ai=True,
        complete_json=_ai(_remove_tag_payload("dog")),
    )
    assert turn.kind in {KIND_ACT, KIND_ACT_PLAN}
    if turn.proposal is not None:
        assert turn.proposal.action_id == ACTION_REMOVE_TAG
        assert turn.proposal.parameters.get("tag") == "dog"
    else:
        step = turn.plan.action_steps()[0]
        assert step.action_id == ACTION_REMOVE_TAG
        assert step.parameters.get("tag") == "dog" or step.parameters.get("tags") == ["dog"]


def test_multiple_named_tags_use_remove_tag_tags(tmp_path):
    paths = [_png(tmp_path / f"{index}.png") for index in range(3)]
    ctx = _ctx(*paths)
    turn = route_ask_ai_turn(
        "remove dog and anime tags",
        ctx,
        allow_ai=True,
        complete_json=_ai(_remove_tag_payload(tags=["dog", "anime"])),
    )
    assert turn.kind in {KIND_ACT, KIND_ACT_PLAN}
    if turn.proposal is not None:
        assert turn.proposal.action_id == ACTION_REMOVE_TAG
        tags = turn.proposal.parameters.get("tags") or [turn.proposal.parameters.get("tag")]
        assert set(tags) == {"dog", "anime"}
    else:
        step = turn.plan.action_steps()[0]
        assert step.action_id == ACTION_REMOVE_TAG
        tags = step.parameters.get("tags") or [step.parameters.get("tag")]
        assert set(tags) == {"dog", "anime"}


def test_local_parser_unnamed_is_remove_all(tmp_path):
    paths = [_png(tmp_path / f"{index}.png") for index in range(3)]
    turn = classify_ask_ai_turn("remove tags from these images", _ctx(*paths))
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    assert turn.proposal.action_id == ACTION_REMOVE_ALL_TAGS


def test_remove_all_preview_lists_tags_and_noop():
    class Item:
        def __init__(self, removed, status="ready"):
            self.status = status
            self.after = {"removed_tags": removed}

    class Plan:
        items = (
            Item(["dog"]),
            Item(["dog"]),
            Item(["anime"]),
            Item([], status="skipped"),
        )

    lines = _tag_preview_detail_lines(Plan(), lambda key, **kwargs: t(key, **kwargs), action_id=ACTION_REMOVE_ALL_TAGS)
    blob = "\n".join(lines)
    assert "dog" in blob
    assert "anime" in blob
    assert t("images.ai.plan_no_tags_count", count=1) in blob


def test_remove_all_completion_mentions_noop_images():
    from app.actions.models import ActionItemResult, ActionTarget, STATUS_SKIPPED, STATUS_SUCCESS, result_from_items

    result = result_from_items(
        ACTION_REMOVE_ALL_TAGS,
        [
            ActionItemResult(target=ActionTarget(path="a.png"), status=STATUS_SUCCESS),
            ActionItemResult(target=ActionTarget(path="b.png"), status=STATUS_SUCCESS),
            ActionItemResult(target=ActionTarget(path="c.png"), status=STATUS_SKIPPED),
        ],
    )
    text = summarize_action_result(result, t=t)
    assert t("images.ai.act_done_remove_all_tags", count=2) in text
    assert t("images.ai.act_no_tags_note", count=1) in text


def test_planner_prompt_has_unnamed_tag_rule():
    assert "remove tags from these images" in SYSTEM_PROMPT
    assert "use remove_all_tags" in SYSTEM_PROMPT
    assert "representative tag" in SYSTEM_PROMPT


def test_missing_tag_parameter_does_not_invent_catalog_tag():
    plan = ActPlan(
        steps=(
            PlanStep(
                step_id="step_1",
                type=STEP_ACTION,
                action_id=ACTION_REMOVE_TAG,
                target_source="result_set",
            ),
        ),
        instruction="remove tags from these images",
    )
    rewritten, reasons = apply_tag_removal_semantics(plan)
    assert rewritten.steps[0].action_id == ACTION_REMOVE_ALL_TAGS
    assert "tag" not in rewritten.steps[0].parameters
    assert "guessed_tag" not in reasons
