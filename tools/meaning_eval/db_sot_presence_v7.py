"""Versioned presence-role facts and condition contract for DB-SoT PoC."""

from copy import deepcopy
import time

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_facts_v6 as v6

BASE_FACT_SCHEMA = poc.fact_schema
BASE_SEARCH_SCHEMA = poc.search_schema
BASE_FORMAT_FACT_RECORD = poc.format_fact_record


PROMPT_VERSION = "db-sot-facts-v7-presence-role"
SCHEMA_VERSION = "image-facts-v4-presence-role"
SEARCH_PROMPT_VERSION = "db-sot-search-v2.1-stable-fact-refs"
SEARCH_SCHEMA_VERSION = "db-sot-relevance-v4-evidence-refs"

PRESENCE_ROLES = (
    "direct_subject",
    "open_interface",
    "nested_content",
    "preview_content",
    "desktop_shortcut",
    "taskbar_icon",
    "ui_control",
    "text_mention",
    "file_or_folder_name",
    "background_incidental",
)

IDENTITY_EVIDENCE = (
    "direct_visual",
    "visible_branding",
    "distinctive_interface",
    "text_label",
    "inferred",
    "unknown",
)

VISUAL_SUBJECT_ROLES = {
    "direct_subject", "nested_content", "preview_content", "background_incidental"
}
APPLICATION_ROLES = {
    "open_interface", "nested_content", "preview_content", "background_incidental"
}
NON_INSTANCE_ROLES = {
    "desktop_shortcut", "taskbar_icon", "ui_control", "text_mention", "file_or_folder_name"
}


FACT_PROMPT = v6.FACT_PROMPT + r"""

Presence-role schema v4 overrides any earlier instruction that discarded
shortcut/icon/mention evidence. Keep useful evidence, but preserve how it
exists so search cannot confuse it with an open instance.

For every entity and application row:
- fact_id: stable unique id within this image (`e1`, `e2`, `a1`, ...).
- presence_role:
  direct_subject = a depicted real-world/illustrated subject in this image;
  open_interface = a visibly rendered application, website, panel, window, or
  OS environment; nested_content = content inside a thumbnail, gallery item,
  embedded screenshot, or image; preview_content = content rendered inside an
  actually visible preview pane; desktop_shortcut = a desktop shortcut only;
  taskbar_icon = a taskbar/dock/launcher icon only; ui_control = a button,
  menu item, tab, label, or other control that does not prove its target is
  open; text_mention = prose/status text only; file_or_folder_name = a visible
  filename or folder name only; background_incidental = a visually present
  secondary/background subject or open interface.
- container: concise visible container, empty only for direct top-level facts.
- identity_confirmed: true only when the pixels directly support that identity.
- identity_evidence: strongest actual basis. `text_label` confirms that the
  label exists but does not by itself prove the named application is open.
  `inferred` must always have identity_confirmed=false.

Applications may now retain recognized application identities at any role,
including shortcut, icon, filename, or nested screenshot. Never change their
role to open_interface merely because the identity is recognizable.

Application identity rule:
- A visible web page proves a web page/site or service when branded, but does
  not prove Google Chrome, Edge, Safari, or another browser unless browser
  chrome, branding, or distinctive browser interface is visible.
- Generic page content without browser chrome must not create a confirmed
  browser identity. If retained as an inference, set identity_confirmed=false,
  identity_evidence=inferred.
- A control labelled Preview proves a Preview control (`ui_control`), not an
  open preview panel. An actually rendered preview pane is `open_interface`;
  its depicted contents are `preview_content`.
- A folder/file name or text label may identify its string, but never proves
  that the named application, panel, or object is open.

Nested visual subjects remain searchable facts. A dog or anime character in a
gallery thumbnail is a subject with presence_role=nested_content, not merely a
filename and not an open application.
"""


