"""Normalize and format stored image-facts-v3 records."""

from __future__ import annotations

from app.image_facts.schema import FACT_FIELDS

HOST_CHROME_TOKENS = (
    "tab",
    "tabs",
    "address bar",
    "omnibox",
    "title bar",
    "window frame",
    "window chrome",
    "browser chrome",
    "window controls",
    "menu bar",
)
TEXT_ONLY_HOST_HINTS = (
    "chip",
    "chips",
    "label",
    "labels",
    "mention",
    "text chip",
    "text bubble",
    "rounded pill",
    "repeated text",
)
BLOCKED_APP_SURFACES = ("shortcut", "taskbar icon", "launcher icon", "thumbnail")
GLUE_CONDITION_LABELS = {
    "showing",
    "show",
    "with",
    "in",
    "and",
    "of",
    "on",
    "a",
    "the",
    "for",
    "visible",
}
EXPLICIT_ENTITY_ALIASES = (
    ("dog", ("dog", "puppy", "puppies", "shiba inu", "shiba")),
    ("cat", ("cat", "kitten", "kittens", "calico")),
)


def normalize_condition_label(label: object) -> str:
    return " ".join(str(label or "").strip().lower().replace("-", " ").split())


def facts_only(record: dict) -> dict:
    payload = {name: record.get(name) for name in FACT_FIELDS}
    payload["media_type"] = record.get("media_type") or "other"
    payload["scene_description"] = str(record.get("scene_description") or "")
    payload["environment"] = str(record.get("environment") or "")
    payload["ui_types"] = list(record.get("ui_types") or [])
    payload["entities"] = [dict(item) for item in (record.get("entities") or []) if isinstance(item, dict)]
    payload["applications"] = [
        dict(item) for item in (record.get("applications") or []) if isinstance(item, dict)
    ]
    payload["activities"] = list(record.get("activities") or [])
    payload["relationships"] = list(record.get("relationships") or [])
    payload["notable_text"] = list(record.get("notable_text") or [])
    return payload


def normalize_surface_roles(record: dict) -> dict:
    """Keep shortcut/icon/thumbnail out of applications; lift posture from attributes."""
    record = dict(record)
    record["applications"] = [
        item
        for item in record.get("applications") or []
        if not any(token in (item.get("visible_content") or "").lower() for token in BLOCKED_APP_SURFACES)
    ]
    for entity in record.get("entities") or []:
        posture = (entity.get("posture") or "").strip().lower()
        attributes = list(entity.get("attributes") or [])
        posture_attributes = [
            item for item in attributes if str(item).strip().lower() in {"sitting", "standing", "lying"}
        ]
        if not posture and len(posture_attributes) == 1:
            entity["posture"] = str(posture_attributes[0]).strip().lower()
            entity["attributes"] = [item for item in attributes if item not in posture_attributes]
    return record


def _is_browser_app(item: dict) -> bool:
    blob = f"{item.get('name') or ''} {item.get('category') or ''} {item.get('kind') or ''}".lower()
    return "browser" in blob


def visible_content_is_text_mention(visible: str) -> bool:
    """True when visible_content is labels/chips rather than product UI."""
    vis = (visible or "").lower()
    if not vis:
        return False
    if not any(hint in vis for hint in TEXT_ONLY_HOST_HINTS):
        return False
    if any(token in vis for token in HOST_CHROME_TOKENS):
        return False
    if "browser window" in vis or "tab strip" in vis or "address bar" in vis:
        return False
    return True


def _content_only_host(item: dict) -> bool:
    if not _is_browser_app(item):
        return False
    visible = (item.get("visible_content") or "").lower()
    if not visible:
        return False
    if visible_content_is_text_mention(visible):
        return True
    if any(token in visible for token in HOST_CHROME_TOKENS):
        return False
    if "browser" in visible or "chrome window" in visible:
        return False
    name = (item.get("name") or "").strip().lower()
    if name and name in visible:
        return False
    return True


