"""Stored Ask AI result paths resolve to current files without re-search."""

from pathlib import Path
from types import SimpleNamespace

from app.ui.ask_ai_result_restore import (
    is_existing_image_file,
    paths_in_folder,
    primary_result_folder,
    resolve_stored_result_paths,
)


def _png(path: Path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


def test_resolve_keeps_existing_paths_and_skips_deleted(tmp_path):
    kept = tmp_path / "keep.png"
    gone = tmp_path / "gone.png"
    _png(kept)
    _png(gone)
    gone.unlink()
    resolved = resolve_stored_result_paths([kept, gone])
    assert resolved == [kept]


def test_resolve_uses_ocr_image_id_for_moved_file(tmp_path):
    original = tmp_path / "a" / "shot.png"
    current = tmp_path / "b" / "shot.png"
    original.parent.mkdir()
    current.parent.mkdir()
    _png(current)
    resolved = resolve_stored_result_paths(
        [original],
        ocr_ids={str(original.resolve()): 7},
        ocr_records=[SimpleNamespace(image_id=7, path=str(current), filename="shot.png")],
    )
    assert [path.resolve() for path in resolved] == [current.resolve()]


def test_resolve_finds_unique_filename_in_lookup_folder(tmp_path):
    original = tmp_path / "a" / "notes.png"
    dest = tmp_path / "b" / "notes.png"
    original.parent.mkdir()
    dest.parent.mkdir()
    _png(dest)
    resolved = resolve_stored_result_paths(
        [original],
        lookup_folders=[tmp_path / "a", tmp_path / "b"],
    )
    assert [path.resolve() for path in resolved] == [dest.resolve()]


def test_resolve_skips_ambiguous_filename(tmp_path):
    original = tmp_path / "a" / "notes.png"
    first = tmp_path / "b" / "notes.png"
    second = tmp_path / "c" / "notes.png"
    original.parent.mkdir()
    first.parent.mkdir()
    second.parent.mkdir()
    _png(first)
    _png(second)
    assert resolve_stored_result_paths(
        [original],
        lookup_folders=[tmp_path / "b", tmp_path / "c"],
    ) == []


def test_primary_folder_uses_majority_then_original_scope(tmp_path):
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    a1 = folder_a / "one.png"
    a2 = folder_a / "two.png"
    b1 = folder_b / "three.png"
    for path in (a1, a2, b1):
        _png(path)
    assert primary_result_folder([a1, b1, a2]) == folder_a
    assert primary_result_folder([a1, b1], original_folder=folder_b) == folder_b
    assert paths_in_folder([a1, b1, a2], folder_a) == [a1, a2]
    assert not is_existing_image_file(tmp_path / "missing.png")
