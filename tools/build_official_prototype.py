"""Official public-prototype packaged build.

Human verification target is always:

    dist\\Rootlize\\Rootlize.exe

Do not point people at artifacts or other EXEs. Auth must be configured
or this script fails. Secret bodies are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_proxy.config import functions_url
from app.auth.config import (
    AUTH_LOCAL_NAME,
    AUTH_SOURCE_NAME,
    PUBLISHABLE_ENV,
    URL_ENV,
    AuthClientConfig,
    classify_publishable_key,
    classify_supabase_url,
    describe_auth_config,
    is_provider_secret_value,
    is_service_role_key,
    load_auth_client_config_or_unconfigured,
)
from app.branding import APP_VERSION, DATA_DIR_NAME, DIST_NAME
from app.build_info import BUILD_INFO_NAME, parse_build_info
from app.image_facts.schema import FACTS_PROMPT_VERSION, SEARCH_PROMPT_VERSION
from app.paths import is_frozen
from app.semantic.bundle import load_bundle
from app.semantic.catalog import (
    MODEL_IDS,
    OPENCLIP_BUNDLE_VERSION,
    OPENCLIP_MODEL_KEY,
    OPENCLIP_PIPELINE_VERSION,
    OPENCLIP_REVISION,
)
from app.semantic.worker_errors import ModelCorruptError, ModelNotInstalledError, SemanticWorkerError

OFFICIAL_DIST_NAME = DIST_NAME
UNCONFIGURED_DIST_NAME = f"{DIST_NAME}-unconfigured"
ALLOW_UNCONFIGURED_ENV = "CAPIXE_ALLOW_UNCONFIGURED_DIST"
BUNDLED_AUTH_REL = Path("build") / "official_bundle" / AUTH_SOURCE_NAME
BUNDLED_BUILD_INFO_REL = Path("build") / "official_bundle" / BUILD_INFO_NAME
OFFICIAL_EXE_REL = Path("dist") / OFFICIAL_DIST_NAME / f"{DIST_NAME}.exe"
VERIFIED_OPENCLIP_REL = Path("release") / f"semantic-model-{OPENCLIP_BUNDLE_VERSION}"
PACKAGED_OPENCLIP_REL = (
    Path("dist")
    / OFFICIAL_DIST_NAME
    / "_internal"
    / "resources"
    / "semantic-models"
    / OPENCLIP_BUNDLE_VERSION
)
REQUIRED_OPENCLIP_FILES = (
    "manifest.json",
    "image_encoder.onnx",
    "text_encoder.onnx",
    "bpe_simple_vocab_16e6.txt.gz",
    "open_clip_config.json",
    "preprocessor_config.json",
    "OPEN_CLIP_LICENSE.txt",
    "NOTICE.txt",
)
OPENCLIP_MODEL_ID = MODEL_IDS[OPENCLIP_MODEL_KEY]
CONFLICTING_EXE_NAMES = ("bat.capixe.exe",)
TOUR_MODULES = (
    "app.prototype_tour",
    "app.prototype_tour.controller",
    "app.prototype_tour.models",
    "app.prototype_tour.steps",
    "app.prototype_tour.events",
    "app.prototype_tour.draft",
    "app.ui.tour_host",
    "app.ui.tour_overlay",
    "app.ui.tour_popover",
)


@dataclass(frozen=True)
class ResolvedPublicAuth:
    supabase_url: str
    publishable_key: str
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.publishable_key)

    @property
    def config(self) -> AuthClientConfig:
        return AuthClientConfig(
            supabase_url=self.supabase_url.rstrip("/"),
            publishable_key=self.publishable_key,
        )


class OfficialBuildError(RuntimeError):
    """Official prototype build is not acceptable."""


def _load_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _public_fields(data: dict) -> tuple[str, str]:
    url = str(data.get("supabase_url") or "").strip().rstrip("/")
    key = str(data.get("publishable_key") or data.get("anon_key") or "").strip()
    return url, key


def _usable_publishable(key: str) -> bool:
    text = str(key or "").strip()
    if not text:
        return False
    if is_service_role_key(text) or is_provider_secret_value(text):
        return False
    return True


def _read_project_ref(root: Path) -> str:
    env_ref = (os.environ.get("CAPIXE_SUPABASE_PROJECT_REF") or "").strip()
    if env_ref:
        return env_ref
    temp = root / "supabase" / ".temp" / "project-ref"
    if temp.is_file():
        return temp.read_text(encoding="utf-8").strip()
    config = root / "supabase" / "config.toml"
    if config.is_file():
        for line in config.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("project_id"):
                _, _, value = stripped.partition("=")
                return value.strip().strip('"').strip("'")
    return ""


def _supabase_cli_command() -> str:
    for name in ("supabase", "supabase.cmd", "supabase.exe"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def _try_supabase_cli(root: Path) -> tuple[str, str]:
    ref = _read_project_ref(root)
    cli = _supabase_cli_command()
    if not ref or not cli:
        return "", ""
    try:
        completed = subprocess.run(
            [cli, "projects", "api-keys", "--project-ref", ref, "--output", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", ""
    if completed.returncode != 0 or not (completed.stdout or "").strip():
        return "", ""
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return "", ""
    rows = payload if isinstance(payload, list) else payload.get("keys") or payload.get("api_keys") or []
    if not isinstance(rows, list):
        return "", ""
    url = f"https://{ref}.supabase.co"
    for row in rows:
        if not isinstance(row, dict):
            continue
        labels = " ".join(
            str(row.get(name) or "") for name in ("name", "type", "id", "tags")
        ).lower()
        key = str(row.get("api_key") or row.get("key") or "").strip()
        if not _usable_publishable(key):
            continue
        if any(token in labels for token in ("anon", "publishable")):
            return url, key
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("api_key") or row.get("key") or "").strip()
        if _usable_publishable(key):
            return url, key
    return url if url else "", ""


def resolve_public_auth(
    root: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    allow_cli: bool = False,
) -> ResolvedPublicAuth:
    base = Path(root or ROOT)
    env = environ if environ is not None else os.environ
    env_url = (env.get(URL_ENV) or "").strip().rstrip("/")
    env_key = (env.get(PUBLISHABLE_ENV) or env.get("CAPIXE_SUPABASE_ANON_KEY") or "").strip()
    if env_url and _usable_publishable(env_key):
        return ResolvedPublicAuth(env_url, env_key, "env")

    local_path = base / "resources" / AUTH_LOCAL_NAME
    if local_path.is_file():
        url, key = _public_fields(_load_json_object(local_path))
        if url and _usable_publishable(key):
            return ResolvedPublicAuth(url, key, "local_file")

    bundled = base / BUNDLED_AUTH_REL
    if bundled.is_file():
        url, key = _public_fields(_load_json_object(bundled))
        if url and _usable_publishable(key):
            return ResolvedPublicAuth(url, key, "bundled_file")

    template = base / "resources" / AUTH_SOURCE_NAME
    if template.is_file():
        url, key = _public_fields(_load_json_object(template))
        if url and _usable_publishable(key):
            return ResolvedPublicAuth(url, key, "file")

    if allow_cli:
        url, key = _try_supabase_cli(base)
        if url and _usable_publishable(key):
            return ResolvedPublicAuth(url, key, "supabase_cli")

    return ResolvedPublicAuth("", "", "none")


def write_bundled_auth_source(root: Path, resolved: ResolvedPublicAuth) -> Path:
    path = Path(root) / BUNDLED_AUTH_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "supabase_url": resolved.supabase_url,
        "publishable_key": resolved.publishable_key,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_local_auth_source(root: Path, resolved: ResolvedPublicAuth) -> Path:
    path = Path(root) / "resources" / AUTH_LOCAL_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "supabase_url": resolved.supabase_url,
        "publishable_key": resolved.publishable_key,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def inspect_auth_source_file(path: Path) -> dict[str, object]:
    """Presence / kind only. Never includes secret bodies."""
    if not path.is_file():
        return {"exists": False, "configured": False, "url_kind": "empty", "key_kind": "empty"}
    url, key = _public_fields(_load_json_object(path))
    return {
        "exists": True,
        "configured": bool(url and _usable_publishable(key)),
        "url_kind": classify_supabase_url(url),
        "key_kind": classify_publishable_key(key),
    }


def allow_unconfigured_dist(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return (env.get(ALLOW_UNCONFIGURED_ENV) or "").strip().lower() in {"1", "true", "yes"}


def _git_text(root: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        return ""
    try:
        completed = subprocess.run(
            [git, "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def read_source_identity(root: Path | None = None) -> dict[str, object]:
    """Commit SHA plus dirty flag. No user names, emails, or local paths."""
    base = Path(root or ROOT)
    revision = _git_text(base, "rev-parse", "HEAD")
    porcelain = _git_text(base, "status", "--porcelain")
    return {
        "source_revision": revision,
        "dirty": bool(porcelain),
    }


def make_build_id(build_time: str, source_revision: str, *, dirty: bool) -> str:
    stamp = (build_time or "").replace("-", "").replace(":", "").replace("T", "")
    stamp = stamp.replace("Z", "")[:15]
    short = (source_revision or "unknown")[:12]
    suffix = "dirty" if dirty else "clean"
    return f"{stamp}-{short}-{suffix}"


def build_provenance_payload(
    root: Path | None = None,
    *,
    official: bool,
    exe_sha256: str = "",
    build_time: str | None = None,
) -> dict[str, object]:
    base = Path(root or ROOT)
    identity = read_source_identity(base)
    revision = str(identity["source_revision"] or "")
    dirty = bool(identity["dirty"])
    stamped = build_time or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "build_id": make_build_id(stamped, revision, dirty=dirty),
        "build_time": stamped,
        "source_revision": revision,
        "dirty": dirty,
        "official": bool(official),
        "app_version": APP_VERSION,
        "search_prompt_version": SEARCH_PROMPT_VERSION,
        "facts_prompt_version": FACTS_PROMPT_VERSION,
        "output_relpath": str(OFFICIAL_EXE_REL).replace("\\", "/") if official else "",
        "exe_sha256": str(exe_sha256 or "").strip().upper(),
    }


def write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_bundled_build_info(
    root: Path,
    *,
    official: bool,
    exe_sha256: str = "",
    build_time: str | None = None,
) -> Path:
    payload = build_provenance_payload(
        root,
        official=official,
        exe_sha256=exe_sha256,
        build_time=build_time,
    )
    return write_json(Path(root) / BUNDLED_BUILD_INFO_REL, payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def conflicting_exe_paths(root: Path | None = None) -> tuple[Path, ...]:
    """EXEs that must never be treated as the official human-verification build."""
    base = Path(root or ROOT)
    official = (base / OFFICIAL_EXE_REL).resolve()
    found: list[Path] = []
    dist = base / "dist"
    if dist.is_dir():
        for path in dist.rglob("*.exe"):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved == official:
                continue
            name = path.name.lower()
            parent = path.parent.resolve()
            if (
                name in {"capixe.exe", "rootlize.exe", "bat.capixe.exe"}
                or name.endswith("capixe.exe")
                or name.endswith("rootlize.exe")
                or parent == dist.resolve()
            ):
                found.append(path)
    for name in CONFLICTING_EXE_NAMES:
        candidate = base / name
        if candidate.is_file():
            found.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def prepare_spec_auth_source(
    spec_root: str | Path,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return (auth-source path, COLLECT name) for Capixe.spec."""
    root = Path(spec_root)
    resolved = resolve_public_auth(root, environ=environ, allow_cli=False)
    if resolved.configured:
        path = write_bundled_auth_source(root, resolved)
        write_bundled_build_info(root, official=True)
        return str(path), OFFICIAL_DIST_NAME
    if allow_unconfigured_dist(environ):
        fallback = root / "resources" / AUTH_SOURCE_NAME
        write_bundled_build_info(root, official=False)
        return str(fallback), UNCONFIGURED_DIST_NAME
    raise OfficialBuildError(
        "Official prototype build refused: Authentication is not configured.\n"
        f"Public Prototype confirmation uses only dist\\{DIST_NAME}\\{DIST_NAME}.exe.\n"
        "Provide CAPIXE_SUPABASE_URL + CAPIXE_SUPABASE_PUBLISHABLE_KEY, or "
        f"resources\\{AUTH_LOCAL_NAME}, then run "
        "tools\\build_official_prototype.py.\n"
        f"Auth-less builds must set {ALLOW_UNCONFIGURED_ENV}=1 and write to "
        f"dist\\{UNCONFIGURED_DIST_NAME}, never dist\\{DIST_NAME}."
    )


