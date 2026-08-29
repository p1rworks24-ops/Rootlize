"""Ask AI starts progressive facts after explicit consent; other entry points do not."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog

from app.config import (
    ASK_AI_CONSENT_NOTICE_VERSION,
    ASK_AI_CONSENT_NOTICE_VERSION_KEY,
    ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY,
)
from app.i18n import t
from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from test_ask_ai_consent import _ScriptedConsentDialog
from test_ask_ai_meaning_search import (
    RecordingMeaningProvider,
    _grid_names,
    _open_and_send,
    _wait_ask_ai,
    _wait_search,
)
from conftest import gallery_image_items, install_ask_ai_test_planner


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


class RecordingIndexer:
    def __init__(self):
        self.starts: list[tuple[Path, bool]] = []
        self.cancels = 0

    def start(self, folder, *, consented):
        self.starts.append((Path(folder).resolve(), consented))
        return consented

    def cancel(self):
        self.cancels += 1

    def close(self, timeout=None):
        self.cancel()


def _page(tmp_path: Path, provider, indexer, *, consented: bool | None = True, extra_folder=None):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for name in ("github-home.png", "notes.png"):
        _png(folder / name)
    if extra_folder is not None:
        extra_folder.mkdir(parents=True, exist_ok=True)
        _png(extra_folder / "other.png")
    config = {
        "selected_folder": str(folder),
        "screenshot_dir": str(tmp_path / "legacy"),
        "current_folder": "Capture",
        "save_folder": "Capture",
        "developer_search_mode": "text",
    }
    if consented is not None:
        config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] = consented
        if consented:
            config[ASK_AI_CONSENT_NOTICE_VERSION_KEY] = ASK_AI_CONSENT_NOTICE_VERSION
    page = ImagesPage(
        config,
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=lambda *_args: (),
        semantic_search_provider=lambda *_args: (),
        vision_search_provider=provider,
        semantic_index_indexer=indexer,
    )
    page.show()
    app.processEvents()
    page.refresh()
    app.processEvents()
    install_ask_ai_test_planner(page)
    return page, folder


def test_folder_load_does_not_start_semantic_index(tmp_path):
    indexer = RecordingIndexer()
    page, _folder = _page(tmp_path, RecordingMeaningProvider([]), indexer)
    assert indexer.starts == []
    page.close()


def test_opening_ask_ai_after_consent_starts_semantic_index(tmp_path):
    indexer = RecordingIndexer()
    page, folder = _page(tmp_path, RecordingMeaningProvider([]), indexer, consented=True)
    page._show_ai_panel()
    assert indexer.starts == [(folder.resolve(), True)]
    page.close()


def test_agreeing_from_ask_ai_starts_semantic_index(tmp_path, monkeypatch):
    indexer = RecordingIndexer()
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, []),
    )
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    page, folder = _page(
        tmp_path, RecordingMeaningProvider([]), indexer, consented=False
    )
    page._show_ai_panel()
    assert page._config[ASK_AI_EXTERNAL_PROCESSING_CONSENTED_KEY] is True
    assert indexer.starts == [(folder.resolve(), True)]
    page.close()


def test_first_send_after_inline_consent_starts_semantic_index(tmp_path, monkeypatch):
    indexer = RecordingIndexer()
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Accepted, []),
    )
    monkeypatch.setattr("app.ui.pages.images_page.save_config", lambda config: None)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, indexer, consented=False)
    provider.batches = [(folder / "notes.png",)]
    page._ai_panel_expanded = True
    page._right_stack.setCurrentWidget(page._ai_page)
    page._action_input.setText("Find windows settings")
    page._on_ask_ai_send()
    _wait_ask_ai(page)
    assert indexer.starts == [(folder.resolve(), True)]
    assert provider.calls == ["windows settings"]
    page.close()


def test_declined_send_does_not_start_semantic_index(tmp_path, monkeypatch):
    indexer = RecordingIndexer()
    monkeypatch.setattr(
        "app.ui.pages.images_page.AskAiConsentDialog",
        _ScriptedConsentDialog(QDialog.Rejected, []),
    )
    page, _folder = _page(
        tmp_path, RecordingMeaningProvider([]), indexer, consented=False
    )
    page._ai_panel_expanded = True
    page._right_stack.setCurrentWidget(page._ai_page)
    page._action_input.setText("Find images with dogs in them")
    page._on_ask_ai_send()
    assert indexer.starts == []
    page.close()


def test_first_ask_ai_send_starts_semantic_index_and_keeps_meaning_grid(tmp_path):
    indexer = RecordingIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, indexer)
    provider.batches = [(folder / "github-home.png", folder / "notes.png")]
    _open_and_send(page, "Find images with dogs in them")
    assert indexer.starts == [(folder.resolve(), True), (folder.resolve(), True)]
    assert provider.calls == ["images with dogs in them"]
    assert _grid_names(page) == ["github-home.png", "notes.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=2
    )
    page.close()


def test_later_ask_ai_sends_ask_to_reuse_existing_index_job(tmp_path):
    indexer = RecordingIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, indexer)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    provider.batches = [(folder / "github-home.png",)]
    _open_and_send(page, "Find images with cats in them")
    assert indexer.starts == [
        (folder.resolve(), True),
        (folder.resolve(), True),
        (folder.resolve(), True),
    ]
    assert provider.calls == ["images with dogs in them", "images with cats in them"]
    assert _grid_names(page) == ["github-home.png"]
    page.close()


def test_text_search_does_not_start_semantic_index(tmp_path, monkeypatch):
    indexer = RecordingIndexer()
    calls = []

    def text_search(query, folder, candidates):
        calls.append(query)
        return (folder / "notes.png",)

    monkeypatch.setattr("app.ui.pages.images_page.search_indexed_images", text_search)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider, indexer)
    page._search_input.setText("notes")
    page._on_search()
    _wait_search(page)
    assert indexer.starts == []
    assert calls == ["notes"]
    visible = [
        Path(item.data(Qt.UserRole)).name
        for item in gallery_image_items(page._list_widget)
    ]
    assert visible == ["notes.png"]
    _open_and_send(page, "Find images with dogs in them")
    assert indexer.starts == [(folder.resolve(), True), (folder.resolve(), True)]
    assert calls == ["notes"]
    page.close()


def test_folder_change_cancels_previous_semantic_index(tmp_path):
    indexer = RecordingIndexer()
    provider = RecordingMeaningProvider([])
    other = tmp_path / "Other"
    page, folder = _page(tmp_path, provider, indexer, extra_folder=other)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    assert indexer.starts == [(folder.resolve(), True), (folder.resolve(), True)]
    cancels = indexer.cancels
    page.open_folder(other)
    assert indexer.cancels == cancels + 1
    page.close()
