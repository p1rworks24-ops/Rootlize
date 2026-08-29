"""Ask AI Action capability expansion: tags, rename, multi-action, safety."""
from __future__ import annotations

from pathlib import Path

from app.actions import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
    ActionContext,
    ActionService,
)
from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.services.metadata_service import MetadataService
from app.workspace import (
    KIND_ACT,
    KIND_ACT_PLAN,
    KIND_CLARIFY,
    KIND_FIND,
    KIND_UNSUPPORTED,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    classify_ask_ai_turn,
    execute_act_plan,
    prepare_act_plan,
    route_ask_ai_turn,
)
from app.workspace.act import resolve_destination_folder
from app.workspace.capabilities import allowed_action_ids, format_capability_catalog
from app.workspace.plan import apply_target_filters
from app.workspace.planner import build_act_plan
from app.actions.models import ActionRequest, ActionTarget


def _png(path: Path) -> Path:
    path.write_bytes(b"png")
    return path


def _ctx(*paths: Path, selected: tuple[Path, ...] = (), query: str = "dogs") -> SearchResultContext:
    mapping = {str(path.resolve()): index + 1 for index, path in enumerate(paths)}
    return SearchResultContext(
        query=query,
        result_paths=tuple(str(path.resolve()) for path in paths),
        result_image_ids=tuple(mapping[str(path.resolve())] for path in paths),
        path_to_image_id=mapping,
        selected_paths=tuple(str(path.resolve()) for path in selected),
        selected_image_ids=tuple(mapping[str(path.resolve())] for path in selected if str(path.resolve()) in mapping),
    )


def _service(tmp_path: Path):
    metadata = MetadataService()
    database = OCRDatabase(tmp_path / "ocr.sqlite3").open()
    ocr = OCRRepository(database)
    return ActionService(ActionContext(metadata=metadata, ocr=ocr, app_root=tmp_path, managed_root=tmp_path)), metadata, ocr, database


def _index(ocr: OCRRepository, path: Path) -> int:
    fingerprint = calculate_quick_fingerprint(path)
    record = ocr.upsert_image(
        path,
        size_bytes=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
        quick_fingerprint=fingerprint,
    )
    return int(record.image_id)


def test_capability_catalog_is_source_of_truth():
    ids = allowed_action_ids()
    catalog = format_capability_catalog()
    for action_id in (
        ACTION_REMOVE_ALL_TAGS,
        ACTION_REPLACE_TAGS,
        ACTION_ADD_TAG,
        ACTION_REMOVE_TAG,
        ACTION_ADD_FAVORITE,
        ACTION_REMOVE_FAVORITE,
        ACTION_MOVE,
        ACTION_RENAME,
        ACTION_CREATE_FOLDER,
    ):
        assert action_id in ids
        assert action_id in catalog
    assert "delete" not in ids
    assert "shell" not in catalog
    assert "rename_strategy" in catalog
    assert "Do not pass tag=all" in catalog


