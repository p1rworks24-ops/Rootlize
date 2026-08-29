SCHEMA_VERSION = 7
SEARCH_SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS images (
 image_id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_norm TEXT NOT NULL UNIQUE,
 folder_path TEXT NOT NULL, folder_path_norm TEXT NOT NULL, filename TEXT NOT NULL,
 filename_norm TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
 mtime_ns INTEGER NOT NULL CHECK(mtime_ns>=0), width INTEGER CHECK(width IS NULL OR width>0),
 height INTEGER CHECK(height IS NULL OR height>0), quick_fingerprint TEXT,
 content_sha256 TEXT, file_state TEXT NOT NULL CHECK(file_state IN ('present','missing')),
 discovered_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, missing_since TEXT
);
CREATE INDEX IF NOT EXISTS images_folder_idx ON images(folder_path_norm);
CREATE INDEX IF NOT EXISTS images_fingerprint_idx ON images(size_bytes,mtime_ns,quick_fingerprint);
CREATE INDEX IF NOT EXISTS images_state_idx ON images(file_state);
CREATE TABLE IF NOT EXISTS ocr_documents (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 ocr_text TEXT, ocr_text_norm TEXT NOT NULL DEFAULT '', ocr_text_compact_norm TEXT NOT NULL DEFAULT '',
 average_confidence REAL CHECK(average_confidence IS NULL OR average_confidence BETWEEN 0 AND 1),
 status TEXT NOT NULL CHECK(status IN ('pending','running','ready','failed','stale','missing')),
 previous_status TEXT CHECK(previous_status IS NULL OR previous_status IN ('pending','running','ready','failed','stale')),
 error_type TEXT, error_message_safe TEXT, retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count>=0),
 indexed_at TEXT, engine_name TEXT, engine_version TEXT, model_name TEXT, model_sha256 TEXT,
 pipeline_version INTEGER NOT NULL, normalization_version INTEGER NOT NULL, settings_fingerprint TEXT
 ,claimed_at TEXT, worker_id TEXT, last_attempt_at TEXT, next_retry_at TEXT
);
CREATE TABLE IF NOT EXISTS search_documents (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 filename_norm TEXT NOT NULL DEFAULT '', tags_norm TEXT NOT NULL DEFAULT '',
 ocr_norm TEXT NOT NULL DEFAULT '', ocr_compact_norm TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
 filename_norm,tags_norm,ocr_norm,ocr_compact_norm,
 content='search_documents',content_rowid='image_id',tokenize='trigram case_sensitive 0'
);
CREATE TRIGGER IF NOT EXISTS search_documents_ai AFTER INSERT ON search_documents BEGIN
 INSERT INTO search_fts(rowid,filename_norm,tags_norm,ocr_norm,ocr_compact_norm)
 VALUES(new.image_id,new.filename_norm,new.tags_norm,new.ocr_norm,new.ocr_compact_norm);
END;
CREATE TRIGGER IF NOT EXISTS search_documents_ad AFTER DELETE ON search_documents BEGIN
 INSERT INTO search_fts(search_fts,rowid,filename_norm,tags_norm,ocr_norm,ocr_compact_norm)
 VALUES('delete',old.image_id,old.filename_norm,old.tags_norm,old.ocr_norm,old.ocr_compact_norm);
END;
CREATE TRIGGER IF NOT EXISTS search_documents_au AFTER UPDATE ON search_documents BEGIN
 INSERT INTO search_fts(search_fts,rowid,filename_norm,tags_norm,ocr_norm,ocr_compact_norm)
 VALUES('delete',old.image_id,old.filename_norm,old.tags_norm,old.ocr_norm,old.ocr_compact_norm);
 INSERT INTO search_fts(rowid,filename_norm,tags_norm,ocr_norm,ocr_compact_norm)
 VALUES(new.image_id,new.filename_norm,new.tags_norm,new.ocr_norm,new.ocr_compact_norm);
END;
CREATE TABLE IF NOT EXISTS semantic_embeddings (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 embedding BLOB NOT NULL CHECK(length(embedding)=dimension*4),
 dimension INTEGER NOT NULL CHECK(dimension IN (512,768)),
 embedding_format_version INTEGER NOT NULL CHECK(embedding_format_version>0),
 model_id TEXT NOT NULL, bundle_version TEXT NOT NULL, model_revision TEXT NOT NULL,
 pipeline_version INTEGER NOT NULL CHECK(pipeline_version>0),
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0),
 source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS semantic_embeddings_model_idx ON semantic_embeddings(
 model_id,bundle_version,model_revision,pipeline_version,embedding_format_version
);
CREATE TABLE IF NOT EXISTS semantic_analysis_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 error_code TEXT NOT NULL, retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
 attempt_count INTEGER NOT NULL CHECK(attempt_count>0), last_attempt_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_indexes (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 metadata_json TEXT NOT NULL,
 text_embedding BLOB NOT NULL CHECK(length(text_embedding)=embedding_dimension*4),
 embedding_dimension INTEGER NOT NULL CHECK(embedding_dimension IN (512,768)),
 embedding_format_version INTEGER NOT NULL CHECK(embedding_format_version>0),
 vision_model TEXT NOT NULL,
 prompt_version TEXT NOT NULL,
 index_schema_version TEXT NOT NULL,
 embedding_model_id TEXT NOT NULL,
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0),
 source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS semantic_indexes_identity_idx ON semantic_indexes(
 vision_model,prompt_version,index_schema_version,embedding_model_id,
 embedding_dimension,embedding_format_version
);
CREATE TABLE IF NOT EXISTS semantic_index_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 error_code TEXT NOT NULL, retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
 attempt_count INTEGER NOT NULL CHECK(attempt_count>0), last_attempt_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS image_facts (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 facts_json TEXT NOT NULL,
 vision_model TEXT NOT NULL,
 prompt_version TEXT NOT NULL,
 facts_schema_version TEXT NOT NULL,
 facts_version TEXT NOT NULL,
 source_size_bytes INTEGER NOT NULL CHECK(source_size_bytes>=0),
 source_mtime_ns INTEGER NOT NULL CHECK(source_mtime_ns>=0),
 source_quick_fingerprint TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS image_facts_identity_idx ON image_facts(
 vision_model,prompt_version,facts_schema_version,facts_version
);
CREATE TABLE IF NOT EXISTS image_facts_failures (
 image_id INTEGER PRIMARY KEY REFERENCES images(image_id) ON DELETE CASCADE,
 error_code TEXT NOT NULL, retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
 attempt_count INTEGER NOT NULL CHECK(attempt_count>0), last_attempt_at TEXT NOT NULL
);
"""
