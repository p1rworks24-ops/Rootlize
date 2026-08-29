"""Capixe visual language: quiet optical surfaces, not pastel chrome."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPixmap, QRegion
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


@dataclass(frozen=True)
class Colors:
    # Canvas / shell — calm ChatGPT-like neutrals, not cool-blue gray.
    app_bg: str = "#f7f7f8"
    app_bg_end: str = "#f2f3f5"
    panel_bg: str = "#f2f3f5"
    # Content / elevation
    surface: str = "#fcfcfd"
    card_bg: str = "#ffffff"
    surface_raised: str = "#ffffff"
    surface_subtle: str = "#f7f7f8"
    surface_sunken: str = "#f2f3f5"
    surface_hover: str = "#eceef1"
    surface_selected: str = "#e5e7eb"
    input_bg: str = "#ffffff"
    surface_glass: str = "rgba(252, 252, 253, 230)"
    text_strong: str = "#111827"
    text: str = "#1f2937"
    text_secondary: str = "#4b5563"
    text_muted: str = "#6b7280"
    text_faint: str = "#9ca3af"
    text_on_ink: str = "#f9fafb"
    border: str = "#e5e7eb"
    border_subtle: str = "#e5e7eb"
    border_strong: str = "#d1d5db"
    card_border: str = "#e5e7eb"
    hairline: str = "rgba(17, 24, 39, 0.08)"
    primary: str = "#1c1f26"
    primary_strong: str = "#111318"
    primary_soft: str = "#f3f4f6"
    primary_soft_hover: str = "#eceef1"
    accent: str = "#6b7c99"
    accent_strong: str = "#4d5c75"
    accent_soft: str = "#eef2f7"
    accent_ring: str = "rgba(37, 99, 235, 0.35)"
    info: str = "#5c6b82"
    info_strong: str = "#3d4a63"
    info_soft: str = "#f4f6f9"
    info_soft_hover: str = "#eceef1"
    trigger: str = "#c2410c"
    trigger_soft: str = "#fff7ed"
    select: str = "#6d28d9"
    select_soft: str = "#f3e8ff"
    target: str = "#2563eb"
    target_soft: str = "#eff6ff"
    ai: str = "#252536"
    ai_soft: str = "#f4f4f6"
    tag: str = "#4a5160"
    tag_soft: str = "#f3f4f6"
    success: str = "#047857"
    success_soft: str = "#ecfdf5"
    warning: str = "#b45309"
    warning_soft: str = "#fffbeb"
    error: str = "#b91c1c"
    error_soft: str = "#fef2f2"
    chat_user_bg: str = "#dbeafe"
    chat_user_border: str = "#93c5fd"
    chat_assistant_bg: str = "#ffffff"


COLORS = Colors()

# Board is a sunken well so white puzzle blocks read against the page, like Images cards.
WORKFLOW_BOARD_BG = COLORS.surface_hover
WORKFLOW_PANE_BG = COLORS.card_bg
WORKFLOW_CARD_LINE = "#d1d5db"
WORKFLOW_BLOCK_LINE = "#c5c9d1"

# Image Favorite star — shared by Grid cards and List rows
FAVORITE_STAR_CHECKED = "#c5921a"
FAVORITE_STAR_CHECKED_SOFT = (197, 146, 26, 42)
FAVORITE_STAR_UNCHECKED = "#b7bec8"
FAVORITE_STAR_UNCHECKED_HOVER = "#7b8494"
FAVORITE_STAR_VISUAL = 18
FAVORITE_STAR_HIT = 28
FAVORITE_LIST_ACTION_WIDTH = 32

# Show Tags and other compact Capixe checkboxes
CHECKBOX_SIZE = 15
CHECKBOX_RADIUS = 3
CHECKBOX_BORDER = "#94a3b8"
CHECKBOX_BORDER_HOVER = COLORS.accent
CHECKBOX_BORDER_PRESSED = COLORS.accent_strong
CHECKBOX_BORDER_CHECKED = COLORS.accent_strong
CHECKBOX_CHECK = COLORS.accent_strong
CHECKBOX_FILL = COLORS.input_bg
CHECKBOX_FILL_PRESSED = COLORS.surface_sunken
CHECKBOX_FOCUS = COLORS.accent

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
AUTOMATION_LIST_HEADER_PAD = 10
AUTOMATION_LIST_RUN_HEADER_PAD = 16
RADIUS_SM = 6
RADIUS_CONTROL = 8
RADIUS_MD = 10
RADIUS_CARD = 16
RADIUS_SEARCH = 14
RADIUS_PILL = 999
CONTROL_COMPACT = 28
CONTROL_STANDARD = 32
MOTION_FAST_MS = 120
MOTION_NORMAL_MS = 180
MOTION_SLOW_MS = 240
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
CAPTURE_BUTTON_WIDTH = 148
CAPTURE_BUTTON_HEIGHT = CONTROL_STANDARD
CAPTURE_EDGE_BUTTON_HEIGHT = CONTROL_STANDARD
CAPTURE_TOGGLE_WIDTH = CONTROL_STANDARD
CAPTURE_MODE_SELECTOR_WIDTH = 128
CAPTURE_MODE_REGION_WIDTH = 62
CAPTURE_MODE_FULLSCREEN_WIDTH = 62
CAPTURE_BAR_PADDING_X = SPACE_3
CAPTURE_BAR_PADDING_Y = SPACE_3
CAPTURE_BAR_ITEM_GAP = SPACE_3
CAPTURE_FIELD_LABEL_GAP = SPACE_1
CAPTURE_FIELD_TITLE_HEIGHT = 16
CAPTURE_FIELD_HEIGHT = 52
CAPTURE_FIELD_FOLDER_MIN_WIDTH = 120
CAPTURE_FIELD_FILENAME_MIN_WIDTH = 140
CAPTURE_FIELD_TAGS_MIN_WIDTH = 120
NAV_UTILITY_HEIGHT = 36
NAV_UTILITY_ICON = 18
NAV_PADDING_X = 14
NAV_PADDING_Y = 18
NAV_ITEM_GAP = 6
NAV_EXPANDED_WIDTH = 216
NAV_COLLAPSED_WIDTH = 64
NAV_COLLAPSED_PADDING_X = 8
NAV_RESPONSIVE_BREAKPOINT = 900
WORKSPACE_PADDING = 20
WORKSPACE_GAP = 14
WORKSPACE_PANEL_PADDING = 16
IMAGES_FOLDER_LOCATOR_MIN_WIDTH = 220
IMAGES_FOLDER_LOCATOR_MAX_WIDTH = 16777215
IMAGES_RIGHT_PANEL_DEFAULT_WIDTH = 392
IMAGES_RIGHT_PANEL_MIN_WIDTH = 328
IMAGES_RIGHT_PANEL_MAX_WIDTH = 560
IMAGES_AI_PANEL_DEFAULT_WIDTH = 456
IMAGES_AI_PANEL_MIN_WIDTH = 400
IMAGES_PREVIEW_IMAGE_MIN_HEIGHT = 148
IMAGES_PREVIEW_IMAGE_MAX_HEIGHT = 228
IMAGES_LEFT_CARD_PAD_X = 10
IMAGES_LEFT_CARD_PAD_Y = 8
IMAGES_COMMAND_GAP = 8

SHADOW_MODE = "soft"
NAV_EMPHASIS = "trial"
NAV_HOVER_BG = COLORS.surface_hover
NAV_ACTIVE_BG = COLORS.surface_selected
NAV_ACTIVE_TEXT = COLORS.accent_strong
NAV_ACTIVE_ICON = COLORS.accent_strong

_SHADOW_PRESETS = {
    "card": (24, 0, 4, QColor(17, 24, 39, 14)),
    "search": (24, 0, 4, QColor(17, 24, 39, 14)),
    "panel": (24, 0, 4, QColor(17, 24, 39, 14)),
    "floating": (28, 0, 8, QColor(17, 24, 39, 22)),
    "ai": (24, 0, 4, QColor(17, 24, 39, 14)),
}


def apply_card_shadow(
    widget: QWidget,
    *,
    blue_tinted: bool = False,
    role: str = "card",
) -> None:
    """Wide, soft elevation. `blue_tinted` is kept for callers and ignored."""
    del blue_tinted
    if SHADOW_MODE == "off":
        widget.setGraphicsEffect(None)
        return
    blur, offset_x, offset_y, color = _SHADOW_PRESETS.get(role, _SHADOW_PRESETS["card"])
    if SHADOW_MODE == "weak":
        blur = max(16, blur - 10)
        offset_y = max(2, offset_y - 3)
        color = QColor(color.red(), color.green(), color.blue(), max(10, color.alpha() - 6))
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(offset_x, offset_y)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def navigation_icon(icon: QIcon, accent: str) -> QIcon:
    """Keep nav glyphs on one quiet tile. Accent is unused on purpose."""
    del accent
    if NAV_EMPHASIS == "quiet" or icon.isNull():
        return icon
    pixmap = QPixmap(NAV_ICON_BOX, NAV_ICON_BOX)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(COLORS.surface_sunken))
    painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -1, -1), 8, 8)
    icon.paint(painter, QRect(5, 5, NAV_ICON_BOX - 10, NAV_ICON_BOX - 10))
    painter.end()
    return QIcon(pixmap)


def navigation_icon_size() -> int:
    return NAV_ICON_BOX if NAV_EMPHASIS == "trial" else ICON_MD


def _app_gradient() -> str:
    c = COLORS
    return (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {c.app_bg}, stop:1 {c.app_bg_end})"
    )


def apply_product_palette(widget: QWidget) -> None:
    """Keep native roles (placeholder, selection) aligned with surface tokens."""
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(COLORS.app_bg))
    pal.setColor(QPalette.ColorRole.Base, QColor(COLORS.input_bg))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS.surface_subtle))
    pal.setColor(QPalette.ColorRole.Button, QColor(COLORS.surface_raised))
    pal.setColor(QPalette.ColorRole.Text, QColor(COLORS.text))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(COLORS.text))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS.text_faint))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(COLORS.target_soft))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS.text_strong))
    widget.setPalette(pal)


def paint_canvas(widget: QWidget, fill: str | None = None) -> None:
    """Fill every pixel so Windows never shows the native black backing store."""
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setAttribute(Qt.WA_OpaquePaintEvent, True)
    widget.setAutoFillBackground(True)
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(fill or COLORS.app_bg))
    widget.setPalette(pal)


def clip_rounded(widget: QWidget, radius: int) -> None:
    """Clip children to a rounded rect so borders are not squared off."""
    rect = widget.rect()
    if rect.width() <= 2 or rect.height() <= 2:
        widget.clearMask()
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), float(radius), float(radius))
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


def _navigation_styles() -> str:
    if NAV_EMPHASIS == "quiet":
        return "QPushButton#navButton:checked { border: none; }"
    c = COLORS
    accents = (
        "home",
        "images",
        "organize",
        "tags",
        "settings",
        "automation",
        "about",
        "favorites",
        "recent",
        "ai",
    )
    accent_rules = []
    for name in accents:
        accent_rules.append(
            f"""
