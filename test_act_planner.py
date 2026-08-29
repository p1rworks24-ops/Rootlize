"""AI Act Planner: structured plans, validation, and Action execution."""
from __future__ import annotations

from pathlib import Path

from app.actions import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
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
    ORIGIN_MEANING,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
    bound_proposal,
    build_act_plan,
    classify_ask_ai_turn,
    execute_act_plan,
    parse_plan_payload,
    prepare_act_plan,
    summarize_action_result,
    summarize_combined_result,
    validate_act_plan,
)
from app.workspace.plan import STEP_ACTION, STEP_FIND, STEP_NARROW


def _png(path: Path) -> Path:
    path.write_bytes(b"png")
    return path


def _context(tmp_path: Path, names: tuple[str, ...] = ("a.png", "b.png", "c.png"), selected: tuple[str, ...] = ()):
    folder = tmp_path / "library"
    folder.mkdir(exist_ok=True)
    paths = []
    mapping = {}
    for index, name in enumerate(names, start=1):
        path = _png(folder / name)
        paths.append(path)
        mapping[str(path.resolve())] = index
    ctx = SearchResultContext().with_results(
        image_ids=tuple(mapping[str(path.resolve())] for path in paths),
        paths=[str(path) for path in paths],
        query="dog",
        scope_folder=folder,
        origin=ORIGIN_MEANING,
        path_to_image_id=mapping,
    )
    if selected:
        chosen = [path for path in paths if path.name in selected]
        ctx = ctx.with_selection(
            image_ids=tuple(mapping[str(path.resolve())] for path in chosen),
            paths=[str(path) for path in chosen],
        )
    return ctx, folder, paths, mapping


def _service(tmp_path: Path):
    metadata = MetadataService()
    database = OCRDatabase(tmp_path / "ocr.sqlite3").open()
    ocr = OCRRepository(database)
    return ActionService(ActionContext(metadata=metadata, ocr=ocr, app_root=tmp_path)), metadata, ocr, database


def _index(ocr: OCRRepository, path: Path) -> int:
    fingerprint = calculate_quick_fingerprint(path)
    record = ocr.upsert_image(
        path,
        size_bytes=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
        quick_fingerprint=fingerprint,
    )
    return int(record.image_id)


def test_simple_act_stays_on_local_parser(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    turn = classify_ask_ai_turn("この結果に work タグを付けて", ctx)
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    assert turn.proposal.action_id == ACTION_ADD_TAG
    assert turn.proposal.parameters["tag"] == "work"

    moved = classify_ask_ai_turn("これらを Dogs に移動して", ctx)
    assert moved.kind == KIND_ACT
    assert moved.proposal.action_id == ACTION_MOVE


def test_vague_organize_clarifies_without_plan():
    turn = classify_ask_ai_turn("いい感じに整理して")
    assert turn.kind == KIND_CLARIFY
    assert "vague_organize" in turn.reasons
    assert turn.message_key == "images.ai.clarify_organize"


def test_multi_action_builds_structured_plan_without_ai(tmp_path, monkeypatch):
    ctx, folder, _paths, _mapping = _context(tmp_path)
    called = []
    monkeypatch.setattr("app.workspace.planner.post_act_plan_json", lambda *_args, **_kwargs: called.append(1) or {})
    turn = classify_ask_ai_turn("この結果に work タグを付けて Project A に移動して", ctx)
    assert turn.kind == KIND_ACT_PLAN
    outcome = build_act_plan(turn.query, ctx, allow_ai=False)
    assert called == []
    assert outcome.status == "plan"
    assert outcome.used_ai is False
    steps = outcome.plan.steps
    assert [step.type for step in steps] == [STEP_ACTION, STEP_ACTION]
    assert steps[0].action_id == ACTION_ADD_TAG
    assert steps[0].parameters["tag"] == "work"
    assert steps[1].action_id == ACTION_MOVE
    assert steps[1].parameters["destination_name"] == "Project A"
    assert steps[0].target_source == SOURCE_RESULT_SET


def test_create_folder_then_move_uses_step_reference(tmp_path):
    ctx, folder, _paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=False)
    assert outcome.status == "plan"
    create, move = outcome.plan.steps
    assert create.action_id == ACTION_CREATE_FOLDER
    assert create.parameters["name"] == "Dogs"
    assert move.action_id == ACTION_MOVE
    assert move.parameters["destination_ref"] == create.step_id
    assert "destination_path" not in move.parameters


