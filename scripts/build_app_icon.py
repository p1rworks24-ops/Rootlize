"""Build Rootlize multi-size app icons from the official mark (canvas → alpha).

Output filenames stay on the existing capixe.ico / capixe_app_icon_*.png
contract so PyInstaller, the Qt icon loader, and tests keep working.

Run from repo root:
  python scripts/build_app_icon.py
"""

from __future__ import annotations

import struct
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "icons"
WEB_BRAND = ROOT / "website" / "assets" / "brand"
# Attached design master (black/white presentation canvas is allowed here).
MASTER_SRC = ROOT / "assets" / "rootlize_icon_master.png"
STABLE_SRC = ROOT / "assets" / "capixe_logo_source.png"
STABLE_ICON_PNG = ROOT / "assets" / "capixe_icon.png"
# Brand master is the transparent mark. Windows/website filled variants are
# derived only where a solid background is required.
TRANSPARENT_MASTER = ROOT / "assets" / "rootlize_icon_master_alpha.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
# Extra inset so 16–32px Windows sizes keep the hexagon outline + inner channel.
_SMALL_PAD = {16: 1, 20: 1, 24: 2, 32: 2}


def _find_incoming() -> Path | None:
    """Prefer the Rootlize design master, then the legacy drop-in path."""
    for path in (
        MASTER_SRC,
        ROOT / "assets" / "capixe_icon_source.png",
    ):
        if path.is_file():
            return path
    return None


def _chroma(r: int, g: int, b: int) -> int:
    return max(r, g, b) - min(r, g, b)


def _is_canvas_black(r: int, g: int, b: int) -> bool:
    """Outer/inner presentation canvas (near-black, including JPEG noise).

    The mark is cyan/blue: real glyph pixels keep strong chroma even when dark.
    """
    chroma = _chroma(r, g, b)
    peak = max(r, g, b)
    if chroma <= 20 and peak <= 52:
        return True
    luma = (r + 2 * g + b) / 4
    return luma <= 24 and chroma <= 28


def _is_canvas_white(r: int, g: int, b: int) -> bool:
    """Outer presentation canvas (near-white / light gray studio backgrounds)."""
    return r >= 235 and g >= 235 and b >= 235 and _chroma(r, g, b) <= 12


def _is_outer_canvas(r: int, g: int, b: int) -> bool:
    return _is_canvas_black(r, g, b) or _is_canvas_white(r, g, b)


def _flood_clear_outer_canvas(im: Image.Image) -> None:
    w, h = im.size
    px = im.load()
    assert px is not None
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


def _knockout_remaining_canvas(im: Image.Image) -> None:
    """Punch enclosed black channels (inner negative space) to alpha."""
    px = im.load()
    assert px is not None
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if _is_canvas_black(r, g, b) or _is_canvas_white(r, g, b):
                px[x, y] = (0, 0, 0, 0)


