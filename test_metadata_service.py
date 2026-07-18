import json
import shutil
import tempfile
from pathlib import Path

from app.services.metadata_service import (
    DEFAULT_PROJECT,
    MetadataService,
)


def test_ensure_sstool_creates_folder_and_project_json():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        sstool_dir = service.ensure_sstool(project_dir)

        assert sstool_dir.exists()
        assert service.get_project_json_path(project_dir).exists()

        with open(service.get_project_json_path(project_dir), "r", encoding="utf-8") as f:
            project = json.load(f)

        assert project == DEFAULT_PROJECT


def test_migrate_legacy_metadata_keeps_old_file():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        legacy = {
            "images": {
                "Default_001.png": {"tags": ["Chrome", "Error"]},
            }
        }
        with open(project_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(legacy, f, indent=2, ensure_ascii=False)

        service.ensure_sstool(project_dir)

        assert (project_dir / "metadata.json").exists()
        assert service.get_metadata_path(project_dir).exists()

        metadata = service.load_metadata(project_dir)
        assert metadata["images"]["Default_001.png"]["tags"] == ["Chrome", "Error"]


def test_register_image_and_tags():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        service.register_image(project_dir, "Default_001.png")
        assert service.get_image_tags(project_dir, "Default_001.png") == []

        assert service.add_image_tag(project_dir, "Default_001.png", "Error") is True
        assert service.get_image_tags(project_dir, "Default_001.png") == ["Error"]

        assert service.add_image_tag(project_dir, "Default_001.png", "Error") is False
        assert service.remove_image_tag(project_dir, "Default_001.png", "Error") is True
        assert service.get_image_tags(project_dir, "Default_001.png") == []


def test_save_writes_to_sstool_not_project_root():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        service.add_image_tag(project_dir, "Default_002.png", "Test")

        assert not (project_dir / "metadata.json").exists()
        assert service.get_metadata_path(project_dir).exists()


def test_metadata_cache_avoids_disk_read():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        service.add_image_tag(project_dir, "Default_001.png", "Cached")

        metadata_path = service.get_metadata_path(project_dir)
        metadata_path.unlink()

        metadata = service.load_metadata(project_dir)
        assert metadata["images"]["Default_001.png"]["tags"] == ["Cached"]


def test_invalidate_cache_forces_reload():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        service = MetadataService()

        service.add_image_tag(project_dir, "Default_001.png", "Before")

        with open(service.get_metadata_path(project_dir), "w", encoding="utf-8") as f:
            json.dump(
                {"images": {"Default_001.png": {"tags": ["After"]}}},
                f,
                indent=2,
                ensure_ascii=False,
            )

        service.invalidate_cache(project_dir)
        metadata = service.load_metadata(project_dir)
        assert metadata["images"]["Default_001.png"]["tags"] == ["After"]


def test_rename_tag_in_all_projects():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder_a = root / "ProjectA"
        folder_b = root / "ProjectB"
        folder_a.mkdir(parents=True)
        folder_b.mkdir(parents=True)

        service = MetadataService()
        service.add_image_tag(folder_a, "a_001.png", "Chrome")
        service.add_image_tag(folder_a, "a_002.png", "Error")
        service.add_image_tag(folder_b, "b_001.png", "Chrome")

        updated = service.rename_tag_in_all_projects(root, "Chrome", "Chrome Extension")
        assert updated == 2

        assert service.get_image_tags(folder_a, "a_001.png") == ["Chrome Extension"]
        assert service.get_image_tags(folder_a, "a_002.png") == ["Error"]
        assert service.get_image_tags(folder_b, "b_001.png") == ["Chrome Extension"]


def test_remove_tag_from_all_projects():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "ProjectA"
        folder.mkdir(parents=True)

        service = MetadataService()
        service.add_image_tag(folder, "a_001.png", "Chrome")
        service.add_image_tag(folder, "a_001.png", "Error")
        service.add_image_tag(folder, "a_002.png", "Chrome")

        updated = service.remove_tag_from_all_projects(root, "Chrome")
        assert updated == 2

        assert service.get_image_tags(folder, "a_001.png") == ["Error"]
        assert service.get_image_tags(folder, "a_002.png") == []


if __name__ == "__main__":
    test_ensure_sstool_creates_folder_and_project_json()
    test_migrate_legacy_metadata_keeps_old_file()
    test_register_image_and_tags()
    test_save_writes_to_sstool_not_project_root()
    test_metadata_cache_avoids_disk_read()
    test_invalidate_cache_forces_reload()
    test_rename_tag_in_all_projects()
    test_remove_tag_from_all_projects()
    print("All metadata service tests passed.")
