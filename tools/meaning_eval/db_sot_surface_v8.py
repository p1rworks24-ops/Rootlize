"""DB-SoT surface-contract v8: keep facts schema v3, fix Precision in search.

Independent of presence-role v7c. Starts from frozen v6b facts/search and adds
the minimum general contract needed to distinguish rendered UI from a name
that only appears as a shortcut, icon, control, folder, or text mention.
"""

from __future__ import annotations

import re

from tools.meaning_eval.describe_judge import add_usage, empty_usage
from tools.meaning_eval import db_sot_facts_v6 as facts_v6
from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE, configure as configure_v6b


PROMPT_VERSION = "db-sot-facts-v8-host-identity"
SEARCH_PROMPT_VERSION = "db-sot-search-v1.5-surface-contract"
SCHEMA_VERSION = "image-facts-v3"

FACT_PROMPT = facts_v6.FACT_PROMPT + r"""

Host application vs inner content (query-independent):
- Name a host application only when that application's own chrome or
  distinctive product UI is visible: window frame/title bar, tab strip,
  address bar, branded window controls, or a layout that is recognizably
  that product rather than generic content.
- Inner content is not host evidence. A web page, form, document, video, or
  settings sheet can live in many hosts. If the host is not visible, record
  the content/site and leave the host unnamed. Do not default a web page to
  a particular browser.
- `ui_types` may include "browser window" only when browser chrome is
  visible. A cropped webpage is web content, not a named browser.

Controls vs open panels:
- A button, tab, or menu labeled X is a control. Record it as an object
  entity with an attribute such as `button` or `ui control`, and/or as
  notable_text. Do not record a control as an open panel, open application,
  or ui_type of that panel.
- Record a panel/pane/sidebar only when that workspace is actually visible
  as an open region.

File and folder names:
- An identifiable file/folder label is notable_text, or an object entity
  with an attribute such as `folder name` / `file name`. It is not the
  named application.

Keep using existing fields. Nested visual subjects (animals, people,
characters, and nested screenshots of UI) remain ordinary entities.
When the entity budget is tight, keep independently identifiable depicted
subjects before a long tail of similar shortcuts; leftover shortcut names
may stay in notable_text.
"""

SEARCH_PROMPT = poc.SEARCH_PROMPT + r"""

Meaning contract for simple queries:
- Visual objects (dog, cat, anime character, person, logo, depicted photo):
  presence anywhere counts, including nested thumbnails/previews. Nested
  placement is not a negative.
- Bare application / product / UI-type queries (Google Chrome, Visual
  Studio Code, code editor, screenshot manager, file explorer window):
  the query asks whether that UI is visually depicted as a rendered
  interface. An open window counts. A nested screenshot of that UI counts.
  A desktop shortcut, taskbar/dock icon, launcher, labeled button, file or
  folder name, or other text mention does not count.
- Bare browser/product identity is not the same as "a web page is visible".
  If stored facts do not identify the host application, do not confirm a
  specific browser or editor from page content alone.
- If the query itself names a surface (icon, shortcut, button, folder,
  text mention, open panel), use that surface. An open application does
  not satisfy "icon" / "button" / "folder name" / "text mention" unless
  that surface is also recorded. A labeled control does not satisfy
  "panel" / "open" unless the panel/workspace is recorded as visible.

Color adjectives:
- Confirm a color on a target when that color is the dominant recorded
  color of the same entity: it is the first canonical color, the only
  canonical color, or the observed description says "mostly <color>".
- Extra markings do not falsify a dominant color. "mostly white" confirms
  white. Adjacent hues still do not match (tan is not orange-brown).

Condition completeness:
- Every image must list the same independent conditions taken from the
  query. If a condition is unsupported, still list it with confirmed=false.
  Omitting an unconfirmed condition is an error.
- The confirmed boolean must agree with the reason. If the reason says a
  condition is not confirmed or not supported, that row must be false.
"""

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
)
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
REASON_UNCONFIRMED_RE = re.compile(
    r"(?P<label>.+?)(?: is not confirmed| is not supported| are not confirmed| not confirmed)",
    re.IGNORECASE,
)


