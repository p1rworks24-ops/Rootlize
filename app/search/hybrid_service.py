"""Rank-based fusion of the existing text and semantic searches."""
from __future__ import annotations

from pathlib import Path

from app.ocr.exceptions import OCRRecordNotFoundError
from app.ocr.search_service import MAX_LIMIT

from .hybrid_models import HybridSearchPage, HybridSearchResult

# Ranking policy lives here so it can be tuned without changing either search.
RRF_RANK_CONSTANT = 60
MIN_CANDIDATE_LIMIT = 100
MAX_CANDIDATE_LIMIT = MAX_LIMIT


class HybridSearchService:
    """Run both searches and combine their ranks using reciprocal rank fusion."""

    def __init__(self, text_search, semantic_search, image_repository=None):
        self.text_search = text_search
        self.semantic_search = semantic_search
        self.image_repository = image_repository or getattr(text_search, "repository", None)

    def search(
        self,
        query: str,
        top_k: int,
        *,
        folder_path: str | Path | None = None,
        candidate_limit: int | None = None,
    ) -> HybridSearchPage:
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError("top_k must be an integer.")
        if top_k < 0:
            raise ValueError("top_k must not be negative.")
        raw_query = str(query or "")
        if top_k == 0:
            return HybridSearchPage(raw_query, 0, 0, 0, ())

        limit = self._candidate_limit(top_k, candidate_limit)
        text_page = self.text_search.search_images(
            raw_query, folder_path=folder_path, limit=limit, offset=0
        )
        text_results = tuple(text_page.results)

        semantic_failed = False
        try:
            semantic_results = tuple(
                self.semantic_search.search(
                    raw_query, limit, folder_path=str(folder_path) if folder_path is not None else None
                )
            )
        except Exception:
            # Model load, worker, and semantic storage failures must not discard
            # otherwise valid filename/tag/OCR matches.
            semantic_results = ()
            semantic_failed = True

        fused: dict[int, dict] = {}
        for rank, result in enumerate(text_results, 1):
            fused[result.image_id] = {
                "score": self._rrf(rank), "text_rank": rank,
                "semantic_rank": None, "text_result": result,
                "semantic_similarity": None,
            }
        for rank, result in enumerate(semantic_results, 1):
            item = fused.setdefault(result.image_id, {
                "score": 0.0, "text_rank": None, "semantic_rank": None,
                "text_result": None, "semantic_similarity": None,
            })
            item["score"] += self._rrf(rank)
            item["semantic_rank"] = rank
            item["semantic_similarity"] = result.similarity

        results = []
        for image_id, item in fused.items():
            text_result = item["text_result"]
            if text_result is not None:
                path, filename = text_result.path, text_result.filename
            else:
                if self.image_repository is None:
                    continue
                try:
                    image = self.image_repository.get_image(image_id)
                except OCRRecordNotFoundError:
                    continue
                path, filename = image.path, image.filename
            results.append(HybridSearchResult(
                image_id, path, filename, item["score"], item["text_rank"],
                item["semantic_rank"], text_result, item["semantic_similarity"],
            ))

        # image_id is the final key, making equal RRF scores stable across runs.
        results.sort(key=lambda result: (-result.score, result.image_id))
        total_count = len(results)
        returned = tuple(results[:top_k])
        return HybridSearchPage(
            raw_query, top_k, total_count, len(returned), returned, semantic_failed
        )

    @staticmethod
    def _rrf(rank: int) -> float:
        return 1.0 / (RRF_RANK_CONSTANT + rank)

    @staticmethod
    def _candidate_limit(top_k: int, candidate_limit: int | None) -> int:
        if candidate_limit is not None:
            if not isinstance(candidate_limit, int) or isinstance(candidate_limit, bool):
                raise TypeError("candidate_limit must be an integer.")
            if candidate_limit < 0:
                raise ValueError("candidate_limit must not be negative.")
        requested = max(top_k, candidate_limit or MIN_CANDIDATE_LIMIT)
        return min(requested, MAX_CANDIDATE_LIMIT)
