"""Product identity-bound surface and same-entity contracts.

Ports the GO PoC surface tests with the product bare-entity rule:
only named conditions are required. Unspecified presence forms are not
added as negatives.
"""

from __future__ import annotations

from app.image_facts.contracts import apply_facts_contracts, filter_query_conditions


def _facts(**fields):
    record = {
        "media_type": "screenshot",
        "scene_description": "",
        "environment": "",
        "ui_types": [],
        "entities": [],
        "applications": [],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }
    record.update(fields)
    return record


def _entity(name, **fields):
    entity = {
        "name": name,
        "kind": fields.pop("kind", "object"),
        "attributes": fields.pop("attributes", []),
        "colors": fields.pop("colors", []),
        "states": fields.pop("states", []),
        "posture": fields.pop("posture", ""),
        "observed_color_description": fields.pop("observed_color_description", ""),
        "visibility": fields.pop("visibility", "visible"),
        "identifiability": fields.pop("identifiability", "clear"),
    }
    entity.update(fields)
    return entity


def _app(name, **fields):
    return {
        "name": name,
        "category": fields.pop("category", ""),
        "kind": fields.pop("kind", "application"),
        "role": fields.pop("role", "primary"),
        "theme": fields.pop("theme", ""),
        "visible_content": fields.pop("visible_content", ""),
        **fields,
    }


def _decide(query, record, conditions):
    return apply_facts_contracts(
        {
            "independent_conditions": [dict(row) for row in conditions],
            "reason": "",
        },
        query=query,
        record=record,
    )


def test_filter_keeps_only_query_named_conditions():
    item = filter_query_conditions(
        {
            "independent_conditions": [
                {"condition": "Google Chrome", "confirmed": True, "evidence": "window"},
                {"condition": "open application", "confirmed": False, "evidence": ""},
            ]
        },
        query="Google Chrome",
    )
    labels = [row["condition"] for row in item["independent_conditions"]]
    assert labels == ["Google Chrome"]
    assert "open application" in item["ignored_extra_conditions"]


def test_bare_chrome_matches_rendered_ui():
    record = _facts(
        scene_description="Google Chrome browser window open",
        ui_types=["browser window"],
        applications=[_app("Google Chrome", category="web browser", visible_content="browser window with tabs")],
    )
    result = _decide(
        "Google Chrome",
        record,
        [{"condition": "Google Chrome", "confirmed": True, "evidence": "browser window"}],
    )
    assert result["relevant"] is True


def test_bare_chrome_matches_icon_shortcut_or_nested():
    icon = _facts(entities=[_entity("Google Chrome", attributes=["taskbar icon"])])
    shortcut = _facts(entities=[_entity("Google Chrome", attributes=["desktop shortcut"])])
    nested = _facts(entities=[_entity("Google Chrome", kind="object", visibility="nested", attributes=["browser window"])])
    for record in (icon, shortcut, nested):
        result = _decide(
            "Google Chrome",
            record,
            [{"condition": "Google Chrome", "confirmed": False, "evidence": ""}],
        )
        assert result["relevant"] is True


def test_bare_chrome_rejects_weak_text_folder_or_false_friend():
    text = _facts(notable_text=["Chrome"])
    folder = _facts(entities=[_entity("Chrome", attributes=["folder name"])])
    false_friend = _facts(scene_description="window chrome around a dialog")
    for record in (text, folder, false_friend):
        result = _decide(
            "Google Chrome",
            record,
            [{"condition": "Google Chrome", "confirmed": True, "evidence": "Chrome"}],
        )
        assert result["relevant"] is False


def test_chrome_open_requires_rendered_interface():
    icon = _facts(entities=[_entity("Google Chrome", attributes=["taskbar icon"])])
    result = _decide(
        "Google Chrome open",
        icon,
        [
            {"condition": "Google Chrome", "confirmed": True, "evidence": "taskbar icon"},
            {"condition": "open", "confirmed": True, "evidence": "icon visible"},
        ],
    )
    assert result["relevant"] is False
    rendered = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        ui_types=["browser window"],
    )
    result = _decide(
        "Google Chrome open",
        rendered,
        [
            {"condition": "Google Chrome", "confirmed": True, "evidence": "window"},
            {"condition": "open", "confirmed": True, "evidence": "open"},
        ],
    )
    assert result["relevant"] is True


