import tempfile
import time
from pathlib import Path

from app.utils.sort_order import (
    SORT_FILENAME_ASC,
    SORT_FILENAME_DESC,
    SORT_MODIFIED_ASC,
    SORT_MODIFIED_DESC,
    normalize_sort_mode,
    should_insert_before,
    sort_png_files,
)


def _touch(path: Path, delay: float = 0.0) -> Path:
    if delay:
        time.sleep(delay)
    path.write_bytes(b"png")
    return path


def test_normalize_sort_mode():
    assert normalize_sort_mode("modified_desc") == "modified_desc"
    assert normalize_sort_mode("unknown") == "modified_desc"
    assert normalize_sort_mode(None) == "modified_desc"


def test_sort_by_filename():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        b = _touch(root / "b.png")
        a = _touch(root / "a.png")
        c = _touch(root / "c.png")

        asc = sort_png_files([b, a, c], SORT_FILENAME_ASC)
        assert [p.name for p in asc] == ["a.png", "b.png", "c.png"]

        desc = sort_png_files([b, a, c], SORT_FILENAME_DESC)
        assert [p.name for p in desc] == ["c.png", "b.png", "a.png"]


def test_sort_by_modified_time():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        older = _touch(root / "older.png")
        newer = _touch(root / "newer.png", delay=0.05)

        newest_first = sort_png_files([older, newer], SORT_MODIFIED_DESC)
        assert [p.name for p in newest_first] == ["newer.png", "older.png"]

        oldest_first = sort_png_files([older, newer], SORT_MODIFIED_ASC)
        assert [p.name for p in oldest_first] == ["older.png", "newer.png"]


def test_should_insert_before():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = _touch(root / "a.png")
        b = _touch(root / "b.png")

        assert should_insert_before(a, b, SORT_FILENAME_ASC) is True
        assert should_insert_before(b, a, SORT_FILENAME_ASC) is False
        assert should_insert_before(b, a, SORT_FILENAME_DESC) is True


if __name__ == "__main__":
    test_normalize_sort_mode()
    test_sort_by_filename()
    test_sort_by_modified_time()
    test_should_insert_before()
    print("All sort order tests passed.")
