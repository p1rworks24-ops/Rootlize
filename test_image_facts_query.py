from app.image_facts.query import is_search_wrapper_condition, meaning_query_target


def test_meaning_query_target_strips_library_search_wrappers():
    assert meaning_query_target("google chrome images") == "google chrome"
    assert meaning_query_target("search for google chrome images from this folder") == "google chrome"
    assert meaning_query_target("images of a dog") == "dog"
    assert meaning_query_target("dog images") == "dog"
    assert meaning_query_target("Find screenshots of VS Code") == "VS Code"


def test_meaning_query_target_keeps_named_products_and_relations():
    assert meaning_query_target("screenshot manager") == "screenshot manager"
    assert meaning_query_target("Google Chrome in Windows desktop") == "Google Chrome in Windows desktop"
    assert meaning_query_target("sitting orange brown dog") == "sitting orange brown dog"
    assert meaning_query_target("image gallery") == "image gallery"
    assert meaning_query_target("empty folder") == "empty folder"


def test_meaning_query_target_keeps_generic_image_requests():
    assert meaning_query_target("related images") == "related images"
    assert meaning_query_target("all images") == "all images"
    assert meaning_query_target("images") == "images"


def test_images_is_wrapper_except_when_it_is_the_target():
    assert is_search_wrapper_condition("images", "google chrome images") is True
    assert is_search_wrapper_condition("Google Chrome", "google chrome images") is False
    assert is_search_wrapper_condition("folder", "search for chrome from this folder") is True
    assert is_search_wrapper_condition("folder", "empty folder") is False
    assert is_search_wrapper_condition("screenshot", "screenshot manager") is False
