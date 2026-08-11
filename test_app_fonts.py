"""Segoe UI application typography and hierarchy."""

from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import QApplication

from app.ui.fonts import (
    UI_FONT_FAMILY,
    install_ui_font,
    ui_font_diagnostics,
)
from app.ui.styles import APP_STYLE


def test_segoe_ui_is_the_application_font_and_resolves_standard_weights():
    app = QApplication.instance() or QApplication([])
    assert install_ui_font(app)
    assert QFontInfo(app.font()).family() == UI_FONT_FAMILY
    assert 'font-family: "Segoe UI"' in APP_STYLE
    assert 'font-family: "Inter"' not in APP_STYLE
    diagnostics = ui_font_diagnostics()
    assert diagnostics["family"] == UI_FONT_FAMILY
    weights = diagnostics["weights"]
    assert weights["regular"]["style"] == "Regular"
    assert all(not result["fallback"] for result in weights.values())


def test_typography_hierarchy_keeps_body_regular_and_titles_semibold():
    assert "QLabel#pageTitle" in APP_STYLE
    assert "font-size: 20px;\n    font-weight: 600;" in APP_STYLE
    assert "QLabel#sectionTitle" in APP_STYLE
    assert "font-weight: 400;" in APP_STYLE
    page_title_rule = APP_STYLE.split("QLabel#pageTitle", 1)[1].split("}", 1)[0]
    section_title_rule = APP_STYLE.split("QLabel#sectionTitle", 1)[1].split("}", 1)[0]
    assert "font-weight: 700" not in page_title_rule
    assert "font-weight: 700" not in section_title_rule
    assert "font-weight: 800" not in APP_STYLE
    assert "font-weight: 900" not in APP_STYLE
    assert "font-weight: bold" not in APP_STYLE
