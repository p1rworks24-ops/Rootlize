from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from app.ocr.exceptions import OCRDatabaseCorruptionError, OCRDatabaseError, OCRDatabaseSchemaError, OCRFTSUnavailableError
from app.ocr.schema import SCHEMA_SQL, SCHEMA_VERSION, SEARCH_SCHEMA_VERSION
from app.ocr.text_normalization import NORMALIZATION_VERSION
from app.paths import get_local_app_data_dir
from app.utils.logger import setup_logger

logger = setup_logger()
DB_FILE_NAME = "ocr-index.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OCRDatabase:
    """Own one SQLite connection for the regenerable OCR index."""

    def __init__(self, path: Path | None = None, *, busy_timeout_ms: int = 3000, clock: Callable[[], str] = utc_now, verify_fts: bool = True):
        self.path = (path or (get_local_app_data_dir() / DB_FILE_NAME)).resolve()
        self.busy_timeout_ms = busy_timeout_ms
        self.clock = clock
        self.verify_fts = verify_fts
        self.connection: sqlite3.Connection | None = None
        self._transaction_lock = threading.RLock()

    def open(self) -> "OCRDatabase":
        """Open and initialize the database."""
        if self.connection is not None: return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
            mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
            if mode != "wal": raise OCRDatabaseError(f"WAL mode unavailable (mode={mode}).")
            self.connection = conn
            if self.verify_fts: self._check_fts5()
            self._initialize_schema()
            logger.info("OCR index database initialized (schema %d)", SCHEMA_VERSION)
            return self
        except OCRDatabaseError:
            self.close(); raise
        except sqlite3.DatabaseError as exc:
            self.close(); raise OCRDatabaseError("Failed to initialize OCR index database.") from exc

    def _check_fts5(self) -> None:
        assert self.connection is not None
        try:
            self.connection.execute("CREATE VIRTUAL TABLE temp.__ocr_fts_probe USING fts5(value,tokenize='trigram')")
            self.connection.execute("DROP TABLE temp.__ocr_fts_probe")
        except sqlite3.DatabaseError as exc:
            raise OCRFTSUnavailableError("SQLite FTS5 trigram tokenizer is unavailable.") from exc

    def _initialize_schema(self) -> None:
        assert self.connection is not None
        exists = self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone()
        if exists:
            row = self.connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if row is None: raise OCRDatabaseSchemaError("OCR schema version is missing.")
            version = int(row[0])
            if version > SCHEMA_VERSION: raise OCRDatabaseSchemaError(f"OCR schema {version} is newer than supported schema {SCHEMA_VERSION}.")
            if version < SCHEMA_VERSION: self._migrate(version)
            return
        now = self.clock()
        # executescript commits an already-open transaction.  Put BEGIN in the
        # script itself so schema creation and its version metadata stay atomic.
        try:
            self.connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_SQL)
            self.connection.executemany("INSERT INTO schema_meta(key,value) VALUES(?,?)", (("schema_version",str(SCHEMA_VERSION)),("normalization_version",str(NORMALIZATION_VERSION)),("search_schema_version",str(SEARCH_SCHEMA_VERSION)),("created_at",now),("updated_at",now)))
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def _migrate(self, old_version: int) -> None:
        if old_version not in {1,2,3,4,5,6}:
            raise OCRDatabaseSchemaError(f"No migration path from OCR schema {old_version}.")
        now = self.clock()
        with self.transaction():
            if old_version == 1:
                self.connection.execute("ALTER TABLE images ADD COLUMN missing_since TEXT")
                self.connection.execute("ALTER TABLE ocr_documents ADD COLUMN previous_status TEXT CHECK(previous_status IS NULL OR previous_status IN ('pending','running','ready','failed','stale'))")
            if old_version < 3:
                self.connection.execute("ALTER TABLE ocr_documents ADD COLUMN claimed_at TEXT")
                self.connection.execute("ALTER TABLE ocr_documents ADD COLUMN worker_id TEXT")
                self.connection.execute("ALTER TABLE ocr_documents ADD COLUMN last_attempt_at TEXT")
                self.connection.execute("ALTER TABLE ocr_documents ADD COLUMN next_retry_at TEXT")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS semantic_embeddings (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 embedding BLOB NOT NULL CHECK(length(embedding)=dimension*4), dimension INTEGER NOT NULL CHECK(dimension IN (512,768)),
 embedding_format_version INTEGER NOT NULL CHECK(embedding_format_version>0), model_id TEXT NOT NULL,
 bundle_version TEXT NOT NULL, model_revision TEXT NOT NULL, pipeline_version INTEGER NOT NULL CHECK(pipeline_version>0),
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0), source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            self.connection.execute("""CREATE INDEX IF NOT EXISTS semantic_embeddings_model_idx
 ON semantic_embeddings(model_id,bundle_version,model_revision,pipeline_version,embedding_format_version)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS semantic_analysis_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE, error_code TEXT NOT NULL,
 retryable INTEGER NOT NULL CHECK(retryable IN (0,1)), attempt_count INTEGER NOT NULL CHECK(attempt_count>0),
 last_attempt_at TEXT NOT NULL)""")
            if old_version == 4:
                self.connection.execute("DROP INDEX IF EXISTS semantic_embeddings_model_idx")
                self.connection.execute("ALTER TABLE semantic_embeddings RENAME TO semantic_embeddings_v4")
                self.connection.execute("""CREATE TABLE semantic_embeddings (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 embedding BLOB NOT NULL CHECK(length(embedding)=dimension*4),
 dimension INTEGER NOT NULL CHECK(dimension IN (512,768)),
 embedding_format_version INTEGER NOT NULL CHECK(embedding_format_version>0), model_id TEXT NOT NULL,
 bundle_version TEXT NOT NULL, model_revision TEXT NOT NULL, pipeline_version INTEGER NOT NULL CHECK(pipeline_version>0),
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0), source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                self.connection.execute("""INSERT INTO semantic_embeddings
 SELECT image_id,embedding,dimension,embedding_format_version,model_id,bundle_version,model_revision,
 pipeline_version,source_size_bytes,source_mtime_ns,source_quick_fingerprint,created_at,updated_at
 FROM semantic_embeddings_v4""")
                self.connection.execute("DROP TABLE semantic_embeddings_v4")
                self.connection.execute("""CREATE INDEX semantic_embeddings_model_idx
 ON semantic_embeddings(model_id,bundle_version,model_revision,pipeline_version,embedding_format_version)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS semantic_indexes (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 metadata_json TEXT NOT NULL,
 text_embedding BLOB NOT NULL CHECK(length(text_embedding)=embedding_dimension*4),
 embedding_dimension INTEGER NOT NULL CHECK(embedding_dimension IN (512,768)),
 embedding_format_version INTEGER NOT NULL CHECK(embedding_format_version>0),
 vision_model TEXT NOT NULL, prompt_version TEXT NOT NULL, index_schema_version TEXT NOT NULL,
 embedding_model_id TEXT NOT NULL,
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0),
 source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            self.connection.execute("""CREATE INDEX IF NOT EXISTS semantic_indexes_identity_idx
 ON semantic_indexes(vision_model,prompt_version,index_schema_version,embedding_model_id,embedding_dimension,embedding_format_version)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS semantic_index_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE, error_code TEXT NOT NULL,
 retryable INTEGER NOT NULL CHECK(retryable IN (0,1)), attempt_count INTEGER NOT NULL CHECK(attempt_count>0),
 last_attempt_at TEXT NOT NULL)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS image_facts (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 facts_json TEXT NOT NULL, vision_model TEXT NOT NULL, prompt_version TEXT NOT NULL,
 facts_schema_version TEXT NOT NULL, facts_version TEXT NOT NULL,
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0),
 source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            self.connection.execute("""CREATE INDEX IF NOT EXISTS image_facts_identity_idx
 ON image_facts(vision_model,prompt_version,facts_schema_version,facts_version)""")
            self.connection.execute("""CREATE TABLE IF NOT EXISTS image_facts_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE, error_code TEXT NOT NULL,
 retryable INTEGER NOT NULL CHECK(retryable IN (0,1)), attempt_count INTEGER NOT NULL CHECK(attempt_count>0),
 last_attempt_at TEXT NOT NULL)""")
            self.connection.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            self.connection.execute("UPDATE schema_meta SET value=? WHERE key='updated_at'", (now,))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a short immediate transaction with rollback on failure."""
        if self.connection is None: raise OCRDatabaseError("OCR database is closed.")
        with self._transaction_lock:
            if self.connection.in_transaction:
                yield self.connection
                return
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                self.connection.execute("COMMIT")
            except Exception:
                if self.connection.in_transaction: self.connection.execute("ROLLBACK")
                raise

    def quick_check(self) -> str:
        if self.connection is None: raise OCRDatabaseError("OCR database is closed.")
        try: result = str(self.connection.execute("PRAGMA quick_check").fetchone()[0])
        except sqlite3.DatabaseError as exc: raise OCRDatabaseCorruptionError("OCR database integrity check failed.") from exc
        if result != "ok": raise OCRDatabaseCorruptionError("OCR database is corrupt.")
        return result

    def rebuild_fts(self) -> None:
        if self.connection is None: raise OCRDatabaseError("OCR database is closed.")
        try:
            with self.transaction(): self.connection.execute("INSERT INTO search_fts(search_fts) VALUES('rebuild')")
            logger.info("OCR search index rebuilt")
        except sqlite3.DatabaseError as exc: raise OCRDatabaseError("Failed to rebuild OCR search index.") from exc

    def schema_version(self) -> int:
        if self.connection is None: raise OCRDatabaseError("OCR database is closed.")
        row = self.connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        if row is None: raise OCRDatabaseSchemaError("OCR schema version is missing.")
        return int(row[0])

    def close(self) -> None:
        """Rollback active work and close the owned connection."""
        if self.connection is not None:
            if self.connection.in_transaction: self.connection.rollback()
            self.connection.close(); self.connection = None

    def __enter__(self): return self.open()
    def __exit__(self, *_args): self.close()
