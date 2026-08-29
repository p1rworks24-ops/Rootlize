"""Tests for the shared Capixe Action foundation."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.actions import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_IDS,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
    ACTION_RENAME,
    ActionContext,
    ActionNotFoundError,
    ActionRequest,
    ActionService,
    ActionTarget,
    default_registry,
)
from app.image_facts.models import ImageFactsState, default_facts_identity
from app.image_facts.repository import ImageFactsRepository
from app.ocr.database import OCRDatabase
from app.ocr.diff_service import OCRDiffService
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.semantic.embedding import encode_embedding
from app.semantic.models import SourceSnapshot
from app.semantic_index.models import SemanticIndexState, default_index_identity
from app.semantic_index.repository import SemanticIndexRepository
from app.semantic_index.schema import index_record
from app.services.metadata_service import MetadataService


def _png(path: Path, data: bytes = b"png") -> Path:
    path.write_bytes(data)
    return path


def _real_png(path: Path, color: tuple[int, int, int] = (40, 80, 120)) -> Path:
    from PIL import Image

    Image.new("RGB", (24, 16), color).save(path)
    return path


def _unit_embedding() -> bytes:
    values = [0.0] * 511 + [1.0]
    return encode_embedding(values, dimension=512)


def _sample_facts():
    return {
        "media_type": "screenshot",
        "scene_description": "keep-facts",
        "environment": "indoor",
        "ui_types": [],
        "entities": [],
        "applications": [],
        "activities": [],
        "relationships": [],
        "notable_text": ["keep-ocr"],
    }


def _index(ocr: OCRRepository, path: Path, *, ocr_text: str | None = None):
    fingerprint = calculate_quick_fingerprint(path)
    record = ocr.upsert_image(
        path,
        size_bytes=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
        quick_fingerprint=fingerprint,
    )
    if ocr_text is not None:
        ocr.save_ocr_document(record.image_id, status="ready", ocr_text=ocr_text)
    return record


def _seed_analysis(ocr: OCRRepository, database: OCRDatabase, path: Path, *, ocr_text: str):
    record = _index(ocr, path, ocr_text=ocr_text)
    snapshot = SourceSnapshot(record.size_bytes, record.mtime_ns, record.quick_fingerprint)
    facts = ImageFactsRepository(database)
    facts.upsert_facts(record.image_id, _sample_facts(), default_facts_identity(), snapshot)
    indexes = SemanticIndexRepository(database)
    indexes.upsert_index(
        record.image_id,
        index_record(
            visual_summary="keep-index",
            objects_entities=["kept"],
            scene_environment="indoor",
            media_type="screenshot",
            searchable_concepts=["kept"],
            identities=[],
        ),
        _unit_embedding(),
        default_index_identity(),
        snapshot,
    )
    return record, facts.get_facts(record.image_id), indexes.get_index(record.image_id)


def _service(tmp_path: Path, *, with_ocr: bool = True):
    metadata = MetadataService()
    database = None
    ocr = None
    if with_ocr:
        database = OCRDatabase(tmp_path / "ocr.sqlite3").open()
        ocr = OCRRepository(database)
    context = ActionContext(metadata=metadata, ocr=ocr, app_root=tmp_path)
    service = ActionService(context)
    return service, metadata, ocr, database


def _close(database) -> None:
    if database is not None:
        database.close()


def test_registry_has_stable_action_ids():
    registry = default_registry()
    assert tuple(sorted(registry.action_ids())) == tuple(sorted(ACTION_IDS))
    for action_id in ACTION_IDS:
        assert registry.get(action_id).action_id == action_id
    with pytest.raises(ActionNotFoundError):
        registry.get("not_an_action")


def test_actions_package_does_not_import_qt():
    root = Path(__file__).resolve().parent / "app" / "actions"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "PySide" not in text
        assert "PyQt" not in text


def test_create_folder_validates_and_creates(tmp_path: Path):
    service, _metadata, _ocr, database = _service(tmp_path, with_ocr=False)
    try:
        parent = tmp_path / "library"
        parent.mkdir()
        request = ActionRequest(
            ACTION_CREATE_FOLDER,
            parameters={"parent_path": str(parent), "name": "Dogs"},
        )
        plan = service.plan(request)
        assert plan.executable_count == 1
        assert plan.confirmation_required is True
        blocked = service.execute(request, confirmed=False)
        assert blocked.status == "blocked"
        assert not (parent / "Dogs").exists()

        result = service.execute(request, confirmed=True)
        assert result.status == "success"
        assert result.changed_count == 1
        assert (parent / "Dogs").is_dir()
        assert result.items[0].after["path"] == str(parent / "Dogs")
        from app.workspace.plan import summarize_action_result
        assert summarize_action_result(result, parameters={"name": "Dogs"}) == 'Created folder "Dogs".'

        exists = service.execute(request, confirmed=True)
        assert exists.status == "success"
        assert exists.changed_count == 0
        assert exists.unchanged_count == 1
        assert exists.items[0].warning == "folder_exists" or exists.items[0].status == "skipped"
        from app.workspace.plan import summarize_action_result
        assert 'Folder "Dogs" already exists.' in summarize_action_result(
            exists, parameters={"name": "Dogs"}
        )
        assert "Created folder" not in summarize_action_result(exists, parameters={"name": "Dogs"})

        reserved = service.plan(
            ActionRequest(
                ACTION_CREATE_FOLDER,
                parameters={"parent_path": str(parent), "name": "NUL"},
            )
        )
        assert reserved.executable_count == 0
        assert reserved.items[0].issues[0].code == "invalid_folder_name"
    finally:
        _close(database)


def test_move_batch_item_statuses_and_preserves_ocr(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        source = tmp_path / "A"
        dest = tmp_path / "B"
        source.mkdir()
        dest.mkdir()
        one = _png(source / "one.png", b"one")
        two = _png(source / "two.png", b"two")
        missing = source / "gone.png"
        same = _png(dest / "stay.png", b"stay")
        rec_one = _index(ocr, one, ocr_text="keep-one")
        rec_two = _index(ocr, two, ocr_text="keep-two")
        rec_same = _index(ocr, same, ocr_text="keep-stay")
        metadata.add_image_tag(source, "one.png", "work")

        result = service.execute(
            ActionRequest(
                ACTION_MOVE,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                    ActionTarget(path=str(missing)),
                    ActionTarget(image_id=rec_same.image_id, path=str(same)),
                ),
                parameters={"destination_path": str(dest)},
            ),
            confirmed=True,
        )
        assert result.succeeded == 2
        assert result.skipped == 1
        assert result.failed == 1
        assert result.status == "partial"
        from app.workspace.plan import summarize_action_result
        move_text = summarize_action_result(result)
        assert "Moved 2 of 4" in move_text
        assert "could not be moved" in move_text
        moved = dest / "one.png"
        assert moved.exists()
        assert not one.exists()
        assert metadata.get_image_tags(dest, "one.png") == ["work"]
        indexed = ocr.get_image(rec_one.image_id)
        assert Path(indexed.path).resolve() == moved.resolve()
        assert ocr.get_ocr_document(rec_one.image_id).ocr_text == "keep-one"
        assert ocr.get_ocr_document(rec_one.image_id).status == "ready"
        assert ocr.get_image(rec_same.image_id).image_id == rec_same.image_id

        same_only = service.execute(
            ActionRequest(
                ACTION_MOVE,
                targets=(ActionTarget(image_id=rec_same.image_id, path=str(same)),),
                parameters={"destination_path": str(dest)},
            ),
            confirmed=True,
        )
        assert same_only.changed_count == 0
        assert same_only.unchanged_count == 1
        same_text = summarize_action_result(same_only)
        assert "needed to be moved" in same_text
        assert "Moved" not in same_text
    finally:
        _close(database)


def test_rename_validation_and_preserves_ocr(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        src = _png(folder / "old.png")
        _png(folder / "taken.png")
        record = _index(ocr, src, ocr_text="preserved")
        metadata.add_image_tag(folder, "old.png", "keep")

        invalid = service.plan(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"new_name": "bad:name"},
            )
        )
        assert invalid.items[0].status == "blocked"
        assert invalid.items[0].issues[0].code == "invalid_filename"

        reserved = service.plan(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"new_name": "CON"},
            )
        )
        assert reserved.items[0].issues[0].code == "reserved_name"

        duplicate = service.plan(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"new_name": "taken.png"},
            )
        )
        assert duplicate.items[0].issues[0].code == "name_conflict"

        unchanged = service.plan(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"new_name": "old.png"},
            )
        )
        assert unchanged.items[0].status == "skipped"

        result = service.execute(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"new_name": "new"},
            ),
            confirmed=True,
        )
        assert result.status == "success"
        dest = folder / "new.png"
        assert dest.exists()
        assert not src.exists()
        from app.workspace.plan import summarize_action_result
        assert summarize_action_result(result) == "Renamed 1 images."
        unchanged_run = service.execute(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=record.image_id, path=str(dest)),),
                parameters={"new_name": "new.png"},
            ),
            confirmed=True,
        )
        assert unchanged_run.changed_count == 0
        assert unchanged_run.unchanged_count == 1
        same_name_text = summarize_action_result(unchanged_run)
        assert "already has that name" in same_name_text
        assert "Renamed 1" not in same_name_text
        assert dest.exists()
        assert not src.exists()
        assert result.items[0].before["name"] == "old.png"
        assert result.items[0].after["name"] == "new.png"
        assert metadata.get_image_tags(folder, "new.png") == ["keep"]
        indexed = ocr.get_image(record.image_id)
        assert Path(indexed.path).resolve() == dest.resolve()
        assert ocr.get_ocr_document(record.image_id).ocr_text == "preserved"
        assert ocr.get_ocr_document(record.image_id).status == "ready"
    finally:
        _close(database)


def test_add_and_remove_tag_batch(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        one = _png(folder / "one.png")
        two = _png(folder / "two.png")
        rec_one = _index(ocr, one)
        rec_two = _index(ocr, two)
        metadata.add_image_tag(folder, "one.png", "work")

        added = service.execute(
            ActionRequest(
                ACTION_ADD_TAG,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                ),
                parameters={"tag": "work"},
            ),
            confirmed=True,
        )
        assert added.succeeded == 1
        assert added.skipped == 1
        assert added.status == "success"
        from app.workspace.plan import summarize_action_result
        assert 'Added "work" to 1 images.' in summarize_action_result(
            added, parameters={"tag": "work"}
        )
        noop = service.execute(
            ActionRequest(
                ACTION_ADD_TAG,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                ),
                parameters={"tag": "work"},
            ),
            confirmed=True,
        )
        assert noop.changed_count == 0
        assert noop.unchanged_count == 2
        assert 'already have the "work" tag' in summarize_action_result(
            noop, parameters={"tag": "work"}
        )
        assert 'Added "work"' not in summarize_action_result(noop, parameters={"tag": "work"})
        assert metadata.get_image_tags(folder, "one.png") == ["work"]
        assert metadata.get_image_tags(folder, "two.png") == ["work"]
        assert "work" in (ocr.get_search_document(rec_two.image_id).tags_norm or "")

        removed = service.execute(
            ActionRequest(
                ACTION_REMOVE_TAG,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                ),
                parameters={"tag": "work"},
            ),
            confirmed=True,
        )
        assert removed.succeeded == 2
        assert metadata.get_image_tags(folder, "one.png") == []
        assert result_tags_empty(ocr, rec_one.image_id)
        assert removed.items[0].before["tags"] == ["work"]
        assert removed.items[0].after["tags"] == []
        assert 'Removed "work" from 2 images.' in summarize_action_result(
            removed, parameters={"tag": "work"}
        )
        missing_tag = service.execute(
            ActionRequest(
                ACTION_REMOVE_TAG,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                ),
                parameters={"tag": "work"},
            ),
            confirmed=True,
        )
        assert missing_tag.changed_count == 0
        assert missing_tag.unchanged_count == 2
        assert 'had the "work" tag' in summarize_action_result(
            missing_tag, parameters={"tag": "work"}
        )
    finally:
        _close(database)


def test_add_and_remove_favorite_require_confirmation(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        src = _png(folder / "shot.png")
        record = _index(ocr, src)
        request = ActionRequest(
            ACTION_ADD_FAVORITE,
            targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
        )
        plan = service.plan(request)
        assert plan.confirmation_required is True
        blocked = service.execute(request, confirmed=False)
        assert blocked.status == "blocked"
        assert metadata.is_image_favorite(folder, "shot.png") is False
        added = service.execute(request, confirmed=True)
        assert added.status == "success"
        assert added.changed_count == 1
        assert added.unchanged_count == 0
        assert added.failed_count == 0
        assert added.requested_count == 1
        assert added.resolved_count == 1
        assert metadata.is_image_favorite(folder, "shot.png") is True
        reloaded = MetadataService()
        assert reloaded.is_image_favorite(folder, "shot.png") is True
        removed = service.execute(
            ActionRequest(
                ACTION_REMOVE_FAVORITE,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
            ),
            confirmed=True,
        )
        assert removed.status == "success"
        assert removed.changed_count == 1
        assert metadata.is_image_favorite(folder, "shot.png") is False
    finally:
        _close(database)


def test_add_favorite_noop_and_missing_and_partial(tmp_path: Path):
    from app.workspace.plan import summarize_action_result

    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        src = _png(folder / "shot.png")
        other = _png(folder / "two.png")
        record = _index(ocr, src)
        _index(ocr, other)
        first = service.execute(
            ActionRequest(
                ACTION_ADD_FAVORITE,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
            ),
            confirmed=True,
        )
        assert first.changed_count == 1
        noop = service.execute(
            ActionRequest(
                ACTION_ADD_FAVORITE,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
            ),
            confirmed=True,
        )
        assert noop.changed_count == 0
        assert noop.unchanged_count == 1
        assert noop.failed_count == 0
        assert "already favorited" in summarize_action_result(noop)
        assert "Added Favorite" not in summarize_action_result(noop)

        missing = service.execute(
            ActionRequest(
                ACTION_ADD_FAVORITE,
                targets=(ActionTarget(path=str(folder / "gone.png")),),
            ),
            confirmed=True,
        )
        assert missing.changed_count == 0
        assert missing.failed_count >= 1
        assert "couldn't find any images" in summarize_action_result(missing)

        empty = service.execute(
            ActionRequest(ACTION_ADD_FAVORITE, targets=()),
            confirmed=True,
        )
        assert empty.changed_count == 0
        assert empty.requested_count == 0
        assert empty.status == "failed"
        assert "couldn't find any images" in summarize_action_result(empty)

        partial = service.execute(
            ActionRequest(
                ACTION_ADD_FAVORITE,
                targets=(
                    ActionTarget(path=str(other)),
                    ActionTarget(path=str(folder / "missing.png")),
                ),
            ),
            confirmed=True,
        )
        assert partial.status == "partial"
        assert partial.changed_count == 1
        assert partial.failed_count == 1
        text = summarize_action_result(partial)
        assert "Added Favorite to 1 of 2" in text
        assert "could not be updated" in text
        assert metadata.is_image_favorite(folder, "two.png") is True
    finally:
        _close(database)


def result_tags_empty(ocr: OCRRepository, image_id: int) -> bool:
    return ocr.get_search_document(image_id).tags_norm.strip() == ""


def test_plan_exposes_preview_fields(tmp_path: Path):
    service, _metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        dest = tmp_path / "out"
        folder.mkdir()
        dest.mkdir()
        src = _png(folder / "shot.png")
        record = _index(ocr, src)
        plan = service.plan(
            ActionRequest(
                ACTION_MOVE,
                targets=(ActionTarget(image_id=record.image_id, path=str(src)),),
                parameters={"destination_path": str(dest)},
            )
        )
        assert plan.item_count == 1
        item = plan.items[0]
        assert item.before["path"]
        assert item.after["path"]
        assert item.before["name"] == "shot.png"
        assert item.after["name"] == "shot.png"
        assert plan.summary["destination_path"] == str(dest)
    finally:
        _close(database)


def _assert_analysis_unchanged(ocr, database, image_id: int, *, path: Path, ocr_text: str, facts_before, index_before):
    indexed = ocr.get_image(image_id)
    assert indexed.image_id == image_id
    assert Path(indexed.path).resolve() == path.resolve()
    document = ocr.get_ocr_document(image_id)
    assert document.ocr_text == ocr_text
    assert document.status == "ready"
    facts = ImageFactsRepository(database).get_facts(image_id)
    stored_index = SemanticIndexRepository(database).get_index(image_id)
    assert facts is not None and facts_before is not None
    assert stored_index is not None and index_before is not None
    assert facts.facts == facts_before.facts
    assert stored_index.metadata == index_before.metadata
    assert stored_index.text_embedding == index_before.text_embedding
    identity = default_facts_identity()
    index_identity = default_index_identity()
    assert ImageFactsRepository(database).classify([image_id], identity)[image_id] == ImageFactsState.FRESH
    assert SemanticIndexRepository(database).classify([image_id], index_identity)[image_id] == SemanticIndexState.FRESH
    diff = OCRDiffService(ocr).reconcile(path.parent, dry_run=True)
    moved_item = next(item for item in diff.items if item.image_id == image_id)
    assert moved_item.requires_ocr is False
    assert moved_item.classification in {"unchanged", "moved"}


def test_move_and_rename_keep_image_id_and_do_not_reanalyze(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        source = tmp_path / "A"
        dest = tmp_path / "B"
        source.mkdir()
        dest.mkdir()
        src = _real_png(source / "keep.png", (12, 34, 56))
        record, facts_before, index_before = _seed_analysis(ocr, database, src, ocr_text="keep-ocr")
        metadata.add_image_tag(source, "keep.png", "work")
        image_id = record.image_id

        moved = service.execute(
            ActionRequest(
                ACTION_MOVE,
                targets=(ActionTarget(image_id=image_id, path=str(src)),),
                parameters={"destination_path": str(dest)},
            ),
            confirmed=True,
        )
        assert moved.status == "success"
        dest_path = dest / "keep.png"
        assert dest_path.exists()
        assert not src.exists()
        assert moved.items[0].after["image_id"] == image_id
        _assert_analysis_unchanged(
            ocr,
            database,
            image_id,
            path=dest_path,
            ocr_text="keep-ocr",
            facts_before=facts_before,
            index_before=index_before,
        )
        assert metadata.get_image_tags(dest, "keep.png") == ["work"]

        renamed = service.execute(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=image_id, path=str(dest_path)),),
                parameters={"new_name": "kept.png"},
            ),
            confirmed=True,
        )
        assert renamed.status == "success"
        renamed_path = dest / "kept.png"
        assert renamed_path.exists()
        assert renamed.items[0].after["image_id"] == image_id
        _assert_analysis_unchanged(
            ocr,
            database,
            image_id,
            path=renamed_path,
            ocr_text="keep-ocr",
            facts_before=facts_before,
            index_before=index_before,
        )
        assert metadata.get_image_tags(dest, "kept.png") == ["work"]
    finally:
        _close(database)


def test_move_execute_keeps_item_results_when_one_file_fails(tmp_path: Path, monkeypatch):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        source = tmp_path / "A"
        dest = tmp_path / "B"
        source.mkdir()
        dest.mkdir()
        names = ("one.png", "two.png", "three.png", "four.png")
        records = []
        for name in names:
            path = _real_png(source / name)
            records.append(_index(ocr, path, ocr_text=f"text-{name}"))
            metadata.register_image(source, name)

        original = metadata.move_image_to_project

        def flaky(source_path, dest_dir):
            if Path(source_path).name == "three.png":
                raise OSError(13, "Permission denied", str(source_path))
            return original(source_path, dest_dir)

        monkeypatch.setattr(metadata, "move_image_to_project", flaky)
        result = service.execute(
            ActionRequest(
                ACTION_MOVE,
                targets=tuple(
                    ActionTarget(image_id=record.image_id, path=str(source / name))
                    for record, name in zip(records, names)
                ),
                parameters={"destination_path": str(dest)},
            ),
            confirmed=True,
        )
        assert [item.status for item in result.items] == ["success", "success", "failed", "success"]
        assert result.status == "partial"
        assert result.succeeded == 3
        assert result.failed == 1
        assert (dest / "one.png").exists()
        assert (dest / "two.png").exists()
        assert not (dest / "three.png").exists()
        assert (dest / "four.png").exists()
        assert (source / "three.png").exists()
        assert not (source / "one.png").exists()
        assert ocr.get_image(records[0].image_id).image_id == records[0].image_id
        assert Path(ocr.get_image(records[0].image_id).path).resolve() == (dest / "one.png").resolve()
        assert Path(ocr.get_image(records[2].image_id).path).resolve() == (source / "three.png").resolve()
        assert ocr.get_ocr_document(records[2].image_id).ocr_text == "text-three.png"
        assert ocr.get_ocr_document(records[3].image_id).ocr_text == "text-four.png"
        source_meta = metadata.load_metadata(source, force_reload=True).get("images", {})
        dest_meta = metadata.load_metadata(dest, force_reload=True).get("images", {})
        assert "three.png" in source_meta
        assert "three.png" not in dest_meta
        assert "one.png" not in source_meta
        assert "one.png" in dest_meta
    finally:
        _close(database)


def _exclusive_lock_windows(path: Path):
    import ctypes

    handle = ctypes.windll.kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
    if handle == -1 or handle == 0xFFFFFFFF:
        raise OSError("Could not lock file exclusively")
    return handle


def test_move_partial_failure_with_windows_file_lock(tmp_path: Path):
    import ctypes
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows exclusive lock is the safe partial-failure method")

    service, metadata, ocr, database = _service(tmp_path)
    lock = None
    try:
        source = tmp_path / "A"
        dest = tmp_path / "B"
        source.mkdir()
        dest.mkdir()
        names = ("one.png", "two.png", "three.png", "four.png")
        records = []
        for name in names:
            path = _real_png(source / name)
            records.append(_index(ocr, path, ocr_text=f"text-{name}"))
            metadata.register_image(source, name)

        lock = _exclusive_lock_windows(source / "three.png")
        result = service.execute(
            ActionRequest(
                ACTION_MOVE,
                targets=tuple(
                    ActionTarget(image_id=record.image_id, path=str(source / name))
                    for record, name in zip(records, names)
                ),
                parameters={"destination_path": str(dest)},
            ),
            confirmed=True,
        )
        assert [item.status for item in result.items] == ["success", "success", "failed", "success"]
        assert result.status == "partial"
        assert (dest / "one.png").exists()
        assert (source / "three.png").exists()
        assert not (dest / "three.png").exists()
        assert (dest / "four.png").exists()
        assert Path(ocr.get_image(records[0].image_id).path).resolve() == (dest / "one.png").resolve()
        assert Path(ocr.get_image(records[2].image_id).path).resolve() == (source / "three.png").resolve()
        source_meta = metadata.load_metadata(source, force_reload=True).get("images", {})
        dest_meta = metadata.load_metadata(dest, force_reload=True).get("images", {})
        assert "three.png" in source_meta
        assert "one.png" in dest_meta
        assert "four.png" in dest_meta
    finally:
        if lock:
            ctypes.windll.kernel32.CloseHandle(lock)
        _close(database)


def test_remove_all_and_replace_tags(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        one = _png(folder / "one.png")
        two = _png(folder / "two.png")
        empty = _png(folder / "empty.png")
        rec_one = _index(ocr, one)
        rec_two = _index(ocr, two)
        rec_empty = _index(ocr, empty)
        metadata.add_image_tag(folder, "one.png", "Dog")
        metadata.add_image_tag(folder, "one.png", "Old")
        metadata.add_image_tag(folder, "two.png", "Work")
        metadata.set_image_favorite(folder, "one.png", True)

        cleared = service.execute(
            ActionRequest(
                ACTION_REMOVE_ALL_TAGS,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                    ActionTarget(image_id=rec_empty.image_id, path=str(empty)),
                ),
            ),
            confirmed=True,
        )
        assert cleared.succeeded == 2
        assert cleared.skipped == 1
        assert metadata.get_image_tags(folder, "one.png") == []
        assert metadata.get_image_tags(folder, "two.png") == []
        assert metadata.is_image_favorite(folder, "one.png") is True
        from app.workspace.plan import summarize_action_result
        text = summarize_action_result(cleared)
        assert "Removed all tags from 2 images" in text
        noop = service.execute(
            ActionRequest(
                ACTION_REMOVE_ALL_TAGS,
                targets=(ActionTarget(image_id=rec_empty.image_id, path=str(empty)),),
            ),
            confirmed=True,
        )
        assert noop.changed_count == 0
        assert "had tags to remove" in summarize_action_result(noop)

        metadata.add_image_tag(folder, "one.png", "Dog")
        metadata.add_image_tag(folder, "one.png", "Old")
        replaced = service.execute(
            ActionRequest(
                ACTION_REPLACE_TAGS,
                targets=(ActionTarget(image_id=rec_one.image_id, path=str(one)),),
                parameters={"tags": ["Test", "Work"]},
            ),
            confirmed=True,
        )
        assert replaced.changed_count == 1
        assert metadata.get_image_tags(folder, "one.png") == ["Test", "Work"]
        assert metadata.is_image_favorite(folder, "one.png") is True
        same = service.execute(
            ActionRequest(
                ACTION_REPLACE_TAGS,
                targets=(ActionTarget(image_id=rec_one.image_id, path=str(one)),),
                parameters={"tags": ["Work", "Test"]},
            ),
            confirmed=True,
        )
        assert same.changed_count == 0
        assert "already had those tags" in summarize_action_result(same)
        blocked = service.plan(
            ActionRequest(
                ACTION_REPLACE_TAGS,
                targets=(ActionTarget(image_id=rec_one.image_id, path=str(one)),),
                parameters={"tags": []},
            )
        )
        assert blocked.executable_count == 0
    finally:
        _close(database)


def test_add_and_remove_multiple_tags(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        one = _png(folder / "one.png")
        rec = _index(ocr, one)
        metadata.add_image_tag(folder, "one.png", "Work")
        added = service.execute(
            ActionRequest(
                ACTION_ADD_TAG,
                targets=(ActionTarget(image_id=rec.image_id, path=str(one)),),
                parameters={"tags": ["Work", "Important", "Outdoor"]},
            ),
            confirmed=True,
        )
        assert added.changed_count == 1
        assert metadata.get_image_tags(folder, "one.png") == ["Work", "Important", "Outdoor"]
        removed = service.execute(
            ActionRequest(
                ACTION_REMOVE_TAG,
                targets=(ActionTarget(image_id=rec.image_id, path=str(one)),),
                parameters={"tags": ["Work", "Missing", "Outdoor"]},
            ),
            confirmed=True,
        )
        assert removed.changed_count == 1
        assert metadata.get_image_tags(folder, "one.png") == ["Important"]
    finally:
        _close(database)


def test_batch_rename_strategies_and_safety(tmp_path: Path):
    from app.actions.rename_names import generate_strategy_names

    names, error = generate_strategy_names(
        tuple(f"img_{index:03d}.png" for index in range(120)),
        {"rename_strategy": "numbered", "base_name": "Screenshot", "start": 1},
    )
    assert error == ""
    assert names[0] == "Screenshot 001.png"
    assert names[119] == "Screenshot 120.png"
    overflow, error = generate_strategy_names(
        tuple(f"a{index}.png" for index in range(100)),
        {"rename_strategy": "numbered", "base_name": "Cat", "start": 1, "digits": 1},
    )
    assert error == "numbering_overflow"
    assert overflow == {}
    dup, error = generate_strategy_names(
        ("one.png", "two.png"),
        {"rename_strategy": "prefix", "prefix": "Same_"},
    )
    assert error == ""
    collide, error = generate_strategy_names(
        ("Cat.png", "Dog.png"),
        {"rename_strategy": "sequential", "base_name": "Pet", "start": 1},
    )
    assert error == ""
    assert collide[0] == "Pet 1.png"

    service, metadata, ocr, database = _service(tmp_path)
    try:
        folder = tmp_path / "lib"
        folder.mkdir()
        one = _png(folder / "one.png")
        two = _png(folder / "two.png")
        rec_one = _index(ocr, one)
        rec_two = _index(ocr, two)
        metadata.add_image_tag(folder, "one.png", "keep")
        japanese = service.execute(
            ActionRequest(
                ACTION_RENAME,
                targets=(
                    ActionTarget(image_id=rec_one.image_id, path=str(one)),
                    ActionTarget(image_id=rec_two.image_id, path=str(two)),
                ),
                parameters={"rename_strategy": "sequential", "base_name": "猫", "start": 1},
            ),
            confirmed=True,
        )
        assert japanese.changed_count == 2
        assert (folder / "猫 1.png").exists()
        assert metadata.get_image_tags(folder, "猫 1.png") == ["keep"]
        illegal = service.plan(
            ActionRequest(
                ACTION_RENAME,
                targets=(ActionTarget(image_id=rec_one.image_id, path=str(folder / "猫 1.png")),),
                parameters={"rename_strategy": "prefix", "prefix": "bad:name_"},
            )
        )
        assert illegal.executable_count == 0
        assert any(found.code == "invalid_filename" for found in illegal.issues)
    finally:
        _close(database)


def test_move_rejects_path_outside_managed_root(tmp_path: Path):
    service, metadata, ocr, database = _service(tmp_path)
    try:
        library = tmp_path / "library"
        outside = tmp_path / "outside"
        library.mkdir()
        outside.mkdir()
        src = _png(library / "shot.png")
        rec = _index(ocr, src)
        service.context.managed_root = library
        blocked = service.plan(
            ActionRequest(
                ACTION_MOVE,
                targets=(ActionTarget(image_id=rec.image_id, path=str(src)),),
                parameters={"destination_path": str(outside), "destination_name": "outside"},
            )
        )
        assert blocked.executable_count == 0
        assert any(found.code == "path_not_allowed" for found in blocked.issues)
        hidden = service.plan(
            ActionRequest(
                ACTION_CREATE_FOLDER,
                parameters={"parent_path": str(library), "name": ".sstool"},
            )
        )
        assert hidden.executable_count == 0
    finally:
        _close(database)
