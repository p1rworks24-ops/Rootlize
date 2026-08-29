"""Identity-bound surface and same-entity contracts for DB facts search.

Bare named-entity queries require sufficient identity presence, not a
presence form the query did not name. Named surfaces stay bound to one
identity. Compound attributes must hold on the same entity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.image_facts.format import (
    flatten_fact_text,
    missing_explicit_entities,
    normalize_condition_label,
    visible_content_is_text_mention,
    GLUE_CONDITION_LABELS,
    HOST_CHROME_TOKENS,
)
from app.image_facts.query import is_search_wrapper_condition, meaning_query_target

WORKSPACE_HEADS = (
    "page",
    "workspace",
    "pane",
    "panel",
    "screen",
    "sidebar",
    "side panel",
    "sidepane",
    "side-panel",
)
CONTROL_ATTRS = {
    "button",
    "buttons",
    "quick action",
    "quick action button",
    "ui control",
    "control",
    "controls",
    "tag control",
    "tag controls",
    "nav",
    "nav item",
    "navigation",
    "menu item",
    "input",
    "input field",
    "text field",
    "dropdown",
    "dropdown control",
}
WORKSPACE_ATTRS = {
    "page",
    "page title",
    "workspace",
    "pane",
    "panel",
    "sidebar",
    "screen",
    "side panel",
    "sidepane",
}
TEXT_ATTR_HINTS = ("chip", "text", "label", "caption", "mention")
ICON_HINTS = (
    "icon",
    "taskbar icon",
    "launcher icon",
    "app icon",
    "shortcut",
    "desktop shortcut",
    "pinned icon",
)
LOCATION_TERMS = (
    "taskbar",
    "system tray",
    "start menu",
    "dock",
    "desktop",
)
FILENAME_HINTS = ("folder name", "file name", "filename", "folder label")
BRANDING_HINTS = ("splash", "branding")
RENDERED_UI_HINTS = (
    "home",
    "images",
    "gallery",
    "library",
    "editor",
    "browser",
    "settings",
    "search page",
    "tags page",
    "window",
    "sidebar",
    "thumbnail",
    "folder tree",
    "preview",
    "chat",
    "document",
)
APP_OPEN_HINTS = ("browser", "application", "window", "open to", "open in")
DISPLAYED_HINTS = ("displaying", "displayed", "showing", "open in", "open to", "page open")
NON_INTERFACE_TOKENS = (
    "desktop shortcut",
    "shortcut",
    "taskbar icon",
    "launcher icon",
    "start menu",
    "folder name",
    "file name",
    "filename",
    "ui control",
)
CONTROL_TOKENS = ("button", "buttons labeled", "button labeled", "menu item")
WEAK_EVIDENCE_TOKENS = NON_INTERFACE_TOKENS + CONTROL_TOKENS + (
    "notable_text",
    "folder list",
    "folder named",
    "tag chip",
    "#",
)
VISUAL_OBJECT_KIND = {"animal", "person", "character"}
VISUAL_OBJECT_TERMS = (
    "dog",
    "cat",
    "puppy",
    "kitten",
    "anime",
    "character",
    "person",
    "logo",
    "wallpaper",
)
UI_TYPE_TERMS = (
    "editor",
    "browser",
    "terminal",
    "explorer",
    "manager",
    "panel",
    "pane",
    "window",
    "desktop",
    "settings",
    "modal",
    "gallery",
    "powershell",
    "shell",
    "ide",
    "preview",
)
GENERIC_CONTENT_TERMS = ("web page", "webpage", "website", "notification")
GENERIC_CONTENT_LABELS = {"web", "web page", "webpage", "website", "web content"}
COLOR_TERMS = (
    "white",
    "black",
    "brown",
    "orange",
    "orange brown",
    "orange-brown",
    "tan",
    "gray",
    "grey",
    "red",
    "blue",
    "green",
    "yellow",
    "pink",
    "calico",
)
POSTURE_TERMS = ("sitting", "standing", "lying", "seated")
CHROME_FALSE_FRIENDS_RE = re.compile(r"\b(?:window|browser|ui) chrome\b")
WORKSPACE_LABEL_RE = re.compile(
    r"\b(?:panel|pane|sidebar|page|workspace)\b",
    re.IGNORECASE,
)
REASON_UNCONFIRMED_RE = re.compile(
    r"(?P<label>.+?)(?: is not confirmed| is not supported| are not confirmed| not confirmed)",
    re.IGNORECASE,
)
BOUND_SURFACE_PATTERNS = (
    (re.compile(r"^(?P<id>.+?) text mention$"), "text"),
    (re.compile(r"^(?P<id>.+?) mention$"), "text"),
    (re.compile(r"^(?P<id>.+?) (?:icon|icons|shortcut|shortcuts)$"), "icon"),
    (re.compile(r"^(?P<id>.+?) button$"), "control"),
    (re.compile(r"^(?P<id>.+?) folder$"), "filename"),
    (
        re.compile(r"^(?P<id>.+?) (?:panel|pane|sidebar|page|workspace)(?: open)?$"),
        "workspace",
    ),
)


@dataclass(frozen=True)
class BoundSurface:
    intent: str
    identity: str


def _norm(value: object) -> str:
    return normalize_condition_label(value)


def _identity_aliases(identity: str) -> tuple[str, ...]:
    name = _norm(identity)
    aliases = {name}
    if name.startswith("google "):
        aliases.add(name[len("google ") :])
    if name.endswith(" panel"):
        aliases.add(name[: -len(" panel")].strip())
    if name.endswith(" pane"):
        aliases.add(name[: -len(" pane")].strip())
    return tuple(item for item in aliases if item)


def _identity_in(text: object, identity: str) -> bool:
    blob = _norm(text)
    if not blob or not identity:
        return False
    aliases = _identity_aliases(identity)
    search_blob = blob
    if any(alias == "chrome" for alias in aliases):
        search_blob = CHROME_FALSE_FRIENDS_RE.sub(" ", blob)
    for alias in aliases:
        haystack = search_blob if alias == "chrome" else blob
        if re.search(rf"\b{re.escape(alias)}\b", haystack):
            return True
    return False


def _is_generic_content_label(label: str) -> bool:
    label_n = _norm(label)
    return label_n in GENERIC_CONTENT_LABELS or _has_whole_term(label_n, GENERIC_CONTENT_TERMS)


def _has_whole_term(text: str, terms: tuple[str, ...]) -> bool:
    text_n = _norm(text)
    tokens = set(text_n.split())
    for term in terms:
        term_n = _norm(term)
        if not term_n:
            continue
        if " " in term_n:
            if term_n in text_n:
                return True
        elif term_n in tokens:
            return True
    return False


def _blob(parts) -> str:
    return " ".join(str(part or "").lower() for part in parts if part)


def _label_in_text(label: str, *parts: object) -> bool:
    text = _norm(_blob(parts))
    label_n = _norm(label)
    if not label_n or not text:
        return False
    if label_n in text:
        return True
    compact_label = label_n.replace(" ", "")
    compact_text = text.replace(" ", "")
    return bool(compact_label) and compact_label in compact_text


def _strip_glue(text: str) -> str:
    tokens = [item for item in _norm(text).split() if item not in GLUE_CONDITION_LABELS]
    return " ".join(tokens)


def query_parts(query: str) -> list[str]:
    q = _norm(query)
    return [part.strip() for part in re.split(r"\b(?:with|showing|in|beside|and)\b", q) if part.strip()]


def parse_bound_surface_query(query: str) -> BoundSurface | None:
    q = _norm(query)
    if not q or _is_generic_content_label(q):
        return None
    if any(token in f" {q} " for token in (" with ", " showing ", " in ", " beside ", " and ")):
        return None
    if q.endswith(" this folder") or q.endswith(" current folder"):
        return None
    for pattern, intent in BOUND_SURFACE_PATTERNS:
        match = pattern.match(q)
        if match:
            identity = _strip_glue(match.group("id"))
            if identity and identity not in {"empty image", "empty"} and not _is_generic_content_label(
                f"{identity} {intent}" if intent == "workspace" else identity
            ):
                if intent == "workspace" and identity in GENERIC_CONTENT_LABELS:
                    continue
                return BoundSurface(intent=intent, identity=identity)
    if q.endswith(" open"):
        identity = _strip_glue(q[: -len(" open")])
        if identity:
            return BoundSurface(intent="open", identity=identity)
    return None


def query_surface_intent(query: str) -> str | None:
    if _is_generic_content_label(query):
        return None
    bound = parse_bound_surface_query(query)
    if bound:
        return bound.intent
    q = _norm(query)
    if WORKSPACE_LABEL_RE.search(q):
        return "workspace"
    if "text mention" in q or q.endswith(" mention"):
        return "text"
    if "button" in q.split() or q.endswith(" button"):
        return "control"
    if "icon" in q.split() or "icons" in q.split() or "shortcut" in q or "shortcuts" in q:
        return "icon"
    if "folder" in q and "empty" not in q and "library" not in q:
        return "filename"
    return None


def _attrs(entity: dict) -> list[str]:
    return [_norm(item) for item in (entity.get("attributes") or [])]


def _attr_set(entity: dict) -> set[str]:
    values = set(_attrs(entity))
    joined = " ".join(_attrs(entity))
    values.add(joined)
    return values


def _entity_is_text_surface(entity: dict) -> bool:
    joined = f"{_norm(entity.get('name'))} {' '.join(_attrs(entity))}"
    return any(hint in joined for hint in TEXT_ATTR_HINTS + ("tag chip", "tag label"))


def _entity_has_control_attrs(entity: dict) -> bool:
    values = _attr_set(entity)
    name = _norm(entity.get("name"))
    if name.endswith(" button") or name.endswith(" icon"):
        return True
    return bool(values & CONTROL_ATTRS) or any(
        "button" in item or "quick action" in item or "tag control" in item for item in values
    )


def _entity_has_workspace_attrs(entity: dict) -> bool:
    values = _attr_set(entity)
    name = _norm(entity.get("name"))
    if any(name.endswith(f" {head}") for head in ("page", "pane", "panel", "workspace", "sidebar", "screen")):
        return True
    return bool(values & WORKSPACE_ATTRS) or any(
        any(head in item for head in WORKSPACE_HEADS) for item in values
    )


def _non_interface_entity(entity: dict) -> bool:
    name = _norm(entity.get("name"))
    attrs = [_norm(item) for item in (entity.get("attributes") or [])]
    dedicated = {
        "desktop shortcut",
        "shortcut",
        "taskbar icon",
        "launcher icon",
        "folder name",
        "file name",
        "filename",
        "ui control",
        "button",
    }
    if any(item in dedicated for item in attrs):
        return True
    name_tokens = name.split()
    if name_tokens and name_tokens[-1] in {"shortcut", "icon", "button"} and "screenshot" not in name:
        return True
    return False


def _is_visual_object_condition(label: str, record: dict) -> bool:
    label_n = _norm(label)
    if _has_whole_term(label_n, VISUAL_OBJECT_TERMS) and not _has_whole_term(
        label_n, ("editor", "manager", "browser", "panel")
    ):
        return True
    for entity in record.get("entities") or []:
        if entity.get("kind") not in VISUAL_OBJECT_KIND:
            continue
        if _label_in_text(label_n, entity.get("name"), *(entity.get("attributes") or [])):
            return True
    return False


def _is_application_or_ui_condition(label: str) -> bool:
    label_n = _norm(label)
    if _has_whole_term(label_n, GENERIC_CONTENT_TERMS):
        return False
    return _has_whole_term(label_n, UI_TYPE_TERMS)


def _panel_core(label: str) -> str:
    core = _norm(label)
    for token in ("open", "panel", "pane", "sidebar"):
        core = core.replace(token, " ")
    tokens = [item for item in _norm(core).split() if item not in GLUE_CONDITION_LABELS]
    return " ".join(tokens)


def _workspace_identity(label: str) -> str:
    core = _panel_core(label)
    core = re.sub(r"\b(?:page|workspace|screen|sidebar)\b", " ", core)
    return _norm(core)


def _blob_without_notable_text(record: dict) -> str:
    chunks = [
        record.get("scene_description") or "",
        record.get("environment") or "",
        " ".join(record.get("ui_types") or []),
        " ".join(record.get("activities") or []),
        " ".join(record.get("relationships") or []),
    ]
    for app in record.get("applications") or []:
        chunks.extend([app.get("name") or "", app.get("visible_content") or ""])
    return _norm(" ".join(str(part) for part in chunks if part))


def _has_workspace_phrase(record: dict, identity: str) -> bool:
    blob = _blob_without_notable_text(record)
    for alias in _identity_aliases(identity):
        for head in WORKSPACE_HEADS:
            if f"{alias} {head}" in blob:
                return True
            if f"{head} {alias}" in blob and head in {"page", "workspace"}:
                return True
    return False


def _current_page_identities(record: dict) -> set[str]:
    text = " ".join(
        [
            str(record.get("scene_description") or ""),
            " ".join(str(item.get("visible_content") or "") for item in (record.get("applications") or [])),
            " ".join(str(item) for item in (record.get("relationships") or [])),
        ]
    )
    found = set()
    for match in re.finditer(
        r"\b([a-z0-9][a-z0-9 +#/-]{0,32}?) (?:page|screen|workspace)\b",
        _norm(text),
    ):
        name = _norm(match.group(1))
        name = re.sub(r"\b(?:its|the|a|an|application|app|library|screenshot)\b", " ", name)
        name = _norm(name)
        if name and name not in {"graphic splash", "branding"}:
            found.add(name)
    for entity in record.get("entities") or []:
        attrs = [_norm(item) for item in (entity.get("attributes") or [])]
        if "page title" in attrs:
            found.add(_norm(entity.get("name")))
    return {item for item in found if item}


def _entity_is_identity_workspace(entity: dict, identity: str) -> bool:
    name = entity.get("name") or ""
    if not _identity_in(name, identity) and not any(_identity_in(item, identity) for item in _attrs(entity)):
        return False
    if _entity_has_control_attrs(entity) and not _entity_has_workspace_attrs(entity):
        return False
    if _entity_has_control_attrs(entity) and _entity_has_workspace_attrs(entity):
        return False
    return _entity_has_workspace_attrs(entity)


def _has_identity_workspace(record: dict, identity: str) -> bool:
    identity = _workspace_identity(identity)
    if not identity:
        return False
    if _has_workspace_phrase(record, identity):
        return True
    if any(_entity_is_identity_workspace(entity, identity) for entity in (record.get("entities") or [])):
        pages = _current_page_identities(record)
        if pages and not any(_identity_in(page, identity) for page in pages):
            return False
        return True
    return False


def _has_text_mention(record: dict, identity: str) -> bool:
    for text in record.get("notable_text") or []:
        if _identity_in(text, identity):
            return True
    for entity in record.get("entities") or []:
        name = entity.get("name") or ""
        attrs = _attr_set(entity)
        if not _identity_in(name, identity):
            continue
        if any(hint in " ".join(attrs) or hint in _norm(name) for hint in TEXT_ATTR_HINTS):
            if not any("window" in item or "browser" in item or "toolbar" in item for item in attrs):
                return True
    return False


def _has_icon_entity(record: dict, identity: str) -> bool:
    for entity in record.get("entities") or []:
        name = _norm(entity.get("name"))
        attrs = _attr_set(entity)
        joined = f"{name} {' '.join(attrs)}"
        if not _identity_in(joined, identity):
            continue
        if any("window" in item or "toolbar" in item or "tab strip" in item for item in attrs):
            continue
        if any(hint in joined for hint in ICON_HINTS) or name.endswith(" icon"):
            return True
    return False


def _has_icon_surface(record: dict, identity: str) -> bool:
    return _has_icon_entity(record, identity)


def _has_control_surface(record: dict, identity: str) -> bool:
    for entity in record.get("entities") or []:
        name = entity.get("name") or ""
        if not _identity_in(name, identity) and not any(_identity_in(item, identity) for item in _attrs(entity)):
            continue
        if _entity_has_control_attrs(entity) or _norm(name).endswith(" button"):
            return True
    blob = _blob_without_notable_text(record)
    return any(f"{alias} button" in blob for alias in _identity_aliases(identity))


def _has_filename_surface(record: dict, identity: str) -> bool:
    for entity in record.get("entities") or []:
        joined = f"{entity.get('name') or ''} {' '.join(_attrs(entity))}"
        if _identity_in(joined, identity) and any(hint in _norm(joined) for hint in FILENAME_HINTS):
            return True
    blob = flatten_fact_text(record)
    return any(
        _identity_in(blob, identity) and hint in blob
        for hint in ("folder name", "folder named", "file name")
    )


def _visible_has_app_ui(visible: str) -> bool:
    vis = _norm(visible)
    if not vis:
        return False
    if any(hint in vis for hint in BRANDING_HINTS) and not any(hint in vis for hint in RENDERED_UI_HINTS):
        return False
    return any(hint in vis for hint in RENDERED_UI_HINTS) or "window" in vis


def _record_is_branding_only(record: dict) -> bool:
    env = _norm(record.get("environment"))
    scene = _norm(record.get("scene_description"))
    ui = _norm(" ".join(record.get("ui_types") or []))
    if any(hint in env or hint in scene for hint in BRANDING_HINTS):
        if not any(hint in ui for hint in ("window", "gallery", "editor", "browser", "manager", "settings")):
            return True
    for app in record.get("applications") or []:
        if app.get("role") != "primary":
            continue
        vis = _norm(app.get("visible_content"))
        if any(hint in vis for hint in BRANDING_HINTS) and not _visible_has_app_ui(vis):
            return True
    return False


def _scene_has_open_host(record: dict, label: str) -> bool:
    scene = _norm(record.get("scene_description"))
    if not _identity_in(scene, label):
        return False
    return any(hint in scene for hint in APP_OPEN_HINTS)


def _has_nested_depicted_ui(record: dict, label: str) -> bool:
    for entity in record.get("entities") or []:
        if entity.get("visibility") != "nested":
            continue
        if _non_interface_entity(entity):
            continue
        if _label_in_text(label, entity.get("name"), *(entity.get("attributes") or [])):
            return True
    return False


def _has_rendered_interface(record: dict, label: str) -> bool:
    label = _strip_glue(label) or _norm(label)
    if _is_visual_object_condition(label, record):
        return False
    if _record_is_branding_only(record) and not _has_nested_depicted_ui(record, label):
        return False
    for app in record.get("applications") or []:
        vis = app.get("visible_content") or ""
        if visible_content_is_text_mention(vis):
            continue
        if any(hint in _norm(vis) for hint in BRANDING_HINTS) and not _visible_has_app_ui(vis):
            continue
        name_hit = _label_in_text(label, app.get("name")) or _identity_in(app.get("name"), label)
        vis_has_ui = _visible_has_app_ui(vis) or any(token in _norm(vis) for token in HOST_CHROME_TOKENS)
        if name_hit and vis_has_ui:
            return True
        if _identity_in(vis, label) and vis_has_ui:
            return True
        if _label_in_text(label, app.get("category")) and vis_has_ui:
            return True
    for ui_type in record.get("ui_types") or []:
        if _label_in_text(label, ui_type) or _identity_in(ui_type, label):
            return True
    for entity in record.get("entities") or []:
        if _non_interface_entity(entity) or _entity_is_text_surface(entity):
            continue
        if _label_in_text(label, entity.get("name"), *(entity.get("attributes") or [])) or _identity_in(
            entity.get("name"), label
        ):
            return True
    for rel in record.get("relationships") or []:
        rel_n = str(rel).lower()
        if any(token in rel_n for token in NON_INTERFACE_TOKENS + CONTROL_TOKENS):
            continue
        if (_label_in_text(label, rel) or _identity_in(rel, label)) and any(
            token in rel_n for token in ("open", "displayed", "displaying", "window", "editor", "browser")
        ):
            return True
    if _scene_has_open_host(record, label):
        return True
    return False


def _has_identity_branding(record: dict, label: str) -> bool:
    for app in record.get("applications") or []:
        vis = _norm(app.get("visible_content"))
        if not any(hint in vis for hint in BRANDING_HINTS):
            continue
        if (
            _identity_in(app.get("name"), label)
            or _label_in_text(label, app.get("name"), app.get("category"))
        ):
            return True
    return False


def _has_sufficient_identity_presence(record: dict, label: str) -> bool:
    """Bare entity: identity is present as UI, icon, shortcut, nested shot, or branding."""
    if _has_rendered_interface(record, label):
        return True
    if _has_nested_depicted_ui(record, label):
        return True
    if _has_icon_surface(record, label):
        return True
    if _has_identity_branding(record, label):
        return True
    return False


def _is_weak_identity_mention(record: dict, label: str) -> bool:
    if _has_sufficient_identity_presence(record, label):
        return False
    if _has_filename_surface(record, label) or _has_text_mention(record, label):
        return True
    blob = flatten_fact_text(record)
    if CHROME_FALSE_FRIENDS_RE.search(blob) and _norm(label) in {"chrome", "google chrome"}:
        return True
    return False


def _looks_like_application_open(core: str, record: dict) -> bool:
    for app in record.get("applications") or []:
        if _identity_in(app.get("name"), core) or _identity_in(core, app.get("name") or ""):
            return True
    for name in record.get("_dropped_host_names") or []:
        if _identity_in(name, core) or _identity_in(core, name):
            return True
    return _scene_has_open_host(record, core)


def _has_named_displayed_content(record: dict, label: str) -> bool:
    if _record_is_branding_only(record):
        return False
    for app in record.get("applications") or []:
        vis = app.get("visible_content") or ""
        if visible_content_is_text_mention(vis):
            continue
        if _identity_in(vis, label):
            return True
    for rel in record.get("relationships") or []:
        if _identity_in(rel, label) and any(hint in _norm(rel) for hint in DISPLAYED_HINTS):
            return True
    for entity in record.get("entities") or []:
        if _entity_is_text_surface(entity) or _non_interface_entity(entity):
            continue
        if _identity_in(entity.get("name"), label):
            return True
    return False


def _has_desktop_environment(record: dict) -> bool:
    blob = _norm(f"{record.get('environment') or ''} {' '.join(record.get('ui_types') or [])}")
    return "windows desktop" in blob or "desktop environment" in blob


def _matches_dropped_host(record: dict, label: str) -> bool:
    for name in record.get("_dropped_host_names") or []:
        if _label_in_text(label, name) or _label_in_text(name, label):
            return True
    return False


def _evidence_is_weak(evidence: str) -> bool:
    blob = (evidence or "").lower()
    return any(token in blob for token in WEAK_EVIDENCE_TOKENS)


def evaluate_bound_surface(bound: BoundSurface, record: dict) -> bool:
    identity = bound.identity
    if bound.intent == "text":
        return _has_text_mention(record, identity)
    if bound.intent == "icon":
        return _has_icon_surface(record, identity)
    if bound.intent == "control":
        return _has_control_surface(record, identity)
    if bound.intent == "filename":
        return _has_filename_surface(record, identity)
    if bound.intent in {"workspace", "open"}:
        if bound.intent == "open" and _looks_like_application_open(identity, record):
            return _has_rendered_interface(record, identity)
        return _has_identity_workspace(record, identity)
    return False


def _workspace_bounds_in_query(query: str) -> list[BoundSurface]:
    bounds = []
    seen = set()
    for part in query_parts(query) + [_norm(query)]:
        bound = parse_bound_surface_query(part)
        if not bound or bound.intent not in {"workspace", "open"}:
            continue
        key = (bound.intent, bound.identity)
        if key in seen:
            continue
        seen.add(key)
        bounds.append(bound)
    return bounds


def _matching_workspace_bound(label: str, query: str) -> BoundSurface | None:
    label_n = _norm(label)
    if _is_generic_content_label(label_n):
        return None
    for bound in _workspace_bounds_in_query(query):
        identity = bound.identity
        if label_n in {identity, _norm(f"{identity} {bound.intent}"), f"{identity} open", f"{identity} panel"}:
            return bound
        if label_n.startswith(f"{identity} ") and WORKSPACE_LABEL_RE.search(label_n):
            return bound
    if WORKSPACE_LABEL_RE.search(label_n):
        return BoundSurface(intent="workspace", identity=_workspace_identity(label_n) or label_n)
    return None


def _set_confirmed(row: dict, confirmed: bool, override: str) -> None:
    row["confirmed"] = confirmed
    row["contract_override"] = override
    if confirmed and not (row.get("evidence") or "").strip():
        row["evidence"] = override.replace("_", " ")[:140]


def condition_mentioned_in_query(label: str, query: str) -> bool:
    query_n = _norm(query)
    return bool(label) and label in query_n


def filter_query_conditions(item: dict, *, query: str) -> dict:
    original = [row for row in (item.get("independent_conditions") or []) if isinstance(row, dict)]
    kept = []
    extras = []
    for row in original:
        label = _norm(row.get("condition"))
        if (
            not label
            or label in GLUE_CONDITION_LABELS
            or is_search_wrapper_condition(label, query)
            or not condition_mentioned_in_query(label, query)
        ):
            extras.append(str(row.get("condition") or ""))
            continue
        kept.append(row)
    item["independent_conditions"] = kept
    item["ignored_extra_conditions"] = extras
    return item


def relevant_from_conditions(
    conditions: list,
    *,
    extra_unconfirmed: list[str] | None = None,
) -> tuple[bool, list[str]]:
    rows = [row for row in conditions if isinstance(row, dict)]
    unconfirmed = [
        str(row.get("condition") or "")
        for row in rows
        if row.get("confirmed") is not True
    ]
    for name in extra_unconfirmed or []:
        if name not in unconfirmed:
            unconfirmed.append(name)
    if not rows:
        return False, unconfirmed
    return (len(unconfirmed) == 0, unconfirmed)


def enforce_condition_consistency(item: dict, *, query: str, record: dict) -> dict:
    conditions = item.get("independent_conditions") or []
    relevant, unconfirmed = relevant_from_conditions(
        conditions,
        extra_unconfirmed=missing_explicit_entities(query, record),
    )
    item["unconfirmed_conditions"] = unconfirmed
    item["relevant"] = relevant
    item["relevant_source"] = "conditions"
    return item


def ensure_bound_conditions(item: dict, *, query: str) -> dict:
    rows = [row for row in (item.get("independent_conditions") or []) if isinstance(row, dict)]
    existing = {_norm(row.get("condition")) for row in rows}
    for bound in _workspace_bounds_in_query(query):
        covered = any(
            label == bound.identity
            or label.startswith(f"{bound.identity} ")
            or bound.identity in label.split()
            for label in existing
        )
        if covered:
            continue
        q = _norm(query)
        if "pane" in q:
            label = f"{bound.identity} pane"
        elif "panel" in q:
            label = f"{bound.identity} panel"
        elif bound.intent == "open":
            label = f"{bound.identity} open"
        else:
            label = bound.identity
        rows.append(
            {
                "condition": label,
                "confirmed": False,
                "evidence": "",
                "missing_from_model": True,
            }
        )
        existing.add(_norm(label))
    item["independent_conditions"] = rows
    return item


def apply_surface_contract(item: dict, *, query: str, record: dict) -> dict:
    intent = query_surface_intent(query)
    bound = parse_bound_surface_query(query)
    rows = [row for row in (item.get("independent_conditions") or []) if isinstance(row, dict)]
    if bound:
        ok = evaluate_bound_surface(bound, record)
        override = f"bound_{bound.intent}_surface"
        for row in rows:
            _set_confirmed(row, ok, override)
        item["surface_intent"] = bound.intent
        item["independent_conditions"] = rows
        return item

    part_bounds = []
    seen = set()
    for part in query_parts(query):
        part_bound = parse_bound_surface_query(part)
        if not part_bound:
            continue
        key = (part_bound.intent, part_bound.identity)
        if key in seen:
            continue
        seen.add(key)
        part_bounds.append(part_bound)
    for row in rows:
        label = _norm(row.get("condition"))
        matching = next(
            (
                part_bound
                for part_bound in part_bounds
                if label
                in {
                    _norm(f"{part_bound.identity} {part_bound.intent}"),
                    part_bound.identity if part_bound.intent == "open" else "",
                }
                or (
                    part_bound.intent == "icon"
                    and ("icon" in label.split() or "shortcut" in label)
                    and _identity_in(label, part_bound.identity)
                )
            ),
            None,
        )
        if matching:
            ok = evaluate_bound_surface(matching, record)
            _set_confirmed(row, ok, f"bound_{matching.intent}_surface")

    for row in rows:
        label = _norm(row.get("condition"))
        if not label or _is_visual_object_condition(label, record):
            continue
        workspace_bound = _matching_workspace_bound(label, query)
        if workspace_bound and label != "open":
            if workspace_bound.intent == "open" and _looks_like_application_open(workspace_bound.identity, record):
                ok = _has_rendered_interface(record, workspace_bound.identity)
                _set_confirmed(row, ok, "application_open" if ok else "application_not_open")
            else:
                ok = _has_identity_workspace(record, workspace_bound.identity)
                _set_confirmed(row, ok, "identity_workspace" if ok else "not_identity_workspace")
            continue
        if label.endswith(" open"):
            core = _panel_core(label) or label[: -len(" open")]
            if _looks_like_application_open(core, record):
                ok = _has_rendered_interface(record, core)
                _set_confirmed(row, ok, "application_open" if ok else "application_not_open")
            else:
                ok = _has_identity_workspace(record, core)
                _set_confirmed(row, ok, "identity_workspace" if ok else "not_identity_workspace")
            continue
        if label == "open":
            continue
        if "desktop" in label.split():
            if row.get("confirmed") is True and not _has_desktop_environment(record):
                _set_confirmed(row, False, "incidental_or_nested_desktop")
            continue
        if row.get("confirmed") is True and _matches_dropped_host(record, label):
            if _has_sufficient_identity_presence(record, label) or _scene_has_open_host(record, label):
                row["contract_override"] = "kept_host_identity"
                continue
            _set_confirmed(row, False, "dropped_host_identity")
            continue
        if _is_application_or_ui_condition(label) or _has_sufficient_identity_presence(record, label) or _is_weak_identity_mention(record, label) or _only_non_interface_mention(record, label):
            if _has_sufficient_identity_presence(record, label):
                if row.get("confirmed") is not True:
                    _set_confirmed(row, True, "identity_presence")
                continue
            if row.get("confirmed") is True and (
                _is_weak_identity_mention(record, label)
                or _evidence_is_weak(row.get("evidence") or "")
            ):
                _set_confirmed(row, False, "weak_identity_mention")
                continue
        if row.get("confirmed") is not True and _has_named_displayed_content(record, label):
            _set_confirmed(row, True, "stored_visible_content")
            row["evidence"] = f"stored visible_content/relationship names {label}"[:140]

    for row in rows:
        label = _norm(row.get("condition"))
        if label != "open":
            continue
        others_ok = any(
            other.get("confirmed") is True
            and other is not row
            and (
                _is_application_or_ui_condition(_norm(other.get("condition")))
                or _has_rendered_interface(record, _norm(other.get("condition")))
                or _has_identity_workspace(record, _norm(other.get("condition")))
            )
            for other in rows
        )
        if others_ok:
            _set_confirmed(row, True, row.get("contract_override") or "open_implied_by_interface")
        elif row.get("confirmed") is True:
            named_failed = any(
                other is not row
                and other.get("confirmed") is not True
                and (
                    _matching_workspace_bound(_norm(other.get("condition")), query)
                    or str(other.get("condition") or "").lower().endswith(" open")
                )
                for other in rows
            )
            if named_failed:
                _set_confirmed(row, False, "open_without_named_workspace")

    item["surface_intent"] = intent or ""
    item["independent_conditions"] = rows
    return item


def _only_non_interface_mention(record: dict, label: str) -> bool:
    if _has_sufficient_identity_presence(record, label):
        return False
    return any(
        _label_in_text(label, entity.get("name")) and _non_interface_entity(entity)
        for entity in (record.get("entities") or [])
    )


def _dominant_color_confirms(entity: dict, color: str) -> bool:
    color_n = _norm(color).replace(" ", "-")
    colors = [_norm(item).replace(" ", "-") for item in (entity.get("colors") or [])]
    observed = _norm(entity.get("observed_color_description"))
    observed_h = observed.replace(" ", "-")
    if f"mostly {color_n}" in observed_h or f"mostly {color.replace('-', ' ')}" in observed:
        return True
    if colors and colors[0] == color_n:
        return True
    if color_n in colors and len(colors) == 1:
        return True
    return False


def _color_from_label(label: str) -> str | None:
    label_n = _norm(label)
    for color in sorted(COLOR_TERMS, key=len, reverse=True):
        color_n = _norm(color)
        if color_n == label_n or label_n.startswith(color_n + " ") or f" {color_n} " in f" {label_n} ":
            if color_n in {"dark", "light"}:
                continue
            return color_n
    return None


def apply_color_contract(item: dict, *, query: str, record: dict) -> dict:
    for row in item.get("independent_conditions") or []:
        label = _norm(row.get("condition"))
        color = _color_from_label(label)
        if not color:
            continue
        remainder = _norm(label.replace(color, ""))
        matched = False
        for entity in record.get("entities") or []:
            if entity.get("kind") not in VISUAL_OBJECT_KIND:
                continue
            if remainder and not _label_in_text(remainder, entity.get("name")):
                continue
            if _dominant_color_confirms(entity, color):
                matched = True
                if row.get("confirmed") is not True:
                    _set_confirmed(row, True, "dominant_color")
                    row["evidence"] = (
                        f"entities: name={entity.get('name')}; "
                        f"canonical_colors={'/'.join(entity.get('colors') or [])}; "
                        f"observed_color={entity.get('observed_color_description')}"
                    )[:140]
                break
        if remainder and row.get("confirmed") is True and not matched:
            _set_confirmed(row, False, "color_without_target")
    return item


def _location_from_query(query: str) -> str | None:
    query_n = _norm(query)
    for location in sorted(LOCATION_TERMS, key=len, reverse=True):
        if location in query_n:
            return location
    return None


def _has_identity_icon_at(record: dict, identity: str, location: str) -> bool:
    for entity in record.get("entities") or []:
        name = _norm(entity.get("name"))
        attrs = _attr_set(entity)
        joined = f"{name} {' '.join(attrs)}"
        if not _identity_in(joined, identity):
            continue
        if not (any(hint in joined for hint in ICON_HINTS) or name.endswith(" icon") or name.endswith(" shortcut")):
            continue
        if location in joined:
            return True
    return False


def apply_icon_location_contract(item: dict, *, query: str, record: dict) -> dict:
    """Require named icon/shortcut and location to hold on the same entity."""
    query_n = _norm(query)
    if "icon" not in query_n.split() and "icons" not in query_n.split() and "shortcut" not in query_n:
        return item
    location = _location_from_query(query)
    if not location:
        return item
    identity = None
    for part in query_parts(query) + [query_n]:
        bound = parse_bound_surface_query(part)
        if bound and bound.intent == "icon":
            identity = bound.identity
            break
    if not identity:
        return item
    ok = _has_identity_icon_at(record, identity, location)
    override = "icon_location" if ok else "icon_not_in_location"
    for row in item.get("independent_conditions") or []:
        label = _norm(row.get("condition"))
        if (
            _identity_in(label, identity)
            or "icon" in label.split()
            or "shortcut" in label
            or location in label
        ):
            _set_confirmed(row, ok, override)
    return item


def apply_same_entity_contract(item: dict, *, query: str, record: dict) -> dict:
    """Require color and posture named in the query to hold on the same entity."""
    query_n = _norm(query)
    object_names = [term for term in VISUAL_OBJECT_TERMS if _has_whole_term(query_n, (term,))]
    colors = [color for color in COLOR_TERMS if _has_whole_term(query_n, (color,)) and color not in {"calico"}]
    postures = [term for term in POSTURE_TERMS if _has_whole_term(query_n, (term,))]
    if not object_names or (not colors and not postures):
        return item
    matched = False
    for entity in record.get("entities") or []:
        if entity.get("kind") not in VISUAL_OBJECT_KIND:
            continue
        name = entity.get("name") or ""
        if not any(_label_in_text(term, name, *(entity.get("attributes") or [])) for term in object_names):
            continue
        color_ok = True
        posture_ok = True
        if colors:
            color_ok = any(_dominant_color_confirms(entity, color) for color in colors)
        if postures:
            stored = _norm(entity.get("posture"))
            attrs = " ".join(_attrs(entity))
            posture_ok = any(
                term in {stored, "seated" if stored == "sitting" else stored} or term in attrs
                for term in postures
            )
        if color_ok and posture_ok:
            matched = True
            break
    if matched:
        return item
    for row in item.get("independent_conditions") or []:
        label = _norm(row.get("condition"))
        if any(term in label for term in object_names + colors + postures if term not in {"calico"}):
            if row.get("confirmed") is True:
                _set_confirmed(row, False, "not_same_entity")
    return item


def _unconfirmed_labels_from_reason(reason: str, *, query: str) -> list[str]:
    labels = []
    for match in REASON_UNCONFIRMED_RE.finditer(reason or ""):
        raw = match.group("label")
        raw = re.split(r"[.;:] ", raw)[-1]
        raw = re.sub(r"^(?:but |and |the query also includes )", "", raw.strip(), flags=re.I)
        label = _norm(raw)
        if label and condition_mentioned_in_query(label, query) and label not in GLUE_CONDITION_LABELS:
            labels.append(label)
    return labels


def _missing_query_colors(query: str, labels) -> list[str]:
    query_n = _norm(query)
    covered = _norm(" ".join(labels))
    missing = []
    for color in sorted(COLOR_TERMS, key=len, reverse=True):
        color_n = _norm(color)
        if color_n in {"dark", "light", "calico"}:
            continue
        if color_n in query_n and color_n not in covered:
            missing.append(color_n)
            break
    return missing


def align_condition_labels(items: list[dict], *, query: str) -> list[dict]:
    aligned_items = []
    for item in items:
        by_label = {}
        for row in item.get("independent_conditions") or []:
            label = _norm(row.get("condition"))
            if label and label not in by_label and condition_mentioned_in_query(label, query):
                by_label[label] = row
        for extracted in _unconfirmed_labels_from_reason(item.get("reason") or "", query=query):
            if extracted not in by_label:
                by_label[extracted] = {
                    "condition": extracted,
                    "confirmed": False,
                    "evidence": "",
                    "missing_from_model": True,
                }
        for color in _missing_query_colors(query, by_label.keys()):
            if color not in by_label:
                by_label[color] = {
                    "condition": color,
                    "confirmed": False,
                    "evidence": "",
                    "missing_from_model": True,
                }
        item = dict(item)
        item["independent_conditions"] = list(by_label.values())
        aligned_items.append(item)
    return aligned_items


def reconcile_reason(item: dict, *, query: str) -> dict:
    reason = item.get("reason") or ""
    denied = set(_unconfirmed_labels_from_reason(reason, query=query))
    if not denied:
        return item
    for row in item.get("independent_conditions") or []:
        label = _norm(row.get("condition"))
        if label in denied and row.get("confirmed") is True and not row.get("contract_override"):
            _set_confirmed(row, False, "reason_contradiction")
    return item


def apply_facts_contracts(item: dict, *, query: str, record: dict) -> dict:
    """Run the full product contract stack on one LLM condition payload."""
    query = meaning_query_target(query) or query
    filtered = filter_query_conditions(dict(item), query=query)
    aligned = align_condition_labels([filtered], query=query)[0]
    ensure_bound_conditions(aligned, query=query)
    apply_surface_contract(aligned, query=query, record=record)
    apply_color_contract(aligned, query=query, record=record)
    apply_icon_location_contract(aligned, query=query, record=record)
    apply_same_entity_contract(aligned, query=query, record=record)
    reconcile_reason(aligned, query=query)
    return enforce_condition_consistency(aligned, query=query, record=record)
