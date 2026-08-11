"""Nav items use associative accent colors (not all blue)."""

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
)
from app.ui.main_window import (
    PAGE_ABOUT,
    PAGE_HOME,
    PAGE_IMAGES,
    PAGE_ORGANIZE,
    PAGE_SETTINGS,
    PAGE_TAGS,
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
        PAGE_HOME: "home",
        PAGE_IMAGES: "images",
        PAGE_SETTINGS: "settings",
        PAGE_ABOUT: "about",
    }
    for page_id, accent in expected.items():
        btn = window._side_nav._nav_buttons[page_id]
        assert btn.property("navAccent") == accent

    colors = {
        NAV_COLOR_HOME,
        NAV_COLOR_IMAGES,
        NAV_COLOR_ORGANIZE,
        NAV_COLOR_TAGS,
        NAV_COLOR_SETTINGS,
        NAV_COLOR_ABOUT,
    }
    assert len(colors) == 6
    assert "#2563eb" not in {
        NAV_COLOR_HOME,
        NAV_COLOR_IMAGES,
        NAV_COLOR_TAGS,
        NAV_COLOR_SETTINGS,
        NAV_COLOR_ABOUT,
    }
