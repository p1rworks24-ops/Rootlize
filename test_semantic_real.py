"""Opt-in real SigLIP 2 contract/integration tests (model files stay untracked)."""

from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.semantic.embedding import decode_embedding
from app.semantic.models import ModelIdentity, SemanticWorkItem, SourceSnapshot
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticSearchService
from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig
from app.search.hybrid_service import HybridSearchService

BUNDLE=Path(os.environ.get("CAPIXE_SEMANTIC_TEST_BUNDLE", ""))
RUNTIME=Path(os.environ.get("CAPIXE_SEMANTIC_TEST_PYTHON", ""))
PYTHON_PACKAGES=Path(os.environ.get("CAPIXE_SEMANTIC_TEST_PYTHON_PACKAGES", ""))
IMAGES=Path(os.environ.get("CAPIXE_SEMANTIC_TEST_IMAGES", ""))
pytestmark=pytest.mark.skipif(not (BUNDLE/"manifest.json").is_file() or not RUNTIME.is_file(),reason="real Semantic bundle/runtime not configured")


def make_client():
    paths=(PYTHON_PACKAGES,) if PYTHON_PACKAGES.is_dir() else ()
    return SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=BUNDLE,python_executable=RUNTIME,python_paths=paths,idle_seconds=0))


def assert_embedding(blob):
    values=decode_embedding(blob); assert len(values)==768 and all(math.isfinite(x) for x in values)
    assert math.isclose(sum(x*x for x in values),1.0,abs_tol=1e-3)


def test_real_japanese_english_and_two_image_embeddings(tmp_path):
    worker=make_client()
    for query in ("夕焼けの海の写真", "a screenshot of a desktop application"):
        blob,identity=worker.embed_text(query); assert_embedding(blob); assert identity.dimension==768
    for name in ("photo.png","screenshot.png"):
        path=IMAGES/name; stat=path.stat(); snapshot=SourceSnapshot(stat.st_size,stat.st_mtime_ns,calculate_quick_fingerprint(path))
        blob,_identity=worker.embed_image(SemanticWorkItem(1,str(path),snapshot)); assert_embedding(blob)
    worker.shutdown()


def test_real_worker_service_repository_round_trip_and_reuse(tmp_path):
    worker=make_client(); status=worker.load_model(["image_encoder"]); model=status["model_identity"]
    identity=ModelIdentity(model["model_id"],model["bundle_version"],model["model_revision"],model["pipeline_version"],model["embedding_format_version"],model["dimension"])
    database=OCRDatabase(tmp_path/"real.sqlite3").open(); images=OCRRepository(database); semantic=SemanticRepository(database)
    path=IMAGES/"screenshot.png"; stat=path.stat(); fingerprint=calculate_quick_fingerprint(path)
    image=images.upsert_image(str(path),size_bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,quick_fingerprint=fingerprint)
    service=SemanticSearchService(semantic,images,worker); result=service.analyze([image.image_id],identity)
    assert result.succeeded==1; record=semantic.get_embedding(image.image_id); assert record is not None; assert_embedding(record.embedding)
    assert service.analyze([image.image_id],identity).total==0
    worker.shutdown(); database.close()


@pytest.mark.parametrize(
    ("filename", "image_format", "mode"),
    [
        ("actual.png", "PNG", "RGBA"),
        ("actual.jpeg", "JPEG", "RGB"),
        ("jpeg-named-png.png", "JPEG", "RGB"),
        ("actual.jpg", "JPEG", "L"),
        ("actual.webp", "WEBP", "RGB"),
        ("actual.bmp", "BMP", "RGB"),
    ],
)
def test_real_image_encoder_accepts_supported_content_formats(tmp_path, filename, image_format, mode):
    path = tmp_path / filename
    color = 128 if mode == "L" else (20, 40, 60, 96) if mode == "RGBA" else (20, 40, 60)
    Image.new(mode, (32, 24), color).save(path, format=image_format)
    stat = path.stat()
    snapshot = SourceSnapshot(stat.st_size, stat.st_mtime_ns, calculate_quick_fingerprint(path))
    worker = make_client()
    blob, identity = worker.embed_image(SemanticWorkItem(1, str(path), snapshot))
    assert len(blob) == 3072
    assert identity.dimension == 768
    assert_embedding(blob)
    worker.shutdown()


