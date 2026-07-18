"""Tests for i18n catalog and Images tag assign modes."""

from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QListWidgetItem

from app.i18n import get_locale, set_locale, t
from app.i18n.en import MESSAGES
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import TAG_MODE_EXISTING, TAG_MODE_NEW, ImagesPage
from app.ui.pages.tags_page import TagsPage
from app.utils.sort_order import sort_option_labels
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.view_mode import thumbnail_mode_labels


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


def test_i18n_format_kwargs():
    assert "boom" in t("images.tag.save_failed", error="boom")


def test_i18n_unknown_key_returns_key():
    assert t("does.not.exist") == "does.not.exist"


def test_i18n_catalog_has_no_empty_values():
    for key, value in MESSAGES.items():
        assert isinstance(value, str) and value.strip(), f"empty message: {key}"


def test_sort_and_view_labels_resolve():
    labels = sort_option_labels()
    assert len(labels) == 4
    assert all(isinstance(label, str) and label for _, label in labels)
    assert all("sort." not in label for _, label in labels)

    view_labels = thumbnail_mode_labels()
    assert len(view_labels) == 3
    assert all(isinstance(label, str) and label for _, label in view_labels)


def test_images_tag_modes_assign_and_tags_page_sync():
    """
    - Select existing tag from combo and Assign
    - Switch mode, create new tag and assign
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

        assert page._list_widget.count() >= 1
        first = page._list_widget.item(0)
        page._list_widget.setCurrentItem(first)
        app.processEvents()

        assert page._info_widget.isEnabled() is True
        assert page._tag_mode_existing_btn.isChecked()
        assert page._tag_existing_row.isVisible()
        assert page._tag_new_row.isHidden()
        assert page._tag_combo.count() == 2
        assert page._tag_assign_btn.isEnabled() is True

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
            "#beta"
        ]

        # New: switch mode, create gamma, verify Tags page
        page._tag_mode_new_btn.click()
        app.processEvents()
        assert page._tag_new_row.isVisible()
        assert page._tag_existing_row.isHidden()

        emitted = {"count": 0}
        page.tags_changed.connect(lambda: emitted.__setitem__("count", emitted["count"] + 1))

        page._tag_new_input.setText("gamma")
        page._tag_create_btn.click()
        app.processEvents()

        tags = service.get_image_tags(project_dir, image_path.name)
        assert "gamma" in tags
        assert "gamma" in service.load_global_tags(root, force_reload=True)
        assert emitted["count"] == 1

        tags_page = TagsPage(service, root, config)
        tags_page.show()
        tags_page.refresh()
        app.processEvents()
        listed = [
            tags_page._list.item(i).text() for i in range(tags_page._list.count())
        ]
        assert listed == ["#alpha", "#beta", "#gamma"]

        # Back to existing mode still works
        page._tag_mode_existing_btn.click()
        app.processEvents()
        assert page._tag_existing_row.isVisible()


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
    test_images_tag_modes_assign_and_tags_page_sync()
    test_invalid_png_still_allows_tagging()
    print("All i18n / tag mode tests passed.")
