"""Official Meaning-search evaluation runner (Phase D).

Evaluates the frozen product retriever and, optionally, Retriever → Vision
Judge → ranking. Query labels never enter app/ product code.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.relevance.openai_provider import (
    SCHEMA_VERSION,
    OpenAIImageRelevanceProvider,
)
from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING, QUERY_EMBEDDING_RAW
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.describe_judge import (
    DESCRIBE_SCHEMA_VERSION,
    JUDGE_SCHEMA_VERSION,
    TEXT_JUDGE_SCHEMA_VERSION,
    add_usage,
    empty_usage,
    estimate_usd,
    judge_ranked_paths_described,
    load_description_cache,
    load_or_describe_paths,
    save_description_cache,
)
from tools.meaning_eval.failure import empty_mode_counts
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.judge_candidates import (
    CANDIDATES,
    DESCRIBE_STRUCTURES,
    STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE,
)
from tools.meaning_eval.metrics import summarize_end_to_end, summarize_retriever
from tools.meaning_eval.pipeline import judge_ranked_paths
from tools.meaning_eval.report import compare_runs, latest_previous_results, write_report
from tools.meaning_eval.evaluate_semantic_index import _load_name_set
from tools.meaning_eval.scoring import end_to_end_row, retriever_row
from tools.retriever_eval import (
    encode_query,
    list_images,
    load_runtime,
    rank_names,
)
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"


def _encode_corpus(runtime, paths: list[Path]) -> tuple[list[str], list[list[float]], list[str]]:
    names = []
    vectors = []
    failed = []
    for path in paths:
        try:
            vectors.append(runtime.embed_image(path))
            names.append(path.name)
        except Exception:
            failed.append(path.name)
    return names, vectors, failed


def _providers(candidate_name: str = "baseline"):
    spec = CANDIDATES[candidate_name]
    if spec.structure in DESCRIBE_STRUCTURES:
        raise ValueError(f"{spec.name} does not use the two-stage relevance provider pair.")
    low_kwargs = {"max_edge": 512, "image_detail": "low", "temperature": 0}
    high_kwargs = {"max_edge": 2048, "image_detail": "high", "temperature": 0}
    if spec.low_prompt is not None:
        low_kwargs["system_prompt"] = spec.low_prompt
        low_kwargs["prompt_version"] = spec.version
    if spec.high_prompt is not None:
        high_kwargs["system_prompt"] = spec.high_prompt
        high_kwargs["prompt_version"] = spec.version
    return (
        OpenAIImageRelevanceProvider(**low_kwargs),
        OpenAIImageRelevanceProvider(**high_kwargs),
    )


def _load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["query"]] = row
    return rows


def _add_modes(total: dict[str, int], row: dict) -> None:
    for mode, count in row["failure_mode_counts"].items():
        total[mode] = total.get(mode, 0) + int(count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase D Meaning-search evaluation")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--split", choices=("dev", "holdout", "both"), default="both")
    parser.add_argument("--retriever-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--candidate",
        choices=tuple(CANDIDATES),
        default="baseline",
        help="Judge candidate. baseline is the product vision-meaning-v1 pair.",
    )
    parser.add_argument(
        "--description-cache",
        type=Path,
        help="Reuse query-independent Stage 1 descriptions JSON (describe-judge-v1).",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Limit to this query. Repeatable. Labels still stay out of product code.",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not overwrite artifacts/meaning-eval/latest. Use for A/B candidates.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse e2e-checkpoint.jsonl rows already completed in --output-dir.",
    )
    parser.add_argument("--compare-with", type=Path, help="Previous results.json to compare")
    parser.add_argument(
        "--match-corpus-from",
        type=Path,
        help="Optional name list/JSON used to keep the same frozen 119-image corpus.",
    )
    args = parser.parse_args()

    dataset = load_dataset(args.gt)
    selected = dataset.queries
    if args.split != "both":
        selected = tuple(spec for spec in dataset.queries if spec.split == args.split)
    if args.queries:
        wanted = list(dict.fromkeys(args.queries))
        by_name = {spec.query: spec for spec in selected}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            raise SystemExit(f"Unknown --query values: {missing}")
        selected = tuple(by_name[name] for name in wanted)
    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
        missing = keep_names - {path.name for path in paths}
        if missing:
            raise SystemExit(f"match-corpus-from names missing from folder: {sorted(missing)[:8]}")
    corpus = corpus_identity(paths)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or (RUNS_DIR / stamp)

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity
    print(f"encoding {len(paths)} images", flush=True)
    embedded_names, image_vectors, embed_failed = _encode_corpus(runtime, paths)
    embedded_set = set(embedded_names)
    query_vectors = {}
    for spec in selected:
        query_vectors[spec.query] = encode_query(runtime, spec.query, QUERY_EMBEDDING_RAW)

    retriever_rows = []
    rankings = {}
    for spec in selected:
        ranking = rank_names(query_vectors[spec.query], embedded_names, image_vectors)
        rankings[spec.query] = ranking
        retriever_rows.append(retriever_row(spec, ranking))
        print(
            f"retriever {spec.split} {spec.query!r} "
            f"R@10={retriever_rows[-1]['recall_at_10']:.3f} "
            f"R@20={retriever_rows[-1]['recall_at_20']:.3f} "
            f"R@40={retriever_rows[-1]['recall_at_40']:.3f} "
            f"R@80={retriever_rows[-1]['recall_at_80']:.3f}",
            flush=True,
        )

    candidate = CANDIDATES[args.candidate]
    schema_version = SCHEMA_VERSION
    if candidate.structure in DESCRIBE_STRUCTURES:
        judge_schema = (
            TEXT_JUDGE_SCHEMA_VERSION
            if candidate.structure == STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE
            else JUDGE_SCHEMA_VERSION
        )
        schema_version = f"{DESCRIBE_SCHEMA_VERSION}+{judge_schema}"
    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=candidate.version,
        schema_version=schema_version,
    )
    run_identity["judge_candidate"] = candidate.name
    run_identity["judge_structure"] = candidate.structure
    splits = dataset.by_split()
    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": embed_failed,
        "splits": {
            "dev": [spec.query for spec in splits["dev"]],
            "holdout": [spec.query for spec in splits["holdout"]],
        },
        "gt_corrections": list(dataset.gt_corrections),
        "acceptable_policy": dataset.acceptable_policy,
        "retriever": {
            "splits": {
                "dev": summarize_retriever([row for row in retriever_rows if row["split"] == "dev"]),
                "holdout": summarize_retriever([row for row in retriever_rows if row["split"] == "holdout"]),
            },
            "queries": retriever_rows,
        },
        "end_to_end": None,
    }

    if not args.retriever_only:
        describe_judge = candidate.structure in DESCRIBE_STRUCTURES
        text_only = candidate.structure == STRUCTURE_DESCRIBE_THEN_TEXT_JUDGE
        low_provider = high_provider = None
        if not describe_judge:
            low_provider, high_provider = _providers(args.candidate)
        path_by_name = {path.name: path for path in paths}
        e2e_rows = []
        mode_totals = empty_mode_counts()
        describe_usage = empty_usage()
        judge_usage = empty_usage()
        descriptions_by_name = {}
        description_cache_reused = False
        checkpoint = output_dir / "e2e-checkpoint.jsonl"
        judgements_path = output_dir / "judgements.jsonl"
        output_dir.mkdir(parents=True, exist_ok=True)
        if describe_judge:
            cache_path = args.description_cache or (output_dir / "descriptions.json")
            needed = {path.name for path in paths}
            cached = load_description_cache(cache_path)
            description_cache_reused = (
                cached is not None and needed <= set(cached[0])
            )
            print(f"describe-judge Stage 1 cache={cache_path} reused={description_cache_reused}", flush=True)
            descriptions_by_name, describe_usage = load_or_describe_paths(
                paths, cache_path
            )
            local_cache = output_dir / "descriptions.json"
            if local_cache.resolve() != cache_path.resolve():
                save_description_cache(local_cache, descriptions_by_name, describe_usage)
            print(
                json.dumps({
                    "stage": "describe",
                    "images": len(descriptions_by_name),
                    "unknown": sum(
                        1 for item in descriptions_by_name.values()
                        if item.get("unknown_reason")
                    ),
                    "cache_reused": description_cache_reused,
                    "request_count": describe_usage.get("request_count"),
                    "input_tokens": describe_usage.get("input_tokens"),
                    "output_tokens": describe_usage.get("output_tokens"),
                    "api_seconds": describe_usage.get("api_seconds"),
                }, ensure_ascii=False),
                flush=True,
            )
        if args.resume:
            completed = _load_checkpoint(checkpoint)
        else:
            completed = {}
            if checkpoint.exists():
                checkpoint.unlink()
            if judgements_path.exists():
                judgements_path.unlink()
        if completed:
            print(f"resuming {len(completed)} checkpointed queries", flush=True)
            for row in completed.values():
                add_usage(judge_usage, row.get("judge_usage"))
        for spec in selected:
            ranking = rankings[spec.query]
            if spec.query in completed:
                row = completed[spec.query]
                _add_modes(mode_totals, row)
                e2e_rows.append(row)
                print(
                    json.dumps({
                        "query": spec.query,
                        "split": spec.split,
                        "resumed": True,
                        "precision": row["precision"],
                        "recall": row["recall"],
                        "tp": row["tp"],
                        "fp": row["fp"],
                        "fn": row["fn"],
                    }, ensure_ascii=False),
                    flush=True,
                )
                continue
            ranked_paths = [path_by_name[name] for name in ranking if name in path_by_name]
            if describe_judge:
                judged = judge_ranked_paths_described(
                    spec.query,
                    ranked_paths,
                    descriptions_by_name,
                    text_only=text_only,
                )
                add_usage(judge_usage, judged.get("usage"))
            else:
                judged = judge_ranked_paths(
                    spec.query, ranked_paths, low_provider, high_provider
                )
            row = end_to_end_row(
                spec,
                ranking=ranking,
                predicted=judged["predicted"],
                judgements=judged["judgements"],
                cancelled=judged["cancelled"],
                failed_names=set(judged["failed_names"]),
                embedded_names=embedded_set,
            )
            if judged.get("usage"):
                row["judge_usage"] = judged["usage"]
            _add_modes(mode_totals, row)
            e2e_rows.append(row)
            if describe_judge:
                with judgements_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "query": spec.query,
                        "split": spec.split,
                        "predicted": judged["predicted"],
                        "judgements": judged["judgements"],
                    }, ensure_ascii=False) + "\n")
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                json.dumps({
                    "query": spec.query,
                    "split": spec.split,
                    "precision": row["precision"],
                    "recall": row["recall"],
                    "tp": row["tp"],
                    "fp": row["fp"],
                    "fn": row["fn"],
                }, ensure_ascii=False),
                flush=True,
            )
        report["end_to_end"] = {
            "splits": {
                "dev": summarize_end_to_end([row for row in e2e_rows if row["split"] == "dev"]),
                "holdout": summarize_end_to_end([row for row in e2e_rows if row["split"] == "holdout"]),
            },
            "failure_mode_counts": mode_totals,
            "queries": e2e_rows,
        }
        if describe_judge:
            describe_usd = estimate_usd(
                int(describe_usage.get("input_tokens") or 0),
                int(describe_usage.get("output_tokens") or 0),
            )
            judge_usd = estimate_usd(
                int(judge_usage.get("input_tokens") or 0),
                int(judge_usage.get("output_tokens") or 0),
            )
            total_usage = add_usage(empty_usage(), describe_usage)
            add_usage(total_usage, judge_usage)
            this_run_usage = dict(judge_usage) if description_cache_reused else total_usage
            n_images = len(paths)
            n_queries = len(selected)
            batches = 0 if n_images == 0 else (n_images + 19) // 20
            baseline_min_requests = n_queries * batches
            baseline_max_requests = n_queries * batches * 2
            candidate_requests = int(total_usage.get("request_count") or 0)
            this_run_requests = int(this_run_usage.get("request_count") or 0)
            if text_only:
                stage_notes = (
                    "Stage 1 is one shared query-independent describe per image. "
                    "Stage 2 judges every described image from query + description "
                    "only; original images are not resent. There is no true/false gate."
                )
                baseline_notes = (
                    "Baseline product judge: 1 low request per image plus 1 high "
                    "request if Stage 1 is true. Candidate A: 1 shared low describe "
                    "plus 1 high-detail image judge per image per query. Candidate B: "
                    "1 shared low describe plus 1 text-only judge per image per query. "
                    "Request multiplier uses batch-20 structural bounds, not a second "
                    "paid baseline run."
                )
            else:
                stage_notes = (
                    "Stage 1 is one shared query-independent describe per image. "
                    "Stage 2 judges every described image; there is no true/false gate."
                )
                baseline_notes = (
                    "Baseline product judge: 1 low request per image plus 1 high "
                    "request if Stage 1 is true. Candidate A: 1 shared low describe "
                    "plus 1 high judge per image per query. Request multiplier uses "
                    "batch-20 structural bounds, not a second paid baseline run."
                )
            report["cost"] = {
                "candidate": candidate.name,
                "structure": candidate.structure,
                "text_only_judge": text_only,
                "description_cache_reused": description_cache_reused,
                "requests_per_image_judgement": {
                    "describe": 1,
                    "judge": 1,
                    "stage2_sent_images": 0 if text_only else 1,
                    "notes": stage_notes,
                },
                "describe": describe_usage,
                "judge": judge_usage,
                "total": total_usage,
                "this_run": this_run_usage,
                "estimated_usd": {
                    "input_per_million": 0.75,
                    "output_per_million": 4.50,
                    "describe": round(describe_usd, 4),
                    "judge": round(judge_usd, 4),
                    "total": round(describe_usd + judge_usd, 4),
                    "this_run": round(
                        judge_usd if description_cache_reused else describe_usd + judge_usd,
                        4,
                    ),
                    "steady_state_cached_descriptions": round(judge_usd, 4),
                },
                "latency_seconds": {
                    "describe": 0.0 if description_cache_reused else describe_usage.get("api_seconds"),
                    "judge": judge_usage.get("api_seconds"),
                    "total": (
                        float(judge_usage.get("api_seconds") or 0.0)
                        if description_cache_reused else
                        total_usage.get("api_seconds")
                    ),
                    "wall_describe": 0.0 if description_cache_reused else describe_usage.get("total_seconds"),
                    "wall_judge": judge_usage.get("total_seconds"),
                    "wall_total": (
                        float(judge_usage.get("total_seconds") or 0.0)
                        if description_cache_reused else
                        total_usage.get("total_seconds")
                    ),
                    "describe_historical": describe_usage.get("api_seconds"),
                },
                "high_detail_image_count": 0 if text_only else int(judge_usage.get("sent_image_count") or 0),
                "stage2_sent_image_count": 0 if text_only else int(judge_usage.get("sent_image_count") or 0),
                "baseline_comparison": {
                    "notes": baseline_notes,
                    "candidate_requests": candidate_requests,
                    "this_run_requests": this_run_requests,
                    "baseline_min_requests": baseline_min_requests,
                    "baseline_max_requests": baseline_max_requests,
                    "request_multiplier": (
                        None if not baseline_min_requests else
                        round(candidate_requests / (
                            (baseline_min_requests + baseline_max_requests) / 2
                        ), 3)
                    ),
                    "request_multiplier_vs_baseline_min": (
                        None if not baseline_min_requests else
                        round(candidate_requests / baseline_min_requests, 3)
                    ),
                    "request_multiplier_vs_baseline_max": (
                        None if not baseline_max_requests else
                        round(candidate_requests / baseline_max_requests, 3)
                    ),
                    "this_run_multiplier_vs_baseline_min": (
                        None if not baseline_min_requests else
                        round(this_run_requests / baseline_min_requests, 3)
                    ),
                },
            }


    if args.compare_with is not None:
        previous = json.loads(args.compare_with.read_text(encoding="utf-8"))
    else:
        previous = latest_previous_results(RUNS_DIR, output_dir)
    report["comparison"] = compare_runs(report, previous)
    json_path, md_path = write_report(output_dir, report)
    if not args.no_latest:
        latest_dir = ROOT / "artifacts" / "meaning-eval" / "latest"
        write_report(latest_dir, report)
    print(json_path)
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
