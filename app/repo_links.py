"""
Central GitHub repository identity and public links.

Edit GITHUB_OWNER / GITHUB_REPO in this file only when the GitHub
identity changes. Do not hardcode github.com URLs elsewhere in
application code.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Single place to update for repository rename / transfer
# ---------------------------------------------------------------------------
GITHUB_HOST = "https://github.com"

GITHUB_OWNER = "p1rworks24-ops"
GITHUB_REPO = "Rootlize"

# Issue Form file names under .github/ISSUE_TEMPLATE/
GITHUB_BUG_REPORT_TEMPLATE = "bug_report.yml"
GITHUB_FEATURE_REQUEST_TEMPLATE = "feature_request.yml"

# Optional absolute URL overrides (None → derive from owner/repo above).
# Use only if a link must differ from the standard repo / Issues / form URLs.
APP_URL_SEND_FEEDBACK: str | None = None
APP_URL_REPORT_BUG: str | None = None
APP_URL_REQUEST_FEATURE: str | None = None
# ---------------------------------------------------------------------------


def github_repo_configured() -> bool:
    """True when both owner and repo are set (a real repository root)."""
    return bool((GITHUB_OWNER or "").strip() and (GITHUB_REPO or "").strip())


def github_repo_url() -> str:
    """Repository root URL, or GitHub host root when owner/repo are unset."""
    host = (GITHUB_HOST or "https://github.com").rstrip("/")
    if github_repo_configured():
        return f"{host}/{GITHUB_OWNER.strip()}/{GITHUB_REPO.strip()}"
    return f"{host}/"


# Back-compat name used by About / existing tests (derived, not duplicated).
APP_GITHUB_URL = github_repo_url()


def github_issues_url() -> str:
    """Issues list for the configured repo (host root when not configured)."""
    if not github_repo_configured():
        return github_repo_url()
    return f"{github_repo_url().rstrip('/')}/issues"


def github_new_issue_url(*, template: str | None = None) -> str:
    """
    Open the New Issue UI, optionally with an Issue Form template.

    When the repo is not configured, falls back to github_issues_url().
    """
    if not github_repo_configured():
        return github_issues_url()
    base = f"{github_repo_url().rstrip('/')}/issues/new"
    name = (template or "").strip()
    if name:
        return f"{base}?template={name}"
    return base


def github_bug_report_url() -> str:
    """Bug Report Issue Form (or Issues list before the repo URL is set)."""
    return github_new_issue_url(template=GITHUB_BUG_REPORT_TEMPLATE)


def github_feature_request_url() -> str:
    """Feature Request Issue Form (or Issues list before the repo URL is set)."""
    return github_new_issue_url(template=GITHUB_FEATURE_REQUEST_TEMPLATE)


def github_feedback_url() -> str:
    """General feedback destination (Issues list)."""
    return github_issues_url()


def resolve_feedback_url(kind: str) -> str:
    """
    Resolve a feedback action URL.

    kind: \"feedback\" | \"bug\" | \"feature\"
    Explicit APP_URL_* overrides win; otherwise URLs are derived from
    GITHUB_OWNER / GITHUB_REPO (and Issue Form template names).
    """
    overrides = {
        "feedback": APP_URL_SEND_FEEDBACK,
        "bug": APP_URL_REPORT_BUG,
        "feature": APP_URL_REQUEST_FEATURE,
    }
    override = overrides.get(kind)
    if override:
        return override
    if kind == "bug":
        return github_bug_report_url()
    if kind == "feature":
        return github_feature_request_url()
    return github_feedback_url()
