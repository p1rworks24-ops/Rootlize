from pathlib import Path

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.bundle import load_bundle
from app.semantic.models import ModelIdentity, SemanticDiffState
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticAnalysisService, SemanticSearchService
from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "release" / "semantic-model-openclip-v1"
IMAGE = ROOT / "screenshots" / "20260713_191111.png"


def test_openclip_real_image_db_search_and_siglip_rollback_stale(tmp_path):
    bundle = load_bundle(BUNDLE)
    assert bundle.identity.dimension == 512
    database = OCRDatabase(tmp_path / "integration.sqlite3").open()
    worker = SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=BUNDLE))
    try:
        images = OCRRepository(database)
        stat = IMAGE.stat()
        image = images.upsert_image(IMAGE, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        repository = SemanticRepository(database)
        result = SemanticAnalysisService(repository, images, worker).analyze((image.image_id,), bundle.identity)
        assert (result.state, result.succeeded, result.failed) == ("completed", 1, 0)
        stored = repository.get_embedding(image.image_id)
        assert stored is not None and stored.dimension == 512 and stored.identity == bundle.identity
        ranked = SemanticSearchService(repository, images, worker).search("Windows desktop", 20)
        assert ranked and ranked[0].image_id == image.image_id

        siglip = ModelIdentity("siglip2-base-patch16-224", "1", "siglip-revision", 1, dimension=768)
        assert repository.classify_embeddings((image.image_id,), siglip)[image.image_id] == SemanticDiffState.STALE_MODEL
        assert repository.classify_embeddings((image.image_id,), bundle.identity)[image.image_id] == SemanticDiffState.UNCHANGED
    finally:
        worker.shutdown()
        database.close()
