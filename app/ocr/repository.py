from __future__ import annotations

import sqlite3
from pathlib import Path

from app.ocr.database import OCRDatabase
from app.ocr.exceptions import OCRDatabaseError, OCRDuplicatePathError, OCRInvalidRecordError, OCRRecordNotFoundError
from app.ocr.models import ImageRecord, OCRDocumentRecord, SchemaInfo, SearchDocumentRecord, SearchResult
from app.ocr.path_normalization import display_path, normalize_windows_path
from app.ocr.text_normalization import NORMALIZATION_VERSION, normalize_compact_text, normalize_search_text
from app.ocr.schema import SEARCH_SCHEMA_VERSION

IMAGE_COLUMNS = "image_id,path,path_norm,folder_path,folder_path_norm,filename,filename_norm,size_bytes,mtime_ns,width,height,quick_fingerprint,content_sha256,file_state,discovered_at,last_seen_at,missing_since"
OCR_COLUMNS = "image_id,ocr_text,ocr_text_norm,ocr_text_compact_norm,average_confidence,status,previous_status,error_type,error_message_safe,retry_count,indexed_at,engine_name,engine_version,model_name,model_sha256,pipeline_version,normalization_version,settings_fingerprint,claimed_at,worker_id,last_attempt_at,next_retry_at"
SEARCH_COLUMNS = "image_id,filename_norm,tags_norm,ocr_norm,ocr_compact_norm"
OCR_STATUSES = {"pending","running","ready","failed","stale","missing"}


