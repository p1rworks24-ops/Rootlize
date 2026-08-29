"""Packaged-build identity. No secrets, no user paths, no mtime-as-latest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.branding import APP_NAME, APP_VERSION
from app.image_facts.schema import FACTS_PROMPT_VERSION, SEARCH_PROMPT_VERSION
from app.paths import get_legacy_install_root, get_resource_root, is_frozen

BUILD_INFO_NAME = "build-info.json"


@dataclass(frozen=True)
class BuildInfo:
    build_id: str = ""
    build_time: str = ""
    source_revision: str = ""
    dirty: bool = False
    official: bool = False
    app_version: str = APP_VERSION
    search_prompt_version: str = SEARCH_PROMPT_VERSION
    facts_prompt_version: str = FACTS_PROMPT_VERSION
    output_relpath: str = ""
    exe_sha256: str = ""

    @property
    def source_revision_display(self) -> str:
        revision = str(self.source_revision or "").strip()
        if not revision:
            return ""
        return f"{revision}-dirty" if self.dirty else revision


def parse_build_info(payload: dict[str, Any] | None) -> BuildInfo:
    data = payload if isinstance(payload, dict) else {}
    return BuildInfo(
        build_id=str(data.get("build_id") or "").strip(),
        build_time=str(data.get("build_time") or "").strip(),
        source_revision=str(data.get("source_revision") or "").strip(),
        dirty=bool(data.get("dirty")),
        official=bool(data.get("official")),
        app_version=str(data.get("app_version") or APP_VERSION).strip() or APP_VERSION,
        search_prompt_version=str(
            data.get("search_prompt_version") or SEARCH_PROMPT_VERSION
        ).strip()
        or SEARCH_PROMPT_VERSION,
        facts_prompt_version=str(
            data.get("facts_prompt_version") or FACTS_PROMPT_VERSION
        ).strip()
        or FACTS_PROMPT_VERSION,
        output_relpath=str(data.get("output_relpath") or "").strip(),
        exe_sha256=str(data.get("exe_sha256") or "").strip().upper(),
    )


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_info_candidates() -> tuple[Path, ...]:
    roots = (get_resource_root(), get_legacy_install_root())
    paths: list[Path] = []
    for root in roots:
        paths.append(root / BUILD_INFO_NAME)
        paths.append(root / "resources" / BUILD_INFO_NAME)
    return tuple(paths)


def load_build_info() -> BuildInfo:
    for path in build_info_candidates():
        if path.is_file():
            return parse_build_info(load_json_object(path))
    return BuildInfo(official=False)


def format_version_text(info: BuildInfo | None = None, *, executable: str = "") -> str:
    data = info or load_build_info()
    lines = [
        f"{APP_NAME} {data.app_version}",
        f"build_id={data.build_id or 'none'}",
        f"source_revision={data.source_revision_display or 'none'}",
        f"official={'true' if data.official else 'false'}",
        f"build_time={data.build_time or 'none'}",
        f"search_prompt_version={data.search_prompt_version}",
        f"facts_prompt_version={data.facts_prompt_version}",
    ]
    if executable:
        lines.append(f"executable={executable}")
    elif is_frozen():
        import sys

        lines.append(f"executable={sys.executable}")
    return "\n".join(lines) + "\n"
