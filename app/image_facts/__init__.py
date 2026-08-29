"""Query-independent image facts persistence and DB-only Meaning Search."""

from .contracts import (
    apply_color_contract,
    apply_facts_contracts,
    apply_same_entity_contract,
    apply_surface_contract,
    ensure_bound_conditions,
    enforce_condition_consistency,
    filter_query_conditions,
)
from .debug import local_match_trace
from .format import visible_content_is_text_mention
from .models import (
    ImageFactsIdentity,
    ImageFactsJobResult,
    ImageFactsState,
    default_facts_identity,
)
from .progressive import FactsPrepSnapshot, ProgressiveFactsIndexer, make_product_progressive_facts_indexer
from .provider import FactsRun, ImageFactsProvider, make_facts_provider
from .query import is_search_wrapper_condition, meaning_query_target
from .repository import ImageFactsRepository
from .schema import (
    FACTS_FIRST_CHUNK_SIZE,
    FACTS_PROMPT_VERSION,
    FACTS_SCHEMA_VERSION,
    FACTS_SEARCH_BATCH_SIZE,
    FACTS_SHORTLIST_SIZE,
    FACTS_VERSION,
    SEARCH_PROMPT_VERSION,
    SEARCH_SCHEMA_VERSION,
)
from .search import ImageFactsSearchMatcher, make_facts_search_matcher
from .service import ImageFactsService, make_facts_service

__all__ = [
    "FACTS_FIRST_CHUNK_SIZE",
    "FACTS_PROMPT_VERSION",
    "FACTS_SCHEMA_VERSION",
    "FACTS_SEARCH_BATCH_SIZE",
    "FACTS_SHORTLIST_SIZE",
    "FACTS_VERSION",
    "SEARCH_PROMPT_VERSION",
    "SEARCH_SCHEMA_VERSION",
    "is_search_wrapper_condition",
    "local_match_trace",
    "meaning_query_target",
    "visible_content_is_text_mention",
    "FactsPrepSnapshot",
    "FactsRun",
    "ImageFactsIdentity",
    "ImageFactsJobResult",
    "ImageFactsProvider",
    "ImageFactsRepository",
    "ImageFactsSearchMatcher",
    "ImageFactsService",
    "ImageFactsState",
    "ProgressiveFactsIndexer",
    "apply_color_contract",
    "apply_facts_contracts",
    "apply_same_entity_contract",
    "apply_surface_contract",
    "default_facts_identity",
    "ensure_bound_conditions",
    "enforce_condition_consistency",
    "filter_query_conditions",
    "make_facts_provider",
    "make_facts_search_matcher",
    "make_facts_service",
    "make_product_progressive_facts_indexer",
]
