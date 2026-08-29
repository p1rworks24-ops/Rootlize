"""Query-independent Semantic Index field meaning, prompt, and JSON schema.

Product persistence, Hybrid scoring, and the evaluation PoC share this
module so the meaning of each field is not defined twice.
"""

from __future__ import annotations

from collections.abc import Sequence

INDEX_PROMPT_VERSION = "semantic-index-v4"
INDEX_SCHEMA_VERSION = "image-semantic-index-v3"

STRING_LIMITS = {
    "visual_summary": 400,
    "scene_environment": 240,
    "incidental_notes": 400,
}
LIST_FIELDS = {
    "objects_entities": (20, 80),
    "ui_interface_concepts": (16, 80),
    "visible_activities": (12, 80),
    "visual_attributes": (12, 80),
    "searchable_concepts": (20, 80),
}
IDENTITIES_MAX = 24
IDENTITY_NAME_MAX = 80
IDENTITY_EVIDENCE_MAX = 160
IDENTITY_KINDS = (
    "application",
    "service",
    "software",
    "website",
    "brand",
    "product",
    "game",
    "character",
    "person",
    "animal",
    "object",
    "ui",
    "other",
)
IDENTITY_IMPORTANCE = ("primary", "secondary", "incidental")
IDENTITY_CONFIDENCE = ("high", "likely", "uncertain")
SEARCHABLE_CONFIDENCE = frozenset({"high", "likely"})
CLIP_INDEX_TEXT_LIMIT = 300
MEDIA_TYPES = ("screenshot", "photograph", "illustration", "mixed", "other")
INDEX_FIELDS = (
    "visual_summary",
    "objects_entities",
    "scene_environment",
    "media_type",
    "ui_interface_concepts",
    "visible_activities",
    "visual_attributes",
    "searchable_concepts",
    "identities",
    "incidental_notes",
)

INDEX_PROMPT = """You write a query-independent search index for images.

A later local search will match user words against this index. You will not
see any user query. Do not infer queries. Do not judge relevance. Do not
decide whether the image would be a useful search result.

Your job is searchable coverage, not a short caption. Record everything a
person might later type to find this image: applications, services, games,
brands, products, people, characters, places, objects, UI kinds, scene,
activities, relationships, and salient visual attributes. Include primary,
secondary, and incidental context when it is identifiable.

Ground every item in visible evidence. Do not hallucinate names, places,
people, or brands with no visual support.

Allowed recognition from visible evidence:
- UI layout, tabs, toolbars, menus, icons, logos, art style, game HUD, or
  other distinctive visual features that reasonably identify an app, service,
  game, brand, product, website, character, or object.
- Visible text, logos, icons, and unmistakable product appearance.

Not allowed:
- Names or facts with no visible support in the image.
- World-knowledge guesses when the image itself is ambiguous.
- Extra synonyms from world knowledge that are not visually justified.

Importance (how central the thing is in the image) and confidence (how sure
you are of the identification) are separate:
- importance: primary, secondary, or incidental.
- confidence: high, likely, or uncertain.

Do not skip an identifiable thing only because importance is secondary or
incidental, or because confidence is not high. Still record it in identities
and the searchable list fields when visually justified.

For every supplied image:

- visual_summary: one short paragraph of what the image is primarily of.
  If a named program, site, or environment frames the main content, mention
  that container as well as the inner content.
- objects_entities: visible objects, beings, and identifiable named entities.
  Include the main subject and other clearly identifiable items a person
  might later search for. Prefer a visible specific name plus an ordinary
  kind-name. Include visually recognized product or app names even when no
  readable label is present, when UI, logo, icon, or layout is distinctive.
  Include the visible outer program or site that contains the main content.
  Omit things too small, cropped, blurry, or unclear to identify.
- scene_environment: setting or surrounding environment
- media_type: screenshot, photograph, illustration, mixed, or other
- ui_interface_concepts: visible interface kinds, including nested ones.
  Always keep the ordinary kind-name, even when a more specific layout term
  is also true. Use kind-names such as editor, terminal, browser, settings,
  file manager, gallery, installer, dialog, form, game, chat, desktop,
  video player, search results, dashboard, sidebar, tabs, or toolbar. A grid
  of picture thumbnails is gallery. A text-editing workspace is editor.
  Include both the outer program and the inner view when both are visible.
  Leave empty when no interface is visible.
- visible_activities: visible actions, poses, tasks, and relationships
  among subjects, such as a person holding a phone or a browser showing a
  chat.
- visual_attributes: salient look, color, theme, style, layout, or clothing
  traits a person might search for. Skip tiny decorative details.
- searchable_concepts: ordinary words and close synonyms a person might type
  to find this image. Cover the primary subject, visually recognized named
  entities, the containing program or environment, interface kinds, scene,
  activity, and distinctive attributes. Keep specific visible or visually
  recognized names. Also add the ordinary kind-name when that generalization
  is visually justified. Do not add generic computer-screen words that apply
  to most captures unless that is the subject.
- identities: structured recognitions for identifiable applications,
  services, software, websites, brands, products, games, characters,
  people, animals, objects, and UI elements. For each item include:
  name, kind, importance, confidence, and a short evidence phrase citing
  what you saw (UI feature, logo, icon, readable text, layout, etc.).
  Use uncertain only when some evidence exists but identification is weak.
  Omit entries with no visual evidence.
- incidental_notes: clearly visible secondary or background context that
  is not the main subject, such as other windows, nearby objects, or
  surroundings. Identifiable named programs and objects still belong in
  objects_entities, searchable_concepts, and identities even when they are
  secondary; use this field for leftover context, not as the only place to
  store a visible product name.

If a content area is blank, unused, or showing placeholders with no items,
say that in visual_summary and searchable_concepts using words such as blank,
unused, placeholder, or no items.

If the capture is a desktop environment, distinguish wallpaper, shortcuts,
and open windows. If source or markup text is the main pane, say so.

Include important visible text that identifies the image: product or program
names, page titles, headings, game titles, error text, and distinctive
labels. Do not transcribe long body text.

Describe the visible image itself. Do not use filenames or assumed metadata.
Return exactly one result for every supplied image_id."""

