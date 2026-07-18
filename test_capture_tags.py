"""ImageSaver applies capture_tags after save."""

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from app.services.image_saver import ImageSaver
from app.services.metadata_service import MetadataService


def test_save_image_applies_capture_tags(tmp_path: Path):
    root = tmp_path
    folder = root / "screenshots" / "Capture"
    folder.mkdir(parents=True)
    svc = MetadataService()
    cfg = {
        "screenshot_dir": str(root / "screenshots"),
        "current_folder": "Capture",
        "filename_template": "{date}_{time}",
        "capture_tags": ["Bug", "#Chrome"],
    }
    saver = ImageSaver(cfg, svc, app_root=root)
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(0x112233)
    when = datetime(2026, 7, 16, 12, 0, 0)
    path = saver.save_image(img, when)
    assert path is not None
    tags = svc.get_image_tags(folder, path.name)
    assert "Bug" in tags
    assert "Chrome" in tags
    globals_ = svc.load_global_tags(root, force_reload=True)
    assert "Bug" in globals_
    assert "Chrome" in globals_
