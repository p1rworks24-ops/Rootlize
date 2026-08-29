"""Local API usage measurement without query text or image content."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.ai_usage.recorder import AiUsageRecorder
from app.ai_usage.repository import AiUsageRepository
from app.image_facts.models import ImageFactsIdentity
from app.image_facts.repository import ImageFactsRepository
from app.image_facts.service import ImageFactsService
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.models import SourceSnapshot

from test_image_facts import FakeVision, IDENTITY, add_image, sample_facts
from test_progressive_vision_search import _MockRelevance, _provider


def _usage(tmp_path: Path) -> tuple[AiUsageRecorder, AiUsageRepository]:
    repository = AiUsageRepository(tmp_path / "ai-usage.sqlite3")
    return AiUsageRecorder(repository), repository


def test_usage_db_does_not_live_in_ocr_schema(tmp_path):
    database = OCRDatabase(tmp_path / "ocr-index.sqlite3").open()
    names = {
        row[0] for row in database.connection.execute("SELECT name FROM sqlite_master")
    }
    database.close()
    assert "ai_usage_events" not in names
    repository = AiUsageRepository(tmp_path / "ai-usage.sqlite3").open()
    usage_names = {
        row[0] for row in repository.connection.execute("SELECT name FROM sqlite_master")
    }
    repository.close()
    assert "ai_usage_events" in usage_names
    assert "ai_usage_totals" in usage_names


def test_vision_usage_counts_first_reparse_and_version(tmp_path):
    database = OCRDatabase(tmp_path / "facts.sqlite3").open()
    images = OCRRepository(database)
    facts = ImageFactsRepository(database)
    recorder, usage = _usage(tmp_path)
    first = add_image(images, tmp_path, "first.png")
    reparse = add_image(images, tmp_path, "reparse.png", fingerprint="v1")
    versioned = add_image(images, tmp_path, "version.png")
    facts.upsert_facts(
        reparse.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(reparse.size_bytes, reparse.mtime_ns, reparse.quick_fingerprint),
    )
    path = tmp_path / "reparse.png"
    Image.new("RGB", (24, 16), "blue").save(path)
    stat = path.stat()
    reparse = images.upsert_image(
        str(path),
        size_bytes=stat.st_size + 8,
        mtime_ns=stat.st_mtime_ns,
        quick_fingerprint="v2",
    )
    old = ImageFactsIdentity(
        vision_model=IDENTITY.vision_model,
        prompt_version="db-sot-facts-v6b",
        schema_version=IDENTITY.schema_version,
        facts_version="db-sot-facts-v6b",
    )
    facts.upsert_facts(
        versioned.image_id,
        sample_facts(),
        old,
        SourceSnapshot(versioned.size_bytes, versioned.mtime_ns, versioned.quick_fingerprint),
    )
    service = ImageFactsService(
        facts, images, vision=FakeVision(), identity=IDENTITY, usage=recorder
    )
    service.index_images([first.image_id, reparse.image_id, versioned.image_id])
    totals = usage.totals()
    assert totals.vision_facts_image_count == 3
    assert totals.vision_request_count == 3
    assert totals.vision_reparse_count == 1
    assert totals.vision_facts_version_regen_count == 1
    reasons = facts.generation_reasons(
        [first.image_id, reparse.image_id, versioned.image_id], IDENTITY
    )
    assert reasons == {}
    event = usage.events()[0]
    assert event.first_image_count == 1
    assert event.reparse_count == 1
    assert event.facts_version_regen_count == 1
    assert event.model == "gpt-5.4-mini"
    raw = (tmp_path / "ai-usage.sqlite3").read_bytes()
    assert b"first.png" not in raw
    assert b"reparse.png" not in raw
    database.close()


def test_fresh_facts_do_not_record_vision_usage(tmp_path):
    database = OCRDatabase(tmp_path / "facts.sqlite3").open()
    images = OCRRepository(database)
    facts = ImageFactsRepository(database)
    recorder, usage = _usage(tmp_path)
    image = add_image(images, tmp_path, "fresh.png")
    facts.upsert_facts(
        image.image_id,
        sample_facts(),
        IDENTITY,
        SourceSnapshot(image.size_bytes, image.mtime_ns, image.quick_fingerprint),
    )
    service = ImageFactsService(
        facts, images, vision=FakeVision(), identity=IDENTITY, usage=recorder
    )
    result = service.index_images([image.image_id])
    assert result.skipped == 1
    assert result.request_count == 0
    assert usage.events() == ()
    assert usage.totals().vision_request_count == 0
    database.close()


def test_search_usage_records_counts_without_query_text(monkeypatch, tmp_path):
    recorder, usage = _usage(tmp_path)
    monkeypatch.setattr("app.ui.images_search.get_usage_recorder", lambda: recorder)
    matcher = _MockRelevance({1})
    provider, candidates = _provider(monkeypatch, tmp_path, 12, matcher)
    provider.search_progressive("secret dog query", tmp_path, candidates)
    totals = usage.totals()
    assert totals.search_query_count == 1
    assert totals.search_candidate_count == 12
    assert totals.search_matcher_image_count == 12
    assert totals.search_text_llm_request_count == 2
    assert totals.search_batch_count == 2
    assert provider.last_coverage["facts_pending_count"] == 0
    assert provider.last_coverage["shortlist_count"] == 12
    raw = (tmp_path / "ai-usage.sqlite3").read_bytes()
    assert b"secret dog query" not in raw
    assert b"1.png" not in raw


def test_search_usage_excludes_pending_facts_from_candidates(monkeypatch, tmp_path):
    recorder, usage = _usage(tmp_path)
    monkeypatch.setattr("app.ui.images_search.get_usage_recorder", lambda: recorder)
    matcher = _MockRelevance({2})
    provider, candidates = _provider(
        monkeypatch, tmp_path, 3, matcher, facts_ids=(2,)
    )
    provider.search_progressive("dog", tmp_path, candidates)
    event = usage.events()[0]
    assert event.candidate_count == 1
    assert event.matcher_image_count == 1
    assert provider.last_coverage["candidate_count"] == 3
    assert provider.last_coverage["facts_pending_count"] == 2
    assert provider.last_coverage["shortlist_count"] == 1
    raw = (tmp_path / "ai-usage.sqlite3").read_bytes()
    assert b"dog" not in raw
