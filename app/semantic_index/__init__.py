"""Query-independent Semantic Index persistence, generation, and Hybrid gating.

Progressive generation starts from the first consented Ask AI send.
Fresh indexes are read by Meaning Search to skip clear-negative Vision
sends. Folder auto-prep does not generate indexes.
"""

from .models import (
    SemanticIndexIdentity,
    SemanticIndexJobResult,
    SemanticIndexState,
    default_index_identity,
)
from .provider import IndexRun, SemanticIndexProvider, make_index_provider
from .repository import SemanticIndexRepository
from .schema import (
    INDEX_FIELDS,
    INDEX_PROMPT,
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    INDEX_USER_PREFIX,
    clip_index_text,
    empty_index_record,
    index_record,
    index_schema,
    metadata_only,
)
from .gate import HybridSplit, split_meaning_candidates
from .hybrid import (
    PRODUCT_HYBRID_BAND,
    PRODUCT_HYBRID_POLICY,
    decide_hybrid,
    decide_product_hybrid,
)
from .progressive import ProgressiveSemanticIndexer, make_product_progressive_indexer
from .scoring import PRODUCT_SEARCH_CONFIG, lexical_score
from .service import SemanticIndexService, make_index_service

__all__ = [
    "INDEX_FIELDS",
    "INDEX_PROMPT",
    "INDEX_PROMPT_VERSION",
    "INDEX_SCHEMA_VERSION",
    "INDEX_USER_PREFIX",
    "IndexRun",
    "SemanticIndexIdentity",
    "SemanticIndexJobResult",
    "SemanticIndexProvider",
    "SemanticIndexRepository",
    "ProgressiveSemanticIndexer",
    "SemanticIndexService",
    "SemanticIndexState",
    "clip_index_text",
    "default_index_identity",
    "empty_index_record",
    "index_record",
    "index_schema",
    "make_index_provider",
    "make_index_service",
    "make_product_progressive_indexer",
    "PRODUCT_HYBRID_BAND",
    "PRODUCT_HYBRID_POLICY",
    "PRODUCT_SEARCH_CONFIG",
    "HybridSplit",
    "decide_hybrid",
    "decide_product_hybrid",
    "lexical_score",
    "split_meaning_candidates",
]
