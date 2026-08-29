"""Snapshot Capixe user state, reset to a first-run machine, or restore.

Live paths:
  %LOCALAPPDATA%\\Capixe   analysis index, tour, local AI usage
  %APPDATA%\\Capixe        config / tags / automations
  Windows Credential Manager target Capixe/auth/session

Snapshots stay on this PC only:
  %LOCALAPPDATA%\\Capixe\\state-snapshots\\<stamp>\\

Examples:
  .build-venv\\Scripts\\python.exe tools\\reset_first_user_state.py snapshot-and-reset
  .build-venv\\Scripts\\python.exe tools\\reset_first_user_state.py restore
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.auth.credentials import TARGET_NAME, WindowsCredentialStore, _dump_session, _load_session
from app.paths import get_app_data_dir, get_local_app_data_dir
from app.utils.workspace import DEFAULT_FOLDER

AUTH_FILE = "auth-session.json"
MANIFEST_FILE = "MANIFEST.json"
SNAPSHOT_DIRNAME = "state-snapshots"

LOCAL_FILES = (
    "ocr-index.sqlite3",
    "ocr-index.sqlite3-wal",
    "ocr-index.sqlite3-shm",
    "ai-usage.sqlite3",
    "ai-usage.sqlite3-wal",
    "ai-usage.sqlite3-shm",
    "ai-usage-status.json",
    "entitlement-cache.json",
    "prototype-tour.json",
    "prototype-feedback.jsonl",
)

ROAMING_FILES = (
    "config.json",
    "tags.json",
    "automations.json",
)

ANALYSIS_FILES = (
    "ocr-index.sqlite3",
    "ocr-index.sqlite3-wal",
    "ocr-index.sqlite3-shm",
)

USAGE_FILES = (
    "ai-usage.sqlite3",
    "ai-usage.sqlite3-wal",
    "ai-usage.sqlite3-shm",
    "ai-usage-status.json",
    "entitlement-cache.json",
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _snapshots_root() -> Path:
    return get_local_app_data_dir() / SNAPSHOT_DIRNAME


def _copy_if_exists(src: Path, dest: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def _remove_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def _capixe_running() -> list[int]:
    if sys.platform != "win32":
        return []
    import subprocess

    raw = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process Capixe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
        capture_output=True,
        text=True,
        check=False,
    )
    ids: list[int] = []
    for line in raw.stdout.splitlines():
        text = line.strip()
        if text.isdigit():
            ids.append(int(text))
    return ids


def _stop_capixe() -> None:
    ids = _capixe_running()
    if not ids:
        return
    import subprocess

    subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Process Capixe -ErrorAction SilentlyContinue | Stop-Process -Force"],
        check=False,
    )


def _snapshot_auth(dest: Path) -> bool:
    store = WindowsCredentialStore()
    session = store.load()
    if session is None:
        return False
    (dest / AUTH_FILE).write_text(_dump_session(session), encoding="utf-8")
    return True


def _restore_auth(src: Path) -> bool:
    path = src / AUTH_FILE
    if not path.is_file():
        WindowsCredentialStore().clear()
        return False
    session = _load_session(path.read_text(encoding="utf-8"))
    if session is None:
        return False
    WindowsCredentialStore().save(session)
    return True


def snapshot(stamp: str | None = None) -> Path:
    dest = _snapshots_root() / (stamp or _stamp())
    dest.mkdir(parents=True, exist_ok=True)
    local = get_local_app_data_dir()
    roam = get_app_data_dir()
    copied: list[str] = []
    for name in LOCAL_FILES:
        if _copy_if_exists(local / name, dest / "local" / name):
            copied.append(f"local/{name}")
    for name in ROAMING_FILES:
        if _copy_if_exists(roam / name, dest / "roaming" / name):
            copied.append(f"roaming/{name}")
    auth_saved = _snapshot_auth(dest)
    manifest = {
        "stamp": dest.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "local_root": str(local),
        "roaming_root": str(roam),
        "auth_target": TARGET_NAME,
        "auth_saved": auth_saved,
        "copied": copied,
    }
    (dest / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    pointer = _snapshots_root() / "LATEST.txt"
    pointer.write_text(dest.name + "\n", encoding="utf-8")
    return dest


def _latest_stamp() -> str:
    pointer = _snapshots_root() / "LATEST.txt"
    if pointer.is_file():
        stamp = pointer.read_text(encoding="utf-8").strip()
        if stamp and (_snapshots_root() / stamp / MANIFEST_FILE).is_file():
            return stamp
    stamps = sorted(
        path.name
        for path in _snapshots_root().iterdir()
        if path.is_dir() and (path / MANIFEST_FILE).is_file()
    )
    if not stamps:
        raise SystemExit("No Capixe state snapshot found.")
    return stamps[-1]


def restore(stamp: str | None = None) -> Path:
    dest = _snapshots_root() / (stamp or _latest_stamp())
    if not (dest / MANIFEST_FILE).is_file():
        raise SystemExit(f"Snapshot not found: {dest}")
    local = get_local_app_data_dir()
    roam = get_app_data_dir()
    for name in LOCAL_FILES:
        src = dest / "local" / name
        live = local / name
        if src.is_file():
            _copy_if_exists(src, live)
        else:
            _remove_if_exists(live)
    for name in ROAMING_FILES:
        src = dest / "roaming" / name
        live = roam / name
        if src.is_file():
            _copy_if_exists(src, live)
        else:
            _remove_if_exists(live)
    _restore_auth(dest)
    return dest


def reset_first_user() -> None:
    local = get_local_app_data_dir()
    roam = get_app_data_dir()
    for name in ANALYSIS_FILES:
        _remove_if_exists(local / name)
    for name in USAGE_FILES:
        _remove_if_exists(local / name)
    _remove_if_exists(local / "prototype-tour.json")
    _remove_if_exists(local / "prototype-feedback.jsonl")
    WindowsCredentialStore().clear()
    config_path = roam / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["ask_ai_external_processing_consented"] = False
        config["ask_ai_consent_notice_version"] = 0
        config["selected_folder"] = ""
        config["current_folder"] = DEFAULT_FOLDER
        config["save_folder"] = DEFAULT_FOLDER
        config["favorite_folders"] = []
        config["recent_folders"] = []
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    _remove_if_exists(roam / "automations.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "snapshot-and-reset", "reset", "restore"))
    parser.add_argument("--id", dest="stamp", default="", help="Snapshot id (restore / snapshot name)")
    parser.add_argument("--keep-running", action="store_true", help="Do not stop Capixe.exe")
    args = parser.parse_args()
    if not args.keep_running:
        _stop_capixe()
    if args.action == "snapshot":
        dest = snapshot(args.stamp or None)
        print(f"Snapshot: {dest}")
        return 0
    if args.action == "snapshot-and-reset":
        dest = snapshot(args.stamp or None)
        reset_first_user()
        print(f"Snapshot: {dest}")
        print("Live state: signed out, tutorial not started, analysis index cleared.")
        return 0
    if args.action == "reset":
        reset_first_user()
        print("Live state: signed out, tutorial not started, analysis index cleared.")
        return 0
    dest = restore(args.stamp or None)
    print(f"Restored: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
