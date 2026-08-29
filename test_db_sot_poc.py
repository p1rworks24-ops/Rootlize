from tools.meaning_eval.db_sot_poc import (
    enforce_condition_consistency,
    filter_query_conditions,
    relevant_from_conditions,
    search_schema,
)
from tools.meaning_eval.db_sot_facts_v6 import _normalize_record
from tools.meaning_eval.db_sot_presence_v7 import enforce_presence_contract


def test_all_confirmed_conditions_are_relevant():
    relevant, unconfirmed = relevant_from_conditions(
        [
            {
                "condition": "screenshot manager",
                "confirmed": True,
                "evidence": "applications[Capixe].category",
            }
        ]
    )
    assert relevant is True
    assert unconfirmed == []


def test_any_unconfirmed_condition_is_not_relevant():
    relevant, unconfirmed = relevant_from_conditions(
        [
            {"condition": "screenshot manager", "confirmed": True, "evidence": "category"},
            {"condition": "dog", "confirmed": False, "evidence": ""},
        ]
    )
    assert relevant is False
    assert unconfirmed == ["dog"]


def test_empty_conditions_are_not_relevant():
    relevant, unconfirmed = relevant_from_conditions([])
    assert relevant is False
    assert unconfirmed == []


def test_code_overrides_missing_model_relevant_flag():
    item = {
        "image_id": 9,
        "independent_conditions": [
            {
                "condition": "screenshot manager",
                "confirmed": True,
                "evidence": "applications[Capixe].category",
            }
        ],
        "reason": "Capixe is a screenshot manager, but the query asked for that name.",
    }
    record = {
        "scene_description": "Capixe about page",
        "environment": "application window",
        "ui_types": ["settings screen"],
        "entities": [],
        "applications": [
            {
                "name": "Capixe",
                "category": "screenshot manager / image management application",
            }
        ],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }
    out = enforce_condition_consistency(item, query="screenshot manager", record=record)
    assert out["relevant"] is True
    assert out["relevant_source"] == "conditions"
    assert out["unconfirmed_conditions"] == []


def test_missing_explicit_dog_forces_false():
    item = {
        "image_id": 12,
        "independent_conditions": [
            {"condition": "dog", "confirmed": True, "evidence": "preview pane"}
        ],
        "reason": "a thumbnail grid implies a dog",
    }
    record = {
        "scene_description": "Screenshot Manager on a desktop",
        "environment": "Windows desktop",
        "ui_types": ["screenshot manager"],
        "entities": [],
        "applications": [{"name": "Screenshot Manager", "category": "screenshot manager"}],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }
    out = enforce_condition_consistency(
        item, query="screenshot manager showing a dog", record=record
    )
    assert out["relevant"] is False
    assert "dog" in out["unconfirmed_conditions"]


def test_query_filter_drops_unasked_attributes():
    item = {
        "independent_conditions": [
            {"condition": "dog", "confirmed": True, "evidence": "entity dog"},
            {"condition": "sitting", "confirmed": False, "evidence": ""},
            {"condition": "orange-brown", "confirmed": False, "evidence": ""},
        ]
    }
    out = filter_query_conditions(item, query="dog")
    relevant, unconfirmed = relevant_from_conditions(out["independent_conditions"])
    assert [row["condition"] for row in out["independent_conditions"]] == ["dog"]
    assert out["ignored_extra_conditions"] == ["sitting", "orange-brown"]
    assert relevant is True
    assert unconfirmed == []


def test_query_filter_drops_showing_glue_but_keeps_both_targets():
    item = {
        "independent_conditions": [
            {"condition": "screenshot manager", "confirmed": True, "evidence": "category"},
            {"condition": "dog", "confirmed": True, "evidence": "entity dog"},
            {"condition": "showing", "confirmed": False, "evidence": ""},
        ]
    }
    out = filter_query_conditions(item, query="screenshot manager showing a dog")
    relevant, unconfirmed = relevant_from_conditions(out["independent_conditions"])
    assert out["ignored_extra_conditions"] == ["showing"]
    assert relevant is True
    assert unconfirmed == []


