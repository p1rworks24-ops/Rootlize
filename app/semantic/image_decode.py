"""Safe, content-based image decoding for Semantic inference."""

from __future__ import annotations

from pathlib import Path

from .worker_errors import SemanticWorkerError


MAX_IMAGE_PIXELS = 100_000_000
SUPPORTED_IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "BMP"})


def decode_semantic_image(path: Path):
    """Decode an allowed image by its contents and normalize it to oriented RGB."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError

        with Image.open(path) as source:
            image_format = (source.format or "").upper()
            if image_format not in SUPPORTED_IMAGE_FORMATS:
                raise SemanticWorkerError(
                    "The image format is not supported.", code="UNSUPPORTED_IMAGE"
                )
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise SemanticWorkerError(
                    "The image is invalid or too large.", code="UNSUPPORTED_IMAGE"
                )
            source.load()
            return ImageOps.exif_transpose(source).convert("RGB")
    except SemanticWorkerError:
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError) as exc:
        raise SemanticWorkerError(
            "The image could not be decoded.", code="UNSUPPORTED_IMAGE"
        ) from exc

