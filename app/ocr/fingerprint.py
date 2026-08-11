"""Bounded-cost fingerprints for OCR change and move detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

QUICK_FINGERPRINT_VERSION = 1
SAMPLE_SIZE = 64 * 1024


def calculate_quick_fingerprint(path: str | Path, *, sample_size: int = SAMPLE_SIZE) -> str:
    """Hash size plus bounded samples without loading the whole image."""
    file_path = Path(path)
    size = file_path.stat().st_size
    digest = hashlib.sha256()
    digest.update(f"qf{QUICK_FINGERPRINT_VERSION}:{size}:".encode("ascii"))
    with file_path.open("rb") as stream:
        offsets = sorted({0, max(0, size // 2 - sample_size // 2), max(0, size - sample_size)})
        for offset in offsets:
            stream.seek(offset)
            digest.update(offset.to_bytes(8, "big"))
            digest.update(stream.read(sample_size))
    return f"qf{QUICK_FINGERPRINT_VERSION}:{digest.hexdigest()}"


def calculate_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a full digest only when an explicit integrity check needs it."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
