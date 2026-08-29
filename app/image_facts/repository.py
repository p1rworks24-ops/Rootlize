from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRDatabaseError, OCRInvalidRecordError, OCRRecordNotFoundError
from app.semantic.models import SourceSnapshot
from app.ai_usage.models import REASON_FACTS_VERSION, REASON_FIRST, REASON_REPARSE
from app.image_facts.format import facts_only, prepare_facts_record
from app.image_facts.models import (
    ImageFactsFailureRecord,
    ImageFactsIdentity,
    ImageFactsMetadata,
    ImageFactsState,
)
from app.image_facts.schema import FACT_FIELDS, FACTS_SCHEMA_VERSION

FACTS_COLUMNS = (
    "image_id,facts_json,vision_model,prompt_version,facts_schema_version,facts_version,"
    "source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at"
)


def _encode_facts(record: dict) -> str:
    payload = facts_only(record)
    missing = [name for name in FACT_FIELDS if name not in payload]
    if missing:
        raise OCRInvalidRecordError("Invalid image facts metadata.")
    if record.get("unknown_reason"):
        raise OCRInvalidRecordError("Failed image facts cannot be stored as fresh.")
    media = payload.get("media_type")
    if media not in {"photograph", "screenshot", "illustration", "mixed", "other"}:
        raise OCRInvalidRecordError("Invalid image facts metadata.")
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _decode_facts(raw: object) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    missing = [name for name in FACT_FIELDS if name not in payload]
    if missing:
        return None
    return prepare_facts_record(payload)


