"""Read fresh Semantic Indexes to skip clear-negative Vision sends.

Does not generate indexes. Missing, stale, corrupt, or failed rows fall
back to Vision. Generation must stay on ProgressiveSemanticIndexer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.semantic.embedding import decode_embedding
from app.semantic_index.hybrid import (
    DECISION_NEGATIVE,
    DECISION_POSITIVE,
    DECISION_UNCERTAIN,
    PRODUCT_HYBRID_BAND,
    PRODUCT_SEARCH_CONFIG,
    decide_hybrid,
    uncertain_reason,
)
from app.semantic_index.models import (
    SemanticIndexIdentity,
    SemanticIndexState,
    default_index_identity,
)
from app.semantic_index.repository import SemanticIndexRepository
from app.semantic_index.scoring import index_judgement
from app.utils.logger import setup_logger

logger = setup_logger()

REASON_UNAVAILABLE = "index_unavailable"
REASON_GATE_FAILURE = "index_gate_failure"


@dataclass(frozen=True)
class HybridSplit:
    vision_ids: tuple[int, ...]
    negative_ids: tuple[int, ...]
    positive_ids: tuple[int, ...]
    reasons: dict[int, str] = field(default_factory=dict)
    decisions: dict[int, str] = field(default_factory=dict)


def _all_vision(
    candidates: Sequence[tuple[int, float | None]],
    reason: str,
) -> HybridSplit:
    vision_ids = tuple(image_id for image_id, _similarity in candidates)
    return HybridSplit(
        vision_ids=vision_ids,
        negative_ids=(),
        positive_ids=(),
        reasons={image_id: reason for image_id in vision_ids},
        decisions={image_id: DECISION_UNCERTAIN for image_id in vision_ids},
    )


def _score_fresh_index(
    *,
    query: str,
    query_vector: Sequence[float],
    img: float,
    record,
    ranking_model_id: str | None,
) -> tuple[str, str]:
    if ranking_model_id and record.embedding_model_id != ranking_model_id:
        return DECISION_UNCERTAIN, REASON_UNAVAILABLE
    dimension = int(record.embedding_dimension)
    if dimension != len(query_vector):
        return DECISION_UNCERTAIN, REASON_UNAVAILABLE
    text_vector = decode_embedding(record.text_embedding, dimension=dimension)
    metadata = dict(record.metadata)
    judgement = index_judgement(
        query,
        metadata,
        query_vector=query_vector,
        image_vector=None,
        text_vector=text_vector,
    )
    judgement["img"] = float(img)
    judgement["reason"] = (
        f"lex={judgement['lex']:.3f} txt={judgement['txt']:.3f} img={float(img):.3f}"
    )
    decision = decide_hybrid(
        judgement,
        PRODUCT_HYBRID_BAND,
        PRODUCT_SEARCH_CONFIG,
        query=query,
        record=metadata,
    )
    if decision == DECISION_NEGATIVE:
        return decision, "index_negative"
    if decision == DECISION_POSITIVE:
        return decision, "index_positive"
    return decision, uncertain_reason(
        judgement,
        PRODUCT_HYBRID_BAND,
        PRODUCT_SEARCH_CONFIG,
        query=query,
        record=metadata,
    )


def split_meaning_candidates(
    *,
    query: str,
    query_vector: Sequence[float] | None,
    candidates: Sequence[tuple[int, float | None]],
    repository: SemanticIndexRepository | None,
    identity: SemanticIndexIdentity | None = None,
    ranking_model_id: str | None = None,
) -> HybridSplit:
    """Partition ranked candidates. Fail open to Vision; never wait to generate."""
    if not candidates:
        return HybridSplit((), (), ())
    if query_vector is None or repository is None:
        return _all_vision(candidates, REASON_UNAVAILABLE)
    active = identity or default_index_identity()
    ids = [image_id for image_id, _similarity in candidates]
    try:
        states = repository.classify(ids, active)
    except Exception:
        logger.warning("semantic-index-hybrid classify-failure", exc_info=False)
        return _all_vision(candidates, REASON_GATE_FAILURE)

    vision_ids: list[int] = []
    negative_ids: list[int] = []
    positive_ids: list[int] = []
    reasons: dict[int, str] = {}
    decisions: dict[int, str] = {}
    for image_id, img in candidates:
        try:
            state = states.get(image_id, SemanticIndexState.PENDING)
            if state != SemanticIndexState.FRESH or img is None:
                decision, reason = DECISION_UNCERTAIN, REASON_UNAVAILABLE
            else:
                record = repository.get_index(image_id)
                if record is None:
                    decision, reason = DECISION_UNCERTAIN, REASON_UNAVAILABLE
                else:
                    decision, reason = _score_fresh_index(
                        query=query,
                        query_vector=query_vector,
                        img=img,
                        record=record,
                        ranking_model_id=ranking_model_id,
                    )
        except Exception:
            logger.warning(
                "semantic-index-hybrid candidate-failure image_id=%s",
                image_id,
                exc_info=False,
            )
            decision, reason = DECISION_UNCERTAIN, REASON_GATE_FAILURE
        decisions[image_id] = decision
        reasons[image_id] = reason
        if decision == DECISION_NEGATIVE:
            negative_ids.append(image_id)
        elif decision == DECISION_POSITIVE:
            positive_ids.append(image_id)
        else:
            vision_ids.append(image_id)
    return HybridSplit(
        vision_ids=tuple(vision_ids),
        negative_ids=tuple(negative_ids),
        positive_ids=tuple(positive_ids),
        reasons=reasons,
        decisions=decisions,
    )
