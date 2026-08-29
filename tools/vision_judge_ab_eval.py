"""Phase B minimum A/B: object-presence judge vs usefulness judge.

Compares both judges on the same frozen candidate image set. Labels stay in
the existing evaluation file and are never sent to the Vision API or product
search path. This is not the Phase D evaluation platform.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.relevance import OpenAIImageRelevanceProvider, RelevanceImage
from app.relevance.openai_provider import SYSTEM_PROMPT as USEFULNESS_PROMPT

DEFAULT_FOLDER = Path(r"D:\07_Programs\shotlogue_test")
DEFAULT_LABELS = ROOT / "tools" / "semantic_search_benchmark" / "real_images" / "queries.json"

# Previously exercised labeled queries. Hold-out is everything else in the
# labels file. These names are evaluation-only and must not be imported by app/.
DEV_QUERIES = (
    "dog", "a dog", "dog photo", "Windows desktop",
    "Windows desktop screenshot", "code editor", "image search application",
    "browser window", "settings screen",
    "command prompt", "file explorer window", "video game screenshot",
    "mountain desktop wallpaper", "application error message",
)

OBJECT_PRESENCE_PROMPT = """You are a strict image-search relevance judge.
For every supplied image, decide whether the query target itself is visually
identifiable anywhere in the image.

Return true whenever the query target is visually identifiable, even if it is
not the main subject, is small or incidental, appears in the background or at
an edge, or is shown inside an app, web page, gallery, or thumbnail.

Return false when the target itself is not visually identifiable and the image
is only semantically or textually related. Query text alone does not establish
visual presence of the target.

A concrete object query such as 'dog' is true when a dog itself is visually
identifiable anywhere in the image, regardless of its size, position, or
presentation context.

