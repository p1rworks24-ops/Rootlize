"""Verify Meaning uses vision_relevance and Text stays text on shotlogue_test."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.metadata_service import MetadataService
from app.ui.images_search import VisionRelevanceImagesSearchProvider
from app.ui.pages.images_page import (
    ImagesPage,
    USER_FACING_MEANING_MODE,
    USER_FACING_TEXT_MODE,
)
from app.utils.thumbnail_cache import ThumbnailCache

FOLDER = Path(r"D:\07_Programs\shotlogue_test")


def _wait(page: ImagesPage, seconds: float = 900) -> None:
    app = QApplication.instance()
    deadline = time.perf_counter() + seconds
    while page._search_tasks and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _names(page: ImagesPage, limit: int | None = None) -> list[str]:
    count = page._list_widget.count()
    if limit is not None:
        count = min(count, limit)
    return [
        Path(page._list_widget.item(row).data(Qt.UserRole)).name
        for row in range(count)
    ]


def _provider_name(page: ImagesPage) -> str:
    provider = page._provider_for_mode(page._active_search_mode)
    if hasattr(provider, "__name__"):
        return provider.__name__
    return type(provider).__name__


def _mode_snapshot(page: ImagesPage) -> dict:
    return {
        "configured_mode": page._configured_search_mode(),
        "active_mode": page._active_search_mode,
        "provider": _provider_name(page),
        "combo": page._search_mode_combo.currentData(),
    }


def main() -> int:
    if not FOLDER.is_dir():
        raise SystemExit(f"missing folder: {FOLDER}")
    import app.ui.pages.images_page as images_page_module
    images_page_module.save_config = lambda _value: None
    app = QApplication.instance() or QApplication([])
    page = ImagesPage(
        {
            "selected_folder": str(FOLDER),
            "developer_search_mode": "semantic",
        },
        MetadataService(),
        ThumbnailCache(size=48),
        Path.cwd(),
    )
    page.show()
    app.processEvents()

    startup = _mode_snapshot(page)
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    after_text = _mode_snapshot(page)
    page._search_input.setText("Capixe")
    page._on_search()
    _wait(page, 60)
    text_count = page._list_widget.count()
    text_names = _names(page, 8)

    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    after_meaning = _mode_snapshot(page)
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    after_cycle = _mode_snapshot(page)
    after_meaning_noop = _mode_snapshot(page)

    import app.ui.images_search as images_search
    import app.ui.pages.images_page as images_page

    captured = []
    original_page_info = images_page.logger.info
    original_search_info = images_search.logger.info

    def _capture(original):
        def logged(*args):
            captured.append(args)
            return original(*args)
        return logged

    images_page.logger.info = _capture(original_page_info)
    images_search.logger.info = _capture(original_search_info)
    try:
        page._search_input.setText("dog")
        page._on_search()
        _wait(page)
    finally:
        images_page.logger.info = original_page_info
        images_search.logger.info = original_search_info

    provider = page._owned_vision_search_provider
    run = provider.last_run
    start_log = next(
        (
            args for args in captured
            if args and str(args[0]).startswith("Images-search start")
        ),
        (),
    )
    vision_final = next(
        (
            args for args in reversed(captured)
            if args and str(args[0]).startswith("Vision-relevance session=")
            and "status=%s" in str(args[0])
        ),
        (),
    )
    meaning = {
        "query": "dog",
        **_mode_snapshot(page),
        "start_log_configured_mode": start_log[3] if len(start_log) > 5 else None,
        "start_log_active_mode": start_log[4] if len(start_log) > 5 else None,
        "start_log_provider": start_log[5] if len(start_log) > 5 else None,
        "openclip_candidate_count": vision_final[3] if len(vision_final) > 3 else None,
        "vision_request_count": None if run is None else run.request_count,
        "final_relevant_count": page._list_widget.count(),
        "final_images": _names(page),
        "timing": provider.last_timing,
        "ui_status": page._search_result_label.text(),
        "search_error": None if page._last_search_error is None else repr(page._last_search_error),
        "completed": not page._search_tasks,
        "vision_provider": type(provider) is VisionRelevanceImagesSearchProvider,
    }

    result = {
        "folder": str(FOLDER),
        "startup_legacy_semantic": startup,
        "after_text": after_text,
        "text_query": "Capixe",
        "text_result_count": text_count,
        "text_sample": text_names,
        "after_meaning": after_meaning,
        "after_text_meaning_text_meaning": after_cycle,
        "meaning_noop_keeps_vision": after_meaning_noop,
        "meaning_dog": meaning,
    }
    output = Path("artifacts") / "meaning-vision-route-verification.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    page.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    ok = (
        startup["active_mode"] == USER_FACING_MEANING_MODE
        and startup["provider"] == "VisionRelevanceImagesSearchProvider"
        and after_text["active_mode"] == USER_FACING_TEXT_MODE
        and text_count > 0
        and after_meaning["active_mode"] == USER_FACING_MEANING_MODE
        and after_cycle["active_mode"] == USER_FACING_MEANING_MODE
        and after_meaning_noop["active_mode"] == USER_FACING_MEANING_MODE
        and meaning["provider"] == "VisionRelevanceImagesSearchProvider"
        and meaning["vision_provider"]
        and meaning["completed"]
        and meaning["final_relevant_count"] > 0
        and (meaning["vision_request_count"] or 0) > 0
        and (meaning["openclip_candidate_count"] or 0) > 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
