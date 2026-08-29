"""Optional Semantic bundle discovery and non-UI installation primitives."""

from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Protocol

from app.paths import (
    get_bundled_semantic_bundle_dir,
    get_bundled_semantic_models_dir,
    get_resource_root,
    get_semantic_models_dir,
    is_frozen,
)

from .bundle import (
    ModelBundle,
    is_bundle_validation_in_flight,
    load_bundle,
    peek_cached_bundle,
)
from .catalog import (
    BUNDLE_VERSIONS,
    DEFAULT_MODEL_KEY,
    MODEL_IDS,
    SIGLIP_MODEL_KEY,
    bundle_version_for_key,
    model_id_for_key,
    normalize_model_key,
)
from .worker_errors import ModelCorruptError, ModelNotInstalledError

SOURCE_DESCRIPTOR = "semantic-model-source.json"


@dataclass(frozen=True)
class InstallProgress:
    downloaded_bytes: int
    total_bytes: int
    current_file: str


class DownloadSource(Protocol):
    def manifest(self) -> dict: ...
    def open_file(self, entry: dict) -> BinaryIO: ...


class HttpDownloadSource:
    """HTTP implementation configured by a shipped descriptor, never a built-in URL."""

    def __init__(self, manifest_url: str, files_base_url: str, *, bundle_version: str | None = None):
        self.manifest_url = manifest_url
        self.files_base_url = files_base_url.rstrip("/") + "/"
        self.bundle_version = bundle_version

    def manifest(self) -> dict:
        with urllib.request.urlopen(self.manifest_url, timeout=30) as response:
            return json.load(response)

    def open_file(self, entry: dict) -> BinaryIO:
        relative = str(entry["path"]).replace("\\", "/")
        return urllib.request.urlopen(self.files_base_url + relative, timeout=60)


class LocalDirectorySource:
    """Development install source selected explicitly by the user."""
    def __init__(self, directory: Path):
        self.directory = directory
        self.bundle_version = None
    def manifest(self) -> dict:
        return json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
    def open_file(self, entry: dict) -> BinaryIO:
        return (self.directory / str(entry["path"])).open("rb")


def configured_download_source(model_key: object = SIGLIP_MODEL_KEY) -> DownloadSource | None:
    """Load release-owned source metadata when packaging has supplied it."""
    if normalize_model_key(model_key) != SIGLIP_MODEL_KEY:
        return None
    descriptor = get_resource_root() / "resources" / SOURCE_DESCRIPTOR
    if not descriptor.is_file():
        return None
    try:
        data = json.loads(descriptor.read_text(encoding="utf-8"))
        manifest_url = str(data["manifest_url"]).strip()
        files_base_url = str(data["files_base_url"]).strip()
        if not manifest_url.startswith("https://") or not files_base_url.startswith("https://"):
            return None
        version = str(data.get("bundle_version") or "").strip() or None
        return HttpDownloadSource(manifest_url, files_base_url, bundle_version=version)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _matches_bundle(bundle: ModelBundle, *, bundle_version: str | None, model_id: str | None) -> bool:
    return (
        (bundle_version is None or bundle.identity.bundle_version == bundle_version)
        and (model_id is None or bundle.identity.model_id == model_id)
    )


def _try_load_bundle(path: Path, *, bundle_version: str | None, model_id: str | None) -> ModelBundle | None:
    try:
        bundle = load_bundle(path)
    except (ModelNotInstalledError, ModelCorruptError):
        return None
    if _matches_bundle(bundle, bundle_version=bundle_version, model_id=model_id):
        return bundle
    return None


def _iter_bundle_dirs(root: Path):
    try:
        children = (path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".installing-"))
        yield from sorted(children, reverse=True)
    except OSError:
        return


def _scan_models_root(root: Path, *, bundle_version: str | None, model_id: str | None) -> ModelBundle | None:
    """Return the newest valid bundle in one models root. Corrupt dirs are ignored."""
    for candidate in _iter_bundle_dirs(root):
        found = _try_load_bundle(candidate, bundle_version=bundle_version, model_id=model_id)
        if found is not None:
            return found
    return None