def test_chrome_icon_is_identity_bound():
    window = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        ui_types=["browser window"],
    )
    result = _decide(
        "Chrome icon",
        window,
        [{"condition": "Chrome icon", "confirmed": True, "evidence": "open Chrome window"}],
    )
    assert result["relevant"] is False
    icon = _facts(entities=[_entity("Google Chrome", attributes=["taskbar icon"])])
    result = _decide(
        "Chrome icon",
        icon,
        [{"condition": "Chrome icon", "confirmed": False, "evidence": ""}],
    )
    assert result["relevant"] is True


def test_chrome_icon_in_taskbar_is_same_target():
    other_icon = _facts(entities=[_entity("Google Chrome", attributes=["desktop shortcut"])])
    result = _decide(
        "Chrome icon in taskbar",
        other_icon,
        [
            {"condition": "Chrome icon", "confirmed": True, "evidence": "desktop shortcut"},
            {"condition": "taskbar", "confirmed": True, "evidence": "taskbar visible"},
        ],
    )
    assert result["relevant"] is False
    taskbar = _facts(entities=[_entity("Google Chrome", attributes=["taskbar icon"])])
    result = _decide(
        "Chrome icon in taskbar",
        taskbar,
        [
            {"condition": "Chrome icon", "confirmed": True, "evidence": "taskbar icon"},
            {"condition": "taskbar", "confirmed": True, "evidence": "taskbar"},
        ],
    )
    assert result["relevant"] is True


def test_bare_screenshot_manager_matches_branding_but_open_does_not():
    splash = _facts(
        environment="graphic splash branding",
        applications=[_app("Capixe", category="screenshot manager", visible_content="Capixe branding/splash")],
    )
    result = _decide(
        "screenshot manager",
        splash,
        [{"condition": "screenshot manager", "confirmed": True, "evidence": "branding/splash"}],
    )
    assert result["relevant"] is True
    result = _decide(
        "screenshot manager open",
        splash,
        [
            {"condition": "screenshot manager", "confirmed": True, "evidence": "branding"},
            {"condition": "open", "confirmed": True, "evidence": "splash"},
        ],
    )
    assert result["relevant"] is False


def test_real_screenshot_manager_ui_still_matches():
    record = _facts(
        scene_description="Capixe home screen",
        ui_types=["screenshot manager", "gallery"],
        applications=[_app("Capixe", category="screenshot manager", visible_content="home gallery thumbnails")],
    )
    result = _decide(
        "screenshot manager",
        record,
        [{"condition": "screenshot manager", "confirmed": True, "evidence": "home screen"}],
    )
    assert result["relevant"] is True


def test_button_is_not_workspace():
    record = _facts(
        entities=[_entity("Tags", attributes=["button", "quick action"])],
        notable_text=["Tags"],
        ui_types=["home"],
        applications=[_app("Capixe", visible_content="home gallery")],
    )
    result = _decide(
        "Tags panel open",
        record,
        [
            {"condition": "Tags panel", "confirmed": True, "evidence": "Tags button"},
            {"condition": "open", "confirmed": True, "evidence": "home open"},
        ],
    )
    assert result["relevant"] is False
    workspace = _facts(
        scene_description="Tags page workspace",
        ui_types=["screenshot manager"],
        applications=[_app("Capixe", visible_content="Tags page")],
        entities=[_entity("Tags", attributes=["page title"])],
    )
    result = _decide(
        "Tags panel open",
        workspace,
        [
            {"condition": "Tags panel", "confirmed": False, "evidence": ""},
            {"condition": "open", "confirmed": True, "evidence": "Tags page"},
        ],
    )
    assert result["relevant"] is True