def normalize_host_identity(record: dict) -> dict:
    """Drop host-application rows that only describe inner content."""
    record = dict(record)
    kept_apps = []
    dropped_names = list(record.get("_dropped_host_names") or [])
    for item in record.get("applications") or []:
        if _content_only_host(item):
            dropped_names.append(str(item.get("name") or "").strip())
            continue
        kept_apps.append(item)
    record["applications"] = kept_apps
    record["_dropped_host_names"] = [name for name in dropped_names if name]
    if dropped_names:
        dropped_l = {name.lower() for name in dropped_names if name}
        record["relationships"] = [
            row
            for row in (record.get("relationships") or [])
            if not any(name in str(row).lower() for name in dropped_l)
        ]
        if not any(_is_browser_app(item) for item in kept_apps):
            record["ui_types"] = [
                item
                for item in (record.get("ui_types") or [])
                if "browser" not in str(item).lower()
            ]
    return record


def prepare_facts_record(record: dict) -> dict:
    return normalize_host_identity(normalize_surface_roles(facts_only(record)))


def format_fact_record(record: dict) -> str:
    apps = record.get("applications") or []
    entities = record.get("entities") or []
    app_lines = []
    for item in apps:
        category = item.get("category") or "(no category)"
        theme = item.get("theme") or "unknown"
        app_lines.append(
            f"  - {item.get('name')} [{category}] "
            f"({item.get('kind')}, {item.get('role')}, {theme}): "
            f"{item.get('visible_content')}"
        )
    entity_lines = []
    for item in entities:
        colors = "/".join(item.get("colors") or []) or "(none)"
        observed = item.get("observed_color_description") or "(none)"
        posture = item.get("posture") or "(unconfirmed)"
        states = "/".join(item.get("states") or []) or "(none)"
        attributes = "/".join(item.get("attributes") or []) or "(none)"
        entity_lines.append(
            "  - "
            f"name={item.get('name')}; kind={item.get('kind')}; "
            f"posture={posture}; canonical_colors={colors}; "
            f"observed_color={observed}; states={states}; "
            f"attributes={attributes}; visibility={item.get('visibility')}; "
            f"identifiability={item.get('identifiability')}"
        )
    ui_types = record.get("ui_types") or []
    lines = [
        f"image_id: {record.get('image_id')}",
        f"media_type: {record.get('media_type')}",
        f"environment: {record.get('environment') or '(none)'}",
        "ui_types: " + ", ".join(ui_types) if ui_types else "ui_types: (none)",
        f"scene: {record.get('scene_description')}",
        "entities:",
        *(entity_lines or ["  - (none)"]),
        "applications:",
        *(app_lines or ["  - (none)"]),
        "activities: " + "; ".join(record.get("activities") or []) or "activities: (none)",
        "relationships: " + "; ".join(record.get("relationships") or []) or "relationships: (none)",
        "notable_text: " + "; ".join(record.get("notable_text") or []) or "notable_text: (none)",
    ]
    return "\n".join(lines)


def flatten_fact_text(record: dict) -> str:
    chunks = [
        record.get("scene_description") or "",
        record.get("environment") or "",
        record.get("media_type") or "",
        " ".join(record.get("ui_types") or []),
    ]
    for item in record.get("entities") or []:
        chunks.extend(
            [
                item.get("name") or "",
                item.get("kind") or "",
                " ".join(item.get("states") or []),
                item.get("posture") or "",
                " ".join(item.get("attributes") or []),
                " ".join(item.get("colors") or []),
                item.get("observed_color_description") or "",
                item.get("visibility") or "",
                item.get("identifiability") or "",
            ]
        )
    for item in record.get("applications") or []:
        chunks.extend(
            [
                item.get("name") or "",
                item.get("category") or "",
                item.get("kind") or "",
                item.get("theme") or "",
                item.get("visible_content") or "",
            ]
        )
    chunks.extend(record.get("activities") or [])
    chunks.extend(record.get("relationships") or [])
    chunks.extend(record.get("notable_text") or [])
    return " ".join(str(part).lower() for part in chunks if part)


def missing_explicit_entities(query: str, record: dict) -> list[str]:
    blob = flatten_fact_text(record).replace("-", " ")
    query_text = f" {query.lower().replace('-', ' ')} "
    missing = []
    for name, aliases in EXPLICIT_ENTITY_ALIASES:
        if f" {name} " not in query_text and f" {name}s " not in query_text:
            continue
        if not any(alias in blob for alias in aliases):
            missing.append(name)
    return missing
