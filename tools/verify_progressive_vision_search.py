"""One-query UI verification for the progressive Vision relevance search."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def main() -> int:
    folder = Path(r"D:\07_Programs\shotlogue_test")
    app = QApplication.instance() or QApplication([])
    page = ImagesPage(
        {"selected_folder": str(folder), "developer_search_mode": "vision_relevance"},
        MetadataService(), ThumbnailCache(size=48), Path.cwd(),
    )
    page.show()
    app.processEvents()
    started = time.perf_counter()
    page._search_input.setText("dog")
    submit_started = time.perf_counter()
    page._on_search()
    submit_seconds = time.perf_counter() - submit_started
    progress = [{
        "checked": 0,
        "visible_count": page._list_widget.count(),
        "elapsed_seconds": time.perf_counter() - started,
        "phase": "search_started",
    }]
    last_checked = None
    deadline = started + 900
    while page._search_tasks and time.perf_counter() < deadline:
        app.processEvents()
        label = page._search_result_label.text()
        match = re.search(r"(\d+)/(\d+)", label)
        if match and int(match.group(1)) != last_checked:
            last_checked = int(match.group(1))
            progress.append({
                "checked": last_checked,
                "visible_count": page._list_widget.count(),
                "elapsed_seconds": time.perf_counter() - started,
                "phase": "chunk_completed",
            })
        time.sleep(0.01)
    app.processEvents()
    provider = page._owned_vision_search_provider
    run = provider.last_run
    result = {
        "query": "dog",
        "folder": str(folder),
        "configured_mode": page._configured_search_mode(),
        "active_mode": page._active_search_mode,
        "provider": type(page._provider_for_mode(page._active_search_mode)).__name__,
        "ui_submit_seconds": submit_seconds,
        "progress": progress,
        "final_elapsed_seconds": time.perf_counter() - started,
        "final_count": page._list_widget.count(),
        "final_images": [
            Path(page._list_widget.item(row).data(Qt.UserRole)).name
            for row in range(page._list_widget.count())
        ],
        "timing": provider.last_timing,
        "request_count": None if run is None else run.request_count,
        "request_attempt_count": None if run is None else run.request_attempt_count,
        "retry_count": None if run is None else run.retry_count,
        "input_tokens": None if run is None else run.input_tokens,
        "output_tokens": None if run is None else run.output_tokens,
        "failed_image_ids": [] if run is None else list(run.failed_image_ids),
        "errors": [] if run is None else list(run.errors),
        "ui_status": page._search_result_label.text(),
        "ui_empty_title": page._list_empty_title.text(),
        "ui_empty_body": page._list_empty_body.text(),
        "search_error": None if page._last_search_error is None else repr(page._last_search_error),
        "completed": not page._search_tasks,
    }
    output = Path("artifacts") / "progressive-vision-dog-verification.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    page.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
