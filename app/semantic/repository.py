from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRDatabaseError, OCRInvalidRecordError, OCRRecordNotFoundError

from .embedding import EMBEDDING_FORMAT_VERSION, SUPPORTED_EMBEDDING_DIMENSIONS, SemanticValidationError, validate_embedding_blob
from .models import (ModelIdentity, SemanticDiffState, SemanticEmbeddingMetadata,
                     SemanticEmbeddingRecord, SemanticFailureRecord, SourceSnapshot)

SEMANTIC_COLUMNS = "image_id,dimension,embedding_format_version,model_id,bundle_version,model_revision,pipeline_version,source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at"


class SemanticRepository:
    def __init__(self, database: OCRDatabase):
        self.database = database

    @property
    def conn(self) -> sqlite3.Connection:
        if self.database.connection is None:
            raise OCRDatabaseError("OCR database is closed.")
        return self.database.connection

    def _metadata(self, row: sqlite3.Row) -> SemanticEmbeddingMetadata:
        data = dict(row)
        data.pop("embedding", None)
        return SemanticEmbeddingMetadata(**data)

    def get_embedding_metadata(self, image_id: int) -> SemanticEmbeddingMetadata | None:
        row = self.conn.execute(f"SELECT {SEMANTIC_COLUMNS} FROM semantic_embeddings WHERE image_id=?", (image_id,)).fetchone()
        return None if row is None else self._metadata(row)

    def get_embedding(self, image_id: int) -> SemanticEmbeddingRecord | None:
        row = self.conn.execute(f"SELECT {SEMANTIC_COLUMNS},embedding FROM semantic_embeddings WHERE image_id=?", (image_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        try:
            data["embedding"] = validate_embedding_blob(data["embedding"], dimension=int(data["dimension"]))
        except (TypeError, ValueError):
            return None
        return SemanticEmbeddingRecord(**data)

    def list_embeddings(self, image_ids: Iterable[int] | None = None, *, folder_path: str | None = None) -> list[SemanticEmbeddingRecord]:
        clauses: list[str] = []
        parameters: list[object] = []
        if image_ids is not None:
            ids = tuple(int(value) for value in image_ids)
            if not ids:
                return []
            clauses.append("s.image_id IN (%s)" % ",".join("?" for _ in ids)); parameters.extend(ids)
        if folder_path is not None:
            from app.ocr.path_normalization import normalize_windows_path
            clauses.append("i.folder_path_norm=?"); parameters.append(normalize_windows_path(folder_path))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(f"SELECT {','.join('s.'+c for c in SEMANTIC_COLUMNS.split(','))},s.embedding FROM semantic_embeddings s JOIN images i ON i.image_id=s.image_id{where} ORDER BY s.image_id", parameters).fetchall()
        result = []
        for row in rows:
            record = self.get_embedding(int(row["image_id"]))
            if record is not None: result.append(record)
        return result

    def upsert_embedding(self, image_id: int, embedding: bytes, identity: ModelIdentity, source: SourceSnapshot) -> SemanticEmbeddingRecord:
        if (identity.dimension not in SUPPORTED_EMBEDDING_DIMENSIONS or
                identity.embedding_format_version != EMBEDDING_FORMAT_VERSION or
                identity.pipeline_version <= 0 or
                not all((identity.model_id, identity.bundle_version, identity.model_revision))):
            raise OCRInvalidRecordError("Invalid semantic identity.")
        try:
            raw = validate_embedding_blob(embedding, dimension=identity.dimension)
        except SemanticValidationError as exc:
            raise OCRInvalidRecordError("Invalid semantic embedding.") from exc
        now = self.database.clock()
        try:
            with self.database.transaction():
                image = self.conn.execute("SELECT size_bytes,mtime_ns,quick_fingerprint,file_state FROM images WHERE image_id=?", (image_id,)).fetchone()
                if image is None: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
                current = SourceSnapshot(int(image[0]), int(image[1]), image[2])
                if image[3] != "present" or current != source: raise OCRInvalidRecordError("Image source snapshot changed before semantic save.")
                self.conn.execute("""INSERT INTO semantic_embeddings(image_id,embedding,dimension,embedding_format_version,model_id,bundle_version,model_revision,pipeline_version,source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at)
VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET embedding=excluded.embedding,dimension=excluded.dimension,embedding_format_version=excluded.embedding_format_version,model_id=excluded.model_id,bundle_version=excluded.bundle_version,model_revision=excluded.model_revision,pipeline_version=excluded.pipeline_version,source_size_bytes=excluded.source_size_bytes,source_mtime_ns=excluded.source_mtime_ns,source_quick_fingerprint=excluded.source_quick_fingerprint,updated_at=excluded.updated_at""",
                    (image_id,raw,identity.dimension,identity.embedding_format_version,identity.model_id,identity.bundle_version,identity.model_revision,identity.pipeline_version,source.size_bytes,source.mtime_ns,source.quick_fingerprint,now,now))
                self.conn.execute("DELETE FROM semantic_analysis_failures WHERE image_id=?", (image_id,))
            record = self.get_embedding(image_id)
            assert record is not None
            return record
        except (OCRInvalidRecordError, OCRRecordNotFoundError): raise
        except sqlite3.DatabaseError as exc: raise OCRDatabaseError("Failed to save semantic embedding.") from exc

    def record_failure(self, image_id: int, error_code: str, retryable: bool, attempted_at: str | None = None) -> SemanticFailureRecord:
        if not error_code or len(error_code) > 100: raise OCRInvalidRecordError("Invalid semantic error code.")
        attempted_at = attempted_at or self.database.clock()
        with self.database.transaction():
            self.conn.execute("""INSERT INTO semantic_analysis_failures(image_id,error_code,retryable,attempt_count,last_attempt_at) VALUES(?,?,?,?,?)
ON CONFLICT(image_id) DO UPDATE SET error_code=excluded.error_code,retryable=excluded.retryable,attempt_count=semantic_analysis_failures.attempt_count+1,last_attempt_at=excluded.last_attempt_at""", (image_id,error_code,int(retryable),1,attempted_at))
        row=self.conn.execute("SELECT * FROM semantic_analysis_failures WHERE image_id=?",(image_id,)).fetchone(); data=dict(row); data["retryable"]=bool(data["retryable"]); return SemanticFailureRecord(**data)

    def clear_failure(self, image_id: int) -> None:
        with self.database.transaction(): self.conn.execute("DELETE FROM semantic_analysis_failures WHERE image_id=?",(image_id,))

    def get_failure(self, image_id: int) -> SemanticFailureRecord | None:
        row=self.conn.execute("SELECT * FROM semantic_analysis_failures WHERE image_id=?",(image_id,)).fetchone()
        if row is None: return None
        data=dict(row); data["retryable"]=bool(data["retryable"]); return SemanticFailureRecord(**data)

    def delete_embedding(self, image_id: int) -> None:
        self.delete_embeddings((image_id,))

    def delete_embeddings(self, image_ids: Iterable[int]) -> int:
        ids=tuple(int(value) for value in image_ids)
        if not ids: return 0
        with self.database.transaction():
            cursor=self.conn.execute("DELETE FROM semantic_embeddings WHERE image_id IN (%s)" % ",".join("?" for _ in ids),ids)
        return cursor.rowcount

    def delete_orphans(self) -> int:
        with self.database.transaction():
            first=self.conn.execute("DELETE FROM semantic_embeddings WHERE image_id NOT IN (SELECT image_id FROM images)").rowcount
            second=self.conn.execute("DELETE FROM semantic_analysis_failures WHERE image_id NOT IN (SELECT image_id FROM images)").rowcount
        return first+second

    def classify_embeddings(self, image_ids: Iterable[int], active_identity: ModelIdentity) -> dict[int, SemanticDiffState]:
        result: dict[int, SemanticDiffState] = {}
        for image_id in image_ids:
            image=self.conn.execute("SELECT size_bytes,mtime_ns,quick_fingerprint,file_state FROM images WHERE image_id=?",(image_id,)).fetchone()
            if image is None or image[3] == "missing": result[image_id]=SemanticDiffState.DELETED; continue
            row=self.conn.execute(f"SELECT {SEMANTIC_COLUMNS},embedding FROM semantic_embeddings WHERE image_id=?",(image_id,)).fetchone()
            if row is None:
                result[image_id]=SemanticDiffState.FAILED if self.get_failure(image_id) else SemanticDiffState.MISSING; continue
            data=dict(row)
            try: validate_embedding_blob(data["embedding"],dimension=int(data["dimension"]))
            except (TypeError,ValueError): result[image_id]=SemanticDiffState.CORRUPT; continue
            source=SourceSnapshot(int(image[0]),int(image[1]),image[2]); stored=self._metadata(row)
            mtime_only_same = (source.size_bytes == stored.source_size_bytes and
                               bool(source.quick_fingerprint) and
                               source.quick_fingerprint == stored.source_quick_fingerprint)
            if source != stored.source_snapshot and not mtime_only_same:
                result[image_id]=SemanticDiffState.MODIFIED
            elif stored.identity != active_identity: result[image_id]=SemanticDiffState.STALE_MODEL
            else: result[image_id]=SemanticDiffState.UNCHANGED
        return result
