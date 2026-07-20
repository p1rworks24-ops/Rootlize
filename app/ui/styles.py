"""Light, colorful app theme (Windows 11 / Notion / Explorer inspired)."""

APP_STYLE = """
/* ===== Base ===== */
QMainWindow, QWidget {
    background-color: #f5f6f8;
    color: #1f2937;
    font-size: 13px;
}

QLabel {
    color: #1f2937;
    background: transparent;
}

/* ===== Sidebar ===== */
QFrame#sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e5e7eb;
}

QWidget#sidebarBrandWrap {
    background-color: #ffffff;
    border: none;
    border-radius: 8px;
}

QLabel#sidebarBrand {
    color: #111827;
    background-color: #ffffff;
    font-size: 13px;
    font-weight: 700;
    padding: 0;
    margin: 0;
}

QLabel#sidebarBrandIcon {
    background-color: #ffffff;
    padding: 0;
    margin: 0;
    border: none;
}

QPushButton#navButton {
    background-color: transparent;
    color: #374151;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 8px 10px 10px;
    min-height: 40px;
    max-height: 40px;
    font-weight: 700;
}

QPushButton#navButton:hover {
    background-color: #f3f4f6;
    color: #111827;
    font-weight: 700;
}

QPushButton#navButton:checked {
    font-weight: 700;
}

/* Per-item nav accents (icon + label association) — no left bar */
QPushButton#navButton[navAccent="home"]:hover {
    background-color: #fff7ed;
    color: #c2410c;
}
QPushButton#navButton[navAccent="home"]:checked {
    background-color: #ffedd5;
    color: #c2410c;
}

QPushButton#navButton[navAccent="images"]:hover {
    background-color: #ecfeff;
    color: #0e7490;
}
QPushButton#navButton[navAccent="images"]:checked {
    background-color: #cffafe;
    color: #0e7490;
}

QPushButton#navButton[navAccent="organize"]:hover {
    background-color: #eff6ff;
    color: #1d4ed8;
}
QPushButton#navButton[navAccent="organize"]:checked {
    background-color: #dbeafe;
    color: #1d4ed8;
}

QPushButton#navButton[navAccent="tags"]:hover {
    background-color: #fdf2f8;
    color: #be185d;
}
QPushButton#navButton[navAccent="tags"]:checked {
    background-color: #fce7f3;
    color: #be185d;
}

QPushButton#navButton[navAccent="settings"]:hover {
    background-color: #f1f5f9;
    color: #475569;
}
QPushButton#navButton[navAccent="settings"]:checked {
    background-color: #e2e8f0;
    color: #334155;
}

QPushButton#navButton[navAccent="about"]:hover {
    background-color: #f0fdfa;
    color: #0f766e;
}
QPushButton#navButton[navAccent="about"]:checked {
    background-color: #ccfbf1;
    color: #0f766e;
}

/* Future feature placeholder — visible but not selectable */
QPushButton#navButtonPlaceholder {
    background-color: transparent;
    color: #9ca3af;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 8px 10px 10px;
    min-height: 40px;
    max-height: 40px;
    font-weight: 700;
    opacity: 0.72;
}

QPushButton#navButtonPlaceholder:hover {
    background-color: #f3f4f6;
    color: #9ca3af;
}

QPushButton#navButtonPlaceholder:checked,
QPushButton#navButtonPlaceholder:pressed {
    background-color: transparent;
    color: #9ca3af;
    font-weight: normal;
}

QPushButton#saveFolderButton {
    background-color: #f3f4f6;
    color: #374151;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 36px;
    font-size: 12px;
    text-align: left;
}

QPushButton#saveFolderButton:hover {
    background-color: #e5e7eb;
    color: #111827;
    border-color: #d1d5db;
}

QWidget#currentProjectSelector {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}

QLabel#currentProjectLabel {
    color: #1e40af;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
    padding-left: 2px;
}

QComboBox#currentProjectCombo {
    background-color: transparent;
    color: #1e3a8a;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 28px;
    min-width: 110px;
    font-size: 13px;
    font-weight: bold;
}

QComboBox#currentProjectCombo:hover {
    background-color: #dbeafe;
}

QComboBox#currentProjectCombo::drop-down {
    border: none;
    width: 22px;
}

QComboBox#currentProjectCombo QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #dbeafe;
    selection-color: #1d4ed8;
    outline: none;
}

QWidget#currentFolderSelector {
    background-color: #ecfdf5;
    border: 1px solid #a7f3d0;
    border-radius: 8px;
}

QLabel#currentFolderLabel {
    color: #065f46;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
    padding-left: 2px;
}

QComboBox#currentFolderCombo {
    background-color: transparent;
    color: #064e3b;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 28px;
    min-width: 110px;
    font-size: 13px;
    font-weight: bold;
}

QComboBox#currentFolderCombo:hover {
    background-color: #d1fae5;
}

QComboBox#currentFolderCombo::drop-down {
    border: none;
    width: 22px;
}

QComboBox#currentFolderCombo QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #d1fae5;
    selection-color: #047857;
    outline: none;
}

/* ===== Page titles ===== */
QLabel#pageTitle {
    color: #111827;
    font-size: 20px;
    font-weight: 700;
}

QLabel#pageSubtitle {
    color: #4b5563;
    font-size: 12px;
    font-weight: 500;
    padding-bottom: 2px;
}

/* Page accent titles — shared pageHeader geometry; color only varies by page */
QWidget#pageHeader {
    background: transparent;
}

QWidget#homeContentColumn QLabel#pageTitle {
    color: #c2410c;
}
QWidget#homeContentColumn QLabel#pageSubtitle {
    color: #ea580c;
}

QWidget#imagesPageHeader QLabel#pageTitle {
    color: #0e7490;
}
QWidget#imagesPageHeader QLabel#pageSubtitle {
    color: #0891b2;
}

QWidget#organizePage QLabel#pageTitle {
    color: #1d4ed8;
}
QWidget#organizePage QLabel#pageSubtitle {
    color: #3b82f6;
}

QWidget#settingsContentColumn QLabel#pageTitle {
    color: #334155;
}
QWidget#settingsContentColumn QLabel#pageSubtitle {
    color: #64748b;
}

QLabel#comingSoonLabel {
    color: #9ca3af;
    font-size: 28px;
    font-weight: bold;
}

QLabel#statValue {
    color: #ea580c;
    font-size: 20px;
    font-weight: 700;
}

QFrame#statCard {
    background-color: #ffffff;
    border: 1px solid #fed7aa;
    border-radius: 12px;
    min-width: 220px;
    max-width: 220px;
}

/* Capture CTAs — near-square ToolButtons; Region green / Full Screen blue */
QToolButton#primaryLargeButton,
QToolButton#fullScreenCaptureButton,
QToolButton#regionCaptureButton {
    color: #ffffff;
    border-radius: 10px;
    padding: 6px 4px 4px 4px;
    font-size: 10px;
    font-weight: 700;
}

QToolButton#primaryLargeButton,
QToolButton#fullScreenCaptureButton {
    background-color: #2563eb;
    border: 1px solid #1d4ed8;
}

QToolButton#primaryLargeButton:hover,
QToolButton#fullScreenCaptureButton:hover {
    background-color: #1d4ed8;
}

QToolButton#primaryLargeButton:pressed,
QToolButton#fullScreenCaptureButton:pressed {
    background-color: #1e40af;
}

QToolButton#regionCaptureButton {
    background-color: #059669;
    border: 1px solid #047857;
}

QToolButton#regionCaptureButton:hover {
    background-color: #047857;
}

QToolButton#regionCaptureButton:pressed {
    background-color: #065f46;
}

QWidget#captureModeCycle {
    background: transparent;
}

QLabel#captureModeCycleLabel {
    color: #334155;
    font-size: 11px;
    font-weight: 700;
}

QPushButton#captureModeCycleButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 0;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}

QPushButton#captureModeCycleButton:hover {
    background-color: #f8fafc;
    border-color: #94a3b8;
}

QPushButton#captureModeCycleButton:pressed {
    background-color: #e2e8f0;
}

QFrame#captureModeDescCard {
    background: transparent;
    border: none;
    min-height: 52px;
}

QLabel#captureModeDescCaption {
    font-size: 13px;
    font-weight: 900;
    letter-spacing: 0.2px;
    border-radius: 5px;
    padding: 2px 8px;
}

QLabel#captureModeDescription {
    font-size: 11px;
    font-weight: 700;
    padding: 0;
    min-height: 28px;
}

/* Region = green (matches capture button) */
QLabel#captureModeDescCaption[mode="region"] {
    color: #047857;
    background-color: #d1fae5;
}

QLabel#captureModeDescription[mode="region"] {
    color: #059669;
}

/* Full Screen = blue (matches capture button) */
QLabel#captureModeDescCaption[mode="fullscreen"] {
    color: #1d4ed8;
    background-color: #dbeafe;
}

QLabel#captureModeDescription[mode="fullscreen"] {
    color: #2563eb;
}

QFrame#captureBarDivider {
    background-color: #e2e8f0;
    border: none;
    max-width: 1px;
}

QLabel#saveFolderStar {
    color: #2563eb;
    background: transparent;
    padding: 0;
    margin: 0;
}

QLabel#saveFolderLegend {
    color: #64748b;
    font-size: 10px;
}

QScrollArea#topBarScroll,
QScrollArea#pageScroll {
    background: transparent;
    border: none;
}

QWidget#saveDestinationSelector {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    min-height: 36px;
}

QLabel#saveDestinationIcon {
    font-size: 15px;
    padding-left: 2px;
}

QLabel#saveDestinationLabel {
    color: #475569;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.2px;
}

QComboBox#saveDestinationCombo {
    background-color: transparent;
    color: #0f172a;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 28px;
    min-width: 140px;
    font-size: 13px;
    font-weight: 700;
}

QComboBox#saveDestinationCombo:hover {
    background-color: #eef2ff;
}

QComboBox#saveDestinationCombo::drop-down {
    border: none;
    width: 22px;
}

QComboBox#saveDestinationCombo QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #dbeafe;
    selection-color: #1d4ed8;
    outline: none;
}

/* ===== Toolbar ===== */
QWidget#toolbar {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e7eb;
}

QLabel#projectLabel {
    color: #2563eb;
    font-size: 13px;
    padding: 0 8px;
}

QWidget#globalTopBar {
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff,
        stop:1 #fafbfc
    );
    border-bottom: 1px solid #e5e7eb;
}

QWidget#globalBottomBarHost {
    background: transparent;
}

QWidget#globalBottomBar {
    background-color: #ffffff;
    border: 1px solid #93c5fd;
    border-radius: 14px;
}

QFrame#captureSettingsStrip {
    background-color: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

/* Capture Panel opener — same accent family as the floating panel */
QWidget#capturePanelField {
    background: transparent;
    min-width: 108px;
    max-width: 128px;
}

QPushButton#capturePanelPopOutButton {
    background-color: #bfdbfe;
    color: #1e3a8a;
    border: 1px solid #60a5fa;
    border-radius: 8px;
    padding: 4px 8px;
    min-height: 26px;
    max-height: 28px;
    font-size: 10px;
    font-weight: 700;
}

QPushButton#capturePanelPopOutButton:hover {
    background-color: #93c5fd;
    color: #1e3a8a;
    border-color: #3b82f6;
}

QLabel#capturePanelFieldHint {
    color: #64748b;
    font-size: 9px;
    font-weight: 500;
    padding-left: 1px;
}

QWidget#capturePanelWindow {
    background: transparent;
}

/*
 * Square Capture Panel shell — soft blue fill, gentle border (not too dark).
 */
QFrame#capturePanelWindowChrome {
    background-color: #bfdbfe;
    border: 1px solid #93c5fd;
    border-radius: 0;
}

QWidget#capturePanelTitleBar {
    background-color: #93c5fd;
    border-radius: 0;
    border-bottom: 1px solid #93c5fd;
}

QWidget#capturePanelControls,
QWidget#capturePanelSideCol {
    background: transparent;
}

QLabel#capturePanelTitle {
    color: #1e3a8a;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.1px;
    padding-left: 2px;
}

QPushButton#capturePanelCloseButton,
QToolButton#capturePanelBackButton {
    background-color: #eff6ff;
    color: #1e40af;
    border: 1px solid #93c5fd;
    border-radius: 0;
    font-size: 11px;
    font-weight: 700;
    padding: 0;
    margin: 0;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}

/* Panel mode / settings — icon-only */
QPushButton#capturePanelModeButton,
QToolButton#capturePanelSettingsButton {
    background-color: transparent;
    color: #1e40af;
    border: none;
    border-radius: 0;
    padding: 0;
    margin: 0;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
}

QPushButton#capturePanelCloseButton:hover {
    background-color: #fecaca;
    border-color: #fca5a5;
    color: #991b1b;
}

QPushButton#capturePanelModeButton:hover,
QToolButton#capturePanelSettingsButton:hover {
    background-color: rgba(30, 64, 175, 0.14);
    border: none;
    color: #1e3a8a;
}

QToolButton#capturePanelBackButton:hover {
    background-color: #dbeafe;
    border-color: #93c5fd;
    color: #1e3a8a;
}

QPushButton#capturePanelModeButton:pressed,
QToolButton#capturePanelSettingsButton:pressed {
    background-color: rgba(30, 64, 175, 0.22);
    border: none;
}

QToolButton#capturePanelSettingsButton:disabled {
    background-color: transparent;
    border: none;
    color: #94a3b8;
}

/* Panel shot CTA — same two-line labels as the main Capture button */
QToolButton#capturePanelShotButton {
    border-radius: 0;
    font-size: 10px;
    font-weight: 700;
    padding: 4px 2px 4px 2px;
    spacing: 2px;
}

QToolButton#capturePanelShotButton[mode="region"] {
    background-color: #16a34a;
    color: #ffffff;
    border: 1px solid #15803d;
}

QToolButton#capturePanelShotButton[mode="region"]:hover {
    background-color: #15803d;
}

QToolButton#capturePanelShotButton[mode="fullscreen"] {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}

QToolButton#capturePanelShotButton[mode="fullscreen"]:hover {
    background-color: #1d4ed8;
}

QWidget#capturePanelWindowBody,
QWidget#capturePanelSettingsPage,
QStackedWidget#capturePanelStack {
    background-color: #bfdbfe;
}

QWidget#capturePanelCompactField {
    background: transparent;
    min-width: 0;
}

QLabel#capturePanelBodyHint {
    color: #1e40af;
    font-size: 11px;
    font-weight: 500;
}

QWidget#compactField {
    background: transparent;
    min-width: 100px;
}

QLabel#compactFieldLabel {
    color: #334155;
    font-size: 11px;
    font-weight: 700;
}

QLabel#compactFieldHint {
    color: #94a3b8;
    font-size: 9px;
    padding-left: 1px;
}

QLabel#compactFieldChevron {
    color: #64748b;
    font-size: 10px;
    padding: 0 2px;
    margin: 0;
    background: transparent;
    min-height: 22px;
    max-height: 22px;
}

/* Panel settings — keep ▼ on the same baseline as the value text */
QWidget#capturePanelWindow QLabel#compactFieldChevron {
    min-height: 22px;
    max-height: 22px;
    padding: 0 2px;
    margin: 0;
}

QFrame#compactFieldSep {
    background-color: #e2e8f0;
    border: none;
    max-width: 1px;
    min-width: 1px;
}

/* Shared value chrome for every setting (incl. Save folder + ★) */
QFrame#compactSettingValueRow {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    min-height: 26px;
    max-height: 26px;
}

QFrame#compactSettingValueRow:hover {
    border-color: #93c5fd;
    background-color: #f8fbff;
}

/* Panel settings — value frame can grow for long folder / filename text */
QFrame#compactSettingValueRowExpandable {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    min-height: 26px;
}

QFrame#compactSettingValueRowExpandable:hover {
    border-color: #f59e0b;
    background-color: #fffbeb;
}

QWidget#capturePanelWindow QLabel#compactFieldHint {
    color: #1e40af;
    font-size: 9px;
    font-weight: 500;
}

QWidget#capturePanelWindow QLabel#compactFieldLabel {
    color: #1e3a8a;
    font-size: 10px;
    font-weight: 700;
}

QWidget#capturePanelWindow QFrame#compactSettingValueRow,
QWidget#capturePanelWindow QFrame#compactSettingValueRowExpandable {
    background-color: #eff6ff;
    border: 1px solid #93c5fd;
    border-radius: 0;
}

QWidget#capturePanelWindow QFrame#compactSettingValueRow:hover,
QWidget#capturePanelWindow QFrame#compactSettingValueRowExpandable:hover {
    border-color: #7dd3fc;
    background-color: #dbeafe;
}

QLabel#imagesFileInfo {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
}

QWidget#sectionHeaderTitleRow {
    min-height: 28px;
    max-height: 28px;
}

/* Setting value text — combo is borderless inside the shared frame.
   Do NOT set max-height on QComboBox: Qt applies it to the popup and
   the list becomes ~one row tall / appears not to open. */
QComboBox#compactSettingCombo {
    background: transparent;
    color: #1d4ed8;
    border: none;
    border-radius: 0;
    padding: 2px 2px;
    min-height: 22px;
    font-size: 12px;
    font-weight: 700;
}

QComboBox#compactSettingCombo:hover,
QComboBox#compactSettingCombo:focus {
    background: transparent;
    border: none;
    color: #1e40af;
}

/* Keep a real hit target; arrow is drawn by CompactField's ▼ label */
QComboBox#compactSettingCombo::drop-down {
    border: none;
    width: 18px;
    background: transparent;
}

QComboBox#compactSettingCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}

QComboBox#compactSettingCombo QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #dbeafe;
    selection-color: #1d4ed8;
    outline: none;
    max-height: 220px;
}

QFrame#filenameRulePanel {
    background-color: transparent;
    border: none;
    border-radius: 0;
}

QLabel#filenameRuleTitle {
    color: #0f172a;
    font-size: 12px;
    font-weight: 600;
    padding: 0 0 4px 0;
}

/* Chip hugs ● + rule name + example; equal side padding */
QFrame#filenameRuleRow {
    background-color: #f3f4f6;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}

QFrame#filenameRuleRow:hover {
    border-color: #bfdbfe;
    background-color: #eef2ff;
}

QFrame#filenameRuleRow[selected="true"] {
    background-color: #eff6ff;
    border: 1px solid #2563eb;
}

QLabel#filenameRuleMarker {
    color: #2563eb;
    font-size: 13px;
    font-weight: 700;
    padding: 0;
    margin: 0;
    background: transparent;
    min-width: 14px;
    max-width: 14px;
}

/* Hide native radio disc — selection is the leading ● + chip border */
QRadioButton#filenameRuleRadio {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
    spacing: 0;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}

QRadioButton#filenameRuleRadio::indicator {
    width: 0;
    height: 0;
    border: none;
    margin: 0;
    padding: 0;
}

QFrame#filenameRuleRow[selected="true"] QRadioButton#filenameRuleRadio {
    color: #1d4ed8;
}

QLabel#filenameRuleExample {
    color: #64748b;
    font-size: 11px;
    padding: 0;
    background: transparent;
}

QFrame#filenameRuleRow[selected="true"] QLabel#filenameRuleExample {
    color: #1e40af;
    font-weight: 600;
}

QLabel#filenameRulePreview {
    color: #2563eb;
    font-size: 11px;
    font-weight: 600;
}

QLineEdit#filenameRuleCustomEdit {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px 8px;
}

QLabel#settingsAutosaveHint {
    color: #047857;
    font-size: 12px;
    font-weight: 500;
    padding: 2px 0 4px 0;
}

QWidget#statsChartPanel {
    background: transparent;
}

QWidget#segmentedToggle {
    background: transparent;
}

QPushButton#segmentButtonLeft,
QPushButton#segmentButtonMid,
QPushButton#segmentButtonRight {
    background-color: #f8fafc;
    color: #475569;
    border: 1px solid #e2e8f0;
    border-radius: 0px;
    padding: 5px 12px;
    min-height: 26px;
    font-size: 12px;
    font-weight: 500;
}

QPushButton#segmentButtonLeft {
    border-top-left-radius: 7px;
    border-bottom-left-radius: 7px;
}

QPushButton#segmentButtonRight {
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    margin-left: -1px;
}

QPushButton#segmentButtonMid {
    margin-left: -1px;
}

QPushButton#segmentButtonLeft:hover,
QPushButton#segmentButtonMid:hover,
QPushButton#segmentButtonRight:hover {
    background-color: #eff6ff;
    color: #1d4ed8;
    border-color: #bfdbfe;
}

QPushButton#segmentButtonLeft:checked,
QPushButton#segmentButtonMid:checked,
QPushButton#segmentButtonRight:checked {
    background-color: #eff6ff;
    color: #1d4ed8;
    border-color: #93c5fd;
    font-weight: 600;
}

QPushButton#segmentButtonLeft:pressed,
QPushButton#segmentButtonMid:pressed,
QPushButton#segmentButtonRight:pressed {
    background-color: #dbeafe;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 30px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton:disabled {
    background-color: #e5e7eb;
    color: #9ca3af;
}

QPushButton#secondaryButton {
    background-color: #f8fafc;
    color: #374151;
    border: 1px solid #e5e7eb;
}

QPushButton#secondaryButton:hover {
    background-color: #eff6ff;
    color: #1d4ed8;
    border-color: #bfdbfe;
}

QPushButton#secondaryButton:pressed {
    background-color: #dbeafe;
}

/* ===== Tag chips ===== */
QPushButton#tagChip {
    background-color: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #93c5fd;
    border-radius: 12px;
    padding: 4px 12px;
    min-height: 22px;
    font-size: 12px;
}

QPushButton#tagChip:hover {
    background-color: #dbeafe;
    color: #1e40af;
    border-color: #60a5fa;
}

/* Tags page — compact master chips (not full-width rows) */
QFrame#tagsChipPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QWidget#tagsChipHost {
    background: transparent;
}

QPushButton#tagMasterChip {
    background-color: #fdf2f8;
    color: #be185d;
    border: 1px solid #f9a8d4;
    border-radius: 14px;
    padding: 5px 12px;
    min-height: 26px;
    max-height: 28px;
    font-size: 12px;
    font-weight: 600;
}

QPushButton#tagMasterChip:hover {
    background-color: #fce7f3;
    border-color: #f472b6;
    color: #9d174d;
}

QPushButton#tagMasterChip:checked {
    background-color: #fce7f3;
    border: 1px solid #db2777;
    color: #9d174d;
    font-weight: 700;
}

QWidget#tagsSearchRow QLineEdit#tagsSearchInput {
    background-color: #ffffff;
    min-height: 26px;
    max-height: 28px;
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 6px;
}

QWidget#tagsSearchRow QPushButton {
    min-height: 26px;
    max-height: 28px;
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 6px;
}

QPushButton#tagModeButton {
    background-color: #f3f4f6;
    color: #4b5563;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 26px;
    font-size: 12px;
}

QPushButton#tagModeButton:hover {
    background-color: #e5e7eb;
    color: #111827;
}

QPushButton#tagModeButton:checked {
    background-color: #dbeafe;
    color: #1d4ed8;
    border-color: #2563eb;
    font-weight: bold;
}

/* ===== Inputs ===== */
QLineEdit {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 28px;
    selection-background-color: #bfdbfe;
}

QLineEdit:focus {
    border: 1px solid #2563eb;
}

QLineEdit:disabled {
    background-color: #f3f4f6;
    color: #9ca3af;
}

/* ===== Combo box ===== */
QComboBox {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 28px;
}

QComboBox:hover {
    border: 1px solid #2563eb;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #dbeafe;
    selection-color: #1d4ed8;
    outline: none;
}

/* ===== Folder tree (compact Explorer-like) ===== */
QWidget#folderPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QWidget#folderPanelCollapsed {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QWidget#folderPanelCollapsed:hover {
    background-color: #eff6ff;
    border-color: #93c5fd;
}

QLabel#folderExpandGlyph {
    color: #1d4ed8;
    font-size: 14px;
    font-weight: 700;
    background: transparent;
    border: none;
    padding: 0;
}

QPushButton#folderAddButton {
    background-color: #ffffff;
    color: #374151;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 26px;
    font-size: 12px;
    font-weight: 500;
    text-align: left;
}

QPushButton#folderAddButton:hover {
    background-color: #f3f4f6;
    color: #111827;
    border-color: #9ca3af;
}

QPushButton#folderAddButton:pressed {
    background-color: #e5e7eb;
}

QPushButton#sectionToggleButton {
    background-color: transparent;
    color: #6b7280;
    border: none;
    border-radius: 4px;
    padding: 0;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    font-size: 11px;
    font-weight: bold;
}

QPushButton#sectionToggleButton:hover {
    background-color: #e5e7eb;
    color: #111827;
}

QTreeWidget#folderTree {
    background-color: #fafafa;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    outline: none;
    padding: 2px;
    color: #1f2937;
    font-size: 12px;
    show-decoration-selected: 1;
}

QTreeWidget#folderTree::item {
    padding: 2px 4px 2px 2px;
    border-radius: 4px;
    min-height: 22px;
    margin: 0px;
}

QTreeWidget#folderTree::item:hover {
    background-color: #eef2ff;
}

QTreeWidget#folderTree::item:selected {
    background-color: #d1fae5;
    color: #047857;
    font-weight: bold;
}

/* Drop target while dragging images — distinct from current-folder green */
QTreeWidget#folderTree[dropping="true"]::item:selected {
    background-color: #bfdbfe;
    color: #1e40af;
    font-weight: bold;
    border: 1px solid #2563eb;
}

QTreeWidget#folderTree[dropping="true"]::item:hover {
    background-color: #dbeafe;
}

QTreeWidget#folderTree::branch {
    background-color: transparent;
    border-image: none;
    image: none;
}

QTreeWidget {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    outline: none;
    padding: 1px;
    color: #1f2937;
}

QTreeWidget::item {
    padding: 0px 2px;
    border-radius: 3px;
    min-height: 16px;
}

QTreeWidget::item:hover {
    background-color: #eef2ff;
}

QTreeWidget::item:selected {
    background-color: #dbeafe;
    color: #1d4ed8;
}

QTreeWidget::branch {
    background-color: transparent;
}

/* ===== Thumbnail list ===== */
QListWidget {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    outline: none;
    padding: 10px;
}

QListWidget::item {
    color: #1f2937;
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 8px;
    margin: 5px;
}

QListWidget::item:hover {
    background-color: #eff6ff;
    border: 1px solid #93c5fd;
}

QListWidget::item:selected {
    background-color: #bfdbfe;
    border: 2px solid #2563eb;
    color: #1e3a8a;
}

QListWidget::item:selected:hover {
    background-color: #93c5fd;
    border: 2px solid #1d4ed8;
}

QListWidget#screenshotList {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 4px;
}

/* ListMode: keep readable rows (not transparent like IconMode captions) */
QListWidget#screenshotList[captionMode="list"]::item {
    color: #1f2937;
    background-color: transparent;
    border: none;
    padding: 0;
    margin: 1px;
}

QListWidget#screenshotList[captionMode="list"]::item:hover,
QListWidget#screenshotList[captionMode="list"]::item:selected,
QListWidget#screenshotList[captionMode="list"]::item:selected:hover {
    background-color: transparent;
    border: none;
}

/* IconMode captions are painted by CaptionIconDelegate */
QListWidget#screenshotList[captionMode="icon"]::item {
    color: transparent;
    background-color: transparent;
    border: none;
    padding: 0;
    margin: 2px;
}

QListWidget#screenshotList[captionMode="icon"]::item:hover,
QListWidget#screenshotList[captionMode="icon"]::item:selected,
QListWidget#screenshotList[captionMode="icon"]::item:selected:hover {
    background-color: transparent;
    border: none;
}

/* ===== Filename template (global top bar) ===== */
QWidget#filenameTemplateSelector {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}

QLabel#filenameTemplateLabel {
    color: #475569;
    font-size: 12px;
    font-weight: 600;
}

QComboBox#filenameTemplateCombo {
    background-color: transparent;
    color: #0f172a;
    border: none;
    padding: 2px 4px;
    min-width: 160px;
}

QComboBox#filenameTemplateCombo:hover {
    background-color: #eef2ff;
    border-radius: 6px;
}

QComboBox#filenameTemplateCombo::drop-down {
    border: none;
    width: 18px;
}

QComboBox#filenameTemplateCombo QAbstractItemView {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    selection-background-color: #dbeafe;
    selection-color: #1d4ed8;
}

QLabel#filenameTemplatePreview {
    color: #64748b;
    font-size: 11px;
    padding-left: 2px;
}

/* ===== Preview ===== */
QLabel#previewLabel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    color: #6b7280;
    padding: 8px;
}

QPushButton#statCardIconButton {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 0;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}

QPushButton#statCardIconButton:hover {
    background-color: #f8fafc;
    border-color: #cbd5e1;
}

QPushButton#statCardIconButton:pressed {
    background-color: #f1f5f9;
}

/* ===== Panels ===== */
QWidget#leftPanel, QWidget#rightPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QWidget#rightPanel {
    max-width: 480px;
}

QWidget#infoPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

/* ===== Empty-state hints (Home / Images) ===== */
QFrame#emptyHintCard {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QLabel#emptyHintTitle {
    color: #111827;
    font-size: 14px;
    font-weight: 700;
}

QLabel#emptyHintBody {
    color: #4b5563;
    font-size: 13px;
    font-weight: 500;
}

QLabel#emptyHintMeta {
    color: #6b7280;
    font-size: 12px;
    font-weight: 500;
}

/* ===== About page ===== */
QFrame#aboutCard {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QLabel#aboutBrandTitle {
    color: #111827;
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.3px;
}

QLabel#aboutBrandMark {
    background: transparent;
    padding: 0;
    margin: 0;
}

QLabel#aboutTagline {
    color: #4b5563;
    font-size: 14px;
    font-weight: 500;
}

QLabel#aboutVersionBadge {
    color: #0f766e;
    background-color: #f0fdfa;
    border: 1px solid #99f6e4;
    border-radius: 8px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}

QLabel#aboutSectionHeading {
    color: #111827;
    font-size: 14px;
    font-weight: 700;
}

QLabel#aboutSectionHint {
    color: #6b7280;
    font-size: 12px;
    font-weight: 500;
}

QPushButton#aboutLinkButton {
    background-color: #f9fafb;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    font-weight: 600;
    text-align: left;
}

QPushButton#aboutLinkButton:hover {
    background-color: #f0fdfa;
    border-color: #5eead4;
    color: #0f766e;
}

QPushButton#aboutLinkButton:pressed {
    background-color: #ccfbf1;
}

QFrame#aboutFeedbackRow {
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}

QFrame#aboutFeedbackRow:hover {
    background-color: #f0fdfa;
    border-color: #5eead4;
}

QFrame#aboutFeedbackRow:focus {
    border-color: #2dd4bf;
}

QLabel#aboutFeedbackTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}

QLabel#aboutFeedbackDesc {
    color: #6b7280;
    font-size: 12px;
    font-weight: 500;
}

QLabel#aboutFeedbackIcon,
QLabel#aboutFeedbackChevron {
    background: transparent;
    border: none;
}

QFrame#aboutLegalFooter {
    background: transparent;
    border: none;
}

QLabel#aboutLegalText {
    color: #9ca3af;
    font-size: 11px;
    font-weight: 500;
}

QWidget#aboutContentColumn QLabel#pageTitle {
    color: #0f766e;
}

/* ===== App floating toast (not Windows notification center) ===== */
QWidget#floatingToast {
    background: transparent;
}

QFrame#floatingToastCard {
    background-color: rgba(255, 255, 255, 242);
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}

QFrame#floatingToastAccent {
    background-color: #16a34a;
    border: none;
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}

QFrame#floatingToastAccent[kind="success"] {
    background-color: #16a34a;
}

QFrame#floatingToastAccent[kind="error"] {
    background-color: #dc2626;
}

QLabel#floatingToastIcon {
    color: #16a34a;
    font-size: 14px;
    font-weight: 800;
    min-width: 16px;
}

QFrame#floatingToastCard[kind="error"] QLabel#floatingToastIcon {
    color: #dc2626;
}

QLabel#floatingToastTitle {
    color: #0f172a;
    font-size: 13px;
    font-weight: 800;
}

QLabel#floatingToastLine {
    color: #475569;
    font-size: 12px;
    font-weight: 500;
}

QPushButton#floatingToastClose {
    background-color: transparent;
    color: #94a3b8;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 700;
    padding: 0;
}

QPushButton#floatingToastClose:hover {
    background-color: #f1f5f9;
    color: #334155;
}

QPushButton#floatingToastAction {
    background-color: #f8fafc;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}

QFrame#shortcutRow {
    background-color: transparent;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 0;
    margin: 0;
}

QLabel#shortcutActionLabel {
    color: #111827;
    font-size: 12px;
    font-weight: 600;
}

QLabel#shortcutValueLabel {
    color: #2563eb;
    font-size: 13px;
    font-weight: 700;
    padding: 4px 10px;
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
}

QLabel#shortcutCapturePrompt {
    color: #0f172a;
    font-size: 14px;
    font-weight: 700;
}

QWidget#sectionHeader {
    background: transparent;
}

QLabel#sectionTitle {
    color: #111827;
    font-weight: 700;
    font-size: 13px;
}

QLabel#sectionIcon {
    background: transparent;
}

QLabel#toolbarFieldLabel {
    color: #64748b;
    font-size: 10px;
    font-weight: 700;
}

QWidget#headerToolField,
QWidget#listToolbar,
QWidget#screenshotsSearchRow {
    background: transparent;
}

/* Images Sort / Group By / View — same chip language as Organize Folder */
QFrame#headerTools,
QWidget#headerTools {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}

QWidget#headerTools QLabel#toolbarFieldLabel,
QFrame#headerTools QLabel#toolbarFieldLabel {
    color: #1d4ed8;
    font-size: 11px;
    font-weight: 700;
    padding: 0;
}

QWidget#headerTools QComboBox,
QFrame#headerTools QComboBox {
    background-color: #ffffff;
    color: #1e3a8a;
    border: 1px solid #93c5fd;
    min-height: 24px;
    max-height: 26px;
    padding: 2px 8px;
    font-size: 12px;
    font-weight: 700;
    border-radius: 6px;
}

QWidget#headerTools QComboBox:hover,
QWidget#headerTools QComboBox:focus,
QWidget#headerTools QComboBox:on,
QFrame#headerTools QComboBox:hover,
QFrame#headerTools QComboBox:focus,
QFrame#headerTools QComboBox:on {
    background-color: #ffffff;
    border: 1px solid #2563eb;
}

QWidget#listToolbar QComboBox,
QWidget#screenshotsSearchRow QComboBox {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    min-height: 24px;
    max-height: 26px;
    padding: 2px 8px;
    font-size: 11px;
    border-radius: 6px;
}

QWidget#listToolbar QComboBox:hover {
    background-color: #ffffff;
    border: 1px solid #2563eb;
}

QWidget#headerTools QComboBox::drop-down,
QWidget#listToolbar QComboBox::drop-down {
    border: none;
    width: 18px;
    background: transparent;
}

QWidget#headerTools QComboBox QAbstractItemView,
QFrame#headerTools QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #bfdbfe;
}

QWidget#headerTools QPushButton,
QWidget#listToolbar QPushButton,
QWidget#screenshotsSearchRow QPushButton {
    min-height: 26px;
    max-height: 28px;
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 6px;
}

QWidget#listToolbar QLineEdit,
QWidget#screenshotsSearchRow QLineEdit,
QLineEdit#screenshotsSearchInput {
    background-color: #ffffff;
    min-height: 26px;
    max-height: 28px;
    padding: 3px 10px;
    font-size: 11px;
    border-radius: 6px;
}

QWidget#listToolbar {
    spacing: 4px;
}

QFrame#sectionDivider {
    background-color: #e5e7eb;
    border: none;
    max-height: 1px;
    min-height: 1px;
}

QLabel#mutedLabel {
    color: #6b7280;
    font-size: 12px;
    font-weight: 500;
}

QWidget#folderPanel QLabel#sectionTitle {
    color: #0e7490;
    font-weight: 700;
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #e5e7eb;
    width: 2px;
}

/* Images: frames already separate panels — no gray gutter lines */
QSplitter#imagesSplitter::handle {
    background-color: transparent;
}

/* ===== Menu ===== */
QMenu {
    background-color: #ffffff;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    padding: 4px;
    border-radius: 8px;
}

QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #dbeafe;
    color: #1d4ed8;
}

QMenu::separator {
    height: 1px;
    background: #e5e7eb;
    margin: 4px 8px;
}

/* ===== Message boxes / dialogs ===== */
QMessageBox {
    background-color: #ffffff;
    color: #1f2937;
}

QMessageBox QPushButton {
    min-width: 70px;
}

QInputDialog {
    background-color: #ffffff;
}

/* Simple, high-contrast scrollbars (page + lists) */
QScrollBar:vertical {
    background: #e8eaed;
    width: 12px;
    margin: 2px 1px 2px 1px;
    border: none;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #64748b;
    border-radius: 5px;
    min-height: 28px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::handle:vertical:pressed {
    background: #334155;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: #e8eaed;
    height: 12px;
    margin: 1px 2px 1px 2px;
    border: none;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #64748b;
    border-radius: 5px;
    min-width: 28px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: #475569;
}

QScrollBar::handle:horizontal:pressed {
    background: #334155;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    border: none;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ===== Organize page (select + operate) ===== */
QWidget#organizePage {
    background-color: #f5f6f8;
}

QWidget#organizeBody {
    background: transparent;
}

QSplitter#organizeSplitter::handle {
    background-color: transparent;
}

QFrame#organizeListPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QFrame#organizeOpsPanel {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 12px;
}

QWidget#organizeOpsHub,
QWidget#organizeOpsDetail,
QStackedWidget#organizeOpsNavStack,
QStackedWidget#organizeOpStack,
QWidget#organizeOpPicker,
QFrame#organizeOpDetailBody {
    background-color: #ffffff;
    border: none;
}

QScrollArea#organizeOpsScroll,
QScrollArea#organizeOpsDetailScroll {
    background-color: #ffffff;
    border: none;
}

QScrollArea#organizeOpsScroll > QWidget > QWidget,
QScrollArea#organizeOpsDetailScroll > QWidget > QWidget {
    background-color: #ffffff;
}


QLabel#organizeListTitle {
    color: #1d4ed8;
    font-weight: 700;
    font-size: 13px;
}

QFrame#organizeRootChip {
    background-color: #fff7ed;
    border: 1px solid #fdba74;
    border-radius: 8px;
}

QLabel#organizeRootLabel {
    color: #c2410c;
    font-size: 11px;
    font-weight: 700;
}

QLabel#organizeRootValue {
    color: #ea580c;
    font-size: 12px;
    font-weight: 700;
}

/* Current working folder — clearer than Sort/View, not loud */
QFrame#organizeFolderChip {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}

QLabel#organizeFolderLabel {
    color: #1d4ed8;
    font-size: 11px;
    font-weight: 700;
}

QComboBox#organizeFolderCombo {
    background-color: #ffffff;
    color: #1e3a8a;
    border: 1px solid #93c5fd;
    border-radius: 6px;
    padding: 2px 8px;
    min-height: 24px;
    max-height: 26px;
    font-size: 12px;
    font-weight: 700;
}

QComboBox#organizeFolderCombo:hover {
    border: 1px solid #2563eb;
    background-color: #ffffff;
}

QComboBox#organizeFolderCombo::drop-down {
    border: none;
    width: 18px;
}

QLabel#organizeOpsTitle {
    color: #312e81;
    font-weight: 700;
    font-size: 15px;
    letter-spacing: 0.2px;
    padding: 0;
    margin: 0;
}

QLabel#organizeOpsHint {
    color: #6b7280;
    font-size: 11px;
    padding: 0;
    margin: 0;
}

QFrame#operationMenuItem:focus {
    outline: none;
}

QFrame#organizeSelectionBanner {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
}

QLabel#organizeSelectedHeading {
    color: #1d4ed8;
    font-size: 11px;
    font-weight: 600;
}

QLabel#organizeSelectedCount {
    color: #1e40af;
    font-size: 14px;
    font-weight: 700;
}

QWidget#organizeOpPicker {
    background-color: #ffffff;
    border: none;
}

QScrollArea#organizeOpsScroll,
QScrollArea#organizeOpsDetailScroll {
    background-color: #ffffff;
    border: none;
}

/* Hub menu items — default / unselected */
QFrame#operationMenuItem {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QFrame#operationMenuItem[hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #f8fafc;
    border: 1px solid #d1d5db;
}

QFrame#operationMenuItem[enabledOp="false"] {
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
}

QLabel#operationMenuTitle {
    color: #111827;
    font-size: 12px;
    font-weight: 700;
}

QLabel#operationMenuDesc {
    color: #6b7280;
    font-size: 11px;
}

QLabel#operationMenuStatus {
    color: #9ca3af;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
    background-color: #f3f4f6;
    border-radius: 8px;
}

/* Selected / hover accents by op */
QFrame#operationMenuItem[opId="tags"][selected="true"] {
    background-color: #f5f3ff;
    border: 1px solid #c4b5fd;
}
QFrame#operationMenuItem[opId="tags"][hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #ede9fe;
    border: 1px solid #ddd6fe;
}
QFrame#operationMenuItem[opId="tags"][selected="true"] QLabel#operationMenuTitle {
    color: #5b21b6;
}

QFrame#operationMenuItem[opId="rename"][selected="true"] {
    background-color: #fff7ed;
    border: 1px solid #fdba74;
}
QFrame#operationMenuItem[opId="rename"][hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #ffedd5;
    border: 1px solid #fed7aa;
}
QFrame#operationMenuItem[opId="rename"][selected="true"] QLabel#operationMenuTitle {
    color: #c2410c;
}

QFrame#operationMenuItem[opId="convert"][selected="true"] {
    background-color: #faf5ff;
    border: 1px solid #d8b4fe;
}
QFrame#operationMenuItem[opId="convert"][hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #f3e8ff;
    border: 1px solid #e9d5ff;
}
QFrame#operationMenuItem[opId="convert"][selected="true"] QLabel#operationMenuTitle {
    color: #6d28d9;
}

QFrame#operationMenuItem[opId="resize"][selected="true"] {
    background-color: #ecfdf5;
    border: 1px solid #6ee7b7;
}
QFrame#operationMenuItem[opId="resize"][hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #d1fae5;
    border: 1px solid #a7f3d0;
}
QFrame#operationMenuItem[opId="resize"][selected="true"] QLabel#operationMenuTitle {
    color: #047857;
}

QFrame#operationMenuItem[opId="export"][selected="true"] {
    background-color: #f0fdfa;
    border: 1px solid #5eead4;
}
QFrame#operationMenuItem[opId="export"][hovered="true"][selected="false"][enabledOp="true"] {
    background-color: #ccfbf1;
    border: 1px solid #99f6e4;
}
QFrame#operationMenuItem[opId="export"][selected="true"] QLabel#operationMenuTitle {
    color: #0f766e;
}

QPushButton#organizeOpsBackButton {
    background-color: transparent;
    color: #2563eb;
    border: none;
    border-radius: 6px;
    padding: 2px 0;
    font-size: 12px;
    font-weight: 600;
    text-align: left;
}

QPushButton#organizeOpsBackButton:hover {
    color: #1d4ed8;
}

QFrame#organizeOpsDetailHeader {
    background-color: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QFrame#organizeOpsSelectedStrip {
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QLabel#organizeOpsSelectedCount {
    color: #111827;
    font-size: 13px;
    font-weight: 700;
}

/* Detail accents */
QFrame#organizeOpsDetailHeader[opId="tags"],
QFrame#organizeOpsSelectedStrip[opId="tags"] {
    background-color: #f5f3ff;
    border: 1px solid #c4b5fd;
}
QFrame#organizeOpsPanel[opId="tags"] QLabel#organizeOpsTitle {
    color: #5b21b6;
}

QFrame#organizeOpsDetailHeader[opId="rename"],
QFrame#organizeOpsSelectedStrip[opId="rename"] {
    background-color: #fff7ed;
    border: 1px solid #fdba74;
}
QFrame#organizeOpsPanel[opId="rename"] QLabel#organizeOpsTitle {
    color: #c2410c;
}

QFrame#organizeOpsDetailHeader[opId="convert"],
QFrame#organizeOpsSelectedStrip[opId="convert"] {
    background-color: #faf5ff;
    border: 1px solid #d8b4fe;
}
QFrame#organizeOpsPanel[opId="convert"] QLabel#organizeOpsTitle {
    color: #6d28d9;
}

QFrame#organizeOpsDetailHeader[opId="resize"],
QFrame#organizeOpsSelectedStrip[opId="resize"] {
    background-color: #ecfdf5;
    border: 1px solid #6ee7b7;
}
QFrame#organizeOpsPanel[opId="resize"] QLabel#organizeOpsTitle {
    color: #047857;
}

QFrame#organizeOpsDetailHeader[opId="export"],
QFrame#organizeOpsSelectedStrip[opId="export"] {
    background-color: #f0fdfa;
    border: 1px solid #5eead4;
}
QFrame#organizeOpsPanel[opId="export"] QLabel#organizeOpsTitle {
    color: #0f766e;
}

QFrame#organizeOpDetailBody {
    background-color: transparent;
    border: none;
}

QPushButton#organizeOpPrimaryButton {
    min-width: 140px;
    padding: 6px 14px;
    border-radius: 8px;
    border: 1px solid transparent;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#organizeOpPrimaryButton[opId="tags"] {
    background-color: #7c3aed;
    border-color: #6d28d9;
}
QPushButton#organizeOpPrimaryButton[opId="tags"]:hover {
    background-color: #6d28d9;
}

QPushButton#organizeOpPrimaryButton[opId="rename"] {
    background-color: #ea580c;
    border-color: #c2410c;
}
QPushButton#organizeOpPrimaryButton[opId="rename"]:hover {
    background-color: #c2410c;
}

QPushButton#organizeOpSecondaryButton {
    min-width: 140px;
    padding: 6px 14px;
    border-radius: 8px;
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    color: #374151;
    font-weight: 600;
}

QPushButton#organizeOpSecondaryButton[opId="tags"] {
    border-color: #c4b5fd;
    color: #5b21b6;
    background-color: #faf5ff;
}
QPushButton#organizeOpSecondaryButton[opId="tags"]:hover {
    background-color: #f5f3ff;
}

QLabel#organizeBulkSectionLabel {
    color: #374151;
    font-size: 11px;
    font-weight: 700;
    margin-top: 2px;
}

QListWidget#organizeImageList {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 4px;
    selection-background-color: #dbeafe;
}

/* Tags page accent */
QWidget#tagsContentColumn QLabel#pageTitle {
    color: #be185d;
}
QWidget#tagsContentColumn QLabel#pageSubtitle {
    color: #db2777;
}
"""

# Backwards-compatible alias (old import name)
DARK_STYLE = APP_STYLE
