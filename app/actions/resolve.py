"""Resolve Action targets to Capixe image_id + current path, then sync index."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ocr.exceptions import OCRDuplicatePathError, OCRRecordNotFoundError

from .context import ActionContext
from .models import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    ActionIssue,
    ActionTarget,
    issue,
)


@dataclass(frozen=True)
class ResolvedTarget:
    target: ActionTarget
    image_id: int | None
    path: Path | None
    record: Any | None
    issues: tuple[ActionIssue, ...]

    @property
    def blocked(self) -> bool:
        return any(item.severity == SEVERITY_ERROR for item in self.issues)


def _paths_match(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


def resolve_target(target: ActionTarget, context: ActionContext) -> ResolvedTarget:
    issues: list[ActionIssue] = []
    record = None
    path = Path(target.path) if target.path else None
    image_id = target.image_id

    if image_id is not None and context.ocr is not None:
        try:
            record = context.ocr.get_image(image_id)
            db_path = Path(record.path)
            if path is not None and not _paths_match(db_path, path):
                issues.append(
                    issue(
                        "db_mismatch",
                        SEVERITY_ERROR,
                        "Current path does not match the indexed image.",
                        path=str(path),
                    )
                )
            path = db_path
        except OCRRecordNotFoundError:
            issues.append(
                issue(
                    "source_missing",
                    SEVERITY_ERROR,
                    "Indexed image was not found.",
                    path=str(path) if path is not None else None,
                )
            )
            return ResolvedTarget(target, image_id, path, None, tuple(issues))
    elif path is not None and context.ocr is not None:
        try:
            record = context.ocr.get_image_by_path(path)
            image_id = int(record.image_id)
        except (OCRRecordNotFoundError, OSError):
            record = None

    if path is None:
        issues.append(issue("source_missing", SEVERITY_ERROR, "A target path is required."))
        return ResolvedTarget(target, image_id, None, record, tuple(issues))

    return ResolvedTarget(
        target=ActionTarget(image_id=image_id, path=str(path)),
        image_id=image_id,
        path=path,
        record=record,
        issues=tuple(issues),
    )


def sync_path_change(context: ActionContext, image_id: int | None, new_path: Path) -> ActionIssue | None:
    """Point OCR / search / facts at the new path without re-analyzing content."""
    if context.ocr is None or image_id is None:
        return None
    try:
        mtime_ns = int(new_path.stat().st_mtime_ns)
        context.ocr.update_path(image_id, new_path, mtime_ns=mtime_ns)
        return None
    except OCRRecordNotFoundError:
        return None
    except OCRDuplicatePathError:
        return issue(
            "index_path_conflict",
            SEVERITY_WARNING,
            "Index already has a record for the destination path.",
            path=str(new_path),
        )
    except OSError as exc:
        return issue(
            "index_sync_failed",
            SEVERITY_WARNING,
            str(exc),
            path=str(new_path),
        )


def sync_tags(context: ActionContext, image_id: int | None, tags: list[str]) -> ActionIssue | None:
    if context.ocr is None or image_id is None:
        return None
    try:
        context.ocr.update_tags(image_id, list(tags))
        return None
    except OCRRecordNotFoundError:
        return None
    except OSError as exc:
        return issue("index_sync_failed", SEVERITY_WARNING, str(exc))