Judge the visible image itself. Do not use similarity scores, filenames,
ranking, or assumed metadata.
Return exactly one result for every supplied image_id."""


def load_labels(path: Path) -> dict[str, set[str]]:
    return {
        item["query"]: set(item["relevant"])
        for item in json.loads(path.read_text(encoding="utf-8"))
    }


def split_queries(labeled_queries: list[str]) -> dict[str, list[str]]:
    labeled = list(labeled_queries)
    dev = [query for query in DEV_QUERIES if query in labeled]
    holdout = [query for query in labeled if query not in set(DEV_QUERIES)]
    return {"dev": dev, "holdout": holdout}


def metrics(expected: set[str], predicted: set[str]) -> dict:
    tp_names = sorted(expected & predicted)
    fp_names = sorted(predicted - expected)
    fn_names = sorted(expected - predicted)
    tp = len(tp_names)
    fp = len(fp_names)
    fn = len(fn_names)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "tp_names": tp_names, "fp_names": fp_names, "fn_names": fn_names,
    }


def failure_reasons(
    expected: set[str],
    predicted: set[str],
    judgements: dict[str, dict],
) -> dict:
    reasons = {"false_positives": [], "false_negatives": [], "unknown": []}
    for name in sorted(predicted - expected):
        item = judgements.get(name, {})
        reasons["false_positives"].append({
            "name": name,
            "reason": item.get("reason", ""),
            "relevance_score": item.get("relevance_score"),
        })
    for name in sorted(expected - predicted):
        item = judgements.get(name, {})
        if item.get("relevant") is None:
            reasons["unknown"].append({
                "name": name,
                "unknown_reason": item.get("unknown_reason"),
            })
        else:
            reasons["false_negatives"].append({
                "name": name,
                "reason": item.get("reason", ""),
                "relevance_score": item.get("relevance_score"),
            })
    return reasons


def ranked_names(judgements: dict[str, dict], embedding_order: list[str]) -> list[str]:
    relevant = [name for name in embedding_order if judgements.get(name, {}).get("relevant") is True]
    relevant.sort(
        key=lambda name: (
            -(judgements[name].get("relevance_score") or 0.0),
            embedding_order.index(name),
        )
    )
    return relevant


def compare_query(
    query: str,
    expected: set[str] | None,
    old_judgements: dict[str, dict],
    new_judgements: dict[str, dict],
    embedding_order: list[str],
    split: str,
) -> dict:
    old_predicted = {
        name for name, item in old_judgements.items() if item.get("relevant") is True
    }
    new_predicted = {
        name for name, item in new_judgements.items() if item.get("relevant") is True
    }
    old_unknown = {
        name for name, item in old_judgements.items() if item.get("relevant") is None
    }
    new_unknown = {
        name for name, item in new_judgements.items() if item.get("relevant") is None
    }
    labeled = expected is not None
    expected_set = expected or set()
    old_metrics = metrics(expected_set, old_predicted) if labeled else None
    new_metrics = metrics(expected_set, new_predicted) if labeled else None
    return {
        "query": query,
        "split": split,
        "labeled": labeled,
        "old": {
            **(old_metrics or {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None, "tp_names": [], "fp_names": [], "fn_names": []}),
            "predicted": sorted(old_predicted),
            "unknown_count": len(old_unknown),
            "unknown_names": sorted(old_unknown),
            "ranked": ranked_names(old_judgements, embedding_order),
            "failures": failure_reasons(expected_set, old_predicted, old_judgements) if labeled else None,
        },
        "new": {
            **(new_metrics or {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None, "f1": None, "tp_names": [], "fp_names": [], "fn_names": []}),
            "predicted": sorted(new_predicted),
            "unknown_count": len(new_unknown),
            "unknown_names": sorted(new_unknown),
            "ranked": ranked_names(new_judgements, embedding_order),
            "failures": failure_reasons(expected_set, new_predicted, new_judgements) if labeled else None,
        },
    }


def _provider(*, usefulness: bool) -> OpenAIImageRelevanceProvider:
    if usefulness:
        return OpenAIImageRelevanceProvider(
            batch_size=int(os.environ.get("CAPIXE_VISION_BATCH_SIZE", "20")),
            max_workers=int(os.environ.get("CAPIXE_VISION_PARALLEL", "2")),
            retries=0,
            unknown_retries=2,
        )
    return OpenAIImageRelevanceProvider(
        batch_size=int(os.environ.get("CAPIXE_VISION_BATCH_SIZE", "20")),
        max_workers=int(os.environ.get("CAPIXE_VISION_PARALLEL", "2")),
        retries=0,
        unknown_retries=2,
        system_prompt=OBJECT_PRESENCE_PROMPT,
        prompt_version="vision-relevance-v1",
        include_relevance_score=False,
    )


def _judgements_from_run(run, names_by_id: dict[int, str]) -> dict[str, dict]:
    out = {}
    for item in run.results:
        name = names_by_id[item.image_id]
        out[name] = {
            "relevant": item.relevant,
            "confidence": item.confidence,
            "relevance_score": item.relevance_score,
            "reason": item.reason,
            "unknown_reason": item.unknown_reason,
        }
    return out


def summarize(entries: list[dict], judge_key: str) -> dict:
    labeled = [item for item in entries if item.get("labeled")]
    if not labeled:
        return {"queries": 0, "precision": None, "recall": None, "fp": 0, "fn": 0}
    precision = sum(item[judge_key]["precision"] for item in labeled) / len(labeled)
    recall = sum(item[judge_key]["recall"] for item in labeled) / len(labeled)
    return {
        "queries": len(labeled),
        "macro_precision": precision,
        "macro_recall": recall,
        "fp": sum(item[judge_key]["fp"] for item in labeled),
        "fn": sum(item[judge_key]["fn"] for item in labeled),
        "unknown": sum(item[judge_key]["unknown_count"] for item in labeled),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--query", action="append")
    parser.add_argument("--split", choices=("dev", "holdout", "both"), default="both")
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    truth = load_labels(args.labels)
    splits = split_queries(list(truth))
    holdout_set = set(splits["holdout"])
    dev_set = set(splits["dev"])
    if args.query:
        selected = []
        for query in args.query:
            if query in dev_set:
                selected.append(("dev", query))
            elif query in holdout_set:
                selected.append(("holdout", query))
            else:
                selected.append(("adhoc", query))
    elif args.split == "dev":
        selected = [("dev", query) for query in splits["dev"]]
    elif args.split == "holdout":
        selected = [("holdout", query) for query in splits["holdout"]]
    else:
        selected = (
            [("dev", query) for query in splits["dev"]]
            + [("holdout", query) for query in splits["holdout"]]
        )

    paths = sorted(
        path for path in args.folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if args.max_images > 0:
        paths = paths[: args.max_images]
    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    names_by_id = {item.image_id: item.path.name for item in images}
    embedding_order = [path.name for path in paths]
    old_provider = _provider(usefulness=False)
    new_provider = _provider(usefulness=True)
    report = {
        "folder": str(args.folder),
        "image_count": len(paths),
        "candidate_names": embedding_order,
        "prompt_new": USEFULNESS_PROMPT,
        "splits": splits,
        "queries": [],
    }
    for split, query in selected:
        old_run = old_provider.classify(query, images)
        new_run = new_provider.classify(query, images)
        entry = compare_query(
            query,
            truth.get(query),
            _judgements_from_run(old_run, names_by_id),
            _judgements_from_run(new_run, names_by_id),
            embedding_order,
            split,
        )
        report["queries"].append(entry)
        print(json.dumps({
            "query": query, "split": split,
            "old": {key: entry["old"][key] for key in ("precision", "recall", "fp", "fn", "unknown_count")},
            "new": {key: entry["new"][key] for key in ("precision", "recall", "fp", "fn", "unknown_count")},
        }, ensure_ascii=False), flush=True)
    report["summary"] = {
        "dev": {
            "old": summarize([item for item in report["queries"] if item["split"] == "dev"], "old"),
            "new": summarize([item for item in report["queries"] if item["split"] == "dev"], "new"),
        },
        "holdout": {
            "old": summarize([item for item in report["queries"] if item["split"] == "holdout"], "old"),
            "new": summarize([item for item in report["queries"] if item["split"] == "holdout"], "new"),
        },
        "adhoc": {
            "old": summarize([item for item in report["queries"] if item["split"] == "adhoc"], "old"),
            "new": summarize([item for item in report["queries"] if item["split"] == "adhoc"], "new"),
        },
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
