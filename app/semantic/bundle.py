"""Immutable Semantic model bundle discovery and integrity validation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ModelIdentity
from .worker_errors import ModelCorruptError, ModelNotInstalledError, SemanticWorkerError

ROLES = frozenset({"image_encoder", "text_encoder", "tokenizer", "tokenizer_config", "preprocess_config", "model_config", "license", "notice"})

logger = logging.getLogger("app.semantic.bundle")

_cache_lock = threading.Lock()
_cache: dict[str, ModelBundle | BaseException] = {}
_inflight: dict[str, threading.Event] = {}
_full_validations = 0


@dataclass(frozen=True)
class ModelBundle:
    root: Path
    manifest: dict[str, Any]
    files: dict[str, Path]
    identity: ModelIdentity


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_key(root: Path) -> str:
    try:
        return str(root.resolve())
    except OSError:
        return str(root)


def clear_bundle_validation_cache() -> None:
    """Drop process-wide integrity results. Tests reset this between cases."""
    global _full_validations
    with _cache_lock:
        _cache.clear()
        _inflight.clear()
        _full_validations = 0


def bundle_full_validation_count() -> int:
    with _cache_lock:
        return _full_validations


def peek_cached_bundle(root: Path | None) -> ModelBundle | BaseException | None:
    """Return a cached integrity result without hashing. None if unknown."""
    if root is None:
        return None
    key = _cache_key(root)
    with _cache_lock:
        return _cache.get(key)


def is_bundle_validation_in_flight(root: Path | None) -> bool:
    if root is None:
        return False
    key = _cache_key(root)
    with _cache_lock:
        return key in _inflight


def _running_on_gui_thread() -> bool:
    try:
        from PySide6.QtCore import QCoreApplication, QThread
    except Exception:
        return False
    app = QCoreApplication.instance()
    if app is None:
        return False
    return QThread.currentThread() is app.thread()


def _reject_gui_thread_hash() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if _running_on_gui_thread():
        raise RuntimeError(
            "OpenCLIP integrity validation must not run on the UI thread."
        )


def _validate_bundle(root: Path) -> ModelBundle:
    """Authoritative size + SHA-256 validation. Callers own caching."""
    _reject_gui_thread_hash()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ModelCorruptError("Semantic model manifest is missing.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        embedding = manifest["embedding"]; image = manifest["image"]; runtime = manifest["runtime"]
        dimension = int(embedding["dimension"])
        if (manifest["manifest_schema_version"] != 1 or dimension not in {512, 768}
                or embedding.get("dtype") != "float32" or embedding.get("normalized") is not True):
            raise ValueError
        if int(image["width"]) != 224 or int(image["height"]) != 224 or runtime["name"] != "onnxruntime":
            raise ValueError
        if str(runtime["minimum_version"]) != "1.28.0" or runtime.get("providers") != ["CPUExecutionProvider"]:
            raise SemanticWorkerError("Semantic model runtime is incompatible.", code="MODEL_INCOMPATIBLE")
        entries = manifest["files"]
        if not isinstance(entries, list) or not entries:
            raise ValueError
        files: dict[str, Path] = {}; seen: set[Path] = set(); total = 0
        resolved_root = root.resolve()
        for entry in entries:
            relative = Path(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or entry["role"] not in ROLES:
                raise ValueError
            path = (root / relative).resolve()
            if path in seen or resolved_root not in path.parents or not path.is_file() or path.is_symlink():
                raise ValueError
            size = path.stat().st_size
            if size != int(entry["size_bytes"]) or _sha256(path) != str(entry["sha256"]).lower():
                raise ValueError
            seen.add(path); total += size; files[entry["role"]] = path
        if total != int(manifest["total_size_bytes"]):
            raise ValueError
        identity = ModelIdentity(str(manifest["model_id"]), str(manifest["bundle_version"]), str(manifest["revision"]), int(manifest["pipeline_version"]), dimension=dimension)
        return ModelBundle(root, manifest, files, identity)
    except SemanticWorkerError:
        raise
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise ModelCorruptError("Semantic model bundle failed integrity validation.") from exc


def load_bundle(root: Path | None, *, use_cache: bool = True) -> ModelBundle:
    """Load and fully validate a bundle.

    Full SHA-256 of every declared file runs once per resolved path in this
    process. Later callers share that result. Official build / installer copy
    paths pass ``use_cache=False`` so each check still hashes.
    """
    global _full_validations
    if root is None or not root.is_dir():
        raise ModelNotInstalledError("Semantic model is not installed.")
    if not use_cache:
        started = time.perf_counter()
        with _cache_lock:
            _full_validations += 1
        logger.info("openclip bundle validation start path=%s cached=false", root)
        try:
            bundle = _validate_bundle(root)
        except Exception:
            logger.info(
                "openclip bundle validation failed path=%s elapsed_ms=%.1f cached=false",
                root, (time.perf_counter() - started) * 1000,
            )
            raise
        logger.info(
            "openclip bundle validation ok path=%s elapsed_ms=%.1f cached=false",
            root, (time.perf_counter() - started) * 1000,
        )
        return bundle

    key = _cache_key(root)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            if isinstance(cached, ModelBundle):
                return cached
            raise cached
        event = _inflight.get(key)
        owner = event is None
        if owner:
            event = threading.Event()
            _inflight[key] = event
    if not owner:
        event.wait()
        with _cache_lock:
            cached = _cache[key]
        if isinstance(cached, ModelBundle):
            return cached
        raise cached

    started = time.perf_counter()
    with _cache_lock:
        _full_validations += 1
    logger.info("openclip bundle validation start path=%s cached=miss", root)
    try:
        bundle = _validate_bundle(root)
    except BaseException as exc:
        with _cache_lock:
            _cache[key] = exc
            _inflight.pop(key, None)
        event.set()
        logger.info(
            "openclip bundle validation failed path=%s elapsed_ms=%.1f cached=store",
            root, (time.perf_counter() - started) * 1000,
        )
        raise
    with _cache_lock:
        _cache[key] = bundle
        _inflight.pop(key, None)
    event.set()
    logger.info(
        "openclip bundle validation ok path=%s elapsed_ms=%.1f cached=store",
        root, (time.perf_counter() - started) * 1000,
    )
    return bundle
