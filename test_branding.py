"""Product name and release identity: Rootlize display, Capixe data dirs."""

from __future__ import annotations

from app import branding
from app.branding import (
    APP_COPYRIGHT,
    APP_GITHUB_URL,
    APP_LICENSE,
    APP_LOGGER_NAME,
    APP_NAME,
    APP_NAME_SHORT,
    APP_NAME_SIDEBAR,
    APP_PREVIEW_BADGE,
    APP_SUPPORTING_MESSAGE,
    APP_TAGLINE,
    APP_VERSION,
    APP_VERSION_LABEL,
    DATA_DIR_NAME,
    DISPLAY_VERSION,
    DIST_NAME,
    RELEASE_CHANNEL,
    SUPPORTING_MESSAGE,
    TAGLINE,
    github_issues_url,
    resolve_feedback_url,
)
from app.config import DEFAULT_CONFIG
from app.i18n import t


def test_canonical_brand_constants():
    assert APP_NAME == "Rootlize"
    assert DATA_DIR_NAME == "Capixe"
    assert DIST_NAME == "Rootlize"
    assert APP_NAME != DATA_DIR_NAME
    assert APP_VERSION == "0.1.0-preview"
    assert RELEASE_CHANNEL == "Prototype Preview"
    assert TAGLINE == "Your Local Workspace."
    assert SUPPORTING_MESSAGE == (
        "Find, organize, and work with the images on your PC — "
        "without moving them to the cloud."
    )
    assert DISPLAY_VERSION == "v0.1.0-preview"


def test_display_version_strips_empty_channel():
    assert branding._display_version("1.2.3", "") == "v1.2.3"
    assert branding._display_version("1.2.3", "  ") == "v1.2.3"
    assert branding._display_version("", "Beta") == "Beta"
    assert branding._display_version("v1.0.0", "Beta") == "v1.0.0"
    assert branding._display_version("0.1.0-preview", "Prototype Preview") == (
        "v0.1.0-preview"
    )


def test_compat_aliases_match_canonical():
    assert APP_TAGLINE == TAGLINE
    assert APP_SUPPORTING_MESSAGE == SUPPORTING_MESSAGE
    assert APP_VERSION_LABEL == DISPLAY_VERSION
    assert APP_PREVIEW_BADGE == DISPLAY_VERSION
    assert APP_NAME_SIDEBAR == APP_NAME
    assert APP_LOGGER_NAME == APP_NAME
    assert APP_NAME_SHORT == "RL"
    assert APP_LICENSE.startswith("License:")
    assert "proprietary" in APP_LICENSE.lower()
    assert "All rights reserved" in APP_LICENSE
    assert APP_COPYRIGHT == "Copyright © 2026 Rootlize. All rights reserved."
    assert APP_NAME in APP_COPYRIGHT
    assert "private" in APP_LICENSE.lower()
    assert APP_GITHUB_URL.startswith("https://")
    assert APP_GITHUB_URL == "https://github.com/p1rworks24-ops/Rootlize"
    assert resolve_feedback_url("bug") == (
        "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=bug_report.yml"
    )
    assert DEFAULT_CONFIG["window_title"] == APP_NAME
    assert t("app.name") == APP_NAME
    assert t("nav.brand") == APP_NAME
    assert t("nav.brand_short") == APP_NAME_SHORT
    assert t("nav.about") == "About"
    assert t("images.ai.role_assistant") == APP_NAME
    assert t("tour.welcome.title") == f"Welcome to {APP_NAME}"
    assert t("tour.welcome.body") == SUPPORTING_MESSAGE
    assert "Capixe" not in t("tour.welcome.body")
    assert "Capixe" not in t("images.ai.placeholder")
    assert "%LOCALAPPDATA%\\Capixe\\" in t("settings.developer_search.hint")
    assert t("images.ai.role_assistant") == APP_NAME
    assert t("tour.welcome.title") == f"Welcome to {APP_NAME}"
    assert t("tour.welcome.body") == SUPPORTING_MESSAGE
    assert "Capixe" not in t("tour.welcome.body")
    assert "Capixe" not in t("images.ai.placeholder")
    assert "%LOCALAPPDATA%\\Capixe\\" in t("settings.developer_search.hint")
