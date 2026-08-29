"""Pytest defaults: never write Capixe user data into the real APPDATA/Pictures."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.config import reset_migration_flag_for_tests
from app.paths import clear_path_overrides, set_path_overrides
from app.ui.caption_delegate import ITEM_KIND_IMAGE, ITEM_KIND_ROLE


def gallery_image_items(list_widget):
    """Image rows only (date/tag group headers are skipped)."""
    items = []
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item is not None and item.data(ITEM_KIND_ROLE) == ITEM_KIND_IMAGE:
            items.append(item)
    return items


@pytest.fixture(autouse=True)
def _capixe_isolate_user_dirs(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("capixe_user_data")
    set_path_overrides(
        app_data_dir=base / "AppData" / "Capixe",
        local_app_data_dir=base / "LocalAppData" / "Capixe",
        default_screenshot_root=base / "Pictures" / "Capixe",
        # Leave legacy/resource unset so tests that pass their own app_root
        # still control relative screenshot resolution via MainWindow overrides.
    )
    reset_migration_flag_for_tests()
    yield
    from app.semantic.bundle import clear_bundle_validation_cache
    from app.semantic.installer import reset_product_bundle_warmup_for_tests

    clear_bundle_validation_cache()
    reset_product_bundle_warmup_for_tests()
    clear_path_overrides()
    reset_migration_flag_for_tests()


@pytest.fixture(autouse=True)
def _capixe_reset_ai_budget_gate():
    from app.ai_budget import reset_ai_budget_gate_for_tests

    reset_ai_budget_gate_for_tests()
    yield
    reset_ai_budget_gate_for_tests()


@pytest.fixture(autouse=True)
def _capixe_isolate_auth(monkeypatch):
    """Never read/write the real Windows Credential Manager during tests."""
    from app.auth.credentials import MemoryCredentialStore

    store = MemoryCredentialStore()
    monkeypatch.setattr("app.auth.credentials.default_credential_store", lambda: store)
    monkeypatch.setattr("app.auth.service.default_credential_store", lambda: store)


@pytest.fixture(autouse=True)
def _capixe_cleanup_qt_state():
    """Release Qt clipboard data and top-level widgets created by each test."""
    yield

    app = QApplication.instance()
    if app is None:
        return

    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.clear()

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()

    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def install_ask_ai_test_planner(page):
    """Product Ask AI always calls the Planner. UI tests stub it with the local parser."""
    from app.i18n import t
    from app.workspace.intent import (
        KIND_ACT,
        KIND_CLARIFY,
        KIND_FIND,
        KIND_HELP,
        KIND_NARROW,
        KIND_QUESTION,
        KIND_UNSUPPORTED,
        classify_ask_ai_turn,
    )
    from app.workspace.plan import PLAN_STATUS_PLAN, STEP_ACTION, STEP_FIND, STEP_NARROW
    from app.workspace.planner import try_local_act_plan

    def complete(_system_prompt: str, user_prompt: str, **_kwargs) -> dict:
        instruction = _extract_user_request(user_prompt)
        ctx = page._workspace.context
        outcome = try_local_act_plan(instruction, ctx)
        if outcome is not None and outcome.status == PLAN_STATUS_PLAN and outcome.plan is not None:
            return _plan_to_planner_payload(outcome.plan)
        turn = classify_ask_ai_turn(instruction, ctx)
        if turn.kind == KIND_FIND:
            return _search_payload(turn.query, "find")
        if turn.kind == KIND_NARROW:
            return _search_payload(turn.query, "narrow", turn.target_source)
        if turn.kind == KIND_ACT and turn.proposal is not None:
            return {
                "intent": "action",
                "status": "plan",
                "clarify_message": "",
                "steps": [
                    {
                        "id": "step_1",
                        "type": STEP_ACTION,
                        "query": "",
                        "action_id": turn.proposal.action_id,
                        "target_source": turn.proposal.target_source,
                        "parameters": dict(turn.proposal.parameters),
                    }
                ],
            }
        if turn.kind == KIND_HELP:
            return {"intent": "help", "status": "clarify", "clarify_message": "", "steps": []}
        if turn.kind == KIND_QUESTION:
            return {
                "intent": "question",
                "status": "clarify",
                "clarify_message": turn.message or t(turn.message_key or "images.ai.question_not_search"),
                "steps": [],
            }
        if turn.kind == KIND_UNSUPPORTED:
            return {
                "intent": "unsupported",
                "status": "clarify",
                "clarify_message": turn.message or t(turn.message_key or "images.ai.not_available"),
                "steps": [],
            }
        message = turn.message or (t(turn.message_key) if turn.message_key else "")
        return {
            "intent": "clarify" if turn.kind == KIND_CLARIFY else "clarify",
            "status": "clarify",
            "clarify_message": message,
            "steps": [],
        }

    page._act_plan_complete_json = complete
    return page


def _extract_user_request(user_prompt: str) -> str:
    marker = "user_request: "
    for line in str(user_prompt or "").splitlines():
        if line.startswith(marker):
            return line[len(marker):].strip()
    return str(user_prompt or "").strip()


def _search_payload(query: str, step_type: str, target_source: str = "folder") -> dict:
    intent = "narrow" if str(step_type).lower() == "narrow" else "search"
    return {
        "intent": intent,
        "status": "plan",
        "clarify_message": "",
        "steps": [
            {
                "id": "step_1",
                "type": "narrow" if intent == "narrow" else "find",
                "query": query,
                "action_id": "",
                "target_source": target_source,
                "parameters": {},
            }
        ],
    }


def _plan_to_planner_payload(plan) -> dict:
    from app.workspace.plan import STEP_ACTION, STEP_FIND, STEP_NARROW

    has_search = bool(plan.search_steps())
    has_action = bool(plan.action_steps())
    if has_search and has_action:
        intent = "find_and_action"
    elif has_action:
        intent = "action"
    elif has_search:
        first = plan.search_steps()[0]
        intent = "narrow" if first.type == STEP_NARROW else "search"
    else:
        intent = "clarify"
    steps = []
    for step in plan.steps:
        steps.append(
            {
                "id": step.step_id,
                "type": step.type,
                "query": step.query,
                "action_id": step.action_id,
                "target_source": step.target_source,
                "parameters": dict(step.parameters),
            }
        )
    return {
        "intent": intent,
        "status": "plan" if steps else "clarify",
        "clarify_message": "",
        "steps": steps,
    }