def _defringe_black_matte(im: Image.Image) -> None:
    """Straighten JPEG anti-alias baked against black; do not introduce white."""
    px = im.load()
    assert px is not None
    w, h = im.size

    def _transparent(x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= w or y >= h:
            return True
        return px[x, y][3] == 0

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            edge = (
                _transparent(x - 1, y)
                or _transparent(x + 1, y)
                or _transparent(x, y - 1)
                or _transparent(x, y + 1)
            )
            if not edge:
                continue
            peak = max(r, g, b)
            # Leftover near-black fringe only; keep real navy facets.
            if peak <= 40 and _chroma(r, g, b) <= 32:
                px[x, y] = (0, 0, 0, 0)
                continue
            if a == 255 and peak < 255 and _chroma(r, g, b) >= 12:
                coverage = peak / 255.0
                if coverage <= 0.12:
                    px[x, y] = (0, 0, 0, 0)
                    continue
                if coverage < 0.92:
                    inv = 1.0 / coverage
                    nr = min(255, int(round(r * inv)))
                    ng = min(255, int(round(g * inv)))
                    nb = min(255, int(round(b * inv)))
                    na = min(255, int(round(255 * coverage)))
                    px[x, y] = (nr, ng, nb, na)


def extract_mark(src: Path) -> Image.Image:
    print("extract:", src)
    im = Image.open(src).convert("RGBA")
    _flood_clear_outer_canvas(im)
    _knockout_remaining_canvas(im)
    _defringe_black_matte(im)

    bbox = im.getbbox()
    if bbox is None:
        raise RuntimeError("Could not locate Rootlize mark after canvas removal")

    crop = im.crop(bbox)
    cw, ch = crop.size
    # Tiny transparent margin so Lanczos AA is not clipped. Large UI marks
    # (splash / About) still read as the full hexagon.
    margin = max(2, round(max(cw, ch) * 0.02))
    side = max(cw, ch) + margin * 2
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(crop, ((side - cw) // 2, (side - ch) // 2), crop)
    print("extract square", sq.size, "glyph", (cw, ch), "margin", margin)
    return sq


def make_master(mark: Image.Image, size: int = 1024) -> Image.Image:
    return mark.resize((size, size), Image.Resampling.LANCZOS)


def make_size(master: Image.Image, size: int) -> Image.Image:
    pad = _SMALL_PAD.get(size, 0)
    inner = max(size - pad * 2, 1)
    if size <= 32:
        work = master.resize((inner * 4, inner * 4), Image.Resampling.LANCZOS)
        work = ImageEnhance.Contrast(work).enhance(1.12)
        work = ImageEnhance.Color(work).enhance(1.08)
        # Do not dilate alpha: MaxFilter closes the inner hexagonal channel.
        glyph = work.resize((inner, inner), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(glyph, (pad, pad), glyph)
        return canvas
    return master.resize((size, size), Image.Resampling.LANCZOS)


def composite_on_background(mark: Image.Image, hex_color: str) -> Image.Image:
    """Opaque derivative for surfaces that cannot keep transparency."""
    hex_color = hex_color.lstrip("#")
    rgb = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    bg = Image.new("RGBA", mark.size, rgb + (255,))
    return Image.alpha_composite(bg, mark.convert("RGBA"))


def _bmp_icon_bytes(im: Image.Image) -> bytes:
    """Classic 32bpp DIB ICO payload. Win32 LoadImage cannot read PNG ICO <256."""
    rgba = im.convert("RGBA")
    width, height = rgba.size
    xor = bytearray()
    px = rgba.load()
    assert px is not None
    for y in range(height - 1, -1, -1):
        for x in range(width):
            red, green, blue, alpha = px[x, y]
            xor.extend((blue, green, red, alpha))
    row_stride = ((width + 31) // 32) * 4
    and_mask = bytes(row_stride * height)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(xor),
        0,
        0,
        0,
        0,
    )
    return header + bytes(xor) + and_mask


def write_ico(path: Path, images: list[Image.Image]) -> None:
    import io

    entries: list[tuple[int, int, bytes]] = []
    for im in images:
        if im.width >= 256:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            data = buf.getvalue()
        else:
            data = _bmp_icon_bytes(im)
        entries.append((im.width, im.height, data))

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
    return [(width, height) for width, height, _kind in ico_payloads(path)]


def ico_payloads(path: Path) -> list[tuple[int, int, str]]:
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    out: list[tuple[int, int, str]] = []
    for i in range(count):
        off = 6 + i * 16
        width, height = struct.unpack_from("<BB", data, off)
        size, rel = struct.unpack_from("<II", data, off + 8)
        blob = data[rel : rel + size]
        kind = "png" if blob.startswith(b"\x89PNG") else "bmp"
        out.append((256 if width == 0 else width, 256 if height == 0 else height, kind))
    return out


def main() -> int:
    incoming = _find_incoming()
    OUT.mkdir(parents=True, exist_ok=True)
    WEB_BRAND.mkdir(parents=True, exist_ok=True)
    STABLE_SRC.parent.mkdir(parents=True, exist_ok=True)

    if incoming is not None:
        Image.open(incoming).convert("RGBA").save(STABLE_SRC, "PNG")
        print("updated source from master ->", STABLE_SRC)
    if not STABLE_SRC.is_file():
        raise FileNotFoundError(f"Missing {STABLE_SRC}")

    mark = extract_mark(STABLE_SRC)
    mark.save(TRANSPARENT_MASTER, "PNG")
    print("transparent master ->", TRANSPARENT_MASTER)

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

    make_size(master, 256).save(OUT / "capixe_icon.png", "PNG")

    ico_path = OUT / "capixe.ico"
    write_ico(ico_path, sized)
    assets_ico = ROOT / "assets" / "capixe_icon.ico"
    write_ico(assets_ico, sized)

    # Website: transparent brand master. Header is 28px on a light page.
    make_size(master, 64).save(WEB_BRAND / "favicon.png", "PNG")
    make_size(master, 512).save(WEB_BRAND / "app-icon.png", "PNG")
    # iOS home-screen icons composite transparency to black; use the light
    # page background so the mark matches the site instead of a black tile.
    composite_on_background(make_size(master, 180), "f5f6f8").save(
        WEB_BRAND / "apple-touch-icon.png", "PNG"
    )

    print(f"ico: {ico_path} ({ico_path.stat().st_size} bytes)")
    print("ico sizes:", ", ".join(f"{w}x{h}" for w, h in ico_entries(ico_path)))
    print("assets png:", STABLE_ICON_PNG)
    print("assets ico:", assets_ico)
    print("web favicon:", WEB_BRAND / "favicon.png")
    print("web app-icon:", WEB_BRAND / "app-icon.png")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("ERROR", type(exc).__name__, exc, file=sys.stderr)
        raise