def _prototype_tour_present() -> tuple[bool, tuple[str, ...]]:
    missing: list[str] = []
    for name in TOUR_MODULES:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return (not missing), tuple(missing)


def inspect_openclip_bundle(path: Path) -> dict[str, object]:
    """Validate a verified OpenCLIP product bundle. Uses load_bundle() integrity checks."""
    present = path.is_dir()
    names = {child.name for child in path.iterdir()} if present else set()
    missing = tuple(name for name in REQUIRED_OPENCLIP_FILES if name not in names)
    has_symlink = False
    if present:
        try:
            has_symlink = any(child.is_symlink() for child in path.rglob("*"))
        except OSError:
            has_symlink = True
    identity: dict[str, object] = {}
    error = ""
    total_size = 0
    valid = False
    if present and not missing and not has_symlink:
        try:
            bundle = load_bundle(path, use_cache=False)
            identity = {
                "model_id": bundle.identity.model_id,
                "bundle_version": bundle.identity.bundle_version,
                "revision": bundle.identity.model_revision,
                "pipeline_version": bundle.identity.pipeline_version,
            }
            total_size = int(bundle.manifest.get("total_size_bytes") or 0)
            license_ok = (path / "OPEN_CLIP_LICENSE.txt").is_file()
            notice_ok = (path / "NOTICE.txt").is_file()
            valid = (
                bundle.identity.model_id == OPENCLIP_MODEL_ID
                and bundle.identity.bundle_version == OPENCLIP_BUNDLE_VERSION
                and bundle.identity.model_revision == OPENCLIP_REVISION
                and bundle.identity.pipeline_version == OPENCLIP_PIPELINE_VERSION
                and license_ok
                and notice_ok
            )
            if not valid:
                error = "identity_or_license_mismatch"
        except (ModelNotInstalledError, ModelCorruptError, SemanticWorkerError) as exc:
            error = exc.__class__.__name__
        except (OSError, KeyError, TypeError, ValueError) as exc:
            error = exc.__class__.__name__
    elif not present:
        error = "missing"
    elif missing:
        error = "incomplete"
    elif has_symlink:
        error = "symlink"
    return {
        "present": present,
        "valid": valid,
        "missing_files": missing,
        "has_symlink": has_symlink,
        "identity": identity,
        "error": error,
        "path": str(path),
        "total_size_bytes": total_size,
    }


