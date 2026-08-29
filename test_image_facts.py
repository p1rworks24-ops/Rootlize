from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from app.image_facts.models import ImageFactsIdentity, ImageFactsState, default_facts_identity
from app.image_facts.progressive import ProgressiveFactsIndexer
from app.image_facts.provider import ImageFactsProvider, make_facts_provider, multiscale_views
from app.image_facts.repository import ImageFactsRepository
from app.image_facts.schema import (
    FACTS_PROMPT_VERSION,
    FACTS_SCHEMA_VERSION,
    FACTS_VERSION,
)
from app.image_facts.service import ImageFactsService
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.relevance import RelevanceImage
from app.semantic.models import SourceSnapshot

NOW = "2026-08-19T00:00:00+00:00"
IDENTITY = default_facts_identity(vision_model="gpt-5.4-mini")


def sample_facts(**fields):
    record = {
        "media_type": "screenshot",
        "scene_description": "a brown dog sitting on grass",
        "environment": "outdoor lawn",
        "ui_types": [],
        "entities": [
            {
                "name": "dog",
                "kind": "animal",
                "attributes": [],
                "colors": ["brown"],
                "states": [],
                "posture": "sitting",
                "observed_color_description": "mostly brown",
                "visibility": "visible",
                "identifiability": "clear",
            }
        ],
        "applications": [],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }
    record.update(fields)
    return record


def add_image(images: OCRRepository, tmp_path: Path, name: str, *, fingerprint="same"):
    path = tmp_path / name
    Image.new("RGB", (24, 16), "red").save(path)
    stat = path.stat()
    return images.upsert_image(
        str(path),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        quick_fingerprint=fingerprint,
    )


class FakeVision:
    def __init__(self, *, records=None, model="gpt-5.4-mini"):
        self.model = model
        self.records = records or {}
        self.calls: list[list[int]] = []

    def index(self, images, *, cancelled=None):
        ids = [item.image_id for item in images]
        self.calls.append(ids)
        from app.image_facts.provider import FactsRun

        results = []
        for item in images:
            record = dict(self.records.get(item.image_id) or sample_facts())
            record["image_id"] = item.image_id
            results.append(record)
        return FactsRun(results=tuple(results), request_count=len(results), sent_image_count=len(results))


@pytest.fixture
def repositories(tmp_path):
    database = OCRDatabase(tmp_path / "facts.sqlite3", clock=lambda: NOW).open()
    images = OCRRepository(database)
    facts = ImageFactsRepository(database)
    yield database, images, facts
    database.close()


