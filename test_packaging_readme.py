"""Public ZIP README must match the current Prototype contract."""

from pathlib import Path

README = Path("packaging/README.txt").read_text(encoding="utf-8")


def test_zip_readme_matches_public_prototype():
    text = " ".join(README.split())
    lower = text.lower()
    assert "sign in to start" not in lower
    assert "ask ai needs sign-in" not in lower
    assert "sign-in is not required" in lower
    assert "guest" in lower
    assert "usage limit" in lower
    assert "consent" in lower
    assert "does not send images on every search" in lower
    assert "v0.1.0-preview" in README
    assert "Windows 10" in README
    assert "Rootlize.exe" in README
    assert "_internal" in README
    assert "Capixe" not in README
    assert "Capture" not in README
