"""Progressive Semantic Index generation after the first Ask AI send."""

from __future__ import annotations

import threading
from pathlib import Path

from PIL import Image

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.models import SourceSnapshot
from app.semantic_index.models import SemanticIndexState
from app.semantic_index.progressive import ProgressiveSemanticIndexer, make_product_progressive_indexer
from app.semantic_index.provider import IndexRun
from app.semantic_index.repository import SemanticIndexRepository
from app.ui import images_analysis, images_search

from test_semantic_index import (
    IDENTITY,
    NOW,
    add_image,
    deterministic_text_embedding,
    make_service,
    sample_record,
)


class GatedVision:
    def __init__(self):
        self.model = "gpt-5.4-mini"
        self.calls: list[list[int]] = []
        self.gate = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def index(self, images, *, cancelled=None):
        ids = [item.image_id for item in images]
        self.calls.append(ids)
        self.gate.set()
        self.release.wait(5)
        results = []
        for item in images:
            if cancelled is not None and cancelled():
                results.append({"image_id": item.image_id, "unknown_reason": "cancelled"})
                continue
            record = sample_record()
            record["image_id"] = item.image_id
            record["unknown_reason"] = None
            results.append(record)
        return IndexRun(
            results=tuple(results),
            failed_image_ids=tuple(ids if cancelled is not None and cancelled() else ()),
        )


