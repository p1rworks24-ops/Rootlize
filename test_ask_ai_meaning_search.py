"""Ask AI send uses existing Meaning Search and shows image results in the main grid."""

from __future__ import annotations

from pathlib import Path
import shutil
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QPushButton

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.images_search import (
    VisionRelevanceImagesSearchProvider,
    create_meaning_search_provider,
)
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items, install_ask_ai_test_planner


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _wait_planner(page, timeout=4000):
    elapsed = 0
    while elapsed < timeout:
        busy = bool(getattr(page, "_ask_ai_turn_busy", False))
        turns = bool(getattr(page, "_ask_ai_turn_tasks", None))
        if not busy and not turns:
            break
        QTest.qWait(20)
        elapsed += 20
    QTest.qWait(20)
    assert not getattr(page, "_ask_ai_turn_busy", False)
    assert not getattr(page, "_ask_ai_turn_tasks", {})


def _wait_ask_ai(page, timeout=4000):
    elapsed = 0
    while elapsed < timeout:
        busy = bool(getattr(page, "_ask_ai_turn_busy", False))
        turns = bool(getattr(page, "_ask_ai_turn_tasks", None))
        searches = bool(getattr(page, "_ask_ai_search_tasks", None))
        executing = bool(getattr(page, "_action_executing", False))
        if not busy and not turns and not searches and not executing:
            break
        QTest.qWait(20)
        elapsed += 20
    QTest.qWait(20)
    assert not getattr(page, "_ask_ai_turn_busy", False)
    assert not getattr(page, "_ask_ai_turn_tasks", {})
    assert not page._ask_ai_search_tasks
    assert not getattr(page, "_action_executing", False)


def _grid_names(page):
    return [
        Path(item.data(Qt.UserRole)).name
        for item in gallery_image_items(page._list_widget)
    ]


def _wait_search(page, timeout=3000):
    elapsed = 0
    while page._search_tasks and elapsed < timeout:
        QTest.qWait(20)
        elapsed += 20
    assert not page._search_tasks


class RecordingMeaningProvider:
    def __init__(self, batches: list[tuple[Path, ...]]):
        self.batches = list(batches)
        self.calls: list[str] = []
        self.gate = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def search_progressive(
        self, query, folder, candidates, *, on_progress=None, cancelled=None
    ):
        self.calls.append(query)
        visible: list[Path] = []
        total = sum(len(batch) for batch in self.batches) or 1
        checked = 0
        for index, batch in enumerate(self.batches):
            if cancelled is not None and cancelled():
                break
            visible.extend(batch)
            checked += len(batch)
            if on_progress is not None:
                on_progress(tuple(visible), checked, total)
            if index == 0:
                self.gate.set()
                self.release.wait(2)
                if cancelled is not None and cancelled():
                    break
        return tuple(visible)


def _page(tmp_path: Path, provider, *, mode: str = "text"):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for name in ("github-home.png", "github-issue.png", "notes.png"):
        _png(folder / name)
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "developer_search_mode": mode,
            "ask_ai_external_processing_consented": True,
            "ask_ai_consent_notice_version": 2,
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=lambda *_args: (),
        semantic_search_provider=lambda *_args: (),
        vision_search_provider=provider,
    )
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    install_ask_ai_test_planner(page)
    return page, folder


def _open_and_send(page, text: str, *, wait=True):
    if not page._ai_panel_expanded:
        page._show_ai_panel()
    page._action_input.setText(text)
    page._action_preview_btn.click()
    if wait:
        _wait_ask_ai(page)
    else:
        _wait_planner(page)


def test_create_meaning_search_provider_is_existing_engine():
    provider = create_meaning_search_provider()
    assert isinstance(provider, VisionRelevanceImagesSearchProvider)


