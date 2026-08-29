"""Ask AI UI preview uses local replies and never starts Meaning Search."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.ask_ai_preview import (
    ASK_AI_PREVIEW_CONFIG_KEY,
    ASK_AI_PREVIEW_ENV,
    ask_ai_ui_preview_enabled,
    preview_reply_for,
    preview_result_paths,
)
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache
from conftest import install_ask_ai_test_planner
from test_ask_ai_consent import _ScriptedConsentDialog
from test_ask_ai_meaning_search import RecordingMeaningProvider, _wait_ask_ai
from test_ask_ai_semantic_index import RecordingIndexer


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _wait_preview(page, timeout=2000):
    elapsed = 0
    while elapsed < timeout:
        timer = page._ask_ai_preview_timer
        messages = page._ai_history.result_messages
        searching = bool(messages) and messages[-1].searching
        if timer is None and messages and not searching:
            return
        QTest.qWait(20)
        elapsed += 20
    assert page._ai_history.result_messages
    assert page._ai_history.result_messages[-1].searching is False


def _page(tmp_path: Path, provider, indexer=None, **config):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for name in ("github-home.png", "notes.png"):
        _png(folder / name)
    values = {
        "selected_folder": str(folder),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "developer_search_mode": "text",
        "ask_ai_external_processing_consented": False,
        ASK_AI_PREVIEW_CONFIG_KEY: True,
    }
    values.update(config)
    page = ImagesPage(
        values,
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=lambda *_args: (),
        semantic_search_provider=lambda *_args: (),
        vision_search_provider=provider,
        semantic_index_indexer=indexer,
    )
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    return page, folder


def test_preview_flag_reads_env_and_config(monkeypatch):
    monkeypatch.delenv(ASK_AI_PREVIEW_ENV, raising=False)
    assert ask_ai_ui_preview_enabled({}) is False
    assert ask_ai_ui_preview_enabled({ASK_AI_PREVIEW_CONFIG_KEY: True}) is True
    monkeypatch.setenv(ASK_AI_PREVIEW_ENV, "1")
    assert ask_ai_ui_preview_enabled({}) is True
    monkeypatch.setenv(ASK_AI_PREVIEW_ENV, "0")
    assert ask_ai_ui_preview_enabled({ASK_AI_PREVIEW_CONFIG_KEY: True}) is False


def test_preview_send_skips_api_indexer_and_consent(tmp_path, monkeypatch):
    indexer = RecordingIndexer()
    provider = RecordingMeaningProvider([])
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Rejected, []),
    )
    page, folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    assert page._ai_panel_expanded
    assert page._ask_ai_preview_hint.isVisible()
    page._action_input.setText("short")
    page._on_ask_ai_send()
    assert page._ai_history.result_messages[-1].searching is True
    _wait_preview(page)
    assert provider.calls == []
    assert indexer.starts == []
    assert page._ask_ai_search_tasks == {}
    result = page._ai_history.result_messages[-1]
    assert result.searching is False
    assert result.assistant_text == preview_reply_for("short").text
    assert page._ai_history.user_texts == ["short"]
    assert page._ask_ai_grid_active is False
    page.close()


def test_preview_supports_consecutive_long_and_error_replies(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    for text in ("hello", "long", "error"):
        page._action_input.setText(text)
        page._on_ask_ai_send()
        _wait_preview(page)
    assert provider.calls == []
    assert indexer.starts == []
    assert page._ai_history.user_texts == ["hello", "long", "error"]
    messages = page._ai_history.result_messages
    assert len(messages) == 3
    assert messages[0].assistant_text.startswith("Hi")
    assert len(messages[1].assistant_text) > 200
    assert t("images.ai.error") in messages[2].status_text
    page.close()


def test_normal_ask_ai_path_unchanged_when_preview_off(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, folder = _page(
        tmp_path,
        provider,
        indexer,
        **{
            ASK_AI_PREVIEW_CONFIG_KEY: False,
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
        },
    )
    provider.batches = [(folder / "notes.png",)]
    page._show_ai_panel()
    install_ask_ai_test_planner(page)
    assert page._ask_ai_preview_hint.isHidden()
    page._action_input.setText("Find images with dogs in them")
    page._on_ask_ai_send()
    _wait_ask_ai(page)
    assert provider.calls == ["images with dogs in them"]
    assert indexer.starts == [(folder.resolve(), True), (folder.resolve(), True)]
    page.close()


def test_preview_conversation_stays_short_and_local(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    turns = (
        "hello",
        "chrome screenshots",
        "only clear ones",
        "thanks",
    )
    for text in turns:
        page._action_input.setText(text)
        page._on_ask_ai_send()
        _wait_preview(page)
    assert provider.calls == []
    assert indexer.starts == []
    assert page._ai_history.user_texts == list(turns)
    replies = [message.assistant_text for message in page._ai_history.result_messages]
    assert len(replies) == 4
    assert replies[0].startswith("Hi") or replies[0].startswith("Hello")
    assert "Chrome" in replies[1]
    assert "clearly visible" in replies[2]
    assert 8 <= len(replies[3]) <= 180
    page.close()


def test_preview_reply_rules_cover_follow_up_without_api():
    hello = preview_reply_for("hello")
    chrome = preview_reply_for("chrome screenshots", history=["hello"])
    clear = preview_reply_for(
        "only clear ones", history=["hello", "chrome screenshots"]
    )
    dog = preview_reply_for("a dog")
    slow = preview_reply_for("slow")
    assert "looking for" in hello.text or "search" in hello.text.lower()
    assert "Chrome" in chrome.text
    assert "narrow" in clear.text.lower()
    assert "dog" in dog.text.lower()
    assert slow.delay_ms >= 800
    assert preview_reply_for("error").kind == "error"
    dog_results = preview_reply_for("dog")
    chrome_results = preview_reply_for("chrome")
    assert dog_results.kind == "results"
    assert chrome_results.kind == "results"
    files = [Path("a.png"), Path("b.png"), Path("c.png")]
    assert preview_result_paths(files, dog_results) == files[:2]
    assert preview_result_paths(files, chrome_results) == files[1:3]


def test_preview_start_menu_is_local_and_hides_after_conversation(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    menu = page._ai_history.start_menu
    assert menu.isVisible()
    heading = menu.findChild(QLabel, "askAiStartHeading")
    assert heading is not None
    assert heading.text() == t("images.ai.start.heading")
    rows = {row.action_id: row for row in menu.action_rows}
    assert rows["find"].isEnabled()
    assert rows["organize"].isVisible()
    assert rows["organize"].isEnabled() is False
    assert t("images.ai.start.organize.soon") in rows["organize"].accessibleName()
    rows["find"].click()
    assert provider.calls == []
    assert indexer.starts == []
    assert menu.isHidden()
    assert page._ai_history.result_messages[-1].assistant_text == t(
        "images.ai.start.find.prompt"
    )
    assert page._action_input.hasFocus()
    page.close()


def test_preview_help_start_action_stays_local(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    rows = {row.action_id: row for row in page._ai_history.start_menu.action_rows}
    rows["help"].click()
    assert provider.calls == []
    assert indexer.starts == []
    assert page._ask_ai_search_tasks == {}
    assert page._ai_history.start_menu.isHidden()
    assert t("images.ai.start.help.reply") == page._ai_history.result_messages[-1].assistant_text
    page.close()


def test_preview_mock_results_restore_without_api(tmp_path):
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, folder = _page(tmp_path, provider, indexer)
    page._show_ai_panel()
    page._action_input.setText("dog")
    page._on_ask_ai_send()
    _wait_preview(page)
    page._action_input.setText("chrome")
    page._on_ask_ai_send()
    _wait_preview(page)
    assert provider.calls == []
    assert indexer.starts == []
    first, second = page._ai_history.result_messages
    assert first.result_query == "dog"
    assert second.result_query == "chrome"
    assert first.result_count >= 1
    assert second.result_count >= 1
    dog_action = first.findChild(QPushButton, "askAiResultAction")
    chrome_action = second.findChild(QPushButton, "askAiResultAction")
    assert dog_action is not None and dog_action.isVisible()
    assert chrome_action is not None and chrome_action.isVisible()
    chrome_action.click()
    chrome_names = _grid_names_preview(page)
    dog_action.click()
    dog_names = _grid_names_preview(page)
    assert provider.calls == []
    assert dog_names
    if chrome_names != dog_names:
        assert chrome_names
    page.close()


def test_preview_result_restore_after_folder_change_stays_local(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    provider = RecordingMeaningProvider([])
    indexer = RecordingIndexer()
    page, folder = _page(tmp_path, provider, indexer)
    other = tmp_path / "Other"
    other.mkdir()
    _png(other / "other.png")
    page._show_ai_panel()
    page._action_input.setText("dog")
    page._on_ask_ai_send()
    _wait_preview(page)
    first = page._ai_history.result_messages[-1]
    dog_action = first.findChild(QPushButton, "askAiResultAction")
    assert dog_action is not None and dog_action.isVisible()
    original = _grid_names_preview(page)
    assert original
    page.open_folder(other)
    QApplication.instance().processEvents()
    assert _grid_names_preview(page) == ["other.png"]
    dog_action.click()
    QApplication.instance().processEvents()
    assert provider.calls == []
    assert indexer.starts == []
    assert _grid_names_preview(page) == original
    assert Path(page._config["selected_folder"]).resolve() == folder.resolve()
    page.close()


def _grid_names_preview(page):
    from conftest import gallery_image_items

    return [
        Path(item.data(Qt.UserRole)).name
        for item in gallery_image_items(page._list_widget)
    ]
