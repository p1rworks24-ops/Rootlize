from app.utils.view_mode import (
    DEFAULT_THUMBNAIL_MODE,
    normalize_thumbnail_mode,
)


def test_normalize_thumbnail_mode():
    assert normalize_thumbnail_mode("large") == "large"
    assert normalize_thumbnail_mode("medium") == "medium"
    assert normalize_thumbnail_mode("small") == "small"
    assert normalize_thumbnail_mode("details") == "small"
    assert normalize_thumbnail_mode("unknown") == DEFAULT_THUMBNAIL_MODE
    assert normalize_thumbnail_mode(None) == DEFAULT_THUMBNAIL_MODE


if __name__ == "__main__":
    test_normalize_thumbnail_mode()
    print("All view mode tests passed.")