QPushButton#navButton[navAccent="{name}"]:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
}}
QPushButton#navButton[navAccent="{name}"]:checked,
QPushButton#navButton[navAccent="{name}"]:checked:hover {{
    background-color: {NAV_ACTIVE_BG};
    color: {NAV_ACTIVE_TEXT};
    border: none;
}}
"""
        )
    return f"""
QPushButton#navButton {{
    border: none;
    border-radius: 12px;
    min-height: 44px;
    max-height: 44px;
    padding: 8px 10px 8px 10px;
    margin: 1px 0;
    color: {c.text_secondary};
    background: transparent;
    font-weight: 500;
    letter-spacing: 0.01em;
}}
QPushButton#navButton:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
}}
QPushButton#navButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#navButton:checked,
QPushButton#navButton:checked:hover,
QPushButton#navButton[collapsed="true"]:checked,
QPushButton#navButton[collapsed="true"]:checked:hover {{
    background-color: {NAV_ACTIVE_BG};
    color: {NAV_ACTIVE_TEXT};
    border: none;
}}
QPushButton#navButton:disabled {{
    color: {c.text_faint};
    background: transparent;
}}
QPushButton#navButton[collapsed="true"] {{
    padding: 8px 4px;
    margin: 1px 0;
    text-align: center;
}}
QPushButton#navUtilityButton {{
    border: none;
    border-radius: 10px;
    min-height: {NAV_UTILITY_HEIGHT}px;
    max-height: {NAV_UTILITY_HEIGHT}px;
    padding: 6px 10px 6px 10px;
    margin: 1px 0;
    color: {c.text_secondary};
    background: transparent;
    font-weight: 500;
    letter-spacing: 0.01em;
    text-align: left;
}}
QPushButton#navUtilityButton:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
}}
QPushButton#navUtilityButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#navUtilityButton[utilityActive="true"],
QPushButton#navUtilityButton[utilityActive="true"]:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
    border: none;
}}
QPushButton#navUtilityButton:disabled {{
    color: {c.text_faint};
    background: transparent;
}}
QPushButton#navUtilityButton[collapsed="true"] {{
    padding: 6px 4px;
    margin: 1px 0;
    text-align: center;
}}
QWidget#navUtilityGroup {{
    background: transparent;
    border: none;
}}
QFrame#navUtilityDivider {{
    background-color: {c.hairline};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
{''.join(accent_rules)}
"""


def token_style_sheet() -> str:
    """Targeted token layer appended after the legacy stylesheet."""
    c = COLORS
    return f"""
/* ===== Design Guidelines v1 trial tokens ===== */
QMainWindow, QWidget#appShell, QWidget#appContent {{
    background-color: {c.app_bg};
    color: {c.text};
}}
QFrame#sidebar {{
    background-color: {c.panel_bg};
    border-right: 1px solid {c.border_subtle};
}}
QLabel#pageTitle,
QWidget#imagesPageHeader QLabel#pageTitle,
QWidget#imagesWorkspacePage QLabel#pageTitle,
QWidget#homeContentColumn QLabel#pageTitle,
QWidget#organizePage QLabel#pageTitle,
QWidget#settingsContentColumn QLabel#pageTitle,
QWidget#tagsContentColumn QLabel#pageTitle,
QWidget#aboutContentColumn QLabel#pageTitle {{
    color: {c.text_strong};
    letter-spacing: -0.3px;
}}
QLabel#pageSubtitle,
QWidget#imagesPageHeader QLabel#pageSubtitle,
QWidget#imagesWorkspacePage QLabel#pageSubtitle,
QWidget#homeContentColumn QLabel#pageSubtitle,
QWidget#organizePage QLabel#pageSubtitle,
QWidget#settingsContentColumn QLabel#pageSubtitle,
QWidget#tagsContentColumn QLabel#pageSubtitle,
QWidget#aboutContentColumn QLabel#pageSubtitle {{
    color: {c.text_muted};
}}
QFrame#pageHeaderSymbol {{
    background-color: {c.accent_soft};
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#pageHeaderSymbol[accent="information"] {{
    background-color: {c.info_soft_hover};
    border-color: {c.border};
}}
QFrame#pageHeaderSymbol[hero="true"] {{
    background: transparent;
    border: none;
}}
QFrame#pageHeaderSymbolShape {{
    background-color: {c.info_soft_hover};
    border: 1px solid {c.border};
    border-radius: {PAGE_HEADER_SYMBOL_RADIUS}px;
}}
QFrame#pageHeaderSymbolGlow {{
    background-color: {c.accent_soft};
    border: none;
    border-radius: {PAGE_HEADER_SYMBOL_RADIUS}px;
}}
QFrame#pageHeaderSymbolDot {{
    background-color: {c.primary_soft_hover};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget,
QScrollArea#pageScroll > QWidget > QWidget,
QWidget#homeContentColumn,
QWidget#imagesWorkspacePage,
QWidget#imagesWorkspaceBody,
QWidget#organizePage,
QWidget#organizeBody,
QWidget#tagsContentColumn,
QWidget#settingsContentColumn,
QWidget#aboutContentColumn {{
    background-color: {c.app_bg};
    border: none;
}}
QWidget#pageHeader,
QWidget#pageHeaderText {{
    background-color: transparent;
    border: none;
}}
QWidget#pageHeader QLabel {{
    background: transparent;
}}
QSplitter#imagesSplitter,
QWidget#imagesLeftWorkspace,
QStackedWidget#imagesListStack,
QWidget#imagesGalleryBody,
QWidget#previewPaneScrollHost,
QScrollArea#previewPaneScroll > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}
QWidget#folderPanel, QWidget#folderPanelCollapsed {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#leftPanel,
QFrame#leftPanel {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#imagesResultsHeader {{
    background-color: {c.surface_subtle};
    border: none;
    border-top-left-radius: {RADIUS_CARD}px;
    border-top-right-radius: {RADIUS_CARD}px;
}}
QWidget#imagesResultsHeader QWidget#searchStatusRow,
QWidget#imagesResultsHeader QWidget#headerToolField,
QWidget#imagesResultsHeader QFrame#headerTools,
QWidget#imagesResultsHeader QWidget#headerTools {{
    background: transparent;
    border: none;
}}
QFrame#emptyHintCard {{
    background: transparent;
    border: none;
}}
QLabel#emptyHintTitle {{
    color: {c.text_strong};
}}
QLabel#emptyHintBody {{
    color: {c.text_secondary};
}}
QLabel#emptyHintMeta {{
    color: {c.text_muted};
}}
QStackedWidget#imagesListStack {{
    background: transparent;
    border: none;
}}
QWidget#leftPanel QWidget#sectionHeader,
QWidget#leftPanel QWidget#sectionHeaderTitleRow,
QWidget#leftPanel QWidget#sectionHeaderTitleRow QLabel {{
    background-color: transparent;
}}
QWidget#rightPanel {{
    background: transparent;
    border: none;
}}
QFrame#imagesCommandSurface {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#imagesCommandPrimaryRow,
QWidget#imagesCommandSecondaryRow,
QWidget#screenshotsSearchRow,
QWidget#searchHeaderRow,
QLabel#searchShellGlyph {{
    background: transparent;
    border: none;
}}
QFrame#folderSelectorBar {{
    background: transparent;
    border: none;
}}
QFrame#folderBrowser {{
    background-color: {c.surface_glass};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#folderSelectorBar QLabel {{ color: {c.text_secondary}; }}
QFrame#folderSelectorBar QLabel#folderSelectorPath {{
    color: {c.text};
}}
QLineEdit, QComboBox {{
    border-color: {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c.target}; }}
