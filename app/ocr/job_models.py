from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class OCRIndexProgress:
    run_id: str | None=None
    folder_path: str | None=None
    state: str="idle"
    total_discovered: int=0
    total_requires_ocr: int=0
    completed: int=0
    succeeded: int=0
    failed: int=0
    skipped: int=0
    pending: int=0
    current_image_id: int | None=None
    current_filename: str | None=None
    current_started_at: str | None=None
    elapsed_seconds: float=0.0
    estimated_remaining_seconds: float | None=None
    worker_restart_count: int=0
    last_error_type: str | None=None
