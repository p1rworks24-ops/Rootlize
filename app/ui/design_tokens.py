"""Small, adjustable UI token set for the Design Guidelines v1 trial."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


@dataclass(frozen=True)
class Colors:
    app_bg: str = "#f7faff"
    surface: str = "#ffffff"
    surface_subtle: str = "#f8fafc"
    surface_sunken: str = "#f3f4f6"
    text_strong: str = "#111827"
    text: str = "#1f2937"
    text_secondary: str = "#475569"
    text_muted: str = "#64748b"
    border: str = "#e5e7eb"
    border_strong: str = "#cbd5e1"
    card_border: str = "#d8e2ee"
    primary: str = "#2563eb"
    primary_strong: str = "#1e40af"
    primary_soft: str = "#eff6ff"
    primary_soft_hover: str = "#dbeafe"
    info: str = "#0891b2"
    info_strong: str = "#0e7490"
    info_soft: str = "#ecfeff"
    info_soft_hover: str = "#cffafe"
    ai: str = "#7c3aed"
    ai_soft: str = "#f5f3ff"
    tag: str = "#db2777"
    tag_soft: str = "#fdf2f8"
    success: str = "#059669"
    success_soft: str = "#ecfdf5"
    warning: str = "#d97706"
    warning_soft: str = "#fffbeb"
    error: str = "#dc2626"
    error_soft: str = "#fef2f2"


COLORS = Colors()

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
RADIUS_SM = 4
RADIUS_CONTROL = 6
RADIUS_MD = 8
RADIUS_CARD = 12
CONTROL_COMPACT = 28
CONTROL_STANDARD = 32
ICON_MD = 20
ICON_LG = 24
ICON_XL = 28
PAGE_HEADER_SYMBOL_HERO = 64
PAGE_HEADER_SYMBOL_SHAPE = 52
PAGE_HEADER_SYMBOL_GLOW = 42
PAGE_HEADER_SYMBOL_DOT = 12
PAGE_HEADER_SYMBOL_RADIUS = 18
NAV_ICON_BOX = 28
CAPTURE_BAR_HEIGHT = 52
CAPTURE_BUTTON_WIDTH = 88
CAPTURE_BUTTON_HEIGHT = 60
CAPTURE_EDGE_BUTTON_HEIGHT = 32
CAPTURE_TOGGLE_WIDTH = 32
CAPTURE_MODE_SELECTOR_WIDTH = 128
CAPTURE_MODE_REGION_WIDTH = 62
CAPTURE_MODE_FULLSCREEN_WIDTH = 62
CAPTURE_BAR_PADDING_X = 12
CAPTURE_BAR_PADDING_Y = 12
CAPTURE_BAR_ITEM_GAP = 8
CAPTURE_FIELD_TITLE_HEIGHT = 18
CAPTURE_FIELD_HEIGHT = 52
NAV_PADDING_X = 8
NAV_PADDING_Y = 14
NAV_ITEM_GAP = 4
NAV_RESPONSIVE_BREAKPOINT = 900
WORKSPACE_PADDING = 12
WORKSPACE_GAP = 8
WORKSPACE_PANEL_PADDING = 12
IMAGES_FOLDER_LOCATOR_MIN_WIDTH = 220
# The selected folder is workspace context, not a compact field. Allow the
# locator to span the Images command surface at desktop widths.
IMAGES_FOLDER_LOCATOR_MAX_WIDTH = 16777215
IMAGES_RIGHT_PANEL_DEFAULT_WIDTH = 300
IMAGES_RIGHT_PANEL_MIN_WIDTH = 280
IMAGES_RIGHT_PANEL_MAX_WIDTH = 420
IMAGES_COMMAND_GAP = 8

# Trial switches. Change only these values to compare visual strength.
# SHADOW_MODE: "soft" (guideline candidate), "weak", or "off".
SHADOW_MODE = "weak"
# NAV_EMPHASIS: "trial" (stronger) or "quiet" (close to the previous UI).
NAV_EMPHASIS = "trial"


def apply_card_shadow(widget: QWidget, *, blue_tinted: bool = False) -> None:
    """Apply the shared trial shadow, or remove it globally when disabled."""
    if SHADOW_MODE == "off":
        widget.setGraphicsEffect(None)
        return
    weak = SHADOW_MODE == "weak"
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(14 if weak else 20)
    effect.setOffset(0, 1 if weak else 2)
    effect.setColor(
        QColor(71, 104, 145, 18 if weak else 28)
        if blue_tinted
        else QColor(15, 23, 42, 12 if weak else 26)
    )
    widget.setGraphicsEffect(effect)


def navigation_icon(icon: QIcon, accent: str) -> QIcon:
    """Wrap a navigation glyph in a pastel tile for the trial emphasis."""
    if NAV_EMPHASIS == "quiet" or icon.isNull():
        return icon
    surfaces = {
        "home": "#ffedd5",
        "images": COLORS.info_soft_hover,
        "organize": COLORS.primary_soft_hover,
        "tags": "#fce7f3",
        "ai": "#ede9fe",
        "settings": "#e2e8f0",
        "about": "#ccfbf1",
    }
    pixmap = QPixmap(NAV_ICON_BOX, NAV_ICON_BOX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(surfaces.get(accent, COLORS.primary_soft)))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 7, 7)
    icon.paint(painter, QRect(5, 5, NAV_ICON_BOX - 10, NAV_ICON_BOX - 10))
    painter.end()
    return QIcon(pixmap)


def navigation_icon_size() -> int:
    return NAV_ICON_BOX if NAV_EMPHASIS == "trial" else ICON_MD


def _navigation_styles() -> str:
    if NAV_EMPHASIS == "quiet":
        return "QPushButton#navButton:checked { border: none; }"
    c = COLORS
    return f"""
