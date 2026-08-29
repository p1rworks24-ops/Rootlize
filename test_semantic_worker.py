from __future__ import annotations

import math
import json
import subprocess
import struct
import sys
import threading
import time
import uuid
import zlib
from pathlib import Path

import pytest
from PIL import Image

from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.semantic.embedding import decode_embedding
from app.semantic.image_decode import decode_semantic_image
from app.semantic.models import ModelIdentity, SemanticDiffState, SemanticWorkItem, SourceSnapshot
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticSearchService
from app.semantic.worker_client import SemanticTimeouts, SemanticWorkerClient, SemanticWorkerConfig
from app.semantic.worker_errors import SemanticWorkerCrashedError, SemanticWorkerError
from app.semantic.worker_protocol import command, encode


IDENTITY = ModelIdentity("fake-semantic", "fake-v1", "fake-revision")


def png(path, color="red"):
    Image.new("RGB", (24, 16), color).save(path)
    stat=path.stat()
    return SourceSnapshot(stat.st_size,stat.st_mtime_ns,calculate_quick_fingerprint(path))


def image_snapshot(path, image_format, *, mode="RGB"):
    Image.new(mode, (24, 16), 128 if mode == "L" else (10, 20, 30, 96) if mode == "RGBA" else "red").save(path, format=image_format)
    stat=path.stat()
    return SourceSnapshot(stat.st_size,stat.st_mtime_ns,calculate_quick_fingerprint(path))


def client(*, mode="success", idle=900):
    return SemanticWorkerClient(SemanticWorkerConfig(fake_mode=mode,idle_seconds=idle,timeouts=SemanticTimeouts(stall=2,shutdown=2)))


def test_frozen_client_uses_bundled_semantic_worker_entry(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert SemanticWorkerClient._default_command("Rootlize.exe") == (
        "Rootlize.exe", "--semantic-worker"
    )


def test_source_client_uses_python_module_worker(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert SemanticWorkerClient._default_command("python.exe") == (
        "python.exe", "-m", "app.semantic.worker"
    )


def test_client_lazy_start_ping_status_text_and_shutdown():
    worker=client(); assert worker.state=="worker stopped" and worker.process is None
    assert worker.ping() and worker.get_status()["worker_state"]=="idle"
    loaded=worker.load_model(["text_encoder"])
    assert loaded.get("bundle_validation_ms") == 0.0
    assert loaded.get("onnx_load_ms") == 0.0
    blob,identity=worker.embed_text("夕焼けの海")
    assert identity==IDENTITY and len(decode_embedding(blob))==768
    status=worker.get_status(); assert status["loaded_encoders"]==["text_encoder"]
    worker.shutdown(); assert worker.process is None and worker.state=="worker stopped"


def test_worker_model_missing_and_corrupt(tmp_path):
    missing=client(mode="model-missing")
    with pytest.raises(SemanticWorkerError) as exc: missing.embed_text("hello")
    assert exc.value.code=="MODEL_NOT_INSTALLED"; missing.shutdown()
    bundle=tmp_path/"bundle"; bundle.mkdir(); (bundle/"manifest.json").write_text("{}",encoding="utf-8")
    corrupt=SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=bundle,idle_seconds=0))
    with pytest.raises(SemanticWorkerError) as exc: corrupt.load_model(["image_encoder"])
    assert exc.value.code=="MODEL_CORRUPT"; corrupt.shutdown()


def test_image_events_cancel_and_idle_shutdown(tmp_path):
    items=[]
    for index in range(4):
        path=tmp_path/f"{index}.png"; snapshot=png(path,(index*40,index*20,index*10))
        items.append(SemanticWorkItem(index+1,str(path),snapshot))
    worker=client(mode="slow",idle=.15); cancel=threading.Event(); seen=[]
    for event in worker.analyze(tuple(items),request_id=str(uuid.uuid4()),cancel_event=cancel):
        seen.append(event)
        if event.kind=="item_result": cancel.set()
    # The in-flight image is allowed to complete after cancel is requested.
    assert 1 <= sum(event.kind=="item_result" for event in seen) < len(items) and cancel.is_set()
    time.sleep(.3); assert worker.process is None


