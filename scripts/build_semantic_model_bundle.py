"""Assemble and verify the optional Semantic model release bundle.

The ONNX graphs are produced by
``tools/semantic_search_benchmark/onnx/benchmark_onnx.py`` from the pinned
upstream snapshot.  This script turns those immutable inputs into the exact
files uploaded as separate GitHub Release assets, plus a deterministic ZIP
for archival/manual verification.  The ZIP is never included in the app ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


MODEL_ID = "siglip2-base-patch16-224"
MODEL_NAME = "SigLIP 2 Base/224"
SOURCE = "google/siglip2-base-patch16-224"
REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
BUNDLE_VERSION = "1"
FILE_SPECS = (
    ("image_encoder", "image_encoder.onnx"),
    ("text_encoder", "text_encoder.onnx"),
    ("tokenizer", "tokenizer.json"),
    ("tokenizer_config", "tokenizer_config.json"),
    ("preprocess_config", "preprocessor_config.json"),
    ("model_config", "config.json"),
    ("license", "LICENSE.txt"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assemble(onnx_dir: Path, snapshot_dir: Path, license_file: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.mkdir(parents=True)
    sources = {
        "image_encoder.onnx": onnx_dir / "image_encoder.onnx",
        "text_encoder.onnx": onnx_dir / "text_encoder.onnx",
        "tokenizer.json": snapshot_dir / "tokenizer.json",
        "tokenizer_config.json": snapshot_dir / "tokenizer_config.json",
        "preprocessor_config.json": snapshot_dir / "preprocessor_config.json",
        "config.json": snapshot_dir / "config.json",
        "LICENSE.txt": license_file,
    }
    entries = []
    total = 0
    for role, name in FILE_SPECS:
        source = sources[name]
        if not source.is_file():
            raise FileNotFoundError(source)
        target_name = "model_config.json" if name == "config.json" else name
        target = output / target_name
        shutil.copyfile(source, target)
        size = target.stat().st_size
        entries.append({"role": role, "path": target_name, "size_bytes": size, "sha256": sha256(target)})
        total += size

    manifest = {
        "manifest_schema_version": 1,
        "bundle_version": BUNDLE_VERSION,
        "model_id": MODEL_ID,
        "model_name": MODEL_NAME,
        "source": SOURCE,
        "revision": REVISION,
        "license": {"spdx_id": "Apache-2.0", "file": "LICENSE.txt"},
        "embedding": {"dimension": 768, "dtype": "float32", "normalized": True},
        "image": {"width": 224, "height": 224, "color_mode": "RGB", "preprocess_config": "preprocessor_config.json"},
        "text": {"max_length": 64, "tokenizer": "tokenizer.json", "tokenizer_config": "tokenizer_config.json"},
        "runtime": {"name": "onnxruntime", "minimum_version": "1.28.0", "opset": 17, "providers": ["CPUExecutionProvider"]},
        "pipeline_version": 1,
        "files": entries,
        "total_size_bytes": total,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return output


def deterministic_zip(bundle: Path, target: Path) -> None:
    timestamp = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for source in sorted(bundle.iterdir(), key=lambda item: item.name):
            info = zipfile.ZipInfo(source.name, timestamp)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            with source.open("rb") as stream, archive.open(info, "w", force_zip64=True) as sink:
                shutil.copyfileobj(stream, sink, length=1024 * 1024)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx-dir", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--license-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    bundle = assemble(args.onnx_dir.resolve(), args.snapshot_dir.resolve(), args.license_file.resolve(), args.output.resolve())
    if args.zip:
        deterministic_zip(bundle, args.zip.resolve())
    print(json.dumps({
        "bundle": str(bundle),
        "total_size_bytes": json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))["total_size_bytes"],
        "zip": str(args.zip.resolve()) if args.zip else None,
        "zip_size_bytes": args.zip.resolve().stat().st_size if args.zip else None,
        "zip_sha256": sha256(args.zip.resolve()) if args.zip else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
