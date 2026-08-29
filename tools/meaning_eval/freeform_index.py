"""Eval-only free-form Index generation, cache, and document-only search.

Does not change product Semantic Index, Ask AI, Hybrid, or Vision Judge.
Embeddings are computed at eval time from the stored search document with
the same OpenCLIP model the product uses. Product SQLite already has
metadata_json + text_embedding + prompt/schema/source columns, so a later
product port would not need a new table.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
import time

from app.ocr.fingerprint import calculate_quick_fingerprint
from app.relevance import RelevanceImage
from app.relevance.openai_provider import (
    _BatchResult,
    _diagnostics_logger,
    _provider_error_reason,
)
from app.relevance.provider import RelevanceProviderError
from app.semantic_index.provider import SemanticIndexProvider
from app.semantic_index.scoring import (
    SearchConfig,
    content_tokens,
    cosine,
    tokenize,
)
from tools.meaning_eval.describe_judge import add_usage, empty_usage, usage_from_run
from tools.meaning_eval.freeform_schema import (
    FREEFORM_PROMPT,
    FREEFORM_PROMPT_VERSION,
    FREEFORM_SCHEMA_VERSION,
    FREEFORM_USER_PREFIX,
    empty_freeform_record,
    freeform_schema,
    search_document,
    unknown_freeform_record,
    validate_freeform_payload,
)

SEARCH_VERSION = "semantic-index-freeform-local-v1"
CLIP_CONTEXT_LENGTH = 77

# Document-only configs. Image cosine is never used. Thresholds may be
# chosen on dev; hold-out must not retune them.
FREEFORM_SEARCH_CONFIGS = (
    SearchConfig("hybrid_v1", 0.50, 0.34, 0.22, 1.01, 0.0),
    SearchConfig("lex_0.50", 0.50, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("lex_0.67", 0.67, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("lex_1.00", 1.00, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("lex_0.34", 0.34, 1.01, 1.01, 1.01, 0.0),
    SearchConfig("txt_0.22", 1.01, 0.0, 0.22, 1.01, 0.0),
    SearchConfig("txt_0.28", 1.01, 0.0, 0.28, 1.01, 0.0),
    SearchConfig("fusion_0.28", 1.01, 1.01, 0.0, 0.0, 0.28, img_weight=0.0, txt_weight=0.45, lex_weight=0.55),
)

PRIMARY_SEARCH_NAME = "hybrid_v1"


class FreeformIndexProvider(SemanticIndexProvider):
    """Vision Index that returns one search document per image."""

    def _index_batch(
        self, batch: Sequence[RelevanceImage]
    ) -> tuple[_BatchResult, tuple[dict, ...]]:
        ids = tuple(item.image_id for item in batch)
        resize_started = time.perf_counter()
        resize_seconds = 0.0
        api_seconds = 0.0
        logger = _diagnostics_logger()
        try:
            encoded = list(zip(batch, self._prepare_images([item.path for item in batch])))
            resize_seconds = time.perf_counter() - resize_started
            content: list[dict] = [{"type": "text", "text": FREEFORM_USER_PREFIX}]
            for item, encoded_image in encoded:
                content.append({"type": "text", "text": f"image_id: {item.image_id}"})
                content.append({
                    "type": "image_url",
                    "image_url": {"url": encoded_image.data_url, "detail": self.image_detail},
                })
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "image_search_document",
                        "strict": True,
                        "schema": freeform_schema(ids),
                    },
                },
            }
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            diagnostics = tuple(
                {
                    "image_id": item.image_id,
                    "jpeg_sha256": encoded_image.sha256,
                    "jpeg_width": encoded_image.width,
                    "jpeg_height": encoded_image.height,
                }
                for item, encoded_image in encoded
            )
            api_started = time.perf_counter()
            response = self._post_with_retry(payload, image_diagnostics=diagnostics)
            api_seconds = time.perf_counter() - api_started
            try:
                raw_content = response["choices"][0]["message"]["content"]
                parsed_payload = (
                    json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                )
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise RelevanceProviderError(
                    "Vision API returned an invalid structured result."
                ) from exc
            parsed = validate_freeform_payload(parsed_payload, ids)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            omitted = [
                item["image_id"] for item in parsed if item.get("unknown_reason") == "omitted"
            ]
            malformed = [
                item["image_id"] for item in parsed if item.get("unknown_reason") == "malformed"
            ]
            if omitted:
                logger.warning(
                    "freeform-index batch-omitted image_ids=%s omitted_ids=%s",
                    list(ids), omitted,
                )
            if malformed:
                logger.warning(
                    "freeform-index batch-malformed image_ids=%s malformed_ids=%s",
                    list(ids), malformed,
                )
            batch_result = _BatchResult(
                results=(),
                image_ids=ids,
                resize_seconds=resize_seconds,
                api_seconds=api_seconds,
                input_tokens=int(usage.get("prompt_tokens", 0) or 0),
                output_tokens=int(usage.get("completion_tokens", 0) or 0),
            )
            return batch_result, parsed
        except RelevanceProviderError as exc:
            reason = _provider_error_reason(exc)
            logger.warning(
                "freeform-index batch-failure reason=%s image_ids=%s error=%s",
                reason, list(ids), self._safe_error(exc),
            )
            return (
                self._unknown_batch(ids, reason, resize_seconds, api_seconds),
                tuple(unknown_freeform_record(image_id, reason) for image_id in ids),
            )
        except json.JSONDecodeError:
            logger.warning(
                "freeform-index batch-malformed image_ids=%s error=JSONDecodeError",
                list(ids),
            )
            return (
                self._unknown_batch(ids, "malformed", resize_seconds, api_seconds),
                tuple(unknown_freeform_record(image_id, "malformed") for image_id in ids),
            )


def make_freeform_provider() -> FreeformIndexProvider:
    return FreeformIndexProvider(
        max_edge=512,
        image_detail="low",
        temperature=0,
        batch_size=2,
        timeout_seconds=180,
        max_workers=2,
        system_prompt=FREEFORM_PROMPT,
        prompt_version=FREEFORM_PROMPT_VERSION,
        include_relevance_score=False,
    )


def source_snapshot(path: Path) -> dict:
    stat = path.stat()
    return {
        "source_size_bytes": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
        "source_quick_fingerprint": calculate_quick_fingerprint(path),
    }


def _snapshot_mismatch(record: dict, path: Path) -> bool:
    stored_fp = record.get("source_quick_fingerprint")
    if not stored_fp:
        return False
    try:
        current = source_snapshot(path)
    except OSError:
        return True
    return (
        int(record.get("source_size_bytes") or -1) != current["source_size_bytes"]
        or stored_fp != current["source_quick_fingerprint"]
    )


def load_freeform_cache(path: Path) -> tuple[dict[str, dict], dict] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prompt_version") != FREEFORM_PROMPT_VERSION:
        return None
    if payload.get("schema_version") != FREEFORM_SCHEMA_VERSION:
        return None
    by_name = payload.get("by_name")
    if not isinstance(by_name, dict):
        return None
    return by_name, dict(payload.get("usage") or empty_usage())


def save_freeform_cache(path: Path, by_name: dict[str, dict], usage: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "prompt_version": FREEFORM_PROMPT_VERSION,
                "schema_version": FREEFORM_SCHEMA_VERSION,
                "usage": usage,
                "by_name": by_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def index_paths(
    paths: Sequence[Path],
    provider: FreeformIndexProvider,
    *,
    cancelled=None,
) -> tuple[dict[str, dict], dict]:
    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    run = provider.index(images, cancelled=cancelled)
    by_name = {}
    for item, result in zip(images, run.results):
        record = dict(result)
        record["image_id"] = item.image_id
        record.update(source_snapshot(item.path))
        by_name[item.path.name] = record
    return by_name, usage_from_run(run)


def load_or_index_paths(
    paths: Sequence[Path],
    cache_path: Path,
    *,
    provider: FreeformIndexProvider | None = None,
    cancelled=None,
) -> tuple[dict[str, dict], dict, bool]:
    needed = {path.name for path in paths}
    cached = load_freeform_cache(cache_path)
    by_name: dict[str, dict] = {}
    usage = empty_usage()
    if cached is not None:
        by_name, usage = cached
    missing = []
    for path in paths:
        record = by_name.get(path.name) or {}
        if (
            path.name not in by_name
            or record.get("unknown_reason")
            or not search_document(record)
            or _snapshot_mismatch(record, path)
        ):
            missing.append(path)
    reused = not missing and needed <= set(by_name)
    if missing:
        provider = provider or make_freeform_provider()
        fresh, fresh_usage = index_paths(missing, provider, cancelled=cancelled)
        by_name.update(fresh)
        add_usage(usage, fresh_usage)
        save_freeform_cache(cache_path, by_name, usage)
    elif cached is None:
        save_freeform_cache(cache_path, by_name, usage)
    return by_name, usage, reused


def _has_phrase(needle: str, haystack: str) -> bool:
    needle_tokens = tokenize(needle)
    hay_tokens = tokenize(haystack)
    if not needle_tokens or not hay_tokens:
        return False
    if needle_tokens == hay_tokens:
        return True
    width = len(needle_tokens)
    for index in range(len(hay_tokens) - width + 1):
        if hay_tokens[index:index + width] == needle_tokens:
            return True
    return False


def _coverage(query_tokens: Sequence[str], haystack_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    hits = 0
    for token in query_tokens:
        forms = {token}
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            forms.add(token[:-1])
        if forms & haystack_tokens:
            hits += 1
    return hits / len(query_tokens)


def document_token_set(record: dict) -> set[str]:
    tokens: set[str] = set()
    for token in tokenize(search_document(record)):
        tokens.add(token)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            tokens.add(token[:-1])
    return tokens


def freeform_lexical_score(query: str, record: dict) -> float:
    if record.get("unknown_reason"):
        return 0.0
    document = search_document(record).lower()
    query_l = query.lower().strip()
    if not document or not query_l:
        return 0.0
    phrase = 1.0 if _has_phrase(query_l, document) else 0.0
    tokens = content_tokens(query_l)
    if not tokens:
        return 0.0
    coverage = _coverage(tokens, document_token_set(record))
    if phrase == 0.0 and coverage < 0.34:
        return 0.0
    return min(1.0, max(phrase, coverage))


def freeform_include_hit(txt: float, lex: float, config: SearchConfig) -> bool:
    if lex >= config.lex_include:
        return True
    if lex >= config.lex_support and txt >= config.txt_min:
        return True
    if config.combined_min > 0:
        combined = config.txt_weight * txt + config.lex_weight * lex
        if combined >= config.combined_min:
            return True
    return False


def freeform_combined_score(txt: float, lex: float, config: SearchConfig) -> float:
    img_weight = 0.0
    txt_weight = config.txt_weight
    lex_weight = config.lex_weight
    total = img_weight + txt_weight + lex_weight
    if total <= 0:
        return 0.0
    return (txt_weight * txt + lex_weight * lex) / total


def freeform_index_judgement(
    query: str,
    record: dict,
    *,
    query_vector: Sequence[float] | None,
    text_vector: Sequence[float] | None,
    config: SearchConfig,
) -> dict:
    if record.get("unknown_reason"):
        return {
            "relevant": None,
            "relevance_score": None,
            "confidence": None,
            "reason": record.get("unknown_reason"),
            "unknown_reason": record.get("unknown_reason"),
        }
    lex = freeform_lexical_score(query, record)
    txt = cosine(query_vector, text_vector)
    img = 0.0
    combined = freeform_combined_score(txt, lex, config)
    hit = freeform_include_hit(txt, lex, config)
    return {
        "relevant": hit,
        "relevance_score": combined,
        "confidence": lex,
        "reason": f"lex={lex:.3f} txt={txt:.3f} img={img:.3f}",
        "lex": lex,
        "txt": txt,
        "img": img,
    }


def search_freeform_records(
    query: str,
    names: Sequence[str],
    records: dict[str, dict],
    *,
    query_vector: Sequence[float] | None,
    text_vectors: dict[str, Sequence[float]],
    config: SearchConfig,
) -> dict:
    scored = []
    judgements = {}
    failed_names = []
    for name in names:
        record = records.get(name) or empty_freeform_record(unknown_reason="missing")
        if record.get("unknown_reason"):
            failed_names.append(name)
            judgements[name] = {
                "relevant": None,
                "relevance_score": None,
                "confidence": None,
                "reason": record.get("unknown_reason"),
                "unknown_reason": record.get("unknown_reason"),
                "low_relevant": None,
                "high_relevant": None,
            }
            continue
        judged = freeform_index_judgement(
            query,
            record,
            query_vector=query_vector,
            text_vector=text_vectors.get(name),
            config=config,
        )
        judged["low_relevant"] = None
        judged["high_relevant"] = None
        judgements[name] = judged
        if judged.get("relevant"):
            scored.append((judged["relevance_score"], name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    predicted = [name for _, name in scored]
    return {
        "predicted": predicted,
        "judgements": judgements,
        "failed_names": failed_names,
        "cancelled": False,
        "usage": empty_usage(),
    }


def clip_token_count(runtime, text: str) -> int:
    tokenizer = getattr(runtime, "tokenizer", None)
    if tokenizer is None:
        return 0
    encode = getattr(tokenizer, "encode", None)
    if encode is None:
        return 0
    return len(encode(text))


def measure_clip_truncation(runtime, records: dict[str, dict]) -> dict:
    truncated = 0
    total = 0
    token_counts = []
    limit = CLIP_CONTEXT_LENGTH - 2
    for record in records.values():
        if record.get("unknown_reason"):
            continue
        document = search_document(record)
        if not document:
            continue
        total += 1
        count = clip_token_count(runtime, document)
        token_counts.append(count)
        if count > limit:
            truncated += 1
    token_counts.sort()
    n = len(token_counts)
    median = 0
    if token_counts:
        mid = n // 2
        median = token_counts[mid] if n % 2 else (token_counts[mid - 1] + token_counts[mid]) / 2
    return {
        "clip_context_length": CLIP_CONTEXT_LENGTH,
        "content_token_limit": limit,
        "images": total,
        "truncated_images": truncated,
        "truncation_rate": (truncated / total) if total else 0.0,
        "token_count_min": min(token_counts) if token_counts else 0,
        "token_count_median": median,
        "token_count_max": max(token_counts) if token_counts else 0,
    }


def document_length_stats(records: dict[str, dict]) -> dict:
    lengths = []
    words = []
    examples_short = []
    examples_long = []
    too_short = 0
    for name, record in records.items():
        if record.get("unknown_reason"):
            continue
        document = search_document(record)
        char_count = len(document)
        word_count = len(document.split())
        lengths.append((name, char_count, word_count, document))
        words.append(word_count)
        if char_count < 400 or word_count < 80:
            too_short += 1
    lengths.sort(key=lambda item: item[1])
    n = len(lengths)
    def percentile(values: list[int], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
        return float(ordered[index])

    char_values = [item[1] for item in lengths]
    word_values = [item[2] for item in lengths]
    for item in lengths[:3]:
        examples_short.append({
            "name": item[0],
            "chars": item[1],
            "words": item[2],
            "preview": item[3][:280],
        })
    for item in reversed(lengths[-3:]):
        examples_long.append({
            "name": item[0],
            "chars": item[1],
            "words": item[2],
            "preview": item[3][:280],
        })
    return {
        "images": n,
        "chars_min": min(char_values) if char_values else 0,
        "chars_p10": percentile(char_values, 0.10),
        "chars_median": percentile(char_values, 0.50),
        "chars_p90": percentile(char_values, 0.90),
        "chars_max": max(char_values) if char_values else 0,
        "words_min": min(word_values) if word_values else 0,
        "words_p10": percentile(word_values, 0.10),
        "words_median": percentile(word_values, 0.50),
        "words_p90": percentile(word_values, 0.90),
        "words_max": max(word_values) if word_values else 0,
        "too_short_images": too_short,
        "too_short_rule": "chars<400 or words<80",
        "shortest": examples_short,
        "longest": examples_long,
    }
