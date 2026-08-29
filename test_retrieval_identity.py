import json
from pathlib import Path

import pytest

import app.config as config_module
from app.config import (
    DEFAULT_CONFIG,
    _migrate_official_retrieval_identity,
    load_config,
    reset_migration_flag_for_tests,
)
from app.paths import clear_path_overrides, set_path_overrides
from app.semantic.catalog import (
    DEFAULT_MODEL_KEY,
    LEGACY_OFFICIAL_MODEL_KEYS,
    MODEL_IDS,
    OPENCLIP_BUNDLE_VERSION,
    OPENCLIP_MODEL_KEY,
    OPENCLIP_PIPELINE_VERSION,
    OPENCLIP_REVISION,
    SIGLIP_MODEL_KEY,
    bundle_version_for_key,
    model_id_for_key,
    normalize_model_key,
)
from app.semantic.query_embedding import (
    DEFAULT_QUERY_EMBEDDING,
    QUERY_EMBEDDING_RAW,
    normalize_query_embedding_method,
    query_texts,
)

OFFICIAL_MODEL_ID = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"


@pytest.fixture
def isolated_config(tmp_path: Path):
    app_data = tmp_path / "AppDataRoaming" / "Capixe"
    set_path_overrides(
        app_data_dir=app_data,
        local_app_data_dir=tmp_path / "AppDataLocal" / "Capixe",
        default_screenshot_root=tmp_path / "Pictures" / "Capixe",
        legacy_install_root=tmp_path / "LegacyInstall",
        resource_root=tmp_path / "LegacyInstall",
    )
    reset_migration_flag_for_tests()
    yield app_data
    clear_path_overrides()
    reset_migration_flag_for_tests()


def _write_existing_config(app_data: Path, payload: dict) -> Path:
    path = app_data / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _persisted(app_data: Path) -> dict:
    return json.loads((app_data / "config.json").read_text(encoding="utf-8"))


def _log_text(calls: list) -> str:
    parts = []
    for args in calls:
        if not args:
            continue
        template = str(args[0])
        try:
            parts.append(template % args[1:])
        except (TypeError, ValueError):
            parts.append(" ".join(str(value) for value in args))
    return "\n".join(parts)


def test_official_retrieval_identity_matches_config_and_catalog():
    assert DEFAULT_MODEL_KEY == OPENCLIP_MODEL_KEY
    assert DEFAULT_CONFIG["developer_semantic_model"] == DEFAULT_MODEL_KEY
    assert DEFAULT_CONFIG["developer_query_embedding"] == QUERY_EMBEDDING_RAW
    assert DEFAULT_QUERY_EMBEDDING == QUERY_EMBEDDING_RAW
    assert model_id_for_key(DEFAULT_MODEL_KEY) == OFFICIAL_MODEL_ID
    assert MODEL_IDS[DEFAULT_MODEL_KEY] == OFFICIAL_MODEL_ID
    assert bundle_version_for_key(DEFAULT_MODEL_KEY) == OPENCLIP_BUNDLE_VERSION
    assert OPENCLIP_REVISION == "1a25a446712ba5ee05982a381eed697ef9b435cf"
    assert OPENCLIP_PIPELINE_VERSION == 2
    assert SIGLIP_MODEL_KEY in LEGACY_OFFICIAL_MODEL_KEYS


def test_query_embedding_has_no_per_query_product_switch():
    from app.semantic.query_embedding import QUERY_EMBEDDING_TEMPLATE_ENSEMBLE

    for query in ("dog", "icon", "anime", "login screen"):
        assert query_texts(query, QUERY_EMBEDDING_RAW) == (query,)
        assert query_texts(query, QUERY_EMBEDDING_TEMPLATE_ENSEMBLE) == (
            query,
            f"an image of {query}",
            f"a screenshot related to {query}",
        )


