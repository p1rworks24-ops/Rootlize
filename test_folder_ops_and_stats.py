"""Folder ops and workspace stats unit tests."""

from pathlib import Path

from app.services.metadata_service import MetadataService
from app.utils.folder_ops import (
    delete_folder,
    duplicate_folder,
    make_unique_folder_copy_name,
    rename_folder,
)
from app.utils.workspace_stats import collect_folder_stats, collect_tag_stats, format_bytes


def test_make_unique_folder_copy_name(tmp_path: Path):
    (tmp_path / "Project").mkdir()
    assert make_unique_folder_copy_name(tmp_path, "Project") == "Project - Copy"
    (tmp_path / "Project - Copy").mkdir()
    assert make_unique_folder_copy_name(tmp_path, "Project") == "Project - Copy (2)"


def test_duplicate_rename_delete_folder(tmp_path: Path):
    src = tmp_path / "Alpha"
    src.mkdir()
    (src / "a.png").write_bytes(b"x")
    sstool = src / ".sstool"
    sstool.mkdir()
    (sstool / "metadata.json").write_text('{"images": {}}', encoding="utf-8")
    (sstool / "project.json").write_text("{}", encoding="utf-8")

    copy = duplicate_folder(src, tmp_path)
    assert copy.name == "Alpha - Copy"
    assert (copy / "a.png").exists()
    assert (copy / ".sstool" / "metadata.json").exists()

    renamed = rename_folder(copy, "Beta")
    assert renamed.name == "Beta"
    assert renamed.exists()

    delete_folder(renamed)
    assert not renamed.exists()


def test_format_bytes():
    assert format_bytes(500) == "500KB" or "KB" in format_bytes(500)
    assert "MB" in format_bytes(2 * 1024 * 1024)


def test_collect_folder_and_tag_stats(tmp_path: Path):
    root = tmp_path / "screenshots"
    folder = root / "Chrome"
    folder.mkdir(parents=True)
    png = folder / "shot.png"
    png.write_bytes(b"0123456789")
    svc = MetadataService()
    svc.ensure_sstool(folder)
    svc.register_image(folder, png.name)
    svc.add_image_tag(folder, png.name, "Bug")

    folders = collect_folder_stats(str(root), tmp_path, svc)
    assert any(r.label == "Chrome" and r.count == 1 for r in folders)

    tags = collect_tag_stats(str(root), tmp_path, svc)
    assert any(r.label == "Bug" and r.count == 1 for r in tags)