def test_facts_schema_roundtrip(repositories, tmp_path):
    _, images, facts = repositories
    image = add_image(images, tmp_path, "one.png")
    stored = facts.upsert_facts(
        image.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    loaded = facts.get_facts(image.image_id)
    assert loaded is not None
    assert loaded.facts["media_type"] == "screenshot"
    assert loaded.facts["entities"][0]["name"] == "dog"
    assert loaded.prompt_version == FACTS_PROMPT_VERSION
    assert loaded.schema_version == FACTS_SCHEMA_VERSION
    assert loaded.facts_version == FACTS_VERSION
    assert loaded.identity == IDENTITY
    assert stored.facts_version == FACTS_VERSION


def test_old_facts_version_is_stale(repositories, tmp_path):
    _, images, facts = repositories
    image = add_image(images, tmp_path, "old.png")
    old = ImageFactsIdentity(
        vision_model=IDENTITY.vision_model,
        prompt_version="db-sot-facts-v6b",
        schema_version=FACTS_SCHEMA_VERSION,
        facts_version="db-sot-facts-v6b",
    )
    facts.upsert_facts(
        image.image_id,
        sample_facts(),
        old,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    states = facts.classify([image.image_id], IDENTITY)
    assert states[image.image_id] == ImageFactsState.STALE
    assert facts.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]
    assert facts.fresh_facts_for_search([image.image_id], IDENTITY) == {}


def test_missing_facts_are_pending(repositories, tmp_path):
    _, images, facts = repositories
    image = add_image(images, tmp_path, "pending.png")
    states = facts.classify([image.image_id], IDENTITY)
    assert states[image.image_id] == ImageFactsState.PENDING
    assert facts.needed_image_ids([image.image_id], IDENTITY) == [image.image_id]


def test_service_generates_only_unparsed_images(repositories, tmp_path):
    _, images, facts = repositories
    fresh = add_image(images, tmp_path, "fresh.png")
    pending = add_image(images, tmp_path, "pending.png")
    facts.upsert_facts(
        fresh.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(fresh.size_bytes, fresh.mtime_ns, fresh.quick_fingerprint),
    )
    vision = FakeVision()
    service = ImageFactsService(facts, images, vision=vision, identity=IDENTITY)
    result = service.index_images([fresh.image_id, pending.image_id])
    assert vision.calls == [[pending.image_id]]
    assert result.succeeded == 1
    assert result.skipped == 1
    second = service.index_images([fresh.image_id, pending.image_id])
    assert vision.calls == [[pending.image_id]]
    assert second.succeeded == 0
    assert second.skipped == 2


def test_changed_source_is_regenerated(repositories, tmp_path):
    _, images, facts = repositories
    image = add_image(images, tmp_path, "changed.png", fingerprint="v1")
    facts.upsert_facts(
        image.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    path = tmp_path / "changed.png"
    Image.new("RGB", (24, 16), "blue").save(path)
    stat = path.stat()
    updated = images.upsert_image(
        str(path),
        size_bytes=stat.st_size + 10,
        mtime_ns=stat.st_mtime_ns,
        quick_fingerprint="v2",
    )
    vision = FakeVision()
    service = ImageFactsService(facts, images, vision=vision, identity=IDENTITY)
    assert service.needed_image_ids([updated.image_id]) == [updated.image_id]
    service.index_images([updated.image_id])
    assert vision.calls == [[updated.image_id]]


def test_progressive_indexer_skips_fresh_and_requires_consent(repositories, tmp_path):
    _, images, facts = repositories
    folder = tmp_path / "lib"
    folder.mkdir()
    image = add_image(images, folder, "one.png")
    vision = FakeVision()
    service = ImageFactsService(facts, images, vision=vision, identity=IDENTITY)
    indexer = ProgressiveFactsIndexer(service, images, reconcile=False)
    assert indexer.start(folder, consented=False) is False
    assert vision.calls == []
    assert indexer.start(folder, consented=True) is True
    indexer.wait(2)
    assert vision.calls == [[image.image_id]]
    snap = indexer.snapshot()
    assert snap.running is False
    assert snap.needed == 0
    assert snap.total == 1
    assert snap.ready == 1
    assert indexer.start(folder, consented=True) is False
    assert indexer.has_unready_images(folder) is False
    indexer.wait(2)
    assert vision.calls == [[image.image_id]]


def test_progressive_job_failure_logs_safe_proxy_fields(repositories, tmp_path, caplog):
    from app.ai_proxy.errors import AiProxyError

    class BoomVision:
        model = "gpt-5.4-mini"

        def index(self, images, *, cancelled=None):
            raise AiProxyError("budget_unavailable", status=0)

    _, images, facts = repositories
    folder = tmp_path / "lib"
    folder.mkdir()
    add_image(images, folder, "one.png")
    service = ImageFactsService(facts, images, vision=BoomVision(), identity=IDENTITY)
    indexer = ProgressiveFactsIndexer(service, images, reconcile=False)
    with caplog.at_level(logging.WARNING):
        assert indexer.start(folder, consented=True) is True
        indexer.wait(2)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "image-facts job-failure" in text
    assert "error_class=AiProxyError" in text
    assert "proxy_code=budget_unavailable" in text
    assert "http_status=0" in text
    assert "operation=facts_generate" in text
    assert "facts_needed=" in text
    assert "facts_generated=" in text
    assert "facts_failed=" in text
    assert "sk-" not in text
    assert "access-token" not in text
    assert "eyJ" not in text
    error = indexer.last_error()
    assert isinstance(error, AiProxyError)
    assert error.code == "budget_unavailable"


def test_progressive_indexer_only_generates_new_images(repositories, tmp_path):
    _, images, facts = repositories
    folder = tmp_path / "lib"
    folder.mkdir()
    fresh = add_image(images, folder, "fresh.png")
    facts.upsert_facts(
        fresh.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(fresh.size_bytes, fresh.mtime_ns, fresh.quick_fingerprint),
    )
    added = add_image(images, folder, "new.png")
    vision = FakeVision()
    service = ImageFactsService(facts, images, vision=vision, identity=IDENTITY)
    indexer = ProgressiveFactsIndexer(service, images, reconcile=False)
    assert indexer.start(folder, consented=True) is True
    indexer.wait(2)
    assert vision.calls == [[added.image_id]]
    assert indexer.has_unready_images(folder) is False
    assert indexer.start(folder, consented=True) is False


def test_facts_provider_is_one_request_per_image_without_resend():
    provider = make_facts_provider()
    assert isinstance(provider, ImageFactsProvider)
    assert provider.max_edge == 1536
    assert provider.image_detail == "high"
    assert provider.unknown_retries == 0
    assert provider.batch_size == 1
    assert provider.prompt_version == FACTS_PROMPT_VERSION
    with pytest.raises(RuntimeError, match="index"):
        provider.classify("dog", [])


def test_multiscale_keeps_overview_and_at_most_four_crops(tmp_path):
    small = tmp_path / "small.png"
    Image.new("RGB", (32, 32), "red").save(small)
    assert len(multiscale_views(small)) == 1
    large = tmp_path / "large.png"
    Image.new("RGB", (1600, 1200), "blue").save(large)
    views = multiscale_views(large, max_edge=1536)
    assert len(views) == 5
    assert views[0][0] == "Full image overview"
    assert views[0][2] <= 1536
    assert views[0][3] <= 1536


def test_facts_provider_posts_one_payload_with_views(monkeypatch, tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (1600, 1200), "green").save(path)
    provider = ImageFactsProvider(
        api_key="test",
        max_edge=1536,
        image_detail="high",
        unknown_retries=0,
        retries=0,
        timeout_seconds=1,
    )
    posts = []

    def fake_post(self, payload, *, image_diagnostics=()):
        posts.append(payload)
        return {
            "choices": [{"message": {"content": '{"results":[%s]}' % (
                '{"image_id":1,"media_type":"screenshot","scene_description":"desk",'
                '"environment":"","ui_types":[],"entities":[],"applications":[],'
                '"activities":[],"relationships":[],"notable_text":[]}'
            )}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(ImageFactsProvider, "_post_with_retry", fake_post)
    run = provider.index([RelevanceImage(1, path)])
    assert len(posts) == 1
    content = posts[0]["messages"][1]["content"]
    image_parts = [part for part in content if part.get("type") == "image_url"]
    assert 1 <= len(image_parts) <= 5
    assert all(part["image_url"]["detail"] == "high" for part in image_parts)
    assert run.request_count == 1
    assert run.results[0]["media_type"] == "screenshot"