QPushButton#navButton {{
    border: none;
    border-radius: 10px;
    min-height: 44px;
    max-height: 44px;
    padding: 8px 8px 8px 10px;
    margin: 1px 0;
}}
QPushButton#navButton:hover {{ background-color: {c.primary_soft}; }}
QPushButton#navButton:checked {{
    background-color: {c.primary_soft_hover};
    color: {c.primary_strong};
}}
QPushButton#navButton[navAccent="home"]:hover {{ background-color: #fff7ed; }}
QPushButton#navButton[navAccent="home"]:checked {{ background-color: #ffedd5; }}
QPushButton#navButton[navAccent="images"]:hover {{ background-color: {c.info_soft}; }}
QPushButton#navButton[navAccent="images"]:checked {{ background-color: {c.info_soft_hover}; }}
QPushButton#navButton[navAccent="organize"]:hover {{ background-color: {c.primary_soft}; }}
QPushButton#navButton[navAccent="organize"]:checked {{ background-color: {c.primary_soft_hover}; }}
QPushButton#navButton[navAccent="tags"]:hover {{ background-color: {c.tag_soft}; }}
QPushButton#navButton[navAccent="tags"]:checked {{ background-color: #fce7f3; }}
QPushButton#navButton[navAccent="settings"]:hover {{ background-color: #f1f5f9; }}
QPushButton#navButton[navAccent="settings"]:checked {{ background-color: #e2e8f0; }}
QPushButton#navButton[navAccent="about"]:hover {{ background-color: #f0fdfa; }}
QPushButton#navButton[navAccent="about"]:checked {{ background-color: #ccfbf1; }}
"""


def token_style_sheet() -> str:
    """Targeted v1 trial overrides appended after the legacy stylesheet."""
    c = COLORS
    return f"""
