"""Ask AI Act Planner uses Find / Narrow / Action without executing before confirm."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from app.i18n import t
from app.ocr.database import OCRDatabase
from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.repository import OCRRepository
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache
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
    QTest.qWait(40)
    assert not getattr(page, "_ask_ai_turn_busy", False)
    assert not getattr(page, "_ask_ai_turn_tasks", {})
    assert not page._ask_ai_search_tasks
    assert not getattr(page, "_action_executing", False)


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
    QTest.qWait(30)


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
        return tuple(path for path in hits if not allowed or str(path.resolve()) in allowed)


def _grid_names(page):
    return [
        Path(item.data(Qt.UserRole)).name
        for item in gallery_image_items(page._list_widget)
    ]


def _seed_ocr(folder: Path) -> None:
    database = OCRDatabase().open()
    try:
        repository = OCRRepository(database)
        for path in sorted(folder.glob("*.png")):
            repository.upsert_image(
                path,
                size_bytes=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
                quick_fingerprint=calculate_quick_fingerprint(path),
            )
    finally:
        database.close()


def _confirm_has_no_thumbnails(confirm) -> None:
    pixmaps = []
    for widget in confirm.findChildren(QLabel):
        pixmap = widget.pixmap()
        if pixmap is not None and not pixmap.isNull():
            pixmaps.append(widget)
    assert pixmaps == []


def test_tag_and_move_plan_waits_for_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "この結果に work タグを付けて Project A に移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert "work" in confirm.status_text or "work" in confirm._detail.text()
    assert "Project A" in confirm._detail.text()
    assert not (folder / "Project A").exists()
    confirm._cancel_btn.click()
    QTest.qWait(30)
    assert not (folder / "Project A").exists()
    assert day.exists()
    metadata = page._metadata_service.load_metadata(folder)
    assert "work" not in metadata.get("images", {}).get("day-dog.png", {}).get("tags", [])
    page.close()


def test_create_folder_and_move_runs_only_after_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "Dogs フォルダを作って、この結果をそこへ移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert not (folder / "Dogs").exists()
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    assert (folder / "Dogs" / "day-dog.png").exists()
    assert (folder / "Dogs" / "night-dog.png").exists()
    assert not day.exists()
    page.close()


def test_find_then_move_plan_searches_before_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"犬の画像": (day, night), "犬": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "犬の画像を探して Dogs に移動して")
    assert provider.calls
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert not (folder / "Dogs").exists()
    assert cat.exists()
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    assert (folder / "Dogs" / "day-dog.png").exists()
    assert cat.exists()
    assert not (folder / "Dogs" / "cat.png").exists()
    page.close()


def test_tag_and_move_combined_preview_then_confirm(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.workspace.planner.post_act_plan_json",
        lambda *_args, **_kwargs: called.append(1) or {},
    )
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "この結果に work タグを付けて Project A に移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert confirm._confirm_btn.text() == t("images.ai.confirm_run")
    assert t("images.ai.will_update_count", count=2) in confirm.status_text or "2" in confirm.status_text
    detail = confirm._detail.text()
    assert "work" in detail
    assert "Project A" in detail
    _confirm_has_no_thumbnails(confirm)
    assert not (folder / "Project A").exists()
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    assert (folder / "Project A" / "day-dog.png").exists()
    tags = page._metadata_service.load_metadata(folder / "Project A")
    assert "work" in tags.get("images", {}).get("day-dog.png", {}).get("tags", [])
    assert called == []
    page.close()


def test_create_folder_existing_reuses_folder_and_moves(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day,)})
    page, folder = _page(tmp_path, provider)
    (folder / "Dogs").mkdir()
    _send(page, "Find dog")
    _send(page, "Dogs フォルダを作って、この結果をそこへ移動して")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    assert not day.exists()
    assert (folder / "Dogs" / "day-dog.png").exists()
    page.close()


def test_narrow_then_tag_uses_narrowed_set(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.workspace.planner.post_act_plan_json",
        lambda *_args, **_kwargs: called.append(1) or {},
    )
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dog": (day, night, cat), "犬": (day, night)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    assert set(_grid_names(page)) == {"day-dog.png", "night-dog.png", "cat.png"}
    _send(page, "この中で犬の画像だけ favorite タグを付けて")
    assert provider.calls[-1]["query"] == "犬"
    assert "cat.png" in provider.calls[0]["candidates"]
    assert "settings.png" not in provider.calls[-1]["candidates"]
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    grid = _grid_names(page)
    assert set(grid) == {"day-dog.png", "night-dog.png"}
    assert "cat.png" not in grid
    assert str(len(grid)) in confirm.status_text
    metadata = page._metadata_service.load_metadata(folder)
    assert "favorite" not in metadata.get("images", {}).get("day-dog.png", {}).get("tags", [])
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    metadata = page._metadata_service.load_metadata(folder)
    assert "favorite" in metadata["images"]["day-dog.png"]["tags"]
    assert "favorite" in metadata["images"]["night-dog.png"]["tags"]
    assert "favorite" not in metadata.get("images", {}).get("cat.png", {}).get("tags", [])
    assert called == []
    page.close()


def test_empty_find_does_not_move(tmp_path):
    folder = tmp_path / "Selected"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"giraffeの画像": (), "giraffe": ()})
    page, folder = _page(tmp_path, provider)
    confirms_before = len(page._ai_history._confirm_messages)
    _send(page, "giraffeの画像を探して Dogs に移動して")
    assert len(page._ai_history._confirm_messages) == confirms_before
    assert not (folder / "Dogs").exists()
    assert cat.exists()
    page.close()


def test_simple_act_stays_on_single_preview(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.build_act_plan",
        lambda *_args, **_kwargs: called.append(1) or (_ for _ in ()).throw(AssertionError("planner")),
    )
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day,)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    _send(page, "この結果に work タグを付けて")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    assert confirm._confirm_btn.text() == t("images.ai.confirm_tag")
    assert called == []
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(50)
    tags = page._metadata_service.load_metadata(folder)["images"]["day-dog.png"]["tags"]
    assert "work" in tags
    page.close()


def test_vague_organize_clarifies_without_pending_action(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    provider = ScriptedMeaningProvider({"dog": (day,)})
    page, folder = _page(tmp_path, provider)
    _send(page, "Find dog")
    confirms_before = len(page._ai_history._confirm_messages)
    before = day.stat().st_mtime_ns
    _send(page, "いい感じに整理して")
    assert len(page._ai_history._confirm_messages) == confirms_before
    assert t("images.ai.clarify_organize") in page._ai_history.result_messages[-1].assistant_text
    assert day.exists()
    assert day.stat().st_mtime_ns == before
    page.close()


def test_descriptive_rename_preview_then_confirm(tmp_path):
    folder = tmp_path / "Selected"
    day = folder / "day-dog.png"
    night = folder / "night-dog.png"
    cat = folder / "cat.png"
    provider = ScriptedMeaningProvider({"dog": (day, night, cat)})
    page, folder = _page(tmp_path, provider)
    _seed_ocr(folder)
    page._act_plan_name_generator = lambda images: {
        int(item["image_id"]): f"scene-{item['image_id']}" for item in images
    }
    _send(page, "Find dog")
    _send(page, "この3枚を内容が分かる名前に変えて")
    confirm = page._ai_history._confirm_messages[-1]
    assert confirm.pending is True
    detail = confirm._detail.text()
    assert "→" in detail or "day-dog" in detail
    assert day.exists() and day.name == "day-dog.png"
    confirm._cancel_btn.click()
    QTest.qWait(30)
    assert day.exists()
    _send(page, "この3枚を内容が分かる名前に変えて")
    confirm = page._ai_history._confirm_messages[-1]
    confirm._confirm_btn.click()
    _wait_ask_ai(page)
    QTest.qWait(80)
    assert not day.exists()
    assert (folder / "settings.png").exists()
    assert len(list(folder.glob("scene-*.png"))) == 3
    assert all(path.suffix.lower() == ".png" for path in folder.glob("scene-*.png"))
    page.close()
