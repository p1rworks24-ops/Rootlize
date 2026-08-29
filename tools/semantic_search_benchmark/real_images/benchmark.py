"""Independent real-library text-to-image retrieval benchmark for Capixe."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import torch
import torch.nn.functional as F
from PIL import Image

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "cache" / "models"
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def model_source(model_id: str):
    cache_name = "models--" + model_id.replace("/", "--")
    candidates = [
        *(CACHE / model_id.replace("/", "--") / cache_name).glob("snapshots/*"),
        *(CACHE / cache_name).glob("snapshots/*"),
    ]
    return candidates[0] if candidates else model_id


def normalize(array):
    array = np.asarray(array, dtype=np.float32)
    return array / np.linalg.norm(array, axis=1, keepdims=True)


class PeakRSS:
    def __enter__(self):
        self.process = psutil.Process()
        self.baseline = self.process.memory_info().rss
        self.peak = self.baseline
        self.stop = False
        def sample():
            while not self.stop:
                self.peak = max(self.peak, self.process.memory_info().rss)
                time.sleep(.02)
        self.thread = threading.Thread(target=sample, daemon=True)
        self.thread.start()
        return self
    def __exit__(self, *_args):
        self.stop = True
        self.thread.join()


def load_transformers(spec):
    from transformers import AutoModel, AutoProcessor
    kwargs = {"cache_dir": str(CACHE), "trust_remote_code": spec.get("trust_remote_code", False)}
    source = model_source(spec["image_model"])
    processor = AutoProcessor.from_pretrained(source, **kwargs)
    model = AutoModel.from_pretrained(source, **kwargs).eval().to("cpu")

    def images(paths, batch):
        if hasattr(model, "encode_image"):
            return model.encode_image([str(path) for path in paths], batch_size=batch, show_progress_bar=False)
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(paths), batch):
                batch_images = [Image.open(path).convert("RGB") for path in paths[pos:pos + batch]]
                inputs = processor(images=batch_images, return_tensors="pt")
                rows.append(model.get_image_features(**inputs).float().numpy())
        return np.concatenate(rows)

    def texts(values, batch):
        if hasattr(model, "encode_text"):
            return model.encode_text(values, batch_size=batch, show_progress_bar=False)
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(values), batch):
                inputs = processor(text=values[pos:pos + batch], padding="max_length", truncation=True, return_tensors="pt")
                rows.append(model.get_text_features(**inputs).float().numpy())
        return np.concatenate(rows)
    return model, images, texts


def load_open_clip(spec):
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:" + spec["image_model"], cache_dir=str(CACHE)
    )
    model = model.eval().to("cpu")
    tokenizer = open_clip.get_tokenizer("hf-hub:" + spec["image_model"])
    def images(paths, batch):
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(paths), batch):
                values = torch.stack([preprocess(Image.open(path).convert("RGB")) for path in paths[pos:pos + batch]])
                rows.append(model.encode_image(values).float().numpy())
        return np.concatenate(rows)
    def texts(values, batch):
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(values), batch):
                rows.append(model.encode_text(tokenizer(values[pos:pos + batch])).float().numpy())
        return np.concatenate(rows)
    return model, images, texts


def load_nomic(spec):
    from transformers import AutoImageProcessor, AutoModel, AutoTokenizer
    common = {"cache_dir": str(CACHE), "trust_remote_code": True}
    image_source = model_source(spec["image_model"])
    text_source = model_source(spec["text_model"])
    processor = AutoImageProcessor.from_pretrained(image_source, **common)
    vision = AutoModel.from_pretrained(image_source, **common).eval().to("cpu")
    tokenizer = AutoTokenizer.from_pretrained(text_source, **common)
    text_model = AutoModel.from_pretrained(text_source, **common).eval().to("cpu")
    def images(paths, batch):
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(paths), batch):
                values = [Image.open(path).convert("RGB") for path in paths[pos:pos + batch]]
                output = vision(**processor(images=values, return_tensors="pt")).last_hidden_state
                if output.ndim == 3: output = output[:, 0]
                rows.append(output.float().numpy())
        return np.concatenate(rows)
    def texts(values, batch):
        rows = []
        with torch.inference_mode():
            for pos in range(0, len(values), batch):
                prefixed = ["search_query: " + value for value in values[pos:pos + batch]]
                tokens = tokenizer(prefixed, padding=True, truncation=True, return_tensors="pt")
                output = text_model(**tokens).last_hidden_state[:, 0]
                output = F.layer_norm(output, normalized_shape=(output.shape[1],))
                rows.append(output.float().numpy())
        return np.concatenate(rows)
    class Combined:
        def parameters(self):
            yield from vision.parameters(); yield from text_model.parameters()
    return Combined(), images, texts


def evaluate(scores, paths, queries):
    names = [path.name for path in paths]
    rows = []
    hits = {1: 0, 3: 0, 5: 0, 10: 0}
    reciprocal = []
    for query_index, item in enumerate(queries):
        order = np.argsort(-scores[query_index], kind="stable")
        ranked = [names[index] for index in order]
        relevant = set(item["relevant"])
        ranks = {name: ranked.index(name) + 1 for name in relevant}
        best = min(ranks.values())
        reciprocal.append(1 / best)
        for k in hits: hits[k] += best <= k
        false_positives = [name for name in ranked[:5] if name not in relevant]
        false_negatives = [name for name, rank in ranks.items() if rank > 20]
        rows.append({
            "query": item["query"], "best_relevant_rank": best,
            "relevant_ranks": dict(sorted(ranks.items(), key=lambda pair: pair[1])),
            "top_10": ranked[:10], "false_positives_top_5": false_positives,
            "false_negatives_after_20": false_negatives,
        })
    count = len(queries)
    return {
        "top_1": hits[1] / count, "top_3": hits[3] / count,
        "top_5": hits[5] / count, "top_10": hits[10] / count,
        "mrr": float(np.mean(reciprocal)), "queries": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    specs = json.loads((HERE / "models.json").read_text(encoding="utf-8"))
    spec = next(item for item in specs if item["name"] == args.model)
    queries = json.loads((HERE / "queries.json").read_text(encoding="utf-8"))
    paths = [path for path in sorted(args.images.iterdir()) if path.suffix.lower() in SUPPORTED]
    missing = sorted({name for item in queries for name in item["relevant"]} - {p.name for p in paths})
    if missing: raise FileNotFoundError(missing)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    loader = {"transformers": load_transformers, "open_clip": load_open_clip, "nomic": load_nomic}[spec["kind"]]
    with PeakRSS() as memory:
        started = time.perf_counter(); model, encode_images, encode_texts = loader(spec); load_s = time.perf_counter() - started
        started = time.perf_counter(); image_embeddings = normalize(encode_images(paths, args.batch_size)); image_s = time.perf_counter() - started
        text_values = [item["query"] for item in queries]
        started = time.perf_counter(); text_embeddings = normalize(encode_texts(text_values, args.batch_size)); text_s = time.perf_counter() - started
    scores = text_embeddings @ image_embeddings.T
    parameter_bytes = sum(parameter.numel() * parameter.element_size() for parameter in model.parameters())
    result = {
        "model": spec, "image_count": len(paths), "query_count": len(queries),
        "dimension": int(image_embeddings.shape[1]),
        "performance": {
            "load_seconds": load_s, "image_total_seconds": image_s,
            "image_ms_each": image_s * 1000 / len(paths),
            "text_total_seconds": text_s, "text_ms_each": text_s * 1000 / len(queries),
            "peak_rss_mb": memory.peak / 1024**2,
            "incremental_peak_rss_mb": (memory.peak - memory.baseline) / 1024**2,
            "parameter_mb": parameter_bytes / 1024**2,
        },
        "metrics": evaluate(scores, paths, queries),
    }
    output = HERE / (spec["name"].lower().replace(" ", "_").replace("/", "_") + ".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
