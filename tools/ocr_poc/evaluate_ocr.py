"""Manifest-driven, local-only OCR evaluation for real screenshots."""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import platform
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from .ocr_engine import RapidOCREngine
    from .run_ocr_poc import unique_output_path
    from .text_normalization import match_keywords
except ImportError:
    from ocr_engine import RapidOCREngine
    from run_ocr_poc import unique_output_path
    from text_normalization import match_keywords


def load_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    images = data.get("images")
    if not isinstance(images, list):
        raise ValueError("Manifest must contain an images list.")
    for item in images:
        if not isinstance(item, dict) or not item.get("filename"):
            raise ValueError("Every manifest entry needs a filename.")
        item.setdefault("categories", [])
        item.setdefault("expected_keywords", [])
        item.setdefault("notes", "")
        item.setdefault("manual_status", None)
        item.setdefault("failure_reasons", [])
    return images


def searchable_status(matches: dict[str, bool]) -> str:
    if not matches or not any(matches.values()):
        return "Not Searchable"
    if all(matches.values()):
        return "Searchable"
    return "Partially Searchable"


def _rate(matched: int, total: int) -> float:
    return round(matched / total, 6) if total else 0.0


def _average(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction + 0.999999)))
    return round(ordered[index], 3)


def aggregate(results: list[dict], model_load_ms: float, total_ms: float) -> dict:
    keyword_total = sum(len(row["expected_keywords"]) for row in results)
    matched_total = sum(len(row["matched_keywords"]) for row in results)
    successful = [row for row in results if row["ocr"]["status"] == "success"]
    durations = [float(row["ocr"]["duration_ms"]) for row in successful]
    confidences = [float(row["ocr"]["average_confidence"]) for row in successful if row["ocr"]["average_confidence"] is not None]
    statuses = {name: sum(row["searchable_status"] == name for row in results) for name in ("Searchable", "Partially Searchable", "Not Searchable")}
    categories: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        for category in row["categories"]:
            grouped[category].append(row)
    for category, rows in sorted(grouped.items()):
        expected = sum(len(row["expected_keywords"]) for row in rows)
        matched = sum(len(row["matched_keywords"]) for row in rows)
        categories[category] = {
            "image_count": len(rows), "expected_keyword_count": expected,
            "matched_keyword_count": matched, "match_rate": _rate(matched, expected),
            "average_duration_ms": _average([float(row["ocr"]["duration_ms"]) for row in rows if row["ocr"]["status"] == "success"]),
            "average_confidence": _average([float(row["ocr"]["average_confidence"]) for row in rows if row["ocr"]["average_confidence"] is not None]),
        }
    resolution_groups: dict[str, list[float]] = defaultdict(list)
    block_groups: dict[str, list[float]] = defaultdict(list)
    for row in successful:
        width, height = row["ocr"].get("width", 0), row["ocr"].get("height", 0)
        pixels = width * height
        resolution_groups["<=1080p" if pixels <= 1920 * 1080 else ">1080p"].append(float(row["ocr"]["duration_ms"]))
        blocks = row["ocr"].get("block_count", 0)
        block_groups["0-25" if blocks <= 25 else "26-75" if blocks <= 75 else "76+"].append(float(row["ocr"]["duration_ms"]))
    return {
        "image_count": len(results), "ocr_success_count": len(successful),
        "ocr_failure_count": len(results) - len(successful),
        "expected_keyword_count": keyword_total, "matched_keyword_count": matched_total,
        "failed_keyword_count": keyword_total - matched_total,
        "keyword_match_rate": _rate(matched_total, keyword_total),
        "images_with_any_match": sum(bool(row["matched_keywords"]) for row in results),
        "images_with_all_matches": sum(bool(row["expected_keywords"]) and not row["failed_keywords"] for row in results),
        "images_with_no_matches": sum(not row["matched_keywords"] for row in results),
        "searchable_statuses": statuses, "model_load_duration_ms": model_load_ms,
        "total_duration_ms": total_ms,
        "duration_ms": {"average": _average(durations), "median": round(statistics.median(durations), 3) if durations else None, "minimum": min(durations) if durations else None, "maximum": max(durations) if durations else None, "p90": percentile(durations, 0.9)},
        "average_confidence": _average(confidences), "minimum_image_average_confidence": min(confidences) if confidences else None,
        "duration_by_resolution": {name: {"image_count": len(values), "average_ms": _average(values)} for name, values in sorted(resolution_groups.items())},
        "duration_by_block_count": {name: {"image_count": len(values), "average_ms": _average(values)} for name, values in sorted(block_groups.items())},
        "categories": categories,
    }


