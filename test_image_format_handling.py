from __future__ import annotations

from pathlib import Path
import struct

import pytest
from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.scanner import scan_folder
from app.ocr.worker_process import FakeEngine, process_request
from app.ocr.worker_protocol import OCRWorkerRequest
from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.semantic.models import ModelIdentity, SourceSnapshot
from app.semantic.repository import SemanticRepository
from app.semantic.image_decode import decode_semantic_image


def _request(path: Path) -> OCRWorkerRequest:
    stat = path.stat()
    return OCRWorkerRequest(
        "request", str(path), stat.st_size, stat.st_mtime_ns,
        calculate_quick_fingerprint(path), {},
    )


def _write_encoded(path: Path, image_format: str) -> Path:
    Image.new("RGB", (24, 12), "white").save(path, format=image_format)
    return path


@pytest.mark.parametrize(
    ("filename", "encoded_format"),
    [
        ("normal.png", "PNG"),
        ("normal.jpg", "JPEG"),
        ("jpeg-as-png.png", "JPEG"),
        ("png-as-jpeg.jpg", "PNG"),
    ],
)
def test_thumbnail_semantic_and_ocr_decode_by_content(tmp_path, filename, encoded_format):
    QApplication.instance() or QApplication([])
    path = _write_encoded(tmp_path / filename, encoded_format)

    assert not QPixmap(str(path)).isNull()
    semantic = decode_semantic_image(path)
    try:
        assert semantic.size == (24, 12)
    finally:
        semantic.close()
    result = process_request(FakeEngine("success"), _request(path))
    assert result.success


@pytest.mark.parametrize(
    ("filename", "prefix"),
    [("corrupt.jpg", b"\xff\xd8\xffbroken"), ("corrupt.png", b"\x89PNG\r\n\x1a\nbroken")],
)
def test_corrupt_supported_images_are_reported_not_indexed(tmp_path, filename, prefix):
    path = tmp_path / filename
    path.write_bytes(prefix)
    scan = scan_folder(tmp_path)
    item = next(value for value in scan.items if value.filename == filename)
    assert item.read_success is False
    result = process_request(FakeEngine("success"), _request(path))
    assert result.success is False
    assert result.error_type == "image_decode_failed"


def test_scanner_indexes_every_decodable_supported_image(tmp_path):
    for index in range(99):
        _write_encoded(tmp_path / f"{index:03}.png", "JPEG" if index == 98 else "PNG")
    scan = scan_folder(tmp_path)
    assert len(scan.items) == 99
    assert sum(item.read_success for item in scan.items) == 99


def test_queue_ocr_retry_preserves_semantic_embedding(tmp_path):
    path = _write_encoded(tmp_path / "image.jpg", "JPEG")
    stat = path.stat()
    database = OCRDatabase(tmp_path / "index.sqlite3").open()
    try:
        images = OCRRepository(database)
        image = images.upsert_image(path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        images.save_ocr_document(image.image_id, status="failed", error_type="ocr_failed")
        identity = ModelIdentity("model", "1", "rev", 1, 1, 512)
        source = SourceSnapshot(stat.st_size, stat.st_mtime_ns, None)
        embedding = struct.pack("<512f", 1.0, *([0.0] * 511))
        SemanticRepository(database).upsert_embedding(image.image_id, embedding, identity, source)

        assert images.queue_ocr_retry([image.image_id]) == 1
        assert images.get_ocr_document(image.image_id).status == "pending"
        assert SemanticRepository(database).get_embedding(image.image_id) is not None
    finally:
        database.close()