def _inferred_bundle_version(bundle_version: str | None, model_id: str | None) -> str | None:
    if bundle_version:
        return bundle_version
    if not model_id:
        return None
    for key, known in MODEL_IDS.items():
        if known == model_id:
            return BUNDLE_VERSIONS.get(key)
    return None


def _development_release_bundle_dir(bundle_version: str) -> Path | None:
    """Unfrozen source tree only. Tests stay on isolated LOCALAPPDATA / overrides."""
    if is_frozen() or os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return get_resource_root() / "release" / f"semantic-model-{bundle_version}"


def find_installed_bundle(root: Path | None = None, *, bundle_version: str | None = None, model_id: str | None = None) -> ModelBundle | None:
    """Find a valid Semantic bundle.

    An explicit ``root`` is scanned only (installer / tests). Product discovery
    (``root is None``) prefers the shipped resource, then an existing
    LOCALAPPDATA fallback. Development also accepts ``release/semantic-model-*``.
    """
    if root is not None:
        return _scan_models_root(root, bundle_version=bundle_version, model_id=model_id)

    version = _inferred_bundle_version(bundle_version, model_id)
    if version:
        bundled = _try_load_bundle(
            get_bundled_semantic_bundle_dir(version),
            bundle_version=bundle_version or version,
            model_id=model_id,
        )
        if bundled is not None:
            return bundled
    found = _scan_models_root(
        get_bundled_semantic_models_dir(),
        bundle_version=bundle_version,
        model_id=model_id,
    )
    if found is not None:
        return found
    if version:
        release = _development_release_bundle_dir(version)
        if release is not None:
            found = _try_load_bundle(
                release,
                bundle_version=bundle_version or version,
                model_id=model_id,
            )
            if found is not None:
                return found
    return _scan_models_root(
        get_semantic_models_dir(),
        bundle_version=bundle_version,
        model_id=model_id,
    )


def resolve_semantic_bundle(model_key: object = DEFAULT_MODEL_KEY, *, root: Path | None = None) -> ModelBundle | None:
    """Product bundle resolution used by Images Search, Semantic Index, and setup UI."""
    key = normalize_model_key(model_key)
    source = configured_download_source(key)
    version = getattr(source, "bundle_version", None) or bundle_version_for_key(key)
    return find_installed_bundle(root, bundle_version=version, model_id=model_id_for_key(key))


def _path_ui_state(
    path: Path,
    *,
    bundle_version: str | None,
    model_id: str | None,
) -> str:
    """ready, pending, or skip. Never hashes."""
    if is_bundle_validation_in_flight(path):
        return "pending"
    cached = peek_cached_bundle(path)
    if isinstance(cached, ModelBundle):
        if _matches_bundle(cached, bundle_version=bundle_version, model_id=model_id):
            return "ready"
        return "skip"
    if isinstance(cached, BaseException):
        return "skip"
    try:
        if path.is_dir() and (path / "manifest.json").is_file():
            return "pending"
    except OSError:
        return "skip"
    return "skip"


def _scan_ui_state(root: Path, *, bundle_version: str | None, model_id: str | None) -> str:
    pending = False
    for candidate in _iter_bundle_dirs(root):
        state = _path_ui_state(
            candidate, bundle_version=bundle_version, model_id=model_id
        )
        if state == "ready":
            return "ready"
        if state == "pending":
            pending = True
    return "pending" if pending else "unavailable"