INDEX_USER_PREFIX = (
    "Write a query-independent search index for every following image. "
    "Record searchable evidence from visible text and from distinctive visual "
    "features such as UI, logos, icons, and layout. Use identities with "
    "importance and confidence. Do not guess unseen details. Do not infer a "
    "user query or judge relevance."
)


def empty_index_record(*, unknown_reason: str | None = None) -> dict:
    return {
        "visual_summary": "",
        "objects_entities": [],
        "scene_environment": "",
        "media_type": "other",
        "ui_interface_concepts": [],
        "visible_activities": [],
        "visual_attributes": [],
        "searchable_concepts": [],
        "identities": [],
        "incidental_notes": "",
        "unknown_reason": unknown_reason,
    }


def index_record(**fields: object) -> dict:
    record = empty_index_record()
    for name, value in fields.items():
        record[name] = value
    return record


def unknown_index_record(image_id: int, reason: str) -> dict:
    record = empty_index_record(unknown_reason=reason)
    record["image_id"] = image_id
    return record


def _identity_item_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string", "maxLength": IDENTITY_NAME_MAX},
            "kind": {"type": "string", "enum": list(IDENTITY_KINDS)},
            "importance": {"type": "string", "enum": list(IDENTITY_IMPORTANCE)},
            "confidence": {"type": "string", "enum": list(IDENTITY_CONFIDENCE)},
            "evidence": {"type": "string", "maxLength": IDENTITY_EVIDENCE_MAX},
        },
        "required": ["name", "kind", "importance", "confidence", "evidence"],
        "additionalProperties": False,
    }


def index_schema(image_ids: Sequence[int]) -> dict:
    properties = {
        "image_id": {"type": "integer", "enum": list(image_ids)},
        "visual_summary": {"type": "string", "maxLength": STRING_LIMITS["visual_summary"]},
        "scene_environment": {
            "type": "string",
            "maxLength": STRING_LIMITS["scene_environment"],
        },
        "media_type": {"type": "string", "enum": list(MEDIA_TYPES)},
        "incidental_notes": {
            "type": "string",
            "maxLength": STRING_LIMITS["incidental_notes"],
        },
        "identities": {
            "type": "array",
            "minItems": 0,
            "maxItems": IDENTITIES_MAX,
            "items": _identity_item_schema(),
        },
    }
    for name, (max_items, max_length) in LIST_FIELDS.items():
        properties[name] = {
            "type": "array",
            "minItems": 0,
            "maxItems": max_items,
            "items": {"type": "string", "maxLength": max_length},
        }
    required = ["image_id", *INDEX_FIELDS]
    return {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }


def clip_text(value: object, limit: int) -> str:
    return str(value or "")[:limit]