QWidget#screenshotsSearchRow QLineEdit,
QLineEdit#screenshotsSearchInput {{
    background-color: transparent;
    border: none;
    min-height: 30px;
    max-height: 34px;
}}
QWidget#screenshotsSearchRow QLineEdit:focus,
QLineEdit#screenshotsSearchInput:focus {{ border: none; }}
QPushButton#imagesPrimarySearchButton {{
    min-width: 88px;
    border-radius: {RADIUS_SEARCH}px;
}}
QFrame#imagesAnalysisBar {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#imagesAnalysisBar QLabel#mutedLabel {{ color: {c.info_strong}; }}
QFrame#imagesAnalysisBar QLabel#analysisStatusChip {{
    color: {c.text_muted};
    background-color: {c.surface_subtle};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CARD}px;
    padding: 2px 6px;
}}
QFrame#imagesAnalysisBar QPushButton {{
    min-height: {CONTROL_COMPACT}px;
    max-height: {CONTROL_COMPACT}px;
    border-radius: {RADIUS_CONTROL}px;
}}
QWidget#leftPanel QListWidget#screenshotList {{
    background: transparent;
    border: none;
    padding: 4px;
}}
QWidget#leftPanel QListWidget#screenshotList > QWidget {{
    background: transparent;
    border-radius: 14px;
}}
QDialog#welcomeDialog {{ background-color: {c.card_bg}; }}
QDialog#welcomeDialog QLabel#welcomeTitle {{
    color: {c.text_strong};
}}
QDialog#welcomeDialog QLabel#welcomeSubtitle {{
    color: {c.text_secondary};
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
}}
QDialog#welcomeDialog QLabel#welcomeStepBody {{
    color: {c.text_secondary};
}}
QPushButton#welcomePrimaryButton,
QPushButton#accountSignInButton {{
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
}}
QPushButton#accountGoogleButton,
QPushButton#accountGitHubButton,
QPushButton#accountCreateButton,
QPushButton#accountSignOutButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
}}
QPushButton#accountGoogleButton:hover,
QPushButton#accountGitHubButton:hover,
QPushButton#accountCreateButton:hover,
QPushButton#accountSignOutButton:hover {{
    background-color: {c.surface_hover};
    border-color: {c.border_strong};
}}
QLineEdit#accountEmailInput,
QLineEdit#accountPasswordInput {{
    min-height: {CONTROL_STANDARD}px;
}}
QLabel#accountEmailLabel,
QLabel#accountPlanLabel {{
    color: {c.text_strong};
}}
QLabel#accountStatusLabel {{
    color: {c.text_secondary};
}}
QDialog#askAiConsentDialog {{ background-color: {c.card_bg}; }}
QDialog#askAiConsentDialog QScrollArea#askAiConsentScroll,
QDialog#askAiConsentDialog QScrollArea#askAiConsentScroll > QWidget,
QDialog#askAiConsentDialog QWidget#askAiConsentBody {{
    background-color: {c.card_bg};
    border: none;
}}
QDialog#askAiConsentDialog QLabel#askAiConsentTitle {{
    color: {c.text_strong};
}}
QDialog#askAiConsentDialog QLabel#askAiConsentSubtitle,
QDialog#askAiConsentDialog QLabel#askAiConsentFootnote {{
    color: {c.text_secondary};
}}
QDialog#askAiConsentDialog QLabel#askAiConsentSectionTitle {{
    color: {c.text_strong};
    font-weight: 600;
}}
QDialog#askAiConsentDialog QFrame#askAiConsentFactCard {{
    background-color: {c.surface_subtle};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QPushButton#askAiConsentPrimaryButton {{
    background-color: {c.target};
    color: #ffffff;
    border: 1px solid {c.target};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#askAiConsentPrimaryButton:hover {{
    background-color: #1d4ed8;
    border-color: #1d4ed8;
    color: #ffffff;
}}
QPushButton#askAiConsentPrimaryButton:pressed {{
    background-color: #1e40af;
    border-color: #1e40af;
    color: #ffffff;
}}
QDialog#askAiConsentDialog QLabel#askAiConsentFactTitle {{
    color: {c.text_strong};
}}
QDialog#askAiConsentDialog QLabel#askAiConsentFactBody {{
    color: {c.text_secondary};
}}
QDialog#askAiConsentDialog QLabel#askAiConsentExample {{
    color: {c.text};
    font-family: Consolas, "Cascadia Mono", "Segoe UI Mono", monospace;
}}
QDialog#automationRunDialog,
QDialog#automationSaveDialog {{
    background-color: {c.card_bg};
}}
QDialog#automationRunDialog QLabel#automationRunTitle {{
    color: {c.text_strong};
    font-size: 16px;
    font-weight: 700;
}}
QDialog#automationRunDialog QLabel#automationRunHeading {{
    color: {c.text};
    font-size: 13px;
    font-weight: 600;
}}
QDialog#automationRunDialog QLabel#automationRunHint,
QDialog#automationRunDialog QLabel#automationRunFootnote {{
    color: {c.text_secondary};
}}
QDialog#automationRunDialog QFrame#automationRunSummaryCard {{
    background-color: {c.surface_subtle};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QDialog#automationRunDialog QLabel#automationRunCaption {{
    color: {c.text_muted};
    font-size: 11px;
    font-weight: 600;
}}
QDialog#automationRunDialog QLabel#automationRunStepLabel {{
    color: {c.text_strong};
    font-size: 12px;
    font-weight: 600;
}}
QDialog#automationRunDialog QLabel#automationRunStepBody {{
    color: {c.text_secondary};
    font-size: 12px;
}}
QPushButton#automationRunConfirm {{
    background-color: {c.target};
    color: {c.text_on_ink};
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#automationRunConfirm:hover {{
    background-color: #1d4ed8;
}}
QPushButton#automationRunConfirm:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
}}
QPushButton#automationRunCancel {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
}}
QPushButton#automationRunCancel:hover {{
    background-color: {c.surface_subtle};
    border-color: {c.accent};
}}
QLabel#galleryItemCount {{
    color: {c.text_strong};
    letter-spacing: -0.2px;
}}
QFrame#previewCard {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#previewCard[cardRole="preview"],
QFrame#previewCard[cardRole="information"],
QFrame#previewCard[cardRole="tags"] {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#previewCard[cardRole="preview"] QScrollArea#previewImageView {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
}}
QWidget#previewInfoSection {{
    background: transparent;
    border: none;
}}
QFrame#analysisRetryBar {{
    background-color: {c.warning_soft};
    border: 1px solid #f3e0c8;
    border-radius: {RADIUS_MD}px;
}}
QLabel#analysisRetryLabel {{
    color: {c.warning};
}}
QPushButton#analysisRetryButton {{
    background-color: {c.warning_soft};
    border: 1px solid #f3e0c8;
    border-radius: {RADIUS_MD}px;
    color: {c.warning};
    min-height: 28px;
    max-height: 28px;
    padding: 0 12px;
}}
QWidget#sectionHeader QLabel#sectionTitle {{
    color: {c.text_strong};
    letter-spacing: 0.01em;
}}
QFrame#sectionDivider {{ background-color: {c.border}; border: none; }}
QFrame#currentTagChip {{
    background-color: {c.tag_soft};
    border-color: {c.border_strong};
}}
QFrame#currentTagChip[selected="true"] {{
    background-color: {c.accent_soft};
    border-color: {c.accent};
}}
QLabel#currentTagChipLabel {{ color: {c.text_secondary}; }}
QWidget#globalBottomBar {{
    background-color: {c.surface};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#captureBarControlsRow,
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
}}
QFrame#captureSettingsStrip {{
    background: transparent;
    border: none;
}}
QWidget#captureSettingsFlatStrip,
QWidget#captureFlatField {{
    background: transparent;
    border: none;
}}
QComboBox#captureFlatCombo,
QPushButton#captureSaveFolderButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    padding: 0 22px 0 8px;
}}
QComboBox#captureFlatCombo[empty="true"] {{ color: {c.text_faint}; }}
QComboBox#captureFlatCombo:hover,
QPushButton#captureSaveFolderButton:hover {{
    background-color: {c.surface};
    border-color: {c.accent};
}}
QComboBox#captureFlatCombo:focus,
QComboBox#captureFlatCombo:on,
QPushButton#captureSaveFolderButton:pressed {{
    background-color: {c.surface};
    border: 1px solid {c.accent};
}}
QComboBox#captureFlatCombo:disabled,
QPushButton#captureSaveFolderButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border-color: {c.border};
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
QWidget#captureModeSelector,
QWidget#captureActionField,
QWidget#captureEdgeActionField {{
    background: transparent;
    border: none;
}}
QLabel#captureModeSelectorLabel {{
    color: {c.text_secondary};
}}
QFrame#captureModeSegments {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: 10px;
}}
QPushButton#captureModeSegment {{
    background: transparent;
    color: {c.text_muted};
    border: 1px solid transparent;
    border-radius: 8px;
    min-height: 22px;
    max-height: 22px;
    padding: 2px 9px;
}}
QPushButton#captureModeSegment:hover {{
    background-color: {c.surface};
    color: {c.text};
}}
QPushButton#captureModeSegment:pressed {{
    background-color: {c.primary_soft_hover};
    color: {c.text_strong};
}}
QPushButton#captureModeSegment[captureMode="region"]:checked,
QPushButton#captureModeSegment[captureMode="fullscreen"]:checked {{
    background-color: {c.card_bg};
    color: {c.text_strong};
    border-color: {c.border_subtle};
}}
QPushButton#captureBarToggleButton {{
    background: transparent;
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    padding: 0;
    font-family: "Segoe UI";
}}
QPushButton#captureBarToggleButton:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton#captureBarToggleButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#capturePanelPopOutButton {{
    background-color: {c.primary_soft};
    color: {c.primary};
    border: 1px solid {c.border_strong};
    border-radius: 10px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0;
}}
QPushButton#capturePanelPopOutButton:hover {{
    background-color: {c.primary_soft_hover};
    color: {c.primary_strong};
    border-color: {c.accent};
}}
QToolButton#regionCaptureButton,
QToolButton#fullScreenCaptureButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    padding: 0 10px;
    border-radius: {RADIUS_CONTROL}px;
}}
QToolButton#regionCaptureButton:hover,
QToolButton#fullScreenCaptureButton:hover {{
    background-color: {c.surface_subtle};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QToolButton#regionCaptureButton:pressed,
QToolButton#fullScreenCaptureButton:pressed {{
    background-color: {c.primary_soft_hover};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QToolButton#regionCaptureButton:disabled,
QToolButton#fullScreenCaptureButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border-color: {c.border};
}}
{_navigation_styles()}
"""


def _qss_image_url(*parts: str) -> str:
    from app.paths import get_resource_root

    return (get_resource_root().joinpath(*parts)).as_posix()


def product_visual_overlay() -> str:
    """Last-wins product chrome. Keep after typography normalization."""
    c = COLORS
    board = WORKFLOW_BOARD_BG
    card_line = WORKFLOW_CARD_LINE
    chevron = _qss_image_url("resources", "icons", "combo_chevron.svg")
    return f"""