SEARCH_PROMPT = poc.SEARCH_PROMPT + r"""

Presence-role condition contract v2:
- Every condition must cite one or more exact bracketed fact_id values shown in
  the stored record. Never invent, prefix, suffix, translate, or renumber an ID.
  Context fields also have exact `ctx_*` IDs and may be cited only for the text
  printed on that line. Never cite prose not in the DB.
- condition_type describes what the query requires: subject, application, ui,
  attribute, state, environment, relation, or presence.
- A bare visually depicted object/animal/person/character condition accepts
  direct_subject, nested_content, preview_content, or background_incidental.
  Being in a gallery does not make a dog or character disappear.
- A bare application/product/site/UI condition accepts a confirmed
  open_interface, a visually identifiable nested_content/preview_content
  screenshot, or a visible background_incidental interface. It rejects a
  desktop shortcut, taskbar icon, UI control, text mention, and file/folder
  name. Example: bare `Visual Studio Code` matches an open or visibly depicted
  VS Code interface, not its shortcut and not a folder named Microsoft VS Code.
- A proper application identity requires identity_confirmed=true and evidence
  other than inferred/unknown. Visible web content without browser identity
  evidence cannot confirm Google Chrome.
- Explicit role words are strict: open/active requires open_interface;
  shortcut requires desktop_shortcut; taskbar/dock icon requires taskbar_icon;
  button/menu/control requires ui_control; folder/file name requires
  file_or_folder_name; thumbnail/nested requires nested_content. `Preview
  panel` means the panel is visibly rendered (open_interface), not merely a
  Preview button. `Chrome icon` allows a Chrome desktop_shortcut or taskbar_icon
  but does not claim Chrome is open.
- Attributes/states must cite the same subject fact that owns them. Canonical
  color `white` confirms `white cat` even when other markings/colors coexist;
  exclusivity is required only if the query says all-white, solid white, or
  equivalent. Do not reject a stated canonical color because another color is
  also recorded.
- The boolean must agree with the cited facts and the explanation. If the facts
  do not support the condition under this role contract, confirmed=false.
Final relevant remains code-owned.
"""


def fact_schema_v4(image_ids: list[int]) -> dict:
    schema = deepcopy(BASE_FACT_SCHEMA(image_ids))
    item = schema["properties"]["results"]["items"]
    entity = item["properties"]["entities"]["items"]
    application = item["properties"]["applications"]["items"]
    extra = {
        "fact_id": {"type": "string", "maxLength": 16},
        "presence_role": {"type": "string", "enum": list(PRESENCE_ROLES)},
        "container": {"type": "string", "maxLength": 120},
        "identity_confirmed": {"type": "boolean"},
        "identity_evidence": {"type": "string", "enum": list(IDENTITY_EVIDENCE)},
    }
    for row in (entity, application):
        row["properties"].update(deepcopy(extra))
        row["required"].extend(extra.keys())
    return schema


def search_schema_v4(image_ids: list[int]) -> dict:
    schema = deepcopy(BASE_SEARCH_SCHEMA(image_ids))
    condition = schema["properties"]["results"]["items"]["properties"]["independent_conditions"]["items"]
    condition["properties"].update({
        "condition_type": {
            "type": "string",
            "enum": ["subject", "application", "ui", "attribute", "state", "environment", "relation", "presence"],
        },
        "evidence_fact_ids": {
            "type": "array",
            "items": {"type": "string", "maxLength": 32},
            "maxItems": 6,
        },
    })
    condition["required"].extend(["condition_type", "evidence_fact_ids"])
    return schema


def normalize_record_v4(record: dict) -> dict:
    record = v6._normalize_record(record)
    seen = set()
    for prefix, key in (("e", "entities"), ("a", "applications")):
        for index, item in enumerate(record.get(key) or [], 1):
            fact_id = str(item.get("fact_id") or f"{prefix}{index}")
            if fact_id in seen:
                fact_id = f"{prefix}{index}"
            item["fact_id"] = fact_id
            seen.add(fact_id)
    return record


