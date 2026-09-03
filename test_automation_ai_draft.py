"""AI Workflow Generation: natural language → validated builder blocks only."""
from __future__ import annotations

from app.automation.draft import adapt_plan_for_builder, draft_workflow_from_text
from app.i18n import t
from app.workspace.context import ORIGIN_BROWSE, ORIGIN_MEANING, ORIGIN_TEXT, SearchResultContext
from app.workspace.plan import STEP_ACTION, STEP_FIND, ActPlan, PlanStep


DOG_INSTRUCTION = (
    "Find all dog images in this folder, tag them DOG, and move them to the Animal folder."
)


def test_dog_example_builds_meaning_search_tag_and_move():
    outcome = draft_workflow_from_text(DOG_INSTRUCTION, SearchResultContext(), allow_ai=False)
    assert outcome.ok is True
    assert outcome.origin == ORIGIN_MEANING
    assert [step.type for step in outcome.steps] == [STEP_FIND, STEP_ACTION, STEP_ACTION]
    assert "dog" in outcome.steps[0].query.lower()
    assert "folder" not in outcome.steps[0].query.lower()
    assert outcome.steps[1].action_id == "add_tag"
    assert outcome.steps[1].parameters.get("tag") == "DOG"
    assert outcome.steps[2].action_id == "move"
    assert outcome.steps[2].parameters.get("destination_name") == "Animal"