def clip_list(value: object, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for raw in value[:max_items]:
        text = clip_text(raw, max_length).strip()
        if text:
            items.append(text)
    return items


def clip_identities(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    items: list[dict] = []
    for raw in value[:IDENTITIES_MAX]:
        if not isinstance(raw, dict):
            continue
        name = clip_text(raw.get("name"), IDENTITY_NAME_MAX).strip()
        kind = raw.get("kind")
        importance = raw.get("importance")
        confidence = raw.get("confidence")
        evidence = clip_text(raw.get("evidence"), IDENTITY_EVIDENCE_MAX).strip()
        if (
            not name
            or kind not in IDENTITY_KINDS
            or importance not in IDENTITY_IMPORTANCE
            or confidence not in IDENTITY_CONFIDENCE
            or not evidence
        ):
            continue
        items.append({
            "name": name,
            "kind": kind,
            "importance": importance,
            "confidence": confidence,
            "evidence": evidence,
        })
    return items


def searchable_identity_names(record: dict) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in record.get("identities") or []:
        if not isinstance(item, dict):
            continue
        if item.get("confidence") not in SEARCHABLE_CONFIDENCE:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def merge_identity_names(record: dict) -> None:
    """Ensure high/likely identity names also appear in searchable list fields."""
    for name in searchable_identity_names(record):
        for field in ("objects_entities", "searchable_concepts"):
            items = list(record.get(field) or [])
            if not any(str(item).lower() == name.lower() for item in items):
                items.append(name)
            record[field] = items


def metadata_only(record: dict) -> dict:
    return {name: record.get(name) for name in INDEX_FIELDS}


def clip_index_text(record: dict) -> str:
    """Short OpenCLIP-friendly document. Named entities first."""
    seen: set[str] = set()
    parts: list[str] = []

    def add(value: object) -> None:
        text = str(value or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        parts.append(text)

    for name in searchable_identity_names(record):
        add(name)
    for name in (
        "objects_entities",
        "searchable_concepts",
        "ui_interface_concepts",
        "visible_activities",
        "visual_attributes",
    ):
        for item in record.get(name) or []:
            add(item)
    add(record.get("scene_environment"))
    add(record.get("incidental_notes"))
    add(record.get("media_type"))
    text = ", ".join(parts)
    summary = str(record.get("visual_summary") or "").strip()
    if summary:
        room = CLIP_INDEX_TEXT_LIMIT - len(text) - (2 if text else 0)
        if room >= 24:
            snippet = summary if len(summary) <= room else summary[:room]
            text = f"{text}. {snippet}" if text else snippet
    return text[:CLIP_INDEX_TEXT_LIMIT]


def normalize_index_record(raw: dict) -> dict | None:
    """Return a ready metadata record, or None when the payload is unusable."""
    if not isinstance(raw, dict):
        return None
    missing = [name for name in INDEX_FIELDS if name not in raw]
    if missing:
        return None
    media = raw.get("media_type")
    if media not in MEDIA_TYPES:
        return None
    record = empty_index_record()
    if "image_id" in raw:
        try:
            record["image_id"] = int(raw["image_id"])
        except (TypeError, ValueError):
            return None
    record["visual_summary"] = clip_text(
        raw.get("visual_summary"), STRING_LIMITS["visual_summary"]
    )
    record["scene_environment"] = clip_text(
        raw.get("scene_environment"), STRING_LIMITS["scene_environment"]
    )
    record["incidental_notes"] = clip_text(
        raw.get("incidental_notes"), STRING_LIMITS["incidental_notes"]
    )
    record["media_type"] = media
    for name, (max_items, max_length) in LIST_FIELDS.items():
        record[name] = clip_list(raw.get(name), max_items, max_length)
    record["identities"] = clip_identities(raw.get("identities"))
    merge_identity_names(record)
    record["unknown_reason"] = None
    return record


def validate_index_payload(payload: dict, expected_ids: Sequence[int]) -> tuple[dict, ...]:
    expected = list(expected_ids)
    expected_set = set(expected)
    judged: dict[int, dict] = {}
    unknown: dict[int, str] = {}
    raw_results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw_results, list):
        return tuple(unknown_index_record(image_id, "malformed") for image_id in expected)
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        try:
            image_id = int(raw["image_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if image_id not in expected_set or image_id in judged or image_id in unknown:
            continue
        record = normalize_index_record(raw)
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
        by_id[image_id] = unknown_index_record(image_id, reason)
    return tuple(by_id[image_id] for image_id in expected)