def format_fact_record_v4(record: dict) -> str:
    lines = [f"image_id: {record.get('image_id')}"]
    context = _context_facts(record)
    for fact_id, fact in context.items():
        lines.append(
            f"[{fact_id}] {fact['name']}: {fact['value']}; "
            f"presence_role={fact['presence_role']}; identity_confirmed=true; "
            f"identity_evidence=direct_visual"
        )
    for key in ("entities", "applications"):
        for item in record.get(key) or []:
            details = []
            for detail_key in ("type", "attributes", "canonical_colors", "posture", "activity", "state", "visible_text"):
                value = item.get(detail_key)
                if value not in (None, "", []):
                    details.append(f"{detail_key}={value}")
            lines.append(
                f"[{item.get('fact_id')}] name={item.get('name')}; "
                + "; ".join(details)
                + ("; " if details else "")
                +
                f"presence_role={item.get('presence_role')}; container={item.get('container') or '(none)'}; "
                f"identity_confirmed={item.get('identity_confirmed')}; "
                f"identity_evidence={item.get('identity_evidence')}"
            )
    return "\n".join(lines)


def _context_facts(record: dict) -> dict[str, dict]:
    specs = (
        ("ctx_environment", "environment", record.get("environment"), "open_interface"),
        ("ctx_scene", "scene", record.get("scene_summary"), "direct_subject"),
        ("ctx_ui", "ui_types", record.get("ui_types"), "open_interface"),
        ("ctx_activities", "activities", record.get("activities"), "direct_subject"),
        ("ctx_relationships", "relationships", record.get("relationships"), "direct_subject"),
        ("ctx_text", "visible_text", record.get("visible_text"), "text_mention"),
    )
    return {
        fact_id: {
            "fact_id": fact_id,
            "name": name,
            "value": value,
            "presence_role": role,
            "identity_confirmed": True,
            "identity_evidence": "direct_visual",
        }
        for fact_id, name, value, role in specs
        if value not in (None, "", [])
    }


def _fact_map(record: dict) -> dict[str, dict]:
    facts = {
        str(item.get("fact_id")): item
        for key in ("entities", "applications")
        for item in record.get(key) or []
        if item.get("fact_id")
    }
    facts.update(_context_facts(record))
    return facts


def _explicit_roles(query: str) -> set[str] | None:
    q = " ".join(query.lower().replace("-", " ").split())
    if "shortcut" in q:
        return {"desktop_shortcut"}
    if "taskbar icon" in q or "dock icon" in q:
        return {"taskbar_icon"}
    if " icon" in f" {q}":
        return {"desktop_shortcut", "taskbar_icon", "ui_control"}
    if "folder" in q or "file name" in q or "filename" in q:
        return {"file_or_folder_name"}
    if any(word in q for word in (" button", " menu", " control")):
        return {"ui_control"}
    if "thumbnail" in q or "nested" in q:
        return {"nested_content"}
    if "preview panel" in q or "preview pane" in q:
        return {"open_interface"}
    if " open" in f" {q}" or "active" in q:
        return {"open_interface"}
    return None


def _allowed_roles(query: str, condition_type: str, condition: str) -> set[str]:
    # A role word constrains the condition it describes, not every independent
    # condition in a compound query (for example, a dog inside a preview panel).
    explicit = _explicit_roles(condition)
    if explicit is None and condition_type in {"application", "ui", "presence"}:
        explicit = _explicit_roles(query)
    if explicit is not None:
        return explicit
    if condition_type == "subject":
        return VISUAL_SUBJECT_ROLES
    if condition_type in {"application", "ui"}:
        return APPLICATION_ROLES
    if condition_type in {"attribute", "state"}:
        return VISUAL_SUBJECT_ROLES | APPLICATION_ROLES
    if condition_type == "presence":
        return VISUAL_SUBJECT_ROLES | APPLICATION_ROLES
    return set(PRESENCE_ROLES)


