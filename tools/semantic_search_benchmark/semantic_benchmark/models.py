from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor


class TransformersAdapter:
    def __init__(self, spec: dict, cache_dir: Path):
        self.spec = spec
        self.model_id = spec["id"]
        kwargs = {"cache_dir": str(cache_dir), "trust_remote_code": spec.get("trust_remote_code", False)}
        started = time.perf_counter()
        self.processor = AutoProcessor.from_pretrained(self.model_id, **kwargs)
        self.model = AutoModel.from_pretrained(self.model_id, **kwargs).eval().to("cpu")
        self.load_seconds = time.perf_counter() - started

    @staticmethod
    def _normalize(value):
        if not isinstance(value, torch.Tensor):
            for attribute in ("pooler_output", "image_embeds", "text_embeds"):
                candidate = getattr(value, attribute, None)
                if candidate is not None:
                    value = candidate
                    break
        if value is None:
            raise TypeError("Model did not return a pooled embedding tensor")
        return torch.nn.functional.normalize(value.float(), p=2, dim=-1).cpu().numpy()

    def encode_images(self, paths: list[Path], batch_size: int) -> tuple[np.ndarray, float]:
        output, started = [], time.perf_counter()
        with torch.inference_mode():
            for pos in range(0, len(paths), batch_size):
                images = [Image.open(path).convert("RGB") for path in paths[pos:pos + batch_size]]
                inputs = self.processor(images=images, return_tensors="pt")
                if hasattr(self.model, "get_image_features"):
                    features = self.model.get_image_features(**inputs)
                else:
                    features = self.model(**inputs).image_embeds
                output.append(self._normalize(features))
        return np.concatenate(output), time.perf_counter() - started

    def encode_texts(self, texts: list[str], batch_size: int) -> tuple[np.ndarray, float]:
        output, started = [], time.perf_counter()
        with torch.inference_mode():
            for pos in range(0, len(texts), batch_size):
                padding = "max_length" if "siglip" in self.model_id.lower() else True
                inputs = self.processor(text=texts[pos:pos + batch_size], padding=padding, truncation=True, return_tensors="pt")
                if hasattr(self.model, "get_text_features"):
                    features = self.model.get_text_features(**inputs)
                else:
                    features = self.model(**inputs).text_embeds
                output.append(self._normalize(features))
        return np.concatenate(output), time.perf_counter() - started
