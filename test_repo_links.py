"""GitHub repo links are centralized in app.repo_links."""

from __future__ import annotations

import app.repo_links as links
from app.repo_links import (
    APP_GITHUB_URL,
    github_bug_report_url,
    github_feature_request_url,
    github_issues_url,
    github_repo_configured,
    github_repo_url,
    resolve_feedback_url,
)


def test_unconfigured_matches_host_root():
    assert not github_repo_configured()
    assert github_repo_url() == "https://github.com/"
    assert APP_GITHUB_URL == github_repo_url()
    assert github_issues_url() == github_repo_url()
    # Until owner/repo are set, form links fall back to the same host root
    assert resolve_feedback_url("feedback") == github_issues_url()
    assert resolve_feedback_url("bug") == github_issues_url()
    assert resolve_feedback_url("feature") == github_issues_url()


def test_configured_repo_derives_all_urls(monkeypatch):
    monkeypatch.setattr(links, "GITHUB_OWNER", "dev-org")
    monkeypatch.setattr(links, "GITHUB_REPO", "AutoRunner")

    assert links.github_repo_configured()
    assert links.github_repo_url() == "https://github.com/dev-org/AutoRunner"
    assert links.github_issues_url() == "https://github.com/dev-org/AutoRunner/issues"
    assert (
        links.github_bug_report_url()
        == "https://github.com/dev-org/AutoRunner/issues/new?template=bug_report.yml"
    )
    assert (
        links.github_feature_request_url()
        == "https://github.com/dev-org/AutoRunner/issues/new"
        "?template=feature_request.yml"
    )
    assert links.resolve_feedback_url("bug") == links.github_bug_report_url()
    assert links.resolve_feedback_url("feature") == links.github_feature_request_url()
    assert links.resolve_feedback_url("feedback") == links.github_issues_url()


def test_capixe_migration_is_owner_repo_only(monkeypatch):
    """Publishing Capixe should only require changing owner/repo constants."""
    monkeypatch.setattr(links, "GITHUB_OWNER", "dev-org")
    monkeypatch.setattr(links, "GITHUB_REPO", "Capixe")
    assert links.github_repo_url() == "https://github.com/dev-org/Capixe"
    assert "bug_report.yml" in links.github_bug_report_url()
    assert "feature_request.yml" in links.github_feature_request_url()


def test_explicit_override_wins(monkeypatch):
    monkeypatch.setattr(links, "GITHUB_OWNER", "dev-org")
    monkeypatch.setattr(links, "GITHUB_REPO", "AutoRunner")
    monkeypatch.setattr(
        links, "APP_URL_REPORT_BUG", "https://example.com/custom-bug"
    )
    assert links.resolve_feedback_url("bug") == "https://example.com/custom-bug"
