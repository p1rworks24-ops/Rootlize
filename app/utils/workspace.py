"""Root → Folder → Images path helpers and layout migration."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_FOLDER = "Capture"


def resolve_screenshot_root(screenshot_dir: str | Path, app_root: Path) -> Path:
    path_obj = Path(screenshot_dir)
    if not path_obj.is_absolute():
        path_obj = (app_root / path_obj).resolve()
    return path_obj.resolve()


def resolve_folder_dir(
    screenshot_dir: str | Path,
    folder_name: str,
    app_root: Path,
) -> Path:
    """Resolve {root}/{Folder} where images and .sstool live."""
    return (resolve_screenshot_root(screenshot_dir, app_root) / folder_name).resolve()


def _unique_dir_name(parent: Path, name: str) -> str:
    if not (parent / name).exists():
        return name
    n = 2
    while (parent / f"{name}_{n}").exists():
        n += 1
    return f"{name}_{n}"


def _move_contents(src: Path, dest: Path) -> None:
    """Move files/dirs from src into dest (merge)."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dest / item.name
        if item.name == ".sstool" and target.exists():
            shutil.rmtree(item, ignore_errors=True)
            continue
        if target.exists():
            if item.is_file() and item.suffix.lower() == ".png":
                stem, suffix = item.stem, item.suffix
                n = 1
                while True:
                    candidate = dest / f"{stem}_migrated{n}{suffix}"
                    if not candidate.exists():
                        target = candidate
                        break
                    n += 1
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
                continue
            else:
                item.unlink(missing_ok=True)
                continue
        shutil.move(str(item), str(target))
    try:
        src.rmdir()
    except OSError:
        shutil.rmtree(src, ignore_errors=True)


def is_image_folder(path: Path) -> bool:
    """True when this directory holds images / .sstool directly."""
    if not path.is_dir():
        return False
    if (path / ".sstool").is_dir():
        return True
    if (path / "metadata.json").is_file():
        return True
    return any(path.glob("*.png"))


def migrate_nested_layout(screenshot_root: Path) -> bool:
    """
    Flatten Project/Folder nesting into Root/Folder.

    - Capture (or sole nested image folder) merges into the parent folder.
    - Other nested image folders are promoted to the screenshot root.
    """
    if not screenshot_root.exists():
        return False

    changed = False
    for child in list(screenshot_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue

        subdirs = [
            d
            for d in child.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        nested = [d for d in subdirs if is_image_folder(d)]
        if not nested:
            continue

        # Nested Project/Folder layout detected
        changed = True
        for nested_dir in nested:
            if nested_dir.name == DEFAULT_FOLDER or (
                len(nested) == 1 and not is_image_folder(child)
            ):
                _move_contents(nested_dir, child)
                logger.info(
                    "Flattened nested folder: %s/%s -> %s/",
                    child.name,
                    nested_dir.name,
                    child.name,
                )
            else:
                new_name = _unique_dir_name(screenshot_root, nested_dir.name)
                dest = screenshot_root / new_name
                shutil.move(str(nested_dir), str(dest))
                logger.info(
                    "Promoted nested folder: %s/%s -> %s/",
                    child.name,
                    nested_dir.name,
                    new_name,
                )

    return changed


def list_folder_names(screenshot_root: Path, *, ensure_default: bool = True) -> list[str]:
    """Folder names directly under the screenshot root."""
    if not screenshot_root.exists():
        if ensure_default:
            (screenshot_root / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)
            return [DEFAULT_FOLDER]
        return []

    migrate_nested_layout(screenshot_root)

    names = sorted(
        [
            p.name
            for p in screenshot_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ],
        key=str.lower,
    )

    if ensure_default and not names:
        (screenshot_root / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)
        return [DEFAULT_FOLDER]

    return names


def ensure_folder(
    screenshot_dir: str | Path,
    folder_name: str,
    app_root: Path,
) -> Path:
    folder_dir = resolve_folder_dir(screenshot_dir, folder_name, app_root)
    folder_dir.mkdir(parents=True, exist_ok=True)
    return folder_dir


def iter_image_dirs(screenshot_root: Path) -> list[Path]:
    """All folder dirs under the screenshot root that hold images."""
    return [
        (screenshot_root / name).resolve()
        for name in list_folder_names(screenshot_root, ensure_default=False)
    ]


def pick_folder_name(available: list[str], preferred: str | None = None) -> str:
    if preferred and preferred in available:
        return preferred
    if DEFAULT_FOLDER in available:
        return DEFAULT_FOLDER
    if available:
        return available[0]
    return DEFAULT_FOLDER


def resolve_current_folder(config: dict) -> str:
    """Resolve the Images viewing folder (supports legacy current_project)."""
    folder = (config.get("current_folder") or "").strip()
    if folder:
        return folder
    legacy_project = (config.get("current_project") or "").strip()
    if legacy_project:
        return legacy_project
    return DEFAULT_FOLDER


def resolve_save_folder(config: dict) -> str:
    """
    Resolve the Screenshot capture destination folder.

    Independent from resolve_current_folder (Images viewing). Falls back to the
    viewing folder only when save_folder has never been set.
    """
    folder = (config.get("save_folder") or "").strip()
    if folder:
        return folder
    return resolve_current_folder(config)
