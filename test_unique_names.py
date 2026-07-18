from app.utils.file_copy_name import make_unique_copy_filename
from app.utils.unique_name import make_unique_name


def test_unique_tag_names():
    assert make_unique_name("test", []) == "test"
    assert make_unique_name("test", ["test"]) == "test (1)"
    assert make_unique_name("test", ["test", "test (1)"]) == "test (2)"


def test_unique_copy_filenames():
    assert make_unique_copy_filename("a.png", []) == "a - Copy.png"
    assert make_unique_copy_filename("a.png", ["a.png", "a - Copy.png"]) == "a - Copy (2).png"
    assert (
        make_unique_copy_filename("a.png", ["a.png", "a - Copy.png", "a - Copy (2).png"])
        == "a - Copy (3).png"
    )


if __name__ == "__main__":
    test_unique_tag_names()
    test_unique_copy_filenames()
    print("All unique name tests passed.")
