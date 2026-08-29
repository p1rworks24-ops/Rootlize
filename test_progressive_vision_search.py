from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.relevance import RelevanceResult, RelevanceRun
from app.relevance.provider import RelevanceProviderError
from app.services.metadata_service import MetadataService
from app.ui.images_search import VisionRelevanceImagesSearchProvider
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache

from conftest import gallery_image_items


class _Database:
    def open(self):
        return self

    def close(self):
        pass


class _Images:
    records = {}

    def __init__(self, _database):
        pass

    def get_image(self, image_id):
        return self.records[image_id]

    def get_image_by_path(self, path):
        target = Path(path)
        for record in self.records.values():
            if Path(record.path) == target:
                return record
        raise KeyError(path)

    def update_tags(self, *_args):
        pass


class _SemanticRepository:
    def __init__(self, _database):
        pass


class _SemanticService:
    def __init__(self, *_args, **_kwargs):
        self.last_search_trace = None

    def search(self, _query, top_k, **_kwargs):
        return [SimpleNamespace(image_id=value) for value in range(1, top_k + 1)]


class _MockRelevance:
    batch_size = 5

    def __init__(self, relevant_ids=(), *, fail_ids=(), retries=0, scores=None):
        self.relevant_ids = set(relevant_ids)
        self.fail_ids = set(fail_ids)
        self.retries = retries
        self.scores = dict(scores or {})
        self.calls = []

    def classify(self, _query, images, cancelled=None):
        ids = tuple(item.image_id for item in images)
        return self._run(ids)

    def match_records(self, _query, records, cancelled=None):
        ids = tuple(int(item["image_id"]) for item in records)
        return self._run(ids)

    def _run(self, ids):
        self.calls.append(ids)
        failed = tuple(value for value in ids if value in self.fail_ids)
        results = tuple(
            RelevanceResult(
                value,
                None if value in self.fail_ids else value in self.relevant_ids,
                1.0,
                unknown_reason="api_failure" if value in self.fail_ids else None,
                relevance_score=(
                    None if value in self.fail_ids
                    else self.scores[value] if value in self.scores
                    else (1.0 if value in self.relevant_ids else 0.0)
                ),
            )
            for value in ids
        )
        return RelevanceRun(
            results=results,
            failed_image_ids=failed,
            request_count=1,
            sent_image_count=0,
            retry_count=self.retries,
            request_attempt_count=1 + self.retries,
            errors=("mock partial failure",) if failed else (),
        )


_MockFactsMatcher = _MockRelevance


def _sample_facts(image_id: int) -> dict:
    return {
        "image_id": image_id,
        "media_type": "screenshot",
        "scene_description": "a stored fact record",
        "environment": "",
        "ui_types": [],
        "entities": [
            {
                "name": "dog",
                "kind": "animal",
                "attributes": [],
                "colors": ["brown"],
                "states": [],
                "posture": "sitting",
                "observed_color_description": "mostly brown",
                "visibility": "visible",
                "identifiability": "clear",
            }
        ],
        "applications": [],
        "activities": [],
        "relationships": [],
        "notable_text": [],
    }


def _provider(monkeypatch, tmp_path, count, relevance, high_relevance=None, facts_ids=None):
    import app.ui.images_search as module

    _Images.records = {
        value: SimpleNamespace(image_id=value, path=str(tmp_path / f"{value}.png"), file_state="present")
        for value in range(1, count + 1)
    }
    monkeypatch.setattr(module, "OCRDatabase", _Database)
    monkeypatch.setattr(module, "OCRRepository", _Images)
    monkeypatch.setattr(module, "SemanticRepository", _SemanticRepository)
    monkeypatch.setattr(module, "SemanticSearchService", _SemanticService)
    if facts_ids is None:
        facts_ids = tuple(range(1, count + 1))
    facts = {image_id: _sample_facts(image_id) for image_id in facts_ids}
    provider = VisionRelevanceImagesSearchProvider(
        relevance_provider=relevance,
        high_relevance_provider=high_relevance or relevance,
        facts_matcher=relevance,
        facts_lookup=lambda image_ids: {image_id: facts[image_id] for image_id in image_ids if image_id in facts},
    )
    monkeypatch.setattr(provider, "_ensure_bundle", lambda: tmp_path)
    candidates = tuple((tmp_path / f"{value}.png", ()) for value in range(1, count + 1))
    return provider, candidates