def configure() -> None:
    configure_v6b()
    facts_v6.FACT_PROMPT = FACT_PROMPT
    poc.PROMPT_VERSION = PROMPT_VERSION
    poc.SCHEMA_VERSION = SCHEMA_VERSION
    poc.FACT_PROMPT = FACT_PROMPT
    poc.SEARCH_PROMPT_VERSION = SEARCH_PROMPT_VERSION
    poc.SEARCH_PROMPT = SEARCH_PROMPT
    poc.analyze_image = _analyze_image
    poc.search_query = _search_query
    poc.missing_explicit_entities = _missing_explicit_entities


def _v6b_analyze_image(*args, **kwargs):
    return facts_v6.analyze_image_multiscale(*args, **kwargs)


def _normalize_host_identity(record: dict) -> dict:
    """Drop host-application rows that only describe inner content."""
    kept_apps = []
    dropped_names = []
    for item in record.get("applications") or []:
        if _content_only_host(item):
            dropped_names.append(str(item.get("name") or "").strip())
            continue
        kept_apps.append(item)
    record["applications"] = kept_apps
    if dropped_names:
        record["_dropped_host_names"] = [
            *(record.get("_dropped_host_names") or []),
            *dropped_names,
        ]
    else:
        record.setdefault("_dropped_host_names", [])
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


def _is_browser_app(item: dict) -> bool:
    blob = f"{item.get('name') or ''} {item.get('category') or ''} {item.get('kind') or ''}".lower()
    return "browser" in blob


def _content_only_host(item: dict) -> bool:
    if not _is_browser_app(item):
        return False
    visible = (item.get("visible_content") or "").lower()
    if any(token in visible for token in HOST_CHROME_TOKENS):
        return False
    if "browser" in visible or "chrome window" in visible:
        return False
    name = (item.get("name") or "").strip().lower()
    if name and name in visible:
        return False
    return True


def _analyze_image(*args, **kwargs):
    record, usage, elapsed = _v6b_analyze_image(*args, **kwargs)
    return _normalize_host_identity(record), usage, elapsed


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
            "extra conditions. If the query names an entity, that entity "
            "must be listed. A thumbnail is not that entity. Nested visual "
            "objects still count. Bare application/UI names need a rendered "
            "interface, not a shortcut, button, folder name, or text mention. "
            "Do not output a final relevant flag.\n\n"
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
    records = [_normalize_host_identity(dict(item)) for item in records]
    record_by_id = {int(item["image_id"]): item for item in records}
    image_ids = [int(item["image_id"]) for item in records]
    by_id = {}
    usage = empty_usage()
    elapsed = 0.0
    chunks = [records[i:i + 5] for i in range(0, len(records), 5)]
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
            missing_ids = [int(item["image_id"]) for item in remaining if int(item["image_id"]) not in by_id]
            if missing_ids:
                raise RuntimeError(f"search omitted image_ids={missing_ids} query={query!r}")
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    filtered = [
        poc.filter_query_conditions(by_id[image_id], query=query) for image_id in image_ids
    ]
    aligned = align_condition_labels(filtered, query=query)
    ordered = []
    for item, image_id in zip(aligned, image_ids):
        record = record_by_id[image_id]
        apply_surface_contract(item, query=query, record=record)
        apply_color_contract(item, query=query, record=record)
        reconcile_reason(item, query=query)
        ordered.append(poc.enforce_condition_consistency(item, query=query, record=record))
    return ordered, usage, elapsed


def align_condition_labels(items: list[dict], *, query: str) -> list[dict]:
    """Fill omitted query conditions from this image's own reason, not other images."""
    aligned_items = []
    for item in items:
        by_label = {}
        for row in item.get("independent_conditions") or []:
            label = poc.normalize_condition_label(row.get("condition"))
            if label and label not in by_label and poc.condition_mentioned_in_query(label, query):
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