def test_filename_search_uses_text_origin():
    outcome = draft_workflow_from_text(
        "Find images whose filename contains invoice and add tag bills",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is True
    assert outcome.origin == ORIGIN_TEXT
    assert outcome.steps[0].type == STEP_FIND
    assert "invoice" in outcome.steps[0].query.lower()
    assert outcome.steps[-1].action_id == "add_tag"
    assert outcome.steps[-1].parameters.get("tag") == "bills"


def test_all_images_plus_tag_keeps_browse_origin():
    outcome = draft_workflow_from_text(
        "tag all images as archive",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is True
    assert outcome.origin == ORIGIN_BROWSE
    assert [step.type for step in outcome.steps] == [STEP_ACTION]
    assert outcome.steps[0].action_id == "add_tag"
    assert outcome.steps[0].parameters.get("tag") == "archive"


def test_missing_tag_does_not_invent_a_name():
    outcome = draft_workflow_from_text(
        "find dogs and add a tag",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is False
    assert outcome.message_key == "automation.draft_missing_tag"
    assert "tag" in outcome.missing
    assert any(step.type == STEP_FIND for step in outcome.steps)
    assert not any(
        step.type == STEP_ACTION and str(step.parameters.get("tag") or "").strip()
        for step in outcome.steps
    )


def test_missing_destination_does_not_invent_a_folder():
    outcome = draft_workflow_from_text(
        "find dogs and move them",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is False
    assert "destination" in outcome.missing or outcome.message_key in {
        "automation.draft_missing_destination",
        "automation.draft_clarify",
        "automation.draft_need_act",
    }
    assert not any(
        step.action_id == "move" and str(step.parameters.get("destination_name") or "").strip()
        for step in outcome.steps
    )


def test_rename_and_delete_are_unsupported_not_mapped():
    renamed = draft_workflow_from_text(
        "find dogs and rename them to pet",
        SearchResultContext(),
        allow_ai=False,
    )
    assert renamed.ok is False
    assert renamed.apply_steps is False
    assert renamed.steps == ()
    assert renamed.message_key == "automation.draft_unsupported"
    assert "rename" in renamed.unsupported
    assert "Rename" in (renamed.message or t(renamed.message_key))
    assert not any(step.action_id == "rename" for step in renamed.steps)

    deleted = draft_workflow_from_text(
        "Delete all of these images.",
        SearchResultContext(),
        allow_ai=False,
    )
    assert deleted.ok is False
    assert deleted.apply_steps is False or not deleted.steps
    assert "delete" in deleted.reasons or deleted.message_key in {
        "automation.draft_unsupported",
        "images.ai.not_available_delete",
    }


def test_create_folder_only_is_unsupported():
    outcome = draft_workflow_from_text(
        "Create an Animal folder.",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is False
    assert outcome.apply_steps is False
    assert outcome.steps == ()
    assert "create_folder" in outcome.unsupported
    assert "Create Folder" in (outcome.message or t(outcome.message_key))
    assert not any(step.action_id == "create_folder" for step in outcome.steps)
    assert not any(step.action_id == "move" for step in outcome.steps)


def test_create_folder_and_move_builds_meaning_search_and_move():
    outcome = draft_workflow_from_text(
        "Create an Animal folder and move all dog images into it.",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is True
    assert outcome.apply_steps is True
    assert outcome.origin == ORIGIN_MEANING
    assert [step.type for step in outcome.steps] == [STEP_FIND, STEP_ACTION]
    assert "dog" in outcome.steps[0].query.lower()
    assert outcome.steps[1].action_id == "move"
    assert outcome.steps[1].parameters.get("destination_name") == "Animal"
    assert "create_folder" not in outcome.unsupported
    assert not any(step.action_id == "create_folder" for step in outcome.steps)

    named = draft_workflow_from_text(
        "Create a folder called Animal and move these images there.",
        SearchResultContext(),
        allow_ai=False,
    )
    assert named.ok is True
    assert named.apply_steps is True
    assert [step.action_id for step in named.steps if step.type == STEP_ACTION] == ["move"]
    assert named.steps[-1].parameters.get("destination_name") == "Animal"
    assert "create_folder" not in named.unsupported
    assert not any(step.action_id == "create_folder" for step in named.steps)


def test_move_to_existing_folder_builds_meaning_search_and_move():
    outcome = draft_workflow_from_text(
        "Move all dog images to the existing Animal folder.",
        SearchResultContext(),
        allow_ai=False,
    )
    assert outcome.ok is True
    assert outcome.apply_steps is True
    assert outcome.origin == ORIGIN_MEANING
    assert [step.type for step in outcome.steps] == [STEP_FIND, STEP_ACTION]
    assert "dog" in outcome.steps[0].query.lower()
    assert outcome.steps[1].action_id == "move"
    assert outcome.steps[1].parameters.get("destination_name") == "Animal"
    assert "create_folder" not in outcome.unsupported


UNPARSED = "please assemble a reusable canine workflow xyzzy"


def test_invalid_ai_schema_is_rejected_without_steps():
    outcome = draft_workflow_from_text(
        UNPARSED,
        SearchResultContext(),
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {"not": "a plan", "status": "explode"},
    )
    assert outcome.ok is False
    assert outcome.apply_steps is False
    assert outcome.steps == ()
    assert "invalid_schema" in outcome.reasons
    assert outcome.message_key == "automation.draft_invalid"


def test_ai_payload_with_unknown_action_is_not_applied_as_that_block():
    outcome = draft_workflow_from_text(
        "organize the dogs",
        SearchResultContext(),
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {
            "intent": "find_and_action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {"id": "s1", "type": "find", "query": "dog", "action_id": "", "target_source": "", "parameters": {}},
                {
                    "id": "s2",
                    "type": "action",
                    "query": "",
                    "action_id": "email",
                    "target_source": "result_set",
                    "parameters": {},
                },
            ],
        },
    )
    assert outcome.ok is False
    assert outcome.apply_steps is False
    assert outcome.steps == ()
    assert not any(step.action_id == "email" for step in outcome.steps)
    assert outcome.message_key == "automation.draft_unsupported"


def test_ai_shell_step_is_rejected():
    outcome = draft_workflow_from_text(
        UNPARSED,
        SearchResultContext(),
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {
            "intent": "action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {
                    "id": "s1",
                    "type": "shell",
                    "query": "",
                    "action_id": "move",
                    "target_source": "",
                    "parameters": {"sql": "drop"},
                }
            ],
        },
    )
    assert outcome.ok is False
    assert outcome.apply_steps is False
    assert outcome.steps == ()


def test_ai_valid_plan_is_adapted_to_builder_actions_only():
    outcome = draft_workflow_from_text(
        UNPARSED,
        SearchResultContext(),
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {
            "intent": "find_and_action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {"id": "s1", "type": "find", "query": "dog", "action_id": "", "target_source": "", "parameters": {}},
                {
                    "id": "s2",
                    "type": "action",
                    "query": "",
                    "action_id": "add_tag",
                    "target_source": "result_set",
                    "parameters": {"tag": "DOG"},
                },
                {
                    "id": "s3",
                    "type": "action",
                    "query": "",
                    "action_id": "move",
                    "target_source": "result_set",
                    "parameters": {"destination_name": "Animal"},
                },
            ],
        },
    )
    assert outcome.ok is True
    assert outcome.used_ai is True
    assert [step.action_id for step in outcome.steps if step.type == STEP_ACTION] == ["add_tag", "move"]


def test_ai_create_folder_and_move_becomes_move():
    outcome = draft_workflow_from_text(
        UNPARSED,
        SearchResultContext(),
        allow_ai=True,
        complete_json=lambda *_args, **_kwargs: {
            "intent": "find_and_action",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {"id": "s1", "type": "find", "query": "dog", "action_id": "", "target_source": "", "parameters": {}},
                {
                    "id": "s2",
                    "type": "action",
                    "query": "",
                    "action_id": "create_folder",
                    "target_source": "",
                    "parameters": {"name": "Animal"},
                },
                {
                    "id": "s3",
                    "type": "action",
                    "query": "",
                    "action_id": "move",
                    "target_source": "result_set",
                    "parameters": {"destination_ref": "s2"},
                },
            ],
        },
    )
    assert outcome.ok is True
    assert outcome.apply_steps is True
    assert [step.type for step in outcome.steps] == [STEP_FIND, STEP_ACTION]
    assert outcome.steps[0].query.lower() == "dog"
    assert outcome.steps[1].action_id == "move"
    assert outcome.steps[1].parameters.get("destination_name") == "Animal"
    assert "create_folder" not in outcome.unsupported
    assert not any(step.action_id == "create_folder" for step in outcome.steps)


def test_adapt_strips_forbidden_paths():
    plan = ActPlan(
        steps=(
            PlanStep(step_id="a", type=STEP_ACTION, action_id="move", parameters={"destination_path": "C:\\Evil"}),
        ),
        instruction="move them",
    )
    outcome = adapt_plan_for_builder(plan, "move them")
    assert outcome.ok is False
    assert not any("C:\\" in str(step.parameters) for step in outcome.steps)


def test_empty_instruction_asks_for_description():
    outcome = draft_workflow_from_text("  ", SearchResultContext(), allow_ai=True)
    assert outcome.ok is False
    assert outcome.message_key == "automation.draft_empty"
    assert t(outcome.message_key)
