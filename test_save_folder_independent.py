"""Save folder (capture) is independent from Images viewing folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from app.services.image_saver import ImageSaver
from app.services.metadata_service import MetadataService
from app.utils.workspace import resolve_current_folder, resolve_save_folder


def test_resolve_save_folder_independent_of_viewing():
    cfg = {
        "current_folder": "ProjectB",
        "save_folder": "ProjectA",
    }
    assert resolve_current_folder(cfg) == "ProjectB"
    assert resolve_save_folder(cfg) == "ProjectA"


def test_resolve_save_folder_falls_back_to_viewing():
    cfg = {"current_folder": "OnlyView"}
    assert resolve_save_folder(cfg) == "OnlyView"


def test_image_saver_uses_save_folder_not_viewing(tmp_path: Path):
    root = tmp_path
    (root / "screenshots" / "ViewMe").mkdir(parents=True)
    (root / "screenshots" / "SaveMe").mkdir(parents=True)
    svc = MetadataService()
    cfg = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "ViewMe",
        "save_folder": "SaveMe",
        "filename_template": "{date}_{time}",
        "capture_tags": [],
    }
    saver = ImageSaver(cfg, svc, app_root=root)
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0xABCDEF)
    path = saver.save_image(img, datetime(2026, 7, 16, 10, 0, 0))
    assert path is not None
    assert path.parent.name == "SaveMe"
    assert not (root / "screenshots" / "ViewMe" / path.name).exists()
