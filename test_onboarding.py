"""First-run onboarding and Images empty-state behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from app.config import load_config, reset_migration_flag_for_tests, save_config
from app.paths import get_config_path, set_path_overrides
from app.ui.welcome_dialog import WelcomeDialog
from app.ui.main_window import MainWindow, PAGE_IMAGES


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_fresh_user_starts_with_onboarding_pending(tmp_path) -> None:
    legacy = tmp_path / "NoLegacyInstall"
    legacy.mkdir()
    set_path_overrides(legacy_install_root=legacy)
    config = load_config()
    assert config["onboarding_completed"] is False


def test_existing_config_without_onboarding_key_is_not_interrupted() -> None:
    config = load_config()
    config.pop("onboarding_completed", None)
    save_config(config)
    reset_migration_flag_for_tests()

    loaded = load_config()

    assert loaded["onboarding_completed"] is True
    persisted = json.loads(get_config_path().read_text(encoding="utf-8"))
    assert persisted["onboarding_completed"] is True


def test_welcome_dialog_explains_three_steps_and_primary_action() -> None:
    _app()
    dialog = WelcomeDialog()

    assert dialog.windowTitle() == "Welcome to Capixe"
    step_numbers = {
        label.text()
        for label in dialog.findChildren(QLabel, "welcomeStepNumber")
    }
    assert step_numbers == {"1", "2", "3"}
    buttons = {
        button.text(): button for button in dialog.findChildren(QPushButton)
    }
    assert "Go to Images" in buttons
    assert "Maybe later" in buttons

    buttons["Go to Images"].click()

    assert dialog.go_to_images is True
    assert dialog.result() == QDialog.Accepted


def test_completing_welcome_persists_and_navigates_to_images(monkeypatch) -> None:
    class _FinishedSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

        def emit(self, result=0) -> None:
            assert self.callback is not None
            self.callback(result)

    class _AcceptedWelcome:
        go_to_images = True

        def __init__(self, _parent) -> None:
            self.finished = _FinishedSignal()
            self.opened = False

        def isVisible(self) -> bool:
            return self.opened

        def open(self) -> None:
            self.opened = True

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:
            pass

    saved = []
    pages = []
    monkeypatch.setattr("app.ui.main_window.WelcomeDialog", _AcceptedWelcome)
    monkeypatch.setattr(
        "app.ui.main_window.save_config", lambda config: saved.append(config.copy())
    )
    window = SimpleNamespace(
        _config={"onboarding_completed": False},
        _show_page=pages.append,
    )
    window._complete_welcome = lambda dialog: MainWindow._complete_welcome(
        window, dialog
    )

    MainWindow.show_welcome_if_needed(window)

    assert window._config["onboarding_completed"] is False
    assert window._welcome_dialog.opened is True
    window._welcome_dialog.finished.emit()

    assert window._config["onboarding_completed"] is True
    assert saved[-1]["onboarding_completed"] is True
    assert pages == [PAGE_IMAGES]


def test_source_launch_shows_welcome_even_after_completion(monkeypatch) -> None:
    class _Signal:
        def connect(self, _callback) -> None:
            pass

    class _Welcome:
        def __init__(self, _parent) -> None:
            self.finished = _Signal()

        def isVisible(self) -> bool:
            return False

        def open(self) -> None:
            opened.append(self)

        def raise_(self) -> None:
            pass

        def activateWindow(self) -> None:
            pass

    monkeypatch.setattr("app.ui.main_window.is_frozen", lambda: False)
    opened = []
    monkeypatch.setattr("app.ui.main_window.WelcomeDialog", _Welcome)
    window = SimpleNamespace(_config={"onboarding_completed": True})
    window._complete_welcome = lambda dialog: None

    MainWindow.show_welcome_if_needed(window)

    assert len(opened) == 1


def test_packaged_launch_skips_completed_welcome(monkeypatch) -> None:
    monkeypatch.setattr("app.ui.main_window.is_frozen", lambda: True)
    window = SimpleNamespace(_config={"onboarding_completed": True})

    MainWindow.show_welcome_if_needed(window)

    assert not hasattr(window, "_welcome_dialog")
