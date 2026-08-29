import json
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import (
    ImagesPage,
    LEGACY_MEANING_MODES,
    USER_FACING_MEANING_MODE,
    USER_FACING_TEXT_MODE,
)
from app.semantic.catalog import DEFAULT_MODEL_KEY
from app.ui.pages.settings_page import SettingsPage
from app.ui.images_search import (
    SemanticImagesSearchProvider,
    VisionRelevanceImagesSearchProvider,
)
from app.ui.main_window import MainWindow
from app.utils.thumbnail_cache import ThumbnailCache


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path) -> None:
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def _wait(page: ImagesPage) -> None:
    elapsed = 0
    while page._search_tasks and elapsed < 3000:
        QTest.qWait(20)
        elapsed += 20
    assert not page._search_tasks


def test_images_routes_each_mode_without_cross_contamination(tmp_path, monkeypatch):
    _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    image_path = folder / "one.png"
    _png(image_path)
    calls = []

    def provider(name):
        def search(query, selected_folder, candidates):
            calls.append((name, query, selected_folder, len(candidates)))
            return (image_path,)
        return search

    monkeypatch.setattr(
        "app.ui.pages.images_page.search_indexed_images", provider("text")
    )
    config = {
        "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
        "current_folder": "Capture", "save_folder": "Capture",
        "developer_search_mode": "hybrid",
    }
    page = ImagesPage(
        config, MetadataService(), ThumbnailCache(size=32), tmp_path,
        search_provider=provider("hybrid"),
        semantic_search_provider=provider("semantic"),
    )
    page._owned_vision_search_provider = provider("vision_relevance")
    page.show()
    page._search_input.setText("query")
    page._on_search()
    _wait(page)
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    assert calls and {call[0] for call in calls} == {"vision_relevance"}

    calls.clear()
    config["developer_search_mode"] = "text"
    page.sync_search_mode_from_config()
    _wait(page)
    assert page._active_search_mode == USER_FACING_TEXT_MODE
    assert calls and {call[0] for call in calls} == {"text"}

    calls.clear()
    config["developer_search_mode"] = "semantic"
    page.sync_search_mode_from_config()
    _wait(page)
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    assert calls and {call[0] for call in calls} == {"vision_relevance"}

    calls.clear()
    page._search_input.clear()
    page._on_search()
    assert calls == []
    page.close()


def test_settings_hides_developer_search_controls_and_images_persist_mode(tmp_path, monkeypatch):
    _app()
    config = {
        "window_width": 1600, "window_height": 900,
        "current_folder": "Capture", "save_folder": "Capture",
        "selected_folder": str(tmp_path),
        "screenshot_dir": str(tmp_path),
    }
    saved = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.save_config", lambda value: saved.append(dict(value))
    )
    settings = SettingsPage(config, tmp_path)
    assert settings.findChild(QComboBox, "developerSearchMode") is None
    assert settings.findChild(QComboBox, "developerSemanticModel") is None
    assert not any(
        label.objectName() == "aboutBrandTitle" for label in settings.findChildren(QLabel)
    )

    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=32), tmp_path)
    assert page._search_mode_combo.isHidden()
    assert page._active_search_mode == USER_FACING_TEXT_MODE
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    assert config["developer_search_mode"] == USER_FACING_MEANING_MODE
    assert saved[-1]["developer_search_mode"] == USER_FACING_MEANING_MODE
    page.close()


def test_settings_vision_selection_reaches_main_window_images_provider(
    tmp_path, monkeypatch
):
    _app()
    folder = tmp_path / "screenshots" / "Default"
    folder.mkdir(parents=True)
    config = {
        "screenshot_dir": str(tmp_path / "screenshots"),
        "current_folder": "Default", "save_folder": "Default",
        "selected_folder": str(folder),
        "window_width": 1000, "window_height": 700,
        "window_title": "Capixe", "developer_search_mode": "semantic",
    }
    monkeypatch.setattr("app.ui.pages.settings_page.save_config", lambda _value: None)
    window = MainWindow(config)
    images = window._images_page
    assert images._active_search_mode == USER_FACING_MEANING_MODE
    assert isinstance(
        images._provider_for_mode(images._active_search_mode),
        VisionRelevanceImagesSearchProvider,
    )

    images._search_mode_combo.setCurrentIndex(
        images._search_mode_combo.findData("semantic")
    )
    assert config["developer_search_mode"] == "semantic"
    assert window._images_page._provider_for_mode("semantic") is window._images_page._semantic_search_provider
    window.close()


