"""Official prototype build resolves Auth without logging secret bodies."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.auth.config import (
    AUTH_LOCAL_NAME,
    classify_publishable_key,
    classify_supabase_url,
    describe_auth_config,
    load_auth_client_config,
)

_BUILD_PATH = Path(__file__).resolve().parent / "tools" / "build_official_prototype.py"
_SPEC = importlib.util.spec_from_file_location("capixe_official_prototype_build", _BUILD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_build = importlib.util.module_from_spec(_SPEC)
sys.modules["capixe_official_prototype_build"] = _build
_SPEC.loader.exec_module(_build)

ALLOW_UNCONFIGURED_ENV = _build.ALLOW_UNCONFIGURED_ENV
OFFICIAL_DIST_NAME = _build.OFFICIAL_DIST_NAME
UNCONFIGURED_DIST_NAME = _build.UNCONFIGURED_DIST_NAME
OfficialBuildError = _build.OfficialBuildError
inspect_auth_source_file = _build.inspect_auth_source_file
inspect_packaged_build_identity = _build.inspect_packaged_build_identity
inspect_packaged_openclip = _build.inspect_packaged_openclip
inspect_source_openclip = _build.inspect_source_openclip
copy_official_openclip_bundle = _build.copy_official_openclip_bundle
prepare_spec_auth_source = _build.prepare_spec_auth_source
resolve_public_auth = _build.resolve_public_auth
run_source_preflight = _build.run_source_preflight
write_bundled_auth_source = _build.write_bundled_auth_source
write_bundled_build_info = _build.write_bundled_build_info
finalize_packaged_build_info = _build.finalize_packaged_build_info
conflicting_exe_paths = _build.conflicting_exe_paths
ResolvedPublicAuth = _build.ResolvedPublicAuth
BUNDLED_BUILD_INFO_REL = _build.BUNDLED_BUILD_INFO_REL
OFFICIAL_EXE_REL = _build.OFFICIAL_EXE_REL
PACKAGED_OPENCLIP_REL = _build.PACKAGED_OPENCLIP_REL
VERIFIED_OPENCLIP_REL = _build.VERIFIED_OPENCLIP_REL
REQUIRED_OPENCLIP_FILES = _build.REQUIRED_OPENCLIP_FILES


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_tiny_openclip_bundle(root: Path) -> Path:
    """Minimal load_bundle()-valid OpenCLIP identity for official-build unit tests."""
    import hashlib

    from app.semantic.catalog import (
        MODEL_IDS,
        OPENCLIP_BUNDLE_VERSION,
        OPENCLIP_MODEL_KEY,
        OPENCLIP_PIPELINE_VERSION,
        OPENCLIP_REVISION,
    )

    files = {
        "image_encoder.onnx": b"tiny-image",
        "text_encoder.onnx": b"tiny-text",
        "bpe_simple_vocab_16e6.txt.gz": b"tiny-bpe",
        "open_clip_config.json": b"{}",
        "preprocessor_config.json": b"{}",
        "OPEN_CLIP_LICENSE.txt": b"MIT license text",
        "NOTICE.txt": b"model notice",
    }
    roles = {
        "image_encoder.onnx": "image_encoder",
        "text_encoder.onnx": "text_encoder",
        "bpe_simple_vocab_16e6.txt.gz": "tokenizer",
        "open_clip_config.json": "model_config",
        "preprocessor_config.json": "preprocess_config",
        "OPEN_CLIP_LICENSE.txt": "license",
        "NOTICE.txt": "notice",
    }
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, payload in files.items():
        (root / name).write_bytes(payload)
        entries.append(
            {
                "role": roles[name],
                "path": name,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "manifest_schema_version": 1,
        "bundle_version": OPENCLIP_BUNDLE_VERSION,
        "model_id": MODEL_IDS[OPENCLIP_MODEL_KEY],
        "revision": OPENCLIP_REVISION,
        "embedding": {"dimension": 512, "dtype": "float32", "normalized": True},
        "image": {"width": 224, "height": 224},
        "text": {"max_length": 77},
        "runtime": {
            "name": "onnxruntime",
            "minimum_version": "1.28.0",
            "providers": ["CPUExecutionProvider"],
        },
        "pipeline_version": OPENCLIP_PIPELINE_VERSION,
        "files": entries,
        "total_size_bytes": sum(item["size_bytes"] for item in entries),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root


def test_resolve_prefers_env_over_empty_template(tmp_path, monkeypatch):
    _write_json(
        tmp_path / "resources" / "auth-source.json",
        {"supabase_url": "", "publishable_key": ""},
    )
    env = {
        "CAPIXE_SUPABASE_URL": "https://example.supabase.co",
        "CAPIXE_SUPABASE_PUBLISHABLE_KEY": "eyJhbGciOiJub25lIn0.eyJyb2xlIjoiYW5vbiJ9.",
    }
    resolved = resolve_public_auth(tmp_path, environ=env, allow_cli=False)
    assert resolved.configured is True
    assert resolved.source == "env"
    assert resolved.supabase_url == "https://example.supabase.co"


def test_resolve_uses_local_file_not_empty_template(tmp_path):
    _write_json(
        tmp_path / "resources" / "auth-source.json",
        {"supabase_url": "", "publishable_key": ""},
    )
    _write_json(
        tmp_path / "resources" / AUTH_LOCAL_NAME,
        {
            "supabase_url": "https://local.supabase.co",
            "publishable_key": "sb_publishable_test_key",
        },
    )
    resolved = resolve_public_auth(tmp_path, environ={}, allow_cli=False)
    assert resolved.configured is True
    assert resolved.source == "local_file"
    assert resolved.supabase_url == "https://local.supabase.co"


def test_resolve_skips_provider_secret_and_stays_unconfigured(tmp_path):
    _write_json(
        tmp_path / "resources" / "auth-source.json",
        {"supabase_url": "https://file.supabase.co", "publishable_key": "sk-test-not-a-real-key"},
    )
    resolved = resolve_public_auth(
        tmp_path,
        environ={
            "CAPIXE_SUPABASE_URL": "https://env.supabase.co",
            "CAPIXE_SUPABASE_PUBLISHABLE_KEY": "sk-test-not-a-real-key",
        },
        allow_cli=False,
    )
    assert resolved.configured is False
    assert resolved.source == "none"


def test_prepare_spec_refuses_unconfigured_official_dist(tmp_path):
    _write_json(
        tmp_path / "resources" / "auth-source.json",
        {"supabase_url": "", "publishable_key": ""},
    )
    with pytest.raises(OfficialBuildError):
        prepare_spec_auth_source(tmp_path, environ={})


def test_prepare_spec_sends_unconfigured_build_off_official_dist(tmp_path):
    _write_json(
        tmp_path / "resources" / "auth-source.json",
        {"supabase_url": "", "publishable_key": ""},
    )
    path, name = prepare_spec_auth_source(
        tmp_path,
        environ={ALLOW_UNCONFIGURED_ENV: "1"},
    )
    assert name == UNCONFIGURED_DIST_NAME
    assert name != OFFICIAL_DIST_NAME
    assert path.endswith("auth-source.json")


def test_prepare_spec_writes_official_bundle_when_configured(tmp_path):
    resolved_env = {
        "CAPIXE_SUPABASE_URL": "https://example.supabase.co",
        "CAPIXE_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_official",
    }
    path, name = prepare_spec_auth_source(tmp_path, environ=resolved_env)
    assert name == OFFICIAL_DIST_NAME
    info = inspect_auth_source_file(Path(path))
    assert info["configured"] is True
    assert info["url_kind"] == "supabase_https"
    assert info["key_kind"] == "sb_publishable"
    dumped = json.dumps(info)
    assert "sb_publishable_official" not in dumped


def test_inspect_auth_source_never_returns_secret_body(tmp_path):
    path = write_bundled_auth_source(
        tmp_path,
        resolve_public_auth(
            tmp_path,
            environ={
                "CAPIXE_SUPABASE_URL": "https://example.supabase.co",
                "CAPIXE_SUPABASE_PUBLISHABLE_KEY": "super-secret-publishable",
            },
            allow_cli=False,
        ),
    )
    info = inspect_auth_source_file(path)
    assert "super-secret-publishable" not in json.dumps(info)


def test_source_preflight_fails_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("CAPIXE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    _write_tiny_openclip_bundle(tmp_path / VERIFIED_OPENCLIP_REL)
    result = run_source_preflight(ResolvedPublicAuth("", "", "none"), root=tmp_path)
    assert result["ok"] is False
    assert "authentication_configured" in result["failures"]
    assert result["openclip_bundle_valid"] is True


def test_source_preflight_passes_for_public_settings(monkeypatch, tmp_path):
    resolved = ResolvedPublicAuth(
        "https://example.supabase.co",
        "sb_publishable_ok",
        "env",
    )
    monkeypatch.setattr(
        "app.auth.config._read_source_file",
        lambda: {
            "supabase_url": resolved.supabase_url,
            "publishable_key": resolved.publishable_key,
        },
    )
    _write_tiny_openclip_bundle(tmp_path / VERIFIED_OPENCLIP_REL)
    result = run_source_preflight(resolved, root=tmp_path)
    assert result["ok"] is True
    assert result["prototype_tour_present"] is True
    assert result["ai_proxy_public_settings_readable"] is True
    assert result["openclip_bundle_valid"] is True


def test_source_preflight_fails_when_openclip_missing(monkeypatch, tmp_path):
    resolved = ResolvedPublicAuth(
        "https://example.supabase.co",
        "sb_publishable_ok",
        "env",
    )
    monkeypatch.setattr(
        "app.auth.config._read_source_file",
        lambda: {
            "supabase_url": resolved.supabase_url,
            "publishable_key": resolved.publishable_key,
        },
    )
    result = run_source_preflight(resolved, root=tmp_path)
    assert result["ok"] is False
    assert "openclip_bundle_present" in result["failures"]
    assert "openclip_bundle_valid" in result["failures"]


def test_copy_official_openclip_bundle_validates_and_keeps_license(tmp_path):
    source = _write_tiny_openclip_bundle(tmp_path / VERIFIED_OPENCLIP_REL)
    dest = copy_official_openclip_bundle(tmp_path)
    assert dest == tmp_path / PACKAGED_OPENCLIP_REL
    for name in REQUIRED_OPENCLIP_FILES:
        assert (dest / name).is_file()
        assert not (dest / name).is_symlink()
    assert (dest / "OPEN_CLIP_LICENSE.txt").read_bytes() == (
        source / "OPEN_CLIP_LICENSE.txt"
    ).read_bytes()
    assert (dest / "NOTICE.txt").read_bytes() == (source / "NOTICE.txt").read_bytes()
    info = inspect_packaged_openclip(tmp_path)
    assert info["valid"] is True
    assert info["has_symlink"] is False


def test_copy_official_openclip_bundle_refuses_missing_source(tmp_path):
    with pytest.raises(OfficialBuildError, match="openclip-v1"):
        copy_official_openclip_bundle(tmp_path)
    assert inspect_source_openclip(tmp_path)["valid"] is False
    assert inspect_packaged_openclip(tmp_path)["present"] is False


def test_copy_official_openclip_bundle_refuses_corrupt_source(tmp_path):
    root = _write_tiny_openclip_bundle(tmp_path / VERIFIED_OPENCLIP_REL)
    (root / "image_encoder.onnx").write_bytes(b"tampered")
    with pytest.raises(OfficialBuildError, match="incomplete|missing or incomplete"):
        copy_official_openclip_bundle(tmp_path)


def test_describe_auth_config_has_no_secret_body(monkeypatch):
    monkeypatch.setenv("CAPIXE_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_hidden")
    monkeypatch.setattr("app.auth.config._read_source_file", lambda: {})
    status = describe_auth_config()
    assert status.configured is True
    dumped = json.dumps(status.__dict__)
    assert "sb_publishable_hidden" not in dumped
    assert classify_supabase_url("https://example.supabase.co") == "supabase_https"
    assert classify_publishable_key("sk-test") == "provider_secret"


def test_runtime_prefers_local_auth_source(monkeypatch, tmp_path):
    local = tmp_path / AUTH_LOCAL_NAME
    local.write_text(
        json.dumps(
            {
                "supabase_url": "https://local.supabase.co",
                "publishable_key": "sb_publishable_runtime",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CAPIXE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("CAPIXE_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setattr("app.auth.config._source_file_candidates", lambda: [local])
    config = load_auth_client_config()
    assert config.configured is True
    assert config.supabase_url == "https://local.supabase.co"


def test_prepare_spec_writes_official_build_info(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _build,
        "read_source_identity",
        lambda root=None: {"source_revision": "abc123def456", "dirty": True},
    )
    path, name = prepare_spec_auth_source(
        tmp_path,
        environ={
            "CAPIXE_SUPABASE_URL": "https://example.supabase.co",
            "CAPIXE_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_official",
        },
    )
    assert name == OFFICIAL_DIST_NAME
    bundled = tmp_path / BUNDLED_BUILD_INFO_REL
    payload = json.loads(bundled.read_text(encoding="utf-8"))
    assert payload["official"] is True
    assert payload["source_revision"] == "abc123def456"
    assert payload["dirty"] is True
    assert payload["build_id"]
    assert payload["search_prompt_version"] == "db-sot-search-v1.7-query-target"
    assert payload["facts_prompt_version"] == "db-sot-facts-v8-small-named-surface"
    dumped = json.dumps(payload)
    assert "sb_publishable_official" not in dumped
    assert str(path) not in dumped


def test_unconfigured_build_info_is_not_official(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _build,
        "read_source_identity",
        lambda root=None: {"source_revision": "abc123", "dirty": False},
    )
    _write_json(tmp_path / "resources" / "auth-source.json", {"supabase_url": "", "publishable_key": ""})
    _name = prepare_spec_auth_source(tmp_path, environ={ALLOW_UNCONFIGURED_ENV: "1"})[1]
    assert _name == UNCONFIGURED_DIST_NAME
    payload = json.loads((tmp_path / BUNDLED_BUILD_INFO_REL).read_text(encoding="utf-8"))
    assert payload["official"] is False


def test_conflicting_exes_are_not_official_output(tmp_path):
    assert OFFICIAL_DIST_NAME == "Rootlize"
    assert UNCONFIGURED_DIST_NAME == "Rootlize-unconfigured"
    assert OFFICIAL_EXE_REL == Path("dist") / "Rootlize" / "Rootlize.exe"
    official = tmp_path / OFFICIAL_EXE_REL
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official")
    leftover = tmp_path / "dist" / "openclip-old" / "Capixe" / "Capixe.exe"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"old")
    bat = tmp_path / "bat.capixe.exe"
    bat.write_bytes(b"bat")
    conflicts = conflicting_exe_paths(tmp_path)
    names = {path.name.lower() for path in conflicts}
    assert "bat.capixe.exe" in names
    assert leftover in conflicts
    assert official.resolve() not in {path.resolve() for path in conflicts}


def test_finalize_and_inspect_packaged_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _build,
        "read_source_identity",
        lambda root=None: {"source_revision": "deadbeefcafebabe", "dirty": True},
    )
    exe = tmp_path / OFFICIAL_EXE_REL
    exe.parent.mkdir(parents=True)
    (exe.parent / "_internal").mkdir()
    exe.write_bytes(b"packaged-official-bytes")
    write_bundled_build_info(tmp_path, official=True, build_time="2026-08-27T07:00:00Z")
    payload = finalize_packaged_build_info(tmp_path)
    assert payload["official"] is True
    assert payload["source_revision"] == "deadbeefcafebabe"
    assert payload["exe_sha256"]
    identity = inspect_packaged_build_identity(tmp_path)
    assert identity["official_output_path"] is True
    assert identity["build_info_present"] is True
    assert identity["official_flag"] is True
    assert identity["source_revision_present"] is True
    assert identity["exe_matches_manifest"] is True
    assert identity["no_conflicting_exes"] is True


def test_identity_fails_when_manifest_sha_does_not_match(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _build,
        "read_source_identity",
        lambda root=None: {"source_revision": "deadbeefcafebabe", "dirty": False},
    )
    exe = tmp_path / OFFICIAL_EXE_REL
    exe.parent.mkdir(parents=True)
    (exe.parent / "_internal").mkdir()
    exe.write_bytes(b"one")
    write_bundled_build_info(tmp_path, official=True)
    finalize_packaged_build_info(tmp_path)
    exe.write_bytes(b"two")
    identity = inspect_packaged_build_identity(tmp_path)
    assert identity["exe_matches_manifest"] is False
