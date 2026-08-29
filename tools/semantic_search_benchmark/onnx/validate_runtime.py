"""Final isolated runtime validation. Writes raw JSON; never changes Capixe."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ONNX = Path(__file__).resolve().parent
FP32 = ONNX / "cache" / "fp32"
RESULT = ROOT / "results" / "siglip2_runtime_final_validation.json"


def snapshot():
    roots = list((ROOT / "cache" / "models" / "google--siglip2-base-patch16-224").glob("models--*/snapshots/*"))
    if not roots:
        raise FileNotFoundError("Cached SigLIP 2 snapshot is required")
    return roots[0]


def run_worker(batch, threads, site_packages):
    worker = ONNX / "runtime_worker.py"
    bootstrap = f"import sys,runpy;sys.path.insert(0,{str(site_packages)!r});sys.path.insert(0,{str(ONNX)!r});sys.argv=[{str(worker)!r}]+sys.argv[1:];runpy.run_path({str(worker)!r},run_name='__main__')"
    command = [sys.executable, "-c", bootstrap, "--image-model", str(FP32 / "image_encoder.onnx"), "--text-model", str(FP32 / "text_encoder.onnx"), "--model-dir", str(snapshot()), "--manifest", str(ROOT / "data" / "manifest.json"), "--queries", str(ROOT / "data" / "queries.json"), "--root", str(ROOT), "--batch", str(batch), "--threads", str(threads)]
    started = time.perf_counter()
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "NO_PROXY": "*"})
    row = json.loads(completed.stdout.strip().splitlines()[-1])
    row["wall_s"] = round(time.perf_counter() - started, 4)
    return row


def parity_and_accuracy():
    from transformers import AutoProcessor
    from runtime_light import LightweightTokenizer, preprocess_images
    from semantic_benchmark.metrics import evaluate

    model_dir = snapshot()
    processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True, use_fast=False)
    queries = json.loads((ROOT / "data" / "queries.json").read_text(encoding="utf-8"))
    records = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    texts = [item["text"] for item in queries]
    official_ids = processor(text=texts, padding="max_length", truncation=True, max_length=64, return_tensors="np")["input_ids"]
    light_ids = LightweightTokenizer(model_dir).encode(texts)
    sample_paths = [ROOT / item["path"] for item in records[:12]]
    official_pixels = processor(images=[__import__("PIL").Image.open(path).convert("RGB") for path in sample_paths], return_tensors="np")["pixel_values"]
    light_pixels = preprocess_images(sample_paths, model_dir)
    embeddings = np.load(ROOT / "results" / "runtime_embeddings_b4_t4.npz")
    metrics, rows = evaluate(embeddings["images"], embeddings["texts"], records, queries)
    return {"tokenizer_ids_equal": bool(np.array_equal(official_ids, light_ids)), "tokenizer_max_abs_diff": int(np.max(np.abs(official_ids - light_ids))), "preprocessing_max_abs_diff": float(np.max(np.abs(official_pixels - light_pixels))), "preprocessing_mean_abs_diff": float(np.mean(np.abs(official_pixels - light_pixels))), "metrics": metrics, "top_results": rows}


def deployment_sizes(site_packages):
    model_dir = snapshot()
    runtime_prefixes = ("onnxruntime", "numpy", "PIL", "pillow", "tokenizers")
    runtime_files = []
    for path in site_packages.iterdir():
        if path.name.startswith(runtime_prefixes):
            runtime_files.extend(item for item in path.rglob("*") if item.is_file())
    payload = [FP32 / "image_encoder.onnx", FP32 / "text_encoder.onnx", model_dir / "tokenizer.json", model_dir / "tokenizer_config.json", model_dir / "special_tokens_map.json", model_dir / "preprocessor_config.json"] + runtime_files
    raw = sum(path.stat().st_size for path in payload)
    zip_path = ROOT / "results" / "semantic_runtime_payload.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in payload:
            archive.write(path, path.name if path.parent in {FP32, model_dir} else str(Path("runtime") / path.relative_to(site_packages)))
    return {"image_model_mb": round((FP32 / "image_encoder.onnx").stat().st_size / 1024**2, 2), "text_model_mb": round((FP32 / "text_encoder.onnx").stat().st_size / 1024**2, 2), "tokenizer_mb": round(sum((model_dir / name).stat().st_size for name in ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]) / 1024**2, 2), "runtime_files_mb": round(sum(path.stat().st_size for path in runtime_files) / 1024**2, 2), "expanded_mb": round(raw / 1024**2, 2), "zip_mb": round(zip_path.stat().st_size / 1024**2, 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-packages", type=Path, required=True)
    args = parser.parse_args()
    configurations = [(1, 4), (4, 4), (8, 4), (4, os.cpu_count() or 8)]
    workers = [run_worker(batch, threads, args.site_packages) for batch, threads in configurations]
    result = {"environment": {"python": sys.version, "logical_threads": os.cpu_count(), "onnxruntime": __import__("onnxruntime").__version__}, "workers": workers, "parity_accuracy": parity_and_accuracy(), "deployment": deployment_sizes(args.site_packages), "offline": {"environment_flags": True, "worker_completed": True, "network_required": False}, "imports": {"torch": False, "transformers": False, "runtime_dependencies": ["onnxruntime", "numpy", "Pillow", "tokenizers"]}}
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
