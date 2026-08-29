"""Eval-only free-form search-document Index. Not used by product search.

Product Semantic Index stays on semantic-index-v4 / image-semantic-index-v3.
This module is imported only by meaning_eval tools and their tests.
"""

from __future__ import annotations

from collections.abc import Sequence

FREEFORM_PROMPT_VERSION = "semantic-index-freeform-v1"
FREEFORM_SCHEMA_VERSION = "image-search-document-v1"
SEARCH_DOCUMENT_MAX = 8000
SEARCH_DOCUMENT_FIELD = "search_document"

FREEFORM_PROMPT = """You write a query-independent search document for an image.

A later local search will embed this document and match unknown user queries
against it. You will not see any user query. Do not infer queries. Do not
judge relevance. Do not decide whether the image would be a useful result.

Your job is a retrieval document, not a caption and not a short summary.
A person should be able to find this image later with words they remember:
app names, service names, brands, products, websites, games, people,
animals, objects, UI kinds, UI parts, OS or app environment, containment,
actions, relationships, place or scene, visual attributes such as dark or
light, colors, layout, important readable text, logos, icons, and
incidental background context.

Write enough that an unknown future query can still match. Do not drop
information because it is not the main subject. If Chrome is showing
ChatGPT, the document must contain Google Chrome, web browser, ChatGPT,
chat interface, tabs, address bar, toolbar, and any other identifiable
visible content, and it must say how they relate (for example, ChatGPT is
open inside a Chrome window). If Chrome is only in the background, say
that relationship in sentences.

Allowed recognition from visible evidence:
- UI layout, tabs, toolbars, menus, icons, logos, art style, game HUD, or
  other distinctive visual features that reasonably identify an app,
  service, game, brand, product, website, character, or object, even when
  no readable label is present.
- Visible text, logos, icons, and unmistakable product appearance.

Not allowed:
- Names or facts with no visible support in the image.
- World-knowledge guesses when the image itself is ambiguous.
- Padding with generic computer-screen words that are not actually visible.

Do not make the document short just because the image looks simple. Cover
several visual angles: subject, secondary subjects, background, environment,
UI if any, colors, lighting or theme, layout, notable text, logos, and
incidental items. Rich images must not omit identifiable content to stay
brief. Do not pad with repetition. Do not aim at a fixed character count.
Never return a one-line caption.

Write in natural English sentences and short paragraphs. Prefer specific
visible or visually recognized names together with ordinary kind-names
(for example Google Chrome and web browser; Cursor and code editor).

Start with one dense opening sentence that names every identifiable
application, service, product, game, brand, website, person, animal, object,
and UI kind. Then continue with a thorough description of subject,
containment, UI parts, scene, actions, relationships, visual attributes,
important text, logos, icons, and incidental context.

If a content area is blank, unused, or showing placeholders, say so with
words such as blank, unused, placeholder, or no items. If the capture is a
desktop, distinguish wallpaper, shortcuts, and open windows. Describe the
visible image itself. Do not use filenames or assumed metadata.

Return exactly one result for every supplied image_id."""

FREEFORM_USER_PREFIX = (
    "Write a query-independent search document for every following image. "
    "This document will be stored and used later to find the image from "
    "unknown search queries. Be thorough and specific. Record visible and "
    "visually recognizable names, UI, scene, relationships, and incidental "
    "context. Do not write a short summary. Do not guess unseen details. "
    "Do not infer a user query or judge relevance."
)


def empty_freeform_record(*, unknown_reason: str | None = None) -> dict:
    return {
        SEARCH_DOCUMENT_FIELD: "",
        "unknown_reason": unknown_reason,
    }


def unknown_freeform_record(image_id: int, reason: str) -> dict:
    record = empty_freeform_record(unknown_reason=reason)
    record["image_id"] = image_id
    return record


def freeform_schema(image_ids: Sequence[int]) -> dict:
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_id": {"type": "integer", "enum": list(image_ids)},
                        SEARCH_DOCUMENT_FIELD: {
                            "type": "string",
                            "maxLength": SEARCH_DOCUMENT_MAX,
                        },
                    },
                    "required": ["image_id", SEARCH_DOCUMENT_FIELD],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def clip_document(value: object) -> str:
    return str(value or "")[:SEARCH_DOCUMENT_MAX].strip()


def normalize_freeform_record(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if SEARCH_DOCUMENT_FIELD not in raw:
        return None
    document = clip_document(raw.get(SEARCH_DOCUMENT_FIELD))
    if not document:
        return None
    record = empty_freeform_record()
    if "image_id" in raw:
        try:
            record["image_id"] = int(raw["image_id"])
        except (TypeError, ValueError):
            return None
    record[SEARCH_DOCUMENT_FIELD] = document
    record["unknown_reason"] = None
    return record


def validate_freeform_payload(
    payload: dict, expected_ids: Sequence[int]
) -> tuple[dict, ...]:
    expected = list(expected_ids)
    expected_set = set(expected)
    judged: dict[int, dict] = {}
    unknown: dict[int, str] = {}
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return tuple(unknown_freeform_record(image_id, "malformed") for image_id in expected)
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        try:
            image_id = int(raw["image_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if image_id not in expected_set or image_id in judged or image_id in unknown:
            continue
        record = normalize_freeform_record(raw)
        if record is None:
            unknown[image_id] = "malformed"
            continue
        record["image_id"] = image_id
        judged[image_id] = record
    for image_id in expected:
        if image_id not in judged and image_id not in unknown:
            unknown[image_id] = "omitted"
    by_id = dict(judged)
    for image_id, reason in unknown.items():
        by_id[image_id] = unknown_freeform_record(image_id, reason)
    return tuple(by_id[image_id] for image_id in expected)


def search_document(record: dict) -> str:
    return str(record.get(SEARCH_DOCUMENT_FIELD) or "").strip()