def _env(tmp_path, names, *, chunk_size=8, vision=None):
    database = OCRDatabase(tmp_path / "index.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database)
    indexes = SemanticIndexRepository(database)
    folder = tmp_path / "library"
    folder.mkdir()
    records = [add_image(images, folder, name) for name in names]
    vision = vision or GatedVision()
    service = make_service(images, indexes, vision=vision)
    indexer = ProgressiveSemanticIndexer(
        service, images, chunk_size=chunk_size, reconcile=True
    )
    return database, images, indexes, folder, records, vision, indexer


def test_consent_false_does_not_generate(tmp_path):
    database, images, indexes, folder, records, vision, indexer = _env(tmp_path, ["a.png"])
    try:
        assert indexer.start(folder, consented=False) is False
        assert indexer.wait(1) is True
        assert vision.calls == []
        assert indexes.classify([records[0].image_id], IDENTITY)[records[0].image_id] == SemanticIndexState.PENDING
    finally:
        indexer.close()
        database.close()


def test_construction_and_folder_path_do_not_generate(tmp_path):
    database, images, indexes, folder, records, vision, indexer = _env(tmp_path, ["a.png"])
    try:
        assert vision.calls == []
        assert indexer.is_running() is False
        assert indexes.needed_image_ids([records[0].image_id], IDENTITY) == [records[0].image_id]
    finally:
        indexer.close()
        database.close()


def test_first_start_indexes_only_needed_images(tmp_path):
    database, images, indexes, folder, records, vision, indexer = _env(
        tmp_path, ["fresh.png", "pending.png"]
    )
    fresh, pending = records
    indexes.upsert_index(
        fresh.image_id,
        sample_record(),
        deterministic_text_embedding("fresh"),
        IDENTITY,
        SourceSnapshot(fresh.size_bytes, fresh.mtime_ns, fresh.quick_fingerprint),
    )
    try:
        assert indexer.start(folder, consented=True) is True
        assert indexer.wait(5) is True
        assert vision.calls == [[pending.image_id]]
        states = indexes.classify([fresh.image_id, pending.image_id], IDENTITY)
        assert states[fresh.image_id] == SemanticIndexState.FRESH
        assert states[pending.image_id] == SemanticIndexState.FRESH
    finally:
        indexer.close()
        database.close()


def test_second_start_does_not_resend_fresh_images(tmp_path):
    database, images, indexes, folder, records, vision, indexer = _env(
        tmp_path, ["a.png", "b.png"]
    )
    try:
        assert indexer.start(folder, consented=True)
        assert indexer.wait(5)
        first = [list(call) for call in vision.calls]
        assert sorted(sum(first, [])) == sorted(image.image_id for image in records)
        assert indexer.start(folder, consented=True)
        assert indexer.wait(5)
        assert vision.calls == first
    finally:
        indexer.close()
        database.close()


def test_changed_image_is_the_only_regeneration_target(tmp_path):
    database, images, indexes, folder, records, vision, indexer = _env(
        tmp_path, ["kept.png", "changed.png"]
    )
    kept, changed = records
    try:
        assert indexer.start(folder, consented=True)
        assert indexer.wait(5)
        vision.calls.clear()
        Image.new("RGB", (40, 24), "blue").save(changed.path)
        assert indexer.start(folder, consented=True)
        assert indexer.wait(5)
        assert vision.calls == [[changed.image_id]]
        states = indexes.classify([kept.image_id, changed.image_id], IDENTITY)
        assert states[kept.image_id] == SemanticIndexState.FRESH
        assert states[changed.image_id] == SemanticIndexState.FRESH
    finally:
        indexer.close()
        database.close()


def test_progressive_chunks_start_before_library_is_complete(tmp_path):
    vision = GatedVision()
    vision.release.clear()
    database, images, indexes, folder, records, vision, indexer = _env(
        tmp_path, ["a.png", "b.png", "c.png"], chunk_size=1, vision=vision
    )
    try:
        assert indexer.start(folder, consented=True)
        assert vision.gate.wait(2)
        assert vision.calls == [[records[0].image_id]]
        assert indexes.classify([records[1].image_id], IDENTITY)[records[1].image_id] == SemanticIndexState.PENDING
        vision.release.set()
        assert indexer.wait(5)
        assert [call[0] for call in vision.calls] == [image.image_id for image in records]
        assert all(
            indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FRESH
            for image in records
        )
    finally:
        vision.release.set()
        indexer.close()
        database.close()


def test_folder_change_does_not_index_previous_folder(tmp_path):
    vision = GatedVision()
    vision.release.clear()
    database = OCRDatabase(tmp_path / "index.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database)
    indexes = SemanticIndexRepository(database)
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    first = add_image(images, folder_a, "one.png")
    second = add_image(images, folder_a, "two.png")
    other = add_image(images, folder_b, "other.png")
    service = make_service(images, indexes, vision=vision)
    indexer = ProgressiveSemanticIndexer(service, images, chunk_size=1, reconcile=True)
    try:
        assert indexer.start(folder_a, consented=True)
        assert vision.gate.wait(2)
        assert vision.calls == [[first.image_id]]
        vision.gate.clear()
        assert indexer.start(folder_b, consented=True)
        vision.release.set()
        assert indexer.wait(5)
        sent = [image_id for call in vision.calls for image_id in call]
        assert second.image_id not in sent
        assert other.image_id in sent
        assert indexes.classify([other.image_id], IDENTITY)[other.image_id] == SemanticIndexState.FRESH
        assert indexes.classify([second.image_id], IDENTITY)[second.image_id] == SemanticIndexState.PENDING
    finally:
        vision.release.set()
        indexer.close()
        database.close()


def test_same_folder_start_while_running_does_not_duplicate_job(tmp_path):
    vision = GatedVision()
    vision.release.clear()
    database, images, indexes, folder, records, vision, indexer = _env(
        tmp_path, ["a.png"], chunk_size=1, vision=vision
    )
    try:
        assert indexer.start(folder, consented=True)
        assert vision.gate.wait(2)
        assert indexer.start(folder, consented=True) is True
        vision.release.set()
        assert indexer.wait(5)
        assert vision.calls == [[records[0].image_id]]
    finally:
        vision.release.set()
        indexer.close()
        database.close()


def test_product_indexer_does_not_start_without_consent(tmp_path):
    folder = tmp_path / "lib"
    folder.mkdir()
    indexer = make_product_progressive_indexer({})
    try:
        assert indexer.start(folder, consented=False) is False
        assert indexer.is_running() is False
    finally:
        indexer.close()


def test_search_and_analysis_do_not_own_progressive_generation():
    search_source = Path(images_search.__file__).read_text(encoding="utf-8")
    analysis_source = Path(images_analysis.__file__).read_text(encoding="utf-8")
    assert "ProgressiveSemanticIndexer" not in search_source
    assert "index_images" not in analysis_source
    assert "make_product_progressive_indexer" not in analysis_source
