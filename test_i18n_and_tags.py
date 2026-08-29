"""Tests for i18n catalog and Images Preview tag actions."""

from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QListWidgetItem

from app.i18n import get_locale, set_locale, t
from app.i18n.en import MESSAGES
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.ui.pages.tags_page import TagsPage
from app.utils.sort_order import images_sort_option_labels, sort_option_labels
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import thumbnail_mode_labels

from app.ui.caption_delegate import ITEM_KIND_IMAGE, ITEM_KIND_ROLE

from conftest import gallery_image_items


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_valid_png(path: Path) -> None:
    image = QImage(32, 32, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def test_i18n_default_locale_is_english():
    set_locale("en")
    assert get_locale() == "en"
    assert t("images.tag.assign") == "Add"
    assert t("images.tag.create_assign") == "Add"
    assert t("images.tag.mode_existing") == "Existing Tag"
    assert t("images.tag.mode_new") == "New Tag"
    assert t("images.tag.add_button") == "Add Tag"
    assert t("images.tag.remove_title") == "Remove Tag"


def test_i18n_format_kwargs():
    assert "boom" in t("images.tag.save_failed", error="boom")


def test_preview_tag_copy_is_available_in_japanese():
    set_locale("ja")
    try:
        assert t("images.tag.select_placeholder") == "タグを選択..."
        assert t("images.tag.add_button") == "タグを追加"
        assert t("images.tag.remove_title") == "タグを外す"
        assert t("images.tag.current") == "現在のタグ"
        assert t("images.tag.new_action") == "+ 新しいタグ"
    finally:
        set_locale("en")


def test_i18n_unknown_key_returns_key():
    assert t("does.not.exist") == "does.not.exist"


def test_i18n_catalog_has_no_empty_values():
    # Unsigned Account control hides the plan row; the catalog keeps an empty placeholder.
    allowed_empty = {"nav.account.plan"}
    for key, value in MESSAGES.items():
        if key in allowed_empty:
            assert isinstance(value, str)
            continue
        assert isinstance(value, str) and value.strip(), f"empty message: {key}"


def test_sort_and_view_labels_resolve():
    labels = sort_option_labels()
    assert len(labels) == 5
    assert all(isinstance(label, str) and label for _, label in labels)
    assert all("sort." not in label for _, label in labels)

    view_labels = thumbnail_mode_labels()
    assert len(view_labels) == 3
    assert all(isinstance(label, str) and label for _, label in view_labels)

    images_labels = images_sort_option_labels()
    assert len(images_labels) == 5
    assert all(isinstance(label, str) and label for _, label in images_labels)
    assert all("sort." not in label for _, label in images_labels)


def test_images_preview_tag_actions_and_tags_page_sync():
    """
    - Select existing tag from combo and Assign
    - Create a new tag and assign it to the Preview image
    - New tag appears on Tags page
    """
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "screenshots" / "Default"
        project_dir.mkdir(parents=True)
        image_path = project_dir / "shot.png"
        _write_valid_png(image_path)

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "window_width": 800,
            "window_height": 600,
        }
        service = MetadataService()
        service.ensure_sstool(project_dir)
        service.save_metadata(project_dir, {"images": {}})
        service.save_global_tags(root, ["alpha", "beta"])

        page = ImagesPage(
            config,
            service,
            ThumbnailCache(size=64),
            root,
        )
        page.show()
        app.processEvents()

        page.refresh()
        app.processEvents()

        assert len(gallery_image_items(page._list_widget)) >= 1
        first = gallery_image_items(page._list_widget)[0]
        page._list_widget.setCurrentItem(first)
        app.processEvents()

        assert page._info_widget.isEnabled() is True
        assert page._tag_combo.count() == 2
        assert page._tag_combo.text() == "Select a tag..."
        assert page._tag_assign_btn.isEnabled() is False
        assert page._tag_combo._new_tag_button.text() == "+ New Tag"
        assert not hasattr(page, "_tag_delete_btn")
        assert not hasattr(page, "_tag_mode_existing_btn")
        assert not hasattr(page, "_tag_mode_new_btn")

        # Existing: select alpha and Assign via button
        page._tag_combo.setCurrentIndex(
            next(
                i
                for i in range(page._tag_combo.count())
                if page._tag_combo.itemText(i) == "#alpha"
            )
        )
        page._tag_assign_btn.click()
        app.processEvents()
        assert service.get_image_tags(project_dir, image_path.name) == ["alpha"]
        assert [page._tag_combo.itemText(i) for i in range(page._tag_combo.count())] == [
            "#alpha",
            "#beta"
        ]

        emitted = {"count": 0}
        page.tags_changed.connect(lambda: emitted.__setitem__("count", emitted["count"] + 1))

        page._create_and_assign_tag_name("  gamma  ")
        app.processEvents()

        tags = service.get_image_tags(project_dir, image_path.name)
        assert "gamma" in tags
        assert "gamma" in service.load_global_tags(root, force_reload=True)
        assert emitted["count"] == 1

        tags_page = TagsPage(service, root, config)
        tags_page.show()
        tags_page.refresh()
        app.processEvents()
        listed = sorted(tags_page._chip_buttons)
        assert listed == ["alpha", "beta", "gamma"]
        assert {btn.text() for btn in tags_page._chip_buttons.values()} == {
            "#alpha",
            "#beta",
            "#gamma",
        }

        assert page._current_tags_label.text() == "Current Tags"
        assert not hasattr(page, "_tag_remove_btn")


def test_invalid_png_still_allows_tagging():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "screenshots" / "Default"
        project_dir.mkdir(parents=True)
        image_path = project_dir / "bad.png"
        image_path.write_bytes(b"not-a-png")

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "window_width": 800,
            "window_height": 600,
        }
        service = MetadataService()
        service.ensure_sstool(project_dir)
        service.save_metadata(project_dir, {"images": {}})
        service.save_global_tags(root, ["alpha"])

        page = ImagesPage(config, service, ThumbnailCache(size=64), root)
        page.show()
        app.processEvents()

        item = QListWidgetItem(image_path.name)
        item.setData(Qt.UserRole, str(image_path.resolve()))
        item.setData(ITEM_KIND_ROLE, ITEM_KIND_IMAGE)
        page._list_widget.addItem(item)
        page._list_widget.setCurrentItem(item)
        app.processEvents()

        assert page._info_widget.isEnabled() is True
        page._tag_combo.setCurrentIndex(0)
        page._tag_assign_btn.click()
        app.processEvents()
        assert service.get_image_tags(project_dir, image_path.name) == ["alpha"]


if __name__ == "__main__":
    test_i18n_default_locale_is_english()
    test_i18n_format_kwargs()
    test_i18n_unknown_key_returns_key()
    test_i18n_catalog_has_no_empty_values()
    test_sort_and_view_labels_resolve()
    test_images_preview_tag_actions_and_tags_page_sync()
    test_invalid_png_still_allows_tagging()
    print("All i18n / tag mode tests passed.")
