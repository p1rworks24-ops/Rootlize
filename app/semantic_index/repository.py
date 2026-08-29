from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRDatabaseError, OCRInvalidRecordError, OCRRecordNotFoundError
from app.semantic.embedding import (
    EMBEDDING_FORMAT_VERSION,
    SUPPORTED_EMBEDDING_DIMENSIONS,
    SemanticValidationError,
    validate_embedding_blob,
)
from app.semantic.models import SourceSnapshot
from app.semantic_index.models import (
    SemanticIndexFailureRecord,
    SemanticIndexIdentity,
    SemanticIndexMetadata,
    SemanticIndexRecord,
    SemanticIndexState,
)
from app.semantic_index.schema import INDEX_FIELDS, MEDIA_TYPES, metadata_only, normalize_index_record

INDEX_COLUMNS = (
    "image_id,metadata_json,embedding_dimension,embedding_format_version,vision_model,"
    "prompt_version,index_schema_version,embedding_model_id,source_size_bytes,"
    "source_mtime_ns,source_quick_fingerprint,created_at,updated_at"
)


def _encode_metadata(record: dict) -> str:
    payload = metadata_only(record)
    if payload.get("media_type") not in MEDIA_TYPES:
        raise OCRInvalidRecordError("Invalid semantic index metadata.")
    missing = [name for name in INDEX_FIELDS if name not in payload]
    if missing:
        raise OCRInvalidRecordError("Invalid semantic index metadata.")
    if record.get("unknown_reason"):
        raise OCRInvalidRecordError("Failed semantic index metadata cannot be stored as fresh.")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_metadata(raw: object) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return normalize_index_record(payload)