@pytest.mark.parametrize(
    ("count", "expected_chunks"),
    [(17, [8, 5, 4]), (40, [8, 5, 5, 5, 5, 5, 5, 2]), (41, [8, 5, 5, 5, 5, 5, 5, 2]), (99, [8, 5, 5, 5, 5, 5, 5, 2]), (200, [8, 5, 5, 5, 5, 5, 5, 2])],
)
def test_candidate_chunks_cover_openclip_facts_shortlist(monkeypatch, tmp_path, count, expected_chunks):
    relevance = _MockRelevance()
    provider, candidates = _provider(monkeypatch, tmp_path, count, relevance)
    provider.search_progressive("dog", tmp_path, candidates)
    judged = [item for chunk in relevance.calls for item in chunk]
    assert [len(value) for value in relevance.calls] == expected_chunks
    assert judged == list(range(1, min(count, 40) + 1))
    assert provider.last_run.sent_image_count == 0
    assert provider.last_vision_request_count == 0


def test_shortlist_returns_relevant_in_openclip_order(monkeypatch, tmp_path):
    relevant = set(range(3, 40, 3))
    relevance = _MockRelevance(relevant)
    provider, candidates = _provider(monkeypatch, tmp_path, 200, relevance)
    progress = []
    paths = provider.search_progressive(
        "dog", tmp_path, candidates,
        on_progress=lambda values, checked, total: progress.append(
            ([int(path.stem) for path in values], checked, total)
        ),
    )
    assert [int(path.stem) for path in paths] == sorted(relevant)
    assert [checked for _, checked, _ in progress] == [8, 13, 18, 23, 28, 33, 38, 40]
    assert provider.last_run.sent_image_count == 0


def test_zero_and_one_relevant_complete_without_fallback(monkeypatch, tmp_path):
    for relevant in (set(), {12}):
        relevance = _MockRelevance(relevant)
        provider, candidates = _provider(monkeypatch, tmp_path, 41, relevance)
        paths = provider.search_progressive("dog", tmp_path, candidates)
        assert [int(path.stem) for path in paths] == sorted(relevant)


def test_cancel_stops_unstarted_candidate_chunks(monkeypatch, tmp_path):
    relevance = _MockRelevance(range(1, 41))
    provider, candidates = _provider(monkeypatch, tmp_path, 200, relevance)
    cancelled = {"value": False}
    progress = []

    def on_progress(values, checked, total):
        progress.append((len(values), checked, total))
        cancelled["value"] = True

    paths = provider.search_progressive(
        "dog", tmp_path, candidates, on_progress=on_progress,
        cancelled=lambda: cancelled["value"],
    )
    assert len(relevance.calls) == 1
    assert len(paths) == 8
    assert progress == [(8, 8, 40)]


def test_partial_failure_keeps_other_results_and_retry_stats(monkeypatch, tmp_path):
    relevance = _MockRelevance({1, 12}, fail_ids={2, 3}, retries=1)
    provider, candidates = _provider(monkeypatch, tmp_path, 41, relevance)
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert [int(path.stem) for path in paths] == [1, 12]
    assert provider.last_run.failed_image_ids == (2, 3)
    assert provider.last_run.retry_count == 8
    assert provider.last_run.errors == ("mock partial failure",)


def test_diagnostic_log_connects_openclip_rank_facts_decision_and_final_result(
    monkeypatch, tmp_path,
):
    import app.ui.images_search as module

    relevance = _MockRelevance({2}, fail_ids={3})
    provider, candidates = _provider(monkeypatch, tmp_path, 3, relevance)
    messages = []
    monkeypatch.setattr(
        module.logger, "info",
        lambda message, *args: messages.append(message % args),
    )

    provider.search_progressive("dog", tmp_path, candidates)

    candidate_logs = [
        message for message in messages
        if message.startswith("Meaning-search candidate ")
    ]
    assert len(candidate_logs) == 3
    assert "query='dog'" in candidate_logs[0]
    assert "retrieval_rank=1" in candidate_logs[0]
    assert "search_vision=0" in candidate_logs[0]
    assert "final_result=False" in candidate_logs[0]
    assert "retrieval_rank=2" in candidate_logs[1]
    assert "final_result=True" in candidate_logs[1]
    assert "retrieval_rank=3" in candidate_logs[2]
    assert "final_result=unknown" in candidate_logs[2]


def test_unconfirmed_facts_are_not_final(monkeypatch, tmp_path):
    matcher = _MockRelevance()
    provider, candidates = _provider(monkeypatch, tmp_path, 1, matcher)
    assert provider.search_progressive("object", tmp_path, candidates) == ()


def test_confirmed_facts_are_final(monkeypatch, tmp_path):
    matcher = _MockRelevance({1})
    provider, candidates = _provider(monkeypatch, tmp_path, 1, matcher)
    assert [path.stem for path in provider.search_progressive(
        "object", tmp_path, candidates
    )] == ["1"]


