from __future__ import annotations

import hashlib
import inspect
import json
import math
import sqlite3
import struct
from pathlib import Path

import pytest
from PIL import Image

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRInvalidRecordError
from app.ocr.repository import OCRRepository
from app.ocr.schema import SCHEMA_SQL, SCHEMA_VERSION
from app.relevance import RelevanceImage, RelevanceProviderError
from app.semantic.embedding import decode_embedding, encode_embedding
from app.semantic.models import SourceSnapshot
from app.semantic_index.models import (
    SemanticIndexIdentity,
    SemanticIndexState,
    default_index_identity,
)
from app.semantic_index.provider import IndexRun, SemanticIndexProvider, make_index_provider
from app.semantic_index.repository import SemanticIndexRepository
from app.semantic_index.schema import (
    INDEX_FIELDS,
    INDEX_PROMPT,
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    INDEX_USER_PREFIX,
    clip_index_text,
    index_record,
    metadata_only,
    validate_index_payload,
)
from app.semantic_index.scoring import lexical_score
from app.semantic_index.service import SemanticIndexService
from app.ui import images_analysis, images_search

NOW = "2026-08-18T00:00:00+00:00"
IDENTITY = default_index_identity(vision_model="gpt-5.4-mini")


def deterministic_text_embedding(text: str) -> bytes:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [float(digest[index % len(digest)] + 1) for index in range(512)]
    norm = math.sqrt(sum(value * value for value in values))
    return encode_embedding((value / norm for value in values), dimension=512)


def sample_record(**fields):
    return index_record(
        visual_summary="a brown dog sitting on grass",
        objects_entities=["dog"],
        scene_environment="outdoor lawn",
        media_type="photograph",
        searchable_concepts=["dog", "puppy"],
        identities=[],
        **fields,
    )


class FakeEmbedder:
    def embed_text(self, text: str) -> bytes:
        return deterministic_text_embedding(text)


class FakeVision:
    def __init__(self, *, records=None, reason=None, model="gpt-5.4-mini"):
        self.model = model
        self.records = records or {}
        self.reason = reason
        self.calls: list[list[int]] = []

    def index(self, images, *, cancelled=None):
        ids = [item.image_id for item in images]
        self.calls.append(ids)
        results = []
        for item in images:
            if self.reason:
                record = {"image_id": item.image_id, "unknown_reason": self.reason}
            else:
                record = dict(self.records.get(item.image_id) or sample_record())
                record["image_id"] = item.image_id
                record["unknown_reason"] = None
            results.append(record)
        return IndexRun(results=tuple(results), failed_image_ids=tuple(ids if self.reason else ()))


