"""Find → Narrow → Act session types and intent routing."""
from __future__ import annotations

from pathlib import Path

from app.actions import (
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
)
from app.workspace import (
    KIND_ACT,
    KIND_ACT_PLAN,
    KIND_CLARIFY,
    KIND_FIND,
    KIND_NARROW,
    ORIGIN_MEANING,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    WorkspaceSession,
    bound_proposal,
    classify_ask_ai_turn,
    proposal_to_request,
    resolve_destination_folder,
)


def _context_with_results(*paths: Path, selected: tuple[Path, ...] = ()) -> SearchResultContext:
    mapping = {str(path.resolve()): index + 1 for index, path in enumerate(paths)}
    ctx = SearchResultContext().with_results(
        image_ids=tuple(mapping[str(path.resolve())] for path in paths),
        paths=[str(path) for path in paths],
        query="dog",
        scope_folder=paths[0].parent if paths else None,
        origin=ORIGIN_MEANING,
        path_to_image_id=mapping,
    )
    if selected:
        ctx = ctx.with_selection(
            image_ids=tuple(mapping[str(path.resolve())] for path in selected),
            paths=[str(path) for path in selected],
        )
    return ctx


def test_context_distinguishes_result_set_and_selection(tmp_path):
    a, b, c = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    for path in (a, b, c):
        path.write_bytes(b"png")
    session = WorkspaceSession()
    session.set_find(
        image_ids=(1, 2, 3),
        paths=[str(a), str(b), str(c)],
        query="dog",
        scope_folder=tmp_path,
        origin=ORIGIN_MEANING,
        path_to_image_id={str(a.resolve()): 1, str(b.resolve()): 2, str(c.resolve()): 3},
    )
    session.set_selection(image_ids=(2,), paths=[str(b)])
    ctx = session.context
    assert ctx.targets(SOURCE_RESULT_SET)[0] == (1, 2, 3)
    assert ctx.targets(SOURCE_SELECTION)[0] == (2,)
    session.set_narrow(image_ids=(1, 3), paths=[str(a), str(c)], query="night")
    assert session.context.narrowed is True
    assert session.context.query == "night"
    assert session.context.find_query == "dog"
    assert session.context.narrow_query == "night"
    assert session.context.result_image_ids == (1, 3)


def test_find_narrow_and_act_intents(tmp_path):
    a, b = tmp_path / "one.png", tmp_path / "two.png"
    for path in (a, b):
        path.write_bytes(b"png")
    ctx = _context_with_results(a, b, selected=(a,))

    find = classify_ask_ai_turn("犬の画像を探す")
    assert find.kind == KIND_FIND
    assert find.query == "犬の画像"

    chrome = classify_ask_ai_turn("Google Chrome")
    assert chrome.kind == KIND_CLARIFY
    assert "underspecified_search" in chrome.reasons
    assert chrome.kind != KIND_FIND

    narrow = classify_ask_ai_turn("その中で設定画面だけ", ctx)
    assert narrow.kind == KIND_NARROW
    assert narrow.query == "設定画面"
    assert narrow.target_source == SOURCE_RESULT_SET

    night = classify_ask_ai_turn("その中で夜に撮られたもの", ctx)
    assert night.kind == KIND_NARROW
    assert "夜" in night.query

    chained = classify_ask_ai_turn("設定画面だけ", ctx)
    assert chained.kind == KIND_NARROW

    move = classify_ask_ai_turn("この3枚をDogsへ移動して", ctx)
    assert move.kind == KIND_ACT
    assert move.proposal is not None
    assert move.proposal.action_id == ACTION_MOVE
    assert move.proposal.parameters["destination_name"] == "Dogs"
    assert "image_ids" not in move.proposal.parameters
    assert move.proposal.image_ids == ()

    tag = classify_ask_ai_turn("これらにworkタグを付けて", ctx)
    assert tag.kind == KIND_ACT
    assert tag.proposal.action_id == ACTION_ADD_TAG
    assert tag.proposal.target_source == SOURCE_SELECTION
    assert tag.proposal.parameters["tag"] == "work"

    english_tags = classify_ask_ai_turn("add Game tags to game images", ctx)
    assert english_tags.kind == KIND_ACT
    assert english_tags.proposal is not None
    assert english_tags.proposal.action_id == ACTION_ADD_TAG
    assert english_tags.proposal.parameters["tag"] == "Game"
    assert english_tags.proposal.target_source == SOURCE_RESULT_SET

    english_tag = classify_ask_ai_turn("add work tag to these", ctx)
    assert english_tag.kind == KIND_ACT
    assert english_tag.proposal is not None
    assert english_tag.proposal.action_id == ACTION_ADD_TAG
    assert english_tag.proposal.parameters["tag"] == "work"

    add_the_tag = classify_ask_ai_turn("add the tag Game to these results", ctx)
    assert add_the_tag.kind == KIND_ACT
    assert add_the_tag.proposal is not None
    assert add_the_tag.proposal.parameters["tag"] == "Game"

    rename = classify_ask_ai_turn("この画像をheroにリネームして", ctx)
    assert rename.kind == KIND_ACT
    assert rename.proposal.action_id == ACTION_RENAME
    assert rename.target_source == SOURCE_SELECTION

    folder = classify_ask_ai_turn("Chrome Settingsフォルダを作って")
    assert folder.kind == KIND_ACT
    assert folder.proposal.action_id == ACTION_CREATE_FOLDER
    assert folder.proposal.parameters["name"] == "Chrome Settings"


