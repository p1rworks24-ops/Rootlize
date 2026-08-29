import json
import shutil
from pathlib import Path

from app.utils.file_copy_name import make_unique_copy_filename
from app.utils.image_favorite import (
    copy_image_entry,
    is_favorite_tag_name,
    migrate_favorite_tag_metadata,
    image_entry_is_favorite,
    image_is_favorite,
    visible_tags,
)
from app.utils.logger import setup_logger
from app.utils.tag_format import normalize_tag
from app.utils.unique_name import make_unique_name

logger = setup_logger()

SSTOOL_DIR_NAME = ".sstool"
METADATA_FILE_NAME = "metadata.json"
PROJECT_FILE_NAME = "project.json"
LEGACY_METADATA_FILE_NAME = "metadata.json"
GLOBAL_TAGS_FILE_NAME = "tags.json"

DEFAULT_METADATA: dict = {"images": {}}

DEFAULT_PROJECT: dict = {
    "display": {
        "sort_mode": "modified_desc",
        "manual_order": [],
        "thumbnail_size": 128,
        "thumbnail_mode": "large",
        "group_by": "none",
        "display_schema": 1,
    }
}

DEFAULT_GLOBAL_TAGS: dict = {"tags": []}



class MetadataService:
    """Manage .sstool/metadata.json and .sstool/project.json for each image folder."""

    def __init__(self) -> None:
        self._metadata_cache: dict[str, dict] = {}
        self._project_cache: dict[str, dict] = {}
        self._global_tags_cache: list[str] | None = None
        self._global_tags_path: str | None = None

    def resolve_folder_dir(
        self,
        screenshot_dir: str,
        folder_name: str,
        app_root: Path,
    ) -> Path:
        """Resolve Root/Folder path where images and .sstool live."""
        from app.utils.workspace import resolve_folder_dir as _resolve

        return _resolve(screenshot_dir, folder_name, app_root)

    def resolve_project_dir(
        self,
        screenshot_dir: str,
        project_name: str,
        app_root: Path,
    ) -> Path:
        """Compatibility alias for Root/Folder (name was formerly called project)."""
        return self.resolve_folder_dir(screenshot_dir, project_name, app_root)

    def get_sstool_dir(self, project_dir: Path) -> Path:
        """Return the .sstool directory path inside a project folder."""
        return project_dir / SSTOOL_DIR_NAME

    def get_metadata_path(self, project_dir: Path) -> Path:
        """Return the path to .sstool/metadata.json."""
        return self.get_sstool_dir(project_dir) / METADATA_FILE_NAME

    def get_project_json_path(self, project_dir: Path) -> Path:
        """Return the path to .sstool/project.json."""
        return self.get_sstool_dir(project_dir) / PROJECT_FILE_NAME

    def get_legacy_metadata_path(self, project_dir: Path) -> Path:
        """Return the legacy metadata.json path directly under the project folder."""
        return project_dir / LEGACY_METADATA_FILE_NAME

    def ensure_sstool(self, project_dir: Path) -> Path:
        """
        Create .sstool if missing, migrate legacy metadata.json, and ensure project.json.
        Returns the .sstool directory path.
        """
        sstool_dir = self.get_sstool_dir(project_dir)
        sstool_dir.mkdir(parents=True, exist_ok=True)

        self._migrate_legacy_metadata(project_dir)
        self._ensure_project_json(project_dir)

        return sstool_dir

    def load_metadata(self, project_dir: Path, force_reload: bool = False) -> dict:
        """Load metadata.json from cache or .sstool (creates .sstool if needed)."""
        cache_key = self._cache_key(project_dir)

        if not force_reload and cache_key in self._metadata_cache:
            return self._copy_metadata(self._metadata_cache[cache_key])

        self.ensure_sstool(project_dir)
        metadata_path = self.get_metadata_path(project_dir)

        if not metadata_path.exists():
            metadata = self._copy_metadata(DEFAULT_METADATA)
        else:
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load metadata.json: %s. Using defaults.", e)
                metadata = self._copy_metadata(DEFAULT_METADATA)

        if "images" not in metadata:
            metadata["images"] = {}

        if migrate_favorite_tag_metadata(metadata):
            try:
                self.save_metadata(project_dir, metadata)
            except OSError:
                logger.exception("Failed to persist Favorite tag migration")

        self._metadata_cache[cache_key] = self._copy_metadata(metadata)
        return self._copy_metadata(metadata)

    def save_metadata(self, project_dir: Path, metadata: dict) -> None:
        """Save metadata.json to .sstool."""
        sstool_dir = self.get_sstool_dir(project_dir)
        sstool_dir.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_metadata(project_dir)

        if "images" not in metadata:
            metadata["images"] = {}

        metadata_path = self.get_metadata_path(project_dir)
        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            self._metadata_cache[self._cache_key(project_dir)] = self._copy_metadata(metadata)
            logger.info("Saved metadata.json: %s", metadata_path)
        except OSError as e:
            logger.exception("Failed to save metadata.json: %s", e)
            raise

    def load_project(self, project_dir: Path, force_reload: bool = False) -> dict:
        """Load project.json from cache or .sstool (creates .sstool and defaults if needed)."""
        cache_key = self._cache_key(project_dir)

        if not force_reload and cache_key in self._project_cache:
            return self._copy_project(self._project_cache[cache_key])

        self.ensure_sstool(project_dir)
        project_path = self.get_project_json_path(project_dir)

        if not project_path.exists():
            project = self._copy_project(DEFAULT_PROJECT)
        else:
            try:
                with open(project_path, "r", encoding="utf-8") as f:
                    project = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load project.json: %s. Using defaults.", e)
                project = self._copy_project(DEFAULT_PROJECT)

        self._project_cache[cache_key] = self._copy_project(project)
        return self._copy_project(project)

    def save_project(self, project_dir: Path, project: dict) -> None:
        """Save project.json to .sstool."""
        sstool_dir = self.get_sstool_dir(project_dir)
        sstool_dir.mkdir(parents=True, exist_ok=True)
        project_path = self.get_project_json_path(project_dir)

        try:
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(project, f, indent=2, ensure_ascii=False)
            self._project_cache[self._cache_key(project_dir)] = self._copy_project(project)
            logger.info("Saved project.json: %s", project_path)
        except OSError as e:
            logger.exception("Failed to save project.json: %s", e)
            raise

    def invalidate_cache(self, project_dir: Path | None = None) -> None:
        """Clear cached metadata/project data for one project or all projects."""
        if project_dir is None:
            self._metadata_cache.clear()
            self._project_cache.clear()
            return

        cache_key = self._cache_key(project_dir)
        self._metadata_cache.pop(cache_key, None)
        self._project_cache.pop(cache_key, None)

    def get_image_tags(self, project_dir: Path, file_name: str) -> list[str]:
        """Return the visible tag list for a single image. Favorite is not a tag."""
        metadata = self.load_metadata(project_dir)
        return visible_tags(
            metadata.get("images", {}).get(file_name, {}).get("tags", [])
        )

    def is_image_favorite(self, project_dir: Path, file_name: str) -> bool:
        return image_is_favorite(self.load_metadata(project_dir), file_name)

    def set_image_favorite(
        self, project_dir: Path, file_name: str, favorite: bool
    ) -> bool:
        """Set the independent Favorite attribute. Does not add or remove tags."""
        metadata = self.load_metadata(project_dir)
        images = metadata.setdefault("images", {})
        entry = images.setdefault(file_name, {"tags": []})
        cleaned = visible_tags(entry.get("tags", []))
        current = image_entry_is_favorite(entry)
        if (
            bool(favorite) == current
            and cleaned == list(entry.get("tags", []))
            and ("favorite" in entry) == bool(favorite)
        ):
            return False
        entry["tags"] = cleaned
        if favorite:
            entry["favorite"] = True
        else:
            entry.pop("favorite", None)
        images[file_name] = entry
        self.save_metadata(project_dir, metadata)
        return True

    def add_image_tag(self, project_dir: Path, file_name: str, tag: str) -> bool:
        """Add a tag to an image. Returns True if the tag was added."""
        tag = normalize_tag(tag)
        if not tag or is_favorite_tag_name(tag):
            return False

        metadata = self.load_metadata(project_dir)

        if file_name not in metadata["images"]:
            metadata["images"][file_name] = {"tags": []}

        tags = visible_tags(metadata["images"][file_name].get("tags", []))
        if tag in tags:
            return False

        tags.append(tag)
        metadata["images"][file_name]["tags"] = tags
        self.save_metadata(project_dir, metadata)
        return True

    def set_image_tags(
        self, project_dir: Path, file_name: str, tags: list[str] | tuple[str, ...]
    ) -> bool:
        """Replace the visible tag list. Favorite is left unchanged. True if tags changed."""
        wanted: list[str] = []
        seen: set[str] = set()
        for raw in tags or ():
            tag = normalize_tag(str(raw))
            if not tag or is_favorite_tag_name(tag) or tag.casefold() in seen:
                continue
            seen.add(tag.casefold())
            wanted.append(tag)

        metadata = self.load_metadata(project_dir)
        images = metadata.setdefault("images", {})
        entry = images.setdefault(file_name, {"tags": []})
        current = visible_tags(entry.get("tags", []))
        if current == wanted:
            return False
        entry["tags"] = wanted
        images[file_name] = entry
        self.save_metadata(project_dir, metadata)
        return True

    def remove_image_tag(self, project_dir: Path, file_name: str, tag: str) -> bool:
        """Remove a tag from an image. Returns True if the tag was removed."""
        tag = normalize_tag(tag)
        metadata = self.load_metadata(project_dir)

        if file_name not in metadata.get("images", {}):
            return False

        tags = visible_tags(metadata["images"][file_name].get("tags", []))
        if tag not in tags:
            return False

        tags.remove(tag)
        metadata["images"][file_name]["tags"] = tags
        self.save_metadata(project_dir, metadata)
        return True

    def register_image(self, project_dir: Path, file_name: str) -> None:
        """Register a newly saved image in metadata.json with an empty tag list."""
        metadata = self.load_metadata(project_dir)

        if file_name not in metadata["images"]:
            metadata["images"][file_name] = {"tags": []}
            self.save_metadata(project_dir, metadata)
            logger.info("Registered image in metadata.json: %s", file_name)

    def copy_image_metadata(
        self,
        project_dir: Path,
        source_file_name: str,
        dest_file_name: str,
    ) -> None:
        """Copy one image entry (including tags) to a new file name (same project)."""
        metadata = self.load_metadata(project_dir)
        source = metadata.get("images", {}).get(source_file_name, {"tags": []})
        metadata["images"][dest_file_name] = copy_image_entry(source)
        self.save_metadata(project_dir, metadata)

    def copy_image_to_project(
        self,
        source_path: Path,
        dest_project_dir: Path,
    ) -> Path:
        """
        Copy a PNG and its metadata/tags into dest_project_dir.

        - Does not move or delete the source (foundation for future move_image_to_project).
        - Destination file name keeps the original when free; otherwise uses
          Explorer-style "name - Copy.png" / "name - Copy (2).png".
        - Returns the destination file path.
        """
        source_path = source_path.resolve()
        dest_project_dir = dest_project_dir.resolve()

        if not source_path.exists():
            raise FileNotFoundError(f"Source image not found: {source_path}")

        dest_project_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_sstool(dest_project_dir)

        existing = {p.name for p in dest_project_dir.glob("*.png")}
        source_name = source_path.name
        if source_name not in existing:
            dest_name = source_name
        else:
            dest_name = make_unique_copy_filename(source_name, existing)

        dest_path = dest_project_dir / dest_name
        shutil.copy2(source_path, dest_path)

        source_meta = self.load_metadata(source_path.parent)
        source_entry = source_meta.get("images", {}).get(source_name, {"tags": []})
        dest_meta = self.load_metadata(dest_project_dir)
        if "images" not in dest_meta:
            dest_meta["images"] = {}
        dest_meta["images"][dest_name] = copy_image_entry(source_entry)
        self.save_metadata(dest_project_dir, dest_meta)

        logger.info(
            "Copied image to project: %s -> %s",
            source_path,
            dest_path,
        )
        return dest_path

    def move_image_to_project(
        self,
        source_path: Path,
        dest_project_dir: Path,
    ) -> Path:
        """
        Move a PNG and its metadata/tags into dest_project_dir.

        - Same-folder move is a no-op (returns the source path).
        - On name conflict, uses Explorer-style "name - Copy.png".
        - Removes the source file and its metadata entry after a successful move.
        """
        source_path = source_path.resolve()
        dest_project_dir = dest_project_dir.resolve()

        if not source_path.exists():
            raise FileNotFoundError(f"Source image not found: {source_path}")

        if source_path.parent == dest_project_dir:
            return source_path

        dest_path = self.copy_image_to_project(source_path, dest_project_dir)
        self.delete_image_file(source_path.parent, source_path.name)
        logger.info(
            "Moved image to project: %s -> %s",
            source_path,
            dest_path,
        )
        return dest_path

    def remove_image_metadata(self, project_dir: Path, file_name: str) -> bool:
        """Remove an image entry from metadata.json. Returns True if removed."""
        metadata = self.load_metadata(project_dir)
        images = metadata.get("images", {})
        if file_name not in images:
            return False
        del images[file_name]
        self.save_metadata(project_dir, metadata)
        return True

    def delete_image_file(self, project_dir: Path, file_name: str) -> None:
        """Delete a PNG from disk and remove its metadata entry."""
        project_dir = project_dir.resolve()
        file_path = project_dir / file_name
        if file_path.exists():
            file_path.unlink()
        self.remove_image_metadata(project_dir, file_name)
        self.invalidate_cache(project_dir)

    def rename_image(
        self,
        project_dir: Path,
        old_name: str,
        new_name: str,
    ) -> Path:
        """
        Rename an image and its metadata entry within the same project.

        If ``new_name`` has no recognized image suffix, the source suffix is kept.
        """
        from app.actions.filenames import normalize_rename_filename

        project_dir = project_dir.resolve()
        old_name = Path(old_name).name
        new_name = normalize_rename_filename(old_name, Path(new_name).name)
        if not new_name:
            raise ValueError("new_name must not be empty")

        src = project_dir / old_name
        dest = project_dir / new_name
        if not src.exists():
            raise FileNotFoundError(f"Source image not found: {src}")
        if old_name == new_name:
            return src
        if dest.exists():
            raise FileExistsError(f"Target already exists: {dest}")

        src.rename(dest)

        metadata = self.load_metadata(project_dir)
        images = metadata.setdefault("images", {})
        entry = images.pop(old_name, {"tags": []})
        images[new_name] = entry
        self.save_metadata(project_dir, metadata)
        logger.info("Renamed image: %s -> %s", src, dest)
        return dest

    def get_global_tags_path(self, app_root: Path) -> Path:
        """Global tags live in %APPDATA%\\Capixe (writable); app_root is unused."""
        from app.paths import get_tags_path

        return get_tags_path()

    def load_global_tags(self, app_root: Path, force_reload: bool = False) -> list[str]:
        tags_path = self.get_global_tags_path(app_root)
        path_key = str(tags_path.resolve())

        if (
            not force_reload
            and self._global_tags_cache is not None
            and self._global_tags_path == path_key
        ):
            return list(self._global_tags_cache)

        if not tags_path.exists():
            tags: list[str] = []
        else:
            try:
                with open(tags_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    tags = [str(t) for t in data]
                elif isinstance(data, dict):
                    tags = list(data.get("tags", []))
                else:
                    tags = []
            except (json.JSONDecodeError, OSError, TypeError, AttributeError) as e:
                logger.error("Failed to load tags.json: %s", e)
                tags = []

        visible = visible_tags(tags)
        if visible != tags:
            try:
                self.save_global_tags(app_root, visible)
            except OSError:
                logger.exception("Failed to remove leftover Favorite from tags.json")
            tags = visible

        self._global_tags_cache = list(tags)
        self._global_tags_path = path_key
        return list(tags)

    def save_global_tags(self, app_root: Path, tags: list[str]) -> None:
        tags_path = self.get_global_tags_path(app_root)
        data = {"tags": tags}
        try:
            tags_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tags_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._global_tags_cache = list(tags)
            self._global_tags_path = str(tags_path.resolve())
            logger.info("Saved tags.json: %s", tags_path)
        except OSError as e:
            logger.exception("Failed to save tags.json: %s", e)
            raise

    def add_global_tag(self, app_root: Path, tag: str) -> str:
        """Add a common tag. Duplicates become 'name (1)', 'name (2)', ..."""
        tag = normalize_tag(tag)
        if not tag or is_favorite_tag_name(tag):
            return ""

        tags = self.load_global_tags(app_root)
        unique = make_unique_name(tag, tags)
        tags.append(unique)
        self.save_global_tags(app_root, tags)
        return unique

    def ensure_global_tag(self, app_root: Path, tag: str) -> str:
        """Ensure exact tag exists in the common list (no rename if already present)."""
        tag = normalize_tag(tag)
        if not tag or is_favorite_tag_name(tag):
            return ""

        tags = self.load_global_tags(app_root)
        if tag in tags:
            return tag

        tags.append(tag)
        self.save_global_tags(app_root, tags)
        return tag

    def rename_global_tag(self, app_root: Path, old_tag: str, new_tag: str) -> str | None:
        """Rename a common tag. Duplicate names become 'name (1)' etc."""
        old_tag = normalize_tag(old_tag)
        new_tag = normalize_tag(new_tag)
        if not new_tag or is_favorite_tag_name(new_tag):
            return None

        tags = self.load_global_tags(app_root)
        if old_tag not in tags:
            return None

        others = [t for t in tags if t != old_tag]
        unique = make_unique_name(new_tag, others)
        index = tags.index(old_tag)
        tags[index] = unique
        self.save_global_tags(app_root, tags)
        return unique

    def remove_global_tag(self, app_root: Path, tag: str) -> bool:
        tag = normalize_tag(tag)
        tags = self.load_global_tags(app_root)
        if tag not in tags:
            return False
        tags.remove(tag)
        self.save_global_tags(app_root, tags)
        return True

    def iter_project_dirs(self, screenshot_root: Path) -> list[Path]:
        """Return folder dirs under the screenshot root (image containers)."""
        from app.utils.workspace import list_folder_names

        return [
            (screenshot_root / name).resolve()
            for name in list_folder_names(screenshot_root, ensure_default=False)
        ]

    def iter_image_dirs(self, screenshot_root: Path) -> list[Path]:
        """Return all folder dirs that hold images and .sstool metadata."""
        from app.utils.workspace import iter_image_dirs

        return iter_image_dirs(screenshot_root)

    def rename_tag_in_all_projects(
        self,
        screenshot_root: Path,
        old_tag: str,
        new_tag: str,
    ) -> int:
        """
        Rename old_tag to new_tag in every folder's metadata.json.
        Returns the number of images updated.
        """
        updated_images = 0

        for image_dir in self.iter_image_dirs(screenshot_root):
            metadata = self.load_metadata(image_dir, force_reload=True)
            changed = False

            for _file_name, info in metadata.get("images", {}).items():
                tags = info.get("tags", [])
                if old_tag not in tags:
                    continue

                new_tags: list[str] = []
                for tag in tags:
                    if tag == old_tag:
                        if new_tag not in new_tags:
                            new_tags.append(new_tag)
                    elif tag not in new_tags:
                        new_tags.append(tag)

                info["tags"] = new_tags
                changed = True
                updated_images += 1

            if changed:
                self.save_metadata(image_dir, metadata)

        logger.info(
            "Renamed tag '%s' -> '%s' in %d image(s)",
            old_tag,
            new_tag,
            updated_images,
        )
        return updated_images

    def remove_tag_from_all_projects(self, screenshot_root: Path, tag: str) -> int:
        """
        Remove tag from every folder's metadata.json.
        Returns the number of images updated.
        """
        updated_images = 0

        for image_dir in self.iter_image_dirs(screenshot_root):
            metadata = self.load_metadata(image_dir, force_reload=True)
            changed = False

            for _file_name, info in metadata.get("images", {}).items():
                tags = info.get("tags", [])
                if tag not in tags:
                    continue
                tags.remove(tag)
                info["tags"] = tags
                changed = True
                updated_images += 1

            if changed:
                self.save_metadata(image_dir, metadata)

        logger.info("Removed tag '%s' from %d image(s)", tag, updated_images)
        return updated_images

    def _migrate_legacy_metadata(self, project_dir: Path) -> None:
        """Copy legacy Project/metadata.json into .sstool/metadata.json if needed."""
        legacy_path = self.get_legacy_metadata_path(project_dir)
        new_path = self.get_metadata_path(project_dir)

        if not legacy_path.exists() or new_path.exists():
            return

        try:
            shutil.copy2(legacy_path, new_path)
            logger.info(
                "Migrated legacy metadata.json to .sstool: %s -> %s",
                legacy_path,
                new_path,
            )
        except OSError as e:
            logger.exception("Failed to migrate legacy metadata.json: %s", e)

    def _ensure_project_json(self, project_dir: Path) -> None:
        """Create project.json with default values if it does not exist."""
        project_path = self.get_project_json_path(project_dir)
        if project_path.exists():
            return

        default_project = self._copy_project(DEFAULT_PROJECT)
        try:
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(default_project, f, indent=2, ensure_ascii=False)
            logger.info("Created default project.json: %s", project_path)
        except OSError as e:
            logger.exception("Failed to create project.json: %s", e)

    @staticmethod
    def _cache_key(project_dir: Path) -> str:
        return str(project_dir.resolve())

    @staticmethod
    def _copy_metadata(metadata: dict) -> dict:
        return json.loads(json.dumps(metadata))

    @staticmethod
    def _copy_project(project: dict) -> dict:
        return json.loads(json.dumps(project))
