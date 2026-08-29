"""Ask AI failure categories: auth, timeout, rate limit, schema, target, unsupported."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from app.ai_budget import AiBudgetExceeded
from app.ai_proxy.errors import AiProxyError, classify_ask_ai_failure
from app.i18n import t
from app.workspace import KIND_ACT, KIND_CLARIFY, SearchResultContext, route_ask_ai_turn

from test_ask_ai_meaning_search import (
    RecordingMeaningProvider,
    _open_and_send,
    _page,
)
from test_ask_ai_routing import _ai, _ctx, _png


def _remove_all_tags_payload():
    return {
        "intent": "action",
        "status": "plan",
        "clarify_message": "",
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "query": "",
                "action_id": "remove_all_tags",
                "target_source": "result_set",
                "parameters": {},
            }
        ],
    }


def test_planner_timeout_is_generic_unavailable_network(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        raise AiProxyError("provider_timeout")

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "error"
    assert t("images.ai.temporarily_unavailable") in result.status_text
    assert any(item.get("category") == "network" for item in logged)
    page.close()


def test_wrapped_401_budget_error_is_auth_card(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        raise AiBudgetExceeded(reason="not_authenticated", status=401)

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "auth"
    assert t("account.ai.session_expired") in result.status_text
    assert result.findChildren(QPushButton, "askAiSignInAction")
    assert any(item.get("category") == "auth" for item in logged)
    assert classify_ask_ai_failure(AiBudgetExceeded(reason="not_authenticated")) == "auth"
    page.close()


def test_usage_limit_is_limit_card_not_generic_error(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        raise AiBudgetExceeded(reason="limit_reached")

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "limit"
    assert t("account.ai.limit_reached") in result.status_text
    assert t("account.ai.limit_reached_body") in result.assistant_text
    assert t("images.ai.temporarily_unavailable") not in result.status_text
    assert t("images.ai.temporarily_unavailable") not in result.assistant_text
    assert "$" not in result.status_text
    assert any(item.get("category") == "budget" for item in logged)
    page.close()


def test_rate_limit_is_generic_unavailable(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        raise AiProxyError("provider_rate_limited", status=429)

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "error"
    assert t("images.ai.temporarily_unavailable") in result.status_text
    assert any(item.get("category") == "rate_limit" for item in logged)
    page.close()


def test_malformed_structured_output_is_schema_not_search(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        return "not-json"

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "clarify"
    assert t("images.ai.not_understood") in result.status_text
    assert t("images.ai.temporarily_unavailable") not in result.status_text
    assert any(item.get("category") == "schema" for item in logged)
    page.close()


def test_empty_planner_dict_is_schema_clarify_not_search():
    turn = route_ask_ai_turn("remove all tags from game images", complete_json=_ai({}))
    assert turn.kind == KIND_CLARIFY
    assert "invalid_schema" in turn.reasons
    assert turn.kind != "find"


def test_unsupported_action_is_not_generic_unavailable(tmp_path):
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)

    def complete(*_args, **_kwargs):
        return {
            "intent": "unsupported",
            "status": "clarify",
            "clarify_message": "",
            "steps": [],
        }

    page._act_plan_complete_json = complete
    _open_and_send(page, "Delete all of these images.", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "unsupported"
    assert t("images.ai.temporarily_unavailable") not in result.status_text
    page.close()


def test_missing_target_clarifies_instead_of_unavailable(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr("app.ui.pages.images_page.log_ask_ai_turn", lambda **kw: logged.append(kw))
    monkeypatch.setattr("app.ui.ask_ai_turn_task.log_ask_ai_turn", lambda **kw: logged.append(kw))
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)
    page._act_plan_complete_json = _ai(_remove_all_tags_payload())
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.card_kind == "clarify"
    assert t("images.ai.missing_target") in result.status_text
    assert t("images.ai.temporarily_unavailable") not in result.status_text
    assert any(item.get("category") == "validation" for item in logged)
    page.close()


def test_remove_all_tags_from_game_images_reaches_preview(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    image = folder / "notes.png"
    page._workspace.set_find(
        image_ids=(1,),
        paths=[str(image)],
        query="game images",
        scope_folder=folder,
        origin="meaning",
        path_to_image_id={str(image.resolve()): 1},
    )

    def complete(*_args, **_kwargs):
        return _remove_all_tags_payload()

    page._act_plan_complete_json = complete
    _open_and_send(page, "remove all tags from game images", wait=False)
    assert provider.calls == []
    confirm = page._ai_history.confirm_messages[-1]
    assert confirm.card_kind == "preview"
    assert confirm.pending is True
    page.close()


def test_remove_all_tags_stub_routes_to_act(tmp_path):
    image = _png(tmp_path / "game.png")
    turn = route_ask_ai_turn(
        "remove all tags from game images",
        _ctx(image, query="game images"),
        complete_json=_ai(_remove_all_tags_payload()),
    )
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    assert turn.proposal.action_id == "remove_all_tags"
    assert turn.kind != "find"


def test_missing_target_turn_is_clarify():
    from app.workspace.act import bind_action_proposal

    turn = route_ask_ai_turn(
        "remove all tags from game images",
        SearchResultContext(),
        complete_json=_ai(_remove_all_tags_payload()),
    )
    assert turn.kind == KIND_ACT
    assert turn.proposal is not None
    _proposal, resolution = bind_action_proposal(turn.proposal, SearchResultContext())
    assert resolution.ok is False
    assert resolution.message_key == "images.ai.missing_target"
    assert turn.kind != "find"
