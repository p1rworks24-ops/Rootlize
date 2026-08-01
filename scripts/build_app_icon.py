"""Build Capixe multi-size app icon from the official mark (black canvas → alpha).

Run from repo root:
  python scripts/build_app_icon.py
"""

from __future__ import annotations

import struct
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "icons"
STABLE_SRC = ROOT / "assets" / "capixe_logo_source.png"
STABLE_ICON_PNG = ROOT / "assets" / "capixe_icon.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _find_incoming() -> Path | None:
    """
    Optional drop-in source under assets/ (not Cursor user paths).

    Prefer assets/capixe_icon_source.png when present; otherwise keep the
    stable logo source already in the repo.
    """
    drop_in = ROOT / "assets" / "capixe_icon_source.png"
    if drop_in.is_file():
        return drop_in
    return None


def _is_canvas_black(r: int, g: int, b: int) -> bool:
    """Outer presentation canvas (near-black / dark gray, not icon strokes)."""
    return r <= 45 and g <= 45 and b <= 45 and max(r, g, b) - min(r, g, b) <= 8


def _is_canvas_white(r: int, g: int, b: int) -> bool:
    """Outer presentation canvas (near-white / light gray studio backgrounds)."""
    return r >= 235 and g >= 235 and b >= 235 and max(r, g, b) - min(r, g, b) <= 12


def _is_outer_canvas(r: int, g: int, b: int) -> bool:
    return _is_canvas_black(r, g, b) or _is_canvas_white(r, g, b)


def extract_mark(src: Path) -> Image.Image:
    print("extract:", src)
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    px = im.load()
    assert px is not None

    # Flood-fill outer studio canvas → transparent. Inner white strokes stay
    # because they are enclosed by blue and are not reached from the corners.
    visited = bytearray(w * h)
    q: deque[tuple[int, int]] = deque(
        [
            (0, 0),
            (w - 1, 0),
            (0, h - 1),
            (w - 1, h - 1),
            (w // 2, 0),
            (0, h // 2),
            (w - 1, h // 2),
            (w // 2, h - 1),
        ]
    )
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        idx = y * w + x
        if visited[idx]:
            continue
        r, g, b, a = px[x, y]
        if a < 10 or not _is_outer_canvas(r, g, b):
            continue
        visited[idx] = 1
        px[x, y] = (0, 0, 0, 0)
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    # Crop to full mark (blue + yellow tag + glass), not blue pixels alone
    bbox = im.getbbox()
    if bbox is None:
        raise RuntimeError("Could not locate Capixe mark after canvas removal")

    left, top, right, bottom = bbox
    pad = 8
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w, right + pad)
    bottom = min(h, bottom + pad)
    side = max(right - left, bottom - top)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    right = min(w, left + side)
    bottom = min(h, top + side)
    left = max(0, right - side)
    top = max(0, bottom - side)
    crop = im.crop((left, top, right, bottom))

    bbox = crop.getbbox()
    if bbox:
        crop = crop.crop(bbox)
    cw, ch = crop.size
    side = max(cw, ch)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(crop, ((side - cw) // 2, (side - ch) // 2), crop)
    print("extract square", sq.size)
    return sq


def make_master(mark: Image.Image, size: int = 1024) -> Image.Image:
    master = mark.resize((size, size), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(master).enhance(1.04)


def make_size(master: Image.Image, size: int) -> Image.Image:
    if size > 32:
        return master.resize((size, size), Image.Resampling.LANCZOS)
    work = master.resize((size * 4, size * 4), Image.Resampling.LANCZOS)
    work = ImageEnhance.Contrast(work).enhance(1.18)
    work = ImageEnhance.Color(work).enhance(1.1)
    if size <= 24:
        r, g, b, a = work.split()
        a = a.filter(ImageFilter.MaxFilter(3))
        work = Image.merge("RGBA", (r, g, b, a))
    return work.resize((size, size), Image.Resampling.LANCZOS)


def write_ico(path: Path, images: list[Image.Image]) -> None:
    import io

    entries: list[tuple[int, int, bytes]] = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        entries.append((im.width, im.height, buf.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(entries))
    directory = bytearray()
    blobs = bytearray()
    offset = 6 + 16 * len(entries)
    for width, height, data in entries:
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                0 if width >= 256 else width,
                0 if height >= 256 else height,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        blobs.extend(data)
        offset += len(data)
    path.write_bytes(header + directory + blobs)


def ico_entries(path: Path) -> list[tuple[int, int]]:
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    out: list[tuple[int, int]] = []
    for i in range(count):
        off = 6 + i * 16
        width, height = struct.unpack_from("<BB", data, off)
        out.append((256 if width == 0 else width, 256 if height == 0 else height))
    return out


def main() -> int:
    incoming = _find_incoming()
    OUT.mkdir(parents=True, exist_ok=True)
    STABLE_SRC.parent.mkdir(parents=True, exist_ok=True)

    if incoming is not None:
        Image.open(incoming).convert("RGBA").save(STABLE_SRC, "PNG")
        print("updated source from attachment ->", STABLE_SRC)
    if not STABLE_SRC.is_file():
        raise FileNotFoundError(f"Missing {STABLE_SRC}")

    mark = extract_mark(STABLE_SRC)
    # Canonical transparent PNG for UI (also mirrored as capixe_icon.png)
    mark_512 = make_master(mark, 512)
    mark_512.save(STABLE_ICON_PNG, "PNG")
    mark_512.save(OUT / "capixe_app_icon_512.png", "PNG")

    master = make_master(mark, 1024)
    master.save(OUT / "capixe_app_icon_1024.png", "PNG")

    sized: list[Image.Image] = []
    for size in SIZES:
        im = make_size(master, size)
        im.save(OUT / f"capixe_app_icon_{size}.png", "PNG")
        sized.append(im)
        print("png", size)

    # Keep a transparent PNG alias next to the ICO for docs / future tools
    make_size(master, 256).save(OUT / "capixe_icon.png", "PNG")

    ico_path = OUT / "capixe.ico"
    # Also expose assets/capixe_icon.ico for the recommended layout
    write_ico(ico_path, sized)
    assets_ico = ROOT / "assets" / "capixe_icon.ico"
    write_ico(assets_ico, sized)

    print(f"ico: {ico_path} ({ico_path.stat().st_size} bytes)")
    print("ico sizes:", ", ".join(f"{w}x{h}" for w, h in ico_entries(ico_path)))
    print("assets png:", STABLE_ICON_PNG)
    print("assets ico:", assets_ico)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR", type(exc).__name__, exc, file=sys.stderr)
        raise
