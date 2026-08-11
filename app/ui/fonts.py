"""Application typography based on the Windows UI font."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

UI_FONT_FAMILY = "Segoe UI"


def install_ui_font(app: QApplication | None = None) -> bool:
    """Use Segoe UI as the application-wide font on Windows."""
    application = app or QApplication.instance()
    if application is None:
        return False
    current = application.font()
    font = QFont(UI_FONT_FAMILY, current.pointSize())
    font.setStyleStrategy(current.styleStrategy())
    font.setWeight(QFont.Weight.Normal)
    application.setFont(font)
    return QFontInfo(application.font()).family() == UI_FONT_FAMILY


def ui_font_diagnostics() -> dict[str, object]:
    """Report the resolved Segoe UI faces used by the hierarchy."""
    requested = {
        "regular": QFont.Weight.Normal,
        "medium": QFont.Weight.Medium,
        "semibold": QFont.Weight.DemiBold,
    }
    resolved: dict[str, dict[str, object]] = {}
    for name, weight in requested.items():
        font = QFont(UI_FONT_FAMILY)
        font.setWeight(weight)
        info = QFontInfo(font)
        resolved[name] = {
            "family": info.family(),
            "style": info.styleName(),
            "weight": int(info.weight()),
            "fallback": info.family() != UI_FONT_FAMILY,
        }
    return {
        "family": UI_FONT_FAMILY,
        "weights": resolved,
    }


# Compatibility for older imports while callers migrate to the generic name.
install_inter_font = install_ui_font
inter_font_diagnostics = ui_font_diagnostics
INTER_FAMILY = UI_FONT_FAMILY
