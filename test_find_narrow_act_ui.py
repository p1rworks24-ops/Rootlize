"""Find → Narrow → Act uses one workspace result set and the shared Action layer."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache
from app.workspace import SOURCE_SELECTION

from conftest import gallery_image_items, install_ask_ai_test_planner


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


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


class ScriptedMeaningProvider:
    def __init__(self, by_query: dict[str, tuple[Path, ...]]):
        self.by_query = dict(by_query)
        self.calls: list[dict] = []

    def search_progressive(self, query, folder, candidates, **kwargs):
        allowed = {str(Path(path).resolve()) for path, _tags in candidates}
        self.calls.append(
            {
                "query": query,
                "candidates": tuple(sorted(Path(path).name for path, _tags in candidates)),
                "scope_image_ids": kwargs.get("scope_image_ids"),
            }
        )
        hits = self.by_query.get(query, ())
        return tuple(
            path for path in hits if not allowed or str(path.resolve()) in allowed
        )


def _page(tmp_path: Path, provider):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for name in ("day-dog.png", "night-dog.png", "cat.png", "settings.png"):
        _png(folder / name)
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
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


def _send(page, text: str):
    if not page._ai_panel_expanded:
        page._show_ai_panel()
    page._action_input.setText(text)
    page._action_preview_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(20)


def _select_named(page, *names: str):
    page._list_widget.clearSelection()
    for item in gallery_image_items(page._list_widget):
        if Path(item.data(Qt.UserRole)).name in names:
            item.setSelected(True)
    page._on_selection_changed()


def test_find_then_narrow_reuses_result_set(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    settings = folder / "settings.png"
    provider = ScriptedMeaningProvider(
        {
            "dog": (day, night, cat),
            "夜に撮られたもの": (night,),
        }
    )
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    assert provider.calls[0]["query"] == "dog"
    assert page._workspace.context.result_paths
    assert not page._workspace.context.narrowed
    assert _grid_names(page) == ["day-dog.png", "night-dog.png", "cat.png"]

    _send(page, "その中で夜に撮られたもの")
    assert provider.calls[1]["query"] == "夜に撮られたもの"
    assert set(provider.calls[1]["candidates"]) <= {"day-dog.png", "night-dog.png", "cat.png"}
    assert "settings.png" not in provider.calls[1]["candidates"]
    assert _grid_names(page) == ["night-dog.png"]
    assert page._workspace.context.narrowed is True
    assert t("images.ai.narrowed", count=1) in page._ai_history.result_messages[-1].status_text
    assert page._ai_history.result_messages[-1].findChildren(QPushButton, "askAiResultThumb") == []
    page.close()


def test_find_narrow_narrow_act_and_selection_act(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    settings = folder / "settings.png"
    provider = ScriptedMeaningProvider(
        {
            "Google Chrome": (day, night, cat, settings),
            "設定画面": (night, settings),
            "夜": (night,),
        }
    )
    page, folder = _page(tmp_path, provider)

    _send(page, "Find Google Chrome")
    assert _grid_names(page) == ["day-dog.png", "night-dog.png", "cat.png", "settings.png"]

    _send(page, "その中で設定画面だけ")
    assert _grid_names(page) == ["night-dog.png", "settings.png"]
    assert page._workspace.context.narrowed is True

    _send(page, "その中で夜だけ")
    assert _grid_names(page) == ["night-dog.png"]

    dogs = folder / "Dogs"
    _send(page, "この結果をDogsへ移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert t("images.ai.will_move_count", count=1) in confirm.status_text
    assert not dogs.exists()
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    assert (dogs / "night-dog.png").exists()
    assert not night.exists()
    page.close()


def test_find_then_act_waits_for_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day, night), "night": (night,)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "この結果をDogsへ移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert not (folder / "Dogs").exists()
    confirm._cancel_btn.click()
    QTest.qWait(20)
    assert day.exists()
    assert night.exists()
    assert t("images.ai.act_cancelled") in confirm.status_text
    assert page._workspace.context.has_result_set()
    assert {Path(path).name for path in page._workspace.context.result_paths} == {
        "day-dog.png",
        "night-dog.png",
    }
    _send(page, "その中でnightだけ")
    assert _grid_names(page) == ["night-dog.png"]
    assert page._workspace.context.narrowed is True
    page.close()


def test_selection_act_uses_selection_not_result_set(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dog": (day, night, cat)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _select_named(page, "night-dog.png")
    assert page._workspace.context.targets(SOURCE_SELECTION)[1]
    _send(page, "これらにworkタグを付けて")
    confirm = page._ai_history._confirm_messages[-1]
    assert t("work") in confirm.status_text or "work" in confirm.status_text
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    tags = page._metadata_service.load_metadata(folder)["images"]["night-dog.png"]["tags"]
    assert "work" in tags
    cat_tags = page._metadata_service.load_metadata(folder)["images"].get("cat.png", {}).get("tags", [])
    assert "work" not in cat_tags
    page.close()


def test_spaced_tag_phrase_uses_result_set_before_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "この結果に test タグを付けて")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert "test" in confirm.status_text
    metadata = page._metadata_service.load_metadata(folder)
    assert "test" not in metadata.get("images", {}).get("day-dog.png", {}).get("tags", [])
    assert "test" not in metadata.get("images", {}).get("night-dog.png", {}).get("tags", [])
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    metadata = page._metadata_service.load_metadata(folder)
    assert "test" in metadata["images"]["day-dog.png"]["tags"]
    assert "test" in metadata["images"]["night-dog.png"]["tags"]
    page.close()


def test_folder_switch_clears_result_set_so_act_cannot_use_old_images(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    other = tmp_path / "Other"
    other.mkdir()
    _png(other / "plain.png")
    provider = ScriptedMeaningProvider({"dog": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    assert page._workspace.context.has_result_set()
    page.open_folder(other)
    QTest.qWait(20)
    assert not page._workspace.context.has_result_set()
    confirms_before = len(page._ai_history._confirm_messages)
    _send(page, "この結果に test タグを付けて")
    assert len(page._ai_history._confirm_messages) == confirms_before
    assert t("images.ai.missing_target") in page._ai_history.result_messages[-1].assistant_text
    metadata = page._metadata_service.load_metadata(folder)
    assert "test" not in metadata.get("images", {}).get("day-dog.png", {}).get("tags", [])
    assert "test" not in metadata.get("images", {}).get("night-dog.png", {}).get("tags", [])
    page.close()


def test_act_does_not_run_until_action_service_confirms(tmp_path, monkeypatch):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day,)})
    page, folder = _page(tmp_path, provider)
    moved = []

    original = page._metadata_service.move_image_to_project

    def spy(source, dest):
        moved.append((source, dest))
        return original(source, dest)

    monkeypatch.setattr(page._metadata_service, "move_image_to_project", spy)
    _send(page, "Find dog")
    _send(page, "この結果をDogsへ移動して")
    assert moved == []
    page._ai_history._confirm_messages[-1]._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    assert moved
    page.close()


def test_one_result_this_image_tags_without_grid_selection(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dog": (day, night, cat), "night": (night,)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "その中でnightだけ")
    assert _grid_names(page) == ["night-dog.png"]
    assert not page._workspace.context.has_selection()
    _send(page, 'add tag "anime" to this image')
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert t("images.ai.will_tag_count", count=1, tag="anime") in confirm.status_text
    metadata = page._metadata_service.load_metadata(folder)
    assert "anime" not in metadata.get("images", {}).get("night-dog.png", {}).get("tags", [])
    assert not page._workspace.context.has_selection()
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    metadata = page._metadata_service.load_metadata(folder)
    assert "anime" in metadata["images"]["night-dog.png"]["tags"]
    page.close()


def test_search_then_favorite_them_uses_result_set(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"cat": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find cat")
    _send(page, "Favorite them")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert t("images.ai.will_favorite_count", count=2) in confirm.status_text
    assert page._metadata_service.is_image_favorite(folder, "day-dog.png") is False
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    assert page._metadata_service.is_image_favorite(folder, "day-dog.png") is True
    assert page._metadata_service.is_image_favorite(folder, "night-dog.png") is True
    page.close()


def test_narrow_then_those_uses_narrowed_results(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dogs": (day, night, cat), "outdoor": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dogs")
    _send(page, "その中でoutdoorだけ")
    _send(page, "add Test tag to those")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    metadata = page._metadata_service.load_metadata(folder)
    assert "Test" in metadata["images"]["day-dog.png"]["tags"]
    assert "Test" in metadata["images"]["night-dog.png"]["tags"]
    assert "Test" not in metadata.get("images", {}).get("cat.png", {}).get("tags", [])
    page.close()


def test_explicit_selected_and_results_keep_separate_targets(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dog": (day, night, cat)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _select_named(page, "day-dog.png", "night-dog.png")
    _send(page, "Add Test tag to selected images")
    confirm = page._ai_history._confirm_messages[-1]
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    metadata = page._metadata_service.load_metadata(folder)
    assert "Test" in metadata["images"]["day-dog.png"]["tags"]
    assert "Test" in metadata["images"]["night-dog.png"]["tags"]
    assert "Test" not in metadata.get("images", {}).get("cat.png", {}).get("tags", [])

    _select_named(page, "day-dog.png", "night-dog.png")
    _send(page, "Add Work tag to these results")
    confirm = page._ai_history._confirm_messages[-1]
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    metadata = page._metadata_service.load_metadata(folder)
    assert "Work" in metadata["images"]["day-dog.png"]["tags"]
    assert "Work" in metadata["images"]["night-dog.png"]["tags"]
    assert "Work" in metadata["images"]["cat.png"]["tags"]
    page.close()


def test_no_state_act_clarifies_without_internal_error(tmp_path):
    provider = ScriptedMeaningProvider({})
    page, folder = _page(tmp_path, provider)
    _send(page, "add Test tag to these")
    assert page._ai_history._confirm_messages == []
    text = page._ai_history.result_messages[-1].assistant_text
    assert t("images.ai.missing_target") in text
    assert "At least one image is required." not in text
    page.close()


def test_auto_resolved_preview_cancel_makes_no_changes(tmp_path):
    folder = tmp_path / "Selected"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (night,)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, 'add tag "anime" to this image')
    confirm = page._ai_history._confirm_messages[-1]
    confirm._cancel_btn.click()
    QTest.qWait(20)
    metadata = page._metadata_service.load_metadata(folder)
    assert "anime" not in metadata.get("images", {}).get("night-dog.png", {}).get("tags", [])
    assert t("images.ai.act_cancelled") in confirm.status_text
    page.close()