def test_narrow_then_action_plan(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("この中で犬の画像だけ favorite タグを付けて", ctx, allow_ai=False)
    assert outcome.status == "plan"
    narrow, tag = outcome.plan.steps
    assert narrow.type == STEP_NARROW
    assert "犬" in narrow.query
    assert tag.action_id == ACTION_ADD_TAG
    assert tag.parameters["tag"] == "favorite"


def test_find_then_action_plan_without_current_results():
    outcome = build_act_plan("犬の画像を探して Dogs に移動して", SearchResultContext(), allow_ai=False)
    assert outcome.status == "plan"
    find, move = outcome.plan.steps
    assert find.type == STEP_FIND
    assert "犬" in find.query
    assert move.action_id == ACTION_MOVE
    assert move.parameters["destination_name"] == "Dogs"


def test_rename_candidates_go_through_preview_and_confirm(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, names=("one.png", "two.png", "three.png"))
    turn = classify_ask_ai_turn("この3枚を内容が分かる名前に変えて", ctx)
    assert turn.kind == KIND_ACT_PLAN
    outcome = build_act_plan(
        turn.query,
        ctx,
        name_generator=lambda images: {
            int(item["image_id"]): f"scene-{item['image_id']}" for item in images
        },
        allow_ai=False,
    )
    assert outcome.status == "plan"
    assert outcome.plan.steps[0].action_id == ACTION_RENAME
    names = outcome.plan.steps[0].parameters["names"]
    assert names["id:1"] == "scene-1"

    service, _metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        assert prepared.preview.executable is True
        assert prepared.preview.rename_pairs
        assert any("scene-1" in after for _before, after in prepared.preview.rename_pairs)
        blocked = execute_act_plan(prepared, service, confirmed=False, current_folder=folder, context=ctx)
        assert blocked.status == "blocked"
        assert paths[0].exists()
        assert paths[0].name == "one.png"
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        assert result.status == "success"
        assert (folder / "scene-1.png").exists()
        assert not (folder / "one.png").exists()
    finally:
        database.close()


def test_unknown_action_is_rejected(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "step_1", "type": "action", "action_id": "delete", "parameters": {"tag": "x"}}
            ]
        }
    )
    validation = validate_act_plan(plan, ctx)
    assert validation.ok is False
    assert "unknown_action" in validation.reasons


def test_invalid_parameter_is_rejected(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "step_1", "type": "action", "action_id": "add_tag", "parameters": {}}
            ]
        }
    )
    validation = validate_act_plan(plan, ctx)
    assert validation.ok is False
    assert "missing_parameter" in validation.reasons