def enforce_presence_contract(item: dict, *, query: str, record: dict) -> dict:
    facts = _fact_map(record)
    failures = []
    conditions = item.get("independent_conditions") or []
    for row in conditions:
        if row.get("confirmed") is not True:
            continue
        condition_type = str(row.get("condition_type") or "subject")
        raw_refs = row.get("evidence_fact_ids") or []
        normalized_refs = [str(ref).strip().strip("[]") for ref in raw_refs]
        row["evidence_fact_ids"] = normalized_refs
        refs = [facts[ref] for ref in normalized_refs if ref in facts]
        if condition_type == "environment" and "environment" in (row.get("evidence_fact_ids") or []):
            continue
        allowed = _allowed_roles(query, condition_type, str(row.get("condition") or ""))
        compatible = [fact for fact in refs if fact.get("presence_role") in allowed]
        if condition_type in {"application", "ui"}:
            compatible = [
                fact for fact in compatible
                if fact.get("identity_confirmed") is True
                and fact.get("identity_evidence") not in {"inferred", "unknown"}
            ]
        if not compatible:
            row["confirmed"] = False
            failures.append({
                "condition": row.get("condition"),
                "reason": "no cited fact has an allowed presence role and identity basis",
            })
    relevant, unconfirmed = poc.relevant_from_conditions(conditions)
    item["presence_validation_failures"] = failures
    item["unconfirmed_conditions"] = unconfirmed
    item["relevant"] = relevant
    item["relevant_source"] = "conditions+presence_contract"
    return item


def search_query_v4(
    *, query, records, api_key, model, endpoint, temperature, timeout_seconds, retries
):
    image_ids = [int(item["image_id"]) for item in records]
    record_by_id = {int(item["image_id"]): item for item in records}
    by_id = {}
    total_usage = poc.empty_usage()
    elapsed = 0.0
    for start in range(0, len(records), 8):
        batch = records[start : start + 8]
        batch_ids = [int(item["image_id"]) for item in batch]
        docs = "\n\n".join(format_fact_record_v4(item) for item in batch)
        payload = poc.chat_payload(
            model=model,
            system=SEARCH_PROMPT,
            user=(
                f"Query: {query}\n\nStored facts (source of truth). Judge only from these facts. "
                "List every independent condition, cite fact_id values, apply the presence-role contract, "
                "and do not output final relevant.\n\n" + docs
            ),
            schema_name="db_sot_relevance_presence",
            schema=search_schema_v4(batch_ids),
            temperature=temperature,
        )
        started = time.perf_counter()
        response = poc.post_chat(payload, api_key=api_key, endpoint=endpoint, timeout_seconds=timeout_seconds, retries=retries)
        batch_elapsed = time.perf_counter() - started
        elapsed += batch_elapsed
        parsed = poc.parse_message(response)
        by_id.update({int(row["image_id"]): row for row in parsed.get("results") or [] if "image_id" in row})
        batch_usage = poc.usage_from_response(response)
        batch_usage["api_seconds"] = batch_elapsed
        batch_usage["total_seconds"] = batch_elapsed
        total_usage = poc.add_usage(total_usage, batch_usage)
    missing = [image_id for image_id in image_ids if image_id not in by_id]
    if missing:
        raise RuntimeError(f"search omitted image_ids={missing} query={query!r}")
    usage = total_usage
    usage["api_seconds"] = elapsed
    usage["total_seconds"] = elapsed
    ordered = []
    for image_id in image_ids:
        filtered = poc.filter_query_conditions(by_id[image_id], query=query)
        ordered.append(enforce_presence_contract(filtered, query=query, record=record_by_id[image_id]))
    return ordered, usage, elapsed


def configure() -> None:
    v6.configure()
    poc.PROMPT_VERSION = PROMPT_VERSION
    poc.SCHEMA_VERSION = SCHEMA_VERSION
    poc.SEARCH_PROMPT_VERSION = SEARCH_PROMPT_VERSION
    poc.SEARCH_SCHEMA_VERSION = SEARCH_SCHEMA_VERSION
    poc.FACT_PROMPT = FACT_PROMPT
    poc.fact_schema = fact_schema_v4
    poc.search_schema = search_schema_v4
    poc.format_fact_record = format_fact_record_v4
    poc.search_query = search_query_v4
    original_analyze = poc.analyze_image

    def analyze_and_normalize(**kwargs):
        record, usage, elapsed = original_analyze(**kwargs)
        return normalize_record_v4(record), usage, elapsed

    poc.analyze_image = analyze_and_normalize