def _missing_query_colors(query: str, labels) -> list[str]:
    query_n = poc.normalize_condition_label(query)
    covered = poc.normalize_condition_label(" ".join(labels))
    missing = []
    for color in sorted(COLOR_TERMS, key=len, reverse=True):
        color_n = poc.normalize_condition_label(color)
        if color_n in {"dark", "light", "calico"}:
            continue
        if color_n in query_n and color_n not in covered:
            missing.append(color_n)
            break
    return missing


def _missing_explicit_entities(query: str, record: dict) -> list[str]:
    blob = poc.flatten_fact_text(record).replace("-", " ")
    query_text = f" {query.lower().replace('-', ' ')} "
    missing = []
    for name, aliases in poc.EXPLICIT_ENTITY_ALIASES:
        if f" {name} " not in query_text and f" {name}s " not in query_text:
            continue
        if not any(re.search(rf"\b{re.escape(alias)}\b", blob) for alias in aliases):
            missing.append(name)
    return missing


def _unconfirmed_labels_from_reason(reason: str, *, query: str) -> list[str]:
    labels = []
    for match in REASON_UNCONFIRMED_RE.finditer(reason or ""):
        raw = match.group("label")
        raw = re.split(r"[.;:] ", raw)[-1]
        raw = re.sub(r"^(?:but |and |the query also includes )", "", raw.strip(), flags=re.I)
        label = poc.normalize_condition_label(raw)
        if label and poc.condition_mentioned_in_query(label, query) and label not in poc.GLUE_CONDITION_LABELS:
            labels.append(label)
    return labels


def query_surface_intent(query: str) -> str | None:
    q = poc.normalize_condition_label(query)
    if "text mention" in q or q.endswith(" mention"):
        return "text"
    if "button" in q.split() or q.endswith(" button"):
        return "control"
    if "icon" in q.split() or "icons" in q.split() or "shortcut" in q or "shortcuts" in q:
        return "icon"
    if "folder" in q and "empty" not in q and "library" not in q:
        return "filename"
    return None


def _blob(parts) -> str:
    return " ".join(str(part or "").lower() for part in parts if part)


def _has_whole_term(text: str, terms: tuple[str, ...]) -> bool:
    text_n = poc.normalize_condition_label(text)
    tokens = set(text_n.split())
    for term in terms:
        term_n = poc.normalize_condition_label(term)
        if not term_n:
            continue
        if " " in term_n:
            if term_n in text_n:
                return True
        elif term_n in tokens:
            return True
    return False
    return " ".join(str(part or "").lower() for part in parts if part)


def _label_in_text(label: str, *parts: object) -> bool:
    text = poc.normalize_condition_label(_blob(parts))
    label_n = poc.normalize_condition_label(label)
    if not label_n or not text:
        return False
    if label_n in text:
        return True
    compact_label = label_n.replace(" ", "")
    compact_text = text.replace(" ", "")
    return bool(compact_label) and compact_label in compact_text


def _is_visual_object_condition(label: str, record: dict) -> bool:
    label_n = poc.normalize_condition_label(label)
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
    label_n = poc.normalize_condition_label(label)
    if _has_whole_term(label_n, GENERIC_CONTENT_TERMS):
        return False
    return _has_whole_term(label_n, UI_TYPE_TERMS)


def _non_interface_entity(entity: dict) -> bool:
    name = poc.normalize_condition_label(entity.get("name"))
    attrs = [poc.normalize_condition_label(item) for item in (entity.get("attributes") or [])]
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


def _has_rendered_interface(record: dict, label: str) -> bool:
    for app in record.get("applications") or []:
        if _label_in_text(label, app.get("name"), app.get("category"), app.get("visible_content")):
            return True
    for ui_type in record.get("ui_types") or []:
        if _label_in_text(label, ui_type):
            return True
    for entity in record.get("entities") or []:
        if _non_interface_entity(entity):
            continue
        if _label_in_text(label, entity.get("name"), *(entity.get("attributes") or [])):
            return True
    for rel in record.get("relationships") or []:
        rel_n = str(rel).lower()
        if any(token in rel_n for token in NON_INTERFACE_TOKENS + CONTROL_TOKENS):
            continue
        if _label_in_text(label, rel) and any(
            token in rel_n for token in ("open", "displayed", "displaying", "window", "editor", "browser")
        ):
            return True
    return False


