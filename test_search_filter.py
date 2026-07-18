from app.utils.search_filter import image_matches_search


def test_empty_query_matches_all():
    assert image_matches_search("ChromeExtension_001.png", ["Error"], "") is True
    assert image_matches_search("ChromeExtension_001.png", ["Error"], "   ") is True


def test_filename_search():
    assert image_matches_search("ChromeExtension_001.png", [], "chrome") is True
    assert image_matches_search("ChromeExtension_001.png", [], "001") is True
    assert image_matches_search("ChromeExtension_001.png", [], "Firefox") is False


def test_tag_search():
    assert image_matches_search("Default_001.png", ["Chrome", "Error"], "error") is True
    assert image_matches_search("Default_001.png", ["Chrome", "Error"], "chrome") is True
    assert image_matches_search("Default_001.png", ["Chrome", "Error"], "firefox") is False


def test_filename_or_tag():
    assert image_matches_search("ChromeExtension_001.png", ["Bug"], "bug") is True
    assert image_matches_search("Default_001.png", ["Chrome"], "default") is True


if __name__ == "__main__":
    test_empty_query_matches_all()
    test_filename_search()
    test_tag_search()
    test_filename_or_tag()
    print("All search filter tests passed.")
