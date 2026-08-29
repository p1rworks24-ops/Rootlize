"""Asynchronous bridge from the Images page to the unified search API."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import inspect
import logging
import threading
import time
import uuid

from PySide6.QtCore import QObject, QRunnable, Signal

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRRecordNotFoundError
from app.ocr.repository import OCRRepository
from app.ai_actions import AIActionService, ActionExecutor
from app.semantic.catalog import DEFAULT_MODEL_KEY, MODEL_IDS, key_for_model_id, normalize_model_key
from app.semantic.bundle import load_bundle
from app.semantic.models import SemanticDiffState
from app.semantic.installer import resolve_semantic_bundle
from app.search.hybrid_service import HybridSearchService
from app.relevance import (
    RelevanceImage,
    RelevanceProviderError,
    RelevanceResult,
    RelevanceRun,
    rank_relevant_ids,
)
from app.semantic.repository import SemanticRepository
from app.semantic.service import SemanticSearchService
from app.ai_usage.recorder import get_usage_recorder
from app.image_facts.models import default_facts_identity
from app.image_facts.query import meaning_query_target
from app.image_facts.repository import ImageFactsRepository
from app.image_facts.schema import FACTS_FIRST_CHUNK_SIZE, FACTS_SEARCH_BATCH_SIZE, FACTS_SHORTLIST_SIZE
from app.image_facts.search import ImageFactsSearchMatcher
from app.semantic.query_embedding import (
    DEFAULT_QUERY_EMBEDDING,
    normalize_query_embedding_method,
)
from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig
from app.semantic.worker_errors import ModelNotInstalledError
from app.paths import get_local_app_data_dir
from app.utils.logger import setup_logger

SearchCandidate = tuple[Path, tuple[str, ...]]
SearchProvider = Callable[[str, Path, Sequence[SearchCandidate]], tuple[Path, ...]]
ActionPlanProvider = Callable[[str, Path, Sequence[SearchCandidate]], tuple[object, tuple[Path, ...]]]
ActionExecutorProvider = Callable[[object, dict[int, Path], object], object]
logger = setup_logger()
SEMANTIC_SEARCH_LOG = get_local_app_data_dir() / "semantic-search.log"
VISION_FIRST_CANDIDATE_CHUNK_SIZE = FACTS_FIRST_CHUNK_SIZE
VISION_CANDIDATE_CHUNK_SIZE = FACTS_SEARCH_BATCH_SIZE


def vision_candidate_chunk_sizes(
    total: int,
    *,
    first_size: int = VISION_FIRST_CANDIDATE_CHUNK_SIZE,
    chunk_size: int = VISION_CANDIDATE_CHUNK_SIZE,
) -> list[int]:
    """First chunk is smaller so the first relevant result can appear sooner."""
    if total <= 0:
        return []
    first = min(max(1, first_size), total)
    sizes = [first]
    remaining = total - first
    while remaining > 0:
        take = min(chunk_size, remaining)
        sizes.append(take)
        remaining -= take
    return sizes


def _install_semantic_diagnostics_log() -> None:
    resolved = SEMANTIC_SEARCH_LOG.resolve()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == resolved:
            return
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)


_install_semantic_diagnostics_log()


def _installed_semantic_bundle(model_key=DEFAULT_MODEL_KEY) -> Path | None:
    bundle = resolve_semantic_bundle(model_key)
    return bundle.root if bundle is not None else None


class SemanticImagesSearchProvider:
    """Lazy, reusable Semantic worker bridge for the Images page."""

    def __init__(self, *, model_key=DEFAULT_MODEL_KEY, query_embedding_method=None) -> None:
        self._state_lock = threading.RLock()
        self.model_key = normalize_model_key(model_key)
        self.query_embedding_method = normalize_query_embedding_method(
            query_embedding_method
        )
        # Bundle validation hashes ~1.5 GB of model files. Defer it to the
        # existing search runnable instead of blocking page construction/UI.
        self.bundle_dir = None
        self.worker = SemanticWorkerClient(
            SemanticWorkerConfig(bundle_dir=self.bundle_dir)
        )
        self.last_search_trace = None
        self._closed = False
        self._prewarm_started = False

    def _ensure_bundle(self) -> Path | None:
        with self._state_lock:
            if self.bundle_dir is not None:
                return self.bundle_dir
            try:
                bundle_dir = _installed_semantic_bundle(self.model_key)
            except TypeError:  # Compatibility with injected legacy/test providers.
                bundle_dir = _installed_semantic_bundle()
            if bundle_dir is not None:
                self.bundle_dir = bundle_dir
                self.worker = SemanticWorkerClient(
                    SemanticWorkerConfig(bundle_dir=bundle_dir)
                )
            return bundle_dir

    def prewarm(self) -> None:
        """Start the worker and load the text encoder after UI bundle warmup."""
        with self._state_lock:
            if self._closed or self._prewarm_started:
                return
            self._prewarm_started = True

        def run() -> None:
            try:
                with self._state_lock:
                    if self._closed:
                        return
                    if self._ensure_bundle() is None and not self.worker.config.fake_mode:
                        return
                    self.worker.start()
                    self.worker.load_model(["text_encoder"])
                logger.info("Semantic worker prewarm ready")
            except Exception:
                logger.info("Semantic worker prewarm skipped", exc_info=True)

        threading.Thread(target=run, name="SemanticWorkerPrewarm", daemon=True).start()

    def _search_state(self) -> tuple[str, Path, SemanticWorkerClient]:
        if self._ensure_bundle() is None:
            raise ModelNotInstalledError("Image-content search files are not installed.")
        with self._state_lock:
            assert self.bundle_dir is not None
            return self.model_key, self.bundle_dir, self.worker

    def __call__(
        self,
        query: str,
        folder: Path,
        _candidates: Sequence[SearchCandidate],
    ) -> tuple[Path, ...]:
        with self._state_lock:
            model_key, bundle_dir, worker = self._search_state()
        database = OCRDatabase().open()
        try:
            images = OCRRepository(database)
            repository = SemanticRepository(database)
            service = SemanticSearchService(
                repository, images, worker,
                query_embedding_method=self.query_embedding_method,
            )
            # Retrieve every image in the active folder. Relevance filtering is
            # intentionally not approximated with a user-selected Top-N cap.
            top_k = len(_candidates)
            with self._state_lock:
                results = service.search(query.strip(), top_k, folder_path=str(folder))
            self.last_search_trace = service.last_search_trace
            try:
                bundle = load_bundle(bundle_dir)
                image_records = images.list_images(folder_path=folder, file_state="present")
                states = repository.classify_embeddings((item.image_id for item in image_records), bundle.identity)
                counts = {state: sum(value == state for value in states.values()) for state in SemanticDiffState}
                trace = service.last_search_trace
                worker_status = worker.get_status()
                worker_identity = worker_status.get("model_identity")
                candidate_identities = [] if trace is None else [
                    {
                        "model_id": value.model_id,
                        "bundle_version": value.bundle_version,
                        "revision": value.model_revision,
                        "dimension": value.dimension,
                    }
                    for value in trace.candidate_identities
                ]
                logger.info(
                    "Semantic-search summary query=%r developer_search_mode=semantic active_model_setting=%s "
                    "worker_model_identity=%s query_embedding_model_id=%s query_embedding_dimension=%s "
                    "query_embedding_method=%s query_text_count=%s "
                    "db_candidate_identities=%s ready=%d stale=%d missing=%d corrupt=%d failed=%d "
                    "ui_candidate_count=%d repository_candidate_count=%s service_candidate_count=%s service_result_count=%s",
                    query.strip(), model_key, worker_identity,
                    None if trace is None else trace.query_identity.model_id,
                    None if trace is None else trace.query_identity.dimension,
                    None if trace is None else trace.query_embedding_method,
                    None if trace is None else trace.query_text_count,
                    candidate_identities,
                    counts[SemanticDiffState.UNCHANGED], counts[SemanticDiffState.STALE_MODEL],
                    counts[SemanticDiffState.MISSING], counts[SemanticDiffState.CORRUPT],
                    counts[SemanticDiffState.FAILED], len(_candidates),
                    None if trace is None else trace.repository_candidate_count,
                    None if trace is None else trace.service_candidate_count,
                    None if trace is None else trace.result_count,
                )
                logger.info(
                    "Semantic-only diagnostic active_model=%s model_id=%s bundle_version=%s revision=%s dimension=%d ready=%d stale=%d missing=%d corrupt=%d failed=%d query=%r candidate_count=%d",
                    model_key, bundle.identity.model_id, bundle.identity.bundle_version,
                    bundle.identity.model_revision, bundle.identity.dimension,
                    counts[SemanticDiffState.UNCHANGED], counts[SemanticDiffState.STALE_MODEL],
                    counts[SemanticDiffState.MISSING], counts[SemanticDiffState.CORRUPT],
                    counts[SemanticDiffState.FAILED], query.strip(), len(_candidates),
                )
            except Exception:
                # Search results remain available if diagnostics cannot inspect
                # an injected provider or a concurrently changing database.
                logger.warning("Semantic-only diagnostics unavailable", exc_info=True)
            paths: list[Path] = []
            for rank, result in enumerate(results, 1):
                try:
                    image = images.get_image(result.image_id)
                except OCRRecordNotFoundError:
                    continue
                if image.file_state == "present":
                    logger.info(
                        "Semantic-only result query=%r rank=%d similarity=%.6f image_id=%d path=%s",
                        query.strip(),
                        rank, result.similarity, result.image_id, image.path,
                    )
                    paths.append(Path(image.path))
            return tuple(paths)
        finally:
            database.close()

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            self.worker.shutdown()

    def refresh_bundle(self) -> None:
        with self._state_lock:
            old_worker = self.worker
            self.bundle_dir = None
            self._prewarm_started = False
            self.worker = SemanticWorkerClient(
                SemanticWorkerConfig(bundle_dir=None)
            )
        threading.Thread(target=old_worker.shutdown, daemon=True).start()

    def set_model_key(self, value: object) -> bool:
        key = normalize_model_key(value)
        with self._state_lock:
            if key == self.model_key:
                return False
            old_worker = self.worker
            self.model_key = key
            self.bundle_dir = None
            self._prewarm_started = False
            self.worker = SemanticWorkerClient(
                SemanticWorkerConfig(bundle_dir=None)
            )
        threading.Thread(target=old_worker.shutdown, daemon=True).start()
        return True

    def set_query_embedding_method(self, value: object) -> bool:
        method = normalize_query_embedding_method(value)
        with self._state_lock:
            if method == self.query_embedding_method:
                return False
            self.query_embedding_method = method
        return True


class HybridImagesSearchProvider(SemanticImagesSearchProvider):
    """Lazy HybridSearchService bridge used by the Images search box."""

    def __call__(
        self,
        query: str,
        folder: Path,
        candidates: Sequence[SearchCandidate],
    ) -> tuple[Path, ...]:
        self._ensure_bundle()
        database = OCRDatabase().open()
        try:
            images = OCRRepository(database)
            _synchronize_candidates(images, candidates)
            semantic = (
                SemanticSearchService(
                    SemanticRepository(database), images, self.worker,
                    query_embedding_method=self.query_embedding_method,
                )
                if self.bundle_dir is not None
                else _UnavailableSemanticSearch()
            )
            page = HybridSearchService(images, semantic, images).search(
                query.strip(),
                min(max(len(candidates), 1), 500),
                folder_path=folder,
            )
            return tuple(Path(result.path) for result in page.results)
        finally:
            database.close()


class VisionRelevanceImagesSearchProvider(SemanticImagesSearchProvider):
    """OpenCLIP ranking followed by DB facts matching. Search sends no images."""

    CANDIDATE_CHUNK_SIZE = VISION_CANDIDATE_CHUNK_SIZE
    FIRST_CANDIDATE_CHUNK_SIZE = VISION_FIRST_CANDIDATE_CHUNK_SIZE
    SHORTLIST_SIZE = FACTS_SHORTLIST_SIZE

    def __init__(
        self,
        relevance_provider=None,
        high_relevance_provider=None,
        *,
        model_key=DEFAULT_MODEL_KEY,
        query_embedding_method=None,
        facts_matcher=None,
        facts_lookup=None,
    ) -> None:
        super().__init__(
            model_key=model_key, query_embedding_method=query_embedding_method
        )
        self.relevance_provider = relevance_provider
        self.high_relevance_provider = high_relevance_provider
        self.facts_matcher = facts_matcher
        self.facts_lookup = facts_lookup
        self.last_run = None
        self.last_timing = None
        self.last_hybrid_split = None
        self.last_vision_request_count = 0
        self.last_coverage = None
        self.last_query_target = ""
        self.last_raw_query = ""

    def _facts_matcher(self):
        if self.facts_matcher is None:
            self.facts_matcher = ImageFactsSearchMatcher()
        return self.facts_matcher

    def _load_fresh_facts(self, database, image_ids: Sequence[int]) -> dict[int, dict]:
        if self.facts_lookup is not None:
            return self.facts_lookup(image_ids)
        return ImageFactsRepository(database).fresh_facts_for_search(
            image_ids, default_facts_identity()
        )

    def _ensure_ranking_bundle(self) -> Path:
        bundle_dir = self._ensure_bundle()
        if bundle_dir is not None:
            return bundle_dir
        for key in MODEL_IDS:
            if key == self.model_key:
                continue
            self.set_model_key(key)
            bundle_dir = self._ensure_bundle()
            if bundle_dir is not None:
                return bundle_dir
        raise ModelNotInstalledError("Image-content search files are not installed.")

    def _rank_folder(self, query, folder, candidates, images, database, image_ids=None):
        with self._state_lock:
            return self._rank_folder_locked(
                query, folder, candidates, images, database, image_ids=image_ids
            )

    def _rank_folder_locked(self, query, folder, candidates, images, database, image_ids=None):
        semantic = SemanticSearchService(
            SemanticRepository(database), images, self.worker,
            query_embedding_method=self.query_embedding_method,
        )
        top_k = len(image_ids) if image_ids else len(candidates)
        ranked = semantic.search(
            query.strip(),
            max(top_k, 1),
            folder_path=str(folder),
            image_ids=image_ids,
        )
        self.last_search_trace = semantic.last_search_trace
        if ranked:
            return ranked
        trace = semantic.last_search_trace
        if trace is None:
            return ranked
        seen = {self.model_key}
        for identity in trace.candidate_identities:
            fallback = key_for_model_id(identity.model_id)
            if fallback is None or fallback in seen:
                continue
            seen.add(fallback)
            try:
                installed = _installed_semantic_bundle(fallback)
            except TypeError:
                installed = _installed_semantic_bundle()
            if installed is None:
                continue
            self.set_model_key(fallback)
            if self._ensure_bundle() is None:
                continue
            semantic = SemanticSearchService(
                SemanticRepository(database), images, self.worker,
                query_embedding_method=self.query_embedding_method,
            )
            ranked = semantic.search(
                query.strip(),
                max(top_k, 1),
                folder_path=str(folder),
                image_ids=image_ids,
            )
            self.last_search_trace = semantic.last_search_trace
            if ranked:
                fallback_identity = getattr(
                    semantic.last_search_trace, "query_identity", None
                )
                logger.info(
                    "Vision-relevance ranking fell back to model=%s model_id=%s "
                    "query_embedding=%s after empty configured ranking",
                    fallback,
                    None if fallback_identity is None else fallback_identity.model_id,
                    self.query_embedding_method,
                )
                return ranked
        return ranked

    def __call__(self, query, folder, candidates) -> tuple[Path, ...]:
        return self.search_progressive(query, folder, candidates)

    def search_progressive(
        self, query, folder, candidates, *, on_progress=None, cancelled=None,
        scope_image_ids=None,
    ) -> tuple[Path, ...]:
        ranking_started = time.perf_counter()
        session_id = uuid.uuid4().hex[:12]
        raw_query = str(query or "").strip()
        query = meaning_query_target(raw_query) or raw_query
        self.last_query_target = query
        self.last_raw_query = raw_query
        self._ensure_ranking_bundle()
        database = OCRDatabase().open()
        try:
            images = OCRRepository(database)
            _synchronize_candidates(images, candidates)
            allowed_ids = tuple(int(image_id) for image_id in (scope_image_ids or ()) if image_id is not None)
            ranked = self._rank_folder(
                query, folder, candidates, images, database,
                image_ids=allowed_ids or None,
            )
            ranking_seconds = time.perf_counter() - ranking_started
            relevance_images = []
            paths_by_id = {}
            allowed_id_set = set(allowed_ids)
            for result in ranked:
                if allowed_id_set and result.image_id not in allowed_id_set:
                    continue
                try:
                    image = images.get_image(result.image_id)
                except OCRRecordNotFoundError:
                    continue
                if image.file_state != "present":
                    continue
                path = Path(image.path)
                paths_by_id[result.image_id] = path
                relevance_images.append(RelevanceImage(result.image_id, path))

            ranks_by_id = {
                result.image_id: (rank, getattr(result, "similarity", None))
                for rank, result in enumerate(ranked, 1)
            }
            embedding_ranks = {
                image_id: rank for image_id, (rank, _similarity) in ranks_by_id.items()
            }
            trace = self.last_search_trace
            identity = getattr(trace, "query_identity", None) if trace is not None else None
            ranking_model_id = None if identity is None else getattr(identity, "model_id", None)
            ranking_dimension = None if identity is None else getattr(identity, "dimension", None)
            ranking_query_embedding = (
                self.query_embedding_method if trace is None
                else getattr(trace, "query_embedding_method", self.query_embedding_method)
            )
            ranked_ids = [item.image_id for item in relevance_images]
            facts_by_id = self._load_fresh_facts(database, ranked_ids)
            shortlist_images = []
            for item in relevance_images:
                if item.image_id not in facts_by_id:
                    continue
                shortlist_images.append(item)
                if len(shortlist_images) >= self.SHORTLIST_SIZE:
                    break
            self.last_hybrid_split = None
            self.last_vision_request_count = 0
            self.last_coverage = {
                "candidate_count": len(relevance_images),
                "facts_ready_count": len(facts_by_id),
                "facts_pending_count": sum(
                    1 for item in relevance_images if item.image_id not in facts_by_id
                ),
                "shortlist_count": len(shortlist_images),
            }

            def _ordered_relevant_paths() -> tuple[Path, ...]:
                scores = {
                    image_id: (
                        None if result is None else result.relevance_score
                    )
                    for image_id, result in results_by_id.items()
                    if image_id in relevant_ids
                }
                ordered_ids = rank_relevant_ids(
                    [item.image_id for item in relevance_images],
                    relevant_ids=relevant_ids,
                    relevance_scores=scores,
                    embedding_ranks=embedding_ranks,
                )
                return tuple(paths_by_id[image_id] for image_id in ordered_ids)

            relevance_started = time.perf_counter()
            relevant_ids: set[int] = set()
            results_by_id: dict[int, RelevanceResult] = {}
            skipped_reasons = {
                item.image_id: "facts_pending"
                for item in relevance_images
                if item.image_id not in facts_by_id
            }
            runs = []
            checked_count = 0
            unknown_ids: set[int] = set()
            offset = 0
            chunk_sizes = vision_candidate_chunk_sizes(
                len(shortlist_images),
                first_size=self.FIRST_CANDIDATE_CHUNK_SIZE,
                chunk_size=self.CANDIDATE_CHUNK_SIZE,
            )
            shortlist_ids = {item.image_id for item in shortlist_images}
            matcher = self._facts_matcher()
            logger.info(
                "Meaning-search first request starting session=%s query=%r "
                "meaning_target=%r model_id=%s query_embedding=%s ranking_seconds=%.3f "
                "candidates=%d facts_shortlist=%d first_chunk=%d search_vision=0",
                session_id, raw_query, query, ranking_model_id, ranking_query_embedding,
                ranking_seconds, len(relevance_images), len(shortlist_images),
                chunk_sizes[0] if chunk_sizes else 0,
            )
            for chunk_size in chunk_sizes:
                if cancelled is not None and cancelled():
                    break
                chunk = shortlist_images[offset:offset + chunk_size]
                offset += chunk_size
                records = [
                    {**facts_by_id[item.image_id], "image_id": item.image_id}
                    for item in chunk
                ]
                run = matcher.match_records(
                    query.strip(), records, cancelled=cancelled,
                )
                runs.append(run)
                checked_count += len(chunk)
                if cancelled is not None and cancelled():
                    break
                for item in run.results:
                    results_by_id[item.image_id] = item
                    if item.relevant is True:
                        relevant_ids.add(item.image_id)
                        unknown_ids.discard(item.image_id)
                    elif item.relevant is None:
                        unknown_ids.add(item.image_id)
                        skipped_reasons[item.image_id] = item.unknown_reason or "unknown"
                    else:
                        unknown_ids.discard(item.image_id)
                        skipped_reasons[item.image_id] = "facts_not_confirmed"
                final_paths = _ordered_relevant_paths()
                if on_progress is not None and not (cancelled is not None and cancelled()):
                    on_progress(final_paths, checked_count, len(shortlist_images))
                logger.info(
                    "Meaning-search session=%s query=%r candidate_chunk=%d first_chunk=%d "
                    "checked=%d total_candidates=%d facts_shortlist=%d "
                    "relevant=%d api_requests=%d sent_images=%d status=running",
                    session_id, query.strip(), len(chunk),
                    self.FIRST_CANDIDATE_CHUNK_SIZE, checked_count,
                    len(relevance_images), len(shortlist_images), len(final_paths),
                    sum(value.request_count for value in runs),
                    sum(value.sent_image_count for value in runs),
                )

            relevance_seconds = time.perf_counter() - relevance_started
            final_paths = _ordered_relevant_paths()
            final_results = tuple(
                results_by_id[item.image_id]
                for item in shortlist_images
                if item.image_id in results_by_id
            )
            run = RelevanceRun(
                results=final_results,
                failed_image_ids=tuple(item for value in runs for item in value.failed_image_ids),
                request_count=sum(value.request_count for value in runs),
                sent_image_count=sum(value.sent_image_count for value in runs),
                resize_seconds=0.0,
                api_seconds=sum(value.api_seconds for value in runs),
                first_relevant_seconds=next(
                    (value.first_relevant_seconds for value in runs if value.first_relevant_seconds is not None),
                    None,
                ),
                first_result_seconds=next(
                    (value.first_result_seconds for value in runs if value.first_result_seconds is not None),
                    None,
                ),
                total_seconds=relevance_seconds,
                retry_count=sum(value.retry_count for value in runs),
                request_attempt_count=sum(value.request_attempt_count for value in runs),
                input_tokens=sum(value.input_tokens for value in runs),
                output_tokens=sum(value.output_tokens for value in runs),
                errors=tuple(item for value in runs for item in value.errors),
            )
            self.last_run = run
            self.last_vision_request_count = 0
            self._record_search_usage(
                run,
                candidate_count=len(shortlist_images),
                matcher_image_count=checked_count,
                batch_count=len(runs),
            )
            judged_any = any(item.relevant is True or item.relevant is False for item in final_results)
            if (
                checked_count
                and not judged_any
                and unknown_ids
                and checked_count >= len(shortlist_images)
                and shortlist_images
            ):
                raise RelevanceProviderError(
                    "All facts matching requests failed; no result was applied."
                )
            ui_final_seconds = time.perf_counter() - ranking_started
            self.last_timing = {
                "model_id": ranking_model_id,
                "query_embedding_method": ranking_query_embedding,
                "retrieval_ranking_seconds": ranking_seconds,
                "openclip_ranking_seconds": ranking_seconds,
                "vision_api_start_seconds": None,
                "first_result_seconds": (
                    None if run.first_result_seconds is None
                    else relevance_started - ranking_started + run.first_result_seconds
                ),
                "first_relevant_seconds": (
                    None if run.first_relevant_seconds is None
                    else relevance_started - ranking_started + run.first_relevant_seconds
                ),
                "all_judgements_seconds": relevance_started - ranking_started + run.total_seconds,
                "ui_final_seconds": ui_final_seconds,
            }
            logger.info(
                "Meaning-search session=%s query=%r meaning_target=%r model_id=%s query_embedding=%s "
                "dimension=%s total_candidates=%d facts_shortlist=%d "
                "candidate_chunk=%d first_chunk=%d "
                "checked=%d relevant=%d failed=%d unknown=%d status=%s "
                "ranking_seconds=%.3f match_wall_seconds=%.3f "
                "api_seconds=%.3f first_relevant_seconds=%s total_seconds=%.3f "
                "ui_final_seconds=%.3f requests=%d sent_images=%d search_vision=0",
                session_id, raw_query, query, ranking_model_id, ranking_query_embedding,
                ranking_dimension, len(relevance_images), len(shortlist_images),
                self.CANDIDATE_CHUNK_SIZE, self.FIRST_CANDIDATE_CHUNK_SIZE,
                checked_count, len(final_paths), len(run.failed_image_ids),
                len(unknown_ids),
                "cancelled" if checked_count < len(shortlist_images) else "completed",
                ranking_seconds, relevance_seconds, run.api_seconds,
                run.first_relevant_seconds, run.total_seconds, ui_final_seconds,
                run.request_count, run.sent_image_count,
            )
            for candidate in relevance_images:
                result = results_by_id.get(candidate.image_id)
                rank, similarity = ranks_by_id[candidate.image_id]
                logger.info(
                    "Meaning-search candidate session=%s query=%r meaning_target=%r "
                    "model_id=%s query_embedding=%s retrieval_rank=%d "
                    "retrieval_similarity=%s image_id=%d path=%s facts=%s "
                    "shortlist=%s final_result=%s skipped_reason=%r reason=%r "
                    "unknown_reason=%r search_vision=0",
                    session_id, raw_query, query, ranking_model_id, ranking_query_embedding,
                    rank, similarity, candidate.image_id, candidate.path,
                    candidate.image_id in facts_by_id,
                    candidate.image_id in shortlist_ids,
                    True if candidate.image_id in relevant_ids else (
                        "unknown" if candidate.image_id in unknown_ids else False
                    ),
                    skipped_reasons.get(candidate.image_id),
                    None if result is None else result.reason,
                    None if result is None else result.unknown_reason,
                )
            for message in run.errors:
                logger.warning("Meaning-search partial batch failure: %s", message)
            return final_paths
        finally:
            database.close()

    def _record_search_usage(
        self,
        run,
        *,
        candidate_count: int,
        matcher_image_count: int,
        batch_count: int,
    ) -> None:
        matcher = self.facts_matcher
        get_usage_recorder().record_search(
            model=str(getattr(matcher, "model", "") or ""),
            request_count=int(getattr(run, "request_count", 0) or 0),
            input_tokens=int(getattr(run, "input_tokens", 0) or 0),
            output_tokens=int(getattr(run, "output_tokens", 0) or 0),
            candidate_count=int(candidate_count),
            batch_count=int(batch_count),
            matcher_image_count=int(matcher_image_count),
        )


def create_meaning_search_provider(
    *,
    model_key=DEFAULT_MODEL_KEY,
    query_embedding_method=None,
    relevance_provider=None,
    high_relevance_provider=None,
    facts_matcher=None,
    facts_lookup=None,
) -> VisionRelevanceImagesSearchProvider:
    """Shared Meaning Search entry for Search (Meaning) and Ask AI.

    OpenCLIP ranking and DB facts matching stay inside
    VisionRelevanceImagesSearchProvider. Callers must not copy that logic.
    """
    return VisionRelevanceImagesSearchProvider(
        relevance_provider=relevance_provider,
        high_relevance_provider=high_relevance_provider,
        facts_matcher=facts_matcher,
        facts_lookup=facts_lookup,
        model_key=model_key,
        query_embedding_method=query_embedding_method,
    )


class _UnavailableSemanticSearch:
    def search(self, *_args, **_kwargs):
        raise ModelNotInstalledError("Image-content search files are not installed.")


def _synchronize_candidates(
    repository: OCRRepository, candidates: Sequence[SearchCandidate]
) -> None:
    """Keep UI-owned filename/tag facts current before any indexed search."""
    for path, tags in candidates:
        try:
            image = repository.get_image_by_path(path)
        except OCRRecordNotFoundError:
            stat = path.stat()
            image = repository.upsert_image(
                path,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        repository.update_tags(image.image_id, list(tags))


def search_indexed_images(
    query: str,
    folder: Path,
    candidates: Sequence[SearchCandidate],
) -> tuple[Path, ...]:
    """Synchronize UI-owned filename/tag facts, then use the formal search API."""
    database = OCRDatabase().open()
    try:
        repository = OCRRepository(database)
        _synchronize_candidates(repository, candidates)

        paths: list[Path] = []
        offset = 0
        while True:
            page = repository.search_images(
                query,
                folder_path=folder,
                limit=500,
                offset=offset,
            )
            paths.extend(Path(result.path) for result in page.results)
            offset += page.returned_count
            if offset >= page.total_count or not page.returned_count:
                break
        return tuple(paths)
    finally:
        database.close()


def plan_image_action(
    instruction: str,
    folder: Path,
    candidates: Sequence[SearchCandidate],
) -> tuple[object, tuple[Path, ...]]:
    """Build a safe action preview and resolve its candidate IDs to paths."""
    database = OCRDatabase().open()
    worker = None
    try:
        images = OCRRepository(database)
        _synchronize_candidates(images, candidates)
        bundle_dir = _installed_semantic_bundle()
        if bundle_dir is not None:
            worker = SemanticWorkerClient(SemanticWorkerConfig(bundle_dir=bundle_dir))
            semantic = SemanticSearchService(
                SemanticRepository(database), images, worker
            )
        else:
            semantic = _UnavailableSemanticSearch()
        service = AIActionService(HybridSearchService(images, semantic, images))
        plan = service.plan(instruction, folder_path=folder)
        paths = []
        for image_id in plan.matched_image_ids:
            try:
                image = images.get_image(image_id)
            except OCRRecordNotFoundError:
                continue
            if image.file_state == "present":
                paths.append(Path(image.path))
        return plan, tuple(paths)
    finally:
        if worker is not None:
            worker.shutdown()
        database.close()


def execute_image_tag_action(plan, preview_paths, metadata_service):
    """Open a fresh index view and execute a confirmed tag preview."""
    database = OCRDatabase().open()
    try:
        return ActionExecutor(OCRRepository(database), metadata_service).execute_tag(
            plan, confirmed=True, preview_paths=preview_paths
        )
    finally:
        database.close()


class SearchTaskSignals(QObject):
    finished = Signal(int, str, str, object, object)
    progress = Signal(int, str, str, object, int, int)


class ImagesSearchTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        query: str,
        folder: Path,
        candidates: Sequence[SearchCandidate],
        provider: SearchProvider,
        mode: str = "text",
        scope_image_ids: Sequence[int] | None = None,
    ) -> None:
        super().__init__()
        # The page owns this runnable until its queued finished callback has
        # removed it from _search_tasks.  Qt auto-deletion can otherwise race
        # that callback (especially in frozen builds) and destroy the signals
        # object while the provider is still reporting progress/completion.
        self.setAutoDelete(False)
        self.request_id = request_id
        self.query = query
        self.folder = folder
        self.candidates = tuple(candidates)
        self.provider = provider
        self.mode = mode
        self.scope_image_ids = tuple(scope_image_ids or ())
        self.signals = SearchTaskSignals()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        logger.info(
            "Images-search cancel requested request=%d query=%r mode=%s",
            self.request_id, self.query, self.mode,
        )

    def _emit_progress(self, values, checked, total) -> None:
        if self._cancelled.is_set():
            return
        self.signals.progress.emit(
            self.request_id, self.query, str(self.folder.resolve()),
            values, checked, total,
        )

    def run(self) -> None:
        logger.info(
            "Images-search task running request=%d query=%r mode=%s provider=%s",
            self.request_id, self.query, self.mode, type(self.provider).__name__,
        )
        try:
            progressive = getattr(self.provider, "search_progressive", None)
            if callable(progressive):
                kwargs = {
                    "on_progress": self._emit_progress,
                    "cancelled": self._cancelled.is_set,
                }
                if self.scope_image_ids:
                    try:
                        params = inspect.signature(progressive).parameters
                    except (TypeError, ValueError):
                        params = {}
                    if "scope_image_ids" in params or any(
                        item.kind is inspect.Parameter.VAR_KEYWORD
                        for item in params.values()
                    ):
                        kwargs["scope_image_ids"] = self.scope_image_ids
                paths = progressive(
                    self.query, self.folder, self.candidates, **kwargs,
                )
            else:
                paths = self.provider(self.query, self.folder, self.candidates)
            self.signals.finished.emit(
                self.request_id, self.query, str(self.folder.resolve()), paths, None
            )
        except Exception as exc:  # Delivered to the UI as a generic search error.
            if self._cancelled.is_set():
                logger.info(
                    "Images-search task stopped request=%d query=%r mode=%s "
                    "provider=%s reason=cancelled",
                    self.request_id, self.query, self.mode,
                    type(self.provider).__name__,
                )
                self.signals.finished.emit(
                    self.request_id, self.query, str(self.folder.resolve()), (), None
                )
                return
            logger.exception(
                "Images-search task failed request=%d query=%r mode=%s provider=%s cancelled=%s",
                self.request_id, self.query, self.mode, type(self.provider).__name__,
                self._cancelled.is_set(),
            )
            self.signals.finished.emit(
                self.request_id, self.query, str(self.folder.resolve()), (), exc
            )


class ActionPlanTaskSignals(QObject):
    finished = Signal(int, str, str, object, object, object)


class ActionPlanTask(QRunnable):
    """Run parsing, search, and any lazy model work away from the UI thread."""

    def __init__(self, request_id, instruction, folder, candidates, provider):
        super().__init__()
        # The page releases its Python reference from the queued completion
        # callback. Let Python own deletion so Qt cannot delete the runnable at
        # the same time that callback is handling its signal payload.
        self.setAutoDelete(False)
        self.request_id = request_id
        self.instruction = instruction
        self.folder = folder
        self.candidates = tuple(candidates)
        self.provider = provider
        self.signals = ActionPlanTaskSignals()

    def run(self) -> None:
        try:
            plan, paths = self.provider(
                self.instruction, self.folder, self.candidates
            )
            self.signals.finished.emit(
                self.request_id, self.instruction, str(self.folder.resolve()),
                plan, paths, None,
            )
        except Exception as exc:
            self.signals.finished.emit(
                self.request_id, self.instruction, str(self.folder.resolve()),
                None, (), exc,
            )