def test_natural_language_tag_and_rename_actions(tmp_path):
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png")
    ctx = _ctx(a, b)
    remove_all = classify_ask_ai_turn("Remove all tags from these images.", ctx)
    assert remove_all.kind == KIND_ACT
    assert remove_all.proposal.action_id == ACTION_REMOVE_ALL_TAGS

    replaced = classify_ask_ai_turn("Replace the tags on these images with Test and Work.", ctx)
    assert replaced.kind == KIND_ACT
    assert replaced.proposal.action_id == ACTION_REPLACE_TAGS
    assert replaced.proposal.parameters["tags"] == ["Test", "Work"]

    added = classify_ask_ai_turn("Add Pets and Outdoor tags to these images.", ctx)
    assert added.kind == KIND_ACT
    assert added.proposal.action_id == ACTION_ADD_TAG
    assert added.proposal.parameters.get("tags") == ["Pets", "Outdoor"]

    removed = classify_ask_ai_turn("Remove Test and Old from these results.", ctx)
    assert removed.kind == KIND_ACT
    assert removed.proposal.action_id == ACTION_REMOVE_TAG
    assert removed.proposal.parameters.get("tags") == ["Test", "Old"]

    named = classify_ask_ai_turn("remove the tag Game from these results", ctx)
    assert named.kind == KIND_ACT
    assert named.proposal.action_id == ACTION_REMOVE_TAG
    assert named.proposal.parameters["tag"] == "Game"

    prefix = classify_ask_ai_turn('Add "Vacation_" to the beginning of these filenames.', ctx)
    assert prefix.kind == KIND_ACT
    assert prefix.proposal.parameters["rename_strategy"] == "prefix"
    assert prefix.proposal.parameters["prefix"] == "Vacation_"

    sequential = classify_ask_ai_turn("Rename these Cat 001, Cat 002, Cat 003...", ctx)
    assert sequential.kind == KIND_ACT
    assert sequential.proposal.action_id == ACTION_RENAME
    assert sequential.proposal.parameters["rename_strategy"] == "numbered"
    assert sequential.proposal.parameters["base_name"] == "Cat"

    empty = classify_ask_ai_turn("Replace their tags with", ctx)
    assert empty.kind == KIND_CLARIFY
    assert "empty_replace_tags" in empty.reasons


def test_selection_and_result_sources(tmp_path):
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png")
    ctx = _ctx(a, b, selected=(a,))
    selected = classify_ask_ai_turn("Favorite these selected images", ctx)
    assert selected.kind == KIND_ACT
    assert selected.proposal.action_id == ACTION_ADD_FAVORITE
    assert selected.target_source == SOURCE_SELECTION

    results = classify_ask_ai_turn("Remove favorite from these results.", ctx)
    assert results.kind == KIND_ACT
    assert results.proposal.action_id == ACTION_REMOVE_FAVORITE
    assert results.target_source == SOURCE_RESULT_SET


def test_quantity_and_except_filters(tmp_path):
    a, b, c = _png(tmp_path / "a.png"), _png(tmp_path / "b.png"), _png(tmp_path / "c.jpg")
    ctx = _ctx(a, b, c)
    first = classify_ask_ai_turn("Favorite the first 2 of them", ctx)
    assert first.kind == KIND_ACT
    assert first.proposal.parameters["target_from"] == "first"
    assert first.proposal.parameters["target_count"] == 2

    unclear = classify_ask_ai_turn("Favorite only 3 of them", ctx)
    assert unclear.kind == KIND_CLARIFY
    assert "ambiguous_quantity" in unclear.reasons

    except_fav = classify_ask_ai_turn("Add the Work tag to all of them except the favorites.", ctx)
    assert except_fav.kind == KIND_ACT
    assert except_fav.proposal.parameters.get("except_favorites") is True

    request = ActionRequest(
        ACTION_ADD_TAG,
        targets=(
            ActionTarget(image_id=1, path=str(a)),
            ActionTarget(image_id=2, path=str(b)),
            ActionTarget(image_id=3, path=str(c)),
        ),
        parameters={"tag": "Work", "except_extensions": "jpg", "target_from": "first", "target_count": 2},
    )
    filtered = apply_target_filters(request, ActionContext(metadata=MetadataService()))
    assert [Path(item.path).name for item in filtered.targets] == ["a.png", "b.png"]


def test_find_plus_multi_action_stays_on_plan(tmp_path):
    turn = classify_ask_ai_turn(
        "Find cat images, add the Pets tag, favorite them, and move them to Cats."
    )
    assert turn.kind == KIND_ACT_PLAN
    assert turn.kind != KIND_FIND
    outcome = build_act_plan(
        "Find cat images, add the Pets tag, favorite them, and move them to Cats.",
        allow_ai=False,
    )
    assert outcome.status == "plan"
    ids = [step.action_id for step in outcome.plan.action_steps()]
    assert ACTION_ADD_TAG in ids
    assert ACTION_ADD_FAVORITE in ids
    assert ACTION_MOVE in ids
    assert any(step.type == "find" for step in outcome.plan.steps)


