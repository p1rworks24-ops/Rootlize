from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from app.semantic.bundle import load_bundle
from scripts.build_semantic_model_bundle import assemble, deterministic_zip, sha256


def test_release_bundle_is_reproducible_and_loadable(tmp_path: Path):
    onnx = tmp_path / "onnx"; snapshot = tmp_path / "snapshot"
    onnx.mkdir(); snapshot.mkdir()
    (onnx / "image_encoder.onnx").write_bytes(b"image")
    (onnx / "text_encoder.onnx").write_bytes(b"text")
    for name in ("tokenizer.json", "tokenizer_config.json", "preprocessor_config.json", "config.json"):
        (snapshot / name).write_text("{}", encoding="utf-8")
    license_file = tmp_path / "LICENSE.txt"; license_file.write_text("Apache", encoding="utf-8")

    first = assemble(onnx, snapshot, license_file, tmp_path / "first")
    second = assemble(onnx, snapshot, license_file, tmp_path / "second")
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["license"] == {"spdx_id": "Apache-2.0", "file": "LICENSE.txt"}
    assert manifest["runtime"]["opset"] == 17
    assert manifest["total_size_bytes"] == sum(item["size_bytes"] for item in manifest["files"])
    for item in manifest["files"]:
        assert hashlib.sha256((first / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    assert load_bundle(first).identity.bundle_version == "1"

    zip_a = tmp_path / "a.zip"; zip_b = tmp_path / "b.zip"
    deterministic_zip(first, zip_a); deterministic_zip(second, zip_b)
    assert sha256(zip_a) == sha256(zip_b)


def test_packaging_spec_pins_supported_python_runtime():
    spec = Path("Capixe.spec").read_text(encoding="utf-8")
    assert "sys.version_info[:2] != (3, 12)" in spec
    assert sys.version_info[:2] == (3, 12)
