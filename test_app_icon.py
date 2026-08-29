"""Official Rootlize app icon assets are present and loadable."""

from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.ui.app_icon import app_ico_path, app_icons_dir, app_mark_pixmap, load_app_icon

_PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512, 1024)
_ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _ico_entries(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    out: list[tuple[int, int]] = []
    for i in range(count):
        off = 6 + i * 16
        width, height = struct.unpack_from("<BB", data, off)
        out.append((256 if width == 0 else width, 256 if height == 0 else height))
    return out


def _is_white_fringe(r: int, g: int, b: int, a: int) -> bool:
    return a > 16 and r >= 248 and g >= 248 and b >= 248 and max(r, g, b) - min(r, g, b) <= 8


def test_icon_files_exist():
    ico = app_ico_path()
    assert ico.is_file(), ico
    root = ico.parent
    for size in _PNG_SIZES:
        assert (root / f"capixe_app_icon_{size}.png").is_file()
    assert (root / "capixe_icon.png").is_file()


def test_ico_contains_windows_sizes():
    path = app_ico_path()
    sizes = {w for w, h in _ico_entries(path)}
    for size in _ICO_SIZES:
        assert size in sizes, (size, sizes)


def test_ico_uses_bmp_for_shell_sizes():
    """Win32 LoadImage / taskbar need DIB entries below 256; 256 stays PNG."""
    path = app_ico_path()
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    kinds: dict[int, str] = {}
    for i in range(count):
        off = 6 + i * 16
        width = struct.unpack_from("<B", data, off)[0]
        size, rel = struct.unpack_from("<II", data, off + 8)
        blob = data[rel : rel + size]
        kind = "png" if blob.startswith(b"\x89PNG") else "bmp"
        kinds[256 if width == 0 else width] = kind
    for size in (16, 20, 24, 32, 40, 48, 64, 128):
        assert kinds.get(size) == "bmp", (size, kinds)
    assert kinds.get(256) == "png", kinds


def test_apply_windows_aumid_sets_process_id():
    from app.ui.windows_shell import (
        WINDOWS_APP_USER_MODEL_ID,
        apply_windows_app_user_model_id,
        current_windows_app_user_model_id,
    )

    apply_windows_app_user_model_id()
    assert current_windows_app_user_model_id() == WINDOWS_APP_USER_MODEL_ID
    from app.branding import DATA_DIR_NAME
    from app.ui.windows_shell import WINDOWS_APP_USER_MODEL_ID

    assert WINDOWS_APP_USER_MODEL_ID == "Rootlize.App"
    assert "Capixe" not in WINDOWS_APP_USER_MODEL_ID
    assert DATA_DIR_NAME == "Capixe"


def test_main_sets_aumid_before_qapplication():
    text = Path(__file__).resolve().parent.joinpath("main.py").read_text(encoding="utf-8")
    assert text.index("apply_windows_app_user_model_id") < text.index("QApplication(sys.argv)")
    assert "apply_windows_window_icons" in text
    assert "QTimer.singleShot" in text


def test_windows_shell_stamps_taskbar_from_ico():
    path = Path(__file__).resolve().parent / "app" / "ui" / "windows_shell.py"
    text = path.read_text(encoding="utf-8")
    assert "LoadImageW" in text
    assert "RelaunchIconResource" in text or "_PKEY_RELAUNCH_ICON_RESOURCE" in text
    assert "app_ico_path" in text
    assert "Rootlize.App" in text or 'f"{APP_NAME}.App"' in text
    from app.ui.windows_shell import windows_relaunch_icon_resource
    from app.ui.app_icon import app_ico_path

    resource = windows_relaunch_icon_resource()
    # On-disk ico name stays capixe.ico; the shell ID must not be Capixe.
    # Frozen builds must also point at the ICO, not exe,0 (16px upscale).
    assert resource == str(app_ico_path())
    assert not resource.endswith(",0")
    from app.ui.windows_shell import WINDOWS_APP_USER_MODEL_ID

    assert WINDOWS_APP_USER_MODEL_ID == "Rootlize.App"


def test_frozen_relaunch_icon_uses_bundled_ico(monkeypatch):
    from app.ui import windows_shell as ws
    from app.ui.app_icon import app_ico_path

    monkeypatch.setattr(ws.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ws.sys, "executable", r"C:\fake\Rootlize.exe", raising=False)
    resource = ws.windows_relaunch_icon_resource()
    assert resource == str(app_ico_path())
    assert resource.endswith("capixe.ico")


def test_apply_windows_window_icons_does_not_raise():
    """Shell icon stamping must not abort GUI startup (frozen TypeError regression)."""
    import sys

    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    from PySide6.QtWidgets import QWidget

    from app.ui.windows_shell import (
        _PROPVARIANT,
        _VT_LPWSTR,
        apply_windows_window_icons,
    )

    buf = ctypes.create_unicode_buffer("Rootlize.App")
    variant = _PROPVARIANT()
    variant.vt = _VT_LPWSTR
    variant.pwszVal = ctypes.cast(buf, wintypes.LPWSTR)
    assert variant.pwszVal

    _ensure_app()
    widget = QWidget()
    assert int(widget.winId())
    apply_windows_window_icons(widget)
    widget.close()


def test_loadimage_reads_bmp_ico_sizes():
    import sys

    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    from app.ui.app_icon import app_ico_path

    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    handle = user32.LoadImageW(None, str(app_ico_path()), 1, 32, 32, 0x0010)
    assert handle, "Win32 LoadImage must read the 32px BMP ICO entry"


def test_transparent_master_has_no_canvas_or_white_fringe():
    path = app_icons_dir() / "capixe_app_icon_1024.png"
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    assert px is not None
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        assert px[x, y][3] == 0, (x, y, px[x, y])
    fringe = 0
    opaque = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if _is_white_fringe(r, g, b, a):
                fringe += 1
            if a >= 200:
                opaque += 1
    assert fringe == 0
    assert opaque > 50_000


def test_small_icons_keep_a_readable_mark():
    folder = app_icons_dir()
    for size in (16, 20, 24, 32):
        im = Image.open(folder / f"capixe_app_icon_{size}.png").convert("RGBA")
        assert im.size == (size, size)
        px = im.load()
        assert px is not None
        opaque = 0
        hole = 0
        fringe = 0
        for y in range(size):
            for x in range(size):
                r, g, b, a = px[x, y]
                if _is_white_fringe(r, g, b, a):
                    fringe += 1
                if a >= 80:
                    opaque += 1
                elif a < 24:
                    hole += 1
        assert fringe == 0, size
        # Hexagon + stem must occupy a real share of the canvas, with
        # transparent padding / inner channel remaining visible.
        assert opaque >= size * size * 0.22, (size, opaque)
        assert hole >= size * size * 0.18, (size, hole)
        for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
            assert px[x, y][3] < 32, (size, x, y, px[x, y])


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
    splash = app_mark_pixmap(168)
    splash_w = splash.width() / max(splash.devicePixelRatio(), 1.0)
    assert 150 <= splash_w <= 180


def test_ico_is_under_resources():
    path = app_ico_path()
    parts = [p.lower() for p in Path(path).parts]
    assert "resources" in parts
    assert "icons" in parts
    assert path.name == "capixe.ico"


def test_website_brand_icons_exist():
    brand = Path(__file__).resolve().parent / "website" / "assets" / "brand"
    assert (brand / "favicon.png").is_file()
    assert (brand / "app-icon.png").is_file()
    fav = Image.open(brand / "favicon.png").convert("RGBA")
    app_icon = Image.open(brand / "app-icon.png").convert("RGBA")
    assert fav.size[0] >= 32
    assert app_icon.size == (512, 512)
    assert fav.getpixel((0, 0))[3] == 0
    assert app_icon.getpixel((0, 0))[3] == 0


def test_packaged_icon_resources_if_dist_present():
    bundled = (
        Path(__file__).resolve().parent
        / "dist"
        / "Rootlize"
        / "_internal"
        / "resources"
        / "icons"
    )
    if not bundled.is_dir():
        return
    assert (bundled / "capixe.ico").is_file(), bundled
    for size in _PNG_SIZES:
        assert (bundled / f"capixe_app_icon_{size}.png").is_file()
