from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from semantic_benchmark.dataset import prepare_dataset
from semantic_benchmark.metrics import evaluate, summarize_rows
from semantic_benchmark.models import TransformersAdapter
from semantic_benchmark.queries import build_queries
from semantic_benchmark.report import write_report


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def score_result(result: dict, all_results: list[dict]) -> float:
    metrics, perf, model = result["metrics"], result["performance"], result["model"]
    accuracy = metrics["required"]["top_3"]
    multilingual = metrics["language_ja"]["top_3"]
    fastest = min(x["performance"]["image_ms_each"] for x in all_results)
    smallest = min(x["performance"]["model_cache_mb"] for x in all_results)
    cpu = fastest / max(perf["image_ms_each"], 0.001)
    size = smallest / max(perf["model_cache_mb"], 0.001)
    deploy = 1.0 if model["commercial_redistribution"] else 0.0
    license_score = deploy
    return round(100 * (0.35 * accuracy + 0.25 * multilingual + 0.15 * cpu + 0.10 * size + 0.10 * deploy + 0.05 * license_score), 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="benchmark_config.json")
    parser.add_argument("--models", nargs="*", help="Only run these model IDs")
    parser.add_argument("--dataset-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = json.loads((root / args.config).read_text(encoding="utf-8"))
    records = prepare_dataset(root, config["public_image_count"], config["synthetic_screenshot_count"], config["seed"])
    queries = build_queries(records)
    (root / "data" / "queries.json").write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(records)} images and {len(queries)} bilingual queries.", flush=True)
    if args.dataset_only:
        return 0
    if args.report_only:
        result_dir = root / "results" / "models"
        results = []
        for spec in config["models"]:
            result_file = result_dir / f"{spec['id'].replace('/', '--')}.json"
            if result_file.exists():
                result = json.loads(result_file.read_text(encoding="utf-8"))
                result["metrics"] = summarize_rows(result["queries"], records)
                results.append(result)
        if not results:
            raise RuntimeError("No cached model results are available")
        for result in results:
            result["score"] = score_result(result, results)
        payload = {"environment": {"platform": sys.platform, "python": sys.version, "cpu_threads": os.cpu_count()}, "dataset": {"public": sum(x["kind"] == "photo" for x in records), "synthetic": sum(x["kind"] == "screenshot" for x in records), "total": len(records), "queries": len(queries)}, "results": results}
        write_report(root, payload)
        print(f"Regenerated report from {len(results)} cached model results.")
        return 0
    selected = [m for m in config["models"] if not args.models or m["id"] in args.models]
    results = []
    result_dir = root / "results" / "models"
    result_dir.mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(exist_ok=True)
    process = psutil.Process(os.getpid())
    for spec in selected:
        print(f"Loading {spec['id']}...", flush=True)
        model_cache = root / "cache" / "models" / spec["id"].replace("/", "--")
        adapter = TransformersAdapter(spec, model_cache)
        paths = [root / item["path"] for item in records]
        images, image_seconds = adapter.encode_images(paths, config["batch_size"])
        texts, text_seconds = adapter.encode_texts([item["text"] for item in queries], config["batch_size"])
        search_started = time.perf_counter()
        probe_images = np.resize(images, (10000, images.shape[1]))
        _ = texts[:1] @ probe_images.T
        search_ms = (time.perf_counter() - search_started) * 1000
        metrics, query_rows = evaluate(images, texts, records, queries)
        result = {"model": spec, "metrics": metrics, "queries": query_rows, "performance": {"load_seconds": adapter.load_seconds, "image_ms_each": image_seconds * 1000 / len(records), "query_ms_each": text_seconds * 1000 / len(queries), "search_10000_ms": search_ms, "peak_rss_mb": process.memory_info().peak_wset / 1024**2 if hasattr(process.memory_info(), "peak_wset") else process.memory_info().rss / 1024**2, "embedding_dimension": int(images.shape[1]), "vectors_10000_mb": images.shape[1] * 4 * 10000 / 1024**2, "model_cache_mb": directory_size(model_cache) / 1024**2}}
        results.append(result)
        result_file = result_dir / f"{spec['id'].replace('/', '--')}.json"
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        np.save(root / "artifacts" / f"{spec['family'].lower().replace(' ', '_')}_image_embeddings.npy", images)
        print(f"Completed {spec['id']}: JA Top-3={metrics['language_ja']['top_3']:.3f}", flush=True)
        del adapter, images, texts
        gc.collect()
    completed_ids = {item["model"]["id"] for item in results}
    for spec in config["models"]:
        result_file = result_dir / f"{spec['id'].replace('/', '--')}.json"
        if spec["id"] not in completed_ids and result_file.exists():
            cached = json.loads(result_file.read_text(encoding="utf-8"))
            if len(cached.get("queries", [])) == len(queries):
                cached["metrics"] = summarize_rows(cached["queries"], records)
                results.append(cached)
    for result in results:
        result["score"] = score_result(result, results)
    payload = {"environment": {"platform": sys.platform, "python": sys.version, "cpu_threads": os.cpu_count()}, "dataset": {"public": sum(x["kind"] == "photo" for x in records), "synthetic": sum(x["kind"] == "screenshot" for x in records), "total": len(records), "queries": len(queries)}, "results": results}
    report = write_report(root, payload)
    print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
