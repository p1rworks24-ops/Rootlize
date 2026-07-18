"""Tag display helpers (# prefix)."""

from app.utils.tag_format import format_tag, format_tags, normalize_tag


def test_normalize_strips_hash():
    assert normalize_tag("#debug") == "debug"
    assert normalize_tag("##foo") == "foo"
    assert normalize_tag("  bar  ") == "bar"


def test_format_tag_adds_hash():
    assert format_tag("debug") == "#debug"
    assert format_tag("#debug") == "#debug"
    assert format_tag("") == ""


def test_format_tags_join():
    assert format_tags(["a", "b"]) == "#a, #b"
    assert format_tags([]) == "-"
    assert format_tags(None, empty="No tags") == "No tags"
