"""Home chart grows with folders; no inner chart scrollbar."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QScrollArea

from app.services.metadata_service import MetadataService
from app.ui.pages.home_page import HomePage
from app.ui.stats_chart import StatsChartPanel
from app.utils.thumbnail_cache import ThumbnailCache
from app.utils.workspace_stats import StatBar


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_stats_chart_panel_has_no_inner_scroll():
    _ensure_app()
    panel = StatsChartPanel()
    assert panel.findChild(QScrollArea) is None


def test_stats_chart_grows_with_row_count():
    _ensure_app()
    panel = StatsChartPanel()
    panel.set_rows([StatBar(label="A", count=1, bytes_total=10)])
    h1 = panel._chart.height()
    panel.set_rows(
        [
            StatBar(label=f"F{i}", count=i + 1, bytes_total=100)
            for i in range(8)
        ]
    )
    h2 = panel._chart.height()
    assert h2 > h1


def test_home_dashboard_uses_page_scroll_and_distinct_hierarchy():
    app = _ensure_app()
    root = Path(tempfile.mkdtemp())
    screenshots = root / "screenshots"
    for name in ("Capture", "Work", "Archive", "Misc"):
        (screenshots / name).mkdir(parents=True)
        (screenshots / name / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)

    config = {
        "screenshot_dir": str(screenshots),
        "home_stats_mode": "folder",
    }
    page = HomePage(config, MetadataService(), ThumbnailCache(), root)
    page.refresh()
    app.processEvents()

    # Home keeps one page scroll with one folder context and two role panels.
    assert page.findChild(QScrollArea, "pageScroll") is not None
    assert page._folder_card.objectName() == "homeSelectedFolderCard"
    assert page._library_panel.objectName() == "homeLibraryPanel"
    assert page._plan_panel.objectName() == "homePlanPanel"
    assert page._total_value.text() == "1"
