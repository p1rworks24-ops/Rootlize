from __future__ import annotations

from pathlib import Path

import pytest

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.ocr.search_service import MAX_LIMIT, OCRSearchService


@pytest.fixture
def repository(tmp_path):
    database = OCRDatabase(tmp_path / "db" / "index.sqlite3").open()
    yield OCRRepository(database)
    database.close()


def add_image(repository, folder: Path, name: str, *, mtime=1, tags=(), text=None, status="ready"):
    path = folder / name
    image = repository.upsert_image(path, size_bytes=10, mtime_ns=mtime)
    repository.update_tags(image.image_id, list(tags))
    repository.save_ocr_document(image.image_id, status=status, ocr_text=text)
    return image


def test_short_japanese_and_ascii_queries_use_substring_mode(repository, tmp_path):
    folder = tmp_path / "日本語 folder"
    add_image(repository, folder, "料金表.png", tags=["税"], text="駅 UI DB C# 設定")
    for query in ("税", "表", "駅", "AI", "UI", "DB", "C#", "料金", "設定"):
        page = repository.search_images(query, folder_path=folder)
        if query == "AI":
            assert page.total_count == 0
        else:
            assert page.total_count == 1
        assert page.query_mode == "substring"


def test_three_plus_characters_use_fts_and_special_characters_are_safe(repository, tmp_path):
    folder = tmp_path / "shots"
    content = r"Python QMainWindow config.get localhost:3000 C:\Users NullReferenceException v0.1.0 user@example.com snake_case dashed-value"
    add_image(repository, folder, "technical.png", text=content)
    for query in ("Python", "QMainWindow", "config.get", "localhost:3000", r"C:\Users", "NullReferenceException", "v0.1.0", "user@example.com", "snake_case", "dashed-value"):
        page = repository.search_images(query, folder_path=folder)
        assert page.query_mode == "fts5_trigram"
        assert page.total_count == 1, query
        assert page.results[0].matched_ocr


def test_ranking_is_explainable_and_stable(repository, tmp_path):
    folder = tmp_path / "shots"
    add_image(repository, folder, "python.png", mtime=1)
    add_image(repository, folder, "other.png", mtime=99, tags=["python"])
    add_image(repository, folder, "python-error.png", mtime=2)
    add_image(repository, folder, "tag-prefix.png", mtime=3, tags=["python-tools"])
    add_image(repository, folder, "my-python-log.png", mtime=4)
    add_image(repository, folder, "tag-part.png", mtime=5, tags=["my-python"])
    add_image(repository, folder, "ocr-exact.png", mtime=6, text="python")
    add_image(repository, folder, "ocr-part.png", mtime=7, text="cpython runtime")
    page = repository.search_images("python", folder_path=folder)
    assert [item.filename for item in page.results] == [
        "python.png", "other.png", "python-error.png", "tag-prefix.png",
        "my-python-log.png", "tag-part.png", "ocr-exact.png", "ocr-part.png",
    ]
    assert [item.score for item in page.results] == sorted([item.score for item in page.results], reverse=True)
    assert page.results[0].filename_match_type == "exact"
    assert page.results[1].tag_match_type == "exact"
    assert page.results[-1].ocr_match_type == "substring"


def test_multiple_match_fields_are_returned_and_receive_bonus(repository, tmp_path):
    folder = tmp_path / "shots"
    add_image(repository, folder, "python-note.png", tags=["python"], text="python guide")
    result = repository.search_images("python", folder_path=folder).results[0]
    assert result.matched_fields == ("filename", "tags", "image_content")
    # Exact tag (90) is the strongest match, plus two extra-field bonuses (10).
    assert result.score == 100


def test_ocr_snippet_is_short_plain_text_around_match(repository, tmp_path):
    folder = tmp_path / "shots"
    text = "prefix " * 30 + "class MainWindow(QMainWindow):\n    pass" + " suffix" * 30
    add_image(repository, folder, "code.png", text=text)
    result = repository.search_images("QMainWindow", folder_path=folder).results[0]
    assert result.ocr_snippet is not None
    assert "QMainWindow" in result.ocr_snippet
    assert "\n" not in result.ocr_snippet
    assert len(result.ocr_snippet) <= 162
    assert result.ocr_snippet.startswith("…") and result.ocr_snippet.endswith("…")


def test_non_ready_ocr_is_excluded_but_filename_and_tags_remain_searchable(repository, tmp_path):
    folder = tmp_path / "shots"
    for index, status in enumerate(("pending", "running", "stale", "failed")):
        add_image(repository, folder, f"{status}-needle.png", mtime=index, tags=["needle"], text="secret needle", status=status)
    page = repository.search_images("needle", folder_path=folder)
    assert page.total_count == 4
    assert {result.ocr_status for result in page.results} == {"pending", "running", "stale", "failed"}
    assert all(result.matched_filename and result.matched_tags and not result.matched_ocr for result in page.results)
    assert all(result.ocr_snippet is None for result in page.results)


def test_missing_is_excluded_by_default_and_optional(repository, tmp_path):
    folder = tmp_path / "shots"
    image = add_image(repository, folder, "missing-needle.png", text="needle")
    repository.mark_file_state(image.image_id, "missing")
    assert repository.search_images("needle", folder_path=folder).total_count == 0
    included = repository.search_images("needle", folder_path=folder, include_missing=True)
    assert included.total_count == 1
    assert included.results[0].ocr_status == "missing"
    assert not included.results[0].matched_ocr


def test_folder_filter_is_direct_case_insensitive_and_safe(repository, tmp_path):
    first = tmp_path / "日本語 Folder"
    second = tmp_path / "other"
    add_image(repository, first, "needle-one.png")
    add_image(repository, second, "needle-two.png")
    page = repository.search_images("needle", folder_path=str(first).upper())
    assert page.total_count == 1 and page.results[0].filename == "needle-one.png"
    assert repository.search_images("needle", folder_path=tmp_path / "does not exist").total_count == 0


def test_total_count_paging_and_tie_break_are_stable(repository, tmp_path):
    folder = tmp_path / "shots"
    for index in range(12):
        add_image(repository, folder, f"needle-{index:02}.png", mtime=index // 2)
    first = repository.search_images("needle", folder_path=folder, limit=5, offset=0)
    second = repository.search_images("needle", folder_path=folder, limit=5, offset=5)
    assert first.total_count == second.total_count == 12
    assert first.returned_count == second.returned_count == 5
    assert not ({item.image_id for item in first.results} & {item.image_id for item in second.results})
    all_ids = [item.image_id for item in repository.search_images("needle", folder_path=folder, limit=20).results]
    assert [item.image_id for item in first.results + second.results] == all_ids[:10]


def test_limit_validation_clamping_and_empty_query(repository, tmp_path):
    with pytest.raises(ValueError): repository.search_images("test", limit=-1)
    with pytest.raises(ValueError): repository.search_images("test", offset=-1)
    page = repository.search_images("test", limit=MAX_LIMIT + 1000)
    assert page.limit == MAX_LIMIT
    empty = repository.search_images("   ", limit=10, offset=4)
    assert empty.query_mode == "empty" and empty.total_count == empty.returned_count == 0