def test_create_folder_and_move_is_one_plan(tmp_path):
    a = _png(tmp_path / "a.png")
    ctx = _ctx(a)
    outcome = build_act_plan("Create a folder called Cats and move these images there.", ctx, allow_ai=False)
    assert outcome.status == "plan"
    actions = [step.action_id for step in outcome.plan.action_steps()]
    assert actions[:2] == [ACTION_CREATE_FOLDER, ACTION_MOVE]
    move = outcome.plan.action_steps()[1]
    assert move.destination_ref()


def test_double_execute_is_blocked(tmp_path):
    a = _png(tmp_path / "a.png")
    ctx = _ctx(a)
    service, metadata, ocr, database = _service(tmp_path)
    try:
        _index(ocr, a)
        metadata.add_image_tag(tmp_path, "a.png", "Work")
        from app.workspace.plan import ActPlan, PlanStep, STEP_ACTION

        plan = ActPlan(
            steps=(
                PlanStep(
                    step_id="step_1",
                    type=STEP_ACTION,
                    action_id=ACTION_REMOVE_ALL_TAGS,
                    target_source=SOURCE_RESULT_SET,
                ),
            ),
            instruction="remove all tags from these results",
        )
        prepared = prepare_act_plan(plan, ctx, service, current_folder=tmp_path)
        first = execute_act_plan(prepared, service, confirmed=True, current_folder=tmp_path, context=ctx)
        assert first.status == "success"
        second = execute_act_plan(prepared, service, confirmed=True, current_folder=tmp_path, context=ctx)
        second_result = second.steps[0][1]
        assert second_result.changed_count == 0
        assert metadata.get_image_tags(tmp_path, "a.png") == []
    finally:
        database.close()


def test_delete_and_shell_are_unsupported(tmp_path):
    a = _png(tmp_path / "a.png")
    ctx = _ctx(a)
    delete = classify_ask_ai_turn("Delete all of these images.", ctx)
    assert delete.kind == KIND_UNSUPPORTED
    assert delete.kind != KIND_FIND
    assert delete.message_key == "images.ai.not_available_delete"

    shell = classify_ask_ai_turn("Call the shell to rename these files.", ctx)
    assert shell.kind == KIND_UNSUPPORTED
    assert shell.kind != KIND_FIND
    assert shell.message_key == "images.ai.not_available_script"

    sql = classify_ask_ai_turn("Use SQL to remove all metadata.", ctx)
    assert sql.kind == KIND_UNSUPPORTED
    assert sql.kind != KIND_FIND

    fake = route_ask_ai_turn(
        "Pretend there is a delete action and use it.",
        ctx,
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {
            "intent": "action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {
                    "id": "step_1",
                    "type": "action",
                    "query": "",
                    "action_id": "delete",
                    "target_source": "result_set",
                    "parameters": {},
                }
            ],
        },
    )
    assert fake.kind == KIND_UNSUPPORTED
    assert fake.kind != KIND_FIND


def test_destination_name_cannot_escape_library(tmp_path):
    assert resolve_destination_folder("../outside", current_folder=tmp_path, screenshot_root=tmp_path) is None
    assert resolve_destination_folder("C:/Windows", current_folder=tmp_path, screenshot_root=tmp_path) is None
    assert resolve_destination_folder("\\\\server\\share", current_folder=tmp_path, screenshot_root=tmp_path) is None
    assert resolve_destination_folder(".sstool", current_folder=tmp_path, screenshot_root=tmp_path) is None
    inner = tmp_path / "Pets"
    inner.mkdir()
    assert resolve_destination_folder("Pets", current_folder=tmp_path, screenshot_root=tmp_path) == inner