def test_ask_ai_send_calls_meaning_search_and_shows_images(tmp_path):
    folder = tmp_path / "Selected"
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [
        (folder / "github-home.png", folder / "github-issue.png", folder / "notes.png"),
    ]

    _open_and_send(page, "Find images with dogs in them")

    assert provider.calls == ["images with dogs in them"]
    assert page._ai_history.user_texts == ["Find images with dogs in them"]
    result = page._ai_history.result_messages[-1]
    assert [path.name for path in result.paths] == [
        "github-home.png", "github-issue.png", "notes.png",
    ]
    assert result.searching is False
    assert result.findChildren(QLabel, "askAiResultThumb") == []
    assert result.findChildren(QLabel, "askAiRole") == []
    assert t("images.ai.found", count=3) in result.status_text
    assert _grid_names(page) == [
        "github-home.png", "github-issue.png", "notes.png",
    ]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=3
    )
    user = page._ai_history._user_messages[-1]
    assert user.parentWidget().objectName() == "askAiUserRow"
    assert result.parentWidget().objectName() == "askAiAssistantRow"
    page.close()


def test_ask_ai_results_clear_on_tools_bar_restores_folder(tmp_path):
    folder = tmp_path / "Selected"
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    assert page._ai_results_clear_btn.isHidden()
    _open_and_send(page, "Find images with dogs in them")
    assert page._ask_ai_grid_active is True
    assert page._ai_results_clear_btn.isVisible()
    assert page._ai_results_clear_btn.parentWidget() is page._header_tools
    assert _grid_names(page) == ["notes.png"]
    page._ai_results_clear_btn.click()
    QTest.qWait(40)
    assert page._ask_ai_grid_active is False
    assert page._ai_results_clear_btn.isHidden()
    assert set(_grid_names(page)) == {
        "github-home.png",
        "github-issue.png",
        "notes.png",
    }
    page.close()


