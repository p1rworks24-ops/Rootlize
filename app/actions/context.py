"""Runtime dependencies for Action plan / execute. Not a UI type."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ActionContext:
    metadata: Any
    ocr: Any | None = None
    app_root: Path | None = None
    managed_root: Path | None = None