def test_facts_failure_never_accepts_unconfirmed_image(monkeypatch, tmp_path):
    matcher = _MockRelevance({1}, fail_ids={1})
    provider, candidates = _provider(monkeypatch, tmp_path, 1, matcher)
    with pytest.raises(RelevanceProviderError, match="no result was applied"):
        provider.search_progressive("object", tmp_path, candidates)
    result = provider.last_run.results[0]
    assert result.relevant is None
    assert result.relevant is not False


def test_progress_is_emitted_after_facts_confirmation(monkeypatch, tmp_path):
    matcher = _MockRelevance({2})
    provider, candidates = _provider(monkeypatch, tmp_path, 2, matcher)
    progress = []
    provider.search_progressive(
        "object", tmp_path, candidates,
        on_progress=lambda paths, *_: progress.append([path.stem for path in paths]),
    )
    assert progress == [["2"]]


def test_cancel_during_match_discards_its_response(monkeypatch, tmp_path):
    cancelled = {"value": False}

    class CancellingMatcher(_MockRelevance):
        def match_records(self, query, records, cancelled=None):
            result = super().match_records(query, records, cancelled=cancelled)
            cancelled_state["value"] = True
            return result

    cancelled_state = cancelled

    matcher = CancellingMatcher({1})
    provider, candidates = _provider(monkeypatch, tmp_path, 1, matcher)
    progress = []
    paths = provider.search_progressive(
        "object", tmp_path, candidates,
        on_progress=lambda *args: progress.append(args),
        cancelled=lambda: cancelled["value"],
    )
    assert paths == ()
    assert progress == []


def test_images_ui_appends_batches_without_reordering_or_accepting_stale_results(tmp_path):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / "Selected"
    folder.mkdir()
    paths = []
    for value in range(1, 5):
        path = folder / f"{value}.png"
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(path), "PNG")
        paths.append(path)
    page = ImagesPage(
        {"selected_folder": str(folder), "developer_search_mode": "text"},
        MetadataService(), ThumbnailCache(size=32), tmp_path,
        search_provider=lambda *_args: (), semantic_search_provider=lambda *_args: (),
    )
    page.show()
    app.processEvents()
    page._active_search_query = "dog"
    page._search_request_id = 7
    page._progressive_visible_paths[7] = []

    resolved = str(folder.resolve())
    page._progress_unified_search(7, "dog", resolved, (paths[2], paths[0]), 40, 99)
    assert [Path(page._list_widget.item(row).data(Qt.UserRole)) for row in range(2)] == [paths[2], paths[0]]
    page._list_widget.setCurrentRow(0)
    selected = page._get_selected_path()

    page._progress_unified_search(7, "dog", resolved, (paths[2], paths[0], paths[3]), 80, 99)
    assert [Path(page._list_widget.item(row).data(Qt.UserRole)) for row in range(3)] == [paths[2], paths[0], paths[3]]
    assert page._get_selected_path() == selected

    page._progress_unified_search(6, "dog", resolved, (paths[1],), 99, 99)
    page._progress_unified_search(7, "dog", str(tmp_path.resolve()), (paths[1],), 99, 99)
    assert page._list_widget.count() == 3
    page.close()


def _loaded_vision_page(tmp_path, count):
    app = QApplication.instance() or QApplication([])
    folder = tmp_path / f"Selected-{count}"
    folder.mkdir()
    paths = []
    for value in range(1, count + 1):
        path = folder / f"{value}.png"
        image = QImage(2, 2, QImage.Format_RGB32)
        image.fill(Qt.GlobalColor.blue)
        assert image.save(str(path), "PNG")
        paths.append(path)
    page = ImagesPage(
        {"selected_folder": str(folder), "developer_search_mode": "vision_relevance"},
        MetadataService(), ThumbnailCache(size=8), tmp_path,
        search_provider=lambda *_args: (), semantic_search_provider=lambda *_args: (),
    )
    page._load_images()
    assert len(gallery_image_items(page._list_widget)) == count
    return app, page, folder, paths


def _visible_paths(page):
    return [
        Path(page._list_widget.item(row).data(Qt.UserRole))
        for row in range(page._list_widget.count())
    ]