/* ===== Design Guidelines v1 trial tokens ===== */
QMainWindow, QWidget#appShell, QWidget#appContent {{
    background-color: {c.app_bg};
    color: {c.text};
}}
QFrame#sidebar {{
    background-color: {c.surface};
    border-right: 1px solid #dbe3ec;
}}
QLabel#pageTitle,
QWidget#imagesPageHeader QLabel#pageTitle {{ color: {c.text_strong}; }}
QLabel#pageSubtitle,
QWidget#imagesPageHeader QLabel#pageSubtitle {{ color: {c.text_muted}; }}
QWidget#imagesWorkspacePage QLabel#pageTitle {{ color: {c.info_strong}; }}
QWidget#imagesWorkspacePage QLabel#pageSubtitle {{ color: {c.info}; }}
QFrame#pageHeaderSymbol {{
    background-color: {c.primary_soft};
    border: 1px solid #bfdbfe;
    border-radius: {RADIUS_MD}px;
}}
QFrame#pageHeaderSymbol[accent="information"] {{
    background-color: {c.info_soft_hover};
    border-color: #67e8f9;
}}
QFrame#pageHeaderSymbol[hero="true"] {{
    background: transparent;
    border: none;
}}
QFrame#pageHeaderSymbolShape {{
    background-color: {c.info_soft_hover};
    border: 1px solid #a5f3fc;
    border-radius: {PAGE_HEADER_SYMBOL_RADIUS}px;
}}
QFrame#pageHeaderSymbolGlow {{
    background-color: {c.primary_soft_hover};
    border: none;
    border-radius: {PAGE_HEADER_SYMBOL_RADIUS}px;
}}
QFrame#pageHeaderSymbolDot {{
    background-color: #ddd6fe;
    border: 1px solid #c4b5fd;
    border-radius: {RADIUS_CONTROL}px;
}}
QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget > QWidget,
QWidget#homeContentColumn,
QWidget#imagesWorkspacePage,
QWidget#imagesWorkspaceBody,
QWidget#organizePage,
QWidget#organizeBody,
QWidget#tagsContentColumn,
QWidget#settingsContentColumn,
QWidget#aboutContentColumn,
QWidget#pageHeader,
QWidget#pageHeaderText {{
    background-color: {c.app_bg};
    border: none;
}}
QWidget#pageHeader QLabel {{
    background: transparent;
}}
QSplitter#imagesSplitter,
QWidget#imagesLeftWorkspace,
QStackedWidget#imagesListStack,
QWidget#previewPaneScrollHost,
QScrollArea#previewPaneScroll > QWidget > QWidget {{
    background-color: {c.app_bg};
    border: none;
}}
QWidget#leftPanel,
QWidget#folderPanel, QWidget#folderPanelCollapsed,
QFrame#previewCard {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QStackedWidget#imagesListStack {{
    background-color: {c.surface};
    border: none;
}}
QWidget#leftPanel QWidget#sectionHeader,
QWidget#leftPanel QWidget#sectionHeaderTitleRow,
QWidget#leftPanel QWidget#sectionHeaderTitleRow QLabel {{
    background-color: {c.surface};
}}
QWidget#rightPanel {{
    background: transparent;
    border: none;
}}
QFrame#imagesCommandSurface {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#imagesCommandPrimaryRow,
QWidget#imagesCommandSecondaryRow {{ background: transparent; }}
QFrame#folderSelectorBar {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#folderSelectorBar QLabel {{ color: {c.text_secondary}; }}
QFrame#folderSelectorBar QLabel#folderSelectorPath {{
    color: {c.text};
    font-weight: 600;
}}
QLineEdit, QComboBox {{ border-color: {c.border_strong}; border-radius: {RADIUS_CONTROL}px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {c.primary}; }}
QWidget#screenshotsSearchRow QLineEdit,
QLineEdit#screenshotsSearchInput {{
    background-color: {c.surface};
    border: 1px solid {c.border_strong};
    border-radius: {RADIUS_MD}px;
}}
QWidget#screenshotsSearchRow QLineEdit:focus,
QLineEdit#screenshotsSearchInput:focus {{ border-color: {c.primary}; }}
QWidget#screenshotsSearchRow QPushButton {{
    min-height: {CONTROL_STANDARD}px;
    max-height: {CONTROL_STANDARD}px;
    border-radius: {RADIUS_CONTROL}px;
}}
QFrame#imagesAnalysisBar {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#imagesAnalysisBar QLabel#mutedLabel {{ color: {c.info_strong}; }}
QFrame#imagesAnalysisBar QPushButton {{
    min-height: {CONTROL_COMPACT}px;
    max-height: {CONTROL_COMPACT}px;
    border-radius: {RADIUS_CONTROL}px;
    font-size: 11px;
}}
QWidget#leftPanel QListWidget#screenshotList {{
    background-color: {c.surface};
    border: 1px solid {c.border};
    border-radius: 10px;
    padding: 4px;
}}
QWidget#leftPanel QListWidget#screenshotList > QWidget {{
    background-color: {c.surface};
    border-radius: 9px;
}}
QDialog#welcomeDialog {{ background-color: {c.surface}; }}
QDialog#welcomeDialog QLabel#welcomeTitle {{
    color: {c.text_strong};
    font-size: 20px;
    font-weight: 600;
}}
QDialog#welcomeDialog QLabel#welcomeSubtitle {{
    color: {c.text_secondary};
    font-size: 13px;
}}
QDialog#welcomeDialog QFrame#welcomeStepCard {{
    background-color: {c.surface_subtle};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QDialog#welcomeDialog QLabel#welcomeStepNumber {{
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    background-color: {c.info_soft};
    border-radius: {RADIUS_CONTROL}px;
}}
QDialog#welcomeDialog QLabel#welcomeStepTitle {{
    color: {c.text_strong};
    font-size: 13px;
    font-weight: 600;
}}
QDialog#welcomeDialog QLabel#welcomeStepBody {{
    color: {c.text_secondary};
    font-size: 12px;
}}
QPushButton#welcomePrimaryButton {{
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
}}
QLabel#galleryItemCount {{
    color: {c.text_muted};
    font-size: 11px;
    font-weight: 600;
}}
QFrame#previewCard[cardRole="preview"],
QFrame#previewCard[cardRole="information"],
QFrame#previewCard[cardRole="tags"] {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#previewCard[cardRole="preview"] QScrollArea#previewImageView {{
    background-color: {c.surface_subtle};
    border-radius: {RADIUS_MD}px;
}}
QWidget#sectionHeader QLabel#sectionTitle {{
    color: {c.text_strong};
    font-size: 13px;
    font-weight: 700;
}}
QFrame#sectionDivider {{ background-color: {c.border}; border: none; }}
QFrame#currentTagChip {{ background-color: #fae8ff; border-color: #f0abfc; }}
QFrame#currentTagChip[selected="true"] {{ background-color: #f5d0fe; border-color: {c.tag}; }}
QLabel#currentTagChipLabel {{ color: #9d174d; }}
QWidget#globalBottomBar {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#captureBarControlsRow {{
    background: transparent;
    border: none;
}}
QWidget#captureBarTitleRow {{
    background: transparent;
    border: none;
}}
QLabel#captureBarTitleIcon {{
    background: transparent;
    border: none;
}}
QLabel#captureBarTitle {{
    color: {c.text_strong};
    font-size: 15px;
    font-weight: 600;
}}
QFrame#captureSettingsStrip {{
    background-color: {c.surface_subtle};
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
}}
QWidget#captureSettingsFlatStrip {{
    background: transparent;
    border: none;
}}
QWidget#captureFlatField {{ background: transparent; border: none; }}
QComboBox#captureFlatCombo,
QPushButton#captureSaveFolderButton {{
    background-color: {c.surface_sunken};
    color: {c.primary_strong};
    border: 1px solid {c.border_strong};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 30px;
    max-height: 30px;
    padding: 0 24px 0 8px;
    font-size: 10px;
    font-weight: 600;
}}
QComboBox#captureFlatCombo[empty="true"] {{ color: {c.text_muted}; }}
QComboBox#captureFlatCombo:hover,
QPushButton#captureSaveFolderButton:hover {{
    background-color: {c.primary_soft};
    border-color: #93c5fd;
}}
QPushButton#captureSaveFolderButton {{
    text-align: left;
    padding-left: 8px;
    padding-right: 8px;
}}
QScrollArea#captureSettingsScroll {{
    background: transparent;
    border: none;
}}
QWidget#captureModeSelector {{ background: transparent; }}
QWidget#captureActionField {{ background: transparent; border: none; }}
QWidget#captureEdgeActionField {{ background: transparent; border: none; }}
QLabel#captureModeSelectorLabel {{
    color: {c.text_secondary};
    font-size: 11px;
    font-weight: 700;
}}
QFrame#captureModeSegments {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border_strong};
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton#captureModeSegment {{
    background: transparent;
    color: {c.text_secondary};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    min-height: 22px;
    max-height: 22px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#captureModeSegment:hover {{
    background-color: {c.primary_soft};
    color: {c.primary_strong};
}}
QPushButton#captureModeSegment[captureMode="region"] {{
    color: {c.primary_strong};
}}
QPushButton#captureModeSegment[captureMode="region"]:hover {{
    background-color: {c.primary_soft};
}}
QPushButton#captureModeSegment[captureMode="region"]:checked {{
    background-color: {c.primary_soft};
    color: {c.primary};
    border-color: {c.primary};
}}
QPushButton#captureModeSegment[captureMode="fullscreen"] {{
    color: {c.primary_strong};
}}
QPushButton#captureModeSegment[captureMode="fullscreen"]:hover {{
    background-color: {c.primary_soft};
}}
QPushButton#captureModeSegment[captureMode="fullscreen"]:checked {{
    background-color: {c.primary_soft};
    color: {c.primary};
    border-color: {c.primary};
}}
QPushButton#captureBarToggleButton {{
    background-color: {c.surface_subtle};
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    font-family: "Segoe UI";
    font-size: 13px;
}}
QPushButton#captureBarToggleButton:hover {{
    background-color: {c.primary_soft};
    color: {c.primary_strong};
}}
QPushButton#capturePanelPopOutButton {{
    background-color: {c.primary_soft};
    color: {c.primary_strong};
    border: 1px solid #93c5fd;
    border-radius: 10px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0;
}}
QPushButton#capturePanelPopOutButton:hover {{
    background-color: {c.primary_soft};
    color: {c.primary_strong};
    border-color: #bfdbfe;
}}
QToolButton#regionCaptureButton,
QToolButton#fullScreenCaptureButton {{
    background-color: {c.primary_soft};
    color: {c.primary};
    border: 1px solid #93c5fd;
    padding: 5px 6px;
    border-radius: {RADIUS_MD}px;
    font-size: 8px;
}}
QToolButton#regionCaptureButton:hover,
QToolButton#fullScreenCaptureButton:hover {{
    background-color: {c.primary_soft_hover};
    color: {c.primary_strong};
    border-color: {c.primary_strong};
}}
QToolButton#regionCaptureButton:pressed,
QToolButton#fullScreenCaptureButton:pressed {{
    background-color: {c.primary_soft_hover};
    color: {c.primary_strong};
    border-color: {c.primary_strong};
}}
{_navigation_styles()}
"""
