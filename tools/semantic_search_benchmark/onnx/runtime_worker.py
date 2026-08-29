"""One-shot independent process for product-like RAM and throughput measurement."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import psutil

from runtime_light import SemanticRuntime


class Sampler:
    def __init__(self):
        self.process = psutil.Process()
        self.peak = self.process.memory_info().rss
        self.cpu_samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        self.process.cpu_percent(None)
        while not self.stop_event.wait(0.01):
            self.peak = max(self.peak, self.process.memory_info().rss)
            self.cpu_samples.append(self.process.cpu_percent(None))

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)


def mb(value):
    return round(value / 1024**2, 2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-model", type=Path, required=True)
    parser.add_argument("--text-model", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    process = psutil.Process()
    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    result = {"pid": os.getpid(), "batch": args.batch, "threads": args.threads, "rss_start_mb": mb(process.memory_info().rss)}
    started = time.perf_counter()
    with Sampler() as sampler:
        runtime = SemanticRuntime(args.image_model, args.text_model, args.model_dir, intra_threads=args.threads)
    result.update(load_s=round(time.perf_counter() - started, 4), rss_loaded_mb=mb(process.memory_info().rss), load_peak_mb=mb(sampler.peak))
    image_rows = []
    started = time.perf_counter()
    with Sampler() as sampler:
        for pos in range(0, len(records), args.batch):
            paths = [args.root / item["path"] for item in records[pos:pos + args.batch]]
            image_rows.append(runtime.embed_images(paths))
    image_s = time.perf_counter() - started
    image_peak = sampler.peak
    result.update(image_total_s=round(image_s, 4), image_ms_per_item=round(image_s * 1000 / len(records), 3), images_per_s=round(len(records) / image_s, 3), image_peak_mb=mb(image_peak), image_cpu_percent=round(sum(sampler.cpu_samples) / max(1, len(sampler.cpu_samples)), 1))
    started = time.perf_counter()
    with Sampler() as sampler:
        text_rows = []
        for pos in range(0, len(queries), args.batch):
            text_rows.append(runtime.embed_texts([item["text"] for item in queries[pos:pos + args.batch]]))
    text_s = time.perf_counter() - started
    result.update(text_total_s=round(text_s, 4), text_ms_per_item=round(text_s * 1000 / len(queries), 3), text_peak_mb=mb(sampler.peak), text_cpu_percent=round(sum(sampler.cpu_samples) / max(1, len(sampler.cpu_samples)), 1), rss_idle_mb=mb(process.memory_info().rss), peak_rss_mb=mb(max(image_peak, sampler.peak, process.memory_info().rss)))
    import numpy as np
    np.savez_compressed(args.root / "results" / f"runtime_embeddings_b{args.batch}_t{args.threads}.npz", images=np.concatenate(image_rows), texts=np.concatenate(text_rows))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
