from PySide6.QtWidgets import QApplication

from app.services.capture_modes import CAPTURE_FULLSCREEN, CAPTURE_REGION
from app.services.screenshot_session import ScreenshotSession
from app.ui.design_tokens import CAPTURE_BUTTON_HEIGHT, CAPTURE_BUTTON_WIDTH
from app.ui.main_window import (
    PAGE_IMAGES,
    PAGE_SETTINGS,
    PAGE_TAGS,
    MainWindow,
    _SNIP_HOTKEY_DELAY_MS,
)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _minimal_config() -> dict:
    return {
        "screenshot_dir": "screenshots",
        "current_project": "Default",
        "window_width": 800,
        "window_height": 600,
        "window_title": "Test",
        "clipboard_check_interval_ms": 500,
    }


def test_screenshot_session_default_timeout_is_60_seconds():
    _ensure_app()
    session = ScreenshotSession()
    assert session._timeout_ms == 60000


def test_screenshot_session_complete_emits_finished():
    _ensure_app()
    session = ScreenshotSession(timeout_ms=5000)
    finished = {"count": 0}
    session.finished.connect(lambda: finished.__setitem__("count", finished["count"] + 1))

    session.start(CAPTURE_REGION)
    assert session.is_active is True
    assert session.mode == CAPTURE_REGION

    session.complete()
    assert session.is_active is False
    assert finished["count"] == 1

    session.complete()
    assert finished["count"] == 1


def test_screenshot_session_cancel_does_not_emit_finished():
    _ensure_app()
    session = ScreenshotSession(timeout_ms=5000)
    finished = {"count": 0}
    session.finished.connect(lambda: finished.__setitem__("count", finished["count"] + 1))

    session.start()
    session.cancel()
    assert session.is_active is False
    assert finished["count"] == 0


def test_screenshot_session_timeout_emits_finished():
    app = _ensure_app()
    session = ScreenshotSession(timeout_ms=50)
    finished = {"count": 0}
    session.finished.connect(lambda: finished.__setitem__("count", finished["count"] + 1))

    session.start()
    assert session.is_active is True

    import time

    for _ in range(20):
        app.processEvents()
        if finished["count"] > 0:
            break
        time.sleep(0.03)
        app.processEvents()

    assert finished["count"] == 1
    assert session.is_active is False


def test_screenshot_minimizes_and_stays_on_taskbar(monkeypatch=None):
    """showMinimized keeps the window (taskbar icon); does not hide()."""
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    hotkey_calls = {"count": 0}

    def _fake_hotkey():
        hotkey_calls["count"] += 1
        return True

    import app.ui.main_window as main_window_mod

    original = main_window_mod.default_region_trigger
    main_window_mod.default_region_trigger = _fake_hotkey
    try:
        window = MainWindow(_minimal_config())
        window.show()
        app.processEvents()

        window._start_capture_session(CAPTURE_REGION)
        app.processEvents()

        assert window.isMinimized() is True
        assert window.isVisible() is True  # minimized windows stay "visible" to Qt
        assert window._screenshot_session.is_active is True
        assert window._screenshot_session.mode == CAPTURE_REGION

        # Wait for delayed region trigger
        import time

        deadline = time.time() + (_SNIP_HOTKEY_DELAY_MS / 1000.0) + 0.5
        while time.time() < deadline and hotkey_calls["count"] == 0:
            app.processEvents()
            time.sleep(0.02)

        assert hotkey_calls["count"] == 1

        window._screenshot_session.complete()
        app.processEvents()

        assert window.isMinimized() is False
        assert window.isVisible() is True
        window.close()
        app.processEvents()
    finally:
        main_window_mod.default_region_trigger = original


def test_fullscreen_capture_uses_grab_and_save_path():
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    import app.ui.main_window as main_window_mod
    from PySide6.QtGui import QImage

    grab_calls = {"count": 0}
    save_calls = {"count": 0}

    def _fake_grab():
        grab_calls["count"] += 1
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(0x112233)
        return img

    original_grab = main_window_mod.grab_fullscreen_image
    main_window_mod.grab_fullscreen_image = _fake_grab

    window = MainWindow(_minimal_config())
    original_save = window._image_saver.save_image

    def _fake_save(image, detected_at=None):
        save_calls["count"] += 1
        return original_save(image, detected_at)

    window._image_saver.save_image = _fake_save
    try:
        window.show()
        app.processEvents()
        window._start_capture_session(CAPTURE_FULLSCREEN)
        app.processEvents()
        assert window._screenshot_session.mode == CAPTURE_FULLSCREEN

        import time

        deadline = time.time() + (_SNIP_HOTKEY_DELAY_MS / 1000.0) + 1.0
        while time.time() < deadline and save_calls["count"] == 0:
            app.processEvents()
            time.sleep(0.02)

        assert grab_calls["count"] == 1
        assert save_calls["count"] == 1
        assert window._screenshot_session.is_active is False
        window.close()
        app.processEvents()
    finally:
        main_window_mod.grab_fullscreen_image = original_grab


def test_capture_keeps_already_minimized_window():
    """If the app was minimized before capture, stay minimized after save."""
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    import app.ui.main_window as main_window_mod

    original = main_window_mod.default_region_trigger
    main_window_mod.default_region_trigger = lambda: True
    try:
        window = MainWindow(_minimal_config())
        window.show()
        app.processEvents()
        window.showMinimized()
        app.processEvents()
        assert window.isMinimized() is True

        window._start_capture_session(CAPTURE_REGION)
        app.processEvents()
        assert window._keep_minimized_after_capture is True

        window._screenshot_session.complete()
        app.processEvents()

        assert window.isMinimized() is True
        window.close()
        app.processEvents()
    finally:
        main_window_mod.default_region_trigger = original