def test_broken_step_reference_is_rejected(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    plan = parse_plan_payload(
        {
            "steps": [
                {
                    "id": "step_1",
                    "type": "action",
                    "action_id": "move",
                    "parameters": {"destination_ref": "step_99"},
                }
            ]
        }
    )
    validation = validate_act_plan(plan, ctx)
    assert validation.ok is False
    assert "broken_step_reference" in validation.reasons


def test_forbidden_path_parameter_from_ai_is_rejected(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    plan = parse_plan_payload(
        {
            "steps": [
                {
                    "id": "step_1",
                    "type": "action",
                    "action_id": "move",
                    "parameters": {"destination_name": "Dogs", "destination_path": "C:/Windows"},
                }
            ]
        }
    )
    validation = validate_act_plan(plan, ctx)
    assert validation.ok is False
    assert "forbidden_parameter" in validation.reasons


def test_ai_payload_is_validated_before_prepare(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    outcome = build_act_plan(
        "tag these and move them",
        ctx,
        complete_json=lambda *_args, **_kwargs: {
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {
                    "id": "step_1",
                    "type": "shell",
                    "query": "",
                    "action_id": "",
                    "target_source": "result_set",
                    "parameters": {},
                }
            ],
        },
    )
    assert outcome.status == "rejected"
    assert "unknown_step_type" in outcome.reasons


def test_result_set_and_selection_resolution(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, selected=("b.png",))
    tagged = classify_ask_ai_turn("この結果に work タグを付けて", ctx)
    proposal = bound_proposal(tagged.proposal, ctx)
    assert proposal.image_ids == (1, 2, 3)
    selected = classify_ask_ai_turn("これらに work タグを付けて", ctx)
    assert selected.proposal.target_source == SOURCE_SELECTION
    bound = bound_proposal(selected.proposal, ctx)
    assert bound.image_ids == (mapping[str(paths[1].resolve())],)


def test_confirm_false_and_cancel_do_not_execute(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=False)
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        assert prepared.preview.executable is True
        blocked = execute_act_plan(prepared, service, confirmed=False, current_folder=folder, context=ctx)
        assert blocked.status == "blocked"
        assert not (folder / "Dogs").exists()
        assert paths[0].exists()
    finally:
        database.close()


def test_existing_folder_is_reused_for_create_then_move(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path)
    (folder / "Dogs").mkdir()
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=False)
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        assert prepared.preview.executable is True
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        create_result = result.steps[0][1]
        move_result = result.steps[1][1]
        assert create_result.changed_count == 0
        assert move_result.succeeded == len(paths)
        assert (folder / "Dogs" / paths[0].name).exists()
        assert not paths[0].exists()
    finally:
        database.close()


def test_create_folder_failure_after_preview_skips_move(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=False)
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        assert prepared.preview.executable is True
        (folder / "Dogs").write_bytes(b"not-a-folder")
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        create_result = result.steps[0][1]
        move_result = result.steps[1][1]
        assert create_result.status == "failed"
        assert move_result.status == "skipped"
        assert move_result.issues[0].code == "prerequisite_failed"
        assert paths[0].exists()
        assert not (folder / "Dogs" / paths[0].name).exists()
    finally:
        database.close()


def test_create_folder_then_move_executes_in_order(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=False)
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        assert result.status == "success"
        assert (folder / "Dogs").is_dir()
        for path in paths:
            assert (folder / "Dogs" / path.name).exists()
            assert not path.exists()
    finally:
        database.close()


def test_multi_action_executes_tag_then_move(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path)
    outcome = build_act_plan("この結果に work タグを付けて Project A に移動して", ctx, allow_ai=False)
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            image_id = _index(ocr, path)
            assert image_id == mapping[str(path.resolve())]
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        assert "work" in prepared.preview.detail
        assert "Project A" in prepared.preview.detail
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        assert result.succeeded >= 1
        dest = folder / "Project A"
        assert dest.is_dir()
        tags = metadata.get_image_tags(dest, paths[0].name)
        assert "work" in tags
    finally:
        database.close()


def test_planner_modules_do_not_call_filesystem_or_qt():
    root = Path(__file__).resolve().parent / "app" / "workspace"
    for name in ("planner.py", "intent.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "subprocess" not in text
        assert "shutil" not in text
        assert "PySide" not in text
        assert ".mkdir(" not in text
        assert ".unlink(" not in text


def test_ai_plan_without_execution_does_not_touch_files(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path)
    before = {path.name: path.stat().st_mtime_ns for path in paths}
    outcome = build_act_plan(
        "tag these with work and move them to Project A",
        ctx,
        complete_json=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("local plan should win")),
        allow_ai=True,
    )
    assert outcome.used_ai is False
    assert outcome.status == "plan"
    for path in paths:
        assert path.exists()
        assert path.stat().st_mtime_ns == before[path.name]
    assert not (folder / "Project A").exists()


def test_find_intent_is_unchanged():
    turn = classify_ask_ai_turn("犬の画像を探す")
    assert turn.kind == KIND_FIND
    assert turn.query == "犬の画像"


def test_python_sql_and_parent_path_are_rejected(tmp_path):
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    python_plan = parse_plan_payload(
        {"steps": [{"id": "step_1", "type": "python", "action_id": "", "parameters": {}}]}
    )
    assert "unknown_step_type" in validate_act_plan(python_plan, ctx).reasons
    sql_plan = parse_plan_payload(
        {"steps": [{"id": "step_1", "type": "sql", "action_id": "", "parameters": {}}]}
    )
    assert "unknown_step_type" in validate_act_plan(sql_plan, ctx).reasons
    parent = parse_plan_payload(
        {
            "steps": [
                {
                    "id": "step_1",
                    "type": "action",
                    "action_id": "create_folder",
                    "parameters": {"name": "Dogs", "parent_path": "C:/Windows"},
                }
            ]
        }
    )
    assert "forbidden_parameter" in validate_act_plan(parent, ctx).reasons


def test_rename_invalid_reserved_and_duplicate_are_not_executable(tmp_path):
    ctx, folder, paths, _mapping = _context(tmp_path, names=("one.png", "two.png", "taken.png"))
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        invalid = parse_plan_payload(
            {
                "steps": [
                    {
                        "id": "step_1",
                        "type": "action",
                        "action_id": "rename",
                        "parameters": {"names": {"id:1": "bad:name"}},
                    }
                ]
            }
        )
        reserved = parse_plan_payload(
            {
                "steps": [
                    {
                        "id": "step_1",
                        "type": "action",
                        "action_id": "rename",
                        "parameters": {"names": {"id:1": "CON"}},
                    }
                ]
            }
        )
        duplicate = parse_plan_payload(
            {
                "steps": [
                    {
                        "id": "step_1",
                        "type": "action",
                        "action_id": "rename",
                        "parameters": {"names": {"id:1": "taken.png"}},
                    }
                ]
            }
        )
        for plan, code in (
            (invalid, "invalid_filename"),
            (reserved, "reserved_name"),
            (duplicate, "name_conflict"),
        ):
            prepared = prepare_act_plan(plan, ctx, service, current_folder=folder)
            assert prepared.preview.executable is False
            assert code in prepared.preview.issues
            assert paths[0].name == "one.png"
    finally:
        database.close()


def test_tag_then_move_keeps_image_id_and_analysis(tmp_path):
    from PIL import Image

    from test_actions import _assert_analysis_unchanged, _seed_analysis

    ctx, folder, paths, mapping = _context(tmp_path, names=("keep.png",))
    Image.new("RGB", (24, 16), (12, 34, 56)).save(paths[0])
    outcome = build_act_plan("この結果に work タグを付けて Project A に移動して", ctx, allow_ai=False)
    service, metadata, ocr, database = _service(tmp_path)
    try:
        record, facts_before, index_before = _seed_analysis(ocr, database, paths[0], ocr_text="keep-ocr")
        assert record.image_id == mapping[str(paths[0].resolve())]
        prepared = prepare_act_plan(outcome.plan, ctx, service, current_folder=folder)
        blocked = execute_act_plan(prepared, service, confirmed=False, current_folder=folder, context=ctx)
        assert blocked.status == "blocked"
        assert paths[0].exists()
        result = execute_act_plan(prepared, service, confirmed=True, current_folder=folder, context=ctx)
        assert result.status == "success"
        dest = folder / "Project A" / "keep.png"
        assert dest.exists()
        _assert_analysis_unchanged(
            ocr,
            database,
            record.image_id,
            path=dest,
            ocr_text="keep-ocr",
            facts_before=facts_before,
            index_before=index_before,
        )
        assert "work" in metadata.get_image_tags(dest.parent, dest.name)
    finally:
        database.close()


def test_find_and_favorite_uses_search_targets_and_result_copy(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, names=("cat-one.png", "cat-two.png"))
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "find", "type": "find", "query": "cat images"},
                {"id": "fav", "type": "action", "action_id": "add_favorite"},
            ]
        }
    )
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            image_id = _index(ocr, path)
            assert image_id == mapping[str(path.resolve())]
        prepared = prepare_act_plan(plan, ctx, service, current_folder=folder)
        favorite_plan = next(item for item in prepared.action_plans if item is not None)
        assert favorite_plan.confirmation_required is True
        assert favorite_plan.item_count == 2
        assert favorite_plan.executable_count == 2
        assert prepared.preview.item_count == 2
        blocked = execute_act_plan(
            prepared, service, confirmed=False, current_folder=folder, context=ctx
        )
        assert blocked.status == "blocked"
        assert metadata.is_image_favorite(folder, "cat-one.png") is False

        empty_ctx_result = execute_act_plan(
            prepared,
            service,
            confirmed=True,
            current_folder=folder,
            context=SearchResultContext(),
        )
        favorite_result = next(
            item for step, item in empty_ctx_result.steps if step.action_id == ACTION_ADD_FAVORITE
        )
        assert favorite_result.changed_count == 2
        assert favorite_result.requested_count == 2
        assert metadata.is_image_favorite(folder, "cat-one.png") is True
        assert metadata.is_image_favorite(folder, "cat-two.png") is True
        assert MetadataService().is_image_favorite(folder, "cat-one.png") is True
        text = summarize_combined_result(empty_ctx_result)
        assert text == "Added Favorite to 2 images."
        assert "Finished" not in text

        again = execute_act_plan(
            prepared, service, confirmed=True, current_folder=folder, context=ctx
        )
        again_result = next(
            item for step, item in again.steps if step.action_id == ACTION_ADD_FAVORITE
        )
        assert again_result.changed_count == 0
        assert again_result.unchanged_count == 2
        assert "already favorited" in summarize_action_result(again_result)
        assert "Added Favorite" not in summarize_action_result(again_result)
    finally:
        database.close()


