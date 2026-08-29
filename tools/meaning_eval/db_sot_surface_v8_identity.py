"""Identity-bound surface contract on top of frozen v8 facts.

Keeps image-facts-v3 and the stored facts. Changes only search meaning and
the code-side condition contract: named surfaces are one bound condition,
workspace queries need that identity's page/pane/panel, and branding/category
is not a rendered application interface.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
from pathlib import Path

from tools.meaning_eval.describe_judge import add_usage, empty_usage
from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_surface_v8 as v8

_V8_QUERY_SURFACE_INTENT = v8.query_surface_intent


SEARCH_PROMPT_VERSION = "db-sot-search-v1.6-identity-surface"
SCHEMA_VERSION = v8.SCHEMA_VERSION
PROMPT_VERSION = v8.PROMPT_VERSION

_CATEGORY_PARAGRAPH = (
    "A recorded product whose category is screenshot manager / image management\n"
    "application confirms the condition \"screenshot manager\". The product's\n"
    "proper name (Capixe) does not block that confirmation.\n"
)
_CATEGORY_REPLACEMENT = (
    "A product category, logo, splash, or branding screen does not by itself "
    "confirm that an application interface is visibly open. Confirm a bare "
    "application or UI-type query only from a rendered interface (a window, "
    "page, workspace, or a nested screenshot of that UI). Category names are "
    "not rendered UI. Nested depicted UI still counts.\n"
)

SEARCH_PROMPT = (
    poc.SEARCH_PROMPT.replace(_CATEGORY_PARAGRAPH, _CATEGORY_REPLACEMENT)
    + v8.SEARCH_PROMPT[len(poc.SEARCH_PROMPT) :]
    + r"""

Identity-bound surfaces (do not use bag-of-words):
- A named surface is one condition. Do not split it into independent words.
  "Chrome icon" -> [Chrome icon]. "Tags button" -> [Tags button].
  "Chrome text mention" -> [Chrome text mention].
  "Microsoft VS Code folder" -> [Microsoft VS Code folder].
  "Tags panel open" -> [Tags panel open]. "Ask AI open" -> [Ask AI open].
  "Preview panel" -> [Preview panel].
- "X icon" is an icon whose identity is X. An open X window plus some other
  icon is not an X icon.
- "X button" is a control whose identity is X, not an X workspace.
- "X text mention" is X as actual visible text (notable_text, a tag chip, a
  text label). An open X application plus unrelated text is not a text mention.
- "X folder" is a folder whose identity is X, not an open X application.

Workspace / open-panel:
- "X panel", "X open", "Preview panel", "Ask AI open" mean a workspace whose
  identity is X is actually displayed. page, workspace, pane, panel, and
  screen are the same workspace family for that purpose.
- An X button, quick action, nav item, text mention, statistics widget, or
  an X input on a different page is not an X workspace.
- Do not confirm from co-occurrence of X with an unrelated panel/open/page.

Branding is not a rendered application:
- Splash, branding, logo, or category-only evidence does not confirm that
  the application UI is visibly open.

