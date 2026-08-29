"""Local-only Workflow persistence. No cloud sync."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import ensure_dir, get_automations_path

from .models import WORKFLOW_FORMAT_VERSION, Workflow, workflow_from_payload, workflow_to_payload


def default_store_path() -> Path:
    return get_automations_path()


class WorkflowStore:
    """Load and save Workflows as a single JSON file under APPDATA."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()

    def list(self) -> tuple[Workflow, ...]:
        return tuple(self._load().values())

    def get(self, workflow_id: str) -> Workflow | None:
        return self._load().get(str(workflow_id or "").strip())

    def save(self, workflow: Workflow) -> Workflow:
        items = self._load()
        items[workflow.id] = workflow
        self._write(items)
        return workflow

    def rename(self, workflow_id: str, name: str, *, description: str | None = None) -> Workflow | None:
        current = self.get(workflow_id)
        if current is None:
            return None
        updated = current.with_name(name, description=description)
        if not updated.name:
            return None
        return self.save(updated)

    def delete(self, workflow_id: str) -> bool:
        items = self._load()
        key = str(workflow_id or "").strip()
        if key not in items:
            return False
        del items[key]
        self._write(items)
        return True

    def _load(self) -> dict[str, Workflow]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {}
        rows = raw.get("workflows") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return {}
        items: dict[str, Workflow] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            workflow = workflow_from_payload(row)
            if workflow is None:
                continue
            items[workflow.id] = workflow
        return items

    def _write(self, items: dict[str, Workflow]) -> None:
        ensure_dir(self.path.parent, label="automation store")
        payload: dict[str, Any] = {
            "version": WORKFLOW_FORMAT_VERSION,
            "workflows": [workflow_to_payload(item) for item in items.values()],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)
