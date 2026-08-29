"""Eval-only chunk splitting for free-form search documents.

Splits long natural-language search documents into OpenCLIP-safe chunks.
Does not change product Semantic Index or search paths.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tools.meaning_eval.freeform_index import CLIP_CONTEXT_LENGTH

CLIP_CONTENT_LIMIT = CLIP_CONTEXT_LENGTH - 2
CHUNK_STRATEGIES = ("sentence", "paragraph", "overlap_window")

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_RE = re.compile(r"(?<=[,;:])\s+|\s+(?:and|with|while|where|which|that)\s+", re.I)
_WORD_RE = re.compile(r"\S+")


def clip_token_count(runtime, text: str) -> int:
    tokenizer = getattr(runtime, "tokenizer", None)
    if tokenizer is None:
        return len(_WORD_RE.findall(text))
    encode = getattr(tokenizer, "encode", None)
    if encode is None:
        return len(_WORD_RE.findall(text))
    return len(encode(text))


def split_sentences(document: str) -> list[str]:
    text = " ".join(document.split())
    if not text:
        return []
    parts = [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]
    return parts or [text]


def split_clauses(text: str) -> list[str]:
    parts = [part.strip() for part in _CLAUSE_RE.split(text) if part.strip()]
    return parts or [text]


def _split_token_window(text: str, *, max_tokens: int, stride: int) -> list[str]:
    words = _WORD_RE.findall(text)
    if not words:
        return []
    if len(words) <= max_tokens:
        return [" ".join(words)]
    chunks = []
    start = 0
    while start < len(words):
        end = min(len(words), start + max_tokens)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start += stride
    return chunks


def ensure_chunks_fit(runtime, parts: Sequence[str], *, max_tokens: int) -> list[str]:
    out: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if clip_token_count(runtime, part) <= max_tokens:
            out.append(part)
            continue
        for clause in split_clauses(part):
            if clip_token_count(runtime, clause) <= max_tokens:
                out.append(clause)
            else:
                out.extend(
                    _split_token_window(
                        clause,
                        max_tokens=max_tokens,
                        stride=max(8, max_tokens // 2),
                    )
                )
    return out


def split_document(document: str, strategy: str, runtime) -> list[str]:
    text = " ".join(document.split())
    if not text:
        return []
    if strategy == "sentence":
        parts = split_sentences(text)
    elif strategy == "paragraph":
        raw_paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if len(raw_paragraphs) <= 1:
            sentences = split_sentences(text)
            parts = []
            group: list[str] = []
            for sentence in sentences:
                group.append(sentence)
                if len(group) >= 2:
                    parts.append(" ".join(group))
                    group = []
            if group:
                parts.append(" ".join(group))
            if not parts:
                parts = sentences
        else:
            parts = raw_paragraphs
    elif strategy == "overlap_window":
        return ensure_chunks_fit(
            runtime,
            _split_token_window(text, max_tokens=50, stride=25),
            max_tokens=CLIP_CONTENT_LIMIT,
        )
    else:
        raise ValueError(f"unknown chunk strategy: {strategy}")
    return ensure_chunks_fit(runtime, parts, max_tokens=CLIP_CONTENT_LIMIT)


def chunk_stats(runtime, records: dict[str, dict], strategy: str) -> dict:
    counts = []
    for record in records.values():
        if record.get("unknown_reason"):
            continue
        document = str(record.get("search_document") or "").strip()
        if not document:
            continue
        chunks = split_document(document, strategy, runtime)
        counts.append(len(chunks))
    counts.sort()
    n = len(counts)
    median = 0.0
    if counts:
        mid = n // 2
        median = counts[mid] if n % 2 else (counts[mid - 1] + counts[mid]) / 2
    return {
        "strategy": strategy,
        "images": n,
        "chunks_min": min(counts) if counts else 0,
        "chunks_median": median,
        "chunks_max": max(counts) if counts else 0,
        "total_chunks": sum(counts),
    }
