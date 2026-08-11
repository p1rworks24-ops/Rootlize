"""User-data path separation: APPDATA config + Pictures screenshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt

import app.config as config_mod
from app.config import (
    build_default_config,
    load_config,
    normalize_screenshot_dir,
    reset_migration_flag_for_tests,
    save_config,
)
from app.paths import (
    clear_path_overrides,
    folder_has_screenshot_data,
    get_config_path,
    get_default_screenshot_root,
    get_legacy_config_path,
    set_path_overrides,
)


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path: Path):
    """Keep every test out of the real APPDATA / Pictures trees."""
    app_data = tmp_path / "AppDataRoaming" / "Capixe"
    local_data = tmp_path / "AppDataLocal" / "Capixe"
    pictures = tmp_path / "Pictures" / "Capixe"
    legacy = tmp_path / "LegacyInstall"
    legacy.mkdir(parents=True)
    set_path_overrides(
        app_data_dir=app_data,
        local_app_data_dir=local_data,
        default_screenshot_root=pictures,
        legacy_install_root=legacy,
        resource_root=legacy,
    )
    reset_migration_flag_for_tests()
    yield
    clear_path_overrides()
    reset_migration_flag_for_tests()


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.red)
    assert image.save(str(path), "PNG")


def test_new_user_creates_appdata_config_and_pictures_root(tmp_path: Path):
    cfg = load_config()
    assert get_config_path().is_file()
    assert get_config_path().parent.name == "Capixe"
    assert Path(cfg["screenshot_dir"]) == get_default_screenshot_root()
    assert (get_default_screenshot_root() / "Capture").is_dir()
    # Must not create screenshots next to legacy install for brand-new users
    assert not (tmp_path / "LegacyInstall" / "screenshots").exists() or not list(
        (tmp_path / "LegacyInstall" / "screenshots").rglob("*.png")
    )


def test_absolute_root_folder_preserved(tmp_path: Path):
    custom = tmp_path / "MyShots"
    custom.mkdir()
    cfg = build_default_config()
    cfg["screenshot_dir"] = str(custom)
    save_config(cfg)
    reset_migration_flag_for_tests()
    loaded = load_config()
    assert Path(loaded["screenshot_dir"]).resolve() == custom.resolve()


def test_legacy_config_migrated_but_not_deleted(tmp_path: Path):
    legacy_cfg = get_legacy_config_path()
    custom = tmp_path / "ExistingRoot"
    custom.mkdir()
    payload = {
        "screenshot_dir": str(custom),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "window_width": 1050,
        "window_height": 600,
    }
    legacy_cfg.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_config()
    assert get_config_path().is_file()
    assert legacy_cfg.is_file()  # never deleted
    assert Path(loaded["screenshot_dir"]).resolve() == custom.resolve()
    assert Path(loaded["selected_folder"]).resolve() == custom.resolve()
    assert loaded["window_width"] == 1600
    assert loaded["window_height"] == 900


def test_custom_window_size_is_not_replaced_by_default_migration(tmp_path: Path):
    custom = tmp_path / "CustomSizeRoot"
    custom.mkdir()
    save_config(
        {
            **build_default_config(),
            "screenshot_dir": str(custom),
            "window_width": 1280,
            "window_height": 720,
        }
    )
    reset_migration_flag_for_tests()
    loaded = load_config()
    assert loaded["window_width"] == 1280
    assert loaded["window_height"] == 720


def test_old_version_window_size_resets_once_to_1600_by_900(tmp_path: Path):
    custom = tmp_path / "VersionTwoRoot"
    custom.mkdir()
    config = build_default_config()
    config.update(
        {
            "screenshot_dir": str(custom),
            "window_width": 1720,
            "window_height": 980,
            "window_size_default_version": 2,
        }
    )
    save_config(config)
    reset_migration_flag_for_tests()

    loaded = load_config()
    assert loaded["window_width"] == 1600
    assert loaded["window_height"] == 900
    assert loaded["window_size_default_version"] == 7

    config = loaded.copy()
    config.update(
        {
            "window_width": 1000,
            "window_height": 700,
            "window_size_default_version": 4,
        }
    )
    save_config(config)
    loaded = load_config()
    assert loaded["window_width"] == 1600
    assert loaded["window_height"] == 900
    assert loaded["window_size_default_version"] == 7


def test_new_user_starts_without_selected_folder():
    loaded = load_config()
    assert loaded["selected_folder"] == ""


def test_new_config_preferred_over_legacy(tmp_path: Path):
    new_root = tmp_path / "FromNew"
    new_root.mkdir()
    legacy_root = tmp_path / "FromLegacy"
    legacy_root.mkdir()

    save_config(
        {
            **build_default_config(),
            "screenshot_dir": str(new_root),
        }
    )
    get_legacy_config_path().write_text(
        json.dumps({"screenshot_dir": str(legacy_root)}),
        encoding="utf-8",
    )
    loaded = load_config()
    assert Path(loaded["screenshot_dir"]).resolve() == new_root.resolve()


def test_relative_screenshots_with_images_keeps_legacy_absolute(tmp_path: Path):
    shots = tmp_path / "LegacyInstall" / "screenshots" / "Capture"
    _write_png(shots / "keep.png")
    assert folder_has_screenshot_data(tmp_path / "LegacyInstall" / "screenshots")

    cfg = {"screenshot_dir": "screenshots", "save_folder": "Capture"}
    changed = normalize_screenshot_dir(cfg)
    assert changed
    assert Path(cfg["screenshot_dir"]).resolve() == (
        tmp_path / "LegacyInstall" / "screenshots"
    ).resolve()
    assert (shots / "keep.png").is_file()  # not moved


def test_relative_screenshots_empty_switches_to_pictures(tmp_path: Path):
    cfg = {"screenshot_dir": "screenshots"}
    normalize_screenshot_dir(cfg)
    assert Path(cfg["screenshot_dir"]).resolve() == get_default_screenshot_root()


def test_corrupt_legacy_config_falls_back_to_defaults(tmp_path: Path):
    get_legacy_config_path().write_text("{not-json", encoding="utf-8")
    loaded = load_config()
    assert Path(loaded["screenshot_dir"]).resolve() == get_default_screenshot_root()
    assert get_legacy_config_path().is_file()  # untouched


def test_paths_with_spaces_and_unicode(tmp_path: Path):
    custom = tmp_path / "ユーザー Data" / "My Capixe Root"
    custom.mkdir(parents=True)
    cfg = build_default_config()
    cfg["screenshot_dir"] = str(custom)
    save_config(cfg)
    loaded = load_config()
    assert Path(loaded["screenshot_dir"]).resolve() == custom.resolve()


def test_save_config_creates_parent(tmp_path: Path):
    target = get_config_path()
    assert not target.exists()
    save_config(build_default_config())
    assert target.is_file()


def test_load_config_accepts_utf8_bom() -> None:
    target = get_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_config()
    payload["onboarding_completed"] = False
    target.write_text(json.dumps(payload), encoding="utf-8-sig")

    loaded = load_config()

    assert loaded["onboarding_completed"] is False
