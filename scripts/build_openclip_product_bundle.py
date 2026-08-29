"""Build the development OpenCLIP product bundle from verified PoC assets."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "semantic_search_benchmark" / "openclip_onnx_poc" / "bundle"
TARGET = ROOT / "release" / "semantic-model-openclip-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    names = ("image_encoder.onnx", "text_encoder.onnx", "bpe_simple_vocab_16e6.txt.gz", "open_clip_config.json", "OPEN_CLIP_LICENSE.txt")
    for name in names:
        shutil.copy2(SOURCE / name, TARGET / name)
    preprocess = {
        "size": {"width": 224, "height": 224}, "resize_mode": "shortest_center_crop",
        "resample": 3, "rescale_factor": 1 / 255,
        "image_mean": [0.48145466, 0.4578275, 0.40821073],
        "image_std": [0.26862954, 0.26130258, 0.27577711],
    }
    (TARGET / "preprocessor_config.json").write_text(json.dumps(preprocess, indent=2), encoding="utf-8")
    notice = (
        "Model: laion/CLIP-ViT-B-32-laion2B-s34B-b79K\n"
        "Model source: https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K\n"
        "Model repository license: MIT\n"
        "Tokenizer implementation derives from OpenAI CLIP (MIT).\n"
        "OpenCLIP project: https://github.com/mlfoundations/open_clip\n"
    )
    (TARGET / "NOTICE.txt").write_text(notice, encoding="utf-8")
    roles = {
        "image_encoder.onnx": "image_encoder", "text_encoder.onnx": "text_encoder",
        "bpe_simple_vocab_16e6.txt.gz": "tokenizer", "open_clip_config.json": "model_config",
        "preprocessor_config.json": "preprocess_config", "OPEN_CLIP_LICENSE.txt": "license",
        "NOTICE.txt": "notice",
    }
    entries = []
    for name, role in roles.items():
        path = TARGET / name
        entries.append({"role": role, "path": name, "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "manifest_schema_version": 1, "bundle_version": "openclip-v1",
        "model_id": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "model_name": "OpenCLIP ViT-B/32 LAION-2B", "adapter": "openclip",
        "source": "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "revision": "1a25a446712ba5ee05982a381eed697ef9b435cf",
        "license": {"spdx_id": "MIT", "file": "OPEN_CLIP_LICENSE.txt", "notice": "NOTICE.txt"},
        "embedding": {"dimension": 512, "dtype": "float32", "normalized": True},
        "image": {"width": 224, "height": 224, "color_mode": "RGB", "preprocess_config": "preprocessor_config.json"},
        "text": {"max_length": 77, "tokenizer": "bpe_simple_vocab_16e6.txt.gz", "algorithm": "openai_simple_bpe"},
        "runtime": {"name": "onnxruntime", "minimum_version": "1.28.0", "opset": 18, "providers": ["CPUExecutionProvider"]},
        "pipeline_version": 2, "files": entries,
        "total_size_bytes": sum(item["size_bytes"] for item in entries),
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
