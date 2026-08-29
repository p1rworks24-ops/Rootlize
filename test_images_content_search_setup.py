from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.paths import set_path_overrides
from app.semantic.catalog import (
    MODEL_IDS,
    OPENCLIP_BUNDLE_VERSION,
    OPENCLIP_MODEL_KEY,
    OPENCLIP_PIPELINE_VERSION,
    OPENCLIP_REVISION,
)
from app.ui.images_content_search_setup import ImageContentSearchSetup


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write_tiny_openclip_bundle(root: Path) -> Path:
    files = {
        "image_encoder.onnx": b"tiny-image",
        "text_encoder.onnx": b"tiny-text",
        "bpe_simple_vocab_16e6.txt.gz": b"tiny-bpe",
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


def test_setup_hidden_when_bundled_openclip_is_present(tmp_path, monkeypatch):
    _ensure_app()
    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    _write_tiny_openclip_bundle(
        resources / "resources" / "semantic-models" / OPENCLIP_BUNDLE_VERSION
    )
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    widget = ImageContentSearchSetup(model_key=OPENCLIP_MODEL_KEY)
    assert widget.isHidden()
    assert widget.findChildren(type(widget._local))
    widget.close()


def test_setup_recovery_ui_shown_when_bundle_missing(tmp_path, monkeypatch):
    _ensure_app()
    resources = tmp_path / "meipass"
    local = tmp_path / "Local" / "Capixe"
    set_path_overrides(resource_root=resources, local_app_data_dir=local)
    monkeypatch.setattr("app.semantic.installer.is_frozen", lambda: True)
    widget = ImageContentSearchSetup(model_key=OPENCLIP_MODEL_KEY)
    assert widget.isVisible()
    assert widget._label.text() == "Meaning search needs a one-time setup."
    assert widget._local.isVisible()
    assert widget._button.isHidden()
    widget.close()
