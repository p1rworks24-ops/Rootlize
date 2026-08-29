from pathlib import Path

import pytest

from app.ai_actions import (
    ActionExecutionRejected,
    ActionExecutor,
    ActionParameters,
    ActionPlan,
    ActionType,
)
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.services.metadata_service import MetadataService


def _plan(action=ActionType.TAG, ids=(1,), tag="work", **overrides):
    values = dict(
        instruction="tag images",
        action=action,
        search_query="image",
        matched_image_ids=tuple(ids),
        confidence=.9,
        match_state="single_candidate",
        action_parameters=ActionParameters(tag=tag),
        confirmation_required=True,
        clarification_required=False,
    )
    values.update(overrides)
    return ActionPlan(**values)


@pytest.fixture
def executor_setup(tmp_path):
    folder = tmp_path / "Selected"
    folder.mkdir()
    database = OCRDatabase(tmp_path / "ocr.sqlite3").open()
    repository = OCRRepository(database)
    metadata = MetadataService()
    records = []
    for name in ("one.png", "two.png"):
        path = folder / name
        path.write_bytes(b"png")
        records.append(repository.upsert_image(path, size_bytes=3, mtime_ns=1))
    yield ActionExecutor(repository, metadata), metadata, records, folder
    database.close()


def test_adds_tag_to_one_and_multiple_images(executor_setup):
    executor, metadata, records, folder = executor_setup
    ids = tuple(record.image_id for record in records)
    paths = {record.image_id: Path(record.path) for record in records}

    one = executor.execute_tag(
        _plan(ids=ids[:1]), confirmed=True,
        preview_paths={ids[0]: paths[ids[0]]},
    )
    assert one.succeeded_image_ids == ids[:1]
    many = executor.execute_tag(_plan(ids=ids), confirmed=True, preview_paths=paths)
    assert many.succeeded_image_ids == ids[1:]
    assert many.skipped_image_ids == ids[:1]
    assert metadata.get_image_tags(folder, "one.png") == ["work"]
    assert metadata.get_image_tags(folder, "two.png") == ["work"]


def test_missing_image_id_is_failed(executor_setup):
    executor, _metadata, records, _folder = executor_setup
    missing_id = 99999
    paths = {
        records[0].image_id: Path(records[0].path),
        missing_id: Path(records[0].path),
    }
    result = executor.execute_tag(
        _plan(ids=(records[0].image_id, missing_id)),
        confirmed=True,
        preview_paths=paths,
    )
    assert result.succeeded_image_ids == (records[0].image_id,)
    assert result.failed_image_ids == (missing_id,)


@pytest.mark.parametrize("plan,confirmed", [
    (_plan(tag=None), True),
    (_plan(clarification_required=True), True),
    (_plan(action=ActionType.SEARCH), True),
    (_plan(action=ActionType.MOVE), True),
    (_plan(action=ActionType.RENAME), True),
    (_plan(action=ActionType.DELETE), True),
    (_plan(ids=()), True),
    (_plan(), False),
    (_plan(confirmation_required=False), True),
])
def test_rejects_ineligible_or_unconfirmed_plans(executor_setup, plan, confirmed):
    executor, _metadata, records, _folder = executor_setup
    with pytest.raises(ActionExecutionRejected):
        executor.execute_tag(
            plan,
            confirmed=confirmed,
            preview_paths={records[0].image_id: Path(records[0].path)},
        )


def test_rejects_changed_preview_target(executor_setup):
    executor, _metadata, records, folder = executor_setup
    with pytest.raises(ActionExecutionRejected):
        executor.execute_tag(
            _plan(ids=(records[0].image_id,)),
            confirmed=True,
            preview_paths={},
        )
    result = executor.execute_tag(
        _plan(ids=(records[0].image_id,)),
        confirmed=True,
        preview_paths={records[0].image_id: folder / "two.png"},
    )
    assert result.failed_image_ids == (records[0].image_id,)