@pytest.mark.parametrize(
    ("filename", "image_format", "mode"),
    [
        ("normal.png", "PNG", "RGB"),
        ("normal.jpeg", "JPEG", "RGB"),
        ("jpeg-named-png.png", "JPEG", "RGB"),
        ("normal.jpg", "JPEG", "RGB"),
        ("normal.webp", "WEBP", "RGB"),
        ("normal.bmp", "BMP", "RGB"),
        ("alpha.png", "PNG", "RGBA"),
        ("grayscale.png", "PNG", "L"),
    ],
)
def test_worker_decodes_supported_images_by_content_and_emits_3072_bytes(
    tmp_path, filename, image_format, mode
):
    path = tmp_path / filename
    snapshot = image_snapshot(path, image_format, mode=mode)
    worker = client()
    events = list(
        worker.analyze(
            (SemanticWorkItem(1, str(path), snapshot),),
            request_id=str(uuid.uuid4()),
            cancel_event=threading.Event(),
        )
    )
    results = [event for event in events if event.kind == "item_result"]
    assert len(results) == 1
    assert results[0].embedding is not None
    assert len(results[0].embedding) == 3072
    assert len(decode_embedding(results[0].embedding)) == 768
    worker.shutdown()


def test_worker_accepts_repository_snapshot_without_optional_fingerprint(tmp_path):
    path = tmp_path / "jpeg-named-png.png"
    snapshot = image_snapshot(path, "JPEG")
    incomplete = SourceSnapshot(snapshot.size_bytes, snapshot.mtime_ns, None)
    worker = client()
    events = list(
        worker.analyze(
            (SemanticWorkItem(1, str(path), incomplete),),
            request_id=str(uuid.uuid4()),
            cancel_event=threading.Event(),
        )
    )
    results = [event for event in events if event.kind == "item_result"]
    assert len(results) == 1
    assert results[0].source_snapshot == incomplete
    assert results[0].embedding is not None and len(results[0].embedding) == 3072
    worker.shutdown()


