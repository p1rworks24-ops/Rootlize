"""Ask AI composer stays off the regular Search UI until the panel opens."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.images_page import ImagesPage
from app.utils.thumbnail_cache import ThumbnailCache


def _app():
    return QApplication.instance() or QApplication([])


def _png(path: Path):
    image = QImage(10, 10, QImage.Format_RGB32)
    image.fill(Qt.blue)
    assert image.save(str(path), "PNG")


def test_ai_action_controls_are_hidden_from_regular_images_ui(tmp_path):
    app = _app()
    folder = tmp_path / "Selected"
    folder.mkdir()
    for name in ("github-home.png", "github-issue.png", "notes.png"):
        _png(folder / name)
    page = ImagesPage(
        {
            "selected_folder": str(folder),
            "screenshot_dir": str(tmp_path / "legacy"),
            "current_folder": "Capture",
            "save_folder": "Capture",
        },
        MetadataService(),
        ThumbnailCache(size=48),
        tmp_path,
        search_provider=lambda *_args: (),
        vision_search_provider=lambda *_args: (),
    )
    page.show()
    app.processEvents()
    assert page._right_panel.isVisible()
    assert page._right_stack.currentWidget() is page._preview_page
    assert not page._action_input.isVisible()
    assert not page._action_preview.isVisible()
    assert page._search_input.isVisible()
    assert page._list_stack.isVisible()
    assert page._ask_ai_btn.isVisible()
    page.close()