def inspect_source_openclip(root: Path | None = None) -> dict[str, object]:
    return inspect_openclip_bundle(Path(root or ROOT) / VERIFIED_OPENCLIP_REL)


def inspect_packaged_openclip(root: Path | None = None) -> dict[str, object]:
    return inspect_openclip_bundle(Path(root or ROOT) / PACKAGED_OPENCLIP_REL)


def copy_official_openclip_bundle(root: Path | None = None) -> Path:
    """Copy the verified OpenCLIP bundle into official dist after COLLECT. No git, no symlink."""
    base = Path(root or ROOT)
    source = base / VERIFIED_OPENCLIP_REL
    dest = base / PACKAGED_OPENCLIP_REL
    source_info = inspect_openclip_bundle(source)
    if not source_info["valid"]:
        raise OfficialBuildError(
            "Official prototype build refused: OpenCLIP openclip-v1 bundle is "
            "missing or incomplete.\n"
            f"Expected verified bundle at {source}."
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest, symlinks=False, copy_function=shutil.copy2)
    dest_info = inspect_openclip_bundle(dest)
    if not dest_info["valid"]:
        raise OfficialBuildError(
            "Official prototype build refused: packaged OpenCLIP bundle failed validation.\n"
            f"Copied from {source} to {dest}."
        )
    print(f"Official OpenCLIP bundle: {dest}")
    print(f"Official OpenCLIP total_size_bytes: {dest_info.get('total_size_bytes')}")
    return dest