class OCRRepository:
    """Typed CRUD and search boundary for the OCR index database."""

    def __init__(self, database: OCRDatabase):
        self.database = database

    @property
    def conn(self) -> sqlite3.Connection:
        if self.database.connection is None: raise OCRDatabaseError("OCR database is closed.")
        return self.database.connection

    def schema_info(self) -> SchemaInfo:
        values = dict(self.conn.execute("SELECT key,value FROM schema_meta").fetchall())
        return SchemaInfo(int(values["schema_version"]),int(values["normalization_version"]),int(values["search_schema_version"]),values["created_at"],values["updated_at"])

    def upsert_image(self, path: str | Path, *, size_bytes: int, mtime_ns: int, width: int | None = None, height: int | None = None, quick_fingerprint: str | None = None, content_sha256: str | None = None, file_state: str = "present") -> ImageRecord:
        """Register or refresh one image while preserving its image_id."""
        if size_bytes < 0 or mtime_ns < 0 or file_state not in {"present","missing"}: raise OCRInvalidRecordError("Invalid image metadata.")
        shown = display_path(path); norm = normalize_windows_path(path); folder = display_path(nt_parent(shown)); folder_norm = normalize_windows_path(folder); filename = Path(shown).name; filename_norm = normalize_search_text(filename); now = self.database.clock()
        try:
            with self.database.transaction():
                row = self.conn.execute("SELECT image_id,discovered_at FROM images WHERE path_norm=?",(norm,)).fetchone()
                if row:
                    image_id=int(row[0]); self.conn.execute("UPDATE images SET path=?,folder_path=?,folder_path_norm=?,filename=?,filename_norm=?,size_bytes=?,mtime_ns=?,width=?,height=?,quick_fingerprint=?,content_sha256=?,file_state=?,last_seen_at=? WHERE image_id=?",(shown,folder,folder_norm,filename,filename_norm,size_bytes,mtime_ns,width,height,quick_fingerprint,content_sha256,file_state,now,image_id))
                else:
                    cur=self.conn.execute("INSERT INTO images(path,path_norm,folder_path,folder_path_norm,filename,filename_norm,size_bytes,mtime_ns,width,height,quick_fingerprint,content_sha256,file_state,discovered_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(shown,norm,folder,folder_norm,filename,filename_norm,size_bytes,mtime_ns,width,height,quick_fingerprint,content_sha256,file_state,now,now)); image_id=int(cur.lastrowid)
                    self.conn.execute("INSERT INTO search_documents(image_id,filename_norm,tags_norm,ocr_norm,ocr_compact_norm) VALUES(?,?, '', '', '')",(image_id,filename_norm))
            return self.get_image(image_id)
        except sqlite3.IntegrityError as exc: raise OCRDuplicatePathError("Image path conflicts with an existing OCR record.") from exc
        except OCRDatabaseError: raise
        except sqlite3.DatabaseError as exc: raise OCRDatabaseError("Failed to save image record.") from exc

    def get_image(self, image_id: int) -> ImageRecord:
        row=self.conn.execute(f"SELECT {IMAGE_COLUMNS} FROM images WHERE image_id=?",(image_id,)).fetchone()
        if row is None: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
        return ImageRecord(**dict(row))

    def get_image_by_path(self, path: str | Path) -> ImageRecord:
        row=self.conn.execute(f"SELECT {IMAGE_COLUMNS} FROM images WHERE path_norm=?",(normalize_windows_path(path),)).fetchone()
        if row is None: raise OCRRecordNotFoundError("Image record was not found.")
        return ImageRecord(**dict(row))

    def list_images(self, *, folder_path: str | Path | None = None, file_state: str | None = None) -> list[ImageRecord]:
        clauses=[]; params=[]
        if folder_path is not None: clauses.append("folder_path_norm=?"); params.append(normalize_windows_path(folder_path))
        if file_state is not None: clauses.append("file_state=?"); params.append(file_state)
        sql=f"SELECT {IMAGE_COLUMNS} FROM images" + (" WHERE "+" AND ".join(clauses) if clauses else "") + " ORDER BY image_id"
        return [ImageRecord(**dict(row)) for row in self.conn.execute(sql,params)]

    def mark_file_state(self, image_id: int, state: str) -> ImageRecord:
        if state not in {"present","missing"}: raise OCRInvalidRecordError("Invalid file state.")
        with self.database.transaction():
            now=self.database.clock()
            cur=self.conn.execute("UPDATE images SET file_state=?,last_seen_at=?,missing_since=CASE WHEN ?='missing' THEN COALESCE(missing_since,?) ELSE NULL END WHERE image_id=?",(state,now,state,now,image_id))
            if not cur.rowcount: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
            if state == "missing": self.conn.execute("UPDATE ocr_documents SET previous_status=CASE WHEN status<>'missing' THEN status ELSE previous_status END,status='missing' WHERE image_id=?",(image_id,))
        return self.get_image(image_id)

    def save_ocr_document(self, image_id: int, *, status: str, ocr_text: str | None = None, average_confidence: float | None = None, error_type: str | None = None, error_message_safe: str | None = None, retry_count: int = 0, indexed_at: str | None = None, engine_name: str | None = None, engine_version: str | None = None, model_name: str | None = None, model_sha256: str | None = None, pipeline_version: int = 1, settings_fingerprint: str | None = None) -> OCRDocumentRecord:
        """Save OCR state/result and refresh search text atomically."""
        if status not in OCR_STATUSES or retry_count < 0 or (average_confidence is not None and not 0 <= average_confidence <= 1): raise OCRInvalidRecordError("Invalid OCR document.")
        norm=normalize_search_text(ocr_text); compact=normalize_compact_text(ocr_text)
        try:
            with self.database.transaction():
                if not self.conn.execute("SELECT 1 FROM images WHERE image_id=?",(image_id,)).fetchone(): raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
                self.conn.execute("INSERT INTO ocr_documents(image_id,ocr_text,ocr_text_norm,ocr_text_compact_norm,average_confidence,status,previous_status,error_type,error_message_safe,retry_count,indexed_at,engine_name,engine_version,model_name,model_sha256,pipeline_version,normalization_version,settings_fingerprint) VALUES(?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(image_id) DO UPDATE SET ocr_text=excluded.ocr_text,ocr_text_norm=excluded.ocr_text_norm,ocr_text_compact_norm=excluded.ocr_text_compact_norm,average_confidence=excluded.average_confidence,status=excluded.status,previous_status=NULL,error_type=excluded.error_type,error_message_safe=excluded.error_message_safe,retry_count=excluded.retry_count,indexed_at=excluded.indexed_at,engine_name=excluded.engine_name,engine_version=excluded.engine_version,model_name=excluded.model_name,model_sha256=excluded.model_sha256,pipeline_version=excluded.pipeline_version,normalization_version=excluded.normalization_version,settings_fingerprint=excluded.settings_fingerprint",(image_id,ocr_text,norm,compact,average_confidence,status,error_type,error_message_safe,retry_count,indexed_at,engine_name,engine_version,model_name,model_sha256,pipeline_version,NORMALIZATION_VERSION,settings_fingerprint))
                self.conn.execute("UPDATE search_documents SET ocr_norm=?,ocr_compact_norm=? WHERE image_id=?",(norm,compact,image_id))
            return self.get_ocr_document(image_id)
        except sqlite3.DatabaseError as exc: raise OCRDatabaseError("Failed to save OCR document.") from exc

    def get_ocr_document(self, image_id: int) -> OCRDocumentRecord:
        row=self.conn.execute(f"SELECT {OCR_COLUMNS} FROM ocr_documents WHERE image_id=?",(image_id,)).fetchone()
        if row is None: raise OCRRecordNotFoundError(f"OCR document {image_id} was not found.")
        return OCRDocumentRecord(**dict(row))

    def queue_ocr_retry(self, image_ids) -> int:
        """Queue only selected OCR components; Semantic embeddings are untouched."""
        ids = tuple(dict.fromkeys(int(value) for value in image_ids))
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.database.transaction():
            cursor = self.conn.execute(
                f"UPDATE ocr_documents SET status='pending',previous_status=NULL,"
                f"error_type=NULL,error_message_safe=NULL,retry_count=0,claimed_at=NULL,"
                f"worker_id=NULL,next_retry_at=NULL WHERE image_id IN ({placeholders}) "
                "AND status<>'running'",
                ids,
            )
        return int(cursor.rowcount)

    def restore_searchable_ocr(self, image_id: int, *, ready: bool = True) -> None:
        """Put existing OCR text back on the search index. Does not re-read the file."""
        document = self.get_ocr_document(image_id)
        if not document.ocr_text:
            return
        from app.ocr.text_normalization import normalize_compact_text, normalize_search_text

        norm = document.ocr_text_norm or normalize_search_text(document.ocr_text)
        compact = document.ocr_text_compact_norm or normalize_compact_text(document.ocr_text)
        with self.database.transaction():
            self.conn.execute(
                "UPDATE search_documents SET ocr_norm=?,ocr_compact_norm=? WHERE image_id=?",
                (norm, compact, image_id),
            )
            if ready and document.status == "stale":
                self.conn.execute(
                    "UPDATE ocr_documents SET status='ready',previous_status=NULL WHERE image_id=? AND status='stale'",
                    (image_id,),
                )

    def mark_ocr_stale_keep_search(self, image_id: int) -> None:
        """Queue re-OCR without removing the last searchable text."""
        with self.database.transaction():
            self.conn.execute(
                "UPDATE ocr_documents SET status='stale',previous_status=CASE WHEN status<>'stale' THEN status ELSE previous_status END WHERE image_id=?",
                (image_id,),
            )

    def update_tags(self, image_id: int, tags: list[str] | str) -> SearchDocumentRecord:
        text=tags if isinstance(tags,str) else " ".join(tags); value=normalize_search_text(text)
        with self.database.transaction():
            cur=self.conn.execute("UPDATE search_documents SET tags_norm=? WHERE image_id=?",(value,image_id))
            if not cur.rowcount: raise OCRRecordNotFoundError(f"Search document {image_id} was not found.")
        return self.get_search_document(image_id)

    def update_scanned_metadata(self, image_id: int, *, size_bytes: int, mtime_ns: int, width: int, height: int, quick_fingerprint: str, stale: bool) -> ImageRecord:
        """Update file facts, optionally invalidating only OCR search cache."""
        with self.database.transaction():
            cur = self.conn.execute("UPDATE images SET size_bytes=?,mtime_ns=?,width=?,height=?,quick_fingerprint=?,file_state='present',missing_since=NULL,last_seen_at=? WHERE image_id=?", (size_bytes,mtime_ns,width,height,quick_fingerprint,self.database.clock(),image_id))
            if not cur.rowcount: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
            if stale:
                self.conn.execute("UPDATE ocr_documents SET status='stale',previous_status=NULL WHERE image_id=?", (image_id,))
                self.conn.execute("UPDATE search_documents SET ocr_norm='',ocr_compact_norm='' WHERE image_id=?", (image_id,))
        return self.get_image(image_id)

    def restore_image(self, image_id: int, *, size_bytes: int, mtime_ns: int, width: int, height: int, quick_fingerprint: str, content_unchanged: bool) -> ImageRecord:
        """Restore a missing file and either reuse or invalidate its OCR."""
        with self.database.transaction():
            self.conn.execute("UPDATE images SET size_bytes=?,mtime_ns=?,width=?,height=?,quick_fingerprint=?,file_state='present',missing_since=NULL,last_seen_at=? WHERE image_id=?", (size_bytes,mtime_ns,width,height,quick_fingerprint,self.database.clock(),image_id))
            if content_unchanged:
                self.conn.execute("UPDATE ocr_documents SET status=COALESCE(previous_status,CASE WHEN ocr_text IS NOT NULL THEN 'ready' ELSE 'pending' END),previous_status=NULL WHERE image_id=?", (image_id,))
            else:
                self.conn.execute("UPDATE ocr_documents SET status='stale',previous_status=NULL WHERE image_id=?", (image_id,))
                self.conn.execute("UPDATE search_documents SET ocr_norm='',ocr_compact_norm='' WHERE image_id=?", (image_id,))
        return self.get_image(image_id)

    def get_search_document(self, image_id: int) -> SearchDocumentRecord:
        row=self.conn.execute(f"SELECT {SEARCH_COLUMNS} FROM search_documents WHERE image_id=?",(image_id,)).fetchone()
        if row is None: raise OCRRecordNotFoundError(f"Search document {image_id} was not found.")
        return SearchDocumentRecord(**dict(row))

    def update_path(self, image_id: int, new_path: str | Path, *, mtime_ns: int) -> ImageRecord:
        """Rename/move an image without modifying its OCR document."""
        shown=display_path(new_path); norm=normalize_windows_path(new_path); folder=display_path(nt_parent(shown)); folder_norm=normalize_windows_path(folder); filename=Path(shown).name; filename_norm=normalize_search_text(filename)
        try:
            with self.database.transaction():
                cur=self.conn.execute("UPDATE images SET path=?,path_norm=?,folder_path=?,folder_path_norm=?,filename=?,filename_norm=?,mtime_ns=?,last_seen_at=? WHERE image_id=?",(shown,norm,folder,folder_norm,filename,filename_norm,mtime_ns,self.database.clock(),image_id))
                if not cur.rowcount: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")
                self.conn.execute("UPDATE search_documents SET filename_norm=? WHERE image_id=?",(filename_norm,image_id))
            return self.get_image(image_id)
        except sqlite3.IntegrityError as exc: raise OCRDuplicatePathError("Target path already exists in OCR index.") from exc

    def delete_image(self, image_id: int) -> None:
        with self.database.transaction():
            cur=self.conn.execute("DELETE FROM images WHERE image_id=?",(image_id,))
            if not cur.rowcount: raise OCRRecordNotFoundError(f"Image record {image_id} was not found.")

    def delete_path(self, path: str | Path) -> None: self.delete_image(self.get_image_by_path(path).image_id)

    def delete_folder(self, folder_path: str | Path) -> int:
        with self.database.transaction():
            cur=self.conn.execute("DELETE FROM images WHERE folder_path_norm=?",(normalize_windows_path(folder_path),))
            return int(cur.rowcount)

    def search(self, query: str, *, folder_path: str | Path | None = None, file_state: str = "present") -> list[SearchResult]:
        """Search 3+ normalized characters with FTS5 trigram."""
        term=normalize_search_text(query)
        if len(term) < 3: return []
        fts='"'+term.replace('"','""')+'"'; clauses=["search_fts MATCH ?","i.file_state=?"]; params=[fts,file_state]
        if folder_path is not None: clauses.append("i.folder_path_norm=?"); params.append(normalize_windows_path(folder_path))
        sql="SELECT i.image_id,i.path,i.mtime_ns,instr(s.filename_norm,?)>0 matched_filename,instr(s.tags_norm,?)>0 matched_tags,(instr(s.ocr_norm,?)>0 OR instr(s.ocr_compact_norm,?)>0) matched_ocr,bm25(search_fts) rank FROM search_fts JOIN search_documents s ON s.image_id=search_fts.rowid JOIN images i ON i.image_id=s.image_id WHERE "+" AND ".join(clauses)+" ORDER BY rank ASC,i.mtime_ns DESC"
        rows=self.conn.execute(sql,[term,term,term,term,*params]).fetchall()
        return [SearchResult(int(r[0]),r[1],int(r[2]),bool(r[3]),bool(r[4]),bool(r[5]),float(r[6])) for r in rows]

    def search_images(self, query: str, **kwargs):
        """Formal unified search API; legacy ``search`` remains compatible."""
        from app.ocr.search_service import OCRSearchService

        return OCRSearchService(self).search_images(query, **kwargs)

    def fts_counts(self) -> tuple[int,int]:
        return int(self.conn.execute("SELECT count(*) FROM search_documents").fetchone()[0]),int(self.conn.execute("SELECT count(*) FROM search_fts").fetchone()[0])

    def list_ocr_candidates(self, *, folder_path: str | Path, now: str, retry_limit: int = 3) -> list[tuple[ImageRecord, OCRDocumentRecord]]:
        """Return stale, pending, then eligible failed documents."""
        rows=self.conn.execute(
            f"SELECT {','.join('i.'+c for c in IMAGE_COLUMNS.split(','))} FROM images i JOIN ocr_documents o ON o.image_id=i.image_id "
            "WHERE i.folder_path_norm=? AND i.file_state='present' AND (o.status IN ('stale','pending') OR (o.status='failed' AND o.retry_count<? AND (o.next_retry_at IS NULL OR o.next_retry_at<=?))) "
            "ORDER BY CASE o.status WHEN 'stale' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,i.image_id",
            (normalize_windows_path(folder_path),retry_limit,now),
        ).fetchall()
        images=[ImageRecord(**dict(row)) for row in rows]
        return [(image,self.get_ocr_document(image.image_id)) for image in images]

    def claim_ocr(self, image_id: int, *, worker_id: str, claimed_at: str) -> OCRDocumentRecord:
        """Atomically claim one eligible OCR document for this worker."""
        with self.database.transaction():
            cur=self.conn.execute("UPDATE ocr_documents SET status='running',claimed_at=?,worker_id=?,last_attempt_at=?,next_retry_at=NULL WHERE image_id=? AND status IN ('pending','stale','failed') AND worker_id IS NULL",(claimed_at,worker_id,claimed_at,image_id))
            if cur.rowcount != 1: raise OCRInvalidRecordError("OCR document could not be claimed.")
        return self.get_ocr_document(image_id)

    def recover_expired_claims(self, *, before: str) -> int:
        """Release leases older than the supplied UTC threshold without a retry penalty."""
        with self.database.transaction():
            cur=self.conn.execute("UPDATE ocr_documents SET status=CASE WHEN ocr_text IS NULL THEN 'pending' ELSE 'stale' END,claimed_at=NULL,worker_id=NULL WHERE status='running' AND claimed_at<?",(before,))
            return int(cur.rowcount)

    def release_claim(self, image_id: int, *, worker_id: str, status: str) -> None:
        if status not in {"pending","stale","failed"}: raise OCRInvalidRecordError("Invalid released OCR state.")
        with self.database.transaction():
            cur=self.conn.execute("UPDATE ocr_documents SET status=?,claimed_at=NULL,worker_id=NULL WHERE image_id=? AND worker_id=? AND status='running'",(status,image_id,worker_id))
            if cur.rowcount != 1: raise OCRInvalidRecordError("OCR claim ownership does not match.")

    def save_claimed_ocr_success(self, image_id: int, *, worker_id: str, ocr_text: str, average_confidence: float | None, indexed_at: str, engine_name: str | None, engine_version: str | None, model_name: str | None, model_sha256: str | None, pipeline_version: int, settings_fingerprint: str | None) -> OCRDocumentRecord:
        """Commit one verified worker result while preserving filename and tags."""
        norm=normalize_search_text(ocr_text); compact=normalize_compact_text(ocr_text)
        with self.database.transaction():
            cur=self.conn.execute("UPDATE ocr_documents SET ocr_text=?,ocr_text_norm=?,ocr_text_compact_norm=?,average_confidence=?,status='ready',previous_status=NULL,error_type=NULL,error_message_safe=NULL,retry_count=0,indexed_at=?,engine_name=?,engine_version=?,model_name=?,model_sha256=?,pipeline_version=?,normalization_version=?,settings_fingerprint=?,claimed_at=NULL,worker_id=NULL,last_attempt_at=?,next_retry_at=NULL WHERE image_id=? AND worker_id=? AND status='running'",(ocr_text,norm,compact,average_confidence,indexed_at,engine_name,engine_version,model_name,model_sha256,pipeline_version,NORMALIZATION_VERSION,settings_fingerprint,indexed_at,image_id,worker_id))
            if cur.rowcount != 1: raise OCRInvalidRecordError("OCR claim ownership does not match.")
            self.conn.execute("UPDATE search_documents SET ocr_norm=?,ocr_compact_norm=? WHERE image_id=?",(norm,compact,image_id))
        return self.get_ocr_document(image_id)

    def save_claimed_ocr_failure(self, image_id: int, *, worker_id: str, error_type: str, error_message_safe: str, attempted_at: str, increment_retry: bool, next_retry_at: str | None, terminal: bool = False) -> OCRDocumentRecord:
        """Store a safe per-image failure and release its claim."""
        with self.database.transaction():
            cur=self.conn.execute("UPDATE ocr_documents SET status=?,error_type=?,error_message_safe=?,retry_count=retry_count+?,claimed_at=NULL,worker_id=NULL,last_attempt_at=?,next_retry_at=? WHERE image_id=? AND worker_id=? AND status='running'",("failed" if terminal or increment_retry else "stale",error_type,error_message_safe,1 if increment_retry else 0,attempted_at,next_retry_at,image_id,worker_id))
            if cur.rowcount != 1: raise OCRInvalidRecordError("OCR claim ownership does not match.")
        return self.get_ocr_document(image_id)


def nt_parent(path: str) -> str:
    import ntpath
    return ntpath.dirname(path)
