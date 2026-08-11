"""Offline RapidOCR engine wrapper for the independent Capixe PoC."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MAX_IMAGE_PIXELS = 100_000_000
MODEL_FILES = {
    "detection": "PP-OCRv6_det_small.onnx",
    "classification": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
    "recognition": "PP-OCRv6_rec_small.onnx",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RapidOCREngine:
    """Load only local models and return JSON-serializable OCR results."""

    def __init__(self, model_dir: Path, allow_large_images: bool = False) -> None:
        self.model_dir = model_dir.resolve()
        self.allow_large_images = allow_large_images
        self.model_paths = {
            role: self.model_dir / filename for role, filename in MODEL_FILES.items()
        }
        missing = [str(path) for path in self.model_paths.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Required local OCR models are missing. Run prepare_models.py first: "
                + ", ".join(missing)
            )

        from rapidocr import (
            EngineType,
            LangDet,
            LangRec,
            ModelType,
            OCRVersion,
            RapidOCR,
        )

        started = time.perf_counter()
        self._ocr = RapidOCR(
            params={
                "Global.log_level": "warning",
                "Global.max_side_len": 2000,
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.MULTI,
                "Det.model_type": ModelType.SMALL,
                "Det.ocr_version": OCRVersion.PPOCRV6,
                "Det.model_path": str(self.model_paths["detection"]),
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Cls.model_path": str(self.model_paths["classification"]),
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.JAPAN,
                "Rec.model_type": ModelType.SMALL,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
                "Rec.model_path": str(self.model_paths["recognition"]),
            }
        )
        self.load_duration_ms = round((time.perf_counter() - started) * 1000, 3)

    def environment_metadata(self) -> dict[str, Any]:
        return {
            "engine": "RapidOCR",
            "engine_version": importlib.metadata.version("rapidocr"),
            "runtime": "ONNX Runtime CPU",
            "runtime_version": importlib.metadata.version("onnxruntime"),
            "device": "CPU",
            "models": {
                role: {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for role, path in self.model_paths.items()
            },
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        }

    def process(self, image_path: Path) -> dict[str, Any]:
        started_at = utc_now()
        started = time.perf_counter()
        base: dict[str, Any] = {
            "path": str(image_path.resolve()),
            "filename": image_path.name,
            "started_at": started_at,
        }
        try:
            metadata = self._read_image_metadata(image_path)
            base["image"] = metadata
            base.update(
                {
                    "width": metadata["width"],
                    "height": metadata["height"],
                    "file_size_bytes": metadata["size_bytes"],
                }
            )
            raw = self._ocr(image_path)
            blocks = self._convert_blocks(raw)
            base.update(
                {
                    "status": "success",
                    "success": True,
                    "full_text": "\n".join(block["text"] for block in blocks),
                    "blocks": blocks,
                    "block_count": len(blocks),
                    "average_confidence": (
                        round(sum(block["confidence"] for block in blocks) / len(blocks), 6)
                        if blocks else None
                    ),
                    "engine_duration_ms": round(float(getattr(raw, "elapse", 0)) * 1000, 3),
                    "error": None,
                }
            )
        except Exception as exc:  # per-file failures must not stop a folder run
            base.update(
                {
                    "status": "error",
                    "success": False,
                    "full_text": "",
                    "blocks": [],
                    "block_count": 0,
                    "average_confidence": None,
                    "engine_duration_ms": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
        base["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        base["finished_at"] = utc_now()
        return base

    def _read_image_metadata(self, image_path: Path) -> dict[str, Any]:
        from PIL import Image

        if image_path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {image_path.suffix or '(none)'}")
        with Image.open(image_path) as image:
            width, height = image.size
            pixel_count = width * height
            if pixel_count > MAX_IMAGE_PIXELS and not self.allow_large_images:
                raise ValueError(
                    f"Image has {pixel_count:,} pixels; limit is {MAX_IMAGE_PIXELS:,}. "
                    "Use --allow-large-images only after checking memory capacity."
                )
            image.verify()
            return {
                "width": width,
                "height": height,
                "pixels": pixel_count,
                "format": image.format,
                "size_bytes": image_path.stat().st_size,
            }

    @staticmethod
    def _convert_blocks(raw: Any) -> list[dict[str, Any]]:
        boxes = getattr(raw, "boxes", None)
        texts = getattr(raw, "txts", None)
        scores = getattr(raw, "scores", None)
        if boxes is None or texts is None or scores is None:
            return []
        return [
            {
                "text": str(text),
                "confidence": round(float(score), 6),
                "box": [[round(float(x), 3), round(float(y), 3)] for x, y in box],
            }
            for box, text, score in zip(boxes, texts, scores)
        ]
