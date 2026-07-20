"""Load / save Capixe settings under %APPDATA%\\Capixe."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.branding import APP_NAME
from app.paths import (
    ensure_dir,
    folder_has_screenshot_data,
    get_app_data_dir,
    get_config_path,
    get_default_screenshot_root,
    get_legacy_config_path,
    get_legacy_install_root,
    get_legacy_tags_path,
    get_tags_path,
    legacy_screenshots_dir,
)
from app.utils.logger import setup_logger
from app.utils.workspace import DEFAULT_FOLDER

logger = setup_logger()

# Template defaults (screenshot_dir filled at runtime via build_default_config)
DEFAULT_CONFIG: dict = {
    "screenshot_dir": "",  # filled with Pictures\\Capixe for new installs
    "current_folder": DEFAULT_FOLDER,
    "save_folder": DEFAULT_FOLDER,
    "window_width": 1050,
    "window_height": 600,
    "window_title": APP_NAME,
    "clipboard_check_interval_ms": 500,
    "images_folder_tree_expanded": True,
    "filename_template": "{date}_{time}",
    "capture_tags": [],
    "capture_mode": "region",
    "capture_minimize": True,
    "home_stats_mode": "folder",
    "shortcuts": {
        "region_capture": "Ctrl+Shift+R",
        "fullscreen_capture": "Ctrl+Shift+F",
    },
    "show_save_notification": True,
    "notification_duration_sec": 5,
}

# Avoid repeating migration within one process
_migration_attempted = False


def build_default_config() -> dict:
    """Fresh config for a new user (absolute Pictures\\Capixe root)."""
    cfg = {**DEFAULT_CONFIG}
    cfg["screenshot_dir"] = str(get_default_screenshot_root())
    cfg["current_folder"] = DEFAULT_FOLDER
    cfg["save_folder"] = DEFAULT_FOLDER
    cfg["window_title"] = APP_NAME
    return cfg


def _read_json_file(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.error("Config is not a JSON object: %s", path)
        return None
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in %s: %s", path, e)
        return None
    except OSError as e:
        logger.error("Failed to read %s: %s", path, e)
        return None


def _write_json_file(path: Path, data: dict) -> None:
    parent = path.parent
    if not ensure_dir(parent, label="config directory"):
        raise OSError(f"Cannot create config directory: {parent}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("config.json を保存しました: %s", path)


def normalize_screenshot_dir(config: dict) -> bool:
    """
    Normalize Root Folder (screenshot_dir) in place.

    Returns True if the value was changed.
    """
    raw = str(
        config.get("screenshot_dir")
        or config.get("root_folder")
        or ""
    ).strip()
    before = str(config.get("screenshot_dir") or "").strip()

    if raw and Path(raw).is_absolute():
        normalized = str(Path(raw))
        try:
            if Path(raw).exists():
                normalized = str(Path(raw).resolve())
        except OSError:
            normalized = str(Path(raw))
        config["screenshot_dir"] = normalized
        return config["screenshot_dir"] != before

    # Relative / empty / legacy "screenshots" — protect existing library if present
    legacy_root = legacy_screenshots_dir()
    if folder_has_screenshot_data(legacy_root):
        config["screenshot_dir"] = str(legacy_root.resolve())
        logger.info(
            "Keeping legacy screenshot library at %s",
            config["screenshot_dir"],
        )
    else:
        config["screenshot_dir"] = str(get_default_screenshot_root())
        logger.info(
            "Using default screenshot root %s",
            config["screenshot_dir"],
        )
    return config["screenshot_dir"] != before


def ensure_runtime_directories(config: dict) -> None:
    """Create AppData, Root Folder, and Capture when needed."""
    ensure_dir(get_app_data_dir(), label="app data directory")
    root = Path(str(config.get("screenshot_dir") or get_default_screenshot_root()))
    if not root.is_absolute():
        root = (get_legacy_install_root() / root).resolve()
    ensure_dir(root, label="screenshot root")
    save_folder = (
        str(
            config.get("save_folder")
            or config.get("current_folder")
            or DEFAULT_FOLDER
        ).strip()
        or DEFAULT_FOLDER
    )
    ensure_dir(root / save_folder, label="capture folder")


def _maybe_migrate_legacy_tags() -> None:
    new_tags = get_tags_path()
    if new_tags.exists():
        return
    legacy = get_legacy_tags_path()
    if not legacy.is_file():
        return
    try:
        ensure_dir(new_tags.parent, label="app data directory")
        shutil.copy2(legacy, new_tags)
        logger.info("Migrated tags.json to %s (legacy file kept)", new_tags)
    except OSError as e:
        logger.error("Failed to migrate tags.json: %s", e)


def _migrate_legacy_config_if_needed() -> dict | None:
    """
    Copy legacy project-root config.json → APPDATA when new config is absent.

    Never deletes the legacy file. Returns migrated dict or None.
    """
    global _migration_attempted
    new_path = get_config_path()
    if new_path.exists():
        return None
    if _migration_attempted:
        return None
    _migration_attempted = True

    legacy_path = get_legacy_config_path()
    if not legacy_path.is_file():
        return None

    data = _read_json_file(legacy_path)
    if data is None:
        logger.warning(
            "Legacy config unreadable; skipping migration: %s", legacy_path
        )
        return None

    try:
        ensure_dir(get_app_data_dir(), label="app data directory")
        _write_json_file(new_path, data)
        logger.info(
            "Migrated config.json from %s to %s (legacy file kept)",
            legacy_path,
            new_path,
        )
        _maybe_migrate_legacy_tags()
        return data
    except OSError as e:
        logger.error("Config migration failed (legacy untouched): %s", e)
        return None


def _merge_defaults(config: dict) -> bool:
    updated = False
    for key, val in DEFAULT_CONFIG.items():
        if key not in config:
            if key in ("save_folder", "screenshot_dir"):
                continue
            config[key] = val
            updated = True

    if not str(config.get("save_folder") or "").strip():
        legacy_view = (
            (config.get("current_folder") or "").strip()
            or (config.get("current_project") or "").strip()
            or DEFAULT_FOLDER
        )
        config["save_folder"] = legacy_view
        updated = True

    legacy_titles = {
        "Screenshot Manager",
        "ScreenshotManager",
        "ShotNester",
        "ShotNester (Working Title)",
        "ShotDock",
        "Test",
    }
    if (config.get("window_title") or "").strip() in legacy_titles:
        config["window_title"] = APP_NAME
        updated = True
    # Brand window title must stay Capixe (ignore stale custom debug titles)
    if (config.get("window_title") or "").strip() != APP_NAME:
        config["window_title"] = APP_NAME
        updated = True

    defaults_shortcuts = DEFAULT_CONFIG.get("shortcuts") or {}
    raw_shortcuts = config.get("shortcuts")
    if not isinstance(raw_shortcuts, dict):
        config["shortcuts"] = dict(defaults_shortcuts)
        updated = True
    else:
        for sk, sv in defaults_shortcuts.items():
            if sk not in raw_shortcuts or not str(raw_shortcuts.get(sk) or "").strip():
                raw_shortcuts[sk] = sv
                updated = True
        config["shortcuts"] = raw_shortcuts

    return updated


def load_config() -> dict:
    """
    Load config from %APPDATA%\\Capixe\\config.json.

    Migrates legacy project-root config when the new file is absent.
    """
    new_path = get_config_path()

    config: dict | None = None
    if new_path.exists():
        config = _read_json_file(new_path)
        if config is None:
            logger.warning("Using default config (new config unreadable).")
            config = build_default_config()
    else:
        migrated = _migrate_legacy_config_if_needed()
        if migrated is not None:
            config = migrated
        else:
            logger.info("config.json が見つかりません。デフォルト設定を作成します。")
            config = build_default_config()

    assert config is not None
    updated = _merge_defaults(config)
    if normalize_screenshot_dir(config):
        updated = True

    ensure_runtime_directories(config)
    _maybe_migrate_legacy_tags()

    try:
        if updated or not new_path.exists():
            save_config(config)
    except OSError as e:
        logger.error("Failed to persist config after load: %s", e)

    logger.info("config.json を読み込みました: %s", get_config_path())
    return config


def save_config(config: dict) -> None:
    """Persist settings to %APPDATA%\\Capixe\\config.json."""
    path = get_config_path()
    try:
        _write_json_file(path, config)
    except OSError as e:
        logger.error("config.json の保存に失敗しました (%s): %s", path, e)
        raise


def reset_migration_flag_for_tests() -> None:
    """Test helper — allow migration logic to run again."""
    global _migration_attempted
    _migration_attempted = False
