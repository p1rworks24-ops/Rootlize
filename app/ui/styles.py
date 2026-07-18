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

QLabel#sidebarBrand {
    color: #111827;
    font-size: 13px;
    font-weight: bold;
    padding: 4px 4px 8px 4px;
}

QPushButton#navButton {
    background-color: transparent;
    color: #4b5563;
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 8px 10px 10px;
    min-height: 40px;
    max-height: 40px;
    border-left: 3px solid transparent;
}

QPushButton#navButton:hover {
    background-color: #eef2ff;
    color: #1d4ed8;
}

QPushButton#navButton:checked {
    background-color: #dbeafe;
    color: #1d4ed8;
    border-left: 3px solid #2563eb;
    font-weight: bold;
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
    border-left: 3px solid transparent;
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
    border-left: 3px solid transparent;
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
    font-size: 22px;
    font-weight: 600;
}

QLabel#pageSubtitle {
    color: #6b7280;
    font-size: 12px;
    font-weight: 400;
    padding-bottom: 2px;
}

QLabel#comingSoonLabel {
    color: #9ca3af;
    font-size: 28px;
    font-weight: bold;
}

QLabel#statValue {
    color: #2563eb;
    font-size: 20px;
    font-weight: 600;
}

QFrame#statCard {
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff,
        stop:1 #fafbfc
    );
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    min-width: 220px;
}

/* Capture CTAs — near-square ToolButtons; Region green / Full Screen blue */
QToolButton#primaryLargeButton,
QToolButton#fullScreenCaptureButton,
QToolButton#regionCaptureButton {
    color: #ffffff;
    border-radius: 10px;
    padding: 6px 4px 4px 4px;
    font-size: 11px;
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
    color: #94a3b8;
    font-size: 10px;
    font-weight: 500;
}

QPushButton#captureModeCycleButton {
    background-color: #f8fafc;
    color: #475569;
    border: 1px solid #e2e8f0;
    border-radius: 7px;
    padding: 0;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}

QPushButton#captureModeCycleButton:hover {
    background-color: #eff6ff;
    border-color: #bfdbfe;
}

QPushButton#captureModeCycleButton:pressed {
    background-color: #dbeafe;
}

QLabel#captureModeDescription {
    color: #94a3b8;
    font-size: 10px;
    padding: 0 2px;
    min-height: 28px;
}

QWidget#captureCluster {
    background: transparent;
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
QScrollArea#bottomBarScroll,
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
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff,
        stop:1 #fafbfc
    );
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QFrame#captureSettingsStrip {
    background: transparent;
    border: none;
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
    font-size: 9px;
    padding: 0 2px;
    background: transparent;
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

/* Setting value text — combo is borderless inside the shared frame */
QComboBox#compactSettingCombo {
    background: transparent;
    color: #1d4ed8;
    border: none;
    border-radius: 0;
    padding: 2px 2px;
    min-height: 22px;
    max-height: 22px;
    font-size: 12px;
    font-weight: 700;
}

QComboBox#compactSettingCombo:hover,
QComboBox#compactSettingCombo:focus {
    background: transparent;
    border: none;
    color: #1e40af;
}

QComboBox#compactSettingCombo::drop-down {
    border: none;
    width: 0;
    max-width: 0;
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
    border-radius: 10px;
}

QWidget#folderPanelCollapsed {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QWidget#folderPanelCollapsed QLabel,
QWidget#folderPanelCollapsed QTreeWidget,
QWidget#folderPanelCollapsed QPushButton#folderAddButton {
    max-width: 0px;
    max-height: 0px;
    margin: 0px;
    padding: 0px;
    border: none;
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
    color: #9ca3af;
    padding: 8px;
}

/* ===== Panels ===== */
QWidget#leftPanel, QWidget#rightPanel {
    background-color: #f5f6f8;
}

QWidget#rightPanel {
    max-width: 480px;
}

QWidget#infoPanel {
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #ffffff,
        stop:1 #fafbfc
    );
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QWidget#sectionHeader {
    background: transparent;
}

QLabel#sectionTitle {
    color: #111827;
    font-weight: 600;
    font-size: 13px;
}

QLabel#sectionIcon {
    background: transparent;
}

QLabel#toolbarFieldLabel {
    color: #6b7280;
    font-size: 11px;
}

QWidget#headerTools {
    background: transparent;
}

QWidget#headerTools QComboBox {
    min-height: 24px;
    padding: 2px 8px;
    font-size: 12px;
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
}

/* ===== Splitter ===== */
QSplitter::handle {
    background-color: #e5e7eb;
    width: 2px;
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

QScrollBar:vertical {
    background: #f5f6f8;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #d1d5db;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #9ca3af;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ===== Organize page (select + operate) ===== */
QFrame#organizeListPanel,
QFrame#organizeOpsPanel {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QFrame#organizeSelectionBanner {
    background-color: #f3f4f6;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QLabel#organizeSelectedHeading {
    color: #6b7280;
    font-size: 11px;
    font-weight: 500;
}

QLabel#organizeSelectedCount {
    color: #111827;
    font-size: 18px;
    font-weight: 600;
}

QFrame#organizeOpPicker {
    background-color: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QPushButton#operationButton {
    text-align: left;
    padding: 9px 12px;
    border: 1px solid transparent;
    border-radius: 8px;
    background-color: transparent;
    color: #374151;
    font-weight: 500;
}

QPushButton#operationButton:hover {
    background-color: #ffffff;
    border-color: #e5e7eb;
}

QPushButton#operationButton:checked {
    background-color: #ffffff;
    border-color: #d1d5db;
    color: #111827;
    font-weight: 600;
}

QFrame#organizeOpSettings {
    background-color: #fafbfc;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
}

QListWidget#organizeImageList {
    background-color: #fafbfc;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 6px;
}
"""

# Backwards-compatible alias (old import name)
DARK_STYLE = APP_STYLE