def test_vision_mode_survives_disk_reload_and_routes_recreated_window(
    tmp_path, monkeypatch
):
    """Cover the real persistence boundary without invoking the Vision API."""
    import app.config as config_module
    from app.paths import clear_path_overrides, set_path_overrides
    import app.ui.pages.images_page as images_page_module

    _app()
    app_data = tmp_path / "appdata" / "Capixe"
    screenshots = tmp_path / "screenshots"
    selected = screenshots / "Default"
    selected.mkdir(parents=True)
    _png(selected / "dog.png")
    set_path_overrides(
        app_data_dir=app_data,
        local_app_data_dir=tmp_path / "localappdata" / "Capixe",
        default_screenshot_root=screenshots,
        legacy_install_root=tmp_path / "isolated-install",
        resource_root=Path(__file__).resolve().parent,
    )
    config_module.reset_migration_flag_for_tests()
    first_window = None
    restarted_window = None
    try:
        initial = config_module.build_default_config()
        initial.update({
            "selected_folder": str(selected),
            "current_folder": "Default",
            "save_folder": "Default",
            "onboarding_completed": True,
        })
        config_module.save_config(initial)

        first_config = config_module.load_config()
        first_window = MainWindow(first_config)
        first_window._images_page._search_mode_combo.setCurrentIndex(
            first_window._images_page._search_mode_combo.findData("vision_relevance")
        )

        persisted = json.loads(
            (app_data / "config.json").read_text(encoding="utf-8")
        )
        assert persisted["developer_search_mode"] == "vision_relevance"
        first_window.close()
        first_window = None

        # A new dict and a new MainWindow model an application restart.
        restarted_config = config_module.load_config()
        assert restarted_config is not first_config
        restarted_window = MainWindow(restarted_config)
        restarted_images = restarted_window._images_page
        assert restarted_config["developer_search_mode"] == "vision_relevance"
        assert restarted_images._active_search_mode == "vision_relevance"
        provider = restarted_images._provider_for_mode(
            restarted_images._active_search_mode
        )
        # Vision currently reuses Semantic's infrastructure via inheritance;
        # routing must still select the exact Vision provider implementation.
        assert type(provider) is VisionRelevanceImagesSearchProvider
        assert provider is not restarted_images._semantic_search_provider

        log_calls = []
        monkeypatch.setattr(images_page_module.logger, "info", lambda *args: log_calls.append(args))
        monkeypatch.setattr(restarted_images._search_pool, "start", lambda _task: None)
        restarted_images._start_unified_search("dog")
        start_log = next(
            args for args in log_calls
            if args and str(args[0]).startswith("Images-search start")
        )
        assert start_log[3:6] == (
            "vision_relevance",
            "vision_relevance",
            "VisionRelevanceImagesSearchProvider",
        )
    finally:
        if restarted_window is not None:
            restarted_window.close()
        if first_window is not None:
            first_window.close()
        clear_path_overrides()
        config_module.reset_migration_flag_for_tests()

def test_semantic_provider_requests_all_folder_candidates_and_logs_scores(tmp_path, monkeypatch):
    import app.ui.images_search as module

    captured = []
    logged = []

    class Database:
        def open(self): return self
        def close(self): pass
    class Images:
        def __init__(self, _database): pass
        def get_image(self, image_id):
            return SimpleNamespace(
                image_id=image_id, file_state="present",
                path=str(tmp_path / f"{image_id}.png"),
            )
    class SemanticService:
        def __init__(self, *_args, **_kwargs):
            self.last_search_trace = None
        def search(self, query, top_k, *, folder_path):
            captured.append((query, top_k, folder_path))
            return [SimpleNamespace(image_id=index, similarity=1 - index / 100)
                    for index in range(min(top_k, 7))]

    monkeypatch.setattr(module, "OCRDatabase", Database)
    monkeypatch.setattr(module, "OCRRepository", Images)
    monkeypatch.setattr(module, "SemanticRepository", lambda _database: object())
    monkeypatch.setattr(module, "SemanticSearchService", SemanticService)
    monkeypatch.setattr(module.logger, "info", lambda *args: logged.append(args))

    provider = SemanticImagesSearchProvider()
    provider.bundle_dir = tmp_path
    candidates = tuple((tmp_path / f"{index}.png", ()) for index in range(7))
    assert len(provider("desktop", tmp_path, candidates)) == 7
    assert captured[-1][1] == 7
    assert logged[-1][0].startswith("Semantic-only result query=%r rank=%d")
    assert logged[0][1:3] == ("desktop", 1)


