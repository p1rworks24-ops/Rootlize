"""Standalone OpenCLIP ONNX Runtime adapter used only by the prototype."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from tokenizer import SimpleTokenizer


DIMENSION = 512
MEAN = np.asarray([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.asarray([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


class PrototypeError(RuntimeError):
    def __init__(self, message: str, code: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def preprocess_image(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("empty image")
            if width < height:
                resized = (224, int(224 * height / width))
            else:
                resized = (int(224 * width / height), 224)
            image = image.resize(resized, Image.Resampling.BICUBIC)
            left = (image.width - 224) // 2
            top = (image.height - 224) // 2
            image = image.crop((left, top, left + 224, top + 224))
            values = np.asarray(image, dtype=np.float32) / np.float32(255.0)
        return ((values - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32, copy=False)
    except Exception as exc:
        raise PrototypeError("Image preprocessing failed.", "IMAGE_DECODE_FAILED", True) from exc


def normalize(rows: np.ndarray) -> np.ndarray:
    values = np.asarray(rows, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != DIMENSION or not np.isfinite(values).all():
        raise PrototypeError("Model returned invalid embeddings.", "INFERENCE_FAILED")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise PrototypeError("Model returned zero embeddings.", "INFERENCE_FAILED")
    return (values / norms).astype(np.float32, copy=False)


class OpenCLIPRuntime:
    def __init__(self, bundle: Path):
        self.bundle = bundle
        self.image_session = self.text_session = self.tokenizer = None
        self.manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    @staticmethod
    def options():
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        return options

    @property
    def loaded(self) -> list[str]:
        return [name for name, value in (("image_encoder", self.image_session), ("text_encoder", self.text_session)) if value is not None]

    def load(self, components: list[str]) -> None:
        import onnxruntime as ort
        if ort.get_available_providers()[0:] and "CPUExecutionProvider" not in ort.get_available_providers():
            raise PrototypeError("CPUExecutionProvider is unavailable.", "MODEL_INCOMPATIBLE")
        try:
            for component in components:
                if component == "image_encoder" and self.image_session is None:
                    self.image_session = ort.InferenceSession(str(self.bundle / "image_encoder.onnx"), sess_options=self.options(), providers=["CPUExecutionProvider"])
                elif component == "text_encoder" and self.text_session is None:
                    self.text_session = ort.InferenceSession(str(self.bundle / "text_encoder.onnx"), sess_options=self.options(), providers=["CPUExecutionProvider"])
                    self.tokenizer = SimpleTokenizer(self.bundle / "bpe_simple_vocab_16e6.txt.gz")
                elif component not in {"image_encoder", "text_encoder"}:
                    raise PrototypeError("Unknown model component.", "INVALID_REQUEST")
        except PrototypeError:
            raise
        except Exception as exc:
            raise PrototypeError("Model load failed.", "MODEL_LOAD_FAILED") from exc

    def embed_pixels(self, pixels: np.ndarray) -> np.ndarray:
        self.load(["image_encoder"])
        values = np.asarray(pixels, dtype=np.float32)
        if values.ndim != 4 or values.shape[1:] != (3, 224, 224):
            raise PrototypeError("Expected float32[B,3,224,224].", "INVALID_REQUEST")
        return normalize(self.image_session.run(["embedding"], {"pixel_values": values})[0])

    def embed_image(self, path: Path) -> np.ndarray:
        return self.embed_pixels(preprocess_image(path))

    def embed_text(self, texts: str | list[str]) -> np.ndarray:
        self.load(["text_encoder"])
        tokens = self.tokenizer(texts)
        return normalize(self.text_session.run(["embedding"], {"input_ids": tokens})[0])

    @staticmethod
    def search(text: np.ndarray, images: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        scores = np.asarray(text, dtype=np.float32) @ np.asarray(images, dtype=np.float32).T
        return scores, np.argsort(-scores, axis=1, kind="stable")
