from __future__ import annotations

import hashlib
import io
import json
import threading
from pathlib import Path

import pytest

from app.semantic.installer import BundleInstaller, find_installed_bundle, resolve_semantic_bundle
from app.semantic.worker_errors import ModelCorruptError


class MemorySource:
    def __init__(self, *, version="1", bad_data=False):
        self.bundle_version = version
        self.data = b"license text"
        self.bad_data = bad_data
        self.opens = 0
        self._manifest = {
            "manifest_schema_version": 1,
            "bundle_version": version,
            "model_id": "test-model",
            "revision": "test-revision",
            "embedding": {"dimension": 768, "dtype": "float32", "normalized": True},
            "image": {"width": 224, "height": 224},
            "text": {"max_length": 64},
            "runtime": {"name": "onnxruntime", "minimum_version": "1.28.0", "providers": ["CPUExecutionProvider"]},
            "pipeline_version": 1,
            "files": [{"role": "license", "path": "LICENSE.txt", "size_bytes": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}],
            "total_size_bytes": len(self.data),
        }

    def manifest(self):
        return json.loads(json.dumps(self._manifest))

    def open_file(self, _entry):
        self.opens += 1
        return io.BytesIO(b"broken" if self.bad_data else self.data)


def test_optional_bundle_installs_validates_and_is_reused_after_restart(tmp_path: Path):
    source = MemorySource()
    progress = []
    installed = BundleInstaller(source, tmp_path).install(on_progress=progress.append)
    assert installed.identity.bundle_version == "1"
    assert progress[-1].downloaded_bytes == len(source.data)
    assert find_installed_bundle(tmp_path).root == tmp_path / "1"

    BundleInstaller(source, tmp_path).install()
    assert source.opens == 1


def test_hash_or_size_failure_never_activates_partial_bundle_and_can_retry(tmp_path: Path):
    broken = MemorySource(bad_data=True)
    with pytest.raises(ModelCorruptError):
        BundleInstaller(broken, tmp_path).install()
    assert find_installed_bundle(tmp_path) is None
    assert not list(tmp_path.glob(".installing-*"))

    repaired = MemorySource()
    assert BundleInstaller(repaired, tmp_path).install().root == tmp_path / "1"


def test_cancel_removes_incomplete_bundle(tmp_path: Path):
    cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        BundleInstaller(MemorySource(), tmp_path).install(cancel_event=cancel)
    assert find_installed_bundle(tmp_path) is None


def test_requested_model_version_does_not_use_stale_valid_bundle(tmp_path: Path):
    BundleInstaller(MemorySource(version="1"), tmp_path).install()
    assert find_installed_bundle(tmp_path, bundle_version="2") is None
    BundleInstaller(MemorySource(version="2"), tmp_path).install()
    assert find_installed_bundle(tmp_path, bundle_version="2").identity.bundle_version == "2"


def _write_tiny_openclip_bundle(root: Path, *, token: bytes = b"openclip") -> Path:
    from app.semantic.catalog import (
        MODEL_IDS,
        OPENCLIP_BUNDLE_VERSION,
        OPENCLIP_MODEL_KEY,
        OPENCLIP_PIPELINE_VERSION,
        OPENCLIP_REVISION,
    )

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


def test_product_resolution_prefers_bundled_resource_over_localappdata(tmp_path, monkeypatch):
    from app.paths import set_path_overrides
    from app.semantic.catalog import OPENCLIP_BUNDLE_VERSION, OPENCLIP_MODEL_KEY

    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    bundled = _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION,
        token=b"bundled",
    )
    local_bundle = _write_tiny_openclip_bundle(
        local / "semantic-models" / OPENCLIP_BUNDLE_VERSION,
        token=b"localapp",
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    found = resolve_semantic_bundle(OPENCLIP_MODEL_KEY)
    assert found is not None
    assert found.root.resolve() == bundled.resolve()
    assert found.root.resolve() != local_bundle.resolve()
    assert (found.root / "image_encoder.onnx").read_bytes().startswith(b"bundled")


def test_product_resolution_skips_corrupt_bundled_and_uses_local_fallback(tmp_path, monkeypatch):
    from app.paths import set_path_overrides
    from app.semantic.catalog import OPENCLIP_BUNDLE_VERSION, OPENCLIP_MODEL_KEY

    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    bundled = _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION,
        token=b"broken",
    )
    (bundled / "image_encoder.onnx").write_bytes(b"tampered")
    local_bundle = _write_tiny_openclip_bundle(
        local / "semantic-models" / OPENCLIP_BUNDLE_VERSION,
        token=b"fallback",
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    found = resolve_semantic_bundle(OPENCLIP_MODEL_KEY)
    assert found is not None
    assert found.root.resolve() == local_bundle.resolve()
    assert (found.root / "image_encoder.onnx").read_bytes().startswith(b"fallback")


def test_product_resolution_does_not_copy_into_localappdata(tmp_path, monkeypatch):
    from app.paths import get_semantic_models_dir, set_path_overrides
    from app.semantic.catalog import OPENCLIP_BUNDLE_VERSION, OPENCLIP_MODEL_KEY

    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    found = resolve_semantic_bundle(OPENCLIP_MODEL_KEY)
    assert found is not None
    assert not get_semantic_models_dir().exists()


def test_explicit_root_scan_ignores_bundled_resource(tmp_path, monkeypatch):
    from app.paths import set_path_overrides
    from app.semantic.catalog import OPENCLIP_BUNDLE_VERSION, OPENCLIP_MODEL_KEY

    resources = tmp_path / "meipass"
    _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=tmp_path / "empty")
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    assert find_installed_bundle(tmp_path / "only-this") is None
    assert resolve_semantic_bundle(OPENCLIP_MODEL_KEY, root=tmp_path / "only-this") is None
