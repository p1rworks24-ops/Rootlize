"""Shared save-folder helpers used by Settings and the shell top bar."""

from __future__ import annotations

from pathlib import Path

from app.config import save_config
from app.utils.logger import setup_logger
from app.utils.workspace import (
    DEFAULT_FOLDER,
    ensure_folder,
    list_folder_names as workspace_list_folders,
    resolve_save_folder,
    resolve_screenshot_root,
)

logger = setup_logger()


def resolve_screenshot_dir(config: dict, app_root: Path) -> Path:
    return resolve_screenshot_root(
        config.get("screenshot_dir", "screenshots"),
        app_root,
    )


def list_folder_names(config: dict, app_root: Path) -> list[str]:
    """Return folder names under the screenshot root."""
    return workspace_list_folders(resolve_screenshot_dir(config, app_root), ensure_default=True)


def format_save_folder_label(config: dict, app_root: Path, *, max_len: int = 28) -> str:
    """Short label for Settings save-destination control (root path name)."""
    path = resolve_screenshot_dir(config, app_root)
    text = path.name or str(path)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def apply_screenshot_dir(
    config: dict,
    app_root: Path,
    selected_path: str,
) -> Path:
    """
    Update screenshot_dir in config, ensure the current folder exists, and persist.

    Returns the resolved absolute save root.
    """
    selected_path = selected_path.strip()
    if not selected_path:
        raise ValueError("empty path")

    path_obj = Path(selected_path)
    if not path_obj.is_absolute():
        path_obj = (app_root / path_obj).resolve()
    path_obj.mkdir(parents=True, exist_ok=True)

    save_folder = resolve_save_folder(config)
    config["save_folder"] = save_folder
    ensure_folder(str(path_obj), save_folder, app_root)

    try:
        store_path = str(path_obj.relative_to(app_root.resolve()))
    except ValueError:
        store_path = str(path_obj)

    config["screenshot_dir"] = store_path
    save_config(config)
    logger.info("Save folder updated: %s", store_path)
    return path_obj
