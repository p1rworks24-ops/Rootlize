"""Eval-only JSON cache and local search over the product Semantic Index.

Scoring and Hybrid decision logic live in app.semantic_index so product
Meaning Search and evaluation cannot drift. This module keeps cache I/O
and eval-only search helpers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import json
from pathlib import Path

from app.relevance import RelevanceImage
from app.semantic_index.provider import (  # noqa: F401
    IndexRun,
    SemanticIndexProvider,
    make_index_provider,
)
from app.semantic_index.schema import (
    INDEX_PROMPT,
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    INDEX_USER_PREFIX,
    clip_index_text,
    empty_index_record,
    index_record,
    metadata_only,
    unknown_index_record,
    validate_index_payload,
)
from app.semantic_index.scoring import (  # noqa: F401
    GENERIC_MEDIA_TOKENS,
    PRIMARY_SEARCH,
    PRODUCT_SEARCH_CONFIG,
    STOPWORDS,
    TOKEN_RE,
    SearchConfig,
    combined_score,
    content_tokens,
    cosine,
    include_hit,
    incidental_text,
    index_judgement,
    lexical_score,
    lexical_text,
    primary_terms,
    token_forms,
    tokenize,
)
from tools.meaning_eval.describe_judge import (
    add_usage,
    empty_usage,
    usage_from_run,
)

SEARCH_VERSION = "semantic-index-local-v1"

# Eval-only sensitivity configs. hybrid_v1 is the product/Phase E config.
SEARCH_CONFIGS = (
    PRODUCT_SEARCH_CONFIG,
    SearchConfig("lex_0.50", 0.50, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("lex_0.34", 0.34, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("fusion_0.28", 1.01, 1.01, 0.0, 0.0, 0.28),
    SearchConfig("txt_0.24", 1.01, 0.0, 0.24, 0.0, 0.0),
)

# Compatibility alias used by older scoring helpers.
_token_forms = token_forms


def index_json_bytes(record: dict) -> int:
    payload = metadata_only(record)
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def measure_index_storage(
    records: dict[str, dict],
    *,
    embedding_dim: int = 512,
) -> dict:
    sizes = [index_json_bytes(record) for record in records.values()]
    n = len(sizes)
    mean_json = (sum(sizes) / n) if n else 0.0
    ordered = sorted(sizes)
    median_json = 0.0
    if ordered:
        mid = n // 2
        median_json = float(ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2)
    embedding_bytes = embedding_dim * 4
    per_image = mean_json + embedding_bytes
    return {
        "images": n,
        "json_bytes_mean": round(mean_json, 1),
        "json_bytes_median": round(median_json, 1),
        "json_bytes_min": min(sizes) if sizes else 0,
        "json_bytes_max": max(sizes) if sizes else 0,
        "text_embedding_float32_bytes": embedding_bytes,
        "per_image_new_bytes_mean": round(per_image, 1),
        "existing_image_embedding_float32_bytes": embedding_bytes,
        "per_image_total_with_existing_image_embedding": round(per_image + embedding_bytes, 1),
        "scale_new_bytes": {
            "1000": int(round(per_image * 1000)),
            "10000": int(round(per_image * 10000)),
            "100000": int(round(per_image * 100000)),
        },
        "scale_total_with_existing_image_embedding": {
            "1000": int(round((per_image + embedding_bytes) * 1000)),
            "10000": int(round((per_image + embedding_bytes) * 10000)),
            "100000": int(round((per_image + embedding_bytes) * 100000)),
        },
        "notes": (
            "New local cost is semantic JSON plus one 512-d float32 text "
            "embedding. OpenCLIP image embeddings already exist in product. "
            "Converted JPEGs are not stored."
        ),
    }


def load_index_cache(path: Path) -> tuple[dict[str, dict], dict] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != INDEX_PROMPT_VERSION:
        return None
    if payload.get("schema_version") != INDEX_SCHEMA_VERSION:
        return None
    by_name = payload.get("by_name")
    if not isinstance(by_name, dict):
        return None
    return by_name, dict(payload.get("usage") or empty_usage())


def save_index_cache(path: Path, by_name: dict[str, dict], usage: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt_version": INDEX_PROMPT_VERSION,
                "schema_version": INDEX_SCHEMA_VERSION,
                "usage": usage,
                "by_name": by_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def index_paths(
    paths: Sequence[Path],
    provider: SemanticIndexProvider,
    *,
    cancelled=None,
) -> tuple[dict[str, dict], dict]:
    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    run = provider.index(images, cancelled=cancelled)
    by_name = {}
    for item, result in zip(images, run.results):
        record = dict(result)
        record["image_id"] = item.image_id
        by_name[item.path.name] = record
    return by_name, usage_from_run(run)


def load_or_index_paths(
    paths: Sequence[Path],
    cache_path: Path,
    *,
    provider: SemanticIndexProvider | None = None,
    cancelled=None,
) -> tuple[dict[str, dict], dict, bool]:
    """Index each image once. Cached names are not resent."""
    needed = {path.name for path in paths}
    cached = load_index_cache(cache_path)
    by_name: dict[str, dict] = {}
    usage = empty_usage()
    if cached is not None:
        by_name, usage = cached
    missing = [
        path for path in paths
        if path.name not in by_name or (by_name[path.name] or {}).get("unknown_reason")
    ]
    reused = not missing and needed <= set(by_name)
    if missing:
        provider = provider or make_index_provider()
        fresh, fresh_usage = index_paths(missing, provider, cancelled=cancelled)
        by_name.update(fresh)
        add_usage(usage, fresh_usage)
        save_index_cache(cache_path, by_name, usage)
    elif cached is None:
        save_index_cache(cache_path, by_name, usage)
    return by_name, usage, reused


def search_records(
    query: str,
    names: Sequence[str],
    records: dict[str, dict],
    *,
    query_vector: Sequence[float] | None,
    image_vectors: dict[str, Sequence[float]],
    text_vectors: dict[str, Sequence[float]],
    config: SearchConfig,
) -> dict:
    scored = []
    judgements = {}
    failed_names = []
    for name in names:
        record = records.get(name) or empty_index_record(unknown_reason="missing")
        if record.get("unknown_reason"):
            failed_names.append(name)
            judgements[name] = {
                "relevant": None,
                "relevance_score": None,
                "confidence": None,
                "reason": record.get("unknown_reason"),
                "unknown_reason": record.get("unknown_reason"),
                "low_relevant": None,
                "high_relevant": None,
            }
            continue
        judged = index_judgement(
            query,
            record,
            query_vector=query_vector,
            image_vector=image_vectors.get(name),
            text_vector=text_vectors.get(name),
            config=config,
        )
        judged["low_relevant"] = None
        judged["high_relevant"] = None
        judgements[name] = judged
        if judged.get("relevant"):
            scored.append((judged["relevance_score"], name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    predicted = [name for _, name in scored]
    return {
        "predicted": predicted,
        "judgements": judgements,
        "failed_names": failed_names,
        "cancelled": False,
        "usage": empty_usage(),
    }


def dropped_must_include(
    *,
    spec,
    baseline_predicted: Iterable[str],
    poc_predicted: Iterable[str],
) -> list[str]:
    baseline_tp = set(baseline_predicted) & spec.must_include_set
    poc_tp = set(poc_predicted) & spec.must_include_set
    return sorted(baseline_tp - poc_tp)


# Compatibility aliases used by older eval helpers.
_validate_index_payload = validate_index_payload
_unknown_record = unknown_index_record
