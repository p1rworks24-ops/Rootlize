"""Ask AI Action targets resolve from Planner intent + SearchResultContext."""
from __future__ import annotations

from pathlib import Path

from app.actions import ACTION_ADD_TAG
from app.workspace import (
    FOCUS_RESULTS,
    FOCUS_SELECTION,
    KIND_ACT,
    KIND_CLARIFY,
    KIND_FIND,
    ORIGIN_MEANING,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    bind_action_proposal,
    classify_ask_ai_turn,
    route_ask_ai_turn,
)
from app.workspace.act import ActionProposal
from app.workspace.targets import (
    REASON_AMBIGUOUS,
    REASON_MISSING_RESULTS,
    REASON_MISSING_SELECTION,
    REASON_NO_TARGETS,
    REASON_STALE_FOLDER,
    resolve_action_targets,
)


def _png(path: Path) -> Path:
    path.write_bytes(b"png")
    return path


def _ctx(
    *paths: Path,
    selected: tuple[Path, ...] = (),
    query: str = "dogs",
    narrowed: bool = False,
    folder: Path | None = None,
) -> SearchResultContext:
    mapping = {str(path.resolve()): index + 1 for index, path in enumerate(paths)}
    ctx = SearchResultContext().with_results(
        image_ids=tuple(mapping[str(path.resolve())] for path in paths),
        paths=[str(path) for path in paths],
        query=query,
        scope_folder=folder or (paths[0].parent if paths else None),
        origin=ORIGIN_MEANING,
        narrowed=narrowed,
        path_to_image_id=mapping,
    )
    if selected:
        ctx = ctx.with_selection(
            image_ids=tuple(mapping[str(path.resolve())] for path in selected),
            paths=[str(path) for path in selected],
        )
    return ctx


def test_one_result_this_image_uses_result_not_empty_selection(tmp_path):
    a = _png(tmp_path / "anime.png")
    ctx = _ctx(a, query="anime", narrowed=True)
    assert not ctx.has_selection()
    resolution = resolve_action_targets(
        SOURCE_SELECTION,
        ctx,
        instruction='add tag "anime" to this image',
        current_folder=tmp_path,
    )
    assert resolution.ok
    assert resolution.source_used == SOURCE_RESULT_SET
    assert resolution.image_ids == (1,)
    assert resolution.resolved_count == 1
    bound, bound_resolution = bind_action_proposal(
        ActionProposal(
            action_id=ACTION_ADD_TAG,
            target_source=SOURCE_SELECTION,
            parameters={"tag": "anime"},
            instruction='add tag "anime" to this image',
        ),
        ctx,
        current_folder=tmp_path,
    )
    assert bound_resolution.ok
    assert bound.image_ids == (1,)
    assert not ctx.has_selection()


