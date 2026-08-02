"""
End-to-end tag flow tests for Images + Tags + metadata.json + tags.json.

Covers the full checklist: existing assign, new tag, sync, duplicate,
delete, search, and persistence after "restart" (fresh MetadataService).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.ui.pages.tags_page import TagsPage
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_png(path: Path) -> None:
    image = QImage(48, 48, QImage.Format_RGB32)
    image.fill(Qt.darkCyan)
    assert image.save(str(path), "PNG"), f"failed to write {path}"


def _read_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _setup(tmp: str) -> tuple[Path, Path, Path, dict, MetadataService, ImagesPage, TagsPage]:
    root = Path(tmp)
    project_dir = root / "screenshots" / "Default"
    project_dir.mkdir(parents=True)
    image_path = project_dir / "shot.png"
    _write_png(image_path)

    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Default",
        "window_width": 900,
        "window_height": 700,
    }
    service = MetadataService()
    service.ensure_sstool(project_dir)
    service.save_metadata(project_dir, {"images": {}})
    service.save_global_tags(root, ["testcase", "genelar"])

    images = ImagesPage(config, service, ThumbnailCache(size=64), root)
    tags = TagsPage(service, root, config)

    # MainWindow-like wiring
    tags.tags_changed.connect(lambda: images.refresh())
    images.tags_changed.connect(lambda: tags.refresh())

    images.show()
    tags.show()
    return root, project_dir, image_path, config, service, images, tags


def test_full_tag_checklist():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root, project_dir, image_path, config, service, images, tags = _setup(tmp)
        app.processEvents()

        # Labels match expected UX
        assert t("images.tag.mode_existing") == "Existing Tag"
        assert t("images.tag.mode_new") == "New Tag"
        assert t("images.tag.assign") == "Add"
        assert images._tag_assign_btn.text() == "Add"
        assert images._tag_create_btn.text() == "Add"

        # Select image
        images.refresh()
        app.processEvents()
        assert images._list_widget.count() >= 1
        images._list_widget.setCurrentItem(images._list_widget.item(0))
        app.processEvents()
        assert images._info_widget.isEnabled()

        # ① Existing Tag: combo shows tags.json
        assert images._tag_mode_existing_btn.isChecked()
        combo_tags = [
            images._tag_combo.itemText(i) for i in range(images._tag_combo.count())
        ]
        assert combo_tags == ["#testcase", "#genelar"]

        # ② Existing Tag: assign
        images._tag_combo.setCurrentIndex(0)  # testcase
        images._tag_assign_btn.click()
        app.processEvents()
        assert service.get_image_tags(project_dir, "shot.png") == ["testcase"]

        # ③ metadata.json updated
        meta_path = project_dir / ".sstool" / "metadata.json"
        meta = _read_json(meta_path)
        assert meta["images"]["shot.png"]["tags"] == ["testcase"]

        # Chips updated
        chip_texts = []
        for i in range(images._tags_layout.count()):
            w = images._tags_layout.itemAt(i).widget()
            if w is not None and hasattr(w, "text"):
                chip_texts.append(w.text())
        assert any("testcase" in text for text in chip_texts)

        # ④ Tags page still has master list (chip board)
        tags.refresh()
        app.processEvents()
        assert sorted(tags._chip_buttons) == ["genelar", "testcase"]
        assert {btn.text() for btn in tags._chip_buttons.values()} == {
            "#testcase",
            "#genelar",
        }

        # ⑤⑥⑦⑧ New Tag: Debug
        images._tag_mode_new_btn.click()
        app.processEvents()
        assert images._tag_new_row.isVisible()
        images._tag_new_input.setText("Debug")
        images._tag_create_btn.click()
        app.processEvents()

        assert "Debug" in service.get_image_tags(project_dir, "shot.png")
        tags_on_disk = _read_json(service.get_global_tags_path(root))["tags"]
        assert "Debug" in tags_on_disk
        meta = _read_json(meta_path)
        assert "Debug" in meta["images"]["shot.png"]["tags"]

        tags.refresh()
        app.processEvents()
        assert "Debug" in tags._chip_buttons
        assert tags._chip_buttons["Debug"].text() == "#Debug"

        # ⑨ Tags page add → Images combo updates without restart
        images._tag_mode_existing_btn.click()
        app.processEvents()
        tags._new_tag_input.setText("FromTags")
        tags._on_add()
        app.processEvents()
        images.reload_tag_choices()
        app.processEvents()
        combo_tags = [
            images._tag_combo.itemText(i) for i in range(images._tag_combo.count())
        ]
        assert "FromTags" in combo_tags or "#FromTags" in combo_tags

        # Also via signal path (tags_changed → images.refresh)
        tags._new_tag_input.setText("FromTags2")
        tags._on_add()
        app.processEvents()
        combo_tags = [
            images._tag_combo.itemText(i) for i in range(images._tag_combo.count())
        ]
        assert "FromTags2" in combo_tags or "#FromTags2" in combo_tags

        # ⑩ Duplicate assign
        # Put testcase back in combo by removing... it's already assigned so excluded.
        # Assign Debug again via create path (already global)
        images._tag_mode_new_btn.click()
        app.processEvents()
        images._tag_new_input.setText("testcase")
        images._tag_create_btn.click()
        app.processEvents()
        tags_now = service.get_image_tags(project_dir, "shot.png")
        assert tags_now.count("testcase") == 1

        # Existing mode: pick FromTags and assign twice
        images._tag_mode_existing_btn.click()
        app.processEvents()
        idx = next(
            i
            for i in range(images._tag_combo.count())
            if images._tag_combo.itemText(i) in ("FromTags", "#FromTags")
        )
        images._tag_combo.setCurrentIndex(idx)
        images._tag_assign_btn.click()
        app.processEvents()
        images._tag_assign_btn.click()
        app.processEvents()
        assert service.get_image_tags(project_dir, "shot.png").count("FromTags") == 1

        # ⑪ Delete tag chip
        images._delete_tag(image_path, "FromTags")
        app.processEvents()
        assert "FromTags" not in service.get_image_tags(project_dir, "shot.png")

        # ⑫ Search by tag
        images._search_input.setText("Debug")
        images._on_search()
        app.processEvents()
        assert images._list_widget.count() == 1
        images._on_clear_search()
        app.processEvents()
        assert images._list_widget.count() >= 1

        # ⑬ Restart: fresh MetadataService reads disk
        fresh = MetadataService()
        assert "Debug" in fresh.load_global_tags(root, force_reload=True)
        assert "testcase" in fresh.get_image_tags(project_dir, "shot.png")
        assert "Debug" in fresh.get_image_tags(project_dir, "shot.png")


def test_i18n_tag_labels():
    assert t("images.tag.mode_existing") == "Existing Tag"
    assert t("images.tag.mode_new") == "New Tag"
    assert t("images.tag.assign") == "Add"
    assert t("images.tag.create_assign") == "Add"


if __name__ == "__main__":
    test_i18n_tag_labels()
    test_full_tag_checklist()
    print("All tag checklist tests passed.")
