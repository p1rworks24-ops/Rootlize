"""Nav icons share charcoal ink; selected state is the surface, not a rainbow."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.icons import (
    NAV_COLOR_ABOUT,
    NAV_COLOR_HOME,
    NAV_COLOR_IMAGES,
    NAV_COLOR_ORGANIZE,
    NAV_COLOR_SETTINGS,
    NAV_COLOR_TAGS,
    NAV_INK,
)
from app.ui.main_window import (
    PAGE_AUTOMATION,
    PAGE_IMAGES,
    PAGE_SETTINGS,
    MainWindow,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_nav_accents_and_icon_colors_differ():
    _ensure_app()
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Capture").mkdir(parents=True)
    config = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
    }
    window = MainWindow(config)
    expected = {
        PAGE_IMAGES: "images",
        PAGE_AUTOMATION: "automation",
        PAGE_SETTINGS: "settings",
    }
    for page_id, accent in expected.items():
        btn = window._side_nav._nav_buttons[page_id]
        assert btn.property("navAccent") == accent

    assert {
        NAV_COLOR_HOME,
        NAV_COLOR_IMAGES,
        NAV_COLOR_ORGANIZE,
        NAV_COLOR_TAGS,
        NAV_COLOR_SETTINGS,
        NAV_COLOR_ABOUT,
    } == {NAV_INK}
    assert "#2563eb" not in {
        NAV_COLOR_HOME,
        NAV_COLOR_IMAGES,
        NAV_COLOR_TAGS,
        NAV_COLOR_SETTINGS,
        NAV_COLOR_ABOUT,
    }

    images_btn = window._side_nav._nav_buttons[PAGE_IMAGES]
    assert images_btn.isChecked()
    window._side_nav.set_expanded(False, animate=False)
    assert images_btn.property("collapsed") == "true"
    assert images_btn.isChecked()
    window.close()
