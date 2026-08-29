"""Installed Semantic model -> Hybrid search -> Images UI integration."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.paths import get_local_app_data_dir
from app.semantic.embedding import encode_embedding
from app.semantic.models import ModelIdentity, SourceSnapshot
from app.semantic.repository import SemanticRepository
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


IDENTITY = ModelIdentity("installed-test-model", "current")


def _vector(index):
    values = [0.0] * 768
    values[index] = 1.0
    return encode_embedding(values)


class JapaneseQueryWorker:
    queries = []

    def __init__(self, _config): pass
    def embed_text(self, text):
        self.queries.append(text)
        return _vector(0), IDENTITY
    def shutdown(self): pass


def test_japanese_semantic_only_result_survives_hybrid_and_reaches_images_ui(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Selected"
    folder.mkdir()
    image_path = folder / "desktop.png"
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(image_path), "PNG")

    database_path = get_local_app_data_dir() / "ocr-index.sqlite3"
    database_path.parent.mkdir(parents=True)
    database = OCRDatabase(database_path).open()
    images = OCRRepository(database)
    stat = image_path.stat()
    record = images.upsert_image(
        image_path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns
    )
    images.save_ocr_document(record.image_id, status="ready", ocr_text="")
    SemanticRepository(database).upsert_embedding(
        record.image_id, _vector(0), IDENTITY,
        SourceSnapshot(stat.st_size, stat.st_mtime_ns, None),
    )
    database.close()

    import app.ui.images_search as images_search
    monkeypatch.setattr(images_search, "_installed_semantic_bundle", lambda: tmp_path / "installed-model")
    monkeypatch.setattr(images_search, "SemanticWorkerClient", JapaneseQueryWorker)
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda _value: None)
    JapaneseQueryWorker.queries = []

    config = {
        "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
        "current_folder": "Capture", "save_folder": "Capture",
    }
    page = ImagesPage(
        config, MetadataService(), ThumbnailCache(size=48), tmp_path,
        semantic_search_provider=lambda *_args: (),
    )
    page.show()
    app.processEvents()
    page._search_mode_combo.setCurrentIndex(page._search_mode_combo.findData("hybrid"))
    page._search_input.setText("Windowsのデスクトップ")
    page._on_search()
    elapsed = 0
    while page._search_tasks and elapsed < 3000:
        QTest.qWait(20)
        elapsed += 20

    assert JapaneseQueryWorker.queries == ["Windowsのデスクトップ"]
    assert page._list_widget.count() == 1
    assert Path(page._list_widget.item(0).data(Qt.UserRole)).name == "desktop.png"
    page.close()