def system_memory_bytes() -> int | None:
    if os.name != "nt": return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong), ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong), ("total_page_file", ctypes.c_ulonglong), ("available_page_file", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong), ("available_extended_virtual", ctypes.c_ulonglong)]
    status = MemoryStatus(); status.length = ctypes.sizeof(status)
    return int(status.total_physical) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None


def missing_ocr_result() -> dict:
    return {"status":"error","success":False,"duration_ms":0,"blocks":[],"block_count":0,"full_text":"","average_confidence":None,"error":{"type":"FileNotFoundError","message":"Image not found"}}


def cache_key(path: Path, engine_meta: dict) -> str:
    stat = path.stat()
    hashes = ":".join(model["sha256"] for model in engine_meta["models"].values())
    return f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{engine_meta['engine_version']}|{hashes}"


def load_cache(path: Path) -> dict:
    if not path.is_file(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}


def write_outputs(payload: dict, output_dir: Path) -> dict[str, Path]:
    json_path = unique_output_path(output_dir).with_name(unique_output_path(output_dir).name.replace("ocr-poc-", "ocr-evaluation-"))
    stem = json_path.stem
    csv_path, md_path = output_dir / f"{stem}.csv", output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["filename","categories","width","height","block_count","duration_ms","average_confidence","expected_keyword_count","matched_keyword_count","match_rate","searchable_status","failed_keywords","error","cache_hit"]
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in payload["results"]:
            ocr = row["ocr"]; expected = len(row["expected_keywords"]); matched = len(row["matched_keywords"])
            writer.writerow({"filename":row["filename"],"categories":" | ".join(row["categories"]),"width":ocr.get("width"),"height":ocr.get("height"),"block_count":ocr.get("block_count"),"duration_ms":ocr.get("duration_ms"),"average_confidence":ocr.get("average_confidence"),"expected_keyword_count":expected,"matched_keyword_count":matched,"match_rate":_rate(matched,expected),"searchable_status":row["searchable_status"],"failed_keywords":" | ".join(row["failed_keywords"]),"error":(ocr.get("error") or {}).get("message", ""),"cache_hit":row["cache_hit"]})
    md_path.write_text(markdown_report(payload), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}


