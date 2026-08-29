"""Folder rename / duplicate / delete helpers (Explorer-style names)."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger()

_INVALID_FOLDER_CHARS = set('\\/:*?"<>|')


def is_valid_folder_name(name: str) -> bool:
    text = (name or "").strip()
    if not text or text in (".", ".."):
        return False
    return not any(ch in _INVALID_FOLDER_CHARS for ch in text)


def create_folder(parent: Path, name: str) -> Path:
    """Create ``parent / name``. Does not overwrite or merge an existing path."""
    parent = Path(parent)
    name = (name or "").strip()
    if not is_valid_folder_name(name):
        raise ValueError("invalid folder name")
    dest = parent / name
    if dest.exists():
        raise FileExistsError(str(dest))
    dest.mkdir(parents=False, exist_ok=False)
    logger.info("Created folder %s", dest)
    return dest


def make_unique_folder_copy_name(parent: Path, base_name: str) -> str:
    """
    Windows Explorer-like copy names:
    Name → Name - Copy → Name - Copy (2) → …
    """
    candidate = f"{base_name} - Copy"
    if not (parent / candidate).exists():
        return candidate
    n = 2
    while True:
        candidate = f"{base_name} - Copy ({n})"
        if not (parent / candidate).exists():
            return candidate
        n += 1


def duplicate_folder(src: Path, parent: Path | None = None) -> Path:
    """
    Copy an entire folder (PNG + .sstool / metadata / project) to a unique sibling name.
    """
    src = src.resolve()
    if not src.is_dir():
        raise FileNotFoundError(str(src))
    dest_parent = (parent or src.parent).resolve()
    new_name = make_unique_folder_copy_name(dest_parent, src.name)
    dest = dest_parent / new_name
    shutil.copytree(src, dest)
    logger.info("Duplicated folder %s → %s", src, dest)
    return dest


def rename_folder(src: Path, new_name: str) -> Path:
    """Rename a folder directory. Returns the new path."""
    src = src.resolve()
    new_name = (new_name or "").strip()
    if not is_valid_folder_name(new_name):
        raise ValueError("invalid folder name")
    dest = src.parent / new_name
    if dest.exists():
        raise FileExistsError(str(dest))
    src.rename(dest)
    logger.info("Renamed folder %s → %s", src, dest)
    return dest


def delete_folder(path: Path) -> None:
    """Delete a folder and all contents."""
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(str(path))
    shutil.rmtree(path)
    logger.info("Deleted folder %s", path)
