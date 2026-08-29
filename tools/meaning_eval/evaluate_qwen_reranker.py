"""Independent Qwen3-VL-Reranker-2B Meaning-search PoC.

Scores every query-image pair with the official yes/no reranker head.
Does not change product search, OpenCLIP, matcher, threshold, Hybrid,
Vision Judge prompts, Semantic Index, GT v2, or the query set.
Does not overwrite artifacts/meaning-eval/latest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.identity import corpus_identity, git_identity
from tools.meaning_eval.metrics import summarize_end_to_end
from tools.meaning_eval.scoring import end_to_end_row

DEFAULT_FOLDER = Path(r"D:\07_Programs\shotlogue_test")
DEFAULT_CORPUS_NAMES = (
    ROOT / "artifacts" / "meaning-eval" / "runs"
    / "phase-e-describe-text-judge-smoke" / "descriptions.json"
)

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "qwen3-vl-reranker-2b-gt-v2"
HYBRID_RESULTS = (
    RUNS_DIR / "semantic-index-hybrid-phase-e-gt-v2-meaning-units" / "results.json"
)
JUDGE_RESULTS = RUNS_DIR / "vision-judge-gt-v2-meaning-units" / "results.json"
MODEL_ID = "Qwen/Qwen3-VL-Reranker-2B"
INSTRUCTION_VERSION = "qwen3-vl-reranker-meaning-v1"
# Official scoring is sigmoid(yes-no). There is no published binary cutoff.
# 0.5 is the a-priori yes>no boundary and is NOT fit on these queries.
PRIMARY_THRESHOLD = 0.5
SENSITIVITY_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)
# Hold-out queries in the focus set. Never used to pick a threshold.
HOLDOUT_FOCUS = {
    "Google Chrome in Windows desktop",
    "sitting orange brown dog",
    "empty folder in screenshot manager",
}
FOCUS_QUERIES = (
    "Google Chrome",
    "Google Chrome in Windows desktop",
    "dog",
    "orange brown dog",
    "sitting orange brown dog",
    "ChatGPT in a browser",
    "empty folder in screenshot manager",
    "code editor",
    "command prompt",
    "file explorer window",
)
NESTED_DOG_IMAGES = (
    "20260813_225929.png",
    "20260815_221055.png",
    "20260815_231828.png",
)
SUBJECT_DOG_IMAGES = ("A2.png", "images.jpg")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MEANING_INSTRUCTION = (
    "A screenshot is relevant if a human can reasonably identify the query "
    "content anywhere in it, including background, nested windows, or "
    "thumbnails. It does not need to be the main subject. Treat noun phrases "
    "and proper names as meaning units rather than AND-split words. Every "
    "independent condition in the query must hold."
)


def list_images(folder: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda path: path.name.lower(),
    )


def _load_name_set(path: Path | None) -> set[str] | None:
    if path is None or not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {str(name) for name in payload if name}
    if isinstance(payload, dict):
        by_name = payload.get("by_name")
        if isinstance(by_name, dict):
            return set(by_name)
        names = payload.get("names")
        if isinstance(names, list):
            return {str(name) for name in names if name}
    return None


def _json_load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_by_query(payload: dict | None, *, path: tuple[str, ...]) -> dict[str, dict]:
    if not payload:
        return {}
    cursor: object = payload
    for key in path:
        if not isinstance(cursor, dict):
            return {}
        cursor = cursor.get(key)
    if isinstance(cursor, list):
        return {row["query"]: row for row in cursor if isinstance(row, dict) and "query" in row}
    return {}


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    if path.is_file():
        return path.stat().st_size
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _rss_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.Process().memory_info().rss)


def _nvidia_used_bytes() -> int | None:
    try:
        import subprocess

        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    line = (completed.stdout or "").strip().splitlines()
    if not line:
        return None
    try:
        return int(float(line[0]) * 1024 * 1024)
    except ValueError:
        return None


def _histogram(scores: list[float], edges: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01)) -> list[dict]:
    counts = [0] * len(edges)
    for score in scores:
        for index, edge in enumerate(edges):
            if score < edge:
                counts[index] += 1
                break
    previous = 0.0
    rows = []
    for edge, count in zip(edges, counts):
        rows.append({"lo": previous, "hi": edge, "count": count})
        previous = edge
    return rows


def _predicted(scores: dict[str, float], threshold: float) -> list[str]:
    return [name for name, score in scores.items() if score >= threshold]


def _load_checkpoint(path: Path) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        query = item["query"]
        rows.setdefault(query, {})[item["name"]] = float(item["score"])
    return rows


def _open_image(path: Path):
    from PIL import Image

    with Image.open(path) as handle:
        return handle.convert("RGB")


def _score_query_images(
    reranker,
    query: str,
    paths: list[Path],
    *,
    instruction: str,
    batch_size: int,
    max_pixels: int,
    scores_path: Path,
    existing: dict[str, float],
) -> tuple[dict[str, float], dict]:
    import torch

    pending = [path for path in paths if path.name not in existing]
    scores = dict(existing)
    pair_times: list[float] = []
    oom_events = 0
    failed: dict[str, str] = {}
    peak_vram = 0
    peak_rss = _rss_bytes() or 0
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        images = []
        for path in chunk:
            try:
                images.append(_open_image(path))
            except Exception as exc:  # noqa: BLE001
                failed[path.name] = f"open:{exc}"
        valid_paths = [path for path in chunk if path.name not in failed]
        if not images:
            continue
        started = time.perf_counter()
        try:
            values = reranker.score_pairs(
                query, images, instruction=instruction, max_pixels=max_pixels
            )
        except torch.cuda.OutOfMemoryError:
            oom_events += 1
            torch.cuda.empty_cache()
            values = []
            if batch_size > 1:
                raise
            for path, image in zip(valid_paths, images):
                try:
                    one = reranker.score_pairs(
                        query, [image], instruction=instruction, max_pixels=max_pixels
                    )
                    values.extend(one)
                except torch.cuda.OutOfMemoryError:
                    oom_events += 1
                    torch.cuda.empty_cache()
                    failed[path.name] = "oom"
                    values.append(None)
        elapsed = time.perf_counter() - started
        n_ok = sum(1 for value in values if value is not None)
        if n_ok:
            pair_times.append(elapsed / n_ok)
        allocated = int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0
        peak_vram = max(peak_vram, allocated, _nvidia_used_bytes() or 0)
        peak_rss = max(peak_rss, _rss_bytes() or 0)
        with scores_path.open("a", encoding="utf-8") as handle:
            for path, value in zip(valid_paths, values):
                if value is None:
                    continue
                score = float(value)
                scores[path.name] = score
                handle.write(
                    json.dumps({
                        "query": query,
                        "name": path.name,
                        "score": score,
                    }, ensure_ascii=False)
                    + "\n"
                )
        del images
        if start and start % (batch_size * 8) == 0:
            torch.cuda.empty_cache()
    stats = {
        "pair_times": pair_times,
        "oom_events": oom_events,
        "failed": failed,
        "peak_vram_bytes": peak_vram,
        "peak_rss_bytes": peak_rss,
        "pending": len(pending),
        "resumed": len(paths) - len(pending),
    }
    return scores, stats


def _metrics_for_threshold(dataset, selected, scores_by_query, ranking, threshold: float) -> dict:
    rows = []
    for spec in selected:
        predicted = _predicted(scores_by_query.get(spec.query) or {}, threshold)
        judgements = {
            name: {
                "relevant": score >= threshold,
                "relevance_score": score,
                "reason": "qwen3-vl-reranker-yes-probability",
            }
            for name, score in (scores_by_query.get(spec.query) or {}).items()
        }
        rows.append(
            end_to_end_row(
                spec,
                ranking=ranking,
                predicted=predicted,
                judgements=judgements,
                embedded_names=set(ranking),
            )
        )
    splits = {
        "dev": summarize_end_to_end([row for row in rows if row["split"] == "dev"]),
        "holdout": summarize_end_to_end([row for row in rows if row["split"] == "holdout"]),
        "all": summarize_end_to_end(rows),
    }
    return {"threshold": threshold, "splits": splits, "queries": rows}


def _query_snapshot(row: dict) -> dict:
    return {
        "query": row["query"],
        "split": row["split"],
        "kind": row["kind"],
        "precision": row["precision"],
        "recall": row["recall"],
        "f1": row["f1"],
        "tp": row["tp"],
        "fp": row["fp"],
        "fn": row["fn"],
        "tp_names": row["tp_names"],
        "fp_names": row["fp_names"],
        "fn_names": row["fn_names"],
    }


def _compare_baselines(primary_rows: list[dict], hybrid_by_query: dict, judge_by_query: dict) -> list[dict]:
    compared = []
    for row in primary_rows:
        hybrid = hybrid_by_query.get(row["query"]) or {}
        judge = judge_by_query.get(row["query"]) or {}
        compared.append({
            "query": row["query"],
            "split": row["split"],
            "qwen": _query_snapshot(row),
            "hybrid_c": {
                "precision": hybrid.get("precision"),
                "recall": hybrid.get("recall"),
                "f1": hybrid.get("f1"),
                "tp": hybrid.get("tp"),
                "fp": hybrid.get("fp"),
                "fn": hybrid.get("fn"),
                "tp_names": hybrid.get("tp_names"),
                "fp_names": hybrid.get("fp_names"),
                "fn_names": hybrid.get("fn_names"),
                "uncertain": hybrid.get("uncertain"),
                "vision_sent_images": hybrid.get("vision_sent_images"),
            },
            "judge_a": {
                "precision": judge.get("precision"),
                "recall": judge.get("recall"),
                "f1": judge.get("f1"),
                "tp": judge.get("tp"),
                "fp": judge.get("fp"),
                "fn": judge.get("fn"),
            },
        })
    return compared


def _nested_dog_view(scores_by_query: dict[str, dict[str, float]], threshold: float) -> dict:
    dog_scores = scores_by_query.get("dog") or {}
    orange = scores_by_query.get("orange brown dog") or {}
    sitting = scores_by_query.get("sitting orange brown dog") or {}
    rows = []
    for name in NESTED_DOG_IMAGES + SUBJECT_DOG_IMAGES:
        rows.append({
            "name": name,
            "nested": name in NESTED_DOG_IMAGES,
            "dog": dog_scores.get(name),
            "dog_relevant": None if name not in dog_scores else dog_scores[name] >= threshold,
            "orange_brown_dog": orange.get(name),
            "sitting_orange_brown_dog": sitting.get(name),
        })
    return {"threshold": threshold, "images": rows}


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _verdict(primary: dict, nested: dict, compared: list[dict]) -> dict:
    rows = {row["query"]: row for row in primary["queries"]}
    dog = rows.get("dog") or {}
    nested_hits = [
        item for item in nested["images"]
        if item["nested"] and item.get("dog_relevant") is True
    ]
    explorer = rows.get("file explorer window") or {}
    empty = rows.get("empty folder in screenshot manager") or {}
    chrome = rows.get("Google Chrome") or {}
    chrome_desktop = rows.get("Google Chrome in Windows desktop") or {}
    orange = rows.get("orange brown dog") or {}
    sitting = rows.get("sitting orange brown dog") or {}
    signals = {
        "nested_dog_hits": len(nested_hits),
        "nested_dog_total": 3,
        "dog_recall": dog.get("recall"),
        "orange_recall": orange.get("recall"),
        "sitting_recall": sitting.get("recall"),
        "orange_precision": orange.get("precision"),
        "sitting_precision": sitting.get("precision"),
        "chrome_recall": chrome.get("recall"),
        "chrome_precision": chrome.get("precision"),
        "chrome_desktop_precision": chrome_desktop.get("precision"),
        "chrome_desktop_recall": chrome_desktop.get("recall"),
        "empty_folder_precision": empty.get("precision"),
        "empty_folder_recall": empty.get("recall"),
        "explorer_fp": explorer.get("fp"),
        "explorer_precision": explorer.get("precision"),
        "macro_f1": (primary["splits"]["all"] or {}).get("macro_f1"),
        "macro_precision": (primary["splits"]["all"] or {}).get("macro_precision"),
        "macro_recall": (primary["splits"]["all"] or {}).get("macro_recall"),
    }
    promise = (
        len(nested_hits) >= 2
        or (dog.get("recall") or 0) >= 0.8
        or (
            (chrome.get("recall") or 0) >= 0.85
            and (chrome_desktop.get("precision") or 0) >= 0.85
            and (empty.get("precision") or 0) >= 0.5
            and (explorer.get("fp") or 99) <= 10
        )
    )
    weak = (
        len(nested_hits) == 0
        and (dog.get("recall") or 0) <= 0.4
        and (explorer.get("fp") or 0) >= 20
        and (empty.get("precision") or 1) < 0.5
    )
    if weak:
        decision = "no_go_stop"
        recommendation = "別候補PoC"
        adopt_as_judge = False
        reason = (
            "重点queryで入れ子Recall・複合条件Precision・短いUI FPが同時に改善しないため、"
            "35 query全量へ広げない。"
        )
    elif promise:
        decision = "conditional_expand"
        recommendation = "採用は保留。35 query全量で仕様適合を確認する。"
        adopt_as_judge = False
        reason = (
            "重点queryで仕様に対する見込みがある。総合F1だけで採否しない。"
            "製品組み込みはまだしない。"
        )
    else:
        decision = "inconclusive_expand_optional"
        recommendation = "別候補PoCも並行検討"
        adopt_as_judge = False
        reason = "一部queryは動くが、Judge代替の根拠としては不足。"
    return {
        "promise": promise,
        "weak": weak,
        "decision": decision,
        "recommendation": recommendation,
        "adopt_as_judge": adopt_as_judge,
        "reason": reason,
        "signals": signals,
        "compared_queries": len(compared),
    }


def render_summary(report: dict) -> str:
    identity = report["identity"]
    runtime = report.get("runtime") or {}
    primary = report["primary"]
    nested = report.get("nested_dog") or {"images": []}
    verdict = report.get("verdict") or {}
    lines = [
        "# Qwen3-VL-Reranker-2B Meaning eval PoC",
        "",
        "## Run identity",
        "",
        f"- timestamp: `{identity.get('timestamp')}`",
        f"- git commit: `{identity.get('git_commit')}` dirty={identity.get('git_dirty')}",
        f"- model: `{identity.get('model_id')}` revision=`{identity.get('model_revision')}`",
        f"- quantization: `{identity.get('quantization')}` dtype=`{identity.get('torch_dtype')}`",
        f"- instruction: `{identity.get('instruction_version')}`",
        f"- query set: `{identity.get('query_set_version')}`",
        f"- GT: `{identity.get('gt_version')}`",
        f"- corpus: count={identity.get('corpus_count')}",
        f"- primary threshold: {identity.get('primary_threshold')} (a priori yes>no; not fit on these queries)",
        "",
        "## Instruction",
        "",
        report.get("instruction", ""),
        "",
        "## Primary metrics (threshold "
        + str(identity.get("primary_threshold"))
        + ")",
        "",
        "| split | n | macro P | macro R | macro F1 | micro TP | micro FP | micro FN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split_name in ("all", "dev", "holdout"):
        summary = primary["splits"][split_name]
        lines.append(
            f"| {split_name} | {summary['n']} | {_fmt(summary['macro_precision'])} | "
            f"{_fmt(summary['macro_recall'])} | {_fmt(summary['macro_f1'])} | "
            f"{summary['micro_tp']} | {summary['micro_fp']} | {summary['micro_fn']} |"
        )
    lines.extend(["", "### Per query", ""])
    lines.append("| query | split | P | R | F1 | TP | FP | FN |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for row in primary["queries"]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | {_fmt(row['precision'])} | "
            f"{_fmt(row['recall'])} | {_fmt(row['f1'])} | {row['tp']} | {row['fp']} | {row['fn']} |"
        )
    lines.extend(["", "## Nested dog images", ""])
    lines.append("| image | nested | dog score | dog relevant | orange brown | sitting orange brown |")
    lines.append("|---|---|---:|---|---:|---:|")
    for item in nested.get("images") or []:
        lines.append(
            f"| `{item['name']}` | {item['nested']} | {_fmt(item.get('dog'))} | "
            f"{item.get('dog_relevant')} | {_fmt(item.get('orange_brown_dog'))} | "
            f"{_fmt(item.get('sitting_orange_brown_dog'))} |"
        )
    lines.extend(["", "## Comparison with Hybrid C / Judge A", ""])
    lines.append("| query | Qwen P/R/F1 | Hybrid C P/R/F1 | Judge A P/R/F1 |")
    lines.append("|---|---|---|---|")
    for item in report.get("comparison_rows") or []:
        qwen = item["qwen"]
        hybrid = item["hybrid_c"]
        judge = item["judge_a"]
        lines.append(
            f"| `{item['query']}` | "
            f"{_fmt(qwen['precision'])}/{_fmt(qwen['recall'])}/{_fmt(qwen['f1'])} | "
            f"{_fmt(hybrid.get('precision'))}/{_fmt(hybrid.get('recall'))}/{_fmt(hybrid.get('f1'))} | "
            f"{_fmt(judge.get('precision'))}/{_fmt(judge.get('recall'))}/{_fmt(judge.get('f1'))} |"
        )
    lines.extend(["", "## Threshold sensitivity (not used for selection)", ""])
    lines.append("| threshold | macro P | macro R | macro F1 | micro FP | micro FN |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for item in report.get("sensitivity") or []:
        all_split = item["splits"]["all"]
        lines.append(
            f"| {item['threshold']} | {_fmt(all_split['macro_precision'])} | "
            f"{_fmt(all_split['macro_recall'])} | {_fmt(all_split['macro_f1'])} | "
            f"{all_split['micro_fp']} | {all_split['micro_fn']} |"
        )
    lines.extend(["", "## Runtime", ""])
    lines.append(f"- model download bytes: {runtime.get('model_download_bytes')}")
    lines.append(f"- load seconds: {runtime.get('load_seconds')}")
    lines.append(f"- mean pair seconds: {runtime.get('mean_pair_seconds')}")
    lines.append(f"- total score seconds: {runtime.get('total_score_seconds')}")
    lines.append(f"- peak VRAM bytes: {runtime.get('peak_vram_bytes')}")
    lines.append(f"- nvidia-smi used bytes: {runtime.get('nvidia_used_bytes')}")
    lines.append(f"- peak RSS bytes: {runtime.get('peak_rss_bytes')}")
    lines.append(f"- OOM events: {runtime.get('oom_events')}")
    lines.append(f"- batch size: {runtime.get('batch_size')}")
    lines.append(f"- batch probe: {json.dumps(runtime.get('batch_probe') or {}, ensure_ascii=False)}")
    estimate = report.get("uncertain32_estimate") or {}
    lines.extend(["", "## Uncertain ~32 images/query estimate", ""])
    lines.append(
        f"- mean pair seconds × 32 = {_fmt(estimate.get('seconds_per_query_32'), 1)} s/query"
    )
    lines.append(
        f"- 35 queries × 32 = {_fmt(estimate.get('seconds_35q_32'), 1)} s "
        f"({_fmt(estimate.get('minutes_35q_32'), 1)} min)"
    )
    lines.extend(["", "## Verdict", ""])
    lines.append(f"- decision: `{verdict.get('decision')}`")
    lines.append(f"- recommendation: {verdict.get('recommendation')}")
    lines.append(f"- adopt as judge: {verdict.get('adopt_as_judge')}")
    lines.append(f"- reason: {verdict.get('reason')}")
    lines.append("")
    return "\n".join(lines)


def _batch_probe(reranker, query: str, paths: list[Path], *, instruction: str, max_pixels: int) -> dict:
    import torch

    sample = paths[:4]
    if len(sample) < 2:
        return {"skipped": True, "reason": "need at least 2 images"}
    images = [_open_image(path) for path in sample]
    results = {}
    for batch_size in (1, 2, 4):
        if batch_size > len(images):
            continue
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        try:
            chunk = images[:batch_size]
            reranker.score_pairs(query, chunk, instruction=instruction, max_pixels=max_pixels)
            elapsed = time.perf_counter() - started
            results[str(batch_size)] = {
                "ok": True,
                "seconds": elapsed,
                "seconds_per_pair": elapsed / batch_size,
                "peak_vram_bytes": int(torch.cuda.max_memory_allocated()),
            }
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            results[str(batch_size)] = {"ok": False, "error": "oom"}
        except Exception as exc:  # noqa: BLE001
            results[str(batch_size)] = {"ok": False, "error": str(exc)}
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3-VL-Reranker-2B Meaning eval PoC")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--revision", default=None)
    parser.add_argument("--quantization", choices=("4bit", "fp16", "auto"), default="fp16")
    parser.add_argument("--max-pixels", type=int, default=512 * 32 * 32)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=PRIMARY_THRESHOLD)
    parser.add_argument("--stage", choices=("focus", "all"), default="focus")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--query", action="append", dest="queries")
    args = parser.parse_args()

    dataset = load_dataset(args.gt)
    if args.queries:
        wanted = list(dict.fromkeys(args.queries))
    elif args.smoke:
        wanted = ["dog"]
    elif args.stage == "focus":
        wanted = list(FOCUS_QUERIES)
    else:
        wanted = [spec.query for spec in dataset.queries]
    by_name = {spec.query: spec for spec in dataset.queries}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise SystemExit(f"Unknown queries: {missing}")
    selected = tuple(by_name[name] for name in wanted)
    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
        absent = keep_names - {path.name for path in paths}
        if absent:
            raise SystemExit(f"match-corpus-from names missing: {sorted(absent)[:8]}")
    if args.smoke:
        keep = set(NESTED_DOG_IMAGES + SUBJECT_DOG_IMAGES)
        paths = [path for path in paths if path.name in keep]
        if len(paths) < 3:
            raise SystemExit(f"smoke images missing, found {[path.name for path in paths]}")
    corpus = corpus_identity(paths)
    ranking = [path.name for path in paths]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    scores_path = output_dir / "scores.jsonl"
    if args.resume:
        completed = _load_checkpoint(scores_path)
    else:
        completed = {}
        if scores_path.exists():
            scores_path.unlink()

    print(
        json.dumps({
            "stage": args.stage if not args.smoke else "smoke",
            "queries": [spec.query for spec in selected],
            "images": len(paths),
            "pairs": len(selected) * len(paths),
            "quantization": args.quantization,
            "max_pixels": args.max_pixels,
            "batch_size": args.batch_size,
            "threshold": args.threshold,
        }, ensure_ascii=False),
        flush=True,
    )

    from huggingface_hub import snapshot_download

    from tools.meaning_eval.qwen_vl_reranker import Qwen3VLReranker

    download_started = time.perf_counter()
    snapshot_kwargs = {}
    if args.revision:
        snapshot_kwargs["revision"] = args.revision
    snapshot_path = Path(snapshot_download(args.model_id, **snapshot_kwargs))
    download_seconds = time.perf_counter() - download_started
    download_bytes = _dir_size(snapshot_path)
    print(
        json.dumps({
            "snapshot": str(snapshot_path),
            "download_bytes": download_bytes,
            "download_seconds": download_seconds,
        }, ensure_ascii=False),
        flush=True,
    )

    rss_before = _rss_bytes()
    nvidia_before = _nvidia_used_bytes()
    reranker = Qwen3VLReranker(
        str(snapshot_path),
        max_pixels=args.max_pixels,
        quantization=args.quantization,
        default_instruction=MEANING_INSTRUCTION,
    )
    load_info = reranker.load_info
    print(json.dumps(load_info.__dict__, ensure_ascii=False), flush=True)

    probe = {}
    if not args.smoke:
        probe = _batch_probe(
            reranker,
            selected[0].query,
            paths,
            instruction=MEANING_INSTRUCTION,
            max_pixels=args.max_pixels,
        )
        print(json.dumps({"batch_probe": probe}, ensure_ascii=False), flush=True)

    scores_by_query: dict[str, dict[str, float]] = {}
    all_pair_times: list[float] = []
    oom_events = 0
    failed: dict[str, dict[str, str]] = {}
    peak_vram = load_info.peak_vram_bytes or 0
    peak_rss = _rss_bytes() or 0
    score_started = time.perf_counter()
    for spec in selected:
        existing = completed.get(spec.query) or {}
        print(
            json.dumps({
                "query": spec.query,
                "resume_scores": len(existing),
                "remaining": len(paths) - len(existing),
            }, ensure_ascii=False),
            flush=True,
        )
        scores, stats = _score_query_images(
            reranker,
            spec.query,
            paths,
            instruction=MEANING_INSTRUCTION,
            batch_size=max(1, args.batch_size),
            max_pixels=args.max_pixels,
            scores_path=scores_path,
            existing=existing,
        )
        scores_by_query[spec.query] = scores
        all_pair_times.extend(stats["pair_times"])
        oom_events += int(stats["oom_events"])
        if stats["failed"]:
            failed[spec.query] = stats["failed"]
        peak_vram = max(peak_vram, int(stats["peak_vram_bytes"] or 0))
        peak_rss = max(peak_rss, int(stats["peak_rss_bytes"] or 0))
        print(
            json.dumps({
                "query": spec.query,
                "scored": len(scores),
                "failed": len(stats["failed"]),
                "mean_pair_seconds": (
                    None if not stats["pair_times"] else
                    sum(stats["pair_times"]) / len(stats["pair_times"])
                ),
            }, ensure_ascii=False),
            flush=True,
        )
    total_score_seconds = time.perf_counter() - score_started
    mean_pair = None if not all_pair_times else sum(all_pair_times) / len(all_pair_times)
    all_scores = [
        score
        for query_scores in scores_by_query.values()
        for score in query_scores.values()
    ]
    primary = _metrics_for_threshold(
        dataset, selected, scores_by_query, ranking, args.threshold
    )
    sensitivity = [
        {
            "threshold": threshold,
            "splits": _metrics_for_threshold(
                dataset, selected, scores_by_query, ranking, threshold
            )["splits"],
        }
        for threshold in SENSITIVITY_THRESHOLDS
    ]
    hybrid_payload = _json_load(HYBRID_RESULTS)
    judge_payload = _json_load(JUDGE_RESULTS)
    hybrid_by_query = _rows_by_query(hybrid_payload, path=("query_rows", "C"))
    judge_e2e = ((judge_payload or {}).get("end_to_end") or {}).get("queries") or []
    judge_by_query = {row["query"]: row for row in judge_e2e}
    comparison_rows = _compare_baselines(primary["queries"], hybrid_by_query, judge_by_query)
    nested = _nested_dog_view(scores_by_query, args.threshold)
    verdict = _verdict(primary, nested, comparison_rows)
    git = git_identity()
    runtime = {
        "model_id": args.model_id,
        "model_revision": load_info.revision,
        "snapshot_path": str(snapshot_path),
        "model_download_bytes": download_bytes,
        "download_seconds": download_seconds,
        "quantization": load_info.quantization,
        "torch_dtype": load_info.torch_dtype,
        "attn_implementation": load_info.attn_implementation,
        "max_pixels": args.max_pixels,
        "batch_size": args.batch_size,
        "load_seconds": load_info.load_seconds,
        "mean_pair_seconds": mean_pair,
        "total_score_seconds": total_score_seconds,
        "pairs": sum(len(values) for values in scores_by_query.values()),
        "peak_vram_bytes": peak_vram,
        "allocated_after_load_bytes": load_info.allocated_vram_bytes,
        "nvidia_used_before_bytes": nvidia_before,
        "nvidia_used_bytes": _nvidia_used_bytes(),
        "rss_before_bytes": rss_before,
        "peak_rss_bytes": peak_rss,
        "oom_events": oom_events,
        "failed": failed,
        "batch_probe": probe,
        "score_histogram": _histogram(all_scores),
        "score_stats": {
            "n": len(all_scores),
            "min": None if not all_scores else min(all_scores),
            "max": None if not all_scores else max(all_scores),
            "mean": None if not all_scores else sum(all_scores) / len(all_scores),
        },
    }
    uncertain32 = {
        "assumed_images_per_query": 32,
        "seconds_per_query_32": None if mean_pair is None else mean_pair * 32,
        "seconds_10q_32": None if mean_pair is None else mean_pair * 32 * 10,
        "seconds_35q_32": None if mean_pair is None else mean_pair * 32 * 35,
        "minutes_35q_32": None if mean_pair is None else (mean_pair * 32 * 35) / 60.0,
        "note": "Uses measured mean pair time. Hybrid C mean uncertain/query is 32.0.",
    }
    report = {
        "identity": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_commit": git["git_commit"],
            "git_dirty": git["git_dirty"],
            "model_id": args.model_id,
            "model_revision": load_info.revision,
            "quantization": load_info.quantization,
            "torch_dtype": load_info.torch_dtype,
            "instruction_version": INSTRUCTION_VERSION,
            "primary_threshold": args.threshold,
            "threshold_policy": (
                "Official API returns sigmoid(yes-no). No published binary cutoff. "
                "Primary 0.5 is the a-priori yes>no boundary. Hold-out queries were "
                "not used to select it. Sensitivity is reported, not selected."
            ),
            "query_set_version": dataset.query_set_version,
            "query_set_hash": dataset.query_set_hash,
            "gt_version": dataset.gt_version,
            "gt_hash": dataset.gt_hash,
            "corpus_count": corpus["count"],
            "corpus_sha256": corpus["names_sizes_sha256"],
            "stage": "smoke" if args.smoke else args.stage,
        },
        "instruction": MEANING_INSTRUCTION,
        "system_prompt": (
            "Judge whether the Document meets the requirements based on the Query "
            'and the Instruct provided. Note that the answer can only be "yes" or "no".'
        ),
        "folder": str(args.folder),
        "splits": {
            "dev": [spec.query for spec in selected if spec.split == "dev"],
            "holdout": [spec.query for spec in selected if spec.split == "holdout"],
        },
        "holdout_not_used_for_threshold": sorted(HOLDOUT_FOCUS),
        "runtime": runtime,
        "primary": {
            "threshold": args.threshold,
            "splits": primary["splits"],
            "queries": [_query_snapshot(row) | {
                "false_negatives": row["false_negatives"],
                "false_positives": row["false_positives"],
            } for row in primary["queries"]],
        },
        "sensitivity": sensitivity,
        "nested_dog": nested,
        "comparison_rows": comparison_rows,
        "uncertain32_estimate": uncertain32,
        "verdict": verdict,
        "end_to_end": primary,
    }
    results_path = output_dir / "results.json"
    summary_path = output_dir / "summary.md"
    analysis_path = output_dir / "qwen-analysis.md"
    results_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_text = render_summary(report)
    summary_path.write_text(summary_text, encoding="utf-8")
    analysis_path.write_text(summary_text, encoding="utf-8")
    print(results_path)
    print(summary_path)
    print(json.dumps({"verdict": verdict}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