def markdown_report(payload: dict) -> str:
    s = payload["summary"]; env = payload["environment"]
    lines = ["# OCR Evaluation Summary", "", "## Environment", f"- RapidOCR: {env['engine_version']}", f"- ONNX Runtime: {env['runtime_version']}", f"- Device: {env['device']}", f"- Python: {env['python']}", f"- Platform: {env['platform']}", f"- CPU: {env['cpu']}", f"- Logical cores: {env['logical_cores']}", "", "## Overall", f"- Images: {s['image_count']}", f"- Keywords: {s['matched_keyword_count']} / {s['expected_keyword_count']} ({s['keyword_match_rate']:.1%})", f"- Searchable: {s['searchable_statuses']['Searchable']}", f"- Partially Searchable: {s['searchable_statuses']['Partially Searchable']}", f"- Not Searchable: {s['searchable_statuses']['Not Searchable']}", f"- Average processing time: {s['duration_ms']['average']} ms", "", "## Category Results", "| Category | Images | Keywords | Match rate | Avg ms | Avg confidence |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in s["categories"].items(): lines.append(f"| {name} | {row['image_count']} | {row['matched_keyword_count']} / {row['expected_keyword_count']} | {row['match_rate']:.1%} | {row['average_duration_ms']} | {row['average_confidence']} |")
    slowest = sorted(payload["results"], key=lambda row: row["ocr"].get("duration_ms", 0), reverse=True)[:5]
    lines += ["", "## Slowest Images"] + [f"- {row['filename']}: {row['ocr'].get('duration_ms')} ms" for row in slowest]
    lowest = sorted(payload["results"], key=lambda row: len(row["matched_keywords"]) / max(1, len(row["expected_keywords"])))[:5]
    lines += ["", "## Lowest Keyword Match"] + [f"- {row['filename']}: {len(row['matched_keywords'])}/{len(row['expected_keywords'])}" for row in lowest]
    failed = [(row["filename"], word) for row in payload["results"] for word in row["failed_keywords"]]
    lines += ["", "## Failed Keywords"] + ([f"- {name}: {word}" for name, word in failed] or ["- None"])
    manual = [row["filename"] for row in payload["results"] if row["failed_keywords"] or not row.get("manual_status")]
    lines += ["", "## Observations", "- Automated literal keyword matching only; no semantic or fuzzy judgment is made.", "", "## Manual Review Required"] + [f"- {name}" for name in manual]
    return "\n".join(lines) + "\n"


def evaluate(folder: Path, entries: list[dict], model_dir: Path, output_dir: Path, no_cache: bool = False) -> tuple[dict, dict[str, Path]]:
    started = time.perf_counter(); engine = RapidOCREngine(model_dir); meta = engine.environment_metadata()
    cache_path = output_dir / "evaluation-cache.json"; cache = {} if no_cache else load_cache(cache_path); results=[]
    for entry in entries:
        path = folder / entry["filename"]
        if path.is_file():
            key = cache_key(path, meta); hit = key in cache
            ocr = cache[key] if hit else engine.process(path)
            if not hit: cache[key] = ocr
        else:
            hit=False; ocr=missing_ocr_result()
        matches=match_keywords(ocr.get("full_text", ""), entry["expected_keywords"])
        matched=[word for word, ok in matches.items() if ok]; failed=[word for word, ok in matches.items() if not ok]
        results.append({**entry,"matched_keywords":matched,"failed_keywords":failed,"keyword_matches":matches,"searchable_status":searchable_status(matches),"cache_hit":hit,"ocr":ocr})
    output_dir.mkdir(parents=True, exist_ok=True); cache_path.write_text(json.dumps(cache, ensure_ascii=False),encoding="utf-8")
    total=round((time.perf_counter()-started)*1000,3)
    meta.update({"cpu":platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER","unknown"),"logical_cores":os.cpu_count(),"memory_bytes":system_memory_bytes()})
    payload={"generated_at":datetime.now().astimezone().isoformat(),"environment":meta,"summary":aggregate(results,engine.load_duration_ms,total),"results":results}
    return payload, write_outputs(payload, output_dir)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--folder",type=Path,required=True); parser.add_argument("--manifest",type=Path,required=True); parser.add_argument("--model-dir",type=Path,default=Path(__file__).parent/"models"); parser.add_argument("--output-dir",type=Path,default=Path(__file__).parent/"output"); parser.add_argument("--no-cache",action="store_true"); args=parser.parse_args()
    try: payload, paths=evaluate(args.folder.resolve(),load_manifest(args.manifest.resolve()),args.model_dir.resolve(),args.output_dir.resolve(),args.no_cache)
    except Exception as exc: print(f"Evaluation failed: {type(exc).__name__}: {exc}"); return 2
    s=payload["summary"]; print(f"Images: {s['image_count']} | OCR: {s['ocr_success_count']} success, {s['ocr_failure_count']} failed"); print(f"Keywords: {s['matched_keyword_count']}/{s['expected_keyword_count']} ({s['keyword_match_rate']:.1%})"); print(f"Searchable: {s['searchable_statuses']}"); print("Outputs:", *(str(path) for path in paths.values()), sep="\n  "); return 0 if not s["ocr_failure_count"] else 1


if __name__ == "__main__": raise SystemExit(main())
