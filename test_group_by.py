"""Tests for Images Group By (display-only grouping)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import (
    ITEM_KIND_HEADER,
    ITEM_KIND_IMAGE,
    ITEM_KIND_ROLE,
    ImagesPage,
)
from app.utils.group_by import (
    DEFAULT_GROUP_BY,
    GROUP_BY_DATE,
    GROUP_BY_NONE,
    GROUP_BY_TAG,
    NO_TAG_GROUP_KEY,
    build_groups,
    normalize_group_by,
)
from app.utils.sort_order import SORT_FILENAME_ASC, SORT_MODIFIED_DESC
from app.utils.thumbnail_cache import ThumbnailCache


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _touch_png(path: Path, mtime: float | None = None) -> Path:
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(Qt.red)
    assert image.save(str(path), "PNG")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_normalize_group_by():
    assert normalize_group_by("date") == GROUP_BY_DATE
    assert normalize_group_by("tag") == GROUP_BY_TAG
    assert normalize_group_by("none") == GROUP_BY_NONE
    assert normalize_group_by(None) == DEFAULT_GROUP_BY
    assert normalize_group_by("unknown") == DEFAULT_GROUP_BY


def test_build_groups_none_applies_sort():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        b = _touch_png(root / "b.png")
        a = _touch_png(root / "a.png")
        groups = build_groups([b, a], GROUP_BY_NONE, {}, SORT_FILENAME_ASC)
        assert len(groups) == 1
        assert groups[0][0] == ""
        assert [p.name for p in groups[0][1]] == ["a.png", "b.png"]


def test_build_groups_date():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Fixed timestamps: day1 older, day2 newer
        day1 = time.mktime((2026, 7, 13, 12, 0, 0, 0, 0, -1))
        day2 = time.mktime((2026, 7, 15, 12, 0, 0, 0, 0, -1))
        older = _touch_png(root / "older.png", day1)
        newer_a = _touch_png(root / "newer_b.png", day2)
        newer_b = _touch_png(root / "newer_a.png", day2)

        groups = build_groups(
            [older, newer_a, newer_b],
            GROUP_BY_DATE,
            {},
            SORT_FILENAME_ASC,
        )
        assert [g[0] for g in groups] == ["2026/07/15", "2026/07/13"]
        assert [p.name for p in groups[0][1]] == ["newer_a.png", "newer_b.png"]
        assert [p.name for p in groups[1][1]] == ["older.png"]


def test_build_groups_tag_multi_membership_and_no_tag():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = _touch_png(root / "a.png")
        b = _touch_png(root / "b.png")
        c = _touch_png(root / "c.png")
        metadata = {
            "images": {
                "a.png": {"tags": ["Debug", "Chrome"]},
                "b.png": {"tags": ["Chrome"]},
                "c.png": {"tags": []},
            }
        }
        groups = build_groups(
            [a, b, c],
            GROUP_BY_TAG,
            metadata,
            SORT_FILENAME_ASC,
        )
        keys = [g[0] for g in groups]
        assert keys == ["Chrome", "Debug", NO_TAG_GROUP_KEY]
        chrome = dict(groups)["Chrome"]
        debug = dict(groups)["Debug"]
        assert {p.name for p in chrome} == {"a.png", "b.png"}
        assert {p.name for p in debug} == {"a.png"}
        assert [p.name for p in dict(groups)[NO_TAG_GROUP_KEY]] == ["c.png"]


def test_images_page_group_by_ui_and_persistence():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "screenshots" / "Default"
        project_dir.mkdir(parents=True)
        day1 = time.mktime((2026, 7, 14, 10, 0, 0, 0, 0, -1))
        day2 = time.mktime((2026, 7, 15, 10, 0, 0, 0, 0, -1))
        _touch_png(project_dir / "old.png", day1)
        _touch_png(project_dir / "new.png", day2)

        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Default",
            "window_width": 800,
            "window_height": 600,
        }
        service = MetadataService()
        service.ensure_sstool(project_dir)
        service.save_metadata(
            project_dir,
            {
                "images": {
                    "old.png": {"tags": ["Research"]},
                    "new.png": {"tags": ["Debug", "Chrome"]},
                }
            },
        )
        service.save_global_tags(root, ["Debug", "Chrome", "Research"])

        page = ImagesPage(config, service, ThumbnailCache(size=48), root)
        page.show()
        app.processEvents()
        page.refresh()
        app.processEvents()

        # ① None — images only, no headers
        assert page._group_by == GROUP_BY_NONE
        kinds = [
            page._list_widget.item(i).data(ITEM_KIND_ROLE)
            for i in range(page._list_widget.count())
        ]
        assert ITEM_KIND_HEADER not in kinds
        assert kinds.count(ITEM_KIND_IMAGE) == 2

        # ② Date
        page._group_combo.setCurrentIndex(page._group_combo.findData(GROUP_BY_DATE))
        app.processEvents()
        headers = [
            page._list_widget.item(i).text()
            for i in range(page._list_widget.count())
            if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
        ]
        assert headers == ["2026/07/15", "2026/07/14"]

        project = json.loads(
            (project_dir / ".sstool" / "project.json").read_text(encoding="utf-8")
        )
        assert project["display"]["group_by"] == "date"

        # ③ Tag + ④ No Tag (add untagged file)
        _touch_png(project_dir / "plain.png")
        page._group_combo.setCurrentIndex(page._group_combo.findData(GROUP_BY_TAG))
        app.processEvents()
        headers = [
            page._list_widget.item(i).text()
            for i in range(page._list_widget.count())
            if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
        ]
        assert "#Chrome" in headers
        assert "#Debug" in headers
        assert "#Research" in headers
        assert "No tags" in headers

        # Multi-membership: new.png under both Debug and Chrome
        def paths_under(header: str) -> list[str]:
            names: list[str] = []
            collecting = False
            for i in range(page._list_widget.count()):
                item = page._list_widget.item(i)
                if item.data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER:
                    collecting = item.text() == header
                    continue
                if collecting:
                    path = item.data(Qt.UserRole)
                    names.append(Path(path).name)
            return names

        assert "new.png" in paths_under("#Debug")
        assert "new.png" in paths_under("#Chrome")
        assert "plain.png" in paths_under("No tags")

        # ⑤ Search keeps group by
        page._search_input.setText("Debug")
        page._on_search()
        app.processEvents()
        assert page._group_by == GROUP_BY_TAG
        headers = [
            page._list_widget.item(i).text()
            for i in range(page._list_widget.count())
            if page._list_widget.item(i).data(ITEM_KIND_ROLE) == ITEM_KIND_HEADER
        ]
        assert "#Debug" in headers
        assert "plain.png" not in paths_under("No tags") or "No tags" not in headers

        # ⑥ Refresh keeps setting
        page.refresh()
        app.processEvents()
        assert page._group_combo.currentData() == GROUP_BY_TAG

        # ⑦ Restart restore
        page2 = ImagesPage(config, service, ThumbnailCache(size=48), root)
        page2.show()
        app.processEvents()
        page2._load_display_settings_from_project()
        assert page2._group_by == GROUP_BY_TAG
        assert page2._group_combo.currentData() == GROUP_BY_TAG

        # ⑧ Sort within groups (filename asc under Date)
        page._on_clear_search()
        page._group_combo.setCurrentIndex(page._group_combo.findData(GROUP_BY_DATE))
        page._sort_combo.setCurrentIndex(page._sort_combo.findData(SORT_FILENAME_ASC))
        app.processEvents()
        # Only one file per day in this set after search clear — just ensure no crash
        assert page._group_by == GROUP_BY_DATE


if __name__ == "__main__":
    test_normalize_group_by()
    test_build_groups_none_applies_sort()
    test_build_groups_date()
    test_build_groups_tag_multi_membership_and_no_tag()
    test_images_page_group_by_ui_and_persistence()
    print("All group_by tests passed.")
