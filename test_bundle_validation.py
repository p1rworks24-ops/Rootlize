"""Process-wide OpenCLIP integrity: one full SHA-256 per path, off the UI thread."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.paths import set_path_overrides
from app.semantic.bundle import (
    bundle_full_validation_count,
    load_bundle,
)
from app.semantic.catalog import (
    MODEL_IDS,
    OPENCLIP_BUNDLE_VERSION,
    OPENCLIP_MODEL_KEY,
    OPENCLIP_PIPELINE_VERSION,
    OPENCLIP_REVISION,
)
from app.semantic.installer import (
    product_bundle_ui_state,
    resolve_semantic_bundle,
    start_product_bundle_warmup,
)
from app.semantic.worker_errors import ModelCorruptError
from app.ui.images_content_search_setup import ImageContentSearchSetup


def _write_tiny_openclip_bundle(root: Path, *, token: bytes = b"openclip") -> Path:
    files = {
        "image_encoder.onnx": token + b"-image",
        "text_encoder.onnx": token + b"-text",
        "bpe_simple_vocab_16e6.txt.gz": token + b"-bpe",
        "open_clip_config.json": b"{}",
        "preprocessor_config.json": b"{}",
        "OPEN_CLIP_LICENSE.txt": b"MIT license text",
        "NOTICE.txt": b"model notice",
    }
    roles = {
        "image_encoder.onnx": "image_encoder",
        "text_encoder.onnx": "text_encoder",
        "bpe_simple_vocab_16e6.txt.gz": "tokenizer",
        "open_clip_config.json": "model_config",
        "preprocessor_config.json": "preprocess_config",
        "OPEN_CLIP_LICENSE.txt": "license",
        "NOTICE.txt": "notice",
    }
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, payload in files.items():
        (root / name).write_bytes(payload)
        entries.append(
            {
                "role": roles[name],
                "path": name,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "manifest_schema_version": 1,
        "bundle_version": OPENCLIP_BUNDLE_VERSION,
        "model_id": MODEL_IDS[OPENCLIP_MODEL_KEY],
        "revision": OPENCLIP_REVISION,
        "embedding": {"dimension": 512, "dtype": "float32", "normalized": True},
        "image": {"width": 224, "height": 224},
        "text": {"max_length": 77},
        "runtime": {
            "name": "onnxruntime",
            "minimum_version": "1.28.0",
            "providers": ["CPUExecutionProvider"],
        },
        "pipeline_version": OPENCLIP_PIPELINE_VERSION,
        "files": entries,
        "total_size_bytes": sum(item["size_bytes"] for item in entries),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root


def _file_count(root: Path) -> int:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return len(manifest["files"])


def test_load_bundle_full_hash_once_per_process(tmp_path, monkeypatch):
    root = _write_tiny_openclip_bundle(tmp_path / "bundle")
    calls = {"n": 0}
    orig = __import__("app.semantic.bundle", fromlist=["_sha256"])._sha256

    def spy(path):
        calls["n"] += 1
        return orig(path)

    monkeypatch.setattr("app.semantic.bundle._sha256", spy)
    first = load_bundle(root)
    second = load_bundle(root)
    assert first.identity.model_id == second.identity.model_id
    assert calls["n"] == _file_count(root)
    assert bundle_full_validation_count() == 1


def test_use_cache_false_rehashes(tmp_path, monkeypatch):
    root = _write_tiny_openclip_bundle(tmp_path / "bundle")
    calls = {"n": 0}
    orig = __import__("app.semantic.bundle", fromlist=["_sha256"])._sha256

    def spy(path):
        calls["n"] += 1
        return orig(path)

    monkeypatch.setattr("app.semantic.bundle._sha256", spy)
    load_bundle(root)
    load_bundle(root, use_cache=False)
    assert calls["n"] == _file_count(root) * 2
    assert bundle_full_validation_count() == 2


def test_concurrent_load_bundle_hashes_once(tmp_path, monkeypatch):
    root = _write_tiny_openclip_bundle(tmp_path / "bundle")
    calls = {"n": 0}
    lock = threading.Lock()
    orig = __import__("app.semantic.bundle", fromlist=["_sha256"])._sha256

    def spy(path):
        with lock:
            calls["n"] += 1
        time.sleep(0.01)
        return orig(path)

    monkeypatch.setattr("app.semantic.bundle._sha256", spy)
    results = []
    errors = []

    def worker():
        try:
            results.append(load_bundle(root))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(results) == 4
    assert calls["n"] == _file_count(root)
    assert bundle_full_validation_count() == 1


def test_corrupt_bundle_is_cached_and_not_rehashed(tmp_path, monkeypatch):
    root = _write_tiny_openclip_bundle(tmp_path / "bundle")
    payload = (root / "image_encoder.onnx").read_bytes()
    (root / "image_encoder.onnx").write_bytes(b"x" * len(payload))
    calls = {"n": 0}
    orig = __import__("app.semantic.bundle", fromlist=["_sha256"])._sha256

    def spy(path):
        calls["n"] += 1
        return orig(path)

    monkeypatch.setattr("app.semantic.bundle._sha256", spy)
    with pytest.raises(ModelCorruptError):
        load_bundle(root)
    hashed = calls["n"]
    assert hashed >= 1
    with pytest.raises(ModelCorruptError):
        load_bundle(root)
    assert calls["n"] == hashed
    assert bundle_full_validation_count() == 1


def test_setup_construct_does_not_hash_on_gui_thread(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    sha_threads: list[int] = []
    orig = __import__("app.semantic.bundle", fromlist=["_sha256"])._sha256

    def spy(path):
        sha_threads.append(threading.get_ident())
        return orig(path)

    monkeypatch.setattr("app.semantic.bundle._sha256", spy)
    gui = threading.get_ident()
    widget = ImageContentSearchSetup(model_key=OPENCLIP_MODEL_KEY)
    assert widget.isHidden()
    assert gui not in sha_threads
    deadline = time.time() + 3
    while product_bundle_ui_state(OPENCLIP_MODEL_KEY) == "pending" and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert product_bundle_ui_state(OPENCLIP_MODEL_KEY) == "ready"
    assert gui not in sha_threads
    assert bundle_full_validation_count() == 1
    resolve_semantic_bundle(OPENCLIP_MODEL_KEY)
    assert bundle_full_validation_count() == 1
    widget.close()


def test_setup_recovery_after_corrupt_bundled_validation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    bundled = _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    (bundled / "image_encoder.onnx").write_bytes(b"tampered")
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    widget = ImageContentSearchSetup(model_key=OPENCLIP_MODEL_KEY)
    assert widget.isHidden()
    deadline = time.time() + 3
    while product_bundle_ui_state(OPENCLIP_MODEL_KEY) == "pending" and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    widget.refresh()
    assert product_bundle_ui_state(OPENCLIP_MODEL_KEY) == "unavailable"
    assert widget.isVisible()
    assert widget._label.text() == "Meaning search needs a one-time setup."
    widget.close()


def test_warmup_is_idempotent(tmp_path, monkeypatch):
    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    seen = []

    def on_done(bundle, error):
        seen.append((bundle is not None, error))

    start_product_bundle_warmup(OPENCLIP_MODEL_KEY, on_done=on_done)
    start_product_bundle_warmup(OPENCLIP_MODEL_KEY, on_done=on_done)
    deadline = time.time() + 3
    while len(seen) < 2 and time.time() < deadline:
        time.sleep(0.02)
    assert len(seen) == 2
    assert all(ok and error is None for ok, error in seen)
    assert bundle_full_validation_count() == 1


def test_meaning_preparing_copy_exists():
    from app.i18n import t

    assert t("images.meaning.preparing") == "Preparing Meaning Search…"
    assert "Meaning Search" in t("images.meaning.preparing")