def test_chrome_text_mention_is_not_an_open_window():
    window = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        notable_text=["ChatGPT"],
    )
    result = _decide(
        "Chrome text mention",
        window,
        [
            {"condition": "Chrome", "confirmed": True, "evidence": "Google Chrome window"},
            {"condition": "text mention", "confirmed": True, "evidence": "ChatGPT"},
        ],
    )
    assert result["relevant"] is False
    mention = _facts(notable_text=["#Chrome"], entities=[_entity("Chrome", attributes=["tag chip"])])
    result = _decide(
        "Chrome text mention",
        mention,
        [{"condition": "Chrome text mention", "confirmed": True, "evidence": "#Chrome"}],
    )
    assert result["relevant"] is True


def test_same_entity_color_and_posture():
    same = _facts(
        entities=[
            _entity(
                "dog",
                kind="animal",
                colors=["brown"],
                posture="sitting",
                observed_color_description="mostly brown",
            )
        ]
    )
    result = _decide(
        "brown sitting dog",
        same,
        [
            {"condition": "brown", "confirmed": True, "evidence": "brown"},
            {"condition": "sitting", "confirmed": True, "evidence": "sitting"},
            {"condition": "dog", "confirmed": True, "evidence": "dog"},
        ],
    )
    assert result["relevant"] is True
    split = _facts(
        entities=[
            _entity("dog", kind="animal", colors=["brown"], posture="standing", observed_color_description="mostly brown"),
            _entity("dog", kind="animal", colors=["white"], posture="sitting", observed_color_description="mostly white"),
        ]
    )
    result = _decide(
        "brown sitting dog",
        split,
        [
            {"condition": "brown", "confirmed": True, "evidence": "brown dog"},
            {"condition": "sitting", "confirmed": True, "evidence": "sitting dog"},
            {"condition": "dog", "confirmed": True, "evidence": "dog"},
        ],
    )
    assert result["relevant"] is False


def test_nested_content_matches_bare_entity():
    record = _facts(
        entities=[
            _entity("dog", kind="animal", visibility="nested", colors=["brown"], observed_color_description="mostly brown")
        ]
    )
    result = _decide(
        "dog",
        record,
        [{"condition": "dog", "confirmed": True, "evidence": "nested thumbnail"}],
    )
    assert result["relevant"] is True


def test_ask_ai_button_is_not_ask_ai_open():
    record = _facts(
        ui_types=["screenshot manager"],
        applications=[_app("Capixe", category="screenshot manager", visible_content="home gallery")],
        entities=[_entity("Ask AI", attributes=["button"])],
        notable_text=["Ask AI"],
    )
    result = _decide(
        "screenshot manager with Ask AI open",
        record,
        [
            {"condition": "screenshot manager", "confirmed": True, "evidence": "ui_types"},
            {"condition": "Ask AI open", "confirmed": True, "evidence": "notable_text Ask AI"},
            {"condition": "open", "confirmed": True, "evidence": "Capixe open"},
        ],
    )
    assert result["relevant"] is False
    panel = _facts(
        ui_types=["screenshot manager"],
        applications=[_app("Capixe", category="screenshot manager", visible_content="Ask AI side panel")],
        entities=[_entity("Ask AI", attributes=["side panel", "workspace"])],
        scene_description="Ask AI panel open",
    )
    result = _decide(
        "screenshot manager with Ask AI open",
        panel,
        [
            {"condition": "screenshot manager", "confirmed": True, "evidence": "ui_types"},
            {"condition": "Ask AI open", "confirmed": True, "evidence": "Ask AI side panel"},
            {"condition": "open", "confirmed": True, "evidence": "Capixe open"},
        ],
    )
    assert result["relevant"] is True


def test_chrome_images_wrapper_does_not_require_a_gallery():
    record = _facts(
        scene_description="Google Chrome open to a ChatGPT page",
        ui_types=["browser window", "Windows desktop environment"],
        applications=[
            _app("Google Chrome", category="web browser", visible_content="browser window with tabs and address bar"),
            _app("ChatGPT", kind="website", role="secondary", visible_content="conversation page"),
        ],
        entities=[_entity("Google Chrome", attributes=["browser window", "tab strip", "address bar"], states=["open"])],
        relationships=["ChatGPT is displayed inside Google Chrome"],
    )
    result = _decide(
        "google chrome images",
        record,
        [
            {"condition": "Google Chrome", "confirmed": True, "evidence": "browser window"},
            {"condition": "images", "confirmed": False, "evidence": "no Images page"},
        ],
    )
    assert "images" in result["ignored_extra_conditions"]
    assert result["relevant"] is True


