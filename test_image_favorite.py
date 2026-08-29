"""Image Favorite is an independent attribute, not a Tag."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from conftest import gallery_image_items
from app.services.metadata_service import MetadataService
from app.utils.image_favorite import (
    FAVORITE_TAG,
    apply_favorite_filter,
    favorite_names,
    image_is_favorite,
    migrate_favorite_tag_metadata,
    visible_tags,
)
from app.utils.sort_order import SORT_FAVORITES_FIRST, sort_png_files


def test_favorite_tag_is_not_added_or_listed():
    metadata = {
        "images": {
            "shot.png": {"tags": [FAVORITE_TAG, "ui"]},
        }
    }
    assert migrate_favorite_tag_metadata(metadata) is True
    entry = metadata["images"]["shot.png"]
    assert entry["favorite"] is True
    assert entry["tags"] == ["ui"]
    assert visible_tags(entry["tags"]) == ["ui"]
    assert image_is_favorite(metadata, "shot.png")
    assert favorite_names(metadata) == {"shot.png"}
    assert migrate_favorite_tag_metadata(metadata) is False


def test_metadata_service_persists_favorite_without_tags(tmp_path: Path):
    folder = tmp_path / "Library"
    folder.mkdir()
    service = MetadataService()
    service.register_image(folder, "shot.png")
    assert service.add_image_tag(folder, "shot.png", FAVORITE_TAG) is False
    assert service.get_image_tags(folder, "shot.png") == []
    assert service.is_image_favorite(folder, "shot.png") is False

    assert service.set_image_favorite(folder, "shot.png", True) is True
    assert service.is_image_favorite(folder, "shot.png") is True
    assert service.get_image_tags(folder, "shot.png") == []
    assert "Favorite" not in json.loads(
        service.get_metadata_path(folder).read_text(encoding="utf-8")
    )["images"]["shot.png"].get("tags", [])
    assert json.loads(
        service.get_metadata_path(folder).read_text(encoding="utf-8")
    )["images"]["shot.png"]["favorite"] is True

    service.add_image_tag(folder, "shot.png", "ui")
    assert service.get_image_tags(folder, "shot.png") == ["ui"]
    service.set_image_favorite(folder, "shot.png", False)
    assert service.is_image_favorite(folder, "shot.png") is False
    assert service.get_image_tags(folder, "shot.png") == ["ui"]


def test_metadata_service_migrates_legacy_favorite_tag(tmp_path: Path):
    folder = tmp_path / "Library"
    folder.mkdir()
    service = MetadataService()
    service.ensure_sstool(folder)
    payload = {
        "images": {
            "old.png": {"tags": [FAVORITE_TAG, "debug"]},
            "plain.png": {"tags": ["ui"]},
        }
    }
    service.get_metadata_path(folder).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    loaded = service.load_metadata(folder, force_reload=True)
    assert loaded["images"]["old.png"]["favorite"] is True
    assert loaded["images"]["old.png"]["tags"] == ["debug"]
    assert "favorite" not in loaded["images"]["plain.png"]
    assert service.get_image_tags(folder, "old.png") == ["debug"]
    assert service.is_image_favorite(folder, "old.png") is True
    assert service.is_image_favorite(folder, "plain.png") is False


def test_global_tags_drop_favorite(tmp_path):
    from app.paths import set_path_overrides, clear_path_overrides

    appdata = tmp_path / "appdata"
    set_path_overrides(app_data_dir=appdata)
    try:
        service = MetadataService()
        tags_path = service.get_global_tags_path(tmp_path)
        tags_path.parent.mkdir(parents=True, exist_ok=True)
        tags_path.write_text(
            json.dumps({"tags": [FAVORITE_TAG, "ui"]}), encoding="utf-8"
        )
        tags = service.load_global_tags(tmp_path, force_reload=True)
        assert tags == ["ui"]
        assert service.ensure_global_tag(tmp_path, FAVORITE_TAG) == ""
        assert service.add_global_tag(tmp_path, FAVORITE_TAG) == ""
        assert service.load_global_tags(tmp_path) == ["ui"]
    finally:
        clear_path_overrides()


def test_favorite_filter_uses_attribute_or_legacy_tag(tmp_path: Path):
    older = tmp_path / "older.png"
    newer = tmp_path / "newer.png"
    older.write_bytes(b"")
    newer.write_bytes(b"")
    metadata = {
        "images": {
            "older.png": {"favorite": True, "tags": []},
            "newer.png": {"tags": []},
        }
    }
    only_fav = apply_favorite_filter([older, newer], metadata, "favorites_only")
    assert [path.name for path in only_fav] == ["older.png"]
    ranked = sort_png_files(
        [older, newer],
        SORT_FAVORITES_FIRST,
        favorite_names=favorite_names(metadata),
    )
    assert [path.name for path in ranked] == ["older.png", "newer.png"]


def test_page_favorite_toggle_does_not_create_tag(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Library"
    folder.mkdir()
    png = folder / "shot.png"
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(png), "PNG")
    service = MetadataService()
    from app.ui.pages.images_page import ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache
    from app.ui.caption_delegate import ROLE_CAPTION_FAVORITE, ROLE_CAPTION_TAGS

    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        service,
        ThumbnailCache(size=32),
        tmp_path,
    )
    page.refresh()
    app.processEvents()
    item = gallery_image_items(page._list_widget)[0]
    item.setSelected(True)
    page._list_widget.setCurrentItem(item)
    page._toggle_selected_image_favorite()
    item = gallery_image_items(page._list_widget)[0]
    assert service.is_image_favorite(folder, png.name) is True
    assert service.get_image_tags(folder, png.name) == []
    assert item.data(ROLE_CAPTION_FAVORITE) is True
    assert "Favorite" not in str(item.data(ROLE_CAPTION_TAGS))
    page._toggle_selected_image_favorite()
    item = gallery_image_items(page._list_widget)[0]
    assert service.is_image_favorite(folder, png.name) is False
    assert item.data(ROLE_CAPTION_FAVORITE) is False
    page.close()


def test_ask_ai_find_favorite_updates_cards_from_action_result(tmp_path: Path):
    from app.i18n import t
    from app.ui.caption_delegate import ROLE_CAPTION_FAVORITE
    from app.ui.pages.images_page import ImagesPage
    from app.utils.thumbnail_cache import ThumbnailCache
    from app.workspace import ORIGIN_MEANING, parse_plan_payload
    from app.workspace.plan import STEP_FIND

    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Library"
    folder.mkdir()
    paths = []
    for name in ("cat-one.png", "cat-two.png"):
        png = folder / name
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.blue)
        assert image.save(str(png), "PNG")
        paths.append(png)
    service = MetadataService()
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        service,
        ThumbnailCache(size=32),
        tmp_path,
    )
    page.refresh()
    app.processEvents()
    page._remember_workspace_results(paths, "cat images", origin=ORIGIN_MEANING, narrowed=False)
    plan = parse_plan_payload(
        {
            "steps": [
                {"id": "find", "type": STEP_FIND, "query": "cat images"},
                {"id": "fav", "type": "action", "action_id": "add_favorite"},
            ]
        }
    )
    page._show_prepared_act_plan(plan, isolate=False)
    app.processEvents()
    message = page._pending_act_message
    assert message is not None
    prepared = page._pending_prepared_plan
    assert prepared is not None
    favorite_plan = next(item for item in prepared.action_plans if item is not None)
    assert favorite_plan.item_count == 2
    assert favorite_plan.executable_count == 2
    assert service.is_image_favorite(folder, "cat-one.png") is False

    page._on_ask_ai_act_confirmed(message)
    app.processEvents()
    assert service.is_image_favorite(folder, "cat-one.png") is True
    assert service.is_image_favorite(folder, "cat-two.png") is True
    assert MetadataService().is_image_favorite(folder, "cat-one.png") is True
    items = gallery_image_items(page._list_widget)
    assert items
    assert all(item.data(ROLE_CAPTION_FAVORITE) for item in items)
    assert message.status_text == t("images.ai.act_done_favorite", count=2)

    page._remember_workspace_results(paths, "cat images", origin=ORIGIN_MEANING, narrowed=False)
    page._show_prepared_act_plan(plan, isolate=False)
    app.processEvents()
    again = page._pending_act_message
    page._on_ask_ai_act_confirmed(again)
    app.processEvents()
    assert again.status_text == t("images.ai.act_already_favorite", count=2)
    page.close()