def run_source_preflight(
    resolved: ResolvedPublicAuth | None = None,
    *,
    root: Path | None = None,
) -> dict[str, object]:
    auth = resolved or resolve_public_auth(allow_cli=False)
    cfg = auth.config if auth.configured else load_auth_client_config_or_unconfigured()
    status = describe_auth_config(cfg)
    tour_ok, missing = _prototype_tour_present()
    proxy_url = functions_url(cfg.supabase_url) if cfg.configured else ""
    openclip = inspect_source_openclip(root)
    result = {
        "authentication_configured": bool(auth.configured and status.configured),
        "supabase_url_readable": status.url_kind == "supabase_https",
        "publishable_key_readable": status.key_kind in {"jwt", "sb_publishable", "other"},
        "ai_proxy_public_settings_readable": bool(
            status.proxy_functions_readable and proxy_url.startswith("https://")
        ),
        "prototype_tour_present": tour_ok,
        "openclip_bundle_present": bool(openclip["present"]),
        "openclip_bundle_valid": bool(openclip["valid"]),
        "frozen_startable_source": not is_frozen(),
        "url_kind": status.url_kind,
        "key_kind": status.key_kind,
        "auth_source": auth.source,
        "missing_tour_modules": missing,
    }
    failures = [
        name
        for name, ok in (
            ("authentication_configured", result["authentication_configured"]),
            ("supabase_url_readable", result["supabase_url_readable"]),
            ("publishable_key_readable", result["publishable_key_readable"]),
            ("ai_proxy_public_settings_readable", result["ai_proxy_public_settings_readable"]),
            ("prototype_tour_present", result["prototype_tour_present"]),
            ("openclip_bundle_present", result["openclip_bundle_present"]),
            ("openclip_bundle_valid", result["openclip_bundle_valid"]),
        )
        if not ok
    ]
    result["ok"] = not failures
    result["failures"] = tuple(failures)
    return result


