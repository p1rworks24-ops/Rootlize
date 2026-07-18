from pathlib import Path
from datetime import datetime
from PySide6.QtGui import QImage
from app.services.metadata_service import MetadataService
from app.utils.filename_template import (
    DEFAULT_FILENAME_TEMPLATE,
    resolve_screenshot_filename,
)
from app.utils.logger import setup_logger
from app.utils.tag_format import normalize_tag
from app.utils.workspace import DEFAULT_FOLDER, resolve_save_folder

logger = setup_logger()


class ImageSaver:
    """検知した画像をファイルに保存するサービス"""

    def __init__(
        self,
        config: dict,
        metadata_service: MetadataService | None = None,
        app_root: Path | None = None,
    ):
        self._config = config
        self._screenshot_dir = config.get("screenshot_dir", "screenshots")
        self._save_folder = resolve_save_folder(config)
        self._filename_template = config.get(
            "filename_template", DEFAULT_FILENAME_TEMPLATE
        )
        self._capture_tags = self._normalize_capture_tags(config.get("capture_tags"))
        self._metadata_service = metadata_service or MetadataService()
        self._app_root = (
            app_root
            if app_root is not None
            else Path(__file__).resolve().parent.parent.parent
        )

    @staticmethod
    def _normalize_capture_tags(raw) -> list[str]:
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [raw]
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            tag = normalize_tag(str(item))
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out

    def update_config(self, config: dict) -> None:
        self._config = config
        self._screenshot_dir = config.get("screenshot_dir", "screenshots")
        self._save_folder = resolve_save_folder(config)
        self._filename_template = config.get(
            "filename_template", DEFAULT_FILENAME_TEMPLATE
        )
        self._capture_tags = self._normalize_capture_tags(config.get("capture_tags"))
        logger.info("ImageSaver config updated dynamically.")

    def save_image(self, qimage: QImage, detected_at: datetime | None = None) -> Path | None:
        """
        Save the QImage as a PNG under screenshots/<Folder>/.
        Filename comes from config filename_template (with collision numbering).
        Optional capture_tags are applied after register_image.
        """
        try:
            folder = self._save_folder or DEFAULT_FOLDER
            save_dir = self._metadata_service.resolve_folder_dir(
                self._screenshot_dir,
                folder,
                self._app_root,
            )
            save_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_service.ensure_sstool(save_dir)

            when = detected_at or datetime.now()
            file_name = resolve_screenshot_filename(
                save_dir,
                self._filename_template,
                folder=folder,
                when=when,
            )
            save_path = save_dir / file_name

            if save_path.exists():
                from app.utils.filename_template import make_unique_stem

                stem = make_unique_stem(save_dir, save_path.stem)
                file_name = f"{stem}.png"
                save_path = save_dir / file_name

            success = qimage.save(str(save_path), "PNG")
            if success:
                self._metadata_service.register_image(save_dir, file_name)
                for tag in self._capture_tags:
                    self._metadata_service.ensure_global_tag(self._app_root, tag)
                    self._metadata_service.add_image_tag(save_dir, file_name, tag)
                logger.info("Folder: %s", folder)
                logger.info("Template: %s", self._filename_template)
                if self._capture_tags:
                    logger.info("Capture tags: %s", ", ".join(self._capture_tags))
                logger.info("Saved:")
                logger.info("  %s", save_path)
                return save_path

            logger.error("画像の保存に失敗しました。ファイルパス: %s", save_path)
            return None

        except Exception as e:
            logger.exception("画像の保存中に例外が発生しました: %s", e)
            return None