def test_invalid_persisted_mode_falls_back_to_vision_relevance(tmp_path):
    _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    config = {
        "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
        "current_folder": "Capture", "save_folder": "Capture",
        "developer_search_mode": "unknown",
    }
    page = ImagesPage(
        config, MetadataService(), ThumbnailCache(size=32), tmp_path,
        search_provider=lambda *_: (), semantic_search_provider=lambda *_: (),
    )
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    page.close()


def test_meaning_intent_uses_vision_relevance_and_keeps_text(tmp_path, monkeypatch):
    _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    image_path = folder / "one.png"
    _png(image_path)
    saved = []
    monkeypatch.setattr(
        "app.ui.pages.images_page.save_config", lambda value: saved.append(dict(value))
    )
    config = {
        "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
        "current_folder": "Capture", "save_folder": "Capture",
        "developer_search_mode": "semantic",
    }
    page = ImagesPage(config, MetadataService(), ThumbnailCache(size=32), tmp_path)
    page.show()
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    assert isinstance(
        page._provider_for_mode(page._active_search_mode),
        VisionRelevanceImagesSearchProvider,
    )

    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    assert page._active_search_mode == USER_FACING_TEXT_MODE
    assert config["developer_search_mode"] == USER_FACING_TEXT_MODE
    assert page._provider_for_mode(page._active_search_mode) is page._provider_for_mode("text")

    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    assert config["developer_search_mode"] == USER_FACING_MEANING_MODE
    assert isinstance(
        page._provider_for_mode(page._active_search_mode),
        VisionRelevanceImagesSearchProvider,
    )

    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    assert page._active_search_mode == USER_FACING_MEANING_MODE
    assert config["developer_search_mode"] == USER_FACING_MEANING_MODE
    started = []
    page._start_unified_search = lambda *_args, **_kwargs: started.append("search")
    page._search_input.setText("dog")
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_TEXT_MODE)
    )
    page._search_mode_combo.setCurrentIndex(
        page._search_mode_combo.findData(USER_FACING_MEANING_MODE)
    )
    assert started == []
    page.close()


def test_legacy_meaning_configs_use_vision_relevance(tmp_path):
    _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for legacy in sorted(LEGACY_MEANING_MODES):
        config = {
            "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
            "current_folder": "Capture", "save_folder": "Capture",
            "developer_search_mode": legacy,
        }
        page = ImagesPage(
            config, MetadataService(), ThumbnailCache(size=32), tmp_path,
            search_provider=lambda *_: (), semantic_search_provider=lambda *_: (),
        )
        assert page._configured_search_mode() == USER_FACING_MEANING_MODE
        assert page._active_search_mode == USER_FACING_MEANING_MODE
        assert isinstance(
            page._provider_for_mode(page._active_search_mode),
            VisionRelevanceImagesSearchProvider,
        )
        page.close()


