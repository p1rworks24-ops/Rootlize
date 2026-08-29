"""Torch/Transformers-free SigLIP 2 ONNX runtime used by final validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image
from tokenizers import Tokenizer


MAX_LENGTH = 64


def load_preprocessor_config(model_dir: Path) -> dict:
    return json.loads((model_dir / "preprocessor_config.json").read_text(encoding="utf-8"))


def preprocess_images(paths: Iterable[Path], model_dir: Path) -> np.ndarray:
    config = load_preprocessor_config(model_dir)
    size = config["size"]
    resample = Image.Resampling(config.get("resample", Image.Resampling.BICUBIC))
    mean = np.asarray(config.get("image_mean", [0.5, 0.5, 0.5]), dtype=np.float32)
    std = np.asarray(config.get("image_std", [0.5, 0.5, 0.5]), dtype=np.float32)
    factor = np.float32(config.get("rescale_factor", 1.0 / 255.0))
    rows = []
    for path in paths:
        with Image.open(path) as source:
            image = source.convert("RGB").resize((size["width"], size["height"]), resample)
            values = np.asarray(image, dtype=np.float32) * factor
        values = (values - mean) / std
        rows.append(values.transpose(2, 0, 1))
    return np.stack(rows).astype(np.float32, copy=False)


class LightweightTokenizer:
    def __init__(self, model_dir: Path, max_length: int = MAX_LENGTH):
        config = json.loads((model_dir / "tokenizer_config.json").read_text(encoding="utf-8"))
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.max_length = max_length
        self.pad_id = self.tokenizer.token_to_id(config.get("pad_token", "<pad>"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding(length=max_length, pad_id=self.pad_id, pad_token=config.get("pad_token", "<pad>"))

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        return np.asarray([row.ids for row in self.tokenizer.encode_batch(list(texts), add_special_tokens=True)], dtype=np.int64)


def session_options(intra_threads: int, inter_threads: int = 1):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_threads
    options.inter_op_num_threads = inter_threads
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return options


class SemanticRuntime:
    def __init__(self, image_model: Path, text_model: Path, model_dir: Path, *, intra_threads: int = 4):
        import onnxruntime as ort

        options = session_options(intra_threads)
        providers = ["CPUExecutionProvider"]
        self.image_session = ort.InferenceSession(str(image_model), sess_options=options, providers=providers)
        self.text_session = ort.InferenceSession(str(text_model), sess_options=options, providers=providers)
        self.model_dir = model_dir
        self.tokenizer = LightweightTokenizer(model_dir)

    def embed_images(self, paths: Iterable[Path]) -> np.ndarray:
        pixels = preprocess_images(paths, self.model_dir)
        return self.image_session.run(["embedding"], {"pixel_values": pixels})[0]

    def embed_texts(self, texts: Iterable[str]) -> np.ndarray:
        input_ids = self.tokenizer.encode(texts)
        return self.text_session.run(["embedding"], {"input_ids": input_ids})[0]

    @staticmethod
    def similarities(text_embeddings: np.ndarray, image_embeddings: np.ndarray) -> np.ndarray:
        return text_embeddings @ image_embeddings.T