def test_find_and_tag_preview_targets_match_execute(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, names=("one.png", "two.png"))
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "find", "type": "find", "query": "cat images"},
                {"id": "tag", "type": "action", "action_id": "add_tag", "parameters": {"tag": "Test"}},
            ]
        }
    )
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(plan, ctx, service, current_folder=folder)
        tag_plan = next(item for item in prepared.action_plans if item is not None)
        assert tag_plan.item_count == 2
        assert prepared.preview.item_count == 2
        blocked = execute_act_plan(
            prepared, service, confirmed=False, current_folder=folder, context=ctx
        )
        assert blocked.status == "blocked"
        assert metadata.get_image_tags(folder, "one.png") == []

        result = execute_act_plan(
            prepared, service, confirmed=True, current_folder=folder, context=SearchResultContext()
        )
        tag_result = next(item for step, item in result.steps if step.action_id == ACTION_ADD_TAG)
        assert tag_result.requested_count == 2
        assert tag_result.changed_count == 2
        assert metadata.get_image_tags(folder, "one.png") == ["Test"]
        assert metadata.get_image_tags(folder, "two.png") == ["Test"]
        text = summarize_combined_result(result)
        assert 'Added "Test" to 2 images.' in text
        assert "Finished" not in text
    finally:
        database.close()