def test_vision_start_immediately_separates_results_from_99_normal_images(
    tmp_path, monkeypatch
):
    _app, page, _folder, _paths = _loaded_vision_page(tmp_path, 99)
    release = threading.Event()
    logged = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.logger.info",
        lambda *values: logged.append(values),
    )

    class BlockingVisionProvider:
        def search_progressive(self, *_args, **_kwargs):
            release.wait(2)
            return ()

    page._owned_vision_search_provider = BlockingVisionProvider()
    page._active_search_query = "dog"
    page._start_unified_search("dog")
    assert page._list_widget.count() == 0
    assert logged[-1][0].startswith("Images-search start")
    assert logged[-1][-1] == "BlockingVisionProvider"
    release.set()
    while page._search_tasks:
        _app.processEvents()
    assert page._list_widget.count() == 0
    page.close()


@pytest.mark.parametrize(
    ("count", "relevant", "expected_counts"),
    [
        (99, {1, 2, 3}, [0, 3, 3, 3]),
        (99, {41, 42}, [0, 0, 2, 2]),
        (99, set(), [0, 0, 0, 0]),
        (200, set(range(3, 153, 3)), [0, 13, 26, 40, 50, 50]),
    ],
)
def test_vision_ui_replay_uses_only_cumulative_judged_relevant_results(
    tmp_path, count, relevant, expected_counts
):
    _app, page, folder, paths = _loaded_vision_page(tmp_path, count)
    page._active_search_query = "dog"
    page._search_request_id = 7
    page._progressive_visible_paths[7] = []
    page._list_widget.clear()  # authoritative empty result at search start
    observed = [0]
    ever_visible = set()
    for end in range(40, count + 40, 40):
        checked = min(end, count)
        judged_relevant = tuple(
            path for path in paths[:checked] if int(path.stem) in relevant
        )
        page._progress_unified_search(
            7, "dog", str(folder.resolve()), judged_relevant, checked, count
        )
        visible = _visible_paths(page)
        observed.append(len(visible))
        ever_visible.update(int(path.stem) for path in visible)
    assert observed == expected_counts
    assert ever_visible <= relevant
    page.close()


def test_vision_final_empty_never_restores_normal_listing(tmp_path):
    _app, page, folder, _paths = _loaded_vision_page(tmp_path, 99)
    page._active_search_query = "dog"
    page._search_request_id = 9
    page._progressive_visible_paths[9] = []
    page._list_widget.clear()
    page._search_tasks[9] = SimpleNamespace(mode="vision_relevance")
    page._finish_unified_search(9, "dog", str(folder.resolve()), (), None)
    assert page._list_widget.count() == 0
    page.close()


def test_ranking_falls_back_to_stored_embedding_model(monkeypatch, tmp_path):
    import app.ui.images_search as module

    _Images.records = {
        1: SimpleNamespace(image_id=1, path=str(tmp_path / "1.png"), file_state="present")
    }
    monkeypatch.setattr(module, "OCRDatabase", _Database)
    monkeypatch.setattr(module, "OCRRepository", _Images)
    monkeypatch.setattr(module, "SemanticRepository", _SemanticRepository)
    monkeypatch.setattr(module, "_installed_semantic_bundle", lambda _key="siglip2": tmp_path)

    class SwitchingService:
        def __init__(self, *_args, **_kwargs):
            self.last_search_trace = None

        def search(self, _query, _top_k, **_kwargs):
            if provider.model_key == "openclip":
                self.last_search_trace = SimpleNamespace(
                    candidate_identities=(
                        SimpleNamespace(model_id="siglip2-base-patch16-224"),
                    )
                )
                return []
            self.last_search_trace = SimpleNamespace(candidate_identities=())
            return [SimpleNamespace(image_id=1)]

    monkeypatch.setattr(module, "SemanticSearchService", SwitchingService)
    relevance = _MockRelevance({1})
    facts = {1: _sample_facts(1)}
    provider = VisionRelevanceImagesSearchProvider(
        relevance_provider=relevance,
        high_relevance_provider=relevance,
        facts_matcher=relevance,
        facts_lookup=lambda image_ids: {image_id: facts[image_id] for image_id in image_ids if image_id in facts},
        model_key="openclip",
    )
    monkeypatch.setattr(provider, "_ensure_bundle", lambda: tmp_path)
    paths = provider.search_progressive("dog", tmp_path, ((tmp_path / "1.png", ()),))
    assert paths == (tmp_path / "1.png",)
    assert provider.model_key == "siglip2"