def test_search_then_favorite_them_uses_all_results(tmp_path):
    paths = [_png(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    ctx = _ctx(*paths, query="cat")
    resolution = resolve_action_targets(
        SOURCE_RESULT_SET,
        ctx,
        instruction="Favorite them",
        current_folder=tmp_path,
    )
    assert resolution.ok
    assert resolution.source_used == SOURCE_RESULT_SET
    assert resolution.resolved_count == 3


def test_planner_selection_after_search_still_uses_results(tmp_path):
    paths = [_png(tmp_path / name) for name in ("a.png", "b.png")]
    ctx = _ctx(*paths, query="dogs")
    resolution = resolve_action_targets(
        SOURCE_SELECTION,
        ctx,
        instruction="Add Test to these",
        current_folder=tmp_path,
    )
    assert resolution.ok
    assert resolution.source_used == SOURCE_RESULT_SET
    assert resolution.resolved_count == 2


def test_explicit_selection_uses_selection_not_results(tmp_path):
    a, b, c = [_png(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    ctx = _ctx(a, b, c, selected=(a, b), query="dogs")
    resolution = resolve_action_targets(
        SOURCE_SELECTION,
        ctx,
        instruction="Add Test to selected images",
        current_folder=tmp_path,
    )
    assert resolution.ok
    assert resolution.source_used == SOURCE_SELECTION
    assert resolution.resolved_count == 2


def test_explicit_results_uses_result_set(tmp_path):
    a, b, c = [_png(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    ctx = _ctx(a, b, c, selected=(a,), query="dogs")
    resolution = resolve_action_targets(
        SOURCE_RESULT_SET,
        ctx,
        instruction="Add Test to these results",
        current_folder=tmp_path,
    )
    assert resolution.ok
    assert resolution.source_used == SOURCE_RESULT_SET
    assert resolution.resolved_count == 3


def test_explicit_selection_without_selection_clarifies(tmp_path):
    paths = [_png(tmp_path / name) for name in ("a.png", "b.png")]
    ctx = _ctx(*paths, query="dogs")
    resolution = resolve_action_targets(
        SOURCE_SELECTION,
        ctx,
        instruction="Tag the selected images Work",
        current_folder=tmp_path,
    )
    assert not resolution.ok
    assert resolution.reason == REASON_MISSING_SELECTION
    assert resolution.message_key == "images.ai.missing_target"
    assert resolution.hint_key == "images.ai.clarify_target"


def test_ambiguous_these_with_both_sets_clarifies(tmp_path):
    a, b, c = [_png(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    ctx = SearchResultContext(
        result_image_ids=(1, 2, 3),
        result_paths=tuple(str(path.resolve()) for path in (a, b, c)),
        selected_image_ids=(1, 2),
        selected_paths=tuple(str(path.resolve()) for path in (a, b)),
        scope_folder=str(tmp_path.resolve()),
        query="dogs",
        last_target_focus="",
    )
    resolution = resolve_action_targets(
        "",
        ctx,
        instruction="Add Work to these",
        current_folder=tmp_path,
    )
    assert not resolution.ok
    assert resolution.ambiguous
    assert resolution.reason == REASON_AMBIGUOUS
    assert resolution.message_key == "images.ai.ambiguous_target"


def test_no_state_clarifies_instead_of_internal_error():
    resolution = resolve_action_targets(
        SOURCE_RESULT_SET,
        SearchResultContext(),
        instruction="Add Test to these",
    )
    assert not resolution.ok
    assert resolution.reason in {REASON_NO_TARGETS, REASON_MISSING_RESULTS}
    assert resolution.message_key == "images.ai.missing_target"
    turn = classify_ask_ai_turn("add Test tag to these")
    assert turn.kind == KIND_CLARIFY
    assert turn.message_key == "images.ai.missing_target"


def test_stale_folder_results_are_not_used(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    a = _png(tmp_path / "a.png")
    ctx = _ctx(a, query="dogs", folder=tmp_path)
    resolution = resolve_action_targets(
        SOURCE_RESULT_SET,
        ctx,
        instruction="Favorite those",
        current_folder=other,
    )
    assert not resolution.ok
    assert resolution.reason == REASON_STALE_FOLDER


def test_last_focus_prefers_recent_selection_when_implicit(tmp_path):
    a, b, c = [_png(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    ctx = _ctx(a, b, c, selected=(a, b), query="dogs")
    assert ctx.last_target_focus == FOCUS_SELECTION
    resolution = resolve_action_targets("", ctx, instruction="Favorite them", current_folder=tmp_path)
    assert resolution.ok
    assert resolution.source_used == SOURCE_SELECTION
    assert resolution.resolved_count == 2


def test_last_focus_prefers_results_right_after_search(tmp_path):
    a, b = [_png(tmp_path / name) for name in ("a.png", "b.png")]
    ctx = _ctx(a, b, query="dogs")
    assert ctx.last_target_focus == FOCUS_RESULTS
    resolution = resolve_action_targets("", ctx, instruction="Favorite them", current_folder=tmp_path)
    assert resolution.ok
    assert resolution.source_used == SOURCE_RESULT_SET
    assert resolution.resolved_count == 2


def test_local_this_image_after_one_result(tmp_path):
    a = _png(tmp_path / "one.png")
    ctx = _ctx(a, query="anime", narrowed=True)
    turn = classify_ask_ai_turn('add tag "anime" to this image', ctx)
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    assert turn.proposal.action_id == ACTION_ADD_TAG
    bound, resolution = bind_action_proposal(turn.proposal, ctx, current_folder=tmp_path)
    assert resolution.ok
    assert bound.image_ids == (1,)


def test_planner_selection_payload_binds_single_result(tmp_path):
    a = _png(tmp_path / "anime.png")
    ctx = _ctx(a, query="anime", narrowed=True)

    def complete(_system, _user, **_kwargs):
        return {
            "intent": "action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {
                    "id": "step_1",
                    "type": "action",
                    "query": "",
                    "action_id": ACTION_ADD_TAG,
                    "target_source": SOURCE_SELECTION,
                    "parameters": {"tag": "anime"},
                }
            ],
        }

    turn = route_ask_ai_turn(
        'add tag "anime" to this image',
        ctx,
        complete_json=complete,
    )
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    bound, resolution = bind_action_proposal(turn.proposal, ctx, current_folder=tmp_path)
    assert resolution.ok
    assert bound.image_ids == (1,)
    assert bound.target_source == SOURCE_RESULT_SET
    assert turn.kind != KIND_FIND