def _only_non_interface_mention(record: dict, label: str) -> bool:
    if _has_rendered_interface(record, label):
        return False
    return any(
        _label_in_text(label, entity.get("name")) and _non_interface_entity(entity)
        for entity in record.get("entities") or []
    )


def _evidence_is_weak(evidence: str) -> bool:
    blob = (evidence or "").lower()
    return any(token in blob for token in WEAK_EVIDENCE_TOKENS)


def _matches_dropped_host(record: dict, label: str) -> bool:
    for name in record.get("_dropped_host_names") or []:
        if _label_in_text(label, name) or _label_in_text(name, label):
            return True
    return False


def _panel_core(label: str) -> str:
    core = poc.normalize_condition_label(label)
    for token in ("open", "panel", "pane", "sidebar"):
        core = core.replace(token, " ")
    tokens = [item for item in poc.normalize_condition_label(core).split() if item not in poc.GLUE_CONDITION_LABELS]
    return " ".join(tokens)


def _has_desktop_environment(record: dict) -> bool:
    blob = poc.normalize_condition_label(
        f"{record.get('environment') or ''} {' '.join(record.get('ui_types') or [])}"
    )
    return "windows desktop" in blob or "desktop environment" in blob


def _has_open_panel(record: dict, label: str) -> bool:
    core = _panel_core(label)
    if not core:
        return False
    blob = poc.flatten_fact_text(record)
    phrases = (
        f"{core} panel",
        f"{core} pane",
        f"{core} sidebar",
        f"{core} side panel",
        f"{core} sidepane",
    )
    if any(phrase in blob for phrase in phrases):
        return True
    return bool(core) and core in blob and any(word in blob.split() for word in ("panel", "pane", "sidebar"))


def apply_surface_contract(item: dict, *, query: str, record: dict) -> dict:
    intent = query_surface_intent(query)
    rows = item.get("independent_conditions") or []
    for row in rows:
        label = poc.normalize_condition_label(row.get("condition"))
        if not label or _is_visual_object_condition(label, record):
            continue
        if intent:
            continue
        if label == "open":
            others_ok = any(
                other.get("confirmed") is True
                and other is not row
                and (
                    _is_application_or_ui_condition(poc.normalize_condition_label(other.get("condition")))
                    or _has_rendered_interface(record, poc.normalize_condition_label(other.get("condition")))
                )
                for other in rows
            )
            if others_ok:
                row["confirmed"] = True
                row["contract_override"] = row.get("contract_override") or "open_implied_by_interface"
                continue
        if any(token in label.split() for token in ("panel", "pane", "sidebar")):
            if _has_open_panel(record, label) or _has_rendered_interface(record, label):
                if row.get("confirmed") is not True:
                    row["confirmed"] = True
                    row["evidence"] = f"record describes a visible {label}"[:140]
                    row["contract_override"] = "open_panel_in_facts"
                continue
            if row.get("confirmed") is True and _evidence_is_weak(row.get("evidence") or ""):
                row["confirmed"] = False
                row["contract_override"] = "control_is_not_open_panel"
                continue
        if "desktop" in label.split() and row.get("confirmed") is True and not _has_desktop_environment(record):
            row["confirmed"] = False
            row["contract_override"] = "incidental_or_nested_desktop"
            continue
        if label.endswith(" open"):
            core = _panel_core(label) or label
            if _has_open_panel(record, label) or _has_rendered_interface(record, core):
                if row.get("confirmed") is not True:
                    row["confirmed"] = True
                    row["evidence"] = f"record describes visible {label}"[:140]
                    row["contract_override"] = "open_panel_in_facts"
                continue
            if row.get("confirmed") is True:
                row["confirmed"] = False
                row["contract_override"] = "control_is_not_open_panel"
                continue
        if row.get("confirmed") is not True:
            continue
        if _matches_dropped_host(record, label) and not _has_rendered_interface(record, label):
            row["confirmed"] = False
            row["contract_override"] = "dropped_host_identity"
            continue
        if not (_is_application_or_ui_condition(label) or _only_non_interface_mention(record, label)):
            continue
        if _has_rendered_interface(record, label):
            continue
        if _evidence_is_weak(row.get("evidence") or "") or _only_non_interface_mention(record, label):
            row["confirmed"] = False
            row["contract_override"] = "non_interface_surface"
    item["surface_intent"] = intent or ""
    return item