def test_ask_ai_enter_sends_query(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._show_ai_panel()
    page._action_input.setText("Find Windows settings screen")
    QTest.keyClick(page._action_input, Qt.Key_Return)
    _wait_ask_ai(page)
    assert provider.calls == ["Windows settings screen"]
    assert page._ai_history.user_texts == ["Find Windows settings screen"]
    page.close()


def test_progressive_results_then_complete(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    first = (folder / "github-home.png",)
    second = (folder / "github-home.png", folder / "github-issue.png")
    provider.batches = [first, (folder / "github-issue.png",)]
    provider.release.clear()
    _open_and_send(page, "犬の画像を探して", wait=False)
    assert provider.gate.wait(2)
    QTest.qWait(50)
    result = page._ai_history.result_messages[-1]
    assert [path.name for path in result.paths] == ["github-home.png"]
    assert result.searching is True
    assert t("images.searching").rstrip("…") in result.status_text or "Searching" in result.status_text
    assert _grid_names(page) == ["github-home.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_searching", query="犬の画像"
    )
    provider.release.set()
    _wait_ask_ai(page)
    assert [path.name for path in result.paths] == ["github-home.png", "github-issue.png"]
    assert result.searching is False
    assert _grid_names(page) == ["github-home.png", "github-issue.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="犬の画像", count=2
    )
    page.close()


def test_close_and_requery_ignore_stale_results(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [
        (folder / "github-home.png",),
        (folder / "notes.png",),
    ]
    provider.release.clear()
    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert provider.gate.wait(2)
    QTest.qWait(50)
    first = page._ai_history.result_messages[-1]
    assert [path.name for path in first.paths] == ["github-home.png"]

    page._show_preview_panel()
    provider.release.set()
    _wait_ask_ai(page)
    assert [path.name for path in first.paths] == ["github-home.png"]
    assert first.frozen is True
    assert _grid_names(page) == ["github-home.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=1
    )

    provider.batches = [(folder / "github-issue.png",)]
    provider.gate = threading.Event()
    provider.release = threading.Event()
    provider.release.set()
    _open_and_send(page, "Find images with cats in them")
    second = page._ai_history.result_messages[-1]
    assert page._ai_history.user_texts == ["Find images with dogs in them", "Find images with cats in them"]
    assert [path.name for path in second.paths] == ["github-issue.png"]
    assert [path.name for path in first.paths] == ["github-home.png"]
    assert _grid_names(page) == ["github-issue.png"]
    page.close()


def test_new_query_does_not_mix_old_batches(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [
        (folder / "github-home.png",),
        (folder / "notes.png",),
    ]
    provider.release.clear()
    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert provider.gate.wait(2)
    QTest.qWait(50)

    second_provider_release = provider.release
    provider.batches = [(folder / "github-issue.png",)]
    provider.gate = threading.Event()
    provider.release = threading.Event()
    provider.release.set()
    page._action_input.setText("Find images with cats in them")
    page._action_preview_btn.click()
    second_provider_release.set()
    _wait_ask_ai(page)

    first, second = page._ai_history.result_messages
    assert [path.name for path in first.paths] == ["github-home.png"]
    assert [path.name for path in second.paths] == ["github-issue.png"]
    assert "notes.png" not in [path.name for path in first.paths]
    page.close()


def test_search_bar_dog_does_not_call_ask_ai_planner(tmp_path, monkeypatch):
    calls = []
    planner = []

    def text_search(query, folder, candidates):
        calls.append(query)
        return (folder / "notes.png",)

    monkeypatch.setattr(
        "app.ui.pages.images_page.search_indexed_images", text_search
    )
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, mode="text")
    original = page._act_plan_complete_json

    def wrapped(*args, **kwargs):
        planner.append(1)
        return original(*args, **kwargs)

    page._act_plan_complete_json = wrapped
    page._search_input.setText("dog")
    page._on_search()
    _wait_search(page)
    assert calls == ["dog"]
    assert planner == []
    assert provider.calls == []
    page.close()


def test_folder_and_account_change_clear_planner_conversation(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    page.note_ask_ai_account("user-a")
    page._ask_ai_planner_response_id = "resp_keep"
    page._workspace.set_find(
        image_ids=(1,),
        paths=["kept.png"],
        query="dogs",
        scope_folder=folder,
        origin="meaning",
    )
    page.note_ask_ai_account("user-a")
    assert page._ask_ai_planner_response_id == "resp_keep"
    assert page._workspace.context.has_result_set()
    page.note_ask_ai_account("user-b")
    assert page._ask_ai_planner_response_id == ""
    assert not page._workspace.context.has_result_set()
    page._ask_ai_planner_response_id = "resp_keep"
    page.note_ask_ai_account("")
    assert page._ask_ai_planner_response_id == ""
    page._ask_ai_planner_response_id = "resp_keep"
    other = tmp_path / "Other"
    other.mkdir()
    page.open_folder(other)
    assert page._ask_ai_planner_response_id == ""
    page.close()


def test_text_search_stays_on_search_bar(tmp_path, monkeypatch):
    calls = []

    def text_search(query, folder, candidates):
        calls.append(query)
        return (folder / "notes.png",)

    monkeypatch.setattr(
        "app.ui.pages.images_page.search_indexed_images", text_search
    )
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, mode="text")
    provider.batches = [(folder / "github-home.png",)]

    page._search_input.setText("notes")
    page._on_search()
    _wait_search(page)
    assert calls == ["notes"]
    visible = [Path(item.data(Qt.UserRole)).name for item in gallery_image_items(page._list_widget)]
    assert visible == ["notes.png"]

    _open_and_send(page, "Find images with dogs in them")
    assert provider.calls == ["images with dogs in them"]
    assert calls == ["notes"]
    assert _grid_names(page) == ["github-home.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=1
    )
    assert [path.name for path in page._ai_history.result_messages[-1].paths] == [
        "github-home.png"
    ]
    page.close()


def test_start_menu_hides_organize_in_production(tmp_path):
    provider = RecordingMeaningProvider([])
    page, _folder = _page(tmp_path, provider)
    page._show_ai_panel()
    menu = page._ai_history.start_menu
    assert menu.isVisible()
    heading = menu.findChild(QLabel, "askAiStartHeading")
    assert heading is not None
    assert heading.text() == t("images.ai.start.heading")
    rows = {row.action_id: row for row in menu.action_rows}
    assert rows["find"].isVisible()
    assert rows["help"].isVisible()
    assert rows["organize"].isHidden()
    assert rows["find"].isEnabled()
    rows["find"].click()
    assert provider.calls == []
    assert page._ask_ai_search_tasks == {}
    assert menu.isHidden()
    page.close()


def test_result_action_restores_each_message_without_research(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    dog_batch = (folder / "github-home.png", folder / "github-issue.png")
    cat_batch = (folder / "notes.png",)
    provider.batches = [dog_batch]
    _open_and_send(page, "Find images with dogs in them")
    provider.batches = [cat_batch]
    _open_and_send(page, "Find images with cats in them")
    assert provider.calls == ["images with dogs in them", "images with cats in them"]
    first, second = page._ai_history.result_messages
    assert first.result_query == "images with dogs in them"
    assert second.result_query == "images with cats in them"
    assert [path.name for path in first.paths] == [
        "github-home.png",
        "github-issue.png",
    ]
    assert [path.name for path in second.paths] == ["notes.png"]
    assert first.result_count == 2
    assert second.result_count == 1
    dog_action = first.findChild(QPushButton, "askAiResultAction")
    cat_action = second.findChild(QPushButton, "askAiResultAction")
    assert dog_action is not None
    assert cat_action is not None
    assert t("images.ai.result_action", count=2) == dog_action.text()
    assert t("images.ai.result_action", count=1) == cat_action.text()
    assert _grid_names(page) == ["notes.png"]
    dog_action.click()
    assert provider.calls == ["images with dogs in them", "images with cats in them"]
    assert _grid_names(page) == ["github-home.png", "github-issue.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=2
    )
    cat_action.click()
    assert provider.calls == ["images with dogs in them", "images with cats in them"]
    assert _grid_names(page) == ["notes.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with cats in them", count=1
    )
    page.close()


def test_result_restore_skips_missing_files(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [
        (folder / "github-home.png", folder / "notes.png"),
    ]
    _open_and_send(page, "Find images with dogs in them")
    result = page._ai_history.result_messages[-1]
    (folder / "notes.png").unlink()
    action = result.findChild(QPushButton, "askAiResultAction")
    action.click()
    assert provider.calls == ["images with dogs in them"]
    assert _grid_names(page) == ["github-home.png"]
    assert [path.name for path in result.paths] == ["github-home.png", "notes.png"]
    page.close()


def test_result_restore_returns_to_source_folder_without_research(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    other = tmp_path / "Other"
    other.mkdir()
    _png(other / "other.png")
    provider.batches = [
        (folder / "github-home.png", folder / "github-issue.png"),
    ]
    _open_and_send(page, "Find images with dogs in them")
    assert _grid_names(page) == ["github-home.png", "github-issue.png"]
    page.open_folder(other)
    QApplication.instance().processEvents()
    assert _grid_names(page) == ["other.png"]
    result = page._ai_history.result_messages[-1]
    action = result.findChild(QPushButton, "askAiResultAction")
    action.click()
    QApplication.instance().processEvents()
    assert provider.calls == ["images with dogs in them"]
    assert _grid_names(page) == ["github-home.png", "github-issue.png"]
    assert Path(page._config["selected_folder"]).resolve() == folder.resolve()
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=2
    )
    page.close()


def test_result_restore_follows_moved_image_to_current_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    archived = folder / "Archived"
    archived.mkdir()
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    shutil.move(str(folder / "notes.png"), str(archived / "notes.png"))
    result = page._ai_history.result_messages[-1]
    action = result.findChild(QPushButton, "askAiResultAction")
    action.click()
    QApplication.instance().processEvents()
    assert provider.calls == ["images with dogs in them"]
    assert Path(page._config["selected_folder"]).resolve() == archived.resolve()
    assert _grid_names(page) == ["notes.png"]
    assert [path.name for path in result.paths] == ["notes.png"]
    page.close()


def test_result_restore_all_missing_shows_not_found(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [
        (folder / "github-home.png", folder / "notes.png"),
    ]
    _open_and_send(page, "Find images with dogs in them")
    result = page._ai_history.result_messages[-1]
    for path in result.paths:
        Path(path).unlink()
    action = result.findChild(QPushButton, "askAiResultAction")
    action.click()
    assert provider.calls == ["images with dogs in them"]
    assert _grid_names(page) == []
    assert page._list_empty_title.text() == t("images.ai.no_matches")
    page.close()
