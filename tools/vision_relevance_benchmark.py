"""Evaluate the Vision relevance provider on the real-image dataset."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.relevance import OpenAIImageRelevanceProvider
from app.ui.images_search import VisionRelevanceImagesSearchProvider

DEFAULT_FOLDER = Path(r"D:\07_Programs\shotlogue_test")
DEFAULT_LABELS = ROOT / "tools" / "semantic_search_benchmark" / "real_images" / "queries.json"
ABSENT_QUERIES = ("giraffe", "airplane cockpit", "wedding ceremony")
REQUIRED_QUERIES = (
    "dog", "a dog", "dog photo", "Windows desktop",
    "Windows desktop screenshot", "code editor", "image search application",
    "browser window", "settings screen",
)
FIRST_LOOK_QUERIES = (
    "command prompt", "file explorer window", "video game screenshot",
    "mountain desktop wallpaper", "application error message",
)


def metrics(expected: set[str], predicted: set[str]) -> dict:
    tp = len(expected & predicted)
    fp = len(predicted - expected)
    fn = len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def estimated_cost(input_tokens: int, output_tokens: int) -> float:
    # Explicit overrides keep this evaluator correct after model/price changes.
    input_rate = float(os.environ.get("CAPIXE_VISION_INPUT_USD_PER_MTOK", "0.20"))
    output_rate = float(os.environ.get("CAPIXE_VISION_OUTPUT_USD_PER_MTOK", "1.25"))
    return input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--query", action="append")
    parser.add_argument("--all-queries", action="store_true")
    parser.add_argument("--skip-absent", action="store_true")
    parser.add_argument("--batch-size", type=int, nargs="+", default=[5, 10, 20])
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--max-edge", type=int, default=512)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    truth = {item["query"]: set(item["relevant"]) for item in labels}
    queries = list(truth) if args.all_queries else (
        args.query or list(REQUIRED_QUERIES + FIRST_LOOK_QUERIES)
    )
    if not args.skip_absent:
        queries.extend(ABSENT_QUERIES)
        truth.update({query: set() for query in ABSENT_QUERIES})

    paths = sorted(
        path for path in args.folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    candidates = tuple((path, ()) for path in paths)
    report = {
        "folder": str(args.folder), "image_count": len(paths),
        "model": os.environ.get("CAPIXE_VISION_MODEL", "gpt-5.4-nano"),
        "pricing_usd_per_million_tokens": {
            "input": float(os.environ.get("CAPIXE_VISION_INPUT_USD_PER_MTOK", "0.20")),
            "output": float(os.environ.get("CAPIXE_VISION_OUTPUT_USD_PER_MTOK", "1.25")),
        },
        "runs": [],
    }
    for batch_size in args.batch_size:
        relevance_provider = OpenAIImageRelevanceProvider(
            batch_size=batch_size, max_workers=args.parallel, max_edge=args.max_edge
        )
        provider = VisionRelevanceImagesSearchProvider(relevance_provider)
        try:
            for query in queries:
                started = time.perf_counter()
                final_paths = provider(query, args.folder, candidates)
                run = provider.last_run
                timing = provider.last_timing or {}
                assert run is not None
                predicted = {path.name for path in final_paths}
                cost = estimated_cost(run.input_tokens, run.output_tokens)
                entry = {
                    "query": query,
                    "batch_size": batch_size,
                    "parallel": args.parallel,
                    "max_edge": args.max_edge,
                    "predicted": sorted(predicted),
                    "metrics": metrics(truth.get(query, set()), predicted),
                    "openclip_ranking_seconds": timing.get("openclip_ranking_seconds"),
                    "resize_seconds_sum": run.resize_seconds,
                    "vision_api_start_seconds": timing.get("vision_api_start_seconds"),
                    "first_result_seconds": timing.get("first_result_seconds"),
                    "first_relevant_seconds": timing.get("first_relevant_seconds"),
                    "all_judgements_seconds": timing.get("all_judgements_seconds"),
                    "ui_final_seconds": timing.get("ui_final_seconds", time.perf_counter() - started),
                    "api_seconds_sum": run.api_seconds,
                    "request_count": run.request_count,
                    "request_attempt_count": run.request_attempt_count,
                    "retry_count": run.retry_count,
                    "sent_image_count": run.sent_image_count,
                    "failed_image_count": len(run.failed_image_ids),
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "cost_usd": cost,
                    "cost_100_searches_usd": cost * 100,
                    "cost_1000_searches_usd": cost * 1000,
                }
                report["runs"].append(entry)
                print(json.dumps(entry, ensure_ascii=False), flush=True)
        finally:
            provider.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