def test_legacy_semantic_config_survives_restart_as_vision_relevance(
    tmp_path, monkeypatch
):
    import app.config as config_module
    from app.paths import clear_path_overrides, set_path_overrides
    import app.ui.pages.images_page as images_page_module

    _app()
    app_data = tmp_path / "appdata" / "Capixe"
    screenshots = tmp_path / "screenshots"
    selected = screenshots / "Default"
    selected.mkdir(parents=True)
    _png(selected / "dog.png")
    set_path_overrides(
        app_data_dir=app_data,
        local_app_data_dir=tmp_path / "localappdata" / "Capixe",
        default_screenshot_root=screenshots,
        legacy_install_root=tmp_path / "isolated-install",
        resource_root=Path(__file__).resolve().parent,
    )
    config_module.reset_migration_flag_for_tests()
    first_window = None
    restarted_window = None
    try:
        initial = config_module.build_default_config()
        initial.update({
            "selected_folder": str(selected),
            "current_folder": "Default",
            "save_folder": "Default",
            "onboarding_completed": True,
            "developer_search_mode": "semantic",
        })
        config_module.save_config(initial)

        first_config = config_module.load_config()
        first_window = MainWindow(first_config)
        first_images = first_window._images_page
        assert first_images._active_search_mode == USER_FACING_MEANING_MODE
        assert isinstance(
            first_images._provider_for_mode(first_images._active_search_mode),
            VisionRelevanceImagesSearchProvider,
        )
        first_window.close()
        first_window = None

        restarted_config = config_module.load_config()
        restarted_window = MainWindow(restarted_config)
        restarted_images = restarted_window._images_page
        assert restarted_images._active_search_mode == USER_FACING_MEANING_MODE
        provider = restarted_images._provider_for_mode(
            restarted_images._active_search_mode
        )
        assert type(provider) is VisionRelevanceImagesSearchProvider

        log_calls = []
        monkeypatch.setattr(images_page_module.logger, "info", lambda *args: log_calls.append(args))
        monkeypatch.setattr(restarted_images._search_pool, "start", lambda _task: None)
        restarted_images._start_unified_search("dog")
        start_log = next(
            args for args in log_calls
            if args and str(args[0]).startswith("Images-search start")
        )
        assert start_log[3:6] == (
            USER_FACING_MEANING_MODE,
            USER_FACING_MEANING_MODE,
            "VisionRelevanceImagesSearchProvider",
        )
    finally:
        if restarted_window is not None:
            restarted_window.close()
        if first_window is not None:
            first_window.close()
        clear_path_overrides()
        config_module.reset_migration_flag_for_tests()


def test_legacy_semantic_result_limit_is_removed_on_merge_and_save(tmp_path, monkeypatch):
    import app.config as config_module

    config = {
        "developer_semantic_result_limit": 5,
        "screenshot_dir": str(tmp_path),
        "save_folder": "Capture",
    }
    assert config_module._merge_defaults(config)
    assert "developer_semantic_result_limit" not in config

    config["developer_semantic_result_limit"] = "all"
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "get_config_path", lambda: path)
    config_module.save_config(config)
    assert "developer_semantic_result_limit" not in path.read_text(encoding="utf-8")


def test_model_switch_atomically_replaces_bundle_and_worker(tmp_path, monkeypatch):
    import app.ui.images_search as module

    stopped = []

    class Worker:
        def __init__(self, config):
            self.config = config

        def shutdown(self):
            stopped.append(self)

    monkeypatch.setattr(module, "SemanticWorkerClient", Worker)
    provider = module.SemanticImagesSearchProvider(model_key="siglip2")
    old_worker = provider.worker
    provider.bundle_dir = tmp_path / "siglip"

    assert provider.set_model_key("openclip") is True
    assert provider.model_key == "openclip"
    assert provider.bundle_dir is None
    assert provider.worker is not old_worker
    assert provider.worker.config.bundle_dir is None

    for _ in range(100):
        if stopped:
            break
        QTest.qWait(10)
    assert stopped == [old_worker]


def test_meaning_search_uses_analysis_model_instead_of_hardcoded_openclip(tmp_path):
    _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    config = {
        "selected_folder": str(folder), "screenshot_dir": str(tmp_path),
        "current_folder": "Capture", "save_folder": "Capture",
    }
    page = ImagesPage(
        config, MetadataService(), ThumbnailCache(size=32), tmp_path,
        search_provider=lambda *_: (), semantic_search_provider=lambda *_: (),
    )
    assert page._owned_vision_search_provider.model_key == DEFAULT_MODEL_KEY
    page.close()

    config["developer_semantic_model"] = "openclip"
    page = ImagesPage(
        config, MetadataService(), ThumbnailCache(size=32), tmp_path,
        search_provider=lambda *_: (), semantic_search_provider=lambda *_: (),
    )
    assert page._owned_vision_search_provider.model_key == "openclip"
    page.sync_search_mode_from_config(rerun=False)
    config["developer_semantic_model"] = "siglip2"
    page.sync_search_mode_from_config(rerun=False)
    assert page._owned_vision_search_provider.model_key == "siglip2"
    page.close()
