"""Phase D Meaning-search evaluation platform.

Labels, splits, and query kinds stay in this package. They must not be
imported by product search code under app/.
"""

from .dataset import (
    ACCEPTABLE_POLICY_NAME,
    EvalDataset,
    QUERY_KINDS,
    SPLITS,
    load_dataset,
)
from .failure import classify_false_negative, classify_false_positive
from .metrics import (
    end_to_end_counts,
    mean_reciprocal_rank,
    recall_at_k,
    relevant_ranks,
    summarize_end_to_end,
    summarize_retriever,
)

__all__ = [
    "ACCEPTABLE_POLICY_NAME",
    "EvalDataset",
    "QUERY_KINDS",
    "SPLITS",
    "classify_false_negative",
    "classify_false_positive",
    "end_to_end_counts",
    "load_dataset",
    "mean_reciprocal_rank",
    "recall_at_k",
    "relevant_ranks",
    "summarize_end_to_end",
    "summarize_retriever",
]
