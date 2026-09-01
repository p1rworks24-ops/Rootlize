"""GitHub README and Release notes must match the current Prototype contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
NOTES = (ROOT / "docs" / "github-publish" / "RELEASE_NOTES_v0.1.0-preview.md").read_text(
    encoding="utf-8"
)
PUBLIC = README.split("## Development", 1)[0]


def test_github_public_copy_matches_prototype() -> None:
    lower = " ".join((PUBLIC + "\n" + NOTES).split()).lower()
    assert "sign in to start" not in lower
    assert "find → narrow" not in lower
    assert "find → organize → automate" in lower
    assert "no sign-up required" in lower
    assert "v0.1.0-preview" in PUBLIC
    assert "windows 10" in lower
    assert "guest" in NOTES.lower()
    assert "smartscreen" in lower
    assert "Rootlize-v0.1.0-preview-win64.zip" in PUBLIC
    assert "v0.1.0-preview.1" in PUBLIC
    assert "Capture" not in PUBLIC
    assert "macOS is not available" in PUBLIC
    assert "AI usage is limited" in PUBLIC