@pytest.mark.parametrize("data", [b"not an image", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_worker_rejects_corrupt_or_invalid_image_without_crashing(tmp_path, data):
    path = tmp_path / "broken.jpg"
    path.write_bytes(data)
    stat = path.stat()
    snapshot = SourceSnapshot(stat.st_size, stat.st_mtime_ns, calculate_quick_fingerprint(path))
    worker = client()
    events = list(
        worker.analyze(
            (SemanticWorkItem(1, str(path), snapshot),),
            request_id=str(uuid.uuid4()),
            cancel_event=threading.Event(),
        )
    )
    errors = [event for event in events if event.kind == "item_error"]
    assert len(errors) == 1 and errors[0].error_code == "UNSUPPORTED_IMAGE"
    assert worker.ping()
    worker.shutdown()


def test_decoder_applies_jpeg_exif_orientation_and_normalizes_rgb(tmp_path):
    path = tmp_path / "oriented.bin"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("L", (10, 20), 128).save(path, format="JPEG", exif=exif)
    with decode_semantic_image(path) as decoded:
        assert decoded.size == (20, 10)
        assert decoded.mode == "RGB"


def test_worker_rejects_unsupported_decodable_format(tmp_path):
    path = tmp_path / "unsupported.png"
    Image.new("RGB", (8, 8), "red").save(path, format="GIF")
    snapshot = SourceSnapshot(path.stat().st_size, path.stat().st_mtime_ns, calculate_quick_fingerprint(path))
    worker = client()
    events = list(worker.analyze((SemanticWorkItem(1, str(path), snapshot),), request_id=str(uuid.uuid4()), cancel_event=threading.Event()))
    assert [event.error_code for event in events if event.kind == "item_error"] == ["UNSUPPORTED_IMAGE"]
    assert worker.ping()
    worker.shutdown()


def test_worker_rejects_image_over_existing_pixel_limit_before_decode(tmp_path):
    path = tmp_path / "huge.jpg"
    ihdr = struct.pack(">IIBBBBB", 10_001, 10_000, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", zlib.crc32(chunk)))
    snapshot = SourceSnapshot(path.stat().st_size, path.stat().st_mtime_ns, calculate_quick_fingerprint(path))
    worker = client()
    events = list(worker.analyze((SemanticWorkItem(1, str(path), snapshot),), request_id=str(uuid.uuid4()), cancel_event=threading.Event()))
    assert [event.error_code for event in events if event.kind == "item_error"] == ["UNSUPPORTED_IMAGE"]
    assert worker.ping()
    worker.shutdown()


def test_crash_isolated_and_committed_result_survives(tmp_path):
    database=OCRDatabase(tmp_path/"db.sqlite3").open(); images=OCRRepository(database); semantic=SemanticRepository(database)
    ids=[]
    for index in range(2):
        path=tmp_path/f"crash{index}.png"; snap=png(path,"blue")
        ids.append(images.upsert_image(str(path),size_bytes=snap.size_bytes,mtime_ns=snap.mtime_ns,quick_fingerprint=snap.quick_fingerprint).image_id)
    worker=client(mode="crash-after-one"); service=SemanticSearchService(semantic,images,worker)
    with pytest.raises(SemanticWorkerCrashedError): service.analyze(ids,IDENTITY)
    assert semantic.get_embedding(ids[0]) is not None and semantic.get_embedding(ids[1]) is None and database.quick_check()=="ok"
    worker.terminate(); database.close()


def test_service_real_ipc_persistence_reuse_and_stale(tmp_path):
    database=OCRDatabase(tmp_path/"db.sqlite3").open(); images=OCRRepository(database); semantic=SemanticRepository(database)
    paths=[]; ids=[]
    for index,color in enumerate(("green","yellow")):
        path=tmp_path/f"save{index}.png"; snap=png(path,color); paths.append(path)
        ids.append(images.upsert_image(str(path),size_bytes=snap.size_bytes,mtime_ns=snap.mtime_ns,quick_fingerprint=snap.quick_fingerprint).image_id)
    worker=client(); service=SemanticSearchService(semantic,images,worker)
    first=service.analyze(ids,IDENTITY); assert first.succeeded==2
    saved=semantic.get_embedding(ids[0]); assert saved and math.isclose(sum(x*x for x in decode_embedding(saved.embedding)),1,abs_tol=1e-3)
    second=service.analyze(ids,IDENTITY); assert second.total==0
    stale_identity=ModelIdentity("fake-semantic","fake-v2","fake-revision")
    assert semantic.classify_embeddings(ids,stale_identity)[ids[0]]==SemanticDiffState.STALE_MODEL
    worker.shutdown(); worker=client(mode="fake-v2"); service=SemanticSearchService(semantic,images,worker)
    third=service.analyze(ids,stale_identity); assert third.succeeded==2 and semantic.get_embedding(ids[0]).identity==stale_identity
    worker.shutdown(); database.close()


def test_unknown_command_is_rejected(tmp_path):
    process=subprocess.Popen([sys.executable,"-m","app.semantic.worker","--fake-mode","success"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
    request_id=str(uuid.uuid4())
    data={"protocol_version":1,"type":"command","request_id":request_id,"command":"execute","payload":{}}
    process.stdin.write(encode(data)); process.stdin.flush(); result=json.loads(process.stdout.readline())
    assert result["status"]=="error" and result["error"]["code"]=="INVALID_REQUEST"
    shutdown_id,shutdown=command("shutdown"); process.stdin.write(encode(shutdown)); process.stdin.flush()
    assert json.loads(process.stdout.readline())["request_id"]==shutdown_id
    process.wait(timeout=3)


def test_run_capixe_launcher_uses_build_venv():
    text = Path(__file__).resolve().parent.joinpath("Run Capixe.bat").read_text(encoding="utf-8")
    assert 'APP_PYTHON=%PROJECT_DIR%.build-venv\\Scripts\\python.exe' in text
    assert 'APP_PYTHON=%PROJECT_DIR%venv\\Scripts\\python.exe' not in text


def test_missing_runtime_module_becomes_runtime_not_installed():
    script = (
        "import sys;"
        "sys.stderr.write(\"ModuleNotFoundError: No module named 'numpy'\\n\");"
        "sys.exit(1)"
    )
    worker = SemanticWorkerClient(SemanticWorkerConfig(
        command=(sys.executable, "-c", script),
        idle_seconds=0,
        timeouts=SemanticTimeouts(start=3, ping=1, shutdown=2),
    ))
    try:
        with pytest.raises(SemanticWorkerError) as exc:
            worker.embed_text("cat")
        assert exc.value.code == "MODEL_LOAD_FAILED"
        assert "Semantic runtime is not installed." in str(exc.value)
        assert not isinstance(exc.value, SemanticWorkerCrashedError)
    finally:
        worker.terminate()


def test_worker_crash_logs_stderr_without_secrets(monkeypatch):
    import app.semantic.worker_client as module

    logged = []
    monkeypatch.setattr(
        module.logger, "error", lambda *args, **kwargs: logged.append(args)
    )
    script = (
        "import sys;"
        "sys.stderr.write('OPENAI_API_KEY=sk-secretvalue123456\\n');"
        "sys.stderr.write(\"ModuleNotFoundError: No module named 'onnxruntime'\\n\");"
        "sys.exit(1)"
    )
    worker = SemanticWorkerClient(SemanticWorkerConfig(
        command=(sys.executable, "-c", script),
        idle_seconds=0,
        timeouts=SemanticTimeouts(start=3, ping=1, shutdown=2),
    ))
    try:
        with pytest.raises(SemanticWorkerError):
            worker.ping()
    finally:
        worker.terminate()
    blob = " ".join(str(item) for row in logged for item in row)
    assert "onnxruntime" in blob
    assert "sk-secretvalue123456" not in blob
    assert "OPENAI_API_KEY=***" in blob or "sk-***" in blob