def test_real_analyze_persists_repairs_reuses_and_hybrid_searches_images(tmp_path):
    """Real Images Analyze -> SQLite -> normal Hybrid Search regression."""
    source_images = {
        "capture_001.png": IMAGES / "screenshot.png",
        "capture_002.jpg": (
            Path(__file__).parent / "tools" / "semantic_search_benchmark" /
            "data" / "images" / "commons_048.jpg"
        ),
        "capture_003.png": Path(__file__).parent / "website" / "assets" /
            "screenshots" / "images-search.png",
        "capture_004.png": IMAGES / "photo.png",
    }
    folder = tmp_path / "selected"
    other_folder = tmp_path / "other"
    folder.mkdir()
    other_folder.mkdir()
    for name, source in source_images.items():
        shutil.copy2(source, folder / name)
    shutil.copy2(IMAGES / "photo.png", other_folder / "outside.png")

    database_path = tmp_path / "real-e2e.sqlite3"
    database = OCRDatabase(database_path).open()
    images = OCRRepository(database)
    ids = {}
    for path in tuple(folder.iterdir()) + tuple(other_folder.iterdir()):
        stat = path.stat()
        image = images.upsert_image(
            path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
            quick_fingerprint=calculate_quick_fingerprint(path),
        )
        # Deliberately unrelated OCR proves semantic-only matches.
        images.save_ocr_document(
            image.image_id, status="ready", ocr_text="reference code zeta 4815"
        )
        ids[path.name] = image.image_id

    worker = make_client()
    status = worker.load_model(["image_encoder"])
    raw_identity = status["model_identity"]
    identity = ModelIdentity(
        raw_identity["model_id"], raw_identity["bundle_version"],
        raw_identity["model_revision"], raw_identity["pipeline_version"],
        raw_identity["embedding_format_version"], raw_identity["dimension"],
    )
    semantic = SemanticRepository(database)
    service = SemanticSearchService(semantic, images, worker)

    selected_ids = [ids[name] for name in source_images]
    initial = service.analyze(selected_ids, identity)
    assert (initial.total, initial.succeeded, initial.failed) == (4, 4, 0)
    assert len(semantic.list_embeddings(folder_path=str(folder))) == 4

    # Missing, stale, and corrupt persisted values must all be repaired.
    semantic.delete_embedding(ids["capture_001.png"])
    database.connection.execute(
        "UPDATE semantic_embeddings SET bundle_version='stale' WHERE image_id=?",
        (ids["capture_002.jpg"],),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=ON")
    database.connection.execute(
        "UPDATE semantic_embeddings SET embedding=? WHERE image_id=?",
        (b"corrupt", ids["capture_003.png"]),
    )
    database.connection.execute("PRAGMA ignore_check_constraints=OFF")
    repaired = service.analyze(selected_ids, identity)
    assert (repaired.total, repaired.succeeded, repaired.failed) == (3, 3, 0)
    assert all(
        state.value == "unchanged"
        for state in semantic.classify_embeddings(selected_ids, identity).values()
    )
    worker.shutdown()
    database.close()

    # A fresh DB connection and worker model the app after restart. Analyze
    # must reuse all rows; normal Hybrid Search must return semantic-only hits.
    database = OCRDatabase(database_path).open()
    images = OCRRepository(database)
    semantic = SemanticRepository(database)
    worker = make_client()
    service = SemanticSearchService(semantic, images, worker)
    assert service.analyze(selected_ids, identity).total == 0
    hybrid = HybridSearchService(images, service, images)

    cases = (
        ("Windows desktop with a code editor", "capture_001.png"),
        ("Windowsのデスクトップ", "capture_001.png"),
        ("a person cooking a meal", "capture_002.jpg"),
        ("料理をしている人", "capture_002.jpg"),
        ("a screenshot of an image search application", "capture_003.png"),
        ("画像を検索するアプリの画面", "capture_003.png"),
    )
    observed = {}
    for query, expected_name in cases:
        page = hybrid.search(query, 4, folder_path=folder)
        names = [Path(result.path).name for result in page.results]
        observed[query] = names
        # Small real-image sets are deliberately heterogeneous; semantic-only
        # presence is the integration contract, while model quality is tracked
        # separately by the benchmark suite.
        assert expected_name in names, (query, names)
        assert all(Path(result.path).parent == folder for result in page.results)
        assert all(result.text_rank is None for result in page.results)

    class FailedSemantic:
        def search(self, *_args, **_kwargs):
            raise RuntimeError("simulated semantic failure")

    fallback = HybridSearchService(images, FailedSemantic(), images).search(
        "zeta 4815", 10, folder_path=folder
    )
    assert fallback.semantic_failed
    assert len(fallback.results) == 4
    assert len(semantic.list_embeddings(folder_path=str(folder))) == 4
    worker.shutdown()
    database.close()
