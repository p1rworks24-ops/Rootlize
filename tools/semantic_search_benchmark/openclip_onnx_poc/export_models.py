"""Export the exact OpenCLIP checkpoint used by the real-image benchmark."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import open_clip
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CACHE = ROOT / "cache" / "models"
MODEL_ID = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"


class ImageEncoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.visual = model.visual

    def forward(self, pixel_values):
        return self.visual(pixel_values)


class TextEncoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.token_embedding = model.token_embedding
        self.positional_embedding = model.positional_embedding
        self.transformer = model.transformer
        self.ln_final = model.ln_final
        self.text_projection = model.text_projection
        self.attn_mask = model.attn_mask

    def forward(self, input_ids):
        x = self.token_embedding(input_ids)
        x = x + self.positional_embedding.to(x.dtype)
        x = self.transformer(x, attn_mask=self.attn_mask)
        x = self.ln_final(x)
        x = x[torch.arange(x.shape[0]), input_ids.argmax(dim=-1)]
        return x @ self.text_projection


def main():
    output = HERE / "bundle"
    output.mkdir(parents=True, exist_ok=True)
    model, _, _ = open_clip.create_model_and_transforms(
        "hf-hub:" + MODEL_ID, cache_dir=str(CACHE)
    )
    model.eval().cpu()
    exports = [
        (ImageEncoder(model), torch.zeros(1, 3, 224, 224), output / "image_encoder.onnx", "pixel_values"),
        (TextEncoder(model), torch.zeros(1, 77, dtype=torch.long), output / "text_encoder.onnx", "input_ids"),
    ]
    for module, sample, path, input_name in exports:
        torch.onnx.export(
            module.eval(), sample, str(path), input_names=[input_name],
            output_names=["embedding"], dynamic_axes={input_name: {0: "batch"}, "embedding": {0: "batch"}},
            opset_version=18, do_constant_folding=True, dynamo=False,
        )
    snapshot = CACHE / "models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K" / "snapshots" / "1a25a446712ba5ee05982a381eed697ef9b435cf"
    shutil.copy2(snapshot / "open_clip_config.json", output / "open_clip_config.json")
    bpe = Path(open_clip.tokenizer.__file__).parent / "bpe_simple_vocab_16e6.txt.gz"
    shutil.copy2(bpe, output / bpe.name)
    (output / "LICENSE.txt").write_text(
        "Model: laion/CLIP-ViT-B-32-laion2B-s34B-b79K\nLicense: MIT\n"
        "Source: https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K\n",
        encoding="utf-8",
    )
    manifest = {"model_id": MODEL_ID, "snapshot": snapshot.name, "opset": 18,
                "inputs": {"image": "float32[batch,3,224,224]", "text": "int64[batch,77]"},
                "outputs": {"image": "float32[batch,512]", "text": "float32[batch,512]"}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
