"""Ask AI send stays responsive and chat cards change with real processing."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from app.ai_proxy.errors import AiProxyError
from app.i18n import t
from app.ui.ask_ai_chat import AskAiChatView

from test_ask_ai_meaning_search import (
    RecordingMeaningProvider,
    _open_and_send,
    _page,
    _wait_ask_ai,
    _wait_planner,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_enter_shows_user_and_processing_before_planner_returns(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    started = time.perf_counter()

    def complete(_system, _user, **_kwargs):
        time.sleep(0.35)
        return {
            "intent": "search",
            "status": "plan",
            "clarify_message": "",
            "steps": [
                {
                    "id": "step_1",
                    "type": "find",
                    "query": "game images",
                    "action_id": "",
                    "target_source": "result_set",
                    "parameters": {},
                }
            ],
        }

    page._act_plan_complete_json = complete
    if not page._ai_panel_expanded:
        page._show_ai_panel()
    page._action_input.setText("Find game images")
    page._action_preview_btn.click()

    assert time.perf_counter() - started < 0.2
    assert page._ai_history.user_texts[-1] == "Find game images"
    assert page._action_input.text() == ""
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "processing"
    assert result.phase == "understanding"
    assert t("images.ai.understanding") in result.status_text
    assert page._action_preview_btn.isEnabled() is False
    page._action_input.setText("still typing")
    assert page._action_input.text() == "still typing"
    QTest.qWait(50)
    assert page._action_input.text() == "still typing"
    _wait_ask_ai(page, timeout=4000)
    assert page._ai_history.result_messages[-1].card_kind == "result"
    page.close()


def test_planner_error_reuses_processing_card(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)

    def complete(_system, _user, **_kwargs):
        raise AiProxyError("provider_unavailable")

    page._act_plan_complete_json = complete
    _open_and_send(page, "Find images with dogs in them", wait=False)
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "error"
    assert t("images.ai.temporarily_unavailable") in result.status_text
    assert len(page._ai_history.result_messages) == 1
    page.close()


def test_auth_error_becomes_auth_card_without_search_fallback(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)

    def complete(_system, _user, **_kwargs):
        raise AiProxyError("unauthenticated", status=401)

    page._act_plan_complete_json = complete
    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "auth"
    assert t("account.ai.session_expired") in result.status_text
    assert result.findChildren(QPushButton, "askAiSignInAction")
    page.close()


def test_search_result_card_and_action_preview_states(tmp_path):
    folder = tmp_path / "Selected"
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "result"
    assert t("images.ai.found_one") in result.status_text
    assert "dogs" in result.result_query.lower() or "images with dogs" in result.result_query.lower()

    _open_and_send(page, "add favorite to these images")
    confirm = page._ai_history.confirm_messages[-1]
    assert confirm.card_kind == "preview"
    assert confirm.pending is True
    confirm._cancel_btn.click()
    assert confirm.card_kind == "cancelled"
    page.close()


def test_search_images_chip_sends_through_existing_path(tmp_path):
    """Clarify 'Search images' fills a Find follow-up and uses the Send path."""
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "valorant")
    clarify = page._ai_history.result_messages[-1]
    assert clarify.card_kind == "clarify"
    chips = clarify.findChildren(QPushButton, "askAiClarifyChip")
    search = next(chip for chip in chips if chip.text() == t("images.ai.clarify_chip_search"))
    search.click()
    _wait_ask_ai(page)
    assert provider.calls
    page.close()


def test_unsupported_and_clarify_cards(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)

    calls = []

    def complete(_system, _user, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            return {
                "intent": "unsupported",
                "status": "clarify",
                "clarify_message": "",
                "steps": [],
            }
        return {
            "intent": "clarify",
            "status": "clarify",
            "clarify_message": 'What would you like me to do with “valorant”?',
            "steps": [],
        }

    page._act_plan_complete_json = complete
    _open_and_send(page, "Delete all of these images.", wait=False)
    unsupported = page._ai_history.result_messages[-1]
    assert unsupported.card_kind in {"unsupported", "error", "text"}
    _open_and_send(page, "valorant", wait=False)
    clarify = page._ai_history.result_messages[-1]
    assert clarify.card_kind == "clarify"
    chips = clarify.findChildren(QPushButton, "askAiClarifyChip")
    assert chips
    page.close()


def test_many_cards_keep_input_responsive():
    app = _app()
    view = AskAiChatView()
    view.show()
    app.processEvents()
    for index in range(40):
        view.add_user_message(f"turn {index}")
        result = view.add_result_message(index, query=f"q{index}")
        result.complete([], t("images.ai.found", count=0))
    app.processEvents()
    view.add_user_message("latest")
    assert view.user_texts[-1] == "latest"
    view.scroll_to_bottom()
    QTest.qWait(20)
    view.close()


def test_confirm_card_executing_then_complete():
    app = _app()
    view = AskAiChatView()
    confirm = view.add_confirm_message()
    confirm.set_preview("Remove all tags", "7 images", "Confirm")
    assert confirm.card_kind == "preview"
    confirm.set_executing(t("images.ai.updating_count", count=7))
    assert confirm.card_kind == "executing"
    assert confirm._confirm_btn.isEnabled() is False
    confirm.complete(t("images.ai.act_done_remove_all_tags", count=6), detail=t("images.ai.act_no_tags_note", count=1))
    assert confirm.card_kind == "complete"
    confirm2 = view.add_confirm_message()
    confirm2.set_preview("Move images", "5 images", "Confirm")
    confirm2.complete(t("images.ai.act_done_move_partial", changed=4, requested=5, failed=1), warning=True)
    assert confirm2.card_kind == "warning"
    view.close()


def test_chat_bubbles_are_wide_and_user_color_differs():
    from app.ui.ask_ai_chat import ASK_AI_ASSISTANT_BUBBLE_RATIO, ASK_AI_USER_BUBBLE_RATIO
    from app.ui.design_tokens import COLORS

    assert COLORS.chat_user_bg.lower() != COLORS.chat_assistant_bg.lower()
    app = _app()
    view = AskAiChatView()
    view.resize(320, 480)
    view.show()
    app.processEvents()
    text = "find screenshots of the login dialog and tag the matches as work"
    user = view.add_user_message(text)
    result = view.add_result_message(1, query=text)
    app.processEvents()
    view_width = view.viewport().width()
    assert user.maximumWidth() >= int(view_width * ASK_AI_USER_BUBBLE_RATIO) - 1
    assert result.minimumWidth() >= int(view_width * ASK_AI_ASSISTANT_BUBBLE_RATIO) - 1
    assert user.objectName() == "askAiUserMessage"
    assert result.objectName() == "askAiResultMessage"
    view.close()

