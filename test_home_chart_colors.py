"""Home chart: stable per-folder colors for swatch + bar."""

from __future__ import annotations

from app.ui.stats_chart import color_for_label


def test_color_for_label_is_stable():
    a = color_for_label("Capture")
    b = color_for_label("Capture")
    assert a.name() == b.name()


def test_different_folders_get_different_colors_usually():
    colors = {color_for_label(name).name() for name in ("Capture", "Work", "Archive")}
    # Palette is large enough that these common names should not all collide
    assert len(colors) >= 2


def test_overview_label():
    from app.i18n import t

    assert t("home.image_count") == "Overview"


def test_format_bytes_parts_splits_unit():
    from app.utils.workspace_stats import format_bytes_parts

    num, unit = format_bytes_parts(1024 * 1024)
    assert unit == "MB"
    assert num


def test_chart_set_rows_stores_leading_and_prefix():
    from PySide6.QtWidgets import QApplication

    from app.ui.stats_chart import HorizontalBarChart
    from app.utils.workspace_stats import StatBar

    app = QApplication.instance() or QApplication([])
    chart = HorizontalBarChart()
    chart.set_rows(
        [StatBar(label="Capture", count=1, bytes_total=10)],
        label_prefix="",
        leading="folder",
    )
    assert chart._leading == "folder"
    chart.set_rows(
        [StatBar(label="alpha", count=1, bytes_total=10, apply_prefix=True)],
        label_prefix="#",
        leading="swatch",
    )
    assert chart._label_prefix == "#"
    assert chart._leading == "swatch"
    _ = app
