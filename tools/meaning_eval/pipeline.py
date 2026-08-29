"""Product-faithful Retriever → two-stage Vision Judge → score ranking.

Chunk sizes and ranking match app.ui.images_search / app.relevance.ranking.
This module is evaluation-only and does not change product search.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from app.relevance import RelevanceImage, rank_relevant_ids
from app.ui.images_search import (
    VISION_CANDIDATE_CHUNK_SIZE,
    VISION_FIRST_CANDIDATE_CHUNK_SIZE,
    vision_candidate_chunk_sizes,
)

FIRST_CHUNK = VISION_FIRST_CANDIDATE_CHUNK_SIZE
CHUNK = VISION_CANDIDATE_CHUNK_SIZE


def candidate_chunk_sizes(total: int) -> list[int]:
    return vision_candidate_chunk_sizes(
        total, first_size=FIRST_CHUNK, chunk_size=CHUNK
    )


def _result_map(run) -> dict[int, object]:
    return {item.image_id: item for item in run.results}


def judge_ranked_paths(
    query: str,
    ranked_paths: Sequence[Path],
    low_provider,
    high_provider,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Run the product two-stage judge on an embedding-ranked path list."""
    relevance_images = [
        RelevanceImage(index, path) for index, path in enumerate(ranked_paths, 1)
    ]
    names_by_id = {item.image_id: item.path.name for item in relevance_images}
    embedding_ranks = {item.image_id: item.image_id for item in relevance_images}
    low_by_id = {}
    high_by_id = {}
    high_skipped = {}
    relevant_ids: set[int] = set()
    unknown_ids: set[int] = set()
    failed_ids: set[int] = set()
    cancelled_run = False
    offset = 0
    for chunk_size in candidate_chunk_sizes(len(relevance_images)):
        if cancelled is not None and cancelled():
            cancelled_run = True
            break
        chunk = relevance_images[offset:offset + chunk_size]
        offset += chunk_size
        low_run = low_provider.classify(query, chunk, cancelled=cancelled)
        failed_ids.update(low_run.failed_image_ids)
        low_by_id.update(_result_map(low_run))
        low_true = {
            item.image_id for item in low_run.results if item.relevant is True
        }
        low_unknown = set(low_run.failed_image_ids) | {
            item.image_id for item in low_run.results if item.relevant is None
        }
        unknown_ids.update(low_unknown)
        for item in chunk:
            if item.image_id in low_unknown:
                high_skipped[item.image_id] = "low_unknown"
            elif item.image_id not in low_true:
                high_skipped[item.image_id] = "low_false"
        high_chunk = tuple(item for item in chunk if item.image_id in low_true)
        if cancelled is not None and cancelled():
            cancelled_run = True
            for item in high_chunk:
                high_skipped[item.image_id] = "search_cancelled_before_high"
            break
        if not high_chunk:
            continue
        high_run = high_provider.classify(query, high_chunk, cancelled=cancelled)
        failed_ids.update(high_run.failed_image_ids)
        if cancelled is not None and cancelled():
            cancelled_run = True
            for item in high_chunk:
                high_skipped[item.image_id] = "search_cancelled_after_high"
            break
        high_by_id.update(_result_map(high_run))
        high_unknown = set(high_run.failed_image_ids) | {
            item.image_id for item in high_run.results if item.relevant is None
        }
        unknown_ids.update(high_unknown)
        for image_id in high_unknown:
            high_skipped[image_id] = "high_unknown"
        for item in high_run.results:
            if item.relevant is True:
                relevant_ids.add(item.image_id)
                unknown_ids.discard(item.image_id)
            elif item.relevant is False:
                unknown_ids.discard(item.image_id)

    scores = {}
    for image_id in relevant_ids:
        high_result = high_by_id.get(image_id)
        if high_result is not None and high_result.relevance_score is not None:
            scores[image_id] = high_result.relevance_score
            continue
        low_result = low_by_id.get(image_id)
        scores[image_id] = None if low_result is None else low_result.relevance_score
    ordered_ids = rank_relevant_ids(
        [item.image_id for item in relevance_images],
        relevant_ids=relevant_ids,
        relevance_scores=scores,
        embedding_ranks=embedding_ranks,
    )
    judgements = {}
    for item in relevance_images:
        image_id = item.image_id
        name = names_by_id[image_id]
        low_result = low_by_id.get(image_id)
        high_result = high_by_id.get(image_id)
        if image_id in relevant_ids:
            final = True
        elif image_id in unknown_ids:
            final = None
        elif low_result is None and high_result is None:
            final = None
        else:
            final = False
        unknown_reason = None
        if final is None:
            if high_result is not None and high_result.unknown_reason:
                unknown_reason = high_result.unknown_reason
            elif low_result is not None and low_result.unknown_reason:
                unknown_reason = low_result.unknown_reason
            else:
                unknown_reason = high_skipped.get(image_id)
        score = None
        if high_result is not None:
            score = high_result.relevance_score
        elif low_result is not None:
            score = low_result.relevance_score
        judgements[name] = {
            "relevant": final,
            "low_relevant": None if low_result is None else low_result.relevant,
            "high_relevant": None if high_result is None else high_result.relevant,
            "relevance_score": score,
            "low_relevance_score": None if low_result is None else low_result.relevance_score,
            "high_relevance_score": None if high_result is None else high_result.relevance_score,
            "reason": (
                None if high_result is None else high_result.reason
            ) or (
                None if low_result is None else low_result.reason
            ) or high_skipped.get(image_id),
            "unknown_reason": unknown_reason,
            "high_skipped_reason": high_skipped.get(image_id),
            "retrieval_rank": embedding_ranks[image_id],
        }
    predicted = [names_by_id[image_id] for image_id in ordered_ids]
    return {
        "predicted": predicted,
        "judgements": judgements,
        "cancelled": cancelled_run,
        "failed_names": sorted(names_by_id[image_id] for image_id in failed_ids if image_id in names_by_id),
        "unjudged_names": [
            item.path.name for item in relevance_images
            if item.image_id not in low_by_id and item.image_id not in unknown_ids
        ],
    }
