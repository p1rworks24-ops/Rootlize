"""Official Capixe app icon assets are present and loadable."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.app_icon import app_ico_path, app_mark_pixmap, load_app_icon


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_icon_files_exist():
    ico = app_ico_path()
    assert ico.is_file(), ico
    root = ico.parent
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        assert (root / f"capixe_app_icon_{size}.png").is_file()
    assert (root / "capixe_app_icon_512.png").is_file()
    assert (root / "capixe_app_icon_1024.png").is_file()


def test_load_app_icon_and_mark():
    _ensure_app()
    from app.ui import app_icon as app_icon_mod

    app_icon_mod._load_master_pixmap.cache_clear()
    app_icon_mod.load_app_icon.cache_clear()

    icon = load_app_icon()
    assert not icon.isNull()
    pix = app_mark_pixmap(64)
    assert not pix.isNull()
    # Logical size stays 64; device pixels may be larger on HiDPI
    logical_w = pix.width() / max(pix.devicePixelRatio(), 1.0)
    logical_h = pix.height() / max(pix.devicePixelRatio(), 1.0)
    assert abs(logical_w - 64) < 0.51
    assert abs(logical_h - 64) < 0.51
    # Must come from a high-res master (not a tiny 16–32 asset)
    master = app_icon_mod._load_master_pixmap()
    assert master.width() >= 256


def test_ico_is_under_resources():
    path = app_ico_path()
    parts = [p.lower() for p in Path(path).parts]
    assert "resources" in parts
    assert "icons" in parts
    assert path.name == "capixe.ico"