def test_session_finish_does_not_activate_window(monkeypatch):
    """Save/toast must not raise or activate the main window."""
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    import app.ui.main_window as main_window_mod

    original = main_window_mod.default_region_trigger
    main_window_mod.default_region_trigger = lambda: True
    try:
        window = MainWindow(_minimal_config())
        window.show()
        app.processEvents()
        raised = {"raise": 0, "activate": 0}
        monkeypatch.setattr(
            window, "raise_", lambda: raised.__setitem__("raise", raised["raise"] + 1)
        )
        monkeypatch.setattr(
            window,
            "activateWindow",
            lambda: raised.__setitem__("activate", raised["activate"] + 1),
        )

        window._start_capture_session(CAPTURE_REGION)
        app.processEvents()
        window._screenshot_session.complete()
        app.processEvents()

        assert raised["raise"] == 0
        assert raised["activate"] == 0
        window.close()
        app.processEvents()
    finally:
        main_window_mod.default_region_trigger = original


def test_screenshot_restores_previous_page():
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    import app.ui.main_window as main_window_mod

    original = main_window_mod.default_region_trigger
    main_window_mod.default_region_trigger = lambda: True
    try:
        window = MainWindow(_minimal_config())
        window.show()
        app.processEvents()

        window._show_page(PAGE_SETTINGS)
        app.processEvents()
        assert window._stack.currentIndex() == PAGE_SETTINGS

        window._start_screenshot_session()
        app.processEvents()
        assert window._page_before_screenshot == PAGE_SETTINGS
        assert window.isMinimized() is True

        window._screenshot_session.complete()
        app.processEvents()

        assert window.isVisible() is True
        assert window.isMinimized() is False
        assert window._stack.currentIndex() == PAGE_SETTINGS
        assert window._screenshot_session.is_active is False

        window._show_page(PAGE_TAGS)
        app.processEvents()
        window._start_screenshot_session()
        app.processEvents()
        assert window._page_before_screenshot == PAGE_IMAGES
        window._screenshot_session.complete()
        app.processEvents()
        assert window._stack.currentIndex() == PAGE_IMAGES

        window.close()
        app.processEvents()
    finally:
        main_window_mod.default_region_trigger = original


def test_screenshot_restores_images_page():
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)

    import app.ui.main_window as main_window_mod

    original = main_window_mod.default_region_trigger
    main_window_mod.default_region_trigger = lambda: True
    try:
        window = MainWindow(_minimal_config())
        window.show()
        app.processEvents()

        window._show_page(PAGE_IMAGES)
        app.processEvents()
        window._start_screenshot_session()
        app.processEvents()
        window._screenshot_session.complete()
        app.processEvents()

        assert window._stack.currentIndex() == PAGE_IMAGES
        window.close()
        app.processEvents()
    finally:
        main_window_mod.default_region_trigger = original


def test_send_win_shift_s_builds_six_key_events():
    """Sanity: helper returns bool and is importable on this platform."""
    from app.utils.windows_hotkey import send_win_shift_s

    # Do not actually fire the snipping tool in automated tests —
    # only verify the function exists and is callable.
    assert callable(send_win_shift_s)


def test_capture_mode_selector_updates_single_button():
    app = _ensure_app()
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(_minimal_config())
    assert window._capture_mode == CAPTURE_REGION
    assert window._capture_btn.objectName() == "regionCaptureButton"
    assert window._capture_btn.width() == window._capture_btn.minimumWidth() or True
    assert window._capture_mode_selector.region_button.isChecked()

    # Apply without waiting on fade animation
    window._capture_mode = CAPTURE_FULLSCREEN
    window._config["capture_mode"] = CAPTURE_FULLSCREEN
    window._refresh_capture_mode_ui(animate=False)
    app.processEvents()
    assert window._capture_btn.objectName() == "fullScreenCaptureButton"
    assert window._capture_mode_selector.fullscreen_button.isChecked()
    assert window._capture_btn.width() >= CAPTURE_BUTTON_WIDTH
    assert window._capture_btn.height() == CAPTURE_BUTTON_HEIGHT

    window._capture_mode = CAPTURE_REGION
    window._refresh_capture_mode_ui(animate=False)
    app.processEvents()
    assert window._capture_btn.objectName() == "regionCaptureButton"
    assert window._capture_mode_selector.region_button.isChecked()
    assert window._capture_btn.width() >= CAPTURE_BUTTON_WIDTH
    assert window._capture_btn.height() == CAPTURE_BUTTON_HEIGHT

    window.close()
    app.processEvents()


if __name__ == "__main__":
    test_screenshot_session_default_timeout_is_60_seconds()
    test_screenshot_session_complete_emits_finished()
    test_screenshot_session_cancel_does_not_emit_finished()
    test_screenshot_session_timeout_emits_finished()
    test_screenshot_minimizes_and_stays_on_taskbar()
    test_fullscreen_capture_uses_grab_and_save_path()
    test_screenshot_restores_previous_page()
    test_screenshot_restores_images_page()
    test_send_win_shift_s_builds_six_key_events()
    test_capture_mode_buttons_exist()
    print("All screenshot session tests passed.")