class ImageFactsRepository:
    def __init__(self, database: OCRDatabase):
        self.database = database

    @property
    def conn(self) -> sqlite3.Connection:
        if self.database.connection is None:
            raise OCRDatabaseError("OCR database is closed.")
        return self.database.connection

    def _metadata(self, row: sqlite3.Row, facts: dict) -> ImageFactsMetadata:
        data = dict(row)
        data.pop("facts_json", None)
        data["facts"] = facts
        data["schema_version"] = data.pop("facts_schema_version")
        return ImageFactsMetadata(**data)

    def get_facts(self, image_id: int) -> ImageFactsMetadata | None:
        row = self.conn.execute(
            f"SELECT {FACTS_COLUMNS} FROM image_facts WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        facts = _decode_facts(row["facts_json"])
        if facts is None:
            return None
        facts["image_id"] = int(image_id)
        return self._metadata(row, facts)

    def get_facts_map(self, image_ids: Iterable[int]) -> dict[int, ImageFactsMetadata]:
        ids = tuple(int(value) for value in image_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT {FACTS_COLUMNS} FROM image_facts WHERE image_id IN ({placeholders})",
            ids,
        ).fetchall()
        result: dict[int, ImageFactsMetadata] = {}
        for row in rows:
            facts = _decode_facts(row["facts_json"])
            if facts is None:
                continue
            image_id = int(row["image_id"])
            facts["image_id"] = image_id
            result[image_id] = self._metadata(row, facts)
        return result

    def upsert_facts(
        self,
        image_id: int,
        record: dict,
        identity: ImageFactsIdentity,
        source: SourceSnapshot,
    ) -> ImageFactsMetadata:
        if not all((identity.vision_model, identity.prompt_version, identity.schema_version, identity.facts_version)):
            raise OCRInvalidRecordError("Invalid image facts identity.")
        facts_json = _encode_facts(record)
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
                    raise OCRInvalidRecordError("Image source snapshot changed before image facts save.")
                self.conn.execute(
                    """INSERT INTO image_facts(
 image_id,facts_json,vision_model,prompt_version,facts_schema_version,facts_version,
 source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at
) VALUES(?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(image_id) DO UPDATE SET
 facts_json=excluded.facts_json,vision_model=excluded.vision_model,
 prompt_version=excluded.prompt_version,facts_schema_version=excluded.facts_schema_version,
 facts_version=excluded.facts_version,source_size_bytes=excluded.source_size_bytes,
 source_mtime_ns=excluded.source_mtime_ns,source_quick_fingerprint=excluded.source_quick_fingerprint,
 updated_at=excluded.updated_at""",
                    (
                        image_id, facts_json, identity.vision_model, identity.prompt_version,
                        identity.schema_version, identity.facts_version, source.size_bytes,
                        source.mtime_ns, source.quick_fingerprint, now, now,
                    ),
                )
                self.conn.execute("DELETE FROM image_facts_failures WHERE image_id=?", (image_id,))
            stored = self.get_facts(image_id)
            assert stored is not None
            return stored
        except (OCRInvalidRecordError, OCRRecordNotFoundError):
            raise
        except sqlite3.DatabaseError as exc:
            raise OCRDatabaseError("Failed to save image facts.") from exc

    def record_failure(
        self,
        image_id: int,
        error_code: str,
        retryable: bool = True,
        attempted_at: str | None = None,
    ) -> ImageFactsFailureRecord:
        if not error_code or len(error_code) > 100:
            raise OCRInvalidRecordError("Invalid image facts error code.")
        attempted_at = attempted_at or self.database.clock()
        with self.database.transaction():
            self.conn.execute(
                """INSERT INTO image_facts_failures(image_id,error_code,retryable,attempt_count,last_attempt_at)
VALUES(?,?,?,?,?)
ON CONFLICT(image_id) DO UPDATE SET
 error_code=excluded.error_code,retryable=excluded.retryable,
 attempt_count=image_facts_failures.attempt_count+1,
 last_attempt_at=excluded.last_attempt_at""",
                (image_id, error_code, int(retryable), 1, attempted_at),
            )
        row = self.conn.execute(
            "SELECT * FROM image_facts_failures WHERE image_id=?",
            (image_id,),
        ).fetchone()
        data = dict(row)
        data["retryable"] = bool(data["retryable"])
        return ImageFactsFailureRecord(**data)

    def get_failure(self, image_id: int) -> ImageFactsFailureRecord | None:
        row = self.conn.execute(
            "SELECT * FROM image_facts_failures WHERE image_id=?",
            (image_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["retryable"] = bool(data["retryable"])
        return ImageFactsFailureRecord(**data)

    def classify(
        self,
        image_ids: Iterable[int],
        active_identity: ImageFactsIdentity,
    ) -> dict[int, ImageFactsState]:
        result: dict[int, ImageFactsState] = {}
        for image_id in image_ids:
            image = self.conn.execute(
                "SELECT size_bytes,mtime_ns,quick_fingerprint,file_state FROM images WHERE image_id=?",
                (image_id,),
            ).fetchone()
            if image is None or image[3] == "missing":
                result[image_id] = ImageFactsState.DELETED
                continue
            row = self.conn.execute(
                f"SELECT {FACTS_COLUMNS} FROM image_facts WHERE image_id=?",
                (image_id,),
            ).fetchone()
            if row is None:
                result[image_id] = (
                    ImageFactsState.FAILED if self.get_failure(image_id)
                    else ImageFactsState.PENDING
                )
                continue
            facts = _decode_facts(row["facts_json"])
            if facts is None:
                result[image_id] = ImageFactsState.CORRUPT
                continue
            source = SourceSnapshot(int(image[0]), int(image[1]), image[2])
            stored = self._metadata(row, facts)
            mtime_only_same = (
                source.size_bytes == stored.source_size_bytes
                and bool(source.quick_fingerprint)
                and source.quick_fingerprint == stored.source_quick_fingerprint
            )
            if source != stored.source_snapshot and not mtime_only_same:
                result[image_id] = ImageFactsState.STALE
            elif stored.identity != active_identity:
                result[image_id] = ImageFactsState.STALE
            else:
                result[image_id] = ImageFactsState.FRESH
        return result

    def needed_image_ids(
        self,
        image_ids: Iterable[int],
        active_identity: ImageFactsIdentity,
    ) -> list[int]:
        states = self.classify(image_ids, active_identity)
        return [image_id for image_id, state in states.items() if state.needs_generation]

    def generation_reasons(
        self,
        image_ids: Iterable[int],
        active_identity: ImageFactsIdentity,
    ) -> dict[int, str]:
        """Why each needed image would cause a Vision request. No paths or facts."""
        states = self.classify(image_ids, active_identity)
        reasons: dict[int, str] = {}
        stored_map = self.get_facts_map(
            image_id for image_id, state in states.items() if state.needs_generation
        )
        for image_id, state in states.items():
            if not state.needs_generation:
                continue
            stored = stored_map.get(image_id)
            if stored is None:
                reasons[image_id] = REASON_FIRST
            elif stored.facts_version != active_identity.facts_version:
                reasons[image_id] = REASON_FACTS_VERSION
            else:
                reasons[image_id] = REASON_REPARSE
        return reasons

    def fresh_facts_for_search(
        self,
        image_ids: Iterable[int],
        active_identity: ImageFactsIdentity,
    ) -> dict[int, dict]:
        states = self.classify(image_ids, active_identity)
        fresh_ids = [image_id for image_id, state in states.items() if state == ImageFactsState.FRESH]
        stored = self.get_facts_map(fresh_ids)
        return {image_id: item.facts for image_id, item in stored.items()}