If a stored visible_content or relationship already names a displayed
entity, use that fact. Do not ignore it.
"""
)

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
CHROME_FALSE_FRIENDS_RE = re.compile(r"\b(?:window|browser|ui) chrome\b")
GENERIC_CONTENT_LABELS = {"web", "web page", "webpage", "website", "web content"}
WORKSPACE_LABEL_RE = re.compile(
    r"\b(?:panel|pane|sidebar|page|workspace)\b",
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


def configure() -> None:
    v8.configure()
    poc.SEARCH_PROMPT_VERSION = SEARCH_PROMPT_VERSION
    poc.SEARCH_PROMPT = SEARCH_PROMPT
    poc.search_query = _search_query
    v8.SEARCH_PROMPT_VERSION = SEARCH_PROMPT_VERSION
    v8.SEARCH_PROMPT = SEARCH_PROMPT
    v8.apply_surface_contract = apply_surface_contract
    v8.query_surface_intent = query_surface_intent
    v8._search_batch = _search_batch
    v8._search_query = _search_query
    v8._has_rendered_interface = _has_rendered_interface
    v8._has_open_panel = _has_identity_workspace_from_label


def copy_frozen_facts(source: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "facts.json"
    shutil.copyfile(source, dest)


def _norm(value: object) -> str:
    return poc.normalize_condition_label(value)


def _identity_aliases(identity: str) -> tuple[str, ...]:
    name = _norm(identity)
    aliases = {name}
    if name.startswith("google "):
        aliases.add(name[len("google ") :])
    if name == "chrome":
        aliases.add("google chrome")
    if name in {"vs code", "visual studio code", "microsoft vs code"}:
        aliases.update({"vs code", "visual studio code", "microsoft vs code"})
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
    if "chrome" in aliases:
        search_blob = CHROME_FALSE_FRIENDS_RE.sub(" ", blob)
    for alias in aliases:
        haystack = search_blob if alias == "chrome" else blob
        if re.search(rf"\b{re.escape(alias)}\b", haystack):
            return True
    return False


def _is_generic_content_label(label: str) -> bool:
    label_n = _norm(label)
    return label_n in GENERIC_CONTENT_LABELS or v8._has_whole_term(label_n, v8.GENERIC_CONTENT_TERMS)


def _entity_is_text_surface(entity: dict) -> bool:
    joined = f"{_norm(entity.get('name'))} {' '.join(_attrs(entity))}"
    return any(hint in joined for hint in TEXT_ATTR_HINTS + ("tag chip", "tag label"))


def _workspace_identity(label: str) -> str:
    core = v8._panel_core(label)
    core = re.sub(r"\b(?:page|workspace|screen|sidebar)\b", " ", core)
    return _norm(core)


def query_surface_intent(query: str) -> str | None:
    if _is_generic_content_label(query):
        return _V8_QUERY_SURFACE_INTENT(query)
    bound = parse_bound_surface_query(query)
    if bound:
        return bound.intent
    if WORKSPACE_LABEL_RE.search(_norm(query)):
        return "workspace"
    return _V8_QUERY_SURFACE_INTENT(query)


def _strip_glue(text: str) -> str:
    tokens = [item for item in _norm(text).split() if item not in poc.GLUE_CONDITION_LABELS]
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


def _blob_without_notable_text(record: dict) -> str:
    chunks = [
        record.get("scene_description") or "",
        record.get("environment") or "",
        " ".join(record.get("ui_types") or []),
        " ".join(record.get("activities") or []),
        " ".join(record.get("relationships") or []),
    ]
    for app in record.get("applications") or []:
        chunks.extend(
            [
                app.get("name") or "",
                app.get("visible_content") or "",
            ]
        )
    return _norm(" ".join(str(part) for part in chunks if part))


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


def _has_workspace_phrase(record: dict, identity: str) -> bool:
    blob = _blob_without_notable_text(record)
    for alias in _identity_aliases(identity):
        for head in WORKSPACE_HEADS:
            if f"{alias} {head}" in blob:
                return True
            if f"{head} {alias}" in blob and head in {"page", "workspace"}:
                return True
    return False


def _attrs(entity: dict) -> list[str]:
    return [_norm(item) for item in (entity.get("attributes") or [])]


def _attr_set(entity: dict) -> set[str]:
    values = set(_attrs(entity))
    joined = " ".join(_attrs(entity))
    values.add(joined)
    return values


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


def _entity_is_identity_workspace(entity: dict, identity: str) -> bool:
    name = entity.get("name") or ""
    if not _identity_in(name, identity) and not any(_identity_in(item, identity) for item in _attrs(entity)):
        return False
    if _entity_has_control_attrs(entity) and not _entity_has_workspace_attrs(entity):
        return False
    if _entity_has_control_attrs(entity) and _entity_has_workspace_attrs(entity):
        # "tags panel" + "tag controls" is a widget, not a Tags workspace.
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


def _has_identity_workspace_from_label(record: dict, label: str) -> bool:
    return _has_identity_workspace(record, label)


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


def _has_icon_surface(record: dict, identity: str) -> bool:
    blob = poc.flatten_fact_text(record)
    if any(f"{alias} icon" in blob for alias in _identity_aliases(identity)):
        if _has_icon_entity(record, identity):
            return True
        # A phrase in scene still needs the surface, not just an open window.
    return _has_icon_entity(record, identity)


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


def _has_control_surface(record: dict, identity: str) -> bool:
    for entity in record.get("entities") or []:
        name = entity.get("name") or ""
        if not _identity_in(name, identity) and not any(_identity_in(item, identity) for item in _attrs(entity)):
            continue
        if _entity_has_control_attrs(entity):
            return True
        if _norm(name).endswith(" button"):
            return True
    blob = _blob_without_notable_text(record)
    return any(f"{alias} button" in blob for alias in _identity_aliases(identity))


def _has_filename_surface(record: dict, identity: str) -> bool:
    for entity in record.get("entities") or []:
        joined = f"{entity.get('name') or ''} {' '.join(_attrs(entity))}"
        if _identity_in(joined, identity) and any(hint in _norm(joined) for hint in FILENAME_HINTS):
            return True
    blob = poc.flatten_fact_text(record)
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


def _has_rendered_interface(record: dict, label: str) -> bool:
    label = _strip_glue(label) or _norm(label)
    if v8._is_visual_object_condition(label, record):
        return False
    if _record_is_branding_only(record) and not _has_nested_depicted_ui(record, label):
        return False
    for app in record.get("applications") or []:
        vis = app.get("visible_content") or ""
        if any(hint in _norm(vis) for hint in BRANDING_HINTS) and not _visible_has_app_ui(vis):
            continue
        if v8._label_in_text(label, app.get("name"), vis) or _identity_in(app.get("name"), label):
            if _visible_has_app_ui(vis) or v8._label_in_text(label, app.get("name")):
                return True
        if _identity_in(vis, label) and _visible_has_app_ui(vis):
            return True
    for ui_type in record.get("ui_types") or []:
        if v8._label_in_text(label, ui_type) or _identity_in(ui_type, label):
            return True
    for entity in record.get("entities") or []:
        if v8._non_interface_entity(entity) or _entity_is_text_surface(entity):
            continue
        if v8._label_in_text(label, entity.get("name"), *(entity.get("attributes") or [])) or _identity_in(
            entity.get("name"), label
        ):
            return True
    for rel in record.get("relationships") or []:
        rel_n = str(rel).lower()
        if any(token in rel_n for token in v8.NON_INTERFACE_TOKENS + v8.CONTROL_TOKENS):
            continue
        if (v8._label_in_text(label, rel) or _identity_in(rel, label)) and any(
            token in rel_n for token in ("open", "displayed", "displaying", "window", "editor", "browser")
        ):
            return True
    if _scene_has_open_host(record, label):
        return True
    return False


def _has_nested_depicted_ui(record: dict, label: str) -> bool:
    for entity in record.get("entities") or []:
        if entity.get("visibility") != "nested":
            continue
        if v8._non_interface_entity(entity):
            continue
        if v8._label_in_text(label, entity.get("name"), *(entity.get("attributes") or [])):
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
        if _identity_in(vis, label):
            return True
    for rel in record.get("relationships") or []:
        if _identity_in(rel, label) and any(hint in _norm(rel) for hint in DISPLAYED_HINTS):
            return True
    for entity in record.get("entities") or []:
        if _entity_is_text_surface(entity) or v8._non_interface_entity(entity):
            continue
        if _identity_in(entity.get("name"), label):
            return True
    return False


def _set_confirmed(row: dict, confirmed: bool, override: str) -> None:
    row["confirmed"] = confirmed
    row["contract_override"] = override
    if confirmed and not (row.get("evidence") or "").strip():
        row["evidence"] = override.replace("_", " ")[:140]


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


def ensure_bound_conditions(item: dict, *, query: str) -> dict:
    """Keep compound surface conditions even if the model omitted them."""
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

    for row in rows:
        label = _norm(row.get("condition"))
        if not label or v8._is_visual_object_condition(label, record):
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
            core = v8._panel_core(label) or label[: -len(" open")]
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
            if row.get("confirmed") is True and not v8._has_desktop_environment(record):
                _set_confirmed(row, False, "incidental_or_nested_desktop")
            continue
        if row.get("confirmed") is True and v8._matches_dropped_host(record, label):
            if _has_rendered_interface(record, label) or _scene_has_open_host(record, label):
                row["contract_override"] = "kept_host_identity"
                continue
            _set_confirmed(row, False, "dropped_host_identity")
            continue
        if v8._is_application_or_ui_condition(label) or v8._only_non_interface_mention(record, label):
            if _has_rendered_interface(record, label):
                if row.get("confirmed") is not True:
                    _set_confirmed(row, True, "rendered_interface")
                continue
            if row.get("confirmed") is True and (
                _record_is_branding_only(record)
                or v8._evidence_is_weak(row.get("evidence") or "")
                or v8._only_non_interface_mention(record, label)
            ):
                _set_confirmed(row, False, "non_interface_or_branding")
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
                v8._is_application_or_ui_condition(_norm(other.get("condition")))
                or _has_rendered_interface(record, _norm(other.get("condition")))
                or _has_identity_workspace(record, _norm(other.get("condition")))
            )
            for other in rows
        )
        if others_ok:
            _set_confirmed(row, True, row.get("contract_override") or "open_implied_by_interface")
        elif row.get("confirmed") is True:
            # Do not keep a leftover open=true when the named workspace failed.
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


def _search_batch(
    *,
    query,
    records,
    api_key,
    model,
    endpoint,
    temperature,
    timeout_seconds,
    retries,
):
    image_ids = [int(item["image_id"]) for item in records]
    docs = "\n\n".join(poc.format_fact_record(item) for item in records)
    payload = poc.chat_payload(
        model=model,
        system=SEARCH_PROMPT,
        user=(
            f"Query: {query}\n\n"
            "Stored facts (source of truth). Judge only from these facts.\n"
            "List every independent condition the query states. Do not add "
            "extra conditions. Named surfaces are one condition; do not split "
            "Chrome icon, Tags button, Chrome text mention, or Tags panel open "
            "into separate words. Workspace queries need that identity's "
            "page/pane/panel, not a same-named button or unrelated panel. "
            "Branding/splash/category is not a rendered application. Nested "
            "visual objects still count. Do not output a final relevant flag.\n\n"
            f"{docs}"
        ),
        schema_name="db_sot_relevance",
        schema=poc.search_schema(image_ids),
        temperature=temperature,
    )
    started = __import__("time").perf_counter()
    response = poc.post_chat(
        payload,
        api_key=api_key,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )
    elapsed = __import__("time").perf_counter() - started
    parsed = poc.parse_message(response)
    by_id = {
        int(item["image_id"]): item
        for item in parsed.get("results") or []
        if isinstance(item, dict) and "image_id" in item
    }
    missing = [image_id for image_id in image_ids if image_id not in by_id]
    usage = poc.usage_from_response(response)
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    return by_id, missing, usage, elapsed


def _search_query(
    *,
    query,
    records,
    api_key,
    model,
    endpoint,
    temperature,
    timeout_seconds,
    retries,
):
    records = [v8._normalize_host_identity(dict(item)) for item in records]
    record_by_id = {int(item["image_id"]): item for item in records}
    image_ids = [int(item["image_id"]) for item in records]
    by_id = {}
    usage = empty_usage()
    elapsed = 0.0
    chunks = [records[i : i + 5] for i in range(0, len(records), 5)]
    for chunk in chunks:
        remaining = list(chunk)
        for _attempt in range(3):
            found, missing, chunk_usage, chunk_elapsed = _search_batch(
                query=query,
                records=remaining,
                api_key=api_key,
                model=model,
                endpoint=endpoint,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                retries=retries,
            )
            by_id.update(found)
            elapsed += chunk_elapsed
            usage = add_usage(usage, chunk_usage)
            if not missing:
                break
            remaining = [record_by_id[image_id] for image_id in missing]
        else:
            missing_ids = [
                int(item["image_id"]) for item in remaining if int(item["image_id"]) not in by_id
            ]
            if missing_ids:
                raise RuntimeError(f"search omitted image_ids={missing_ids} query={query!r}")
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    filtered = [poc.filter_query_conditions(by_id[image_id], query=query) for image_id in image_ids]
    aligned = v8.align_condition_labels(filtered, query=query)
    ordered = []
    for item, image_id in zip(aligned, image_ids):
        record = record_by_id[image_id]
        ensure_bound_conditions(item, query=query)
        apply_surface_contract(item, query=query, record=record)
        v8.apply_color_contract(item, query=query, record=record)
        v8.reconcile_reason(item, query=query)
        ordered.append(poc.enforce_condition_consistency(item, query=query, record=record))
    return ordered, usage, elapsed
