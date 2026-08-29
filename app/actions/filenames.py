"""Windows filename / folder-name checks used by Action validation.

Kept independent of Qt so UI, Ask AI, and future Automation share one rule set.
"""
from __future__ import annotations

from pathlib import Path

_INVALID_CHARS = set('\\/:*?"<>|')
_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
_MANAGED_FORBIDDEN_NAMES = frozenset({".sstool", "metadata.json"})
MAX_PATH_LEN = 259


def invalid_name_chars(name: str) -> bool:
    text = name or ""
    if any(ord(ch) < 32 for ch in text):
        return True
    return any(ch in _INVALID_CHARS for ch in text)


def reserved_device_stem(name: str) -> bool:
    """True for Windows device names such as CON, NUL, COM1 (with or without suffix)."""
    raw = (name or "").strip().rstrip(" .")
    if not raw:
        return False
    stem = raw.split(".", 1)[0].upper()
    return stem in _RESERVED_STEMS


def is_valid_file_stem(name: str) -> bool:
    text = (name or "").strip()
    if not text or text in {".", ".."}:
        return False
    if text.endswith(".") or text.endswith(" "):
        return False
    if invalid_name_chars(text):
        return False
    if reserved_device_stem(text):
        return False
    return True


def is_safe_relative_name(name: str) -> bool:
    """True for a single folder/file component with no traversal or drive change."""
    text = (name or "").strip().strip("「」\"'")
    if not text or text in {".", ".."}:
        return False
    if text.startswith("\\\\") or text.startswith("//"):
        return False
    if len(text) >= 2 and text[1] == ":":
        return False
    if any(sep in text for sep in ("/", "\\")):
        return False
    if ".." in text:
        return False
    if invalid_name_chars(text) or reserved_device_stem(text):
        return False
    if text.casefold() in {item.casefold() for item in _MANAGED_FORBIDDEN_NAMES}:
        return False
    return True


def is_managed_hidden_path(path: Path | str | None) -> bool:
    candidate = Path(path) if path else None
    if candidate is None:
        return False
    return any(part.casefold() == ".sstool" for part in candidate.parts)


def path_too_long(path: Path | str | None) -> bool:
    return len(str(path or "")) > MAX_PATH_LEN


def is_within_root(path: Path | str | None, root: Path | str | None) -> bool:
    if path is None or root is None:
        return False
    try:
        resolved = Path(path).resolve()
        base = Path(root).resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


def same_filesystem_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left).casefold() == str(right).casefold()


def is_image_suffix(suffix: str) -> bool:
    return (suffix or "").lower() in _IMAGE_SUFFIXES


def normalize_rename_filename(old_name: str, new_name: str) -> str:
    """Keep a recognized image suffix; otherwise reuse the source suffix."""
    old = Path(old_name).name
    incoming = Path((new_name or "").strip()).name
    if not incoming:
        return ""
    new_suffix = Path(incoming).suffix
    old_suffix = Path(old).suffix or ".png"
    if is_image_suffix(new_suffix):
        return incoming
    return f"{incoming}{old_suffix}"