/* ===== Capixe product visual overlay ===== */
QMainWindow, QWidget#appShell, QWidget#appContent {{
    background-color: {c.app_bg};
    color: {c.text};
}}
QStackedWidget#pageStack,
QStackedWidget#pageStack > QWidget,
QStackedWidget#authRootStack,
QStackedWidget#authRootStack > QWidget,
QStackedWidget#automationStack,
QStackedWidget#automationStack > QWidget#automationListPage,
QStackedWidget#rightModeStack,
QWidget#rightModeStack,
QWidget#previewModePage,
QWidget#aiModePage,
QScrollArea#pageScroll,
QScrollArea#pageScroll > QWidget,
QScrollArea#pageScroll > QWidget > QWidget {{
    background-color: {c.app_bg};
}}
QDialog {{
    background-color: {c.card_bg};
    color: {c.text};
}}
QFrame#sidebar {{
    background-color: {c.panel_bg};
    border-right: 1px solid {c.border_subtle};
}}
QLabel {{
    color: {c.text};
    background: transparent;
}}
QLabel#sidebarBrand {{
    color: {c.text_strong};
    background: transparent;
    font-size: 17px;
    font-weight: 600;
    letter-spacing: 0.02em;
}}
QWidget#sidebarBrandWrap {{
    background: transparent;
    border: none;
    min-height: 52px;
}}
QWidget#sidebarBrandBlock {{
    background: transparent;
    border: none;
}}
QWidget#navRestoreWrap {{
    background: transparent;
    border: none;
}}
QScrollArea#navFolderScroll,
QScrollArea#navFolderScroll > QWidget,
QScrollArea#navFolderScroll > QWidget > QWidget,
QWidget#navFolderScrollInner,
QWidget#navFolderSection {{
    background: transparent;
    border: none;
}}
QLabel#navSectionLabel {{
    color: {c.text_faint};
    letter-spacing: 0.12em;
    background: transparent;
}}
QLabel#navSectionEmpty {{
    color: {c.text_faint};
    background: transparent;
}}
QFrame#navFavoritesBranch {{
    background: transparent;
    border: none;
    border-left: 2px solid {c.border_subtle};
    margin-left: 16px;
    padding-left: 8px;
}}
QPushButton#navFavoritesToggle {{
    background: transparent;
    border: none;
    border-radius: 6px;
    min-height: 26px;
    max-height: 26px;
    padding: 0 6px 0 4px;
    margin: 0;
    color: {c.text_muted};
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 0.02em;
    text-align: left;
}}
QPushButton#navFavoritesToggle:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
}}
QPushButton#navFavoritesToggle:checked {{
    background: transparent;
    color: {c.text_muted};
}}
QPushButton#navFavoritesToggle:checked:hover {{
    background-color: {NAV_HOVER_BG};
    color: {c.text_strong};
}}
QPushButton#navUtilityButton {{
    text-align: left;
    padding: 6px 10px 6px 10px;
}}
QPushButton#navUtilityButton[collapsed="true"] {{
    text-align: center;
    padding: 6px 4px;
}}
QLabel#sidebarVersionLabel {{
    color: {c.text_faint};
    background: transparent;
    letter-spacing: 0.02em;
}}
QPushButton#navFolderButton {{
    background: transparent;
    color: {c.text_secondary};
    border: none;
    border-radius: 6px;
    text-align: left;
    padding: 4px 8px 4px 10px;
    font-weight: 500;
}}
QPushButton#navFolderButton:hover {{
    background: transparent;
    color: {c.text_strong};
}}
QPushButton#navFolderButton[currentFolder="true"] {{
    background: transparent;
    color: {c.text_strong};
    font-weight: 600;
}}
QWidget#navFolderRow {{
    background: transparent;
    border: none;
}}
QWidget#navFolderRow[dropEdge="before"] {{
    border-top: 2px solid {c.accent};
}}
QWidget#navFolderRow[dropEdge="after"] {{
    border-bottom: 2px solid {c.accent};
}}
QWidget#navFolderRow QLabel {{
    background: transparent;
    border: none;
}}
QLabel#navFolderName {{
    color: {c.text_secondary};
    font-weight: 500;
}}
QWidget#navFolderRow[currentFolder="true"] QLabel#navFolderName {{
    color: {c.text_strong};
    font-weight: 600;
}}
QPushButton#sidebarUtilityButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
}}
QPushButton#sidebarUtilityButton:hover {{
    background-color: {c.primary_soft};
}}
QPushButton#sidebarUtilityButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton:hover {{
    background-color: {c.surface_hover};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border-color: {c.border};
}}
QPushButton:focus {{
    border: 1px solid {c.accent};
}}
QToolButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QToolButton:hover {{
    background-color: {c.surface_hover};
    border-color: {c.accent};
}}
QToolButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#sectionToggleButton {{
    background: transparent;
    color: {c.text_muted};
    border: none;
    border-radius: 8px;
}}
QPushButton#sectionToggleButton:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border: none;
}}
QPushButton#secondaryButton,
QPushButton#folderAddButton,
QPushButton#searchCaptureButton,
QPushButton#ghostIconButton,
QPushButton#tagPickerButton,
QPushButton#organizeOpSecondaryButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton#secondaryButton:hover,
QPushButton#folderAddButton:hover,
QPushButton#searchCaptureButton:hover,
QPushButton#ghostIconButton:hover,
QPushButton#tagPickerButton:hover,
QPushButton#organizeOpSecondaryButton:hover {{
    background-color: {c.surface_subtle};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton#secondaryButton:pressed,
