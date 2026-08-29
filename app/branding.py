"""Product naming and release identity — single source for UI and logging.

GitHub repository URLs live in app.repo_links (kept separate on purpose).

Public display names (APP_NAME / DIST_NAME) must never be used to build
user-data paths. Existing installs keep DATA_DIR_NAME = "Capixe".
"""

from __future__ import annotations

from app.repo_links import (
    APP_GITHUB_URL,
    APP_URL_REPORT_BUG,
    APP_URL_REQUEST_FEATURE,
    APP_URL_SEND_FEEDBACK,
    github_issues_url,
    resolve_feedback_url,
)

# ---------------------------------------------------------------------------
# Canonical brand / release constants (edit here only)
# ---------------------------------------------------------------------------
APP_NAME = "Rootlize"
# Writable Windows folders for existing users. Never derive from APP_NAME.
DATA_DIR_NAME = "Capixe"
# Public onedir folder and EXE basename (dist/Rootlize/Rootlize.exe).
DIST_NAME = APP_NAME
APP_VERSION = "0.1.0-preview"
RELEASE_CHANNEL = "Prototype Preview"
TAGLINE = "Your Local Workspace."
SUPPORTING_MESSAGE = (
    "Find, organize, and work with the images on your PC — "
    "without moving them to the cloud."
)


def _display_version(version: str, channel: str) -> str:
    """Public version line for About / splash (channel is metadata, not required)."""
    ver = (version or "").strip()
    if not ver:
        return (channel or "").strip()
    # Prefer a leading "v" for preview tags so UI matches Release naming.
    if not ver.lower().startswith("v"):
        ver = f"v{ver}"
    return ver


DISPLAY_VERSION = _display_version(APP_VERSION, RELEASE_CHANNEL)

# Compact / shell variants derived from APP_NAME
APP_NAME_SHORT = "RL"
APP_NAME_SIDEBAR = APP_NAME
APP_LOGGER_NAME = APP_NAME

# Legal (About footer) — keep in sync with root LICENSE / README
APP_LICENSE = "License: Private and proprietary. All rights reserved."
APP_COPYRIGHT = f"Copyright © 2026 {APP_NAME}. All rights reserved."

# ---------------------------------------------------------------------------
# Backward-compatible aliases (same values — do not diverge)
# ---------------------------------------------------------------------------
APP_TAGLINE = TAGLINE
APP_SUPPORTING_MESSAGE = SUPPORTING_MESSAGE
APP_VERSION_LABEL = DISPLAY_VERSION
APP_PREVIEW_BADGE = DISPLAY_VERSION