@pytest.fixture
def repositories(tmp_path):
    database = OCRDatabase(tmp_path / "index.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database)
    indexes = SemanticIndexRepository(database)
    yield database, images, indexes
    database.close()


def add_image(images: OCRRepository, tmp_path: Path, name: str, *, color="red", size=None, mtime=None, fingerprint="same"):
    path = tmp_path / name
    Image.new("RGB", (24, 16), color).save(path)
    stat = path.stat()
    return images.upsert_image(
        str(path),
        size_bytes=size if size is not None else stat.st_size,
        mtime_ns=mtime if mtime is not None else stat.st_mtime_ns,
        quick_fingerprint=fingerprint,
    )


def make_service(images, indexes, vision=None, embedder=None, identity=IDENTITY):
    return SemanticIndexService(
        indexes,
        images,
        vision=vision or FakeVision(),
        embedder=embedder or FakeEmbedder(),
        identity=identity,
    )


def test_schema_creates_semantic_index_tables(repositories):
    database, _, _ = repositories
    names = {row[0] for row in database.connection.execute("SELECT name FROM sqlite_master")}
    assert database.schema_version() == SCHEMA_VERSION == 7
    assert {"semantic_indexes", "semantic_index_failures", "semantic_indexes_identity_idx", "image_facts", "image_facts_failures", "image_facts_identity_idx"} <= names


def test_schema_v5_migrates_without_dropping_embeddings(tmp_path):
    path = tmp_path / "v5.sqlite3"
    v5_sql = SCHEMA_SQL.split("CREATE TABLE IF NOT EXISTS semantic_indexes", 1)[0]
    connection = sqlite3.connect(path)
    connection.executescript(v5_sql)
    connection.executemany(
        "INSERT INTO schema_meta(key,value) VALUES(?,?)",
        [
            ("schema_version", "5"),
            ("normalization_version", "1"),
            ("search_schema_version", "1"),
            ("created_at", NOW),
            ("updated_at", NOW),
        ],
    )
    connection.execute(
        "INSERT INTO images(path,path_norm,folder_path,folder_path_norm,filename,filename_norm,size_bytes,mtime_ns,file_state,discovered_at,last_seen_at) VALUES('D:\\a.png','d:\\a.png','D:\\','d:\\','a.png','a.png',1,1,'present',?,?)",
        (NOW, NOW),
    )
    blob = deterministic_text_embedding("keep")
    connection.execute(
        """INSERT INTO semantic_embeddings(
 image_id,embedding,dimension,embedding_format_version,model_id,bundle_version,model_revision,
 pipeline_version,source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at
) VALUES(1,?,512,1,'laion/CLIP-ViT-B-32-laion2B-s34B-b79K','test-v1','test',1,1,1,'same',?,?)""",
        (blob, NOW, NOW),
    )
    connection.commit()
    connection.close()
    with OCRDatabase(path, clock=lambda: NOW) as database:
        names = {row[0] for row in database.connection.execute("SELECT name FROM sqlite_master")}
        assert database.schema_version() == SCHEMA_VERSION
        assert {"semantic_indexes", "semantic_index_failures", "image_facts", "image_facts_failures"} <= names
        row = database.connection.execute(
            "SELECT dimension,model_id FROM semantic_embeddings WHERE image_id=1"
        ).fetchone()
        assert tuple(row) == (512, "laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
        assert database.connection.execute("SELECT count(*) FROM semantic_indexes").fetchone()[0] == 0


def test_save_and_read_metadata_and_512d_embedding(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    source = SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint)
    record = sample_record()
    blob = deterministic_text_embedding(clip_index_text(record))
    stored = indexes.upsert_index(image.image_id, record, blob, IDENTITY, source)
    loaded = indexes.get_index(image.image_id)
    assert loaded is not None
    assert loaded.metadata["visual_summary"] == "a brown dog sitting on grass"
    assert loaded.metadata["objects_entities"] == ["dog"]
    assert set(loaded.metadata) == set(INDEX_FIELDS)
    assert loaded.identity == IDENTITY
    assert loaded.text_embedding == blob
    values = decode_embedding(loaded.text_embedding, dimension=512)
    assert len(values) == 512
    assert stored.created_at == NOW
    assert "unknown_reason" not in json.loads(
        indexes.conn.execute(
            "SELECT metadata_json FROM semantic_indexes WHERE image_id=?",
            (image.image_id,),
        ).fetchone()[0]
    )


def test_corrupt_embedding_is_not_fresh(repositories, tmp_path):
    database, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    indexes.upsert_index(
        image.image_id,
        sample_record(),
        deterministic_text_embedding("dog"),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    database.connection.execute(
        "UPDATE semantic_indexes SET text_embedding=? WHERE image_id=?",
        (b"short", image.image_id),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")
    assert indexes.get_index(image.image_id) is None
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.CORRUPT
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_new_image_is_pending_and_needed(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "new.png")
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.PENDING
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_fresh_index_is_reusable(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    source = SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint)
    indexes.upsert_index(
        image.image_id, sample_record(), deterministic_text_embedding("dog"), IDENTITY, source
    )
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FRESH
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == []


def test_source_change_marks_stale(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png", fingerprint="same")
    source = SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint)
    indexes.upsert_index(
        image.image_id, sample_record(), deterministic_text_embedding("dog"), IDENTITY, source
    )
    images.upsert_image(image.path, size_bytes=image.size_bytes + 10, mtime_ns=image.mtime_ns + 1, quick_fingerprint="changed")
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.STALE
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_mtime_only_change_with_matching_fingerprint_stays_fresh(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png", fingerprint="same")
    indexes.upsert_index(
        image.image_id,
        sample_record(),
        deterministic_text_embedding("dog"),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    images.upsert_image(image.path, size_bytes=image.size_bytes, mtime_ns=image.mtime_ns + 99, quick_fingerprint="same")
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FRESH


def test_model_and_schema_version_change_marks_stale(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    indexes.upsert_index(
        image.image_id,
        sample_record(),
        deterministic_text_embedding("dog"),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    model_changed = SemanticIndexIdentity(
        vision_model="gpt-future",
        prompt_version=IDENTITY.prompt_version,
        schema_version=IDENTITY.schema_version,
        embedding_model_id=IDENTITY.embedding_model_id,
    )
    schema_changed = SemanticIndexIdentity(
        vision_model=IDENTITY.vision_model,
        prompt_version=IDENTITY.prompt_version,
        schema_version="image-semantic-index-v4",
        embedding_model_id=IDENTITY.embedding_model_id,
    )
    prompt_changed = SemanticIndexIdentity(
        vision_model=IDENTITY.vision_model,
        prompt_version="semantic-index-v5",
        schema_version=IDENTITY.schema_version,
        embedding_model_id=IDENTITY.embedding_model_id,
    )
    assert indexes.classify([image.image_id], model_changed)[image.image_id] == SemanticIndexState.STALE
    assert indexes.classify([image.image_id], schema_changed)[image.image_id] == SemanticIndexState.STALE
    assert indexes.classify([image.image_id], prompt_changed)[image.image_id] == SemanticIndexState.STALE


def test_delete_image_cascades_index_and_failure(repositories, tmp_path):
    database, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    indexes.upsert_index(
        image.image_id,
        sample_record(),
        deterministic_text_embedding("dog"),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    other = add_image(images, tmp_path, "cat.png")
    indexes.record_failure(other.image_id, "api_failure")
    images.delete_image(image.image_id)
    images.delete_image(other.image_id)
    assert indexes.get_index(image.image_id) is None
    assert indexes.get_failure(other.image_id) is None
    assert indexes.delete_orphans() == 0
    assert database.quick_check() == "ok"


def test_missing_image_is_deleted_state(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    images.mark_file_state(image.image_id, "missing")
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.DELETED
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == []


def test_failed_upsert_rejects_unknown_reason(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    with pytest.raises(OCRInvalidRecordError):
        indexes.upsert_index(
            image.image_id,
            index_record(unknown_reason="malformed"),
            deterministic_text_embedding("x"),
            IDENTITY,
            SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
        )
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.PENDING


def test_api_failure_is_not_fresh_and_stays_retryable(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    vision = FakeVision(reason="api_failure")
    result = make_service(images, indexes, vision=vision).index_images([image.image_id])
    assert result.succeeded == 0
    assert result.failed == 1
    assert indexes.get_index(image.image_id) is None
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FAILED
    failure = indexes.get_failure(image.image_id)
    assert failure is not None and failure.retryable is True
    assert failure.error_code == "api_failure"
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_cancelled_index_is_not_stored_as_failure(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    vision = FakeVision(reason="cancelled")
    make_service(images, indexes, vision=vision).index_images([image.image_id])
    assert indexes.get_index(image.image_id) is None
    assert indexes.get_failure(image.image_id) is None
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.PENDING
    assert indexes.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_malformed_response_is_not_fresh(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    vision = FakeVision(reason="malformed")
    make_service(images, indexes, vision=vision).index_images([image.image_id])
    assert indexes.get_index(image.image_id) is None
    assert indexes.classify([image.image_id], IDENTITY)[image.image_id] == SemanticIndexState.FAILED
    assert indexes.get_failure(image.image_id).error_code == "malformed"


def test_fresh_images_are_not_reparsed(repositories, tmp_path):
    _, images, indexes = repositories
    fresh = add_image(images, tmp_path, "fresh.png")
    pending = add_image(images, tmp_path, "pending.png")
    indexes.upsert_index(
        fresh.image_id,
        sample_record(),
        deterministic_text_embedding("fresh"),
        IDENTITY,
        SourceSnapshot(fresh.size_bytes, fresh.mtime_ns, fresh.quick_fingerprint),
    )
    vision = FakeVision()
    result = make_service(images, indexes, vision=vision).index_images([fresh.image_id, pending.image_id])
    assert vision.calls == [[pending.image_id]]
    assert result.succeeded == 1
    assert result.skipped == 1
    assert indexes.classify([fresh.image_id], IDENTITY)[fresh.image_id] == SemanticIndexState.FRESH
    assert indexes.classify([pending.image_id], IDENTITY)[pending.image_id] == SemanticIndexState.FRESH


def test_differential_indexes_only_new_and_stale(repositories, tmp_path):
    _, images, indexes = repositories
    kept = add_image(images, tmp_path, "kept.png", color="red")
    changed = add_image(images, tmp_path, "changed.png", color="blue")
    new = add_image(images, tmp_path, "new.png", color="green")
    for image in (kept, changed):
        indexes.upsert_index(
            image.image_id,
            sample_record(),
            deterministic_text_embedding(image.filename),
            IDENTITY,
            SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
        )
    images.upsert_image(
        changed.path,
        size_bytes=changed.size_bytes + 1,
        mtime_ns=changed.mtime_ns + 1,
        quick_fingerprint="changed",
    )
    vision = FakeVision()
    service = make_service(images, indexes, vision=vision)
    needed = service.needed_image_ids([kept.image_id, changed.image_id, new.image_id])
    assert needed == [changed.image_id, new.image_id]
    service.index_images([kept.image_id, changed.image_id, new.image_id])
    assert vision.calls == [[changed.image_id, new.image_id]]


def test_index_generation_does_not_take_a_query(repositories, tmp_path):
    _, images, indexes = repositories
    image = add_image(images, tmp_path, "dog.png")
    vision = FakeVision()
    make_service(images, indexes, vision=vision).index_images([image.image_id])
    assert vision.calls == [[image.image_id]]
    assert "query" not in inspect.signature(vision.index).parameters


def test_converted_jpeg_is_not_persisted(tmp_path, monkeypatch):
    source = tmp_path / "dog.png"
    Image.new("RGB", (80, 40), "red").save(source)
    captured = {}

    def fake_post(self, payload, *, image_diagnostics=()):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": json.dumps({
                "results": [{
                    "image_id": 1,
                    "visual_summary": "a red rectangle",
                    "objects_entities": ["rectangle"],
                    "scene_environment": "",
                    "media_type": "illustration",
                    "ui_interface_concepts": [],
                    "visible_activities": [],
                    "visual_attributes": ["red"],
                    "searchable_concepts": ["red rectangle"],
                    "identities": [],
                    "incidental_notes": "",
                }]
            })}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(SemanticIndexProvider, "_post_with_retry", fake_post)
    provider = make_index_provider()
    provider.api_key = "test-key"
    provider.unknown_retries = 0
    run = provider.index([RelevanceImage(1, source)])
    assert run.results[0]["media_type"] == "illustration"
    user = captured["payload"]["messages"][1]["content"]
    assert user[0]["text"] == INDEX_USER_PREFIX
    assert all("query" not in str(part).lower() or "do not infer a user query" in str(part).lower() for part in user)
    jpeg_files = list(tmp_path.glob("**/*.jpg")) + list(tmp_path.glob("**/*.jpeg"))
    assert jpeg_files == []
    assert source.exists()


def test_provider_malformed_and_api_failure_are_unknown(tmp_path, monkeypatch):
    source = tmp_path / "dog.png"
    Image.new("RGB", (32, 16), "red").save(source)

    def malformed_post(self, payload, *, image_diagnostics=()):
        return {"choices": [{"message": {"content": "{"}}]}

    monkeypatch.setattr(SemanticIndexProvider, "_post_with_retry", malformed_post)
    provider = make_index_provider()
    provider.api_key = "test-key"
    provider.unknown_retries = 0
    run = provider.index([RelevanceImage(1, source)])
    assert run.results[0]["unknown_reason"] in {"malformed", "api_failure"}
    assert run.failed_image_ids == (1,)

    def failing_post(self, payload, *, image_diagnostics=()):
        raise RelevanceProviderError("Vision API timed out.")

    monkeypatch.setattr(SemanticIndexProvider, "_post_with_retry", failing_post)
    run = provider.index([RelevanceImage(2, source)])
    assert run.results[0]["unknown_reason"] == "timeout"
    assert run.failed_image_ids == (2,)


def test_validate_payload_marks_malformed_and_omitted():
    parsed = validate_index_payload({"results": [{"image_id": 1, "media_type": "nope"}]}, [1, 2])
    assert parsed[0]["unknown_reason"] == "malformed"
    assert parsed[1]["unknown_reason"] == "omitted"


def test_provider_classify_rejects_query():
    provider = make_index_provider()
    with pytest.raises(RuntimeError, match="index()"):
        provider.classify("dog", [])


def test_product_meaning_search_uses_facts_not_generation():
    search_source = inspect.getsource(images_search)
    analysis_source = inspect.getsource(images_analysis)
    assert "ImageFactsRepository" in search_source
    assert "fresh_facts_for_search" in search_source
    assert "match_records" in search_source
    assert "split_meaning_candidates" not in search_source
    assert "ProgressiveSemanticIndexer" not in search_source
    assert "ProgressiveFactsIndexer" not in search_source
    assert "index_images" not in search_source
    assert "SemanticIndexService" not in analysis_source
    assert "ProgressiveSemanticIndexer" not in analysis_source
    assert "index_images" not in analysis_source
    assert INDEX_PROMPT_VERSION == "semantic-index-v4"
    assert INDEX_SCHEMA_VERSION == "image-semantic-index-v3"
    assert "Do not infer queries" in INDEX_PROMPT
    assert "identities" in INDEX_PROMPT.lower()
    assert "confidence" in INDEX_PROMPT.lower()
    assert "visual" in INDEX_PROMPT.lower()
    assert "gallery" in INDEX_PROMPT.lower()
    assert set(metadata_only(sample_record())) == set(INDEX_FIELDS)


def test_clip_index_text_keeps_named_entities_and_incidental_context():
    record = index_record(
        visual_summary="A chat webpage is open inside a named web browser.",
        objects_entities=["ChatGPT", "Google Chrome", "web browser"],
        scene_environment="Windows desktop",
        media_type="screenshot",
        ui_interface_concepts=["browser", "chat"],
        searchable_concepts=["ChatGPT", "Google Chrome", "web browser", "chat interface"],
        incidental_notes="A smartphone is on the desk.",
    )
    text = clip_index_text(record)
    assert text.index("ChatGPT") < text.index("screenshot")
    assert "Google Chrome" in text
    assert "smartphone" in text
    assert lexical_score("Google Chrome", record) >= 0.5
    assert lexical_score("Chrome", record) >= 0.5
    assert lexical_score("ChatGPT", record) >= 0.5


def test_identities_merge_into_searchable_lists():
    from app.semantic_index.schema import normalize_index_record

    record = normalize_index_record({
        "visual_summary": "A browser window is open.",
        "objects_entities": ["browser window"],
        "scene_environment": "desktop",
        "media_type": "screenshot",
        "ui_interface_concepts": ["browser"],
        "visible_activities": [],
        "visual_attributes": [],
        "searchable_concepts": ["browser"],
        "identities": [{
            "name": "Google Chrome",
            "kind": "application",
            "importance": "secondary",
            "confidence": "likely",
            "evidence": "Chrome-like tab strip and address bar.",
        }],
        "incidental_notes": "",
    })
    assert record is not None
    assert "Google Chrome" in record["objects_entities"]
    assert "Google Chrome" in record["searchable_concepts"]
    assert "Google Chrome" in clip_index_text(record)


def test_uncertain_identity_is_stored_but_not_merged_for_search():
    from app.semantic_index.schema import normalize_index_record

    record = normalize_index_record({
        "visual_summary": "A small icon on the taskbar.",
        "objects_entities": ["taskbar"],
        "scene_environment": "desktop",
        "media_type": "screenshot",
        "ui_interface_concepts": ["taskbar"],
        "visible_activities": [],
        "visual_attributes": [],
        "searchable_concepts": ["taskbar"],
        "identities": [{
            "name": "Google Chrome",
            "kind": "application",
            "importance": "incidental",
            "confidence": "uncertain",
            "evidence": "Small colorful circular icon only.",
        }],
        "incidental_notes": "",
    })
    assert record is not None
    assert record["identities"][0]["confidence"] == "uncertain"
    assert "Google Chrome" not in record["objects_entities"]
    assert "Google Chrome" not in clip_index_text(record)


def test_incidental_only_named_entity_does_not_lexical_hit():
    from app.semantic_index.scoring import PRODUCT_SEARCH_CONFIG, include_hit

    record = index_record(
        visual_summary="A game screenshot fills the monitor.",
        objects_entities=["game character"],
        scene_environment="desktop",
        media_type="screenshot",
        searchable_concepts=["video game", "game screenshot"],
        incidental_notes="Google Chrome is visible on the Windows taskbar.",
    )
    assert lexical_score("Chrome", record) == 0.0
    assert lexical_score("Google Chrome", record) == 0.0
    assert include_hit(0.26, 0.68, 0.0, PRODUCT_SEARCH_CONFIG) is False