QPushButton#folderAddButton:pressed,
QPushButton#searchCaptureButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#searchCaptureButton:checked {{
    background-color: {c.accent_soft};
    border-color: {c.accent};
    color: {c.text_strong};
}}
QLineEdit, QComboBox, QDateEdit {{
    background-color: {c.input_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
    padding-right: 8px;
    selection-background-color: {c.target_soft};
    selection-color: {c.text_strong};
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover {{
    border-color: {c.border_strong};
    background-color: {c.input_bg};
}}
QLineEdit:focus, QComboBox:focus, QComboBox:on, QDateEdit:focus {{
    border: 1px solid {c.target};
    background-color: {c.input_bg};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 20px;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url("{chevron}");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {c.card_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: 10px;
    selection-background-color: {c.surface_hover};
    selection-color: {c.text_strong};
    outline: none;
    padding: 4px;
}}
QAbstractItemView {{
    selection-background-color: {c.primary_soft};
    selection-color: {c.text_strong};
    outline: none;
}}
QWidget#headerTools QComboBox,
QFrame#headerTools QComboBox,
QWidget#listToolbar QComboBox,
QWidget#screenshotsSearchRow QComboBox {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    padding: 2px 22px 2px 8px;
}}
QWidget#headerTools QComboBox:hover,
QWidget#headerTools QComboBox:focus,
QWidget#headerTools QComboBox:on,
QFrame#headerTools QComboBox:hover,
QFrame#headerTools QComboBox:focus,
QFrame#headerTools QComboBox:on,
QWidget#listToolbar QComboBox:hover,
QWidget#listToolbar QComboBox:focus,
QWidget#listToolbar QComboBox:on {{
    background-color: {c.surface};
    border: 1px solid {c.accent};
}}
QWidget#headerTools QComboBox::drop-down,
QFrame#headerTools QComboBox::drop-down,
QWidget#listToolbar QComboBox::drop-down {{
    border: none;
    width: 18px;
    background: transparent;
}}
QWidget#headerTools QComboBox::down-arrow,
QFrame#headerTools QComboBox::down-arrow,
QWidget#listToolbar QComboBox::down-arrow {{
    image: url("{chevron}");
    width: 10px;
    height: 6px;
}}
QWidget#headerTools QComboBox QAbstractItemView,
QFrame#headerTools QComboBox QAbstractItemView {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    selection-background-color: {c.primary_soft};
    selection-color: {c.text_strong};
}}
QWidget#headerTools QPushButton,
QWidget#listToolbar QPushButton {{
    border-radius: {RADIUS_CONTROL}px;
}}
QLabel#toolbarFieldLabel {{
    color: {c.text_muted};
    letter-spacing: 0.04em;
}}
QFrame#screenshotsSearchShell {{
    background-color: {c.input_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_SEARCH}px;
}}
QFrame#screenshotsSearchShell:focus-within,
QFrame#screenshotsSearchShell[focused="true"] {{
    border: 1px solid {c.target};
    background-color: {c.input_bg};
}}
QWidget#screenshotsSearchRow QLineEdit,
QLineEdit#screenshotsSearchInput {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    color: {c.text_strong};
    min-height: 30px;
    max-height: 34px;
    padding: 0 4px;
}}
QLineEdit#screenshotsSearchInput:hover,
QLineEdit#screenshotsSearchInput:focus,
QWidget#screenshotsSearchRow QLineEdit:hover,
QWidget#screenshotsSearchRow QLineEdit:focus {{
    background-color: transparent;
    border: none;
    border-radius: 0;
}}
QPushButton#searchClearButton {{
    background: transparent;
    color: {c.text_muted};
    border: none;
    border-radius: 10px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
}}
QPushButton#searchClearButton:hover {{
    background: {c.primary_soft};
    color: {c.text};
    border: none;
}}
QPushButton#imagesPrimarySearchButton {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: none;
    border-radius: 10px;
    padding: 0 14px;
    min-height: 28px;
    max-height: 28px;
}}
QPushButton#imagesPrimarySearchButton:hover {{
    background-color: #2a2f38;
    border: none;
}}
QPushButton#imagesPrimarySearchButton:pressed {{
    background-color: {c.primary_strong};
    border: none;
}}
QPushButton#imagesPrimarySearchButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border: none;
}}
QWidget#searchIntentControl {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    max-height: 28px;
}}
QPushButton#searchIntentTab {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {c.text_muted};
    padding: 3px 10px;
    min-height: 20px;
}}
QPushButton#searchIntentTab:hover {{
    background-color: {c.primary_soft};
    color: {c.text};
    border: none;
}}
QPushButton#searchIntentTab:pressed {{
    background-color: {c.primary_soft_hover};
    border: none;
}}
QPushButton#searchIntentTab:focus {{
    background-color: {c.primary_soft};
    border: none;
    outline: none;
}}
QPushButton#searchIntentTab:checked {{
    background-color: {c.card_bg};
    color: {c.text_strong};
    border: none;
}}
QPushButton#searchIntentTab:checked:hover,
QPushButton#searchIntentTab:checked:focus {{
    background-color: {c.card_bg};
    color: {c.text_strong};
    border: none;
}}
QFrame#folderPathField {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_CONTROL}px;
}}
QFrame#folderBrowser {{
    background-color: {c.surface};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#folderSelectorPath {{
    color: {c.text};
}}
QFrame#folderBrowserDivider {{
    background: transparent;
    border: none;
}}
QFrame#previewCard,
QFrame#previewCard[cardRole="preview"],
QFrame#previewCard[cardRole="information"],
QFrame#previewCard[cardRole="tags"] {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#previewCard[cardRole="preview"] QScrollArea#previewImageView,
QScrollArea#previewImageView {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
}}
QScrollArea#previewImageView > QWidget > QWidget {{
    background-color: {c.surface_sunken};
}}
QPushButton#folderFavoriteButton {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton#folderFavoriteButton:hover {{
    background: {c.surface_subtle};
    border-color: {c.border_strong};
}}
QPushButton#folderFavoriteButton[favorited="true"] {{
    background: #eef2ff;
    border-color: #c7d2fe;
}}
QPushButton#childFolderChip {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: 12px;
    color: {c.text_secondary};
}}
QPushButton#childFolderChip:hover {{
    background: {c.accent_soft};
    border-color: {c.accent};
    color: {c.text_strong};
}}
QPushButton#folderBreadcrumbCrumb {{
    background: transparent;
    border: none;
    color: {c.text_secondary};
    border-radius: 8px;
}}
QPushButton#folderBreadcrumbCrumb:hover {{
    background: {c.primary_soft};
    color: {c.text_strong};
}}
QPushButton#folderBreadcrumbCrumb[currentFolder="true"] {{
    color: {c.text_strong};
}}
QListWidget, QListWidget#screenshotList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item,
QListWidget#screenshotList::item {{
    background: transparent;
    border: none;
    color: {c.text};
}}
QListWidget#screenshotList[captionMode="icon"]::item,
QListWidget#screenshotList[captionMode="list"]::item {{
    background: transparent;
    border: none;
    color: transparent;
}}
QListWidget::item:hover,
QListWidget::item:selected,
QListWidget#screenshotList::item:hover,
QListWidget#screenshotList::item:selected {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 2px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: #c5cad3;
    border-radius: 5px;
    min-height: 28px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: #9aa3b0;
}}
QScrollBar::handle:vertical:pressed {{
    background: {c.text_secondary};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    height: 0;
    border: none;
    background: none;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px 2px 4px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: #c5cad3;
    border-radius: 5px;
    min-width: 28px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #9aa3b0;
}}
QMenu {{
    background-color: {c.card_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    padding: 6px;
    border-radius: 10px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {c.surface_hover};
    color: {c.text_strong};
}}
QMenu::separator {{
    height: 1px;
    background: {c.border};
    margin: 4px 8px;
}}
QLabel#previewInfoKey {{
    color: {c.text_faint};
    letter-spacing: 0.04em;
}}
QLabel#previewInfoValue {{
    color: {c.text};
}}
QLabel#sectionTitle {{
    color: {c.text_strong};
    letter-spacing: 0.01em;
}}
QLabel#mutedLabel,
QLabel#searchResultLabel {{
    color: {c.text_muted};
}}
QFrame#previewCard QLineEdit,
QFrame#previewCard QComboBox,
QFrame#previewCard QPushButton {{
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton#askAiButton {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #1c1f26,
        stop:1 #252536
    );
    color: {c.text_on_ink};
    border: 1px solid #2f3340;
    border-radius: 10px;
    padding: 0 14px;
    min-height: 36px;
    max-height: 36px;
}}
QPushButton#askAiButton:hover {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #252a33,
        stop:1 #2e2e44
    );
    border-color: {c.accent};
}}
QPushButton#askAiButton:pressed {{
    background-color: {c.primary_strong};
}}
QFrame#askAiPanelCard {{
    background-color: {c.surface};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#aiModePage {{
    background-color: {c.app_bg};
    border: none;
}}
QWidget#aiModePage QWidget#sectionHeader,
QWidget#aiModePage QWidget#sectionHeaderTitleRow,
QWidget#aiModePage QWidget#askAiUserRow,
QWidget#aiModePage QWidget#askAiAssistantRow {{
    background: transparent;
    border: none;
}}
QWidget#aiModePage QWidget#sectionHeaderTitleRow {{
    min-height: {CONTROL_STANDARD}px;
    max-height: {CONTROL_STANDARD}px;
}}
QScrollArea#aiChatHistory {{
    background-color: {c.panel_bg};
    border: none;
    border-radius: {RADIUS_MD}px;
}}
QScrollArea#aiChatHistory > QWidget,
QScrollArea#aiChatHistory QWidget#askAiChatHost {{
    background: transparent;
    border: none;
}}
QListWidget#aiChatHistory {{
    background-color: {c.panel_bg};
    border: none;
    border-radius: {RADIUS_MD}px;
}}
QListWidget#aiChatHistory::item {{
    background: transparent;
    border: none;
    color: {c.text};
    padding: 6px 4px;
}}
QWidget#askAiUserRow,
QWidget#askAiAssistantRow {{
    background: transparent;
}}
QFrame#askAiUserMessage {{
    background-color: {c.chat_user_bg};
    border: 1px solid {c.chat_user_border};
    border-radius: {RADIUS_MD}px;
}}
QLabel#askAiUserText {{
    color: {c.text_strong};
    background: transparent;
}}
QFrame#askAiResultMessage {{
    background-color: {c.chat_assistant_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
}}
QFrame#askAiResultMessage[cardKind="processing"],
QFrame#askAiResultMessage[cardKind="executing"] {{
    background-color: {c.surface};
    border-color: {c.border_subtle};
}}
QFrame#askAiResultMessage[cardKind="result"],
QFrame#askAiResultMessage[cardKind="complete"] {{
    background-color: {c.card_bg};
    border-color: {c.border_subtle};
}}
QFrame#askAiResultMessage[cardKind="warning"] {{
    background-color: {c.warning_soft};
    border-color: #F3E0C8;
}}
QFrame#askAiResultMessage[cardKind="error"] {{
    background-color: {c.error_soft};
    border-color: #FECACA;
}}
QFrame#askAiResultMessage[cardKind="unsupported"],
QFrame#askAiResultMessage[cardKind="auth"],
QFrame#askAiResultMessage[cardKind="limit"] {{
    background-color: {c.surface};
    border-color: {c.border_strong};
}}
QFrame#askAiResultMessage[cardKind="processing"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="executing"] QLabel#askAiCardIcon {{
    color: {c.text_faint};
}}
QFrame#askAiResultMessage[cardKind="complete"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="result"] QLabel#askAiCardIcon {{
    color: {c.text_secondary};
}}
QFrame#askAiResultMessage[cardKind="warning"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="error"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="unsupported"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="auth"] QLabel#askAiCardIcon,
QFrame#askAiResultMessage[cardKind="limit"] QLabel#askAiCardIcon {{
    color: {c.text_strong};
}}
QLabel#askAiCardIcon {{
    color: {c.text_muted};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#askAiCardSubtitle {{
    color: {c.text_muted};
    font-size: 11px;
    font-weight: 400;
}}
QPushButton#askAiClarifyChip {{
    background-color: {c.surface_subtle};
    color: {c.text_secondary};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 24px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#askAiClarifyChip:hover {{
    background-color: {c.surface_hover};
    border-color: {c.target};
    color: {c.text_strong};
}}
QPushButton#askAiJumpLatest {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 26px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#askAiJumpLatest:hover {{
    background-color: {c.surface_subtle};
    border-color: {c.accent};
}}
QPushButton#askAiSignInAction {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: 1px solid {c.primary_strong};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#askAiSaveAutomation {{
    background-color: {c.surface_subtle};
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 24px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#askAiSaveAutomation:hover {{
    background-color: {c.surface};
    border-color: {c.accent};
    color: {c.text_strong};
}}
QPushButton#aiSendButton[processing="true"] {{
    color: {c.text_faint};
}}
QLabel#askAiUserText {{
    color: {c.text_strong};
}}
QLabel#askAiAssistantText {{
    color: {c.text};
}}
QLabel#askAiStatus {{
    color: {c.text_secondary};
}}
QLabel#askAiPreviewHint {{
    color: {c.text_faint};
    font-size: 11px;
    font-weight: 500;
    padding: 0 2px 2px 2px;
}}
QWidget#askAiStartMenu {{
    background: transparent;
    border: none;
}}
QLabel#askAiStartHeading {{
    color: {c.text_strong};
    font-size: 13px;
    font-weight: 700;
    padding: 2px 2px 4px 2px;
}}
QPushButton#askAiStartRow {{
    background-color: {c.card_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
    text-align: left;
    padding: 0;
    min-height: 52px;
}}
QPushButton#askAiStartRow:hover {{
    background-color: {c.surface_hover};
    border-color: {c.border_strong};
}}
QPushButton#askAiStartRow:pressed {{
    background-color: {c.primary_soft};
}}
QPushButton#askAiStartRow:focus {{
    border: 1px solid {c.target};
}}
QPushButton#askAiStartRow:disabled {{
    background-color: {c.surface};
    border-color: {c.border_subtle};
    color: {c.text};
}}
QWidget#askAiStartTextCol,
QWidget#askAiStartTitleRow {{
    background: transparent;
    border: none;
}}
QLabel#askAiStartIconPlate {{
    border-radius: {RADIUS_SM}px;
    background-color: {c.surface_subtle};
}}
QLabel#askAiStartIconPlate[startAction="find"] {{
    background-color: #eef3f8;
}}
QLabel#askAiStartIconPlate[startAction="organize"] {{
    background-color: {c.info_soft};
}}
QLabel#askAiStartIconPlate[startAction="help"] {{
    background-color: #f4f2f8;
}}
QLabel#askAiStartTitle {{
    color: {c.text_strong};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#askAiStartBody {{
    color: {c.text_muted};
    font-size: 12px;
    font-weight: 400;
}}
QLabel#askAiStartSoon {{
    color: {c.text_faint};
    font-size: 11px;
    font-weight: 500;
}}
QPushButton#askAiStartRow:disabled QLabel#askAiStartTitle {{
    color: {c.text_secondary};
}}
QPushButton#askAiStartRow:disabled QLabel#askAiStartBody,
QPushButton#askAiStartRow:disabled QLabel#askAiStartSoon {{
    color: {c.text_faint};
}}
QPushButton#askAiResultAction {{
    background: transparent;
    color: {c.text_secondary};
    border: none;
    border-radius: {RADIUS_SM}px;
    text-align: left;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 4px;
    min-height: 24px;
    max-height: 28px;
}}
QPushButton#askAiResultAction:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border: none;
}}
QPushButton#askAiResultAction:pressed {{
    background-color: {c.primary_soft_hover};
    border: none;
}}
QPushButton#askAiResultAction:focus {{
    border: 1px solid {c.accent};
    background-color: {c.surface};
}}
QPushButton#askAiConfirmCancel {{
    background-color: {c.card_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#askAiConfirmCancel:hover {{
    background-color: {c.surface_hover};
    border-color: {c.border_strong};
    color: {c.text_strong};
}}
QPushButton#askAiConfirmExecute {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: 1px solid {c.primary_strong};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#askAiConfirmExecute:hover {{
    background-color: #2a2f38;
}}
QPushButton#askAiConfirmExecute:disabled,
QPushButton#askAiConfirmCancel:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border-color: {c.border};
}}
QWidget#aiModePage QWidget#imagesActionInputRow {{
    margin-top: 6px;
    background-color: {c.surface};
    border-top: 1px solid {c.hairline};
    border-radius: 0 0 {RADIUS_CARD}px {RADIUS_CARD}px;
    padding: 8px 2px 2px 2px;
}}
QLineEdit#imagesActionInput {{
    background-color: {c.input_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
    min-height: 36px;
    padding: 0 12px;
}}
QLineEdit#imagesActionInput:hover {{
    border-color: {c.border_strong};
    background-color: {c.input_bg};
}}
QLineEdit#imagesActionInput:focus {{
    border: 1px solid {c.target};
    background-color: {c.input_bg};
}}
QWidget#sidebarAccountControl,
QPushButton#sidebarAccountControl {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
    text-align: left;
    padding: 0;
    min-height: 52px;
    max-height: none;
}}
QWidget#sidebarAccountControl[collapsed="true"],
QPushButton#sidebarAccountControl[collapsed="true"] {{
    background: transparent;
    border: none;
    min-height: 36px;
}}
QPushButton#sidebarAccountControl:hover {{
    background-color: {c.surface_hover};
    border-color: {c.border_strong};
}}
QPushButton#sidebarAccountControl:pressed {{
    background-color: {c.primary_soft};
}}
QLabel#sidebarAccountAvatar {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: 14px;
}}
QLabel#sidebarAccountName {{
    color: {c.text_strong};
    font-weight: 600;
    letter-spacing: 0.02em;
}}
QLabel#sidebarAccountPlan {{
    color: {c.text_muted};
    font-size: 11px;
    font-weight: 500;
}}
QWidget#navNotificationItem {{
    background: transparent;
    border: none;
}}
QLineEdit#imagesActionInput {{
    background-color: {c.input_bg};
    color: {c.text};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
    min-height: 36px;
    padding: 0 12px;
}}
QLineEdit#imagesActionInput:hover {{
    border-color: {c.border_strong};
    background-color: {c.input_bg};
}}
QLineEdit#imagesActionInput:focus {{
    border: 1px solid {c.target};
    background-color: {c.input_bg};
}}
QPushButton#tagChip,
QPushButton#tagMasterChip {{
    background-color: {c.tag_soft};
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: 12px;
}}
QPushButton#tagChip:hover,
QPushButton#tagMasterChip:hover {{
    background-color: {c.accent_soft};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton#tagChip[selected="true"],