def test_facts_shortlist_keeps_openclip_rank_one(monkeypatch, tmp_path):
    import app.ui.images_search as module

    names = {1: "test3.jpg"}
    records = {}
    candidates = []
    for image_id in range(1, 9):
        name = names.get(image_id, f"{image_id}.png")
        path = tmp_path / name
        Image.new("RGB", (32, 32), "red").save(path)
        records[image_id] = SimpleNamespace(
            image_id=image_id, path=str(path), file_state="present",
        )
        candidates.append((path, ()))
    _Images.records = records
    monkeypatch.setattr(module, "OCRDatabase", _Database)
    monkeypatch.setattr(module, "OCRRepository", _Images)
    monkeypatch.setattr(module, "SemanticRepository", _SemanticRepository)
    monkeypatch.setattr(module, "SemanticSearchService", _SemanticService)
    matcher = _MockRelevance({1})
    facts = {image_id: _sample_facts(image_id) for image_id in range(1, 9)}
    provider = VisionRelevanceImagesSearchProvider(
        facts_matcher=matcher,
        facts_lookup=lambda image_ids: {image_id: facts[image_id] for image_id in image_ids if image_id in facts},
    )
    monkeypatch.setattr(provider, "_ensure_bundle", lambda: tmp_path)

    paths = provider.search_progressive("anime", tmp_path, tuple(candidates))
    assert [path.name for path in paths] == ["test3.jpg"]
    assert matcher.calls[0] == tuple(range(1, 9))
    assert provider.last_run.sent_image_count == 0
    assert provider.last_vision_request_count == 0
    by_id = {item.image_id: item for item in provider.last_run.results}
    assert by_id[1].relevant is True


def test_cancel_during_facts_match_does_not_progress(monkeypatch, tmp_path):
    cancelled = {"value": False}

    class CancellingMatcher(_MockRelevance):
        def match_records(self, query, records, cancelled=None):
            result = super().match_records(query, records, cancelled=cancelled)
            cancelled_state["value"] = True
            return result

    cancelled_state = cancelled
    matcher = CancellingMatcher({1, 2})
    provider, candidates = _provider(monkeypatch, tmp_path, 2, matcher)
    progress = []
    paths = provider.search_progressive(
        "dog", tmp_path, candidates,
        on_progress=lambda *args: progress.append(args),
        cancelled=lambda: cancelled["value"],
    )
    assert paths == ()
    assert progress == []
    assert provider.last_run.sent_image_count == 0
    by_id = {item.image_id: item for item in provider.last_run.results}
    assert by_id == {}


def test_product_facts_search_sends_no_images():
    from app.image_facts.search import ImageFactsSearchMatcher
    from app.image_facts.schema import SEARCH_PROMPT, SEARCH_PROMPT_VERSION

    matcher = ImageFactsSearchMatcher(api_key="test")
    assert matcher.system_prompt == SEARCH_PROMPT
    assert matcher.prompt_version == SEARCH_PROMPT_VERSION
    assert matcher.unknown_retries == 0
    assert matcher.batch_size >= 8
    with pytest.raises(RuntimeError, match="match_records"):
        matcher.classify("dog", [])


def test_final_ranking_uses_relevance_score_then_embedding_rank(monkeypatch, tmp_path):
    scores = {1: 0.4, 2: 0.95, 3: 0.4}
    relevance = _MockRelevance({1, 2, 3}, scores=scores)
    provider, candidates = _provider(monkeypatch, tmp_path, 3, relevance)
    paths = provider.search_progressive("icon", tmp_path, candidates)
    assert [int(path.stem) for path in paths] == [2, 1, 3]
    by_id = {item.image_id: item for item in provider.last_run.results}
    assert by_id[2].relevance_score == 0.95
    assert by_id[2].confidence == 1.0
    assert by_id[1].relevance_score == 0.4


def test_incidental_match_ranks_below_primary_match(monkeypatch, tmp_path):
    incidental_first = 1
    primary = 2
    relevance = _MockRelevance(
        {incidental_first, primary},
        scores={incidental_first: 0.2, primary: 0.93},
    )
    provider, candidates = _provider(monkeypatch, tmp_path, 2, relevance)
    paths = provider.search_progressive("icon", tmp_path, candidates)
    assert [int(path.stem) for path in paths] == [primary, incidental_first]


def test_unknown_result_is_not_converted_to_score_zero_in_ranking(monkeypatch, tmp_path):
    relevance = _MockRelevance({2}, fail_ids={1}, scores={2: 0.8})
    provider, candidates = _provider(monkeypatch, tmp_path, 2, relevance)
    paths = provider.search_progressive("dog", tmp_path, candidates)
    assert [int(path.stem) for path in paths] == [2]
    by_id = {item.image_id: item for item in provider.last_run.results}
    assert by_id[1].relevant is None
    assert by_id[1].relevance_score is None
    assert 1 not in {int(path.stem) for path in paths}
