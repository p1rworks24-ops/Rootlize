"""Ask AI waits for first-time screenshot prep before Meaning Search."""

from __future__ import annotations

from types import SimpleNamespace

from app.ai_proxy.errors import AiProxyError
from app.i18n import t
from app.ui.ask_ai_status import ask_ai_chat_status, ask_ai_grid_status
from test_ask_ai_meaning_search import (
    RecordingMeaningProvider,
    _grid_names,
    _open_and_send,
    _page,
    _wait_ask_ai,
)
from test_ask_ai_semantic_index import RecordingIndexer


class RunningIndexer(RecordingIndexer):
    def __init__(self, *, ready=1, total=3, needed=2):
        super().__init__()
        self._running = True
        self.ready = ready
        self.total = total
        self.needed = needed

    def is_running(self):
        return self._running

    def has_unready_images(self, folder=None):
        return self._running and self.needed > 0

    def snapshot(self):
        return SimpleNamespace(
            running=self._running,
            ready=self.ready,
            total=self.total,
            needed=self.needed,
        )

    def finish(self):
        self._running = False
        self.needed = 0
        self.ready = self.total


def _assert_no_internals(*texts: str) -> None:
    blob = " ".join(texts).lower()
    for word in ("facts", "vision", "openclip", "db", "sqlite"):
        assert word not in blob


def test_status_copy_prepares_without_internals_or_partial_results():
    preparing = ask_ai_chat_status(searching=False, preparing=True, ready=32, total=120)
    grid = ask_ai_grid_status(
        query="dog", searching=False, preparing=True, ready=32, total=120
    )
    _assert_no_internals(preparing, grid)
    assert "32 / 120" in preparing
    assert "32 / 120" in grid
    assert "ready screenshots" not in preparing.lower()
    assert "ready screenshots" not in grid.lower()
    assert ask_ai_chat_status(searching=True, preparing=False) == t("images.ai.searching_status")
    assert ask_ai_chat_status(searching=False, count=1, preparing=False) == t(
        "images.ai.found_one"
    )
    assert ask_ai_chat_status(searching=False, count=3, preparing=False) == t(
        "images.ai.found", count=3
    )
    assert ask_ai_grid_status(
        query="dog", count=3, searching=False, preparing=False
    ) == t("images.ai.grid_results", query="dog", count=3)


def test_first_query_does_not_call_search_while_unready(tmp_path):
    indexer = RunningIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._semantic_index_indexer = indexer

    _open_and_send(page, "Find images with dogs in them", wait=False)

    assert provider.calls == []
    assert _grid_names(page) == []
    result = page._ai_history.result_messages[-1]
    assert result.searching is True
    _assert_no_internals(result.status_text, page._search_result_label.text())
    assert t("images.ai.preparing_progress", ready=1, total=3) == result.status_text
    assert page._search_result_label.text() == t(
        "images.ai.grid_preparing_progress", query="images with dogs in them", ready=1, total=3
    )
    page.close()


def test_first_query_runs_once_after_prep_completes(tmp_path):
    indexer = RunningIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._semantic_index_indexer = indexer

    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert provider.calls == []
    indexer.finish()
    page._refresh_ask_ai_prep_status()
    _wait_ask_ai(page)

    assert provider.calls == ["images with dogs in them"]
    result = page._ai_history.result_messages[-1]
    assert result.status_text == t("images.ai.found_one")
    assert _grid_names(page) == ["notes.png"]
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=1
    )
    page._refresh_ask_ai_prep_status()
    _wait_ask_ai(page)
    assert provider.calls == ["images with dogs in them"]
    page.close()


def test_same_query_is_not_double_executed_while_waiting(tmp_path):
    indexer = RunningIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._semantic_index_indexer = indexer

    _open_and_send(page, "Find images with dogs in them", wait=False)
    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert provider.calls == []
    indexer.finish()
    page._refresh_ask_ai_prep_status()
    _wait_ask_ai(page)
    page._refresh_ask_ai_prep_status()
    _wait_ask_ai(page)

    assert provider.calls == ["images with dogs in them"]
    page.close()


def test_fresh_images_search_immediately(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    assert provider.calls == ["images with dogs in them"]
    result = page._ai_history.result_messages[-1]
    assert result.status_text == t("images.ai.found_one")
    assert page._search_result_label.text() == t(
        "images.ai.grid_results", query="images with dogs in them", count=1
    )
    page.close()


def test_preparing_does_not_show_partial_search_results(tmp_path):
    indexer = RunningIndexer()
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._semantic_index_indexer = indexer
    _open_and_send(page, "Find images with dogs in them", wait=False)
    assert _grid_names(page) == []
    result = page._ai_history.result_messages[-1]
    blob = f"{result.status_text} {page._search_result_label.text()}".lower()
    assert "found" not in blob
    assert "関連する画像" not in result.status_text
    assert "ready" not in blob
    page.close()


def test_first_query_surfaces_prep_failure_instead_of_empty_search(tmp_path):
    indexer = RunningIndexer()
    indexer._running = False
    indexer.last_error = lambda: AiProxyError("budget_exceeded", status=429)
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    page._semantic_index_indexer = indexer

    _open_and_send(page, "Find images with dogs in them", wait=False)
    page._refresh_ask_ai_prep_status()

    assert provider.calls == []
    result = page._ai_history.result_messages[-1]
    assert result.searching is False
    assert t("account.ai.limit_reached") in result.status_text
    page.close()


def test_later_query_does_not_wait_while_new_images_prepare(tmp_path):
    provider = RecordingMeaningProvider([])
    page, folder = _page(tmp_path, provider)
    provider.batches = [(folder / "notes.png",)]
    _open_and_send(page, "Find images with dogs in them")
    assert provider.calls == ["images with dogs in them"]

    page._semantic_index_indexer = RunningIndexer()
    provider.calls.clear()
    provider.batches = [(folder / "github-home.png",)]
    _open_and_send(page, "Find images with cats in them")
    assert provider.calls == ["images with cats in them"]
    assert _grid_names(page) == ["github-home.png"]
    page.close()