QPushButton#tagMasterChip:checked {{
    background-color: {c.accent_soft};
    border-color: {c.accent};
    color: {c.text_strong};
}}
QPushButton#tagPickerButton {{
    background-color: {c.surface_subtle};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QPushButton#tagPickerButton:hover,
QPushButton#tagPickerButton:focus {{
    background-color: {c.surface};
    border-color: {c.accent};
    color: {c.text_strong};
}}
QFrame#tagPickerPopup {{
    background-color: {c.surface};
    border: 1px solid {c.border};
    border-radius: 10px;
}}
QListWidget#tagPickerList::item:hover,
QListWidget#tagPickerList::item:selected {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
}}
QWidget#tagsContentColumn QLabel#pageTitle {{
    color: {c.text_strong};
}}
QWidget#tagsContentColumn QLabel#pageSubtitle {{
    color: {c.text_muted};
}}
QSplitter#imagesSplitter::handle {{
    background-color: transparent;
}}
QTreeWidget#folderTree {{
    background-color: {c.surface_subtle};
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
    color: {c.text};
}}
QTreeWidget#folderTree::item:hover {{
    background-color: {c.primary_soft};
}}
QTreeWidget#folderTree::item:selected {{
    background-color: {c.accent_soft};
    color: {c.text_strong};
}}
QPushButton#organizeOpPrimaryButton,
QPushButton#organizeOpPrimaryButton[opId="tags"],
QPushButton#organizeOpPrimaryButton[opId="rename"] {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: 1px solid {c.primary_strong};
}}
QPushButton#organizeOpPrimaryButton:hover,
QPushButton#organizeOpPrimaryButton[opId="tags"]:hover,
QPushButton#organizeOpPrimaryButton[opId="rename"]:hover {{
    background-color: #2a2f38;
}}
QPushButton#captureBarRestoreButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border_strong};
    border-radius: 16px;
}}
QPushButton#captureBarRestoreButton:hover {{
    background-color: {c.primary_soft};
    border-color: {c.accent};
}}
QWidget#segmentedToggle,
QWidget#galleryLayoutToggle {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border};
    border-radius: 10px;
}}
QPushButton#segmentButtonLeft,
QPushButton#segmentButtonMid,
QPushButton#segmentButtonRight {{
    background-color: transparent;
    color: {c.text_muted};
    border: 1px solid transparent;
    border-radius: 8px;
    min-width: 28px;
    padding: 4px 8px;
}}
QWidget#galleryLayoutToggle QPushButton#segmentButtonLeft,
QWidget#galleryLayoutToggle QPushButton#segmentButtonRight {{
    min-width: 30px;
    max-width: 34px;
    padding: 4px 6px;
}}
QPushButton#segmentButtonLeft:hover,
QPushButton#segmentButtonMid:hover,
QPushButton#segmentButtonRight:hover {{
    background-color: {c.surface_hover};
    color: {c.text};
}}
QPushButton#segmentButtonLeft:checked,
QPushButton#segmentButtonMid:checked,
QPushButton#segmentButtonRight:checked {{
    background-color: {c.card_bg};
    color: {c.text_strong};
    border-color: {c.border_subtle};
}}
QFrame#previewCard[cardRole="tags"] {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QPushButton#tagsPopoverClose {{
    background-color: {c.surface_subtle};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-width: {CONTROL_COMPACT}px;
    max-width: {CONTROL_COMPACT}px;
    min-height: {CONTROL_COMPACT}px;
    max-height: {CONTROL_COMPACT}px;
    padding: 0;
    font-size: 16px;
}}
QPushButton#tagsPopoverClose:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton#aiPanelClose {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-width: {CONTROL_STANDARD}px;
    max-width: {CONTROL_STANDARD}px;
    min-height: {CONTROL_STANDARD}px;
    max-height: {CONTROL_STANDARD}px;
    padding: 0;
}}
QPushButton#aiPanelClose:hover {{
    background-color: {c.surface_subtle};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QPushButton#aiPanelClose:pressed {{
    background-color: {c.primary_soft_hover};
}}
QPushButton#aiSendButton {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: none;
    border-radius: 14px;
    min-width: {CONTROL_COMPACT}px;
    max-width: {CONTROL_COMPACT}px;
    min-height: {CONTROL_COMPACT}px;
    max-height: {CONTROL_COMPACT}px;
    padding: 0;
}}
QPushButton#aiSendButton:hover {{
    background-color: {c.primary_strong};
    border: none;
}}
QPushButton#aiSendButton:pressed {{
    background-color: {c.ai};
    border: none;
}}
QPushButton#aiSendButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border: 1px solid {c.border};
}}
QPushButton#aiSendButton:focus {{
    border: 1px solid {c.accent};
}}
QPushButton#galleryFolderUpButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: 8px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
}}
QPushButton#galleryFolderUpButton:hover {{
    background-color: {c.surface_subtle};
    border-color: {c.accent};
}}
QPushButton#galleryFolderUpButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border-color: {c.border};
}}
QWidget#imagesResultsHeader {{
    background-color: {c.surface_subtle};
    border: none;
    border-top-left-radius: {RADIUS_CARD}px;
    border-top-right-radius: {RADIUS_CARD}px;
}}
QWidget#searchHeaderRow,
QWidget#screenshotsSearchRow,
QLabel#searchShellGlyph {{
    background: transparent;
    border: none;
}}
QWidget#screenshotsSearchRow QLineEdit,
QLineEdit#screenshotsSearchInput,
QLineEdit#screenshotsSearchInput:hover,
QLineEdit#screenshotsSearchInput:focus {{
    background-color: transparent;
    border: none;
    border-radius: 0;
}}
QWidget#workflowEditor,
QStackedWidget#automationStack > QWidget#workflowEditor {{
    background-color: {c.app_bg};
}}
QWidget#automationListPage {{
    background-color: {c.app_bg};
}}
QFrame#workflowEditorHeader {{
    background-color: {c.app_bg};
    border: none;
    min-height: 64px;
}}
QPushButton#workflowBackButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 32px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#workflowBackButton:hover {{
    background-color: {c.surface_subtle};
    color: {c.text_strong};
    border-color: {c.border_strong};
}}
QPushButton#workflowBackButton:focus {{
    border: 1px solid {c.accent};
}}
QFrame#workflowHeaderDivider {{
    background-color: {c.border};
    border: none;
}}
QWidget#workflowIdentity,
QFrame#workflowIdentity {{
    background-color: transparent;
    border: 1px solid {c.border};
    border-radius: {RADIUS_MD}px;
}}
QLabel#workflowIdentityNameLabel {{
    background: transparent;
    border: none;
    font-size: 20px;
    font-weight: 700;
    color: {c.text_strong};
    min-height: 32px;
    padding: 0;
}}
QLabel#workflowIdentityDescriptionLabel {{
    background: transparent;
    border: none;
    font-size: 13px;
    font-weight: 400;
    color: {c.text_muted};
    min-height: 24px;
    padding: 0;
}}
QToolButton#workflowIdentityPencil,
QToolButton#workflowIdentityCancel {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_SM}px;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
    color: {c.text_muted};
    font-size: 12px;
}}
QToolButton#workflowIdentityPencil:hover,
QToolButton#workflowIdentityCancel:hover {{
    background-color: {c.primary_soft};
}}
QLineEdit#workflowIdentityName,
QLineEdit#workflowIdentityName:hover,
QLineEdit#workflowIdentityName:focus,
QLineEdit#workflowIdentityName[editing="true"],
QLineEdit#workflowIdentityName[editing="true"]:hover,
QLineEdit#workflowIdentityName[editing="true"]:focus {{
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0 4px 0 0;
    font-size: 20px;
    font-weight: 700;
    color: {c.text_strong};
    min-height: 32px;
    max-height: 32px;
}}
QLineEdit#workflowIdentityDescription,
QLineEdit#workflowIdentityDescription:hover,
QLineEdit#workflowIdentityDescription:focus,
QLineEdit#workflowIdentityDescription[editing="true"],
QLineEdit#workflowIdentityDescription[editing="true"]:hover,
QLineEdit#workflowIdentityDescription[editing="true"]:focus {{
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0 4px 0 0;
    font-size: 13px;
    font-weight: 400;
    color: {c.text_muted};
    min-height: 24px;
    max-height: 24px;
}}
QLabel#workflowUnsavedLabel {{
    color: {c.warning};
    font-size: 12px;
    font-weight: 600;
    min-height: 16px;
}}
QLabel#workflowStatusBadge {{
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 999px;
}}
QLabel#workflowStatusBadge[status="ready"] {{
    color: {c.success};
    background-color: {c.success_soft};
}}
QLabel#workflowStatusBadge[status="blocked"] {{
    color: {c.warning};
    background-color: {c.warning_soft};
}}
QPushButton#workflowSaveButton {{
    background-color: {c.surface};
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 14px;
    font-weight: 500;
}}
QPushButton#workflowSaveButton:hover {{
    background-color: {c.surface_subtle};
    border-color: {c.border_strong};
    color: {c.text_strong};
}}
QPushButton#workflowSaveButton:focus {{
    border: 1px solid {c.accent};
}}
QFrame#workflowWorkspace {{
    background-color: {board};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#workflowWorkspaceInner,
