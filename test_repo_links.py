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


def test_default_capixe_repo_configured():
    assert github_repo_configured()
    assert github_repo_url() == "https://github.com/p1rworks24-ops/Rootlize"
    assert APP_GITHUB_URL == github_repo_url()
    assert github_issues_url() == "https://github.com/p1rworks24-ops/Rootlize/issues"
    assert resolve_feedback_url("feedback") == github_issues_url()
    assert (
        resolve_feedback_url("bug")
        == "https://github.com/p1rworks24-ops/Rootlize/issues/new?template=bug_report.yml"
    )
    assert (
        resolve_feedback_url("feature")
        == "https://github.com/p1rworks24-ops/Rootlize/issues/new"
        "?template=feature_request.yml"
    )
    assert github_bug_report_url() == resolve_feedback_url("bug")
    assert github_feature_request_url() == resolve_feedback_url("feature")


def test_unconfigured_matches_host_root(monkeypatch):
    monkeypatch.setattr(links, "GITHUB_OWNER", "")
    monkeypatch.setattr(links, "GITHUB_REPO", "")
    assert not links.github_repo_configured()
    assert links.github_repo_url() == "https://github.com/"
    assert links.github_issues_url() == links.github_repo_url()
    assert links.resolve_feedback_url("feedback") == links.github_issues_url()
    assert links.resolve_feedback_url("bug") == links.github_issues_url()
    assert links.resolve_feedback_url("feature") == links.github_issues_url()


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


def test_explicit_override_wins(monkeypatch):
    monkeypatch.setattr(links, "GITHUB_OWNER", "dev-org")
    monkeypatch.setattr(links, "GITHUB_REPO", "AutoRunner")
    monkeypatch.setattr(
        links, "APP_URL_REPORT_BUG", "https://example.com/custom-bug"
    )
    assert links.resolve_feedback_url("bug") == "https://example.com/custom-bug"