def _print_preflight(title: str, result: dict[str, object]) -> None:
    print(title)
    for key in (
        "ok",
        "authentication_configured",
        "supabase_url_readable",
        "publishable_key_readable",
        "ai_proxy_public_settings_readable",
        "prototype_tour_present",
        "openclip_bundle_present",
        "openclip_bundle_valid",
        "frozen_started",
        "auth_source",
        "url_kind",
        "key_kind",
        "official_output_path",
        "build_info_present",
        "official_flag",
        "source_revision",
        "source_revision_present",
        "exe_matches_manifest",
        "no_conflicting_exes",
        "build_id",
        "conflicting_exes",
        "failures",
    ):
        if key in result:
            print(f"  {key}={result[key]}")


def _python_for_build() -> Path:
    venv = ROOT / ".build-venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return venv
    return Path(sys.executable)


def _run_pyinstaller() -> None:
    python = _python_for_build()
    cmd = [str(python), "-m", "PyInstaller", "Capixe.spec", "--clean", "--noconfirm"]
    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if completed.returncode != 0:
        raise OfficialBuildError(f"PyInstaller failed with exit {completed.returncode}.")


def inspect_packaged_auth(root: Path | None = None) -> dict[str, object]:
    base = Path(root or ROOT)
    bundled = base / "dist" / OFFICIAL_DIST_NAME / "_internal" / "resources" / AUTH_SOURCE_NAME
    return inspect_auth_source_file(bundled)


def inspect_packaged_tour(root: Path | None = None) -> dict[str, object]:
    base = Path(root or ROOT)
    internal = base / "dist" / OFFICIAL_DIST_NAME / "_internal"
    markers = (
        internal / "app" / "prototype_tour",
        internal / "prototype_tour",
    )
    present = any(path.exists() for path in markers)
    if not present and internal.is_dir():
        for path in internal.rglob("*prototype_tour*"):
            present = True
            break
    return {"prototype_tour_present": present}


def packaged_build_info_paths(root: Path | None = None) -> tuple[Path, Path, Path]:
    base = Path(root or ROOT)
    dist_dir = base / "dist" / OFFICIAL_DIST_NAME
    return (
        dist_dir / "_internal" / BUILD_INFO_NAME,
        dist_dir / BUILD_INFO_NAME,
        dist_dir / "_internal" / "resources" / BUILD_INFO_NAME,
    )


