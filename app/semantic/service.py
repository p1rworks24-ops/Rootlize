from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass
from collections.abc import Callable, Iterable, Iterator
from typing import Protocol

from app.ocr.repository import OCRRepository
from app.ocr.exceptions import OCRInvalidRecordError, OCRRecordNotFoundError

from app.utils.logger import setup_logger

from .embedding import decode_embedding, validate_embedding_blob
from .models import (ModelIdentity, SemanticAnalysisResult, SemanticDiffState,
                     SemanticSearchResult, SemanticWorkerEvent, SemanticWorkItem,
                     SourceSnapshot)
from .query_embedding import (
    DEFAULT_QUERY_EMBEDDING,
    combine_normalized_embeddings,
    normalize_query_embedding_method,
    query_texts,
)
from .repository import SemanticRepository
from .worker_errors import SemanticWorkerCrashedError

logger = setup_logger()


class SemanticWorker(Protocol):
    def analyze(self, items: tuple[SemanticWorkItem, ...], *, request_id: str, cancel_event: threading.Event) -> Iterator[SemanticWorkerEvent]: ...

    def embed_text(self, text: str) -> tuple[bytes, ModelIdentity]: ...


@dataclass(frozen=True)
class SemanticSearchTrace:
    """Identity and candidate facts from one completed search invocation."""

    query_identity: ModelIdentity
    candidate_identities: tuple[ModelIdentity, ...]
    repository_candidate_count: int
    ready_candidate_count: int
    service_candidate_count: int
    result_count: int
    query_embedding_method: str = DEFAULT_QUERY_EMBEDDING
    query_text_count: int = 1
    query_embedding: tuple[float, ...] | None = None


class SemanticAnalysisService:
    def __init__(self, repository: SemanticRepository, image_repository: OCRRepository, worker: SemanticWorker, *, on_progress: Callable[[SemanticWorkerEvent], None] | None = None):
        self.repository=repository; self.image_repository=image_repository; self.worker=worker; self.on_progress=on_progress
        self._cancel_event=threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def analyze(self, image_ids: Iterable[int], identity: ModelIdentity, *, request_id: str | None = None) -> SemanticAnalysisResult:
        request_id=request_id or str(uuid.uuid4()); self._cancel_event.clear()
        ids=tuple(int(value) for value in image_ids); states=self.repository.classify_embeddings(ids,identity)
        targets=[]
        for image_id in ids:
            if states[image_id] == SemanticDiffState.UNCHANGED or states[image_id] == SemanticDiffState.DELETED: continue
            image=self.image_repository.get_image(image_id)
            targets.append(SemanticWorkItem(image_id,image.path,SourceSnapshot(image.size_bytes,image.mtime_ns,image.quick_fingerprint)))
        succeeded=failed=processed=0
        for event in self.worker.analyze(tuple(targets),request_id=request_id,cancel_event=self._cancel_event):
            if event.request_id != request_id: raise SemanticWorkerCrashedError("Semantic worker request ID mismatch.")
            if event.kind == "item_result":
                try:
                    if event.image_id is None or event.embedding is None or event.model_identity != identity or event.source_snapshot is None:
                        raise ValueError("Invalid semantic worker result metadata.")
                    validate_embedding_blob(event.embedding,dimension=identity.dimension)
                    self.repository.upsert_embedding(event.image_id,event.embedding,identity,event.source_snapshot)
                    succeeded+=1
                except (ValueError, OCRInvalidRecordError, OCRRecordNotFoundError):
                    if event.image_id is not None: self.repository.record_failure(event.image_id,"INVALID_EMBEDDING",False)
                    failed+=1
                processed+=1
            elif event.kind == "item_error":
                if event.image_id is not None: self.repository.record_failure(event.image_id,event.error_code or "INFERENCE_FAILED",event.retryable)
                failed+=1; processed+=1
            if self.on_progress is not None:
                try: self.on_progress(event)
                except Exception: pass
        state="cancelled" if self._cancel_event.is_set() else "completed"
        return SemanticAnalysisResult(request_id,state,processed,succeeded,failed,len(targets))


class SemanticSearchService(SemanticAnalysisService):
    """Semantic analysis plus in-process cosine similarity search."""

    def __init__(self, *args, query_embedding_method: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_embedding_method = normalize_query_embedding_method(
            query_embedding_method
        )
        self._search_trace = threading.local()

    @property
    def last_search_trace(self) -> SemanticSearchTrace | None:
        return getattr(self._search_trace, "value", None)

    def search(
        self,
        query: str,
        top_k: int,
        *,
        image_ids: Iterable[int] | None = None,
        folder_path: str | None = None,
    ) -> list[SemanticSearchResult]:
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError("top_k must be an integer.")
        if top_k < 0:
            raise ValueError("top_k must not be negative.")
        if top_k == 0:
            return []

        embed_started = time.perf_counter()
        texts = query_texts(query, self.query_embedding_method) or (query,)
        encoded = []
        identity = None
        for text in texts:
            query_blob, identity = self.worker.embed_text(text)
            encoded.append(decode_embedding(query_blob, dimension=identity.dimension))
        if identity is None:
            raise RuntimeError("Query embedding identity is missing.")
        query_values = combine_normalized_embeddings(encoded)
        embed_seconds = time.perf_counter() - embed_started
        records = self.repository.list_embeddings(image_ids, folder_path=folder_path)
        candidate_identities = tuple(sorted(
            {record.identity for record in records},
            key=lambda value: (
                value.model_id, value.bundle_version, value.model_revision,
                value.pipeline_version, value.embedding_format_version, value.dimension,
            ),
        ))
        if not records:
            self._search_trace.value = SemanticSearchTrace(
                identity, candidate_identities, 0, 0, 0, 0,
                self.query_embedding_method, len(texts), tuple(query_values),
            )
            return []

        rank_started = time.perf_counter()
        states = self.repository.classify_embeddings(
            (record.image_id for record in records), identity
        )
        ranked: list[SemanticSearchResult] = []
        for record in records:
            if states.get(record.image_id) != SemanticDiffState.UNCHANGED:
                continue
            try:
                values = decode_embedding(record.embedding, dimension=identity.dimension)
                similarity = math.fsum(
                    query_value * image_value
                    for query_value, image_value in zip(query_values, values)
                )
                if not math.isfinite(similarity):
                    continue
            except (TypeError, ValueError):
                # A single malformed persisted value must not fail the search.
                continue
            ranked.append(SemanticSearchResult(record.image_id, similarity))

        ranked.sort(key=lambda result: (-result.similarity, result.image_id))
        results = ranked[:top_k]
        logger.info(
            "Semantic ranking model_id=%s bundle_version=%s revision=%s dimension=%d "
            "query_embedding=%s query_text_count=%d embed_seconds=%.3f rank_seconds=%.3f "
            "candidates=%d results=%d",
            identity.model_id, identity.bundle_version, identity.model_revision,
            identity.dimension, self.query_embedding_method, len(texts),
            embed_seconds, time.perf_counter() - rank_started, len(ranked), len(results),
        )
        self._search_trace.value = SemanticSearchTrace(
            identity,
            candidate_identities,
            len(records),
            len(ranked),
            len(ranked),
            len(results),
            self.query_embedding_method,
            len(texts),
            tuple(query_values),
        )
        return results
