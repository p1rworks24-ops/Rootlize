"""Copy RapidOCR's bundled PP-OCRv6 Small models to the local PoC model folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from importlib import resources
from pathlib import Path


MODEL_FILES = (
    "PP-OCRv6_det_small.onnx",
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "PP-OCRv6_rec_small.onnx",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_bundled_models(destination: Path) -> dict[str, dict[str, object]]:
    destination.mkdir(parents=True, exist_ok=True)
    model_root = resources.files("rapidocr").joinpath("models")
    manifest: dict[str, dict[str, object]] = {}
    for name in MODEL_FILES:
        source = model_root.joinpath(name)
        if not source.is_file():
            raise FileNotFoundError(
                f"RapidOCR package does not contain required model: {name}"
            )
        target = destination / name
        with resources.as_file(source) as source_path:
            shutil.copy2(source_path, target)
        manifest[name] = {
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }
    (destination / "model-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy bundled PP-OCRv6 Small models for offline PoC use."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(__file__).resolve().parent / "models",
    )
    args = parser.parse_args()
    manifest = copy_bundled_models(args.destination.resolve())
    print(f"Prepared {len(manifest)} local model files in {args.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
