"""Non-recursive supported-image folder scanner; it never performs OCR."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from app.ocr.exceptions import OCRFolderScanError
from app.ocr.models import ScannedImage
from app.ocr.path_normalization import display_path, normalize_windows_path
from app.ocr.text_normalization import normalize_search_text

SUPPORTED_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class FolderScan:
    folder_path: str
    items: tuple[ScannedImage, ...]


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("Invalid PNG header")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("Invalid PNG dimensions")
    return width, height


def _image_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.casefold() == ".png":
        try:
            return _png_dimensions(path)
        except ValueError:
            # Some valid PNGs contain ancillary chunks before IHDR layouts that
            # the fast header reader cannot recognize. Fall back to a decoder.
            pass
    from PIL import Image
    with Image.open(path) as image:
        if (image.format or "").upper() not in {"PNG", "JPEG", "WEBP", "BMP"}:
            raise ValueError("Unsupported image format")
        width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image dimensions")
    return width, height


def scan_folder(folder: str | Path) -> FolderScan:
    """Scan supported images directly below a readable folder."""
    try:
        shown_folder = display_path(folder)
    except (TypeError, ValueError, OSError) as exc:
        raise OCRFolderScanError("The selected folder path is invalid.") from exc
    native_folder = Path(shown_folder)
    if not native_folder.is_dir():
        raise OCRFolderScanError("The selected folder does not exist or is unavailable.")
    items: list[ScannedImage] = []
    try:
        entries = list(os.scandir(native_folder))
    except OSError as exc:
        raise OCRFolderScanError("The selected folder could not be read.") from exc
    for entry in entries:
        if entry.name.startswith(".") or Path(entry.name).suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            path = display_path(entry.path)
            stat = entry.stat(follow_symlinks=False)
            width, height = _image_dimensions(Path(entry.path))
            items.append(ScannedImage(path,normalize_windows_path(path),shown_folder,normalize_windows_path(shown_folder),entry.name,normalize_search_text(entry.name),stat.st_size,stat.st_mtime_ns,width,height,True))
        except (OSError, ValueError) as exc:
            try:
                path = display_path(entry.path)
            except Exception:
                path = os.fspath(entry.path)
            items.append(ScannedImage(path,normalize_windows_path(path),shown_folder,normalize_windows_path(shown_folder),entry.name,normalize_search_text(entry.name),None,None,None,None,False,type(exc).__name__))
    return FolderScan(shown_folder, tuple(sorted(items, key=lambda item: item.path_norm)))
