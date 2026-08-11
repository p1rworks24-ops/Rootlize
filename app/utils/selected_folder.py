"""Selected image-folder helpers for Images, Organize, and Home."""

from __future__ import annotations

from pathlib import Path

from app.utils.workspace import resolve_current_folder, resolve_folder_dir

SELECTED_FOLDER_KEY = "selected_folder"


def get_selected_folder(config: dict, app_root: Path) -> Path | None:
    """Return the selected folder, preserving compatibility with direct test configs."""
    if SELECTED_FOLDER_KEY in config:
        raw = str(config.get(SELECTED_FOLDER_KEY) or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = app_root / path
        return path.resolve()

    # Older callers that construct a config directly still describe the old
    # root/current-folder pair. load_config() migrates real user configs.
    return resolve_folder_dir(
        config.get("screenshot_dir", "screenshots"),
        resolve_current_folder(config),
        app_root,
    )


def set_selected_folder(config: dict, folder: str | Path) -> Path:
    path = Path(folder).resolve()
    config[SELECTED_FOLDER_KEY] = str(path)
    return path


def selected_folder_state(config: dict, app_root: Path) -> tuple[Path | None, str]:
    path = get_selected_folder(config, app_root)
    if path is None:
        return None, "unselected"
    if not path.is_dir():
        return path, "missing"
    return path, "ready"