def product_bundle_ui_state(
    model_key: object = DEFAULT_MODEL_KEY, *, root: Path | None = None
) -> str:
    """Cheap Meaning Search readiness for UI. Never hashes.

    Returns ``ready``, ``pending``, or ``unavailable``.
    """
    key = normalize_model_key(model_key)
    source = configured_download_source(key)
    version = getattr(source, "bundle_version", None) or bundle_version_for_key(key)
    model_id = model_id_for_key(key)
    if root is not None:
        return _scan_ui_state(root, bundle_version=version, model_id=model_id)

    pending = False
    if version:
        state = _path_ui_state(
            get_bundled_semantic_bundle_dir(version),
            bundle_version=version,
            model_id=model_id,
        )
        if state == "ready":
            return "ready"
        if state == "pending":
            pending = True
    state = _scan_ui_state(
        get_bundled_semantic_models_dir(), bundle_version=version, model_id=model_id
    )
    if state == "ready":
        return "ready"
    if state == "pending":
        pending = True
    if version:
        release = _development_release_bundle_dir(version)
        if release is not None:
            state = _path_ui_state(
                release, bundle_version=version or release.name, model_id=model_id
            )
            if state == "ready":
                return "ready"
            if state == "pending":
                pending = True
    state = _scan_ui_state(
        get_semantic_models_dir(), bundle_version=version, model_id=model_id
    )
    if state == "ready":
        return "ready"
    if state == "pending":
        pending = True
    return "pending" if pending else "unavailable"


_warmup_lock = threading.Lock()
_warmup_state: dict[str, dict] = {}


def reset_product_bundle_warmup_for_tests() -> None:
    with _warmup_lock:
        _warmup_state.clear()


def start_product_bundle_warmup(
    model_key: object = DEFAULT_MODEL_KEY,
    *,
    root: Path | None = None,
    on_done: Callable[[ModelBundle | None, BaseException | None], None] | None = None,
) -> None:
    """Validate the product bundle once in the background. Idempotent per key/root."""
    token = f"{normalize_model_key(model_key)}::{root}"
    with _warmup_lock:
        state = _warmup_state.get(token)
        if state is not None and not state["done"]:
            if on_done is not None:
                state["callbacks"].append(on_done)
            return
        if state is not None and state["done"] and state["result"] is not None:
            if on_done is not None:
                on_done(state["result"], state["error"])
            return
        state = {
            "done": False,
            "result": None,
            "error": None,
            "callbacks": [] if on_done is None else [on_done],
        }
        _warmup_state[token] = state

    def run() -> None:
        bundle: ModelBundle | None = None
        error: BaseException | None = None
        try:
            bundle = resolve_semantic_bundle(model_key, root=root)
        except Exception as exc:
            error = exc
        with _warmup_lock:
            state["done"] = True
            state["result"] = bundle
            state["error"] = error
            callbacks = list(state["callbacks"])
            state["callbacks"].clear()
        for callback in callbacks:
            try:
                callback(bundle, error)
            except Exception:
                pass

    threading.Thread(
        target=run, name="OpenCLIPBundleValidation", daemon=True
    ).start()


class BundleInstaller:
    def __init__(self, source: DownloadSource, root: Path | None = None):
        self.source = source
        self.root = root or get_semantic_models_dir()

    def describe(self) -> tuple[dict, int]:
        manifest = self.source.manifest()
        return manifest, int(manifest["total_size_bytes"])

    def install(
        self,
        *,
        on_progress: Callable[[InstallProgress], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ModelBundle:
        manifest, total = self.describe()
        version = str(manifest["bundle_version"])
        if not version or version in {".", ".."} or Path(version).name != version:
            raise ModelCorruptError("Model manifest contains an invalid bundle version.")
        target = self.root / version
        if target.is_dir():
            try:
                bundle = load_bundle(target, use_cache=False)
                if bundle.identity.model_id == str(manifest["model_id"]):
                    return bundle
            except (ModelNotInstalledError, ModelCorruptError):
                pass

        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".installing-{uuid.uuid4().hex}"
        staging.mkdir()
        downloaded = 0
        try:
            entries = manifest["files"]
            for entry in entries:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Download cancelled.")
                relative = Path(entry["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ModelCorruptError("Model manifest contains an unsafe path.")
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with self.source.open_file(entry) as response, destination.open("wb") as output:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("Download cancelled.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if on_progress is not None:
                            on_progress(InstallProgress(downloaded, total, str(relative)))
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # This is the existing authoritative size + SHA-256 validation.
            load_bundle(staging, use_cache=False)
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
            return load_bundle(target, use_cache=False)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
