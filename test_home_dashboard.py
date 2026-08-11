from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.services.metadata_service import MetadataService
from app.ui.pages.home_page import HomePage
from app.ui.styles import APP_STYLE
from app.utils.thumbnail_cache import ThumbnailCache


def _app():
    return QApplication.instance() or QApplication([])


def _page(tmp_path: Path, count: int = 3) -> HomePage:
    folder = tmp_path / "Library"
    folder.mkdir()
    for index in range(count):
        image = QImage(20, 20, QImage.Format_RGB32)
        image.fill(0x223344 + index)
        image.save(str(folder / f"image-{index}.png"))
    config = {
        "screenshot_dir": str(tmp_path),
        "selected_folder": str(folder),
        "plan_name": "Free",
        "analysis_image_limit": 100,
    }
    return HomePage(config, MetadataService(), ThumbnailCache(), tmp_path)


def test_dashboard_shows_folder_and_library_status(tmp_path):
    _app()
    page = _page(tmp_path)
    page.refresh()
    page.set_analysis_summary({"total": 3, "analyzed": 1, "pending": 2})
    assert page._folder_path.text().endswith("Library")
    assert page._total_value.text() == "3"
    assert page._analyzed_value.text() == "1 / 3"
    assert page._pending_value.text() == "2"
    assert page._analysis_progress.value() == 33
    assert not hasattr(page, "_folder_count")
    assert not hasattr(page, "_rate_value")
    assert "QWidget#homeDashboardBody" in APP_STYLE
    assert "background-color: #f7faff" in APP_STYLE


def test_plan_usage_has_backend_ready_adapter(tmp_path):
    app = _app()
    page = _page(tmp_path)
    page.refresh()
    page.set_plan_usage("Pro", 75, 200)
    page.show()
    app.processEvents()
    assert page._plan_name.text() == "Pro"
    assert page._usage_donut.remaining == 125
    assert "75 used" in page._usage_caption.text()
    assert "125 remaining" in page._usage_caption.text()
    assert page._dashboard.maximumWidth() == 1120


def test_default_home_plan_is_prototype_and_unlimited(tmp_path):
    _app()
    page = _page(tmp_path)
    page.refresh()

    assert page._plan_name.text() == "Prototype"
    assert page._usage_donut.unlimited
    assert "∞ available" in page._usage_caption.text()


def test_attention_recent_and_ai_actions_are_removed(tmp_path):
    _app()
    page = _page(tmp_path)
    assert not hasattr(page, "_attention_card")
    assert not hasattr(page, "_recent_card")
    assert not hasattr(page, "_ai_card")


def test_home_selected_folder_button_opens_picker_and_updates_folder(
    monkeypatch, tmp_path
):
    app = _app()
    page = _page(tmp_path)
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    saved: list[dict] = []
    emitted: list[str] = []
    monkeypatch.setattr(
        "app.ui.pages.home_page.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(chosen),
    )
    monkeypatch.setattr(
        "app.ui.pages.home_page.save_config",
        lambda config: saved.append(dict(config)),
    )
    page.folder_changed.connect(emitted.append)

    page._select_folder_btn.click()
    app.processEvents()

    assert page._config["selected_folder"] == str(chosen.resolve())
    assert page._folder_path.text() == str(chosen.resolve())
    assert emitted == [str(chosen.resolve())]
    assert saved[-1]["selected_folder"] == str(chosen.resolve())
