"""Pytest defaults: never write Capixe user data into the real APPDATA/Pictures."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.config import reset_migration_flag_for_tests
from app.paths import clear_path_overrides, set_path_overrides


@pytest.fixture(autouse=True)
def _capixe_isolate_user_dirs(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.mktemp("capixe_user_data")
    set_path_overrides(
        app_data_dir=base / "AppData" / "Capixe",
        local_app_data_dir=base / "LocalAppData" / "Capixe",
        default_screenshot_root=base / "Pictures" / "Capixe",
        # Leave legacy/resource unset so tests that pass their own app_root
        # still control relative screenshot resolution via MainWindow overrides.
    )
    reset_migration_flag_for_tests()
    yield
    clear_path_overrides()
    reset_migration_flag_for_tests()


@pytest.fixture(autouse=True)
def _capixe_cleanup_qt_state():
    """Release Qt clipboard data and top-level widgets created by each test."""
    yield

    app = QApplication.instance()
    if app is None:
        return

    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.clear()

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()

    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