def test_query_filter_keeps_meaning_units():
    item = {
        "independent_conditions": [
            {"condition": "code editor", "confirmed": True, "evidence": "ui_types"},
            {"condition": "terminal visible", "confirmed": True, "evidence": "ui_types"},
        ]
    }
    out = filter_query_conditions(item, query="code editor with terminal visible")
    relevant, unconfirmed = relevant_from_conditions(out["independent_conditions"])
    assert relevant is True
    assert unconfirmed == []
    assert out["ignored_extra_conditions"] == []


def test_search_schema_does_not_let_the_model_emit_relevant():
    schema = search_schema([1])
    properties = schema["properties"]["results"]["items"]["properties"]
    required = schema["properties"]["results"]["items"]["required"]
    assert "relevant" not in properties
    assert "relevant" not in required
    assert "independent_conditions" in properties


def test_facts_v6_removes_non_open_application_surfaces():
    record = {
        "applications": [
            {"name": "Cursor", "visible_content": "desktop shortcut"},
            {"name": "Chrome", "visible_content": "taskbar icon"},
            {"name": "Capixe", "visible_content": "open image library window"},
        ],
        "entities": [],
    }
    out = _normalize_record(record)
    assert [item["name"] for item in out["applications"]] == ["Capixe"]


def test_facts_v6_normalizes_unambiguous_posture_attribute():
    record = {
        "applications": [],
        "entities": [
            {"name": "dog", "posture": "", "attributes": ["sitting", "white muzzle"]}
        ],
    }
    out = _normalize_record(record)
    assert out["entities"][0]["posture"] == "sitting"
    assert out["entities"][0]["attributes"] == ["white muzzle"]


def _presence_record(role, *, confirmed=True, evidence="direct_visual"):
    return {
        "entities": [{
            "fact_id": "e1", "name": "Visual Studio Code", "presence_role": role,
            "identity_confirmed": confirmed, "identity_evidence": evidence,
        }],
        "applications": [],
    }


def _presence_item(condition_type="application"):
    return {"independent_conditions": [{
        "condition": "Visual Studio Code", "condition_type": condition_type,
        "confirmed": True, "evidence": "e1", "evidence_fact_ids": ["e1"],
    }]}


def test_presence_contract_rejects_shortcut_for_bare_application():
    out = enforce_presence_contract(
        _presence_item(), query="Visual Studio Code",
        record=_presence_record("desktop_shortcut"),
    )
    assert out["relevant"] is False


def test_presence_contract_accepts_nested_visual_application():
    out = enforce_presence_contract(
        _presence_item(), query="Visual Studio Code",
        record=_presence_record("nested_content"),
    )
    assert out["relevant"] is True


def test_presence_contract_accepts_explicit_shortcut_query():
    out = enforce_presence_contract(
        _presence_item("presence"), query="Visual Studio Code shortcut",
        record=_presence_record("desktop_shortcut"),
    )
    assert out["relevant"] is True


def test_presence_contract_rejects_inferred_application_identity():
    out = enforce_presence_contract(
        _presence_item(), query="Google Chrome",
        record=_presence_record("open_interface", confirmed=False, evidence="inferred"),
    )
    assert out["relevant"] is False


def test_presence_contract_normalizes_bracketed_fact_reference():
    item = _presence_item("subject")
    item["independent_conditions"][0]["evidence_fact_ids"] = ["[e1]"]
    out = enforce_presence_contract(
        item, query="Visual Studio Code",
        record=_presence_record("direct_subject"),
    )
    assert out["relevant"] is True
    assert out["independent_conditions"][0]["evidence_fact_ids"] == ["e1"]


def test_explicit_panel_role_does_not_constrain_companion_subject():
    item = {"independent_conditions": [{
        "condition": "dog", "condition_type": "subject", "confirmed": True,
        "evidence": "e1", "evidence_fact_ids": ["e1"],
    }]}
    record = _presence_record("nested_content")
    out = enforce_presence_contract(
        item, query="screenshot manager with a preview panel", record=record,
    )
    assert out["relevant"] is True