QGraphicsView#workflowCanvas {{
    background-color: {board};
    border: none;
}}
QFrame#workflowSideRail {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#workflowSideRailInner,
QWidget#workflowInspectorTabs {{
    background-color: {c.card_bg};
    border: none;
}}
QWidget#workflowInspectorSettings,
QWidget#workflowInspectorStack,
QFrame#automationDraftComposer {{
    background: transparent;
    border: none;
}}
QFrame#workflowInspectorPane {{
    background: transparent;
    border: none;
}}
QWidget#workflowInspectorTabBar {{
    background-color: transparent;
    border: none;
    border-top-left-radius: {RADIUS_CARD}px;
    border-top-right-radius: {RADIUS_CARD}px;
}}
QPushButton#workflowInspectorTab {{
    background: transparent;
    color: {c.text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    min-height: 40px;
    padding: 8px 0;
    font-size: 13px;
    font-weight: 600;
    text-align: center;
}}
QFrame#workflowInspectorTabRule,
QFrame#workflowInspectorTabSplit {{
    background-color: {c.border};
    border: none;
}}
QPushButton#workflowInspectorTab[selected="true"] {{
    color: {c.target};
    background: transparent;
    border-bottom: 2px solid {c.target};
}}
QPushButton#workflowInspectorTab[tabRole="ai"][selected="true"] {{
    color: {c.target};
    background: transparent;
    border-bottom: 2px solid {c.target};
}}
QPushButton#workflowInspectorTab:hover {{
    color: {c.text};
}}
QPushButton#workflowInspectorTab:disabled,
QPushButton#workflowInspectorTab[catalogEnabled="false"],
QPushButton#workflowInspectorTab:disabled:hover,
QPushButton#workflowInspectorTab[catalogEnabled="false"]:hover {{
    background: transparent;
    color: {c.text_faint};
    border: none;
    border-bottom: 2px solid transparent;
}}
QLabel#workflowInspectorCategory {{
    background: transparent;
    border: none;
    color: {c.select};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0;
    padding: 0;
}}
QLabel#workflowInspectorTitle {{
    background: transparent;
    border: none;
    font-size: 18px;
    font-weight: 700;
    color: {c.text_strong};
    padding: 0;
}}
QToolButton#workflowDeleteBlockButton {{
    background: transparent;
    color: {c.text_secondary};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
}}
QToolButton#workflowDeleteBlockButton:hover {{
    background-color: {c.error_soft};
    border-color: #fecaca;
    color: {c.error};
}}
QToolButton#workflowDeleteBlockButton:pressed {{
    background-color: #fee2e2;
}}
QToolButton#workflowDeleteBlockButton:focus {{
    border: 1px solid {c.accent};
}}
QLabel#workflowFieldLabel {{
    background: transparent;
    border: none;
    font-size: 12px;
    font-weight: 600;
    color: {c.text_strong};
}}
QFrame#workflowFieldGroup {{
    background: transparent;
    border: none;
}}
QFrame#workflowInspectorCallout {{
    background-color: {c.info_soft};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
}}
QLabel#workflowInspectorCalloutText {{
    background: transparent;
    border: none;
    color: {c.info_strong};
    font-size: 12px;
}}
QComboBox#workflowTargetCombo,
QComboBox#workflowActionCombo,
QLineEdit#workflowParamInput,
QLineEdit#automationDraftInput {{
    background-color: {c.input_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    max-height: 28px;
    padding: 2px 8px;
    font-size: 12px;
}}
QComboBox#workflowTargetCombo:hover,
QComboBox#workflowActionCombo:hover,
QLineEdit#workflowParamInput:hover,
QLineEdit#automationDraftInput:hover,
QComboBox#workflowTargetCombo:focus,
QComboBox#workflowActionCombo:focus,
QComboBox#workflowTargetCombo:on,
QLineEdit#workflowParamInput:focus,
QLineEdit#automationDraftInput:focus {{
    background-color: {c.input_bg};
    border: 1px solid {c.accent};
}}
QFrame#workflowAiCard {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_MD}px;
}}
QFrame#workflowAiCard:disabled,
QFrame#workflowAiCard[catalogEnabled="false"] {{
    background-color: {c.surface_sunken};
    border: 1px solid {c.border_subtle};
}}
QLabel#workflowAiCardTitle {{
    background: transparent;
    border: none;
    color: {c.select};
    font-size: 13px;
    font-weight: 600;
}}
QFrame#workflowAiCard:disabled QLabel#workflowAiCardTitle,
QFrame#workflowAiCard[catalogEnabled="false"] QLabel#workflowAiCardTitle {{
    color: {c.text_faint};
}}
QLabel#workflowAiBadge {{
    background-color: {c.select_soft};
    color: {c.select};
    font-size: 10px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
}}
QFrame#workflowAiCard:disabled QLabel#workflowAiBadge,
QFrame#workflowAiCard[catalogEnabled="false"] QLabel#workflowAiBadge {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
}}
QFrame#workflowAiCard:disabled QLabel#mutedLabel,
QFrame#workflowAiCard[catalogEnabled="false"] QLabel#mutedLabel {{
    color: {c.text_faint};
}}
QPushButton#workflowOpenAiButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {card_line};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 12px;
    font-weight: 500;
}}
QPushButton#workflowOpenAiButton:hover {{
    background-color: {c.surface_subtle};
    border-color: {c.border_strong};
    color: {c.text_strong};
}}
QPushButton#workflowOpenAiButton:disabled,
QPushButton#workflowOpenAiButton:disabled:hover {{
    background-color: {c.surface};
    color: {c.text_faint};
    border: 1px solid {c.border};
}}
QWidget#workflowFolderPick {{
    background-color: {c.input_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CONTROL}px;
}}
QLineEdit#workflowFolderValue,
QLineEdit#workflowFolderValue:hover,
QLineEdit#workflowFolderValue:focus {{
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 2px 6px;
    min-height: 24px;
    font-size: 12px;
    color: {c.text_strong};
}}
QToolButton#workflowFolderBrowse {{
    background-color: {c.input_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_SM}px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0;
    color: {c.text};
}}
QToolButton#workflowFolderBrowse:hover {{
    background-color: {c.surface_hover};
    color: {c.text_strong};
}}
QLineEdit#workflowReadonlyPath,
QLineEdit#workflowReadonlyPath:hover,
QLineEdit#workflowReadonlyPath:focus {{
    background-color: {c.surface_sunken};
    color: {c.text_muted};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
}}
QPushButton#automationNewButton {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#automationRunButton {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#automationNewButton:hover {{
    background-color: {c.primary_strong};
}}
QPushButton#automationRunButton:hover {{
    background-color: #2a2f38;
}}
QPushButton#automationRunButton:pressed {{
    background-color: {c.primary_strong};
}}
QPushButton#automationNewButton:focus,
QPushButton#automationRunButton:focus {{
    border: 1px solid {c.accent_strong};
}}
QFrame#workflowCanvasToolbar {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
    min-height: 52px;
}}
QFrame#workflowZoomCluster {{
    background-color: {c.surface};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
}}
QFrame#workflowZoomCluster QToolButton#workflowZoomButton {{
    border: none;
    background: transparent;
}}
QFrame#workflowZoomCluster QToolButton#workflowZoomButton:hover {{
    background-color: {c.primary_soft};
    border: none;
}}
QToolButton#automationAddBlockButton,
QToolButton#workflowSortButton,
QToolButton#workflowZoomButton,
QToolButton#workflowToolbarButton {{
    background-color: {c.surface};
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 34px;
    max-height: 34px;
    padding: 0 12px;
    font-size: 12px;
}}
QToolButton#automationAddBlockButton {{
    min-width: 0;
    max-width: 16777215;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
    color: {c.target};
    background-color: {c.surface};
    border: 1px solid {c.target};
}}
QToolButton#workflowZoomButton {{
    min-width: 34px;
    max-width: 34px;
    padding: 0;
}}
QToolButton#workflowSortButton::menu-indicator {{
    width: 10px;
    height: 10px;
    padding-right: 6px;
    subcontrol-origin: padding;
    subcontrol-position: right center;
}}
QToolButton#automationAddBlockButton:hover {{
    background-color: {c.target_soft};
    color: {c.target};
    border-color: {c.target};
}}
QToolButton#workflowSortButton:hover,
QToolButton#workflowZoomButton:hover,
QToolButton#workflowToolbarButton:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border-color: {c.accent};
}}
QToolButton#automationAddBlockButton:focus,
QToolButton#workflowSortButton:focus,
QToolButton#workflowZoomButton:focus,
QToolButton#workflowToolbarButton:focus {{
    border: 1px solid {c.accent};
}}
QLabel#workflowZoomLabel {{
    color: {c.text_secondary};
    min-width: 44px;
    font-size: 12px;
    font-weight: 600;
}}
QFrame#workflowAddBlockPopup {{
    background: transparent;
    border: none;
}}
QFrame#workflowAddBlockCard {{
    background: transparent;
    border: none;
}}
QWidget#workflowAddBlockColumn,
QWidget#workflowAddBlockColumnInner {{
    background: transparent;
    border: none;
}}
QScrollArea#workflowAddBlockScroll,
QScrollArea#workflowAddBlockScroll > QWidget,
QScrollArea#workflowAddBlockScroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QScrollArea#workflowAddBlockScroll QScrollBar:horizontal {{
    height: 0px;
    background: transparent;
    border: none;
    margin: 0;
}}
QScrollArea#workflowAddBlockScroll QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollArea#workflowAddBlockScroll QScrollBar::handle:vertical {{
    background: {c.border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollArea#workflowAddBlockScroll QScrollBar::add-line:vertical,
QScrollArea#workflowAddBlockScroll QScrollBar::sub-line:vertical {{
    height: 0;
}}
QFrame#workflowAddBlockDivider {{
    background-color: {c.hairline};
    border: none;
}}
QLabel#workflowAddBlockCategory {{
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0;
    padding: 0 8px 8px 8px;
    background: transparent;
    border: none;
}}
QLabel#workflowAddBlockName {{
    font-size: 13px;
    font-weight: 500;
    background: transparent;
    border: none;
}}
QPushButton#workflowAddBlockItem[catalogEnabled="true"] QLabel#workflowAddBlockName {{
    color: {c.text};
    font-weight: 600;
}}
QPushButton#workflowAddBlockItem[catalogEnabled="false"] QLabel#workflowAddBlockName,
QPushButton#workflowAddBlockItem:disabled QLabel#workflowAddBlockName {{
    color: {c.text_faint};
    font-weight: 500;
}}
QLabel#workflowAddBlockGlyph {{
    background: transparent;
    border: none;
}}
QPushButton#workflowAddBlockItem {{
    background: transparent;
    color: {c.text};
    border: none;
    border-radius: 8px;
    min-height: 36px;
    padding: 0;
    font-size: 13px;
    text-align: left;
}}
QPushButton#workflowAddBlockItem:hover,
QPushButton#workflowAddBlockItem:disabled:hover,
QPushButton#workflowAddBlockItem[catalogEnabled="false"]:hover {{
    background: transparent;
    border: none;
}}
QPushButton#workflowAddBlockItem:focus {{
    border: none;
    outline: none;
}}
QPushButton#workflowAddBlockItem:disabled,
QPushButton#workflowAddBlockItem[catalogEnabled="false"] {{
    color: {c.text_faint};
    background: transparent;
    border: none;
}}
QLabel#automationEmptyHint {{
    background: transparent;
    border: none;
    color: {c.text_muted};
    font-size: 13px;
}}
QFrame#automationListCard {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: 0;
}}
QTableWidget#automationWorkflowTable {{
    background-color: transparent;
    alternate-background-color: {c.surface_subtle};
    border: none;
    border-radius: 0;
    gridline-color: transparent;
    outline: none;
}}
QTableWidget#automationWorkflowTable > QWidget {{
    background: transparent;
    border: none;
}}
QTableWidget#automationWorkflowTable::item {{
    color: {c.text};
    padding: 10px {AUTOMATION_LIST_HEADER_PAD}px 10px {AUTOMATION_LIST_HEADER_PAD}px;
    border: none;
    border-bottom: 1px solid {c.hairline};
    font-size: 13px;
}}
QTableWidget#automationWorkflowTable::item:hover {{
    background-color: {c.surface_hover};
}}
QTableWidget#automationWorkflowTable::item:selected {{
    background-color: {c.target_soft};
    color: {c.text_strong};
}}
QHeaderView#automationWorkflowTable {{
    background: transparent;
    border: none;
}}
QTableWidget#automationWorkflowTable QHeaderView::section {{
    background-color: {c.surface_subtle};
    color: {c.text_faint};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: none;
    border-bottom: 1px solid {c.border};
    padding: 9px {AUTOMATION_LIST_HEADER_PAD}px 9px {AUTOMATION_LIST_HEADER_PAD}px;
}}
QTableWidget#automationWorkflowTable QHeaderView::section:first {{
    padding-left: {AUTOMATION_LIST_RUN_HEADER_PAD}px;
}}
QWidget#automationRowRun,
QWidget#automationStatusCell,
QWidget#automationRowActions {{
    background: transparent;
    margin: 0;
    padding: 0;
}}
QPushButton#automationListRunButton {{
    background-color: {c.primary};
    color: {c.text_on_ink};
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
}}
QPushButton#automationListRunButton:hover {{
    background-color: #2a2f38;
    border: none;
}}
QPushButton#automationListRunButton:pressed {{
    background-color: {c.primary_strong};
    border: none;
}}
QPushButton#automationListRunButton:disabled {{
    background-color: {c.surface_sunken};
    color: {c.text_faint};
    border: 1px solid {c.border};
}}
QPushButton#automationListRunButton:focus {{
    border: 1px solid {c.accent_strong};
}}
QLabel#automationStatusBadge {{
    font-size: 13px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 999px;
    min-height: 24px;
    max-width: 100%;
}}
QLabel#automationStatusBadge[status="ready"] {{
    color: {c.success};
    background-color: {c.success_soft};
}}
QLabel#automationStatusBadge[status="running"] {{
    color: {c.target};
    background-color: {c.target_soft};
}}
QLabel#automationStatusBadge[status="needs_action"] {{
    color: {c.warning};
    background-color: {c.warning_soft};
}}
QLabel#automationStatusBadge[status="error"] {{
    color: {c.error};
    background-color: {c.error_soft};
}}
QLabel#automationStatusBadge[status="disabled"] {{
    color: {c.text_muted};
    background-color: {c.surface_sunken};
}}
QToolButton#automationRowIconButton,
QToolButton#automationRowDeleteButton {{
    background: transparent;
    color: {c.text_secondary};
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
}}
QToolButton#automationRowIconButton:hover {{
    background-color: {c.primary_soft};
    color: {c.text_strong};
    border-color: {c.border};
}}
QToolButton#automationRowIconButton:pressed {{
    background-color: {c.primary_soft_hover};
}}
QToolButton#automationRowIconButton:focus,
QToolButton#automationRowDeleteButton:focus {{
    border: 1px solid {c.accent};
}}
QToolButton#automationRowDeleteButton:hover {{
    background-color: {c.error_soft};
    border-color: #fecaca;
    color: {c.error};
}}
QToolButton#automationRowDeleteButton:pressed {{
    background-color: #fee2e2;
}}
QPushButton#automationRowButton {{
    background-color: {c.surface};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: 28px;
    padding: 0 10px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#automationRowButton:hover {{
    background-color: {c.surface_subtle};
    color: {c.text_strong};
    border-color: {c.border_strong};
}}
QWidget#automationRowActions QPushButton#automationRunButton {{
    min-height: 28px;
    padding: 0 10px;
    font-size: 12px;
}}
QWidget#tourChrome {{
    background-color: rgba(15, 23, 42, 0.38);
}}
QScrollArea#tourFeedbackScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#tourFeedbackScroll > QWidget {{
    background: transparent;
}}
QFrame#tourWelcomeCard,
QFrame#tourPopover {{
    background-color: {c.card_bg};
    border: 1px solid {c.card_border};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#tourWelcomeTitle,
