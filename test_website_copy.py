"""Public landing-page copy must match the current Prototype contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEBSITE = ROOT / "website"
INDEX = WEBSITE / "index.html"
CONTENT = WEBSITE / "js" / "content.js"
MAIN = WEBSITE / "js" / "main.js"
PRIVACY = WEBSITE / "privacy" / "index.html"
TERMS = WEBSITE / "terms" / "index.html"

ZIP_NAME = "Rootlize-v0.1.0-preview-win64.zip"
ZIP_URL = (
    "https://github.com/p1rworks24-ops/Rootlize/releases/download/"
    f"v0.1.0-preview.1/{ZIP_NAME}"
)


def _read(*parts: str) -> str:
    return Path(WEBSITE, *parts).read_text(encoding="utf-8")


def test_public_pages_do_not_use_capixe() -> None:
    for path in (INDEX, CONTENT, PRIVACY, TERMS, MAIN):
        assert "Capixe" not in path.read_text(encoding="utf-8")


def test_landing_does_not_require_signup() -> None:
    index = INDEX.read_text(encoding="utf-8")
    content = CONTENT.read_text(encoding="utf-8")
    privacy = PRIVACY.read_text(encoding="utf-8")
    joined = "\n".join((index, content, privacy)).lower()

    assert "sign-in required" not in joined
    assert "sign in to start" not in joined
    assert "opens on a sign-in screen" not in joined
    assert "create account" not in joined
    assert "no sign-up required" in index.lower()
    assert "does not require sign-up" in content.lower()
    assert "does not require sign-up" in privacy.lower()


def test_hero_and_cta_match_prototype() -> None:
    index = INDEX.read_text(encoding="utf-8")
    content = CONTENT.read_text(encoding="utf-8")

    assert "Download for Windows" in index
    assert "Download Rootlize for Windows" in index
    assert "See how it works" in index
    assert "Give feedback" in index
    assert "Download Preview" not in index
    assert ZIP_URL in index
    assert ZIP_NAME in content
    assert "v0.1.0-preview" in index
    assert "Prototype Preview" in index
    assert "Search should be the beginning of the workflow" in index
    assert "Find. Organize. Automate." in index
    assert "Find. Narrow. Act." not in index


def test_download_js_uses_live_zip_without_waiting() -> None:
    main = MAIN.read_text(encoding="utf-8")
    content = CONTENT.read_text(encoding="utf-8")
    assert "canonicalDownloadUrl" in main
    assert ZIP_NAME in content
    assert "v0.1.0-preview.1" in content
    assert live_url_is_https_zip(content)


def live_url_is_https_zip(content: str) -> bool:
    assert ZIP_URL in content
    return True


def test_features_match_current_scope() -> None:
    index = INDEX.read_text(encoding="utf-8").lower()
    content = CONTENT.read_text(encoding="utf-8").lower()
    joined = index + "\n" + content

    assert "meaning search" in joined
    assert "ask ai" in joined
    assert "favorite" in joined
    assert "tag" in joined
    assert "workflow" in joined
    assert "select" in joined and "search" in joined and "action" in joined
    assert "consent" in joined
    assert "does not resend images" in joined or "does not resend images every time" in joined
    assert "capture" not in index
    assert "mac version" in content
    assert "windows 10" in joined
    assert "not yet" in content


def test_faq_covers_required_questions() -> None:
    content = CONTENT.read_text(encoding="utf-8").lower()
    assert 'q: "is rootlize free?"' in content
    assert "ai usage is limited" in content
    assert 'q: "do i need an account?"' in content
    assert "does not require sign-up" in content
    assert 'q: "does rootlize upload my images?"' in content
    assert "not a cloud library" in content
    assert "first analysis may send" in content
    assert 'q: "is there a mac version?"' in content
    assert "windows 10 / windows 11" in content
    assert 'q: "is this a finished product?"' in content
    assert "prototype preview (v0.1.0-preview)" in content
    assert "more info" in content


def test_privacy_matches_ai_consent() -> None:
    privacy = " ".join(PRIVACY.read_text(encoding="utf-8").split()).lower()
    assert "until you agree" in privacy
    assert "does not start sending images" in privacy
    assert "first analysis may send" in privacy
    assert "does not resend images on every search" in privacy
    assert "usage is limited" in privacy
    assert "guest" in privacy
    assert "never send" not in privacy
    assert "never uploads" not in privacy