def test_find_and_move_preview_targets_match_execute(tmp_path):
    names = ("a.png", "b.png", "c.png", "d.png", "e.png")
    ctx, folder, paths, mapping = _context(tmp_path, names=names)
    dest = folder / "Work"
    dest.mkdir()
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "find", "type": "find", "query": "cat images"},
                {
                    "id": "move",
                    "type": "action",
                    "action_id": "move",
                    "parameters": {"destination_name": "Work"},
                },
            ]
        }
    )
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
        prepared = prepare_act_plan(plan, ctx, service, current_folder=folder)
        move_plan = next(item for item in prepared.action_plans if item is not None)
        assert move_plan.item_count == 5
        assert prepared.preview.item_count == 5
        blocked = execute_act_plan(
            prepared, service, confirmed=False, current_folder=folder, context=ctx
        )
        assert blocked.status == "blocked"
        assert paths[0].exists()
        result = execute_act_plan(
            prepared, service, confirmed=True, current_folder=folder, context=SearchResultContext()
        )
        move_result = next(item for step, item in result.steps if step.action_id == ACTION_MOVE)
        assert move_result.requested_count == 5
        assert move_result.changed_count == 5
        assert (dest / "a.png").exists()
        assert not paths[0].exists()
        assert summarize_combined_result(result) == "Moved 5 images."
        assert "Finished" not in summarize_combined_result(result)
    finally:
        database.close()


