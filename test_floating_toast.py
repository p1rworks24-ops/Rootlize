"""App-owned floating toast — save success / failure notifications."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QPointF
from PySide6.QtGui import QEnterEvent, QImage
from PySide6.QtWidgets import QApplication

from app.i18n import t
from app.models.detected_image import DetectedImage
from app.services.image_saver import ImageSaver
from app.services.metadata_service import MetadataService
from app.ui.floating_toast import FloatingToastHost, ToastKind
from app.ui.pages.settings_page import SettingsPage


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_toast_host_replaces_instead_of_stacking():
    app = _ensure_app()
    host = FloatingToastHost()
    host.show_success(
        filename="a.png", folder="Capture", duration_ms=5000
    )
    app.processEvents()
    assert host._toast.isVisible()

    host.show_success(
        filename="b.png", folder="Other", duration_ms=5000
    )
    app.processEvents()
    assert host._toast.isVisible()
    lines = [
        host._toast._lines_layout.itemAt(i).widget().text()
        for i in range(host._toast._lines_layout.count())
    ]
    assert "b.png" in lines
    assert any("Other" in line for line in lines)
    assert not any("Project" in line for line in lines)
    host.shutdown()


def test_toast_error_payload_uses_red_kind():
    _ensure_app()
    host = FloatingToastHost()
    host.show_error(message="Access denied.", duration_ms=3000)
    assert host._toast._card.property("kind") == ToastKind.ERROR.value
    assert host._toast._title_label.text() == t("toast.save_failed_title")
    host.shutdown()


def test_toast_show_result_uses_custom_copy():
    app = _ensure_app()
    host = FloatingToastHost()
    host.show_result(title="Workflow Complete", body="Tagged 1 image.", ok=True)
    app.processEvents()
    assert host._toast.isVisible()
    assert host._toast._card.property("kind") == ToastKind.SUCCESS.value
    assert host._toast._title_label.text() == "Workflow Complete"
    lines = [
        host._toast._lines_layout.itemAt(i).widget().text()
        for i in range(host._toast._lines_layout.count())
    ]
    assert "Tagged 1 image." in lines
    host.shutdown()


def test_toast_hover_pauses_auto_timer():
    app = _ensure_app()
    host = FloatingToastHost()
    host.show_success(
        filename="x.png", folder="Capture", duration_ms=3000
    )
    app.processEvents()
    toast = host._toast
    assert toast._auto_timer.isActive()
    enter = QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))
    toast.enterEvent(enter)
    assert toast._paused is True
    assert toast._auto_timer.isActive() is False
    remaining = toast._remaining_ms
    toast.leaveEvent(enter)
    assert toast._paused is False
    assert toast._auto_timer.isActive()
    assert toast._auto_timer.remainingTime() <= remaining + 50
    host.shutdown()


def test_toast_close_button_dismisses():
    app = _ensure_app()
    host = FloatingToastHost()
    host.show_success(
        filename="x.png", folder="Capture", duration_ms=8000
    )
    app.processEvents()
    host._toast.dismiss_now()
    for _ in range(40):
        app.processEvents()
        if not host._toast.isVisible():
            break
    assert host._toast.isVisible() is False
    host.shutdown()


def test_settings_has_notifications_section():
    app = _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots").mkdir()
        config = {
            "screenshot_dir": "screenshots",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "current_folder": "Capture",
            "save_folder": "Capture",
            "show_save_notification": True,
            "notification_duration_sec": 3,
            "shortcuts": {
                "region_capture": "Ctrl+Shift+R",
                "fullscreen_capture": "Ctrl+Shift+F",
            },
        }
        page = SettingsPage(config, root)
        page.show()
        app.processEvents()
        assert page._notify_toggle.current() == 0  # On
        assert page._notify_duration.currentData() == 3

        page._notify_toggle.set_current(1)  # Off
        app.processEvents()
        assert config["show_save_notification"] is False

        page._notify_duration.setCurrentIndex(page._notify_duration.findData(5))
        app.processEvents()
        assert config["notification_duration_sec"] == 5


def test_image_saver_sets_last_error_on_permission_failure():
    _ensure_app()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "save_folder": "Capture",
            "filename_template": "{date}_{time}",
        }
        saver = ImageSaver(config, MetadataService(), root)
        img = QImage(4, 4, QImage.Format_RGB32)
        img.fill(0x112233)

        def _fail_save(*_args, **_kwargs):
            raise PermissionError("denied")

        img.save = _fail_save  # type: ignore[method-assign]
        result = saver.save_image(img)
        assert result is None
        assert saver.last_error == "Access denied."


def test_main_window_shows_toast_after_save(monkeypatch):
    app = _ensure_app()
    monkeypatch.setattr("app.ui.main_window.CAPTURE_ENABLED", True)
    from app.ui.main_window import MainWindow

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "capture_mode": "region",
            "capture_minimize": False,
            "show_save_notification": True,
            "notification_duration_sec": 3,
            "shortcuts": {
                "region_capture": "Ctrl+Shift+R",
                "fullscreen_capture": "Ctrl+Shift+F",
            },
        }
        window = MainWindow(config)
        window._app_root = root
        shown: dict = {}

        def _fake_success(**kwargs):
            shown.update(kwargs)

        window._toast_host.show_success = _fake_success  # type: ignore[method-assign]
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(0xABCDEF)
        detected = DetectedImage(
            image=img, width=8, height=8, detected_at=datetime.now()
        )
        window._on_image_detected(detected)
        app.processEvents()
        assert "filename" in shown
        assert shown["folder"] == "Capture"

        # Toast folder follows the actual written path, not a stale/default
        # config value.
        shown.clear()
        window._config["save_folder"] = "Default"
        window._show_save_success_toast(
            root / "screenshots" / "Configured Folder" / "saved.png"
        )
        assert shown["folder"] == "Configured Folder"
        window.close()
        app.processEvents()


def test_capture_disabled_skips_clipboard_and_screenshot_toast(monkeypatch):
    app = _ensure_app()
    from unittest.mock import MagicMock

    from app.ui.main_window import CAPTURE_ENABLED, MainWindow

    assert CAPTURE_ENABLED is False
    suppressor = MagicMock()
    monkeypatch.setattr("app.ui.main_window.snipping_toast_suppressor", suppressor)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "screenshots" / "Capture").mkdir(parents=True)
        config = {
            "screenshot_dir": str(root / "screenshots"),
            "current_folder": "Capture",
            "save_folder": "Capture",
            "window_width": 1050,
            "window_height": 600,
            "filename_template": "{date}_{time}",
            "capture_mode": "region",
            "capture_minimize": False,
            "show_save_notification": True,
            "notification_duration_sec": 3,
            "shortcuts": {
                "region_capture": "Ctrl+Shift+R",
                "fullscreen_capture": "Ctrl+Shift+F",
            },
        }
        window = MainWindow(config)
        window._app_root = root
        suppressor.enter.assert_not_called()
        assert window._clipboard_watcher is None
        shown: dict = {}

        def _fake_success(**kwargs):
            shown.update(kwargs)

        window._toast_host.show_success = _fake_success  # type: ignore[method-assign]
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(0xABCDEF)
        detected = DetectedImage(
            image=img, width=8, height=8, detected_at=datetime.now()
        )
        window._on_image_detected(detected)
        app.processEvents()
        assert shown == {}
        window._show_save_success_toast(root / "screenshots" / "Capture" / "saved.png")
        assert shown == {}
        window.close()
        app.processEvents()
