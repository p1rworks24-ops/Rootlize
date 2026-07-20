"""Central path resolution for Capixe (resources vs writable user data).

User data never goes under sys._MEIPASS. Writable roots use Windows
APPDATA / Pictures (with Path.home() fallbacks).

Tests may call ``set_path_overrides`` / ``clear_path_overrides`` so real
user folders are not touched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.branding import APP_NAME

# ---------------------------------------------------------------------------
# Test overrides (None = use real environment)
# ---------------------------------------------------------------------------
_app_data_override: Path | None = None
_local_app_data_override: Path | None = None
_default_screenshot_override: Path | None = None
_legacy_root_override: Path | None = None
_resource_root_override: Path | None = None


def set_path_overrides(
    *,
    app_data_dir: Path | None = None,
    local_app_data_dir: Path | None = None,
    default_screenshot_root: Path | None = None,
    legacy_install_root: Path | None = None,
    resource_root: Path | None = None,
) -> None:
    """Redirect path helpers (for tests). Pass None to leave a slot unchanged."""
    global _app_data_override, _local_app_data_override
    global _default_screenshot_override, _legacy_root_override, _resource_root_override
    if app_data_dir is not None:
        _app_data_override = Path(app_data_dir)
    if local_app_data_dir is not None:
        _local_app_data_override = Path(local_app_data_dir)
    if default_screenshot_root is not None:
        _default_screenshot_override = Path(default_screenshot_root)
    if legacy_install_root is not None:
        _legacy_root_override = Path(legacy_install_root)
    if resource_root is not None:
        _resource_root_override = Path(resource_root)


def clear_path_overrides() -> None:
    global _app_data_override, _local_app_data_override
    global _default_screenshot_override, _legacy_root_override, _resource_root_override
    _app_data_override = None
    _local_app_data_override = None
    _default_screenshot_override = None
    _legacy_root_override = None
    _resource_root_override = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_resource_root() -> Path:
    """
    Read-only bundle / source tree root.

    Frozen + _MEIPASS: unpack dir (read-only). Never write user data here.
    """
    if _resource_root_override is not None:
        return _resource_root_override.resolve()
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_legacy_install_root() -> Path:
    """
    Former project / portable exe directory (writable install neighbour).

    Used for legacy config.json and old relative ``screenshots`` resolution.
    Never returns _MEIPASS.
    """
    if _legacy_root_override is not None:
        return _legacy_root_override.resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_app_data_dir() -> Path:
    """%APPDATA%\\Capixe (roaming settings)."""
    if _app_data_override is not None:
        return _app_data_override.resolve()
    appdata = (os.environ.get("APPDATA") or "").strip()
    if appdata:
        return (Path(appdata) / APP_NAME).resolve()
    return (Path.home() / "AppData" / "Roaming" / APP_NAME).resolve()


def get_local_app_data_dir() -> Path:
    """%LOCALAPPDATA%\\Capixe (logs / future cache)."""
    if _local_app_data_override is not None:
        return _local_app_data_override.resolve()
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        return (Path(local) / APP_NAME).resolve()
    return (Path.home() / "AppData" / "Local" / APP_NAME).resolve()


def get_logs_dir() -> Path:
    """Defined location for future file logs (not used yet)."""
    return get_local_app_data_dir() / "logs"


def get_config_path() -> Path:
    return get_app_data_dir() / "config.json"


def get_legacy_config_path() -> Path:
    return get_legacy_install_root() / "config.json"


def get_tags_path() -> Path:
    """Global tags master file (writable user data)."""
    return get_app_data_dir() / "tags.json"


def get_legacy_tags_path() -> Path:
    return get_legacy_install_root() / "tags.json"


def get_default_screenshot_root() -> Path:
    """New-user Root Folder: Pictures\\Capixe."""
    if _default_screenshot_override is not None:
        return _default_screenshot_override.resolve()
    pictures = _resolve_pictures_dir()
    return (pictures / APP_NAME).resolve()


def _resolve_pictures_dir() -> Path:
    try:
        from PySide6.QtCore import QStandardPaths

        loc = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        if loc:
            return Path(loc)
    except Exception:
        pass
    return Path.home() / "Pictures"


def legacy_screenshots_dir() -> Path:
    return get_legacy_install_root() / "screenshots"


def folder_has_screenshot_data(root: Path) -> bool:
    """True if root looks like it already holds Capixe library data."""
    try:
        if not root.is_dir():
            return False
    except OSError:
        return False
    try:
        for path in root.rglob("*"):
            try:
                if path.is_file() and path.suffix.lower() == ".png":
                    return True
                if path.is_dir() and path.name in (".sstool",):
                    return True
                if path.is_file() and path.name in ("metadata.json", "project.json"):
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False


def ensure_dir(path: Path, *, label: str = "directory") -> bool:
    """Create directory; log and return False on failure (does not raise)."""
    from app.utils.logger import setup_logger

    log = setup_logger()
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        log.error("Failed to create %s %s: %s", label, path, exc)
        return False