def _dominant_color_confirms(entity: dict, color: str) -> bool:
    color_n = poc.normalize_condition_label(color).replace(" ", "-")
    colors = [poc.normalize_condition_label(item).replace(" ", "-") for item in (entity.get("colors") or [])]
    observed = poc.normalize_condition_label(entity.get("observed_color_description"))
    observed_h = observed.replace(" ", "-")
    if f"mostly {color_n}" in observed_h or f"mostly {color.replace('-', ' ')}" in observed:
        return True
    if colors and colors[0] == color_n:
        return True
    if color_n in colors and len(colors) == 1:
        return True
    return False


def _color_from_label(label: str) -> str | None:
    label_n = poc.normalize_condition_label(label)
    for color in sorted(COLOR_TERMS, key=len, reverse=True):
        color_n = poc.normalize_condition_label(color)
        if color_n == label_n or label_n.startswith(color_n + " ") or f" {color_n} " in f" {label_n} ":
            if color_n in {"dark", "light"}:
                continue
            return color_n
    return None


def apply_color_contract(item: dict, *, query: str, record: dict) -> dict:
    for row in item.get("independent_conditions") or []:
        label = poc.normalize_condition_label(row.get("condition"))
        color = _color_from_label(label)
        if not color:
            continue
        remainder = poc.normalize_condition_label(label.replace(color, ""))
        matched = False
        for entity in record.get("entities") or []:
            if entity.get("kind") not in VISUAL_OBJECT_KIND:
                continue
            if remainder and not _label_in_text(remainder, entity.get("name")):
                continue
            if remainder or entity.get("kind") in VISUAL_OBJECT_KIND:
                if remainder and _dominant_color_confirms(entity, color):
                    matched = True
                    if row.get("confirmed") is not True:
                        row["confirmed"] = True
                        row["evidence"] = (
                            f"entities: name={entity.get('name')}; "
                            f"canonical_colors={'/'.join(entity.get('colors') or [])}; "
                            f"observed_color={entity.get('observed_color_description')}"
                        )[:140]
                        row["contract_override"] = "dominant_color"
                    break
                if not remainder and _dominant_color_confirms(entity, color):
                    matched = True
                    if row.get("confirmed") is not True:
                        row["confirmed"] = True
                        row["evidence"] = (
                            f"entities: name={entity.get('name')}; "
                            f"canonical_colors={'/'.join(entity.get('colors') or [])}; "
                            f"observed_color={entity.get('observed_color_description')}"
                        )[:140]
                        row["contract_override"] = "dominant_color"
                    break
        if remainder and row.get("confirmed") is True and not matched:
            row["confirmed"] = False
            row["contract_override"] = "color_without_target"
    return item


def reconcile_reason(item: dict, *, query: str) -> dict:
    reason = item.get("reason") or ""
    denied = set(_unconfirmed_labels_from_reason(reason, query=query))
    if not denied:
        return item
    for row in item.get("independent_conditions") or []:
        label = poc.normalize_condition_label(row.get("condition"))
        if label in denied and row.get("confirmed") is True and not row.get("contract_override"):
            row["confirmed"] = False
            row["contract_override"] = "reason_contradiction"
    return item
