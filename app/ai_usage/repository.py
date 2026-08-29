"""Persist API usage in a dedicated SQLite file, not the OCR/facts schema."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.ai_usage.models import AiUsageEvent, AiUsageTotals
from app.paths import get_local_app_data_dir

USAGE_FILE_NAME = "ai-usage.sqlite3"
USAGE_SCHEMA_VERSION = 1

USAGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage_events (
 event_id INTEGER PRIMARY KEY,
 occurred_at TEXT NOT NULL,
 kind TEXT NOT NULL,
 operation TEXT NOT NULL,
 model TEXT NOT NULL DEFAULT '',
 request_count INTEGER NOT NULL DEFAULT 0,
 input_tokens INTEGER NOT NULL DEFAULT 0,
 output_tokens INTEGER NOT NULL DEFAULT 0,
 image_count INTEGER NOT NULL DEFAULT 0,
 first_image_count INTEGER NOT NULL DEFAULT 0,
 reparse_count INTEGER NOT NULL DEFAULT 0,
 facts_version_regen_count INTEGER NOT NULL DEFAULT 0,
 query_count INTEGER NOT NULL DEFAULT 0,
 candidate_count INTEGER NOT NULL DEFAULT 0,
 batch_count INTEGER NOT NULL DEFAULT 0,
 matcher_image_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_usage_totals (
 metric TEXT PRIMARY KEY,
 value INTEGER NOT NULL DEFAULT 0
);
"""

_TOTAL_METRICS = (
    "vision.facts_image_count",
    "vision.request_count",
    "vision.reparse_count",
    "vision.facts_version_regen_count",
    "search.query_count",
    "search.candidate_count",
    "search.text_llm_request_count",
    "search.batch_count",
    "search.matcher_image_count",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_usage_path() -> Path:
    return get_local_app_data_dir() / USAGE_FILE_NAME


class AiUsageRepository:
    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], str] = utc_now,
    ):
        self.path = (path or default_usage_path()).resolve()
        self.clock = clock
        self.connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def open(self) -> "AiUsageRepository":
        if self.connection is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            timeout=3.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(USAGE_SCHEMA_SQL)
        now = self.clock()
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version',?)",
            (str(USAGE_SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('created_at',?)",
            (now,),
        )
        for metric in _TOTAL_METRICS:
            conn.execute(
                "INSERT OR IGNORE INTO ai_usage_totals(metric,value) VALUES(?,0)",
                (metric,),
            )
        self.connection = conn
        return self

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def record(
        self,
        *,
        kind: str,
        operation: str,
        model: str = "",
        request_count: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        image_count: int = 0,
        first_image_count: int = 0,
        reparse_count: int = 0,
        facts_version_regen_count: int = 0,
        query_count: int = 0,
        candidate_count: int = 0,
        batch_count: int = 0,
        matcher_image_count: int = 0,
    ) -> AiUsageEvent:
        self.open()
        assert self.connection is not None
        occurred_at = self.clock()
        increments = {}
        if kind == "vision":
            increments = {
                "vision.facts_image_count": image_count,
                "vision.request_count": request_count,
                "vision.reparse_count": reparse_count,
                "vision.facts_version_regen_count": facts_version_regen_count,
            }
        elif kind == "search_text":
            increments = {
                "search.query_count": query_count,
                "search.candidate_count": candidate_count,
                "search.text_llm_request_count": request_count,
                "search.batch_count": batch_count,
                "search.matcher_image_count": matcher_image_count,
            }
        with self._lock:
            cursor = self.connection.execute(
                """INSERT INTO ai_usage_events(
 occurred_at,kind,operation,model,request_count,input_tokens,output_tokens,
 image_count,first_image_count,reparse_count,facts_version_regen_count,
 query_count,candidate_count,batch_count,matcher_image_count
) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    occurred_at, kind, operation, model or "",
                    int(request_count), int(input_tokens), int(output_tokens),
                    int(image_count), int(first_image_count), int(reparse_count),
                    int(facts_version_regen_count), int(query_count),
                    int(candidate_count), int(batch_count), int(matcher_image_count),
                ),
            )
            for metric, delta in increments.items():
                if delta:
                    self.connection.execute(
                        "UPDATE ai_usage_totals SET value=value+? WHERE metric=?",
                        (int(delta), metric),
                    )
            event_id = int(cursor.lastrowid)
        return AiUsageEvent(
            event_id=event_id,
            occurred_at=occurred_at,
            kind=kind,
            operation=operation,
            model=model or "",
            request_count=int(request_count),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            image_count=int(image_count),
            first_image_count=int(first_image_count),
            reparse_count=int(reparse_count),
            facts_version_regen_count=int(facts_version_regen_count),
            query_count=int(query_count),
            candidate_count=int(candidate_count),
            batch_count=int(batch_count),
            matcher_image_count=int(matcher_image_count),
        )

    def totals(self) -> AiUsageTotals:
        self.open()
        assert self.connection is not None
        rows = {
            str(row["metric"]): int(row["value"])
            for row in self.connection.execute("SELECT metric,value FROM ai_usage_totals")
        }
        return AiUsageTotals(
            vision_facts_image_count=rows.get("vision.facts_image_count", 0),
            vision_request_count=rows.get("vision.request_count", 0),
            vision_reparse_count=rows.get("vision.reparse_count", 0),
            vision_facts_version_regen_count=rows.get("vision.facts_version_regen_count", 0),
            search_query_count=rows.get("search.query_count", 0),
            search_candidate_count=rows.get("search.candidate_count", 0),
            search_text_llm_request_count=rows.get("search.text_llm_request_count", 0),
            search_batch_count=rows.get("search.batch_count", 0),
            search_matcher_image_count=rows.get("search.matcher_image_count", 0),
        )

    def events(self) -> tuple[AiUsageEvent, ...]:
        self.open()
        assert self.connection is not None
        rows = self.connection.execute(
            "SELECT * FROM ai_usage_events ORDER BY event_id"
        ).fetchall()
        return tuple(
            AiUsageEvent(
                event_id=int(row["event_id"]),
                occurred_at=str(row["occurred_at"]),
                kind=str(row["kind"]),
                operation=str(row["operation"]),
                model=str(row["model"] or ""),
                request_count=int(row["request_count"]),
                input_tokens=int(row["input_tokens"]),
                output_tokens=int(row["output_tokens"]),
                image_count=int(row["image_count"]),
                first_image_count=int(row["first_image_count"]),
                reparse_count=int(row["reparse_count"]),
                facts_version_regen_count=int(row["facts_version_regen_count"]),
                query_count=int(row["query_count"]),
                candidate_count=int(row["candidate_count"]),
                batch_count=int(row["batch_count"]),
                matcher_image_count=int(row["matcher_image_count"]),
            )
            for row in rows
        )

    def __enter__(self):
        return self.open()

    def __exit__(self, *_args):
        self.close()
