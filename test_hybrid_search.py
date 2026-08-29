from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.ocr.search_models import SearchPage, UnifiedSearchResult
from app.search.hybrid_service import HybridSearchService
from app.semantic.models import SemanticSearchResult


def text_result(image_id: int) -> UnifiedSearchResult:
    return UnifiedSearchResult(
        image_id, f"D:/Shots/{image_id}.png", f"{image_id}.png", image_id,
        True, False, False, ("filename",), 60, "substring", "none", "none",
        None, "pending",
    )


class TextSearch:
    def __init__(self, ids): self.ids = ids
    def search_images(self, query, **kwargs):
        results = tuple(text_result(value) for value in self.ids[:kwargs["limit"]])
        return SearchPage(query, query, len(self.ids), len(results), kwargs["limit"], 0, results, 0, "test")


class SemanticSearch:
    def __init__(self, ids=(), error=None): self.ids, self.error = ids, error
    def search(self, query, top_k, **kwargs):
        if self.error: raise self.error
        return [SemanticSearchResult(value, 1.0 - rank / 100) for rank, value in enumerate(self.ids[:top_k])]


@dataclass
class Image:
    image_id: int
    path: str
    filename: str


class Images:
    def get_image(self, image_id): return Image(image_id, f"D:/Shots/{image_id}.png", f"{image_id}.png")


def service(text=(), semantic=(), error=None):
    return HybridSearchService(TextSearch(list(text)), SemanticSearch(list(semantic), error), Images())


def ids(page): return [result.image_id for result in page.results]


def test_overlap_receives_both_rrf_contributions_and_ranks_first():
    page = service((1, 2), (3, 2)).search("query", 3)
    assert ids(page) == [2, 1, 3]
    assert page.results[0].text_rank == 2 and page.results[0].semantic_rank == 2
    assert page.results[0].score > page.results[1].score


@pytest.mark.parametrize(
    ("text", "semantic", "expected"),
    [((1, 2), (), [1, 2]), ((), (3, 4), [3, 4]), ((1,), (2,), [1, 2]), ((), (), [])],
)
def test_text_semantic_and_empty_combinations(text, semantic, expected):
    assert ids(service(text, semantic).search("query", 10)) == expected


def test_semantically_unprocessed_text_hit_remains():
    page = service((7,), ()).search("query", 10)
    assert ids(page) == [7]
    assert page.results[0].semantic_rank is None


def test_semantic_error_falls_back_to_text_results():
    page = service((1, 2), error=RuntimeError("worker failed")).search("query", 10)
    assert ids(page) == [1, 2]
    assert page.semantic_failed


def test_equal_scores_have_deterministic_image_id_order():
    assert ids(service((9, 3), (3, 9)).search("query", 10)) == [3, 9]


def test_top_k_zero_and_candidate_count_boundaries():
    hybrid = service(range(1, 6), ())
    assert hybrid.search("query", 0).results == ()
    assert ids(hybrid.search("query", 10)) == [1, 2, 3, 4, 5]
    assert ids(hybrid.search("query", 2)) == [1, 2]
    with pytest.raises(ValueError): hybrid.search("query", -1)
    with pytest.raises(TypeError): hybrid.search("query", True)
