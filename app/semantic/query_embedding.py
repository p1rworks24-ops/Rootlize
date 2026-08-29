"""Shared query-text encoding for product search and retriever evaluation.

Templates are applied the same way to every query. There is no per-query
template switching and no query-type classifier.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

QUERY_EMBEDDING_RAW = "raw"
QUERY_EMBEDDING_TEMPLATE_ENSEMBLE = "template_ensemble"
DEFAULT_QUERY_EMBEDDING = QUERY_EMBEDDING_RAW

QUERY_EMBEDDING_METHODS = frozenset({
    QUERY_EMBEDDING_RAW,
    QUERY_EMBEDDING_TEMPLATE_ENSEMBLE,
})

QUERY_TEMPLATES = (
    "{q}",
    "an image of {q}",
    "a screenshot related to {q}",
)


def normalize_query_embedding_method(value: object) -> str:
    method = str(value or "").strip().lower()
    return method if method in QUERY_EMBEDDING_METHODS else DEFAULT_QUERY_EMBEDDING


def query_texts(query: str, method: object = None) -> tuple[str, ...]:
    text = str(query or "").strip()
    if not text:
        return ()
    method = normalize_query_embedding_method(method)
    if method == QUERY_EMBEDDING_RAW:
        return (text,)
    return tuple(template.format(q=text) for template in QUERY_TEMPLATES)


def combine_normalized_embeddings(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Mean-pool L2-normalized embeddings, then L2-normalize the mean."""
    if not vectors:
        raise ValueError("No query embeddings to combine.")
    dimension = len(vectors[0])
    if dimension <= 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("Query embeddings must share a positive dimension.")
    if len(vectors) == 1:
        return tuple(float(value) for value in vectors[0])
    summed = [0.0] * dimension
    for vector in vectors:
        for index, value in enumerate(vector):
            summed[index] += float(value)
    scale = 1.0 / len(vectors)
    mean = [value * scale for value in summed]
    norm = math.sqrt(sum(value * value for value in mean))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("Combined query embedding is not L2 normalizable.")
    return tuple(value / norm for value in mean)