def test_proposal_becomes_action_request_without_executing(tmp_path, monkeypatch):
    a, b = tmp_path / "one.png", tmp_path / "two.png"
    for path in (a, b):
        path.write_bytes(b"png")
    ctx = _context_with_results(a, b)
    turn = classify_ask_ai_turn("この結果をDogsへ移動して", ctx)
    proposal = bound_proposal(turn.proposal, ctx)
    assert proposal.image_ids == (1, 2)
    request = proposal_to_request(proposal, current_folder=tmp_path)
    assert request.action_id == ACTION_MOVE
    assert [target.image_id for target in request.targets] == [1, 2]
    assert Path(request.param("destination_path")).name == "Dogs"
    dest = resolve_destination_folder("Dogs", current_folder=tmp_path)
    assert dest == tmp_path / "Dogs"


def test_act_without_results_asks_for_target():
    turn = classify_ask_ai_turn("これらをDogsへ移動して")
    assert turn.kind == KIND_CLARIFY
    assert "no_targets" in turn.reasons


def test_narrow_without_results_asks_for_target():
    turn = classify_ask_ai_turn("その中で夜だけ")
    assert turn.kind == KIND_CLARIFY
    assert "no_targets" in turn.reasons


def test_current_reference_phrases_use_result_set_or_selection(tmp_path):
    a, b = tmp_path / "one.png", tmp_path / "two.png"
    for path in (a, b):
        path.write_bytes(b"png")
    ctx = _context_with_results(a, b, selected=(a,))

    result_tag = classify_ask_ai_turn("この結果に test タグを付けて", ctx)
    assert result_tag.kind == KIND_ACT
    assert result_tag.proposal.action_id == ACTION_ADD_TAG
    assert result_tag.proposal.parameters["tag"] == "test"
    assert result_tag.target_source == SOURCE_RESULT_SET
    assert result_tag.proposal.image_ids == ()

    these = classify_ask_ai_turn("これらに selected-test タグを付けて", ctx)
    assert these.kind == KIND_ACT
    assert these.proposal.target_source == SOURCE_SELECTION
    assert these.proposal.parameters["tag"] == "selected-test"

    selected = classify_ask_ai_turn("選択した画像に selected-test タグを付けて", ctx)
    assert selected.kind == KIND_ACT
    assert selected.target_source == SOURCE_SELECTION
    assert selected.proposal.parameters["tag"] == "selected-test"

    # 「これ」 is not a dedicated selection keyword; current default is the result set.
    this = classify_ask_ai_turn("これに test タグを付けて", ctx)
    assert this.kind == KIND_ACT
    assert this.target_source == SOURCE_RESULT_SET
    assert this.proposal.parameters["tag"] == "test"

    narrow = classify_ask_ai_turn("その中で夜の画像だけ", ctx)
    assert narrow.kind == KIND_NARROW
    assert narrow.query == "夜"
    assert narrow.target_source == SOURCE_RESULT_SET


def test_natural_language_tag_actions_do_not_fall_back_to_find(tmp_path):
    a, b = tmp_path / "one.png", tmp_path / "two.png"
    for path in (a, b):
        path.write_bytes(b"png")
    ctx = _context_with_results(a, b)

    remove_all = classify_ask_ai_turn("remove tags", ctx)
    assert remove_all.kind == KIND_CLARIFY
    assert remove_all.message_key == "images.ai.which_tag_remove"
    assert "tag_missing" in remove_all.reasons

    remove_named = classify_ask_ai_turn("remove tags to this dog images", ctx)
    assert remove_named.kind == KIND_CLARIFY
    assert remove_named.message_key == "images.ai.which_tag_remove"
    assert remove_named.target_source == SOURCE_RESULT_SET

    change = classify_ask_ai_turn(
        'Please change the tags on the five dog images you searched for to "Test".',
        ctx,
    )
    assert change.kind == KIND_ACT
    assert change.proposal is not None
    assert change.proposal.action_id == ACTION_REPLACE_TAGS
    assert change.proposal.parameters.get("tags") == ["Test"]
    assert change.kind != KIND_FIND

    no_context_remove = classify_ask_ai_turn("remove tags")
    assert no_context_remove.kind == KIND_CLARIFY
    assert no_context_remove.message_key == "images.ai.missing_target"

    find_plus_remove = classify_ask_ai_turn("remove tags to this dog images")
    assert find_plus_remove.kind == KIND_ACT_PLAN
    assert find_plus_remove.kind != KIND_FIND

    named_remove = classify_ask_ai_turn("remove the tag Game from these results", ctx)
    assert named_remove.kind == KIND_ACT
    assert named_remove.proposal is not None
    assert named_remove.proposal.action_id == ACTION_REMOVE_TAG
    assert named_remove.proposal.parameters["tag"] == "Game"

    search = classify_ask_ai_turn("dog")
    assert search.kind == KIND_CLARIFY
    assert "underspecified_search" in search.reasons
    assert search.kind != KIND_FIND

    tagged_photos = classify_ask_ai_turn("images with tags")
    assert tagged_photos.kind != KIND_FIND