def test_find_and_remove_tag_preview_targets_match_execute(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, names=("one.png", "two.png"))
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "find", "type": "find", "query": "cat images"},
                {
                    "id": "untag",
                    "type": "action",
                    "action_id": "remove_tag",
                    "parameters": {"tag": "Test"},
                },
            ]
        }
    )
    service, metadata, ocr, database = _service(tmp_path)
    try:
        for path in paths:
            _index(ocr, path)
            metadata.add_image_tag(folder, path.name, "Test")
        prepared = prepare_act_plan(plan, ctx, service, current_folder=folder)
        tag_plan = next(item for item in prepared.action_plans if item is not None)
        assert tag_plan.item_count == 2
        blocked = execute_act_plan(
            prepared, service, confirmed=False, current_folder=folder, context=ctx
        )
        assert blocked.status == "blocked"
        assert metadata.get_image_tags(folder, "one.png") == ["Test"]
        result = execute_act_plan(
            prepared, service, confirmed=True, current_folder=folder, context=SearchResultContext()
        )
        tag_result = next(item for step, item in result.steps if step.action_id == ACTION_REMOVE_TAG)
        assert tag_result.requested_count == 2
        assert tag_result.changed_count == 2
        assert metadata.get_image_tags(folder, "one.png") == []
        assert 'Removed "Test" from 2 images.' in summarize_combined_result(result)
    finally:
        database.close()


def test_search_result_context_relocates_renamed_paths(tmp_path):
    ctx, folder, paths, mapping = _context(tmp_path, names=("old.png",))
    source = str(paths[0].resolve())
    dest = str((folder / "new.png").resolve())
    moved = ctx.with_relocated_paths({source: dest})
    assert moved.result_paths == (dest,)
    assert moved.path_to_image_id[dest] == mapping[source]


def test_empty_find_does_not_execute_move(tmp_path):
    folder = tmp_path / "library"
    folder.mkdir()
    outcome = build_act_plan("giraffeの画像を探して Dogs に移動して", SearchResultContext(), allow_ai=False)
    assert outcome.status == "plan"
    assert outcome.plan.steps[0].type == STEP_FIND
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        prepared = prepare_act_plan(outcome.plan, SearchResultContext(), service, current_folder=folder)
        assert prepared.preview.executable is False
        result = execute_act_plan(
            prepared, service, confirmed=True, current_folder=folder, context=SearchResultContext(),
        )
        assert result.succeeded == 0
        assert not (folder / "Dogs").exists()
    finally:
        database.close()


def test_post_act_plan_json_uses_act_plan_budget_hook(monkeypatch):
    import json

    seen = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            payload = {
                "status": "clarify",
                "clarify_message": "Which folder?",
                "steps": [],
            }
            return json.dumps(
                {
                    "id": "resp_test",
                    "output_text": json.dumps(payload),
                }
            ).encode()

    requests = []

    def fake_urlopen(request, *args, **kwargs):
        requests.append(request)
        return _Response()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CAPIXE_AI_DIRECT_PROVIDER", "1")
    monkeypatch.setattr("app.workspace.planner.check_ai_budget", lambda intent: seen.append(intent))
    monkeypatch.setattr("app.workspace.planner.urlopen", fake_urlopen)
    from app.workspace.planner import RESPONSES_ENDPOINT, post_act_plan_json

    parsed = post_act_plan_json("system", "user")
    assert parsed["status"] == "clarify"
    assert parsed["_response_id"] == "resp_test"
    assert requests
    assert str(getattr(requests[0], "full_url", requests[0])) == RESPONSES_ENDPOINT
    assert len(seen) == 1
    assert seen[0].operation == "act_plan"
    assert seen[0].kind == "text_llm"


def test_simple_act_does_not_call_planner_http(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.workspace.planner.post_act_plan_json",
        lambda *_args, **_kwargs: called.append(1) or {},
    )
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    turn = classify_ask_ai_turn("この結果に work タグを付けて", ctx)
    assert turn.kind == KIND_ACT
    assert called == []


def test_local_composite_plan_skips_llm(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.workspace.planner.post_act_plan_json",
        lambda *_args, **_kwargs: called.append(1) or {},
    )
    ctx, _folder, _paths, _mapping = _context(tmp_path)
    outcome = build_act_plan("Dogs フォルダを作って、この結果をそこへ移動して", ctx, allow_ai=True)
    assert outcome.used_ai is False
    assert outcome.status == "plan"
    assert called == []
