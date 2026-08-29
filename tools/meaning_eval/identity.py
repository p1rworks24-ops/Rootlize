"""Run identity for a Meaning-search evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess

from app.relevance.openai_provider import PROMPT_VERSION, SCHEMA_VERSION
from app.semantic.catalog import MODEL_IDS, OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_MODEL_ID = MODEL_IDS[OPENCLIP_MODEL_KEY]


def git_identity(root: Path = ROOT) -> dict:
    def run(args: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                args, cwd=root, check=False, capture_output=True, text=True
            )
        except OSError:
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    commit = run(["git", "rev-parse", "HEAD"])
    dirty = run(["git", "status", "--porcelain"])
    return {
        "git_commit": commit,
        "git_dirty": bool(dirty),
    }


def corpus_identity(paths: list[Path]) -> dict:
    digest = hashlib.sha256()
    ordered = sorted(paths, key=lambda path: path.name.lower())
    for path in ordered:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        digest.update(str(size).encode("ascii"))
        digest.update(b"\n")
    return {
        "count": len(ordered),
        "names_sizes_sha256": digest.hexdigest(),
        "names": [path.name for path in ordered],
    }


def build_identity(
    *,
    dataset,
    corpus: dict,
    model_id: str = OFFICIAL_MODEL_ID,
    query_embedding: str = DEFAULT_QUERY_EMBEDDING,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    timestamp: str | None = None,
) -> dict:
    git = git_identity()
    when = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "timestamp": when,
        "git_commit": git["git_commit"],
        "git_dirty": git["git_dirty"],
        "retrieval_model_id": model_id,
        "query_embedding": query_embedding,
        "vision_prompt_version": prompt_version,
        "vision_schema_version": schema_version,
        "query_set_version": dataset.query_set_version,
        "query_set_hash": dataset.query_set_hash,
        "gt_version": dataset.gt_version,
        "gt_hash": dataset.gt_hash,
        "corpus_count": corpus["count"],
        "corpus_sha256": corpus["names_sizes_sha256"],
    }
