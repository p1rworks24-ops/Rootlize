"""Phase C retriever evaluation: product ONNX models and query embeddings.

Uses the labeled query file and the same dev/hold-out split as Phase B.
Labels never enter the product search path. Official Phase D metrics live in
tools/meaning_eval.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.semantic.bundle import load_bundle
from app.semantic.catalog import MODEL_IDS, OPENCLIP_MODEL_KEY, SIGLIP_MODEL_KEY
from app.semantic.query_embedding import (
    QUERY_EMBEDDING_RAW,
    QUERY_EMBEDDING_TEMPLATE_ENSEMBLE,
    combine_normalized_embeddings,
    query_texts,
)
from app.semantic.runtime import SemanticRuntime
from tools.vision_judge_ab_eval import (
    DEFAULT_FOLDER,
    DEFAULT_LABELS,
    DEV_QUERIES,
    load_labels,
    split_queries,
)

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KNOWN_GT_ISSUES = {}
DIAGNOSTIC_TARGETS = {
    "anime": ("test3.jpg",),
    "icon": (),
}
BUNDLE_DIRS = {
    OPENCLIP_MODEL_KEY: ROOT / "release" / "semantic-model-openclip-v1",
    SIGLIP_MODEL_KEY: ROOT / "release" / "semantic-model-v1",
}


def list_images(folder: Path) -> list[Path]:
    return sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )


def recall_at_k(relevant: set[str], ranking: list[str], k: int) -> float:
    if not relevant:
        return 1.0
    hits = sum(1 for name in ranking[:k] if name in relevant)
    return hits / len(relevant)


def mean_reciprocal_rank(relevant: set[str], ranking: list[str]) -> float:
    for index, name in enumerate(ranking, 1):
        if name in relevant:
            return 1.0 / index
    return 0.0


def relevant_ranks(relevant: set[str], ranking: list[str]) -> dict[str, int | None]:
    positions = {name: index for index, name in enumerate(ranking, 1)}
    return {name: positions.get(name) for name in sorted(relevant)}


def summarize_split(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "recall_at_10": 0.0, "recall_at_40": 0.0, "mrr": 0.0}
    return {
        "n": len(rows),
        "recall_at_10": sum(row["recall_at_10"] for row in rows) / len(rows),
        "recall_at_40": sum(row["recall_at_40"] for row in rows) / len(rows),
        "mrr": sum(row["mrr"] for row in rows) / len(rows),
    }


def rank_names(query_vector: list[float], names: list[str], image_vectors: list[list[float]]) -> list[str]:
    scores = [
        math.fsum(query_value * image_value for query_value, image_value in zip(query_vector, image_vector))
        for image_vector in image_vectors
    ]
    order = sorted(range(len(names)), key=lambda index: (-scores[index], names[index]))
    return [names[index] for index in order]


def encode_query(runtime: SemanticRuntime, query: str, method: str) -> list[float]:
    texts = query_texts(query, method)
    vectors = [runtime.embed_text(text) for text in texts]
    return list(combine_normalized_embeddings(vectors))


def evaluate_ranking(
    query: str,
    relevant: set[str],
    ranking: list[str],
    split: str,
) -> dict:
    ranks = relevant_ranks(relevant, ranking)
    return {
        "query": query,
        "split": split,
        "gt_issue": KNOWN_GT_ISSUES.get(query),
        "recall_at_10": recall_at_k(relevant, ranking, 10),
        "recall_at_40": recall_at_k(relevant, ranking, 40),
        "mrr": mean_reciprocal_rank(relevant, ranking),
        "best_relevant_rank": min((rank for rank in ranks.values() if rank is not None), default=None),
        "relevant_ranks": ranks,
        "missing_from_corpus": sorted(name for name, rank in ranks.items() if rank is None),
        "top10": ranking[:10],
    }


def evaluate_condition(
    runtime: SemanticRuntime,
    names: list[str],
    image_vectors: list[list[float]],
    labels: dict[str, set[str]],
    splits: dict[str, list[str]],
    method: str,
) -> dict:
    per_query = []
    for split_name, queries in splits.items():
        for query in queries:
            ranking = rank_names(
                encode_query(runtime, query, method), names, image_vectors
            )
            per_query.append(evaluate_ranking(query, labels[query], ranking, split_name))
    diagnostics = {}
    for query, targets in DIAGNOSTIC_TARGETS.items():
        ranking = rank_names(encode_query(runtime, query, method), names, image_vectors)
        diagnostics[query] = {
            "target_ranks": {
                name: ranking.index(name) + 1 if name in ranking else None
                for name in targets
            },
            "top10": ranking[:10],
        }
    by_split = {
        split_name: summarize_split([row for row in per_query if row["split"] == split_name])
        for split_name in splits
    }
    adoption = summarize_split(
        [row for row in per_query if row["query"] not in KNOWN_GT_ISSUES]
    )
    return {
        "query_embedding": method,
        "splits": by_split,
        "adoption_excluding_known_gt_issues": adoption,
        "queries": per_query,
        "diagnostics": diagnostics,
    }


def load_runtime(model_key: str) -> SemanticRuntime:
    bundle_dir = BUNDLE_DIRS[model_key]
    runtime = SemanticRuntime(load_bundle(bundle_dir))
    runtime.load(["image_encoder", "text_encoder"])
    return runtime


def encode_images(runtime: SemanticRuntime, paths: list[Path]) -> list[list[float]]:
    return [runtime.embed_image(path) for path in paths]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "retriever-eval.json")
    args = parser.parse_args()

    paths = list_images(args.folder)
    names = [path.name for path in paths]
    labels = load_labels(args.labels)
    splits = split_queries(list(labels))
    report = {
        "folder": str(args.folder),
        "image_count": len(paths),
        "dev_queries": splits["dev"],
        "holdout_queries": splits["holdout"],
        "known_gt_issues": KNOWN_GT_ISSUES,
        "models": [],
    }
    for model_key in (OPENCLIP_MODEL_KEY, SIGLIP_MODEL_KEY):
        print(f"loading {model_key} {MODEL_IDS[model_key]}", flush=True)
        runtime = load_runtime(model_key)
        identity = runtime.bundle.identity
        print(f"encoding {len(paths)} images", flush=True)
        image_vectors = encode_images(runtime, paths)
        model_report = {
            "model_key": model_key,
            "model_id": identity.model_id,
            "bundle_version": identity.bundle_version,
            "revision": identity.model_revision,
            "dimension": identity.dimension,
            "conditions": [],
        }
        for method in (QUERY_EMBEDDING_RAW, QUERY_EMBEDDING_TEMPLATE_ENSEMBLE):
            print(f"ranking {model_key} {method}", flush=True)
            model_report["conditions"].append(
                evaluate_condition(runtime, names, image_vectors, labels, splits, method)
            )
        report["models"].append(model_report)
        del runtime
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    for model in report["models"]:
        print(f"== {model['model_id']} ==")
        for condition in model["conditions"]:
            print(condition["query_embedding"], condition["splits"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
