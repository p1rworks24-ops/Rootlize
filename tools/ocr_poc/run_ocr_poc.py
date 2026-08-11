"""Command-line runner for the independent, offline RapidOCR PoC."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    from .ocr_engine import RapidOCREngine, SUPPORTED_EXTENSIONS, utc_now
    from .text_normalization import match_keywords, parse_keywords
except ImportError:  # direct script execution
    from ocr_engine import RapidOCREngine, SUPPORTED_EXTENSIONS, utc_now
    from text_normalization import match_keywords, parse_keywords


POC_DIR = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local RapidOCR on screenshots.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, help="Process one image.")
    source.add_argument("--folder", type=Path, help="Process images directly in a folder.")
    parser.add_argument("--keywords", help="Comma-separated literal keywords to evaluate.")
    parser.add_argument("--model-dir", type=Path, default=POC_DIR / "models")
    parser.add_argument("--output-dir", type=Path, default=POC_DIR / "output")
    parser.add_argument("--allow-large-images", action="store_true")
    return parser


def collect_images(image: Path | None, folder: Path | None) -> list[Path]:
    if image is not None:
        path = image.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image does not exist: {path}")
        if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {path.suffix or '(none)'}")
        return [path]
    assert folder is not None
    root = folder.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Folder does not exist: {root}")
    return sorted(
        (path for path in root.iterdir() if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS),
        key=lambda path: path.name.casefold(),
    )


def unique_output_path(output_dir: Path, now: datetime | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S-%f")
    candidate = output_dir / f"ocr-poc-{stamp}.json"
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"ocr-poc-{stamp}-{suffix}.json"
        suffix += 1
    return candidate


def save_json(payload: dict, output_dir: Path) -> Path:
    target = unique_output_path(output_dir)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def performance_summary(results: list[dict]) -> dict:
    successful = [item for item in results if item["status"] == "success"]
    durations = [float(item["duration_ms"]) for item in successful]
    confidences = [
        float(item["average_confidence"])
        for item in successful
        if item["average_confidence"] is not None
    ]
    return {
        "successful_images": len(successful),
        "failed_images": len(results) - len(successful),
        "duration_ms": {
            "minimum": round(min(durations), 3) if durations else None,
            "maximum": round(max(durations), 3) if durations else None,
            "average": round(statistics.fmean(durations), 3) if durations else None,
            "median": round(statistics.median(durations), 3) if durations else None,
        },
        "average_confidence": round(statistics.fmean(confidences), 6) if confidences else None,
    }


def run(args: argparse.Namespace) -> tuple[dict, Path]:
    images = collect_images(args.image, args.folder)
    keywords = parse_keywords(args.keywords)
    started_at = utc_now()
    overall_started = time.perf_counter()
    tracemalloc.start()
    engine = RapidOCREngine(args.model_dir, args.allow_large_images)
    print(f"Local OCR ready: {len(images)} image(s), CPU, no runtime download")
    results = []
    for index, path in enumerate(images, start=1):
        print(f"[{index}/{len(images)}] {path.name}")
        result = engine.process(path)
        result["keyword_matches"] = match_keywords(result["full_text"], keywords)
        results.append(result)
        if result["status"] == "error":
            print("  Status: Failed")
            print(f"  Error: {result['error']['message']}")
        else:
            preview = result["full_text"].replace("\n", " ")[:160]
            confidence = result["average_confidence"]
            print("  Status: Success")
            print(f"  Duration: {result['duration_ms']:.1f} ms")
            print(f"  Blocks: {result['block_count']}")
            print(f"  Average confidence: {confidence if confidence is not None else 'n/a'}")
            print(f"  Text preview: {preview}")
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    performance = performance_summary(results)
    payload = {
        "schema_version": 1,
        "run": {
            "started_at": started_at,
            "finished_at": utc_now(),
            "source": str((args.image or args.folder).resolve()),
            "mode": "image" if args.image else "folder",
            "recursive": False,
            "image_count": len(images),
            "success_count": performance["successful_images"],
            "failure_count": performance["failed_images"],
            "keywords": keywords,
            "model_load_duration_ms": engine.load_duration_ms,
            "total_duration_ms": round((time.perf_counter() - overall_started) * 1000, 3),
            "peak_python_memory_bytes": peak_memory,
            **engine.environment_metadata(),
        },
        "performance": performance,
        "results": results,
    }
    output_path = save_json(payload, args.output_dir.resolve())
    return payload, output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload, output_path = run(args)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        parser.error(str(exc))
    except Exception as exc:
        print(f"OCR initialization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    summary = payload["performance"]
    print(
        f"Done: {summary['successful_images']} succeeded, "
        f"{summary['failed_images']} failed"
    )
    print(f"Total time: {payload['run']['total_duration_ms'] / 1000:.2f} sec")
    print(f"Average time: {summary['duration_ms']['average']} ms/image")
    print(f"JSON: {output_path}")
    return 0 if summary["failed_images"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
