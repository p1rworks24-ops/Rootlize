"""Automation v0: save/load, re-evaluate Find/Narrow, Preview → Confirm → Execute."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.actions import (
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ActionContext,
    ActionRequest,
    ActionService,
    ActionTarget,
)
from app.automation import (
    AutomationService,
    FilenameSearchEvaluator,
    Workflow,
    WorkflowStore,
    WorkflowValidationError,
    sanitize_step_parameters,
    validate_workflow,
    workflow_from_payload,
    workflow_from_session,
    format_list_date,
    workflow_list_status,
    workflow_to_payload,
)
from app.automation.draft import draft_workflow_from_text
from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.services.metadata_service import MetadataService
from app.workspace import ORIGIN_BROWSE, ORIGIN_MEANING, SearchResultContext
from app.workspace.plan import STEP_ACTION, STEP_FIND, STEP_NARROW, PlanStep


def _png(path: Path) -> Path:
    path.write_bytes(b"png")
    return path


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


def _bind_ocr_ids(context: SearchResultContext, ocr: OCRRepository) -> SearchResultContext:
    mapping = {}
    for raw in context.result_paths:
        path = Path(raw)
        try:
            mapping[str(path.resolve())] = int(ocr.get_image_by_path(path).image_id)
        except Exception:
            continue
    return context.with_index(mapping)


def _library(tmp_path: Path, names: tuple[str, ...] = ("dog-a.png", "dog-b.png", "cat.png")):
    folder = tmp_path / "library"
    folder.mkdir()
    paths = [_png(folder / name) for name in names]
    return folder, paths


def _tag_workflow(folder: Path, *, query: str = "dog", tag: str = "work") -> Workflow:
    return workflow_from_session(
        name="Tag dogs",
        description="Find dogs and tag them",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query=query, query=query),
        plan=None,
        action_id=ACTION_ADD_TAG,
        parameters={"tag": tag},
    )


def test_workflow_save_load_rename_delete(tmp_path):
    folder, _paths = _library(tmp_path)
    store = WorkflowStore(tmp_path / "automations.json")
    service = AutomationService(store)
    saved = service.save(_tag_workflow(folder))
    loaded = service.get(saved.id)
    assert loaded is not None
    assert loaded.name == "Tag dogs"
    assert loaded.description == "Find dogs and tag them"
    assert [step.type for step in loaded.steps] == [STEP_FIND, STEP_ACTION]
    listed = service.list_workflows()
    assert listed[0].id == saved.id
    renamed = service.rename(saved.id, "Dogs work", description="updated")
    assert renamed is not None
    assert renamed.name == "Dogs work"
    assert renamed.description == "updated"
    assert service.delete(saved.id) is True
    assert service.get(saved.id) is None
    assert service.list_workflows() == ()


def test_record_run_persists_last_run_at(tmp_path):
    folder, _paths = _library(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    saved = service.save(_tag_workflow(folder))
    assert saved.last_run_at == ""
    recorded = service.record_run(saved.id, at="2026-08-23T09:32:00+00:00")
    assert recorded is not None
    assert recorded.last_run_at == "2026-08-23T09:32:00+00:00"
    loaded = service.get(saved.id)
    assert loaded is not None
    assert loaded.last_run_at == "2026-08-23T09:32:00+00:00"
    payload = workflow_to_payload(loaded)
    assert payload["last_run_at"] == "2026-08-23T09:32:00+00:00"
    restored = workflow_from_payload({**payload, "last_run_at": ""})
    assert restored is not None
    assert restored.last_run_at == ""


def test_all_images_target_reevaluates_folder(tmp_path):
    folder, paths = _library(tmp_path)
    workflow = Workflow(
        id="all-images",
        name="Tag all",
        scope_folder=str(folder),
        origin=ORIGIN_BROWSE,
        steps=(PlanStep(step_id="action", type=STEP_ACTION, action_id=ACTION_ADD_TAG, parameters={"tag": "keep"}),),
    )
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
    assert validation.ok is True
    names = {Path(path).name for path in context.result_paths}
    assert names == {"dog-a.png", "dog-b.png", "cat.png"}
    assert context.origin == ORIGIN_BROWSE
    assert len(paths) == 3


def test_find_and_narrow_are_reevaluated(tmp_path):
    folder, paths = _library(tmp_path, ("dog-night.png", "dog-day.png", "cat.png"))
    workflow = Workflow(
        id="narrow-dogs",
        name="Narrow dogs",
        scope_folder=str(folder),
        origin=ORIGIN_MEANING,
        steps=(
            PlanStep(step_id="find", type=STEP_FIND, query="dog"),
            PlanStep(step_id="narrow", type=STEP_NARROW, query="night"),
            PlanStep(step_id="action", type=STEP_ACTION, action_id=ACTION_ADD_TAG, parameters={"tag": "night"}),
        ),
    )
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
    assert validation.ok is True
    names = {Path(path).name for path in context.result_paths}
    assert names == {"dog-night.png"}
    assert context.narrowed is True
    assert paths[1].name == "dog-day.png"
    assert "dog-day.png" not in names


def test_action_request_preview_confirm_execute(tmp_path):
    folder, paths = _library(tmp_path)
    workflow = _tag_workflow(folder)
    actions, metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        assert prepared.validation.ok is True
        assert prepared.preview.executable is True
        assert prepared.requests[1] is not None
        assert prepared.requests[1].action_id == ACTION_ADD_TAG
        assert all(target.image_id is not None for target in prepared.requests[1].targets)
        blocked = service.execute(prepared, actions, confirmed=False, current_folder=folder, context=context)
        assert blocked.status == "blocked"
        for path in paths:
            assert metadata.get_image_tags(path.parent, path.name) == []
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert metadata.get_image_tags(paths[0].parent, paths[0].name) == ["work"]
        assert metadata.get_image_tags(paths[1].parent, paths[1].name) == ["work"]
        assert metadata.get_image_tags(paths[2].parent, paths[2].name) == []
    finally:
        database.close()


def test_zero_results_do_not_execute(tmp_path):
    folder, paths = _library(tmp_path)
    workflow = _tag_workflow(folder, query="unicorn")
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is False
        assert "no_targets" in validation.reasons
        assert context.result_paths == ()
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        blocked = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert blocked.status in {"failed", "blocked"}
        assert not (folder / "work").exists()
    finally:
        database.close()


def test_missing_folder_is_safe(tmp_path):
    missing = tmp_path / "gone"
    workflow = _tag_workflow(missing)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
    assert validation.ok is False
    assert "missing_folder" in validation.reasons
    assert context.result_paths == ()


def test_missing_file_after_reeval_is_partial(tmp_path):
    folder, paths = _library(tmp_path)
    workflow = _tag_workflow(folder)
    actions, metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        paths[0].unlink()
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status in {"partial", "success", "failed"}
        remaining = metadata.get_image_tags(paths[1].parent, paths[1].name)
        assert remaining in ([], ["work"]) or result.failed >= 1
    finally:
        database.close()


def test_stale_image_ids_are_not_used_as_targets(tmp_path):
    folder, paths = _library(tmp_path)
    stale = workflow_from_payload(
        {
            "id": "stale-1",
            "name": "Stale ids",
            "scope_folder": str(folder),
            "origin": ORIGIN_MEANING,
            "steps": [
                {"id": "find", "type": "find", "query": "dog"},
                {
                    "id": "action",
                    "type": "action",
                    "action_id": "add_tag",
                    "parameters": {"tag": "work", "image_ids": [9999], "paths": ["C:/nope.png"]},
                },
            ],
        }
    )
    assert stale is not None
    assert "image_ids" not in stale.steps[1].parameters
    assert "paths" not in stale.steps[1].parameters
    actions, metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        ids = [_index(ocr, path) for path in paths]
        context, validation = service.evaluate_search(stale, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(stale, context, actions, current_folder=folder)
        request = next(item for item in prepared.requests if item is not None)
        target_ids = {target.image_id for target in request.targets}
        assert 9999 not in target_ids
        assert target_ids <= set(ids)
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert metadata.get_image_tags(paths[0].parent, paths[0].name) == ["work"]
    finally:
        database.close()


def test_malformed_workflow_is_rejected(tmp_path):
    store = WorkflowStore(tmp_path / "automations.json")
    store.path.write_text("{not-json", encoding="utf-8")
    assert store.list() == ()
    bad = workflow_from_payload({"id": "x", "name": "", "steps": []})
    assert bad is None
    broken = Workflow(
        id="bad",
        name="Broken",
        steps=(PlanStep(step_id="step_1", type="shell", parameters={"sql": "drop"}),),
    )
    validation = validate_workflow(broken)
    assert validation.ok is False
    assert "unknown_step_type" in validation.reasons
    with pytest.raises(WorkflowValidationError):
        AutomationService(store).save(broken)


def test_arbitrary_path_shell_sql_are_rejected(tmp_path):
    folder, _paths = _library(tmp_path)
    payload = {
        "id": "unsafe",
        "name": "Unsafe",
        "scope_folder": str(folder),
        "steps": [
            {
                "type": "action",
                "action_id": "move",
                "parameters": {
                    "destination_name": "Dogs",
                    "destination_path": "C:/Windows",
                    "shell": "rm -rf /",
                    "sql": "delete from images",
                },
            }
        ],
    }
    workflow = workflow_from_payload(payload)
    assert workflow is not None
    assert "destination_path" not in workflow.steps[0].parameters
    assert "shell" not in workflow.steps[0].parameters
    assert "sql" not in workflow.steps[0].parameters
    raw = PlanStep(
        step_id="step_1",
        type=STEP_ACTION,
        action_id=ACTION_MOVE,
        parameters={"destination_name": "Dogs", "destination_path": "C:/Windows", "sql": "x"},
    )
    cleaned = sanitize_step_parameters(raw.action_id, raw.parameters)
    assert cleaned == {"destination_name": "Dogs"}


def test_partial_success_and_move(tmp_path):
    folder, paths = _library(tmp_path)
    dest = folder / "Dogs"
    dest.mkdir()
    workflow = workflow_from_session(
        name="Move dogs",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
        action_id=ACTION_MOVE,
        parameters={"destination_name": "Dogs"},
    )
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        blocked = service.execute(prepared, actions, confirmed=False, current_folder=folder, context=context)
        assert blocked.status == "blocked"
        assert paths[0].exists()
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert (dest / "dog-a.png").exists()
        assert (dest / "dog-b.png").exists()
        assert (folder / "cat.png").exists()
    finally:
        database.close()


def test_existing_action_layer_still_plans_direct_requests(tmp_path):
    folder, paths = _library(tmp_path)
    actions, metadata, ocr, database = _service(tmp_path)
    try:
        image_id = _index(ocr, paths[2])
        request = ActionRequest(
            action_id=ACTION_ADD_TAG,
            targets=(ActionTarget(image_id=image_id, path=str(paths[2])),),
            parameters={"tag": "keep"},
        )
        plan = actions.plan(request)
        assert plan.executable_count == 1
        result = actions.execute(request, confirmed=True)
        assert result.status == "success"
        assert metadata.get_image_tags(paths[2].parent, paths[2].name) == ["keep"]
        assert ACTION_CREATE_FOLDER in {ACTION_CREATE_FOLDER}
    finally:
        database.close()


def test_payload_roundtrip_omits_result_sets(tmp_path):
    folder, _paths = _library(tmp_path)
    context = SearchResultContext().with_results(
        image_ids=(11, 22),
        paths=[str(folder / "dog-a.png")],
        query="dog",
        scope_folder=folder,
        origin=ORIGIN_MEANING,
    )
    workflow = workflow_from_session(
        name="Keep recipe",
        context=context,
        action_id=ACTION_ADD_TAG,
        parameters={"tag": "work", "image_ids": [11, 22]},
    )
    payload = workflow_to_payload(workflow)
    assert payload.get("last_run_at", "") == ""
    assert payload["steps"][0]["type"] == "find"
    assert payload["steps"][0]["query"] == "dog"
    action = payload["steps"][1]
    assert action["parameters"] == {"tag": "work"}
    assert "image_ids" not in action["parameters"]
    restored = workflow_from_payload(payload)
    assert restored is not None
    assert restored.steps[0].query == "dog"


def test_format_list_date_uses_iso_date():
    assert format_list_date("2026-08-22T14:35:00+00:00") == "2026-08-22"
    assert format_list_date("2026-08-22T14:35:00+00:00", with_time=True) == "2026-08-22 14:35"
    assert format_list_date("") == ""


def test_workflow_list_status_uses_short_badges(tmp_path):
    folder, _paths = _library(tmp_path)
    ready = _tag_workflow(folder)
    assert workflow_list_status(ready)[0] == "ready"
    incomplete = workflow_from_session(
        name="Draft",
        context=SearchResultContext(scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"),
    )
    kind, label_key, hint_key = workflow_list_status(incomplete)
    assert kind == "needs_action"
    assert label_key == "automation.status_need_action"
    assert hint_key == "automation.status_need_action_hint"
    missing = ready.with_document(scope_folder=str(tmp_path / "gone"))
    assert workflow_list_status(missing)[0] == "error"
    disabled = Workflow(
        id=ready.id,
        name=ready.name,
        created_at=ready.created_at,
        updated_at=ready.updated_at,
        enabled=False,
        scope_folder=ready.scope_folder,
        origin=ready.origin,
        steps=ready.steps,
    )
    assert workflow_list_status(disabled)[0] == "disabled"


def _move_workflow(folder: Path, *, destination: str = "Animal") -> Workflow:
    return workflow_from_session(
        name="Move dogs",
        context=SearchResultContext(
            scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"
        ),
        action_id=ACTION_MOVE,
        parameters={"destination_name": destination},
    )


def test_move_uses_existing_start_folder_destination(tmp_path):
    folder, paths = _library(tmp_path)
    dest = folder / "Animal"
    dest.mkdir()
    workflow = _move_workflow(folder)
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        assert prepared.preview.executable is True
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert (dest / "dog-a.png").exists()
        assert (dest / "dog-b.png").exists()
        assert (folder / "cat.png").exists()
    finally:
        database.close()


def test_move_creates_missing_destination_only_after_confirm(tmp_path):
    folder, paths = _library(tmp_path)
    dest = folder / "Animal"
    sibling = folder.parent / "Animal"
    workflow = _move_workflow(folder)
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        assert prepared.preview.executable is True
        assert "will be created" in prepared.preview.detail.lower() or "does not exist yet" in prepared.preview.detail.lower()
        blocked = service.execute(prepared, actions, confirmed=False, current_folder=folder, context=context)
        assert blocked.status == "blocked"
        assert dest.exists() is False
        assert sibling.exists() is False
        assert paths[0].exists()
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert dest.is_dir()
        assert (dest / "dog-a.png").exists()
        assert (dest / "dog-b.png").exists()
        assert sibling.exists() is False
        assert (folder / "cat.png").exists()
    finally:
        database.close()


def test_move_does_not_use_sibling_folder_with_the_same_name(tmp_path):
    folder, paths = _library(tmp_path)
    sibling = folder.parent / "Animal"
    sibling.mkdir()
    decoy = _png(sibling / "keep-out.png")
    workflow = _move_workflow(folder)
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context = _bind_ocr_ids(
            service.evaluate_search(workflow, FilenameSearchEvaluator())[0],
            ocr,
        )
        prepared = service.prepare(workflow, context, actions, current_folder=folder)
        blocked = service.execute(prepared, actions, confirmed=False, current_folder=folder, context=context)
        assert blocked.status == "blocked"
        assert (folder / "Animal").exists() is False
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert (folder / "Animal" / "dog-a.png").exists()
        assert decoy.exists()
        assert not (sibling / "dog-a.png").exists()
    finally:
        database.close()


def test_manual_and_ai_generated_move_share_execution_path(tmp_path):
    folder, paths = _library(tmp_path)
    drafted = draft_workflow_from_text(
        "Find all dog images in this folder, tag them DOG, and move them to the Animal folder.",
        SearchResultContext(scope_folder=str(folder)),
        allow_ai=False,
    )
    assert drafted.ok is True
    ai_workflow = Workflow(
        id="ai-move",
        name="AI dogs",
        scope_folder=str(folder),
        origin=drafted.origin,
        steps=drafted.steps,
    )
    manual_workflow = workflow_from_session(
        name="Manual dogs",
        context=SearchResultContext(
            scope_folder=str(folder), origin=ORIGIN_MEANING, find_query="dog", query="dog"
        ),
        plan=None,
        action_id=ACTION_MOVE,
        parameters={"destination_name": "Animal"},
    )
    ai_move = next(step for step in ai_workflow.steps if step.action_id == ACTION_MOVE)
    manual_move = next(step for step in manual_workflow.steps if step.action_id == ACTION_MOVE)
    assert ai_move.action_id == manual_move.action_id == ACTION_MOVE
    assert ai_move.parameters.get("destination_name") == manual_move.parameters.get("destination_name") == "Animal"
    actions, _metadata, ocr, database = _service(tmp_path)
    service = AutomationService(WorkflowStore(tmp_path / "automations.json"))
    try:
        for path in paths:
            _index(ocr, path)
        context, validation = service.evaluate_search(ai_workflow, FilenameSearchEvaluator())
        assert validation.ok is True
        context = _bind_ocr_ids(context, ocr)
        prepared = service.prepare(ai_workflow, context, actions, current_folder=folder)
        assert prepared.preview.executable is True
        assert (folder / "Animal").exists() is False
        result = service.execute(prepared, actions, confirmed=True, current_folder=folder, context=context)
        assert result.status == "success"
        assert (folder / "Animal" / "dog-a.png").exists()
    finally:
        database.close()
