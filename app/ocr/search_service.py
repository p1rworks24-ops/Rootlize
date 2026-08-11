"""UI-independent filename, tag, and OCR text search."""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

from app.ocr.path_normalization import normalize_windows_path
from app.ocr.search_models import SearchPage, UnifiedSearchResult
from app.ocr.text_normalization import normalize_compact_text, normalize_search_text

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
SNIPPET_MAX_CHARS = 160

# A max-base score plus a small multi-field bonus keeps explicit filename/tag
# matches above OCR-only matches while remaining easy to explain and tune.
SCORE_FILENAME_EXACT = 100
SCORE_TAG_EXACT = 90
SCORE_FILENAME_PREFIX = 80
SCORE_TAG_PREFIX = 70
SCORE_FILENAME_SUBSTRING = 60
SCORE_TAG_SUBSTRING = 50
SCORE_OCR_EXACT = 40
SCORE_OCR_SUBSTRING = 30
SCORE_EXTRA_FIELD = 5


class OCRSearchService:
    def __init__(self, repository):
        self.repository = repository

    def search_images(
        self,
        query: str,
        *,
        folder_path: str | Path | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        include_missing: bool = False,
    ) -> SearchPage:
        started = time.perf_counter()
        if limit < 0:
            raise ValueError("limit must not be negative")
        if offset < 0:
            raise ValueError("offset must not be negative")
        limit = min(int(limit), MAX_LIMIT)
        offset = int(offset)
        raw_query = str(query or "")
        term = normalize_search_text(raw_query)
        compact = normalize_compact_text(raw_query)
        if not term:
            return SearchPage(raw_query, "", 0, 0, limit, offset, (), self._elapsed(started), "empty")

        query_mode = "substring" if len(term) < 3 else "fts5_trigram"
        from_sql, where_sql, base_params = self._query_source(
            term, compact, folder_path, include_missing, query_mode
        )
        matches_cte = self._matches_cte(from_sql, where_sql)
        total_sql = matches_cte + " SELECT count(*) FROM matches"
        total_count = int(self.repository.conn.execute(total_sql, base_params).fetchone()[0])

        page_sql = matches_cte + self._page_sql()
        rows = self.repository.conn.execute(
            page_sql, [*base_params, limit, offset]
        ).fetchall()
        results = tuple(self._result_from_row(row, raw_query, term) for row in rows)
        return SearchPage(
            raw_query,
            term,
            total_count,
            len(results),
            limit,
            offset,
            results,
            self._elapsed(started),
            query_mode,
        )

    @staticmethod
    def _elapsed(started: float) -> float:
        return (time.perf_counter() - started) * 1000.0

    @staticmethod
    def _query_source(term, compact, folder_path, include_missing, query_mode):
        if query_mode == "fts5_trigram":
            fts_query = '"' + term.replace('"', '""') + '"'
            source = (
                "search_fts JOIN search_documents s ON s.image_id=search_fts.rowid "
                "JOIN images i ON i.image_id=s.image_id "
                "LEFT JOIN ocr_documents o ON o.image_id=i.image_id "
                "CROSS JOIN query q"
            )
            clauses = ["search_fts MATCH ?"]
            params = [term, compact, fts_query]
        else:
            source = (
                "search_documents s JOIN images i ON i.image_id=s.image_id "
                "LEFT JOIN ocr_documents o ON o.image_id=i.image_id "
                "CROSS JOIN query q"
            )
            clauses = []
            params = [term, compact]
        clauses.append("i.file_state IN ('present','missing')" if include_missing else "i.file_state='present'")
        if folder_path is not None:
            clauses.append("i.folder_path_norm=?")
            params.append(normalize_windows_path(folder_path))
        clauses.append(
            "(instr(s.filename_norm,q.term)>0 OR instr(s.tags_norm,q.term)>0 OR "
            "(o.status='ready' AND (instr(s.ocr_norm,q.term)>0 OR instr(s.ocr_compact_norm,q.compact)>0)))"
        )
        return source, " AND ".join(clauses), params

    @staticmethod
    def _matches_cte(from_sql: str, where_sql: str) -> str:
        return f"""
WITH query(term,compact) AS (VALUES (?,?)),
matches AS (
 SELECT i.image_id,i.path,i.filename,i.mtime_ns,s.filename_norm,s.tags_norm,
        CASE WHEN o.status='ready' THEN s.ocr_norm ELSE '' END AS searchable_ocr_norm,
        CASE WHEN o.status='ready' THEN s.ocr_compact_norm ELSE '' END AS searchable_ocr_compact,
        CASE WHEN o.status='ready' THEN o.ocr_text ELSE NULL END AS ocr_text,
        COALESCE(o.status,'pending') AS ocr_status,
        q.term,q.compact,
        instr(s.filename_norm,q.term)>0 AS matched_filename,
        instr(s.tags_norm,q.term)>0 AS matched_tags,
        (o.status='ready' AND (instr(s.ocr_norm,q.term)>0 OR instr(s.ocr_compact_norm,q.compact)>0)) AS matched_ocr,
        (s.filename_norm=q.term OR s.filename_norm=q.term||'.png') AS filename_exact,
        (instr(s.filename_norm,q.term)=1) AS filename_prefix,
        (instr(' '||s.tags_norm||' ',' '||q.term||' ')>0) AS tag_exact,
        (instr(s.tags_norm,q.term)=1 OR instr(s.tags_norm,' '||q.term)>0) AS tag_prefix,
        (o.status='ready' AND instr(' '||s.ocr_norm||' ',' '||q.term||' ')>0) AS ocr_exact
 FROM {from_sql}
 WHERE {where_sql}
)
"""

    @staticmethod
    def _page_sql() -> str:
        return f"""
, ranked AS (
 SELECT *,
   CASE
    WHEN filename_exact THEN {SCORE_FILENAME_EXACT}
    WHEN tag_exact THEN {SCORE_TAG_EXACT}
    WHEN matched_filename AND filename_prefix THEN {SCORE_FILENAME_PREFIX}
    WHEN matched_tags AND tag_prefix THEN {SCORE_TAG_PREFIX}
    WHEN matched_filename THEN {SCORE_FILENAME_SUBSTRING}
    WHEN matched_tags THEN {SCORE_TAG_SUBSTRING}
    WHEN matched_ocr AND ocr_exact THEN {SCORE_OCR_EXACT}
    WHEN matched_ocr THEN {SCORE_OCR_SUBSTRING}
    ELSE 0 END
   + CASE (matched_filename+matched_tags+matched_ocr)
      WHEN 3 THEN {SCORE_EXTRA_FIELD * 2}
      WHEN 2 THEN {SCORE_EXTRA_FIELD}
      ELSE 0 END AS score
 FROM matches
)
SELECT * FROM ranked
ORDER BY score DESC,mtime_ns DESC,image_id ASC
LIMIT ? OFFSET ?
"""

    @staticmethod
    def _result_from_row(row, raw_query: str, normalized_query: str) -> UnifiedSearchResult:
        values = dict(row)
        matched_filename = bool(values["matched_filename"])
        matched_tags = bool(values["matched_tags"])
        matched_ocr = bool(values["matched_ocr"])
        fields = tuple(
            name
            for name, matched in (
                ("filename", matched_filename),
                ("tags", matched_tags),
                ("image_content", matched_ocr),
            )
            if matched
        )
        filename_type = "none"
        if matched_filename:
            filename_type = "exact" if values["filename_exact"] else ("prefix" if values["filename_prefix"] else "substring")
        tag_type = "none"
        if matched_tags:
            tag_type = "exact" if values["tag_exact"] else ("prefix" if values["tag_prefix"] else "substring")
        ocr_type = "none"
        if matched_ocr:
            ocr_type = "exact" if values["ocr_exact"] else "substring"
        snippet = _make_ocr_snippet(values["ocr_text"], raw_query, normalized_query) if matched_ocr else None
        return UnifiedSearchResult(
            int(values["image_id"]), values["path"], values["filename"], int(values["mtime_ns"]),
            matched_filename, matched_tags, matched_ocr, fields, int(values["score"]),
            filename_type, tag_type, ocr_type, snippet, values["ocr_status"],
        )


def _make_ocr_snippet(text: str | None, raw_query: str, normalized_query: str) -> str | None:
    if not text:
        return None
    readable = re.sub(r"\s+", " ", text).strip()
    if not readable:
        return None
    direct_query = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw_query)).strip()
    direct_index = readable.casefold().find(direct_query.casefold()) if direct_query else -1
    if direct_index < 0:
        normalized_text = normalize_search_text(readable)
        normalized_index = normalized_text.find(normalized_query)
        if normalized_index < 0:
            return None
        direct_index = round(normalized_index / max(1, len(normalized_text)) * len(readable))
    half = SNIPPET_MAX_CHARS // 2
    start = max(0, direct_index - half)
    end = min(len(readable), start + SNIPPET_MAX_CHARS)
    if end - start < SNIPPET_MAX_CHARS:
        start = max(0, end - SNIPPET_MAX_CHARS)
    snippet = readable[start:end].strip()
    return ("…" if start else "") + snippet + ("…" if end < len(readable) else "")
