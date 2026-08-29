from __future__ import annotations

import math
import struct

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.embedding import encode_embedding
from app.semantic.models import ModelIdentity, SourceSnapshot
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticSearchService


IDENTITY = ModelIdentity("fake-semantic", "search-v1")
SOURCE = SourceSnapshot(100, 200, "same")


def vector(first: float, second: float = 0.0) -> bytes:
    values = [0.0] * 768
    values[0] = first
    values[1] = second
    return encode_embedding(values)


class QueryWorker:
    def __init__(self, embedding: bytes = vector(1.0)):
        self.embedding = embedding
        self.queries: list[str] = []

    def embed_text(self, text: str):
        self.queries.append(text)
        return self.embedding, IDENTITY


@pytest.fixture
def search_repositories(tmp_path):
    database = OCRDatabase(tmp_path / "search.sqlite3").open()
    images = OCRRepository(database)
    semantic = SemanticRepository(database)
    yield database, images, semantic
    database.close()


def add_embedding(images, semantic, index: int, embedding: bytes):
    image = images.upsert_image(
        rf"D:\Shots\{index}.png",
        size_bytes=SOURCE.size_bytes,
        mtime_ns=SOURCE.mtime_ns,
        quick_fingerprint=SOURCE.quick_fingerprint,
    )
    semantic.upsert_embedding(image.image_id, embedding, IDENTITY, SOURCE)
    return image.image_id


def test_search_embeds_query_and_returns_cosine_similarity_order(search_repositories):
    _, images, semantic = search_repositories
    ids = [
        add_embedding(images, semantic, 1, vector(0.6, 0.8)),
        add_embedding(images, semantic, 2, vector(1.0)),
        add_embedding(images, semantic, 3, vector(-1.0)),
    ]
    worker = QueryWorker()

    results = SemanticSearchService(semantic, images, worker).search("red dialog", 2)

    assert worker.queries == ["red dialog"]
    assert [result.image_id for result in results] == [ids[1], ids[0]]
    assert [result.similarity for result in results] == pytest.approx([1.0, 0.6])


def test_search_template_ensemble_uses_shared_templates_not_query_rules(search_repositories):
    from app.semantic.query_embedding import (
        QUERY_EMBEDDING_TEMPLATE_ENSEMBLE,
        query_texts,
    )

    _, images, semantic = search_repositories
    add_embedding(images, semantic, 1, vector(1.0))
    worker = QueryWorker()
    service = SemanticSearchService(
        semantic, images, worker,
        query_embedding_method=QUERY_EMBEDDING_TEMPLATE_ENSEMBLE,
    )

    service.search("icon", 1)
    assert worker.queries == list(query_texts("icon", QUERY_EMBEDDING_TEMPLATE_ENSEMBLE))
    worker.queries.clear()
    service.search("dog", 1)
    assert worker.queries == list(query_texts("dog", QUERY_EMBEDDING_TEMPLATE_ENSEMBLE))
    assert service.last_search_trace.query_embedding_method == QUERY_EMBEDDING_TEMPLATE_ENSEMBLE
    assert service.last_search_trace.query_text_count == 3
    assert service.last_search_trace.query_identity.model_id == IDENTITY.model_id


def test_search_top_k_boundaries_and_empty_candidates(search_repositories):
    _, images, semantic = search_repositories
    worker = QueryWorker()
    service = SemanticSearchService(semantic, images, worker)

    assert service.search("unused", 0) == []
    assert worker.queries == []
    assert service.search("nothing indexed", 5) == []
    with pytest.raises(ValueError):
        service.search("invalid", -1)

    ids = [
        add_embedding(images, semantic, 1, vector(1.0)),
        add_embedding(images, semantic, 2, vector(0.0, 1.0)),
    ]
    assert [result.image_id for result in service.search("all", 10)] == ids


@pytest.mark.parametrize("limit", [5, 10, 20, 2_147_483_647])
def test_search_respects_developer_result_limits(search_repositories, limit):
    _, images, semantic = search_repositories
    for index in range(25):
        # Distinct decreasing cosine scores preserve an unambiguous ranking.
        angle = index / 100
        add_embedding(images, semantic, index, vector(math.cos(angle), math.sin(angle)))
    results = SemanticSearchService(semantic, images, QueryWorker()).search(
        "desktop", limit
    )
    assert len(results) == min(limit, 25)


def test_search_limit_is_applied_after_folder_filter(search_repositories):
    _, images, semantic = search_repositories
    for folder, count in (("Selected", 7), ("Other", 8)):
        for index in range(count):
            image = images.upsert_image(
                rf"D:\Shots\{folder}\{index}.png",
                size_bytes=SOURCE.size_bytes, mtime_ns=SOURCE.mtime_ns,
                quick_fingerprint=SOURCE.quick_fingerprint,
            )
            semantic.upsert_embedding(image.image_id, vector(1.0), IDENTITY, SOURCE)
    results = SemanticSearchService(semantic, images, QueryWorker()).search(
        "desktop", 5, folder_path=r"D:\Shots\Selected"
    )
    assert len(results) == 5
    assert all(
        images.get_image(result.image_id).folder_path == r"D:\Shots\Selected"
        for result in results
    )


def test_search_skips_corrupt_and_stale_embeddings(search_repositories):
    database, images, semantic = search_repositories
    valid_id = add_embedding(images, semantic, 1, vector(1.0))
    corrupt_id = add_embedding(images, semantic, 2, vector(0.6, 0.8))
    stale_id = add_embedding(images, semantic, 3, vector(1.0))
    corrupt_blob = struct.pack("<f", float("nan")) + vector(1.0)[4:]
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    database.connection.execute(
        "UPDATE semantic_embeddings SET embedding=? WHERE image_id=?",
        (corrupt_blob, corrupt_id),
    )
    database.connection.execute(
        "UPDATE semantic_embeddings SET bundle_version='old' WHERE image_id=?",
        (stale_id,),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")

    service = SemanticSearchService(semantic, images, QueryWorker())
    results = service.search("query", 10)

    assert [result.image_id for result in results] == [valid_id]
    trace = service.last_search_trace
    assert trace is not None
    assert trace.query_identity == IDENTITY
    assert trace.query_embedding_method == "raw"
    assert trace.query_text_count == 1
    assert {identity.bundle_version for identity in trace.candidate_identities} == {
        "search-v1", "old"
    }
    # The corrupt row is rejected by repository decoding before identity
    # filtering; the valid and stale records remain visible to diagnostics.
    assert trace.repository_candidate_count == 2
    assert trace.ready_candidate_count == 1
    assert trace.service_candidate_count == 1
    assert trace.result_count == 1
