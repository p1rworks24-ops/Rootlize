"""Product name and release identity: Capixe."""

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
    APP_TAGLINE,
    APP_VERSION,
    APP_VERSION_LABEL,
    DISPLAY_VERSION,
    RELEASE_CHANNEL,
    TAGLINE,
    github_issues_url,
    resolve_feedback_url,
)
from app.config import DEFAULT_CONFIG
from app.i18n import t


def test_canonical_brand_constants():
    assert APP_NAME == "Capixe"
    assert APP_VERSION == "0.1.0-preview"
    assert RELEASE_CHANNEL == "Prototype Preview"
    assert TAGLINE == "Capture less. Find more."
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
    assert APP_VERSION_LABEL == DISPLAY_VERSION
    assert APP_PREVIEW_BADGE == DISPLAY_VERSION
    assert APP_NAME_SIDEBAR == APP_NAME
    assert APP_LOGGER_NAME == APP_NAME
    assert APP_NAME_SHORT == "CX"
    assert APP_LICENSE.startswith("License:")
    assert "proprietary" in APP_LICENSE.lower()
    assert "All rights reserved" in APP_LICENSE
    assert APP_COPYRIGHT == "Copyright © 2026 Capixe. All rights reserved."
    assert APP_NAME in APP_COPYRIGHT
    assert "private" in APP_LICENSE.lower()
    assert APP_GITHUB_URL.startswith("https://")
    assert resolve_feedback_url("bug") == github_issues_url()
    assert DEFAULT_CONFIG["window_title"] == APP_NAME
    assert t("app.name") == APP_NAME
    assert t("nav.brand") == APP_NAME
    assert t("nav.brand_short") == APP_NAME_SHORT
    assert t("nav.about") == "About"
