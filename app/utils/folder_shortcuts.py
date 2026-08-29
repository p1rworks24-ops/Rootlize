"""Favorite and recent folder lists stored on the app config."""

from __future__ import annotations

from pathlib import Path

FAVORITE_FOLDERS_KEY = "favorite_folders"
RECENT_FOLDERS_KEY = "recent_folders"
MAX_FAVORITE_FOLDERS = 12
MAX_RECENT_FOLDERS = 8


def _normalize_path(folder: str | Path) -> Path:
    return Path(folder).expanduser().resolve()


def _clean_paths(raw_values, *, limit: int) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in raw_values or []:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            path = _normalize_path(text)
        except OSError:
            continue
        key = str(path)
        if key in seen:
            continue
        if not path.is_dir():
            continue
        seen.add(key)
        cleaned.append(key)
        if len(cleaned) >= limit:
            break
    return cleaned


def list_favorite_folders(config: dict) -> list[Path]:
    return [Path(item) for item in _clean_paths(config.get(FAVORITE_FOLDERS_KEY), limit=MAX_FAVORITE_FOLDERS)]


def is_favorite_folder(config: dict, folder: str | Path | None) -> bool:
    if folder is None:
        return False
    try:
        key = str(_normalize_path(folder))
    except OSError:
        return False
    return any(str(path) == key for path in list_favorite_folders(config))


def set_favorite_folder_order(config: dict, folders: list) -> list[Path]:
    """Keep the same favorite set, in the given order."""
    current = _clean_paths(config.get(FAVORITE_FOLDERS_KEY), limit=MAX_FAVORITE_FOLDERS)
    current_set = set(current)
    ordered: list[str] = []
    seen: set[str] = set()
    for folder in folders:
        try:
            key = str(_normalize_path(folder))
        except OSError:
            continue
        if key not in current_set or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    for key in current:
        if key not in seen:
            ordered.append(key)
    config[FAVORITE_FOLDERS_KEY] = ordered[:MAX_FAVORITE_FOLDERS]
    return [Path(item) for item in config[FAVORITE_FOLDERS_KEY]]


def toggle_favorite_folder(config: dict, folder: str | Path) -> bool:
    """Add or remove a folder favorite. Returns True when the folder is now a favorite."""
    path = _normalize_path(folder)
    key = str(path)
    current = _clean_paths(config.get(FAVORITE_FOLDERS_KEY), limit=MAX_FAVORITE_FOLDERS)
    if key in current:
        current = [item for item in current if item != key]
        config[FAVORITE_FOLDERS_KEY] = current
        return False
    current.insert(0, key)
    config[FAVORITE_FOLDERS_KEY] = current[:MAX_FAVORITE_FOLDERS]
    return True


def remember_recent_folder(config: dict, folder: str | Path) -> None:
    path = _normalize_path(folder)
    if not path.is_dir():
        return
    key = str(path)
    current = [item for item in _clean_paths(config.get(RECENT_FOLDERS_KEY), limit=MAX_RECENT_FOLDERS) if item != key]
    current.insert(0, key)
    config[RECENT_FOLDERS_KEY] = current[:MAX_RECENT_FOLDERS]


def list_recent_folders(config: dict) -> list[Path]:
    return [Path(item) for item in _clean_paths(config.get(RECENT_FOLDERS_KEY), limit=MAX_RECENT_FOLDERS)]


def list_child_folders(folder: Path | None) -> list[Path]:
    """Immediate child directories suitable for in-app browsing."""
    if folder is None or not folder.is_dir():
        return []
    skip = {".sstool", "$recycle.bin", "system volume information"}
    children: list[Path] = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    for child in entries:
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        name = child.name
        if name.startswith(".") or name.lower() in skip:
            continue
        children.append(child)
    return sorted(children, key=lambda item: item.name.casefold())