def test_chrome_webpage_desktop_and_dialog_still_match_bare_chrome():
    webpage = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        entities=[_entity("Google Chrome", attributes=["tab strip", "address bar"])],
        ui_types=["browser window"],
    )
    desktop = _facts(
        environment="Windows desktop environment",
        ui_types=["Windows desktop environment", "browser window"],
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        entities=[_entity("Google Chrome", attributes=["browser window", "tab strip"])],
    )
    dialog = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with a modal dialog")],
        entities=[_entity("Google Chrome", attributes=["browser window", "tab strip"])],
        ui_types=["browser window"],
    )
    for record in (webpage, desktop, dialog):
        result = _decide(
            "Google Chrome",
            record,
            [{"condition": "Google Chrome", "confirmed": True, "evidence": "window"}],
        )
        assert result["relevant"] is True


def test_chrome_ui_at_top_counts_even_when_inner_content_is_primary():
    record = _facts(
        scene_description="A Windows desktop with Google Chrome open to ChatGPT",
        environment="Windows desktop environment",
        ui_types=["Windows desktop environment"],
        applications=[_app("ChatGPT", kind="website", role="primary", visible_content="conversation sidebar")],
        entities=[
            _entity(
                "Google Chrome",
                attributes=["browser window", "tab strip", "address bar"],
                states=["open"],
            )
        ],
    )
    result = _decide(
        "search for google chrome images from this folder",
        record,
        [
            {"condition": "Google Chrome", "confirmed": False, "evidence": ""},
            {"condition": "images", "confirmed": False, "evidence": ""},
            {"condition": "this folder", "confirmed": False, "evidence": ""},
        ],
    )
    assert result["relevant"] is True


def test_chrome_text_chip_is_not_chrome_identity():
    record = _facts(
        scene_description="Rounded text chips labeled Google Chrome next to related-images counts",
        ui_types=["browser window"],
        applications=[
            _app(
                "Google Chrome",
                category="web browser",
                visible_content="Repeated Google Chrome labels appear in rounded pills",
            )
        ],
        entities=[_entity("Google Chrome", attributes=["text chip", "label"])],
        notable_text=["Google Chrome", "Found 3 related images."],
    )
    result = _decide(
        "google chrome images",
        record,
        [
            {"condition": "Google Chrome", "confirmed": True, "evidence": "Google Chrome labels"},
            {"condition": "images", "confirmed": True, "evidence": "related-images page"},
        ],
    )
    assert result["relevant"] is False


def test_favorite_flag_does_not_change_chrome_relevance():
    record = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        ui_types=["browser window"],
    )
    conditions = [{"condition": "Google Chrome", "confirmed": True, "evidence": "window"}]
    plain = _decide("Google Chrome", record, conditions)
    starred = _decide("Google Chrome", {**record, "favorite": True}, conditions)
    assert plain["relevant"] is True
    assert starred["relevant"] is True
    assert "favorite" not in str(plain).lower() or plain["relevant"] == starred["relevant"]


def test_local_match_trace_is_local_only_and_ignores_favorite():
    from app.image_facts.debug import local_match_trace

    record = _facts(
        applications=[_app("Google Chrome", visible_content="browser window with tabs")],
        entities=[_entity("Google Chrome", attributes=["tab strip"])],
        ui_types=["browser window"],
    )
    trace = local_match_trace(
        query="google chrome images",
        record=record,
        conditions=[
            {"condition": "Google Chrome", "confirmed": True, "evidence": "window"},
            {"condition": "images", "confirmed": False, "evidence": ""},
        ],
        image_id=17,
        rank=33,
        similarity=0.25,
        shortlist_included=True,
        favorite=True,
    )
    assert trace["meaning_target"] == "google chrome"
    assert trace["shortlist_included"] is True
    assert trace["final_judge_result"] is True
    assert "images" in trace["ignored_extra_conditions"]
    assert "favorite" not in trace
