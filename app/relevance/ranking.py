from __future__ import annotations

from collections.abc import Mapping, Sequence


def rank_relevant_ids(
    image_ids: Sequence[int],
    *,
    relevant_ids: set[int],
    relevance_scores: Mapping[int, float | None],
    embedding_ranks: Mapping[int, int],
) -> tuple[int, ...]:
    """Order confirmed matches by Vision score, then embedding rank.

    Missing scores are not stored as 0. They only tie-break among already
    confirmed `relevant=True` ids so unspecified mock scores keep embedding
    order. Unknown ids are excluded because they are not in `relevant_ids`.
    """
    confirmed = [image_id for image_id in image_ids if image_id in relevant_ids]

    def sort_key(image_id: int) -> tuple[float, int, int]:
        score = relevance_scores.get(image_id)
        numeric = 0.0 if score is None else float(score)
        return (-numeric, embedding_ranks.get(image_id, 10**9), image_id)

    confirmed.sort(key=sort_key)
    return tuple(confirmed)
