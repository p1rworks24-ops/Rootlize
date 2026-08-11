"""Windows path normalization independent of file existence."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path


def display_path(value: str | Path) -> str:
    """Return an absolute, normalized Windows path while preserving case."""
    raw = os.fspath(value).strip()
    if not raw:
        raise ValueError("Path must not be empty.")
    raw = raw.replace("/", "\\")
    return ntpath.normpath(ntpath.abspath(raw))


def normalize_windows_path(value: str | Path) -> str:
    """Return a case-insensitive key for a Windows path."""
    return ntpath.normcase(display_path(value)).casefold()
