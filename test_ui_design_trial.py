"""UI Design Guidelines v1 trial: shared switches and shell behavior."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QFrame, QWidget
from PySide6.QtGui import QFontInfo, QFontMetrics
from PySide6.QtTest import QTest

from app.i18n import t
from app.services.capture_modes import CAPTURE_FULLSCREEN, CAPTURE_REGION
from app.ui.design_tokens import (
    COLORS,
    NAV_EMPHASIS,
    NAV_RESPONSIVE_BREAKPOINT,
    PAGE_HEADER_SYMBOL_HERO,
    SHADOW_MODE,
    token_style_sheet,
)
from app.ui.icons import icon_images
from app.ui.fonts import install_ui_font
from app.ui.main_window import MainWindow, PAGE_IMAGES
from app.ui.page_header import PAGE_HEADER_MARGINS, make_page_header


def _ensure_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    install_ui_font(app)
    return app


def _make_window(
    *,
    capture_bar_visible: bool = True,
    window_width: int = 1000,
    capture_mode: str = CAPTURE_REGION,
) -> MainWindow:
    root = Path(tempfile.mkdtemp())
    (root / "screenshots" / "Capture").mkdir(parents=True)
    window = MainWindow(
        {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": window_width,
            "window_height": 700,
            "capture_bar_visible": capture_bar_visible,
            "capture_mode": capture_mode,
        }
    )
    # Capture controls belong to Images and are intentionally absent on Home.
    window._show_page(PAGE_IMAGES)
    return window


def test_trial_switches_and_navigation_style_are_centralized():
    assert SHADOW_MODE in {"soft", "weak", "off"}
    assert NAV_EMPHASIS in {"trial", "quiet"}
    style = token_style_sheet()
    assert "Design Guidelines v1 trial tokens" in style
    assert "captureBarToggleButton" in style
    assert "border-left" not in style


def test_shared_page_background_and_images_accent_are_tokenized():
    style = token_style_sheet().lower()
    assert "#f7faff" in style
    assert COLORS.card_border in style
    assert "qwidget#pageheadertext" in style
    assert "qstackedwidget#imagesliststack" in style
    assert "qwidget#imagesworkspacepage qlabel#pagetitle" in style


def test_page_header_accepts_navigation_icon_and_semantic_accent():
    _ensure_app()
    root = QFrame()
    header = make_page_header(
        root, "Images", "Find screenshots", icon=icon_images(), accent="information"
    )
    symbol = header.findChild(QFrame, "pageHeaderSymbol")
    assert symbol is not None
    assert symbol.property("accent") == "information"
    assert symbol.size().width() == symbol.size().height() == 40

    hero = make_page_header(
        root,
        "Images",
        "Find screenshots",
        icon=icon_images(),
        accent="information",
        emphasis="hero",
    )
    hero_symbol = hero.findChild(QFrame, "pageHeaderSymbol")
    assert hero.property("emphasis") == "hero"
    assert hero_symbol is not None
    assert hero_symbol.size().width() == hero_symbol.size().height() == (
        PAGE_HEADER_SYMBOL_HERO
    )
    assert hero_symbol.findChild(QFrame, "pageHeaderSymbolGlow") is not None
    assert hero_symbol.findChild(QFrame, "pageHeaderSymbolShape") is not None


def test_capture_bar_is_compact_and_can_restore_persisted_visibility(monkeypatch):
    app = _ensure_app()
    saved: list[dict] = []
    monkeypatch.setattr(
        "app.ui.main_window.save_config", lambda config: saved.append(dict(config))
    )
    window = _make_window(capture_bar_visible=False)
    window.show()
    app.processEvents()

    assert window._capture_bar.isHidden()
    assert not window._capture_bar_restore_row.isHidden()
    assert window._capture_bar_restore_btn.text() == ""
    assert not window._capture_bar_restore_btn.icon().isNull()
    assert window._capture_bar_restore_btn.toolTip() == t(
        "shell.capture_bar.show_tooltip"
    )
    assert window._capture_btn.height() == 60

    window._capture_bar_restore_btn.click()
    app.processEvents()
    assert not window._capture_bar.isHidden()
    assert window._capture_bar_restore_row.isHidden()
    assert window._capture_bar_toggle_btn.text() == ""
    assert not window._capture_bar_toggle_btn.icon().isNull()
    assert window._capture_bar_toggle_btn.toolTip() == t(
        "shell.capture_bar.hide_tooltip"
    )
    assert window._config["capture_bar_visible"] is True
    assert saved[-1]["capture_bar_visible"] is True
    window.close()

    restarted = _make_window(
        capture_bar_visible=saved[-1]["capture_bar_visible"], window_width=720
    )
    restarted.show()
    app.processEvents()
    assert not restarted._capture_bar.isHidden()
    assert restarted._capture_btn.isVisible()
    assert restarted._capture_btn.geometry().right() < restarted._capture_bar.width()
    restarted.close()


def test_trial_navigation_and_capture_hide_action_have_clear_visual_positions():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True)
    window.show()
    app.processEvents()

    images_button = window._side_nav._nav_buttons[1]
    if NAV_EMPHASIS == "trial":
        assert images_button.iconSize().width() == 28

    capture_layout = window._capture_bar_layout
    assert capture_layout.indexOf(window._capture_action_field) < capture_layout.indexOf(
        window._capture_mode_selector
    )
    assert capture_layout.indexOf(window._capture_mode_selector) < capture_layout.indexOf(
        window._capture_settings_scroll
    )
    assert capture_layout.indexOf(window._capture_settings_scroll) < capture_layout.indexOf(
        window._capture_panel_field
    )
    assert window._capture_btn.parentWidget() is window._capture_action_field
    assert window._capture_btn.graphicsEffect() is None
    assert window._capture_bar_restore_row.isHidden()
    assert not hasattr(window, "_folder_combo")
    assert window._capture_settings_scroll.maximumWidth() == 360
    assert window._capture_settings_strip.objectName() == "captureSettingsFlatStrip"
    assert window._capture_settings_strip.layout().indexOf(
        window._save_folder_field
    ) < window._capture_settings_strip.layout().indexOf(window._filename_field)
    assert window._capture_bar_toggle_btn.height() == 32
    assert window._capture_bar_toggle_btn.width() == 32
    assert window._capture_bar_restore_btn.size() == window._capture_bar_toggle_btn.size()
    assert window._capture_bar_title.text() == t("shell.capture_bar.title")
    assert not window._capture_bar_title_icon.pixmap().isNull()
    assert window._capture_panel_btn.width() == window._capture_panel_btn.height() == 36
    assert window._capture_panel_btn.text() == ""
    assert window._capture_panel_btn.accessibleName() == t("shell.capture_panel.button")
    assert window._capture_panel_use_hint.text() == t("shell.capture_panel.use_hint")
    assert window._capture_btn.height() == 60
    assert not hasattr(window, "_capture_action_label")
    capture_right = window._capture_btn.mapTo(
        window._capture_bar, window._capture_btn.rect().topRight()
    ).x()
    assert window._capture_mode_selector.geometry().left() - capture_right >= 16
    for mode_button in (
        window._capture_mode_selector.region_button,
        window._capture_mode_selector.fullscreen_button,
    ):
        assert QFontInfo(mode_button.font()).styleName() == "Regular"
        segment_frame = mode_button.parentWidget()
        frame_top = segment_frame.mapToGlobal(segment_frame.rect().topLeft()).y()
        frame_bottom = segment_frame.mapToGlobal(segment_frame.rect().bottomLeft()).y()
        button_top = mode_button.mapToGlobal(mode_button.rect().topLeft()).y()
        button_bottom = mode_button.mapToGlobal(mode_button.rect().bottomLeft()).y()
        assert button_top - frame_top == frame_bottom - button_bottom
    assert window._filename_field.objectName() == "captureFlatField"
    assert window._capture_tags_field.objectName() == "captureFlatField"
    mode_label_y = window._capture_mode_selector.label.mapToGlobal(
        window._capture_mode_selector.label.rect().topLeft()
    ).y()
    mode_control_top = window._capture_mode_selector.region_button.parentWidget().mapToGlobal(
        window._capture_mode_selector.region_button.parentWidget().rect().topLeft()
    ).y()
    mode_control_bottom = window._capture_mode_selector.region_button.parentWidget().mapToGlobal(
        window._capture_mode_selector.region_button.parentWidget().rect().bottomLeft()
    ).y()
    for field in (window._filename_field, window._capture_tags_field):
        assert field.label.mapToGlobal(field.label.rect().topLeft()).y() == mode_label_y
        assert field._control.mapToGlobal(field._control.rect().topLeft()).y() == mode_control_top
        assert field._control.mapToGlobal(field._control.rect().bottomLeft()).y() == mode_control_bottom
    window.close()


def test_capture_bar_save_folder_chooser_updates_destination(monkeypatch, tmp_path):
    app = _ensure_app()
    saved: list[dict] = []
    destination = tmp_path / "Chosen Folder"
    destination.mkdir()
    monkeypatch.setattr(
        "app.ui.main_window.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(destination),
    )
    monkeypatch.setattr(
        "app.ui.main_window.save_config", lambda config: saved.append(dict(config))
    )
    window = _make_window(capture_bar_visible=True)

    window._choose_capture_save_folder()
    app.processEvents()

    assert window._config["save_folder"] == destination.name
    assert Path(window._config["screenshot_dir"]) == destination.parent
    assert window._save_folder_btn.text() == destination.name
    assert window._save_folder_btn.toolTip() == str(destination)
    assert saved[-1]["save_folder"] == destination.name
    window.close()


def test_navigation_uses_hover_labels_and_collapsed_resting_rail():
    app = _ensure_app()
    window = _make_window(
        capture_bar_visible=True,
        window_width=NAV_RESPONSIVE_BREAKPOINT + 100,
    )
    window.show()
    app.processEvents()

    images_button = window._side_nav._nav_buttons[1]
    assert window._side_nav.width() == window._side_nav.COLLAPSED_WIDTH
    assert images_button.text() == ""

    window._side_nav._animate_to(True)
    window._side_nav._anim.setCurrentTime(window._side_nav.ANIM_MS)
    assert window._side_nav.width() == window._side_nav.EXPANDED_WIDTH
    assert images_button.text() == t("nav.images")

    window._side_nav._animate_to(False)
    window._side_nav._anim.setCurrentTime(window._side_nav.ANIM_MS)
    assert window._side_nav.width() == window._side_nav.COLLAPSED_WIDTH
    assert images_button.text() == ""

    window.resize(720, 600)
    app.processEvents()
    assert window._side_nav.width() == window._side_nav.COLLAPSED_WIDTH
    assert images_button.text() == ""
    assert images_button.toolTip() == t("nav.images")
    window.close()


def test_images_primary_workspace_controls_survive_minimum_width():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True, window_width=720)
    window._show_page(1)
    window.show()
    app.processEvents()

    page = window._images_page
    search_rect = page._search_row.geometry()
    assert page._folder_selector.isVisible()
    assert page._search_row.isVisible()
    assert abs(page._command_surface.width() - page._list_panel.width()) <= 1
    assert page._command_surface.parentWidget() is page._left_workspace
    assert page._list_panel.parentWidget() is page._left_workspace
    assert search_rect.right() <= page._command_primary_row.width()


def test_capture_card_aligns_with_images_workspace_and_has_bottom_air():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True, window_width=1600)
    window._show_page(1)
    window.show()
    QTest.qWait(window._side_nav.ANIM_MS + 40)
    window._sync_capture_bar_geometry()
    app.processEvents()

    workspace = window._images_page._left_workspace
    bar_left = window._capture_bar.mapToGlobal(
        window._capture_bar.rect().topLeft()
    ).x()
    bar_right = window._capture_bar.mapToGlobal(
        window._capture_bar.rect().topRight()
    ).x()
    workspace_left = workspace.mapToGlobal(workspace.rect().topLeft()).x()
    workspace_right = workspace.mapToGlobal(workspace.rect().topRight()).x()
    assert abs(bar_left - workspace_left) <= 1
    assert abs(bar_right - workspace_right) <= 1
    assert window._capture_bar_host.layout().contentsMargins().bottom() == 10
    window.close()


def test_images_header_matches_standard_pages_without_symbol():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True, window_width=1200)
    window._show_page(1)
    window.show()
    app.processEvents()

    page = window._images_page
    header = page.findChild(QWidget, "pageHeader")
    assert header is not None
    assert header.property("emphasis") == "standard"
    assert header.findChild(QFrame, "pageHeaderSymbol") is None
    assert header.layout().contentsMargins().left() == PAGE_HEADER_MARGINS[0]
    window.close()
    assert page._list_panel.width() >= page._list_panel.minimumWidth()
    assert page._right_panel.width() >= page._right_panel.minimumWidth()
    window.close()


def test_mode_selector_routes_existing_capture_actions_and_persists(monkeypatch):
    app = _ensure_app()
    saved: list[dict] = []
    monkeypatch.setattr(
        "app.ui.main_window.save_config", lambda config: saved.append(dict(config))
    )
    window = _make_window(capture_bar_visible=True, window_width=720)
    window.show()
    app.processEvents()

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_capture_region",
        lambda *, from_panel=False: calls.append((CAPTURE_REGION, from_panel)),
    )
    monkeypatch.setattr(
        window,
        "_capture_fullscreen",
        lambda *, from_panel=False: calls.append((CAPTURE_FULLSCREEN, from_panel)),
    )

    selector = window._capture_mode_selector
    assert selector.mode() == CAPTURE_REGION
    assert selector.region_button.isChecked()
    assert window._capture_btn.text() == "Region\nCapture"
    assert window._capture_btn.objectName() == "regionCaptureButton"

    selector.fullscreen_button.click()
    app.processEvents()
    assert calls == []
    assert window._capture_mode == CAPTURE_FULLSCREEN
    assert window._config["capture_mode"] == CAPTURE_FULLSCREEN
    assert selector.mode() == CAPTURE_FULLSCREEN
    assert saved[-1]["capture_mode"] == CAPTURE_FULLSCREEN
    assert window._capture_btn.text() == "Full Screen\nCapture"
    assert window._capture_btn.objectName() == "fullScreenCaptureButton"
    assert QFontMetrics(window._capture_btn.font()).horizontalAdvance(
        "Full Screen"
    ) <= window._capture_btn.width() - 12

    window._capture_btn.click()
    app.processEvents()
    assert calls == [(CAPTURE_FULLSCREEN, False)]

    selector.region_button.click()
    window._capture_btn.click()
    app.processEvents()
    assert window._capture_mode == CAPTURE_REGION
    assert selector.mode() == CAPTURE_REGION
    assert calls[-1] == (CAPTURE_REGION, False)

    window._set_capture_bar_visible(False, persist=False)
    window._set_capture_bar_visible(True, persist=False)
    app.processEvents()
    assert selector.mode() == CAPTURE_REGION

    window._set_capture_mode(CAPTURE_FULLSCREEN)
    persisted_mode = saved[-1]["capture_mode"]
    window.close()

    restarted = _make_window(
        capture_bar_visible=True,
        window_width=720,
        capture_mode=persisted_mode,
    )
    restarted.show()
    app.processEvents()
    assert restarted._capture_mode == CAPTURE_FULLSCREEN
    assert restarted._capture_mode_selector.mode() == CAPTURE_FULLSCREEN
    restarted.close()


def test_capture_panel_mode_control_stays_connected_to_shell_mode(monkeypatch):
    app = _ensure_app()
    monkeypatch.setattr("app.ui.main_window.save_config", lambda config: None)
    window = _make_window(capture_bar_visible=True)
    window.show()
    app.processEvents()

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window,
        "_capture_fullscreen",
        lambda *, from_panel=False: calls.append((CAPTURE_FULLSCREEN, from_panel)),
    )
    panel = window._ensure_capture_panel()
    assert not hasattr(panel, "_folder_combo")
    assert len(panel._settings_fields) == 2
    panel.mode_cycle_clicked.emit()
    app.processEvents()
    assert window._capture_mode == CAPTURE_FULLSCREEN
    assert window._capture_mode_selector.mode() == CAPTURE_FULLSCREEN

    panel.capture_clicked.emit()
    app.processEvents()
    assert calls == [(CAPTURE_FULLSCREEN, True)]
    window.close()


def test_primary_capture_action_stays_visible_near_minimum_window_width():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True, window_width=720)
    window.show()
    app.processEvents()
    capture_rect = window._capture_action_field.geometry()
    mode_rect = window._capture_mode_selector.geometry()
    assert capture_rect.left() >= 0
    assert capture_rect.right() < window._capture_bar.width()
    assert mode_rect.left() > capture_rect.right()
    assert mode_rect.right() < window._capture_bar.width()
    assert window._capture_settings_scroll.width() > 0
    capture_center = window._capture_btn.mapTo(
        window._capture_bar, window._capture_btn.rect().center()
    )
    assert window._capture_bar.childAt(capture_center) is window._capture_btn
    assert window._capture_btn.text() == "Region\nCapture"
    assert window._capture_btn.accessibleName() == t("shell.capture.action")
    assert window._capture_btn.width() == 88
    assert window._capture_btn.height() == 60
    assert window._capture_btn.iconSize() == QSize(20, 20)
    assert window._capture_btn.objectName() in {
        "regionCaptureButton",
        "fullScreenCaptureButton",
    }
    capture_styles = token_style_sheet()
    assert "QToolButton#regionCaptureButton" in capture_styles
    assert f"background-color: {COLORS.primary_soft}" in capture_styles
    assert f"color: {COLORS.primary}" in capture_styles
    assert "border: 1px solid #93c5fd" in capture_styles
    assert 'QPushButton#captureModeSegment[captureMode="fullscreen"]:checked' in capture_styles
    assert "color: #ffffff" not in capture_styles.split(
        'QPushButton#captureModeSegment[captureMode="fullscreen"]:checked', 1
    )[1].split("}", 1)[0]
    window.close()


def test_capture_action_remains_single_and_layout_managed_after_hide_show_resize():
    app = _ensure_app()
    window = _make_window(capture_bar_visible=True, window_width=1000)
    window.show()
    app.processEvents()

    capture = window._capture_btn
    assert window._capture_bar_layout.indexOf(window._capture_action_field) >= 0
    assert window._capture_bar.findChildren(type(capture)).count(capture) == 1

    for width in (720, 900, 720):
        window.resize(width, 600)
        app.processEvents()
        rect = window._capture_action_field.geometry()
        mode_rect = window._capture_mode_selector.geometry()
        assert capture.isVisible()
        assert rect.left() >= 0
        assert rect.right() < window._capture_bar.width()
        assert window._capture_mode_selector.isVisible()
        assert mode_rect.left() > rect.right()
        assert mode_rect.right() < window._capture_bar.width()
        capture_center = capture.mapTo(window._capture_bar, capture.rect().center())
        assert window._capture_bar.childAt(capture_center) is capture

    window._set_capture_bar_visible(False, persist=False)
    assert window._capture_bar_animation is not None
    QTest.qWait(320)
    assert window._capture_bar.isHidden()
    window._set_capture_bar_visible(True, persist=False)
    QTest.qWait(270)
    window.resize(720, 600)
    app.processEvents()

    rect = window._capture_action_field.geometry()
    assert window._capture_btn is capture
    assert capture.isVisible()
    assert rect.right() < window._capture_bar.width()
    assert window._capture_bar_layout.indexOf(window._capture_action_field) >= 0
    window.close()
