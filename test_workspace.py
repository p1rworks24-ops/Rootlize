"""Tests for Root/Folder workspace helpers and nested layout migration."""

import tempfile
from pathlib import Path

from app.utils.workspace import (
    DEFAULT_FOLDER,
    is_image_folder,
    list_folder_names,
    migrate_nested_layout,
    pick_folder_name,
    resolve_folder_dir,
)


def test_migrate_nested_capture_into_parent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "MyApp"
        capture = project / DEFAULT_FOLDER
        capture.mkdir(parents=True)
        (capture / "MyApp_001.png").write_bytes(b"png")
        sstool = capture / ".sstool"
        sstool.mkdir()
        (sstool / "metadata.json").write_text('{"images": {}}', encoding="utf-8")

        assert migrate_nested_layout(root) is True
        assert (project / "MyApp_001.png").exists()
        assert (project / ".sstool" / "metadata.json").exists()
        assert not capture.exists()
        assert is_image_folder(project)


def test_list_folder_names_creates_capture_when_empty():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        names = list_folder_names(root, ensure_default=True)
        assert names == [DEFAULT_FOLDER]
        assert (root / DEFAULT_FOLDER).is_dir()


def test_pick_folder_name_prefers_capture():
    assert pick_folder_name(["UI", "Capture", "Error"], "Missing") == "Capture"
    assert pick_folder_name(["UI", "Error"], "UI") == "UI"
    assert pick_folder_name([], None) == DEFAULT_FOLDER


def test_resolve_folder_dir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = resolve_folder_dir(root, "Capture", root)
        assert path == (root / "Capture").resolve()


if __name__ == "__main__":
    test_migrate_nested_capture_into_parent()
    test_list_folder_names_creates_capture_when_empty()
    test_pick_folder_name_prefers_capture()
    test_resolve_folder_dir()
    print("workspace ok")