def inspect_packaged_build_identity(root: Path | None = None) -> dict[str, object]:
    base = Path(root or ROOT)
    exe = base / OFFICIAL_EXE_REL
    payload: dict[str, object] = {}
    info_path: Path | None = None
    for candidate in packaged_build_info_paths(base):
        if candidate.is_file():
            info_path = candidate
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            break
    info = parse_build_info(payload if isinstance(payload, dict) else {})
    exe_sha = _sha256_file(exe) if exe.is_file() else ""
    conflicts = conflicting_exe_paths(base)
    output_ok = exe.is_file() and exe.resolve() == (base / OFFICIAL_EXE_REL).resolve()
    revision_ok = bool(info.source_revision)
    official_ok = bool(info.official)
    present = info_path is not None
    sha_ok = bool(exe_sha) and bool(info.exe_sha256) and info.exe_sha256 == exe_sha
    return {
        "official_output_path": output_ok,
        "build_info_present": present,
        "official_flag": official_ok,
        "source_revision": info.source_revision,
        "source_revision_present": revision_ok,
        "exe_matches_manifest": sha_ok,
        "conflicting_exes": tuple(str(path) for path in conflicts),
        "no_conflicting_exes": not conflicts,
        "build_id": info.build_id,
        "build_time": info.build_time,
        "exe_sha256": exe_sha,
        "manifest_path": str(info_path) if info_path else "",
    }


def finalize_packaged_build_info(root: Path | None = None) -> dict[str, object]:
    """Stamp SHA-256 after COLLECT. Identity is this manifest, not mtime."""
    base = Path(root or ROOT)
    exe = base / OFFICIAL_EXE_REL
    if not exe.is_file():
        raise OfficialBuildError(f"Official EXE missing: {exe}")
    bundled = base / BUNDLED_BUILD_INFO_REL
    existing = json.loads(bundled.read_text(encoding="utf-8")) if bundled.is_file() else {}
    if not isinstance(existing, dict):
        existing = {}
    payload = build_provenance_payload(
        base,
        official=True,
        exe_sha256=_sha256_file(exe),
        build_time=str(existing.get("build_time") or "") or None,
    )
    if existing.get("build_id"):
        payload["build_id"] = existing["build_id"]
    write_json(bundled, payload)
    for dest in packaged_build_info_paths(base)[:2]:
        write_json(dest, payload)
    return payload


def _startup_log_path() -> Path:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if not local:
        return Path.home() / "AppData" / "Local" / DATA_DIR_NAME / "logs" / "startup.log"
    return Path(local) / DATA_DIR_NAME / "logs" / "startup.log"


def _mark_startup_log() -> tuple[Path, int]:
    path = _startup_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size if path.is_file() else 0
    return path, size


def _read_new_log_text(path: Path, start_size: int) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, start_size))
        raw = handle.read()
    return raw.decode("utf-8", errors="replace")


def launch_official_exe(root: Path | None = None, *, wait_sec: float = 8.0) -> dict[str, object]:
    base = Path(root or ROOT)
    exe = base / OFFICIAL_EXE_REL
    if not exe.is_file():
        return {
            "frozen_started": False,
            "auth_configured_log": False,
            "tour_present_log": False,
            "build_identity_log": False,
        }
    log_path, start_size = _mark_startup_log()
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(wait_sec)
        alive = proc.poll() is None
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    text = _read_new_log_text(log_path, start_size)
    return {
        "frozen_started": alive
        or ("event loop entered" in text)
        or ("MainWindow shown" in text),
        "auth_configured_log": (
            "Auth configured=True" in text or "auth config configured=True" in text
        ),
        "tour_present_log": (
            "Prototype tour present=True" in text or "prototype tour present=True" in text
        ),
        "build_identity_log": "build_id=" in text and "official=" in text,
        "log_has_not_configured": "not configured" in text.lower(),
    }


