"""Official Qwen3-VL-Reranker runtime wrapper for the Meaning eval PoC.

Uses the vendored official `Qwen3VLReranker` (scripts/qwen3_vl_reranker.py from
Qwen/Qwen3-VL-Reranker-2B) for instruction format, tokenize, and
sigmoid(yes-no) scoring.

4bit is optional and was observed to collapse scores on RTX 2070; fp16 is the
default for this PoC because 2B fp16 fits in 8GB.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from PIL import Image
import torch

from tools.meaning_eval.official_qwen3_vl_reranker import (
    MAX_PIXELS as OFFICIAL_MAX_PIXELS,
    Qwen3VLReranker as OfficialQwen3VLReranker,
)

DEFAULT_INSTRUCTION = (
    "Given a search query, retrieve relevant candidates that answer the query."
)


@dataclass
class LoadInfo:
    quantization: str
    torch_dtype: str
    attn_implementation: str
    device: str
    revision: str | None
    load_seconds: float
    peak_vram_bytes: int | None
    allocated_vram_bytes: int | None


def _cuda_mem() -> tuple[int | None, int | None]:
    if not torch.cuda.is_available():
        return None, None
    return int(torch.cuda.memory_allocated()), int(torch.cuda.max_memory_allocated())


class Qwen3VLReranker:
    def __init__(
        self,
        model_name_or_path: str,
        *,
        revision: str | None = None,
        max_pixels: int = OFFICIAL_MAX_PIXELS,
        default_instruction: str = DEFAULT_INSTRUCTION,
        quantization: str = "fp16",
        attn_implementation: str | None = "sdpa",
    ):
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is required for this PoC. CPU execution is not practical "
                "for Qwen3-VL-Reranker-2B on this hardware."
            )
        if quantization == "4bit":
            raise RuntimeError(
                "4bit collapsed yes/no scores on this GPU (dog photos ~0.16). "
                "Use fp16; 2B fp16 fits RTX 2070 8GB."
            )
        self.default_instruction = default_instruction
        self.quantization = "fp16"
        self.max_pixels = max_pixels
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"dtype": torch.float16}
        if attn_implementation:
            kwargs["attn_implementation"] = attn_implementation
        self.inner = OfficialQwen3VLReranker(
            model_name_or_path,
            max_pixels=max_pixels,
            default_instruction=default_instruction,
            **kwargs,
        )
        allocated, peak = _cuda_mem()
        revision_hash = None
        config = getattr(self.inner.model, "config", None)
        if config is not None:
            revision_hash = getattr(config, "_commit_hash", None)
        self.load_info = LoadInfo(
            quantization="fp16",
            torch_dtype="float16",
            attn_implementation=attn_implementation or "default",
            device="cuda",
            revision=str(revision_hash) if revision_hash else revision,
            load_seconds=time.perf_counter() - started,
            peak_vram_bytes=peak,
            allocated_vram_bytes=allocated,
        )

    def score_pairs(
        self,
        query_text: str,
        images: list[Image.Image],
        *,
        instruction: str | None = None,
        max_pixels: int | None = None,
    ) -> list[float]:
        if not images:
            return []
        scores = self.inner.process({
            "instruction": instruction or self.default_instruction,
            "query": {"text": query_text},
            "documents": [{"image": image.convert("RGB")} for image in images],
        })
        return [float(score) for score in scores]