QLabel#tourTitle {{
    color: {c.text_strong};
    font-size: 18px;
    font-weight: 650;
}}
QLabel#tourWelcomeTagline,
QLabel#signInTagline {{
    color: {c.target};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#tourWelcomeBody,
QLabel#tourBody,
QLabel#tourCompleteItem {{
    color: {c.text_secondary};
    font-size: 13px;
}}
QLabel#tourWelcomeBody {{
    padding-bottom: 6px;
}}
QLabel#tourWelcomeItem {{
    color: {c.text};
    font-size: 13px;
    padding-left: 2px;
}}
QLabel#tourHint,
QLabel#tourProgress,
QLabel#tourDots {{
    color: {c.text_muted};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
}}
QLabel#tourStatus {{
    color: {c.warning};
    font-size: 12px;
}}
QPushButton#tourChoiceButton {{
    background: transparent;
    color: {c.text_strong};
    border: 1px solid {c.border_strong};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#tourChoiceButton:hover {{
    background-color: {c.surface_hover};
}}
QPushButton#tourStartButton,
QPushButton#tourNextButton {{
    background-color: {c.target};
    color: #ffffff;
    border: 1px solid {c.target};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_STANDARD}px;
    padding: 0 16px;
    font-weight: 600;
}}
QPushButton#tourStartButton:hover,
QPushButton#tourNextButton:hover {{
    background-color: #1d4ed8;
}}
QPushButton#tourSkipButton,
QPushButton#tourBackButton,
QPushButton#tourCloseButton {{
    background: transparent;
    color: {c.text_secondary};
    border: 1px solid {c.border};
    border-radius: {RADIUS_CONTROL}px;
    min-height: {CONTROL_COMPACT}px;
    padding: 0 10px;
}}
QPushButton#tourCloseButton {{
    min-width: 22px;
    max-width: 22px;
    padding: 0;
    border: none;
}}
QLineEdit#tourFeedbackInput {{
    min-height: {CONTROL_STANDARD}px;
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_SM}px;
    padding: 0 10px;
    background: {c.input_bg};
}}
QRadioButton#tourFeedbackRadio {{
    spacing: 8px;
    color: {c.text};
    min-height: 28px;
    padding: 4px 8px 4px 4px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
}}
QRadioButton#tourFeedbackRadio:hover {{
    background: {c.surface_hover};
}}
QRadioButton#tourFeedbackRadio[selected="true"] {{
    background: {c.target_soft};
    border-color: {c.target};
    color: {c.text_strong};
}}
QRadioButton#tourFeedbackRadio::indicator {{
    width: 0px;
    height: 0px;
    border: none;
    background: transparent;
}}
QRadioButton#tourFeedbackRadio::indicator:hover {{
    border: none;
}}
QRadioButton#tourFeedbackRadio::indicator:checked {{
    border: none;
    background: transparent;
}}
QWidget#infoPanel,
QFrame#infoPanel {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#aboutCard {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#aboutBrandCard {{
    background-color: {c.card_bg};
    border: 1px solid {c.border_subtle};
    border-radius: {RADIUS_CARD}px;
}}
QWidget#signInGatePage,
QWidget#accountPage {{
    background-color: {c.app_bg};
}}
QLabel#emptyHintTitle {{
    color: {c.text_strong};
}}
QLabel#emptyHintBody {{
    color: {c.text_secondary};
}}
QLabel#emptyHintMeta {{
    color: {c.text_muted};
}}
"""