class SemanticIndexRepository:
    def __init__(self, database: OCRDatabase):
        self.database = database

    @property
    def conn(self) -> sqlite3.Connection:
        if self.database.connection is None:
            raise OCRDatabaseError("OCR database is closed.")
        return self.database.connection

    def _metadata(self, row: sqlite3.Row, metadata: dict) -> SemanticIndexMetadata:
        data = dict(row)
        data.pop("text_embedding", None)
        data.pop("metadata_json", None)
        data["metadata"] = metadata_only(metadata)
        data["schema_version"] = data.pop("index_schema_version")
        return SemanticIndexMetadata(**data)

    def get_index_metadata(self, image_id: int) -> SemanticIndexMetadata | None:
        row = self.conn.execute(
            f"SELECT {INDEX_COLUMNS} FROM semantic_indexes WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        metadata = _decode_metadata(row["metadata_json"])
        if metadata is None:
            return None
        return self._metadata(row, metadata)

    def get_index(self, image_id: int) -> SemanticIndexRecord | None:
        row = self.conn.execute(
            f"SELECT {INDEX_COLUMNS},text_embedding FROM semantic_indexes WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        metadata = _decode_metadata(row["metadata_json"])
        if metadata is None:
            return None
        data = dict(row)
        try:
            data["text_embedding"] = validate_embedding_blob(
                data["text_embedding"], dimension=int(data["embedding_dimension"])
            )
        except (TypeError, ValueError):
            return None
        parsed = self._metadata(row, metadata)
        return SemanticIndexRecord(**parsed.__dict__, text_embedding=data["text_embedding"])

    def upsert_index(
        self,
        image_id: int,
        record: dict,
        embedding: bytes,
        identity: SemanticIndexIdentity,
        source: SourceSnapshot,
    ) -> SemanticIndexRecord:
        if (
            identity.embedding_dimension not in SUPPORTED_EMBEDDING_DIMENSIONS
            or identity.embedding_format_version != EMBEDDING_FORMAT_VERSION
            or not all((
                identity.vision_model,
                identity.prompt_version,
                identity.schema_version,
                identity.embedding_model_id,
            ))
        ):
            raise OCRInvalidRecordError("Invalid semantic index identity.")
        try:
            raw = validate_embedding_blob(embedding, dimension=identity.embedding_dimension)
        except SemanticValidationError as exc:
            raise OCRInvalidRecordError("Invalid semantic index embedding.") from exc
        metadata_json = _encode_metadata(record)
        now = self.database.clock()
        try:
            with self.database.transaction():
                image = self.conn.execute(
                    "SELECT size_bytes,mtime_ns,quick_fingerprint,file_state FROM images WHERE image_id=?",
                    (image_id,),
                ).fetchone()
                if image is None:
                    raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
                current = SourceSnapshot(int(image[0]), int(image[1]), image[2])
                if image[3] != "present" or current != source:
                    raise OCRInvalidRecordError("Image source snapshot changed before semantic index save.")
                self.conn.execute(
                    """INSERT INTO semantic_indexes(
 image_id,metadata_json,text_embedding,embedding_dimension,embedding_format_version,
 vision_model,prompt_version,index_schema_version,embedding_model_id,
 source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(image_id) DO UPDATE SET
 metadata_json=excluded.metadata_json,text_embedding=excluded.text_embedding,
 embedding_dimension=excluded.embedding_dimension,
 embedding_format_version=excluded.embedding_format_version,
 vision_model=excluded.vision_model,prompt_version=excluded.prompt_version,
 index_schema_version=excluded.index_schema_version,
 embedding_model_id=excluded.embedding_model_id,
 source_size_bytes=excluded.source_size_bytes,source_mtime_ns=excluded.source_mtime_ns,
 source_quick_fingerprint=excluded.source_quick_fingerprint,updated_at=excluded.updated_at""",
                    (
                        image_id, metadata_json, raw, identity.embedding_dimension,
                        identity.embedding_format_version, identity.vision_model,
                        identity.prompt_version, identity.schema_version,
                        identity.embedding_model_id, source.size_bytes, source.mtime_ns,
                        source.quick_fingerprint, now, now,
                    ),
                )
                self.conn.execute("DELETE FROM semantic_index_failures WHERE image_id=?", (image_id,))
            stored = self.get_index(image_id)
            assert stored is not None
            return stored
        except (OCRInvalidRecordError, OCRRecordNotFoundError):
            raise
        except sqlite3.DatabaseError as exc:
            raise OCRDatabaseError("Failed to save semantic index.") from exc

    def record_failure(
        self,
        image_id: int,
        error_code: str,
        retryable: bool = True,
        attempted_at: str | None = None,
    ) -> SemanticIndexFailureRecord:
        if not error_code or len(error_code) > 100:
            raise OCRInvalidRecordError("Invalid semantic index error code.")
        attempted_at = attempted_at or self.database.clock()
        with self.database.transaction():
            self.conn.execute(
                """INSERT INTO semantic_index_failures(image_id,error_code,retryable,attempt_count,last_attempt_at)
VALUES(?,?,?,?,?)
ON CONFLICT(image_id) DO UPDATE SET
 error_code=excluded.error_code,retryable=excluded.retryable,
 attempt_count=semantic_index_failures.attempt_count+1,
 last_attempt_at=excluded.last_attempt_at""",
                (image_id, error_code, int(retryable), 1, attempted_at),
            )
        row = self.conn.execute(
            "SELECT * FROM semantic_index_failures WHERE image_id=?", (image_id,)
        ).fetchone()
        data = dict(row)
        data["retryable"] = bool(data["retryable"])
        return SemanticIndexFailureRecord(**data)

    def clear_failure(self, image_id: int) -> None:
        with self.database.transaction():
            self.conn.execute("DELETE FROM semantic_index_failures WHERE image_id=?", (image_id,))

    def get_failure(self, image_id: int) -> SemanticIndexFailureRecord | None:
        row = self.conn.execute(
            "SELECT * FROM semantic_index_failures WHERE image_id=?", (image_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["retryable"] = bool(data["retryable"])
        return SemanticIndexFailureRecord(**data)

    def delete_index(self, image_id: int) -> None:
        self.delete_indexes((image_id,))

    def delete_indexes(self, image_ids: Iterable[int]) -> int:
        ids = tuple(int(value) for value in image_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.database.transaction():
            cursor = self.conn.execute(
                f"DELETE FROM semantic_indexes WHERE image_id IN ({placeholders})", ids
            )
            self.conn.execute(
                f"DELETE FROM semantic_index_failures WHERE image_id IN ({placeholders})", ids
            )
        return cursor.rowcount

    def delete_orphans(self) -> int:
        with self.database.transaction():
            first = self.conn.execute(
                "DELETE FROM semantic_indexes WHERE image_id NOT IN (SELECT image_id FROM images)"
            ).rowcount
            second = self.conn.execute(
                "DELETE FROM semantic_index_failures WHERE image_id NOT IN (SELECT image_id FROM images)"
            ).rowcount
        return first + second

    def classify(
        self,
        image_ids: Iterable[int],
        active_identity: SemanticIndexIdentity,
    ) -> dict[int, SemanticIndexState]:
        result: dict[int, SemanticIndexState] = {}
        for image_id in image_ids:
            image = self.conn.execute(
                "SELECT size_bytes,mtime_ns,quick_fingerprint,file_state FROM images WHERE image_id=?",
                (image_id,),
            ).fetchone()
            if image is None or image[3] == "missing":
                result[image_id] = SemanticIndexState.DELETED
                continue
            row = self.conn.execute(
                f"SELECT {INDEX_COLUMNS},text_embedding FROM semantic_indexes WHERE image_id=?",
                (image_id,),
            ).fetchone()
            if row is None:
                result[image_id] = (
                    SemanticIndexState.FAILED if self.get_failure(image_id)
                    else SemanticIndexState.PENDING
                )
                continue
            metadata = _decode_metadata(row["metadata_json"])
            try:
                validate_embedding_blob(
                    row["text_embedding"], dimension=int(row["embedding_dimension"])
                )
                embedding_ok = True
            except (TypeError, ValueError):
                embedding_ok = False
            if metadata is None or not embedding_ok:
                result[image_id] = SemanticIndexState.CORRUPT
                continue
            source = SourceSnapshot(int(image[0]), int(image[1]), image[2])
            stored = self._metadata(row, metadata)
            mtime_only_same = (
                source.size_bytes == stored.source_size_bytes
                and bool(source.quick_fingerprint)
                and source.quick_fingerprint == stored.source_quick_fingerprint
            )
            if source != stored.source_snapshot and not mtime_only_same:
                result[image_id] = SemanticIndexState.STALE
            elif stored.identity != active_identity:
                result[image_id] = SemanticIndexState.STALE
            else:
                result[image_id] = SemanticIndexState.FRESH
        return result

    def needed_image_ids(
        self,
        image_ids: Iterable[int],
        active_identity: SemanticIndexIdentity,
    ) -> list[int]:
        states = self.classify(image_ids, active_identity)
        return [image_id for image_id, state in states.items() if state.needs_indexing]
