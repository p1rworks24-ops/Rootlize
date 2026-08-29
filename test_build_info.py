"""Packaged build identity is read from build-info.json, not mtime."""

from __future__ import annotations

from pathlib import Path

from app.build_info import format_version_text, load_build_info, parse_build_info


def test_parse_build_info_marks_dirty_revision():
    info = parse_build_info(
        {
            "build_id": "20260827T070000-abc123-dirty",
            "build_time": "2026-08-27T07:00:00Z",
            "source_revision": "abc123def456",
            "dirty": True,
            "official": True,
            "app_version": "0.1.0-preview",
            "search_prompt_version": "db-sot-search-v1.7-query-target",
            "facts_prompt_version": "db-sot-facts-v8-small-named-surface",
        }
    )
    assert info.official is True
    assert info.source_revision_display == "abc123def456-dirty"
    text = format_version_text(info, executable=r"D:\dist\Rootlize\Rootlize.exe")
    assert "official=true" in text
    assert "Rootlize 0.1.0-preview" in text
    assert "source_revision=abc123def456-dirty" in text
    assert "executable=" in text


def test_load_build_info_from_resource_root(tmp_path, monkeypatch):
    payload = (
        '{"build_id":"id-1","build_time":"2026-08-27T07:00:00Z",'
        '"source_revision":"abc","dirty":false,"official":true,'
        '"app_version":"0.1.0-preview",'
        '"search_prompt_version":"db-sot-search-v1.7-query-target",'
        '"facts_prompt_version":"db-sot-facts-v8-small-named-surface"}'
    )
    (tmp_path / "build-info.json").write_text(payload, encoding="utf-8")
    monkeypatch.setattr("app.build_info.get_resource_root", lambda: Path(tmp_path))
    monkeypatch.setattr("app.build_info.get_legacy_install_root", lambda: Path(tmp_path))
    info = load_build_info()
    assert info.build_id == "id-1"
    assert info.official is True
    assert info.source_revision == "abc"