def test_legacy_siglip2_identity_migrates_in_memory_and_is_idempotent():
    config = {
        "developer_semantic_model": "siglip2",
        "capture_mode": "fullscreen",
        "show_save_notification": False,
        "window_width": 1280,
    }
    original_keys = set(config)
    assert _migrate_official_retrieval_identity(config) is True
    assert config["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert config["capture_mode"] == "fullscreen"
    assert config["show_save_notification"] is False
    assert config["window_width"] == 1280
    assert set(config) == original_keys
    assert _migrate_official_retrieval_identity(config) is False
    assert config["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert config["capture_mode"] == "fullscreen"


def test_already_openclip_identity_is_not_rewritten():
    config = {
        "developer_semantic_model": "openclip",
        "developer_query_embedding": "raw",
        "capture_mode": "region",
    }
    snapshot = dict(config)
    assert _migrate_official_retrieval_identity(config) is False
    assert config == snapshot


def test_load_config_migrates_siglip2_and_keeps_other_settings(
    isolated_config, monkeypatch, tmp_path
):
    selected = tmp_path / "Library"
    selected.mkdir()
    _write_existing_config(
        isolated_config,
        {
            "screenshot_dir": str(selected),
            "selected_folder": str(selected),
            "save_folder": "Capture",
            "current_folder": "Capture",
            "window_width": 1280,
            "window_height": 720,
            "window_size_default_version": 7,
            "onboarding_completed": True,
            "developer_search_mode": "vision_relevance",
            "developer_semantic_model": "siglip2",
            "capture_mode": "fullscreen",
            "show_save_notification": False,
            "filename_template": "{date}",
        },
    )
    log_calls = []
    monkeypatch.setattr(
        config_module.logger, "info", lambda *args, **_kwargs: log_calls.append(args)
    )

    loaded = load_config()
    logs = _log_text(log_calls)

    assert loaded["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert loaded["developer_query_embedding"] == QUERY_EMBEDDING_RAW
    assert loaded["capture_mode"] == "fullscreen"
    assert loaded["show_save_notification"] is False
    assert loaded["filename_template"] == "{date}"
    assert loaded["window_width"] == 1280
    assert loaded["window_height"] == 720
    assert loaded["developer_search_mode"] == "vision_relevance"
    assert loaded["onboarding_completed"] is True

    persisted = _persisted(isolated_config)
    assert persisted["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert persisted["developer_query_embedding"] == QUERY_EMBEDDING_RAW
    assert persisted["capture_mode"] == "fullscreen"
    assert persisted["filename_template"] == "{date}"

    assert normalize_model_key(loaded["developer_semantic_model"]) == OPENCLIP_MODEL_KEY
    assert model_id_for_key(loaded["developer_semantic_model"]) == OFFICIAL_MODEL_ID
    assert normalize_query_embedding_method(loaded["developer_query_embedding"]) == QUERY_EMBEDDING_RAW
    assert query_texts("dog", loaded["developer_query_embedding"]) == ("dog",)

    assert "Migrated Meaning retrieval identity from developer_semantic_model=siglip2" in logs
    assert f"to {OPENCLIP_MODEL_KEY}" in logs
    assert OFFICIAL_MODEL_ID in logs
    assert f"Meaning retrieval identity model={OPENCLIP_MODEL_KEY} model_id={OFFICIAL_MODEL_ID} query_embedding={QUERY_EMBEDDING_RAW}" in logs


def test_load_config_leaves_openclip_users_unchanged(isolated_config, monkeypatch, tmp_path):
    selected = tmp_path / "Library"
    selected.mkdir()
    _write_existing_config(
        isolated_config,
        {
            "screenshot_dir": str(selected),
            "selected_folder": str(selected),
            "save_folder": "Capture",
            "current_folder": "Capture",
            "window_width": 1400,
            "window_height": 800,
            "window_size_default_version": 7,
            "onboarding_completed": True,
            "developer_search_mode": "vision_relevance",
            "developer_semantic_model": "openclip",
            "developer_query_embedding": "raw",
            "capture_mode": "region",
            "show_save_notification": True,
            "filename_template": "{date}_{time}",
        },
    )
    log_calls = []
    monkeypatch.setattr(
        config_module.logger, "info", lambda *args, **_kwargs: log_calls.append(args)
    )

    loaded = load_config()
    logs = _log_text(log_calls)

    assert loaded["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert loaded["developer_query_embedding"] == QUERY_EMBEDDING_RAW
    assert loaded["capture_mode"] == "region"
    assert loaded["window_width"] == 1400
    assert loaded["filename_template"] == "{date}_{time}"
    assert "Migrated Meaning retrieval identity" not in logs
    assert f"Meaning retrieval identity model={OPENCLIP_MODEL_KEY} model_id={OFFICIAL_MODEL_ID} query_embedding={QUERY_EMBEDDING_RAW}" in logs


def test_load_config_retrieval_identity_migration_is_idempotent(isolated_config, tmp_path):
    selected = tmp_path / "Library"
    selected.mkdir()
    _write_existing_config(
        isolated_config,
        {
            "screenshot_dir": str(selected),
            "selected_folder": str(selected),
            "save_folder": "Capture",
            "window_width": 1280,
            "window_height": 720,
            "window_size_default_version": 7,
            "onboarding_completed": True,
            "developer_semantic_model": "siglip2",
            "capture_mode": "fullscreen",
        },
    )

    first = load_config()
    second = load_config()
    persisted = _persisted(isolated_config)

    assert first["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert second["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert persisted["developer_semantic_model"] == OPENCLIP_MODEL_KEY
    assert first["capture_mode"] == second["capture_mode"] == "fullscreen"
    assert first["developer_query_embedding"] == second["developer_query_embedding"] == QUERY_EMBEDDING_RAW
    assert model_id_for_key(second["developer_semantic_model"]) == OFFICIAL_MODEL_ID
    assert query_texts("icon", second["developer_query_embedding"]) == ("icon",)