def run_packaged_postflight(root: Path | None = None) -> dict[str, object]:
    base = Path(root or ROOT)
    exe = base / OFFICIAL_EXE_REL
    auth = inspect_packaged_auth(base)
    tour = inspect_packaged_tour(base)
    identity = inspect_packaged_build_identity(base)
    launch = launch_official_exe(base)
    openclip = inspect_packaged_openclip(base)
    result = {
        "exe_present": exe.is_file(),
        "authentication_configured": bool(auth.get("configured")),
        "supabase_url_readable": auth.get("url_kind") == "supabase_https",
        "publishable_key_readable": auth.get("key_kind") in {"jwt", "sb_publishable", "other"},
        "ai_proxy_public_settings_readable": bool(auth.get("configured")),
        "prototype_tour_present": bool(tour.get("prototype_tour_present") or launch.get("tour_present_log")),
        "openclip_bundle_present": bool(openclip["present"]),
        "openclip_bundle_valid": bool(openclip["valid"]),
        "frozen_started": bool(launch.get("frozen_started")),
        "auth_configured_log": bool(launch.get("auth_configured_log")),
        "url_kind": auth.get("url_kind"),
        "key_kind": auth.get("key_kind"),
        "official_output_path": bool(identity.get("official_output_path")),
        "build_info_present": bool(identity.get("build_info_present")),
        "official_flag": bool(identity.get("official_flag")),
        "source_revision": identity.get("source_revision") or "",
        "source_revision_present": bool(identity.get("source_revision_present")),
        "exe_matches_manifest": bool(identity.get("exe_matches_manifest")),
        "conflicting_exes": identity.get("conflicting_exes") or (),
        "no_conflicting_exes": bool(identity.get("no_conflicting_exes")),
        "build_id": identity.get("build_id") or "",
        "build_time": identity.get("build_time") or "",
    }
    failures = [
        name
        for name, ok in (
            ("exe_present", result["exe_present"]),
            ("authentication_configured", result["authentication_configured"]),
            ("supabase_url_readable", result["supabase_url_readable"]),
            ("publishable_key_readable", result["publishable_key_readable"]),
            ("ai_proxy_public_settings_readable", result["ai_proxy_public_settings_readable"]),
            ("prototype_tour_present", result["prototype_tour_present"]),
            ("openclip_bundle_present", result["openclip_bundle_present"]),
            ("openclip_bundle_valid", result["openclip_bundle_valid"]),
            ("frozen_started", result["frozen_started"]),
            ("official_output_path", result["official_output_path"]),
            ("build_info_present", result["build_info_present"]),
            ("official_flag", result["official_flag"]),
            ("source_revision_present", result["source_revision_present"]),
            ("exe_matches_manifest", result["exe_matches_manifest"]),
            ("no_conflicting_exes", result["no_conflicting_exes"]),
        )
        if not ok
    ]
    result["ok"] = not failures
    result["failures"] = tuple(failures)
    return result


def build_official_prototype(*, persist_local: bool = True) -> dict[str, object]:
    resolved = resolve_public_auth(ROOT, allow_cli=True)
    if not resolved.configured:
        raise OfficialBuildError(
            "Official prototype build refused: Authentication is not configured.\n"
            "Set CAPIXE_SUPABASE_URL and CAPIXE_SUPABASE_PUBLISHABLE_KEY, or "
            f"create resources\\{AUTH_LOCAL_NAME}, or sign in to the Supabase CLI "
            "for the linked project. Do not write secrets into source."
        )
    write_bundled_auth_source(ROOT, resolved)
    write_bundled_build_info(ROOT, official=True)
    if persist_local:
        write_local_auth_source(ROOT, resolved)
    os.environ[URL_ENV] = resolved.supabase_url
    os.environ[PUBLISHABLE_ENV] = resolved.publishable_key
    preflight = run_source_preflight(resolved, root=ROOT)
    _print_preflight("Official prototype preflight", preflight)
    if not preflight["ok"]:
        raise OfficialBuildError(
            "Official prototype preflight failed: " + ",".join(preflight["failures"])
        )
    _run_pyinstaller()
    copy_official_openclip_bundle(ROOT)
    provenance = finalize_packaged_build_info(ROOT)
    postflight = run_packaged_postflight(ROOT)
    _print_preflight("Official prototype postflight", postflight)
    if not postflight["ok"]:
        raise OfficialBuildError(
            "Official prototype postflight failed: " + ",".join(postflight["failures"])
        )
    exe = ROOT / OFFICIAL_EXE_REL
    print(f"Official EXE: {exe}")
    print(f"Official build_id: {provenance.get('build_id')}")
    print(f"Official source_revision: {provenance.get('source_revision')} dirty={provenance.get('dirty')}")
    print(f"Official exe_sha256: {provenance.get('exe_sha256')}")
    print(
        "Official EXE mtime (auxiliary only): "
        + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exe.stat().st_mtime))
    )
    return {
        "preflight": preflight,
        "postflight": postflight,
        "auth_source": resolved.source,
        "build_info": provenance,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the official Rootlize prototype EXE.")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            resolved = resolve_public_auth(ROOT, allow_cli=True)
            result = run_source_preflight(resolved)
            _print_preflight("Official prototype preflight", result)
            return 0 if result["ok"] else 2
        build_official_prototype()
        return 0
    except OfficialBuildError as exc:
        print(exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
