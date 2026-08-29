"""Diagnose Capixe ONNX Semantic ranking against the upstream SigLIP 2 model."""

from __future__ import annotations

import argparse
import gc
import json
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


QUERIES = (
    "Windowsデスクトップ",
    "Windows desktop",
    "Windows desktop screenshot",
    "computer desktop",
    "desktop with application windows",
)
TARGETS = (
    "20260718_203016.png",
    "20260718_202724.png",
    "20260718_202718.png",
    "ScreenShot_Atest_001.png",
)


def normalized(value) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32).reshape(-1)
    return array / np.linalg.norm(array)


def db_embeddings(database: Path, folder: Path):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT i.image_id, i.path, e.embedding, e.model_id, e.bundle_version,
               e.model_revision, e.pipeline_version, e.embedding_format_version,
               e.dimension
          FROM images AS i
          JOIN semantic_embeddings AS e ON e.image_id = i.image_id
         WHERE lower(i.path) LIKE lower(?)
        """,
        (str(folder.resolve()) + "%",),
    ).fetchall()
    connection.close()
    result = []
    for row in rows:
        vector = np.asarray(struct.unpack("<768f", row["embedding"]), dtype=np.float32)
        result.append((dict(row), vector))
    return result


def load_onnx(bundle: Path):
    import onnxruntime as ort
    from tokenizers import Tokenizer

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    image = ort.InferenceSession(str(bundle / "image_encoder.onnx"), sess_options=options)
    text = ort.InferenceSession(str(bundle / "text_encoder.onnx"), sess_options=options)
    tokenizer = Tokenizer.from_file(str(bundle / "tokenizer.json"))
    config = json.loads((bundle / "tokenizer_config.json").read_text(encoding="utf-8"))
    pad_token = config.get("pad_token", "<pad>")
    tokenizer.enable_truncation(max_length=64)
    tokenizer.enable_padding(length=64, pad_id=tokenizer.token_to_id(pad_token), pad_token=pad_token)
    return image, text, tokenizer


def onnx_texts(session, tokenizer) -> np.ndarray:
    ids = np.asarray([tokenizer.encode(query, add_special_tokens=True).ids for query in QUERIES], dtype=np.int64)
    return np.stack([normalized(row) for row in session.run(["embedding"], {"input_ids": ids})[0]])


def app_pixels(path: Path, preprocess: dict) -> np.ndarray:
    image = Image.open(path).convert("RGB").resize(
        (preprocess["size"]["width"], preprocess["size"]["height"]),
        Image.Resampling(preprocess.get("resample", Image.Resampling.BICUBIC)),
    )
    values = np.asarray(image, dtype=np.float32) * np.float32(preprocess["rescale_factor"])
    mean = np.asarray(preprocess["image_mean"], dtype=np.float32)
    std = np.asarray(preprocess["image_std"], dtype=np.float32)
    return ((values - mean) / std).transpose(2, 0, 1)


def ranks(records, query_vectors):
    images = np.stack([vector for _, vector in records])
    scores = query_vectors @ images.T
    output = {}
    for query_index, query in enumerate(QUERIES):
        order = np.argsort(-scores[query_index], kind="stable")
        positions = np.empty(len(order), dtype=int)
        positions[order] = np.arange(1, len(order) + 1)
        output[query] = {
            Path(records[index][0]["path"]).name: {
                "rank": int(positions[index]),
                "score": float(scores[query_index, index]),
            }
            for index in range(len(records))
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packaged-executable", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = db_embeddings(args.database, args.folder)
    image_session, text_session, tokenizer = load_onnx(args.bundle)
    onnx_text = onnx_texts(text_session, tokenizer)
    db_ranks = ranks(records, onnx_text)

    # Pick definite non-targets from both ends of the failing Japanese ranking.
    japanese = db_ranks[QUERIES[0]]
    unrelated_names = [
        name for name, _ in sorted(japanese.items(), key=lambda item: -item[1]["score"])
        if name not in TARGETS
    ][:4]
    comparison_names = list(TARGETS) + unrelated_names
    paths = [args.folder / name for name in comparison_names]

    preprocess = json.loads((args.bundle / "preprocessor_config.json").read_text(encoding="utf-8"))
    pixels = np.stack([app_pixels(path, preprocess) for path in paths]).astype(np.float32)
    onnx_image = np.stack([normalized(row) for row in image_session.run(["embedding"], {"pixel_values": pixels})[0]])

    # Release the ~1.5 GB ONNX sessions before loading the upstream PyTorch model.
    del image_session, text_session, tokenizer
    gc.collect()

    packaged_text = None
    if args.packaged_executable:
        from app.semantic.embedding import decode_embedding
        from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig

        client = SemanticWorkerClient(SemanticWorkerConfig(
            bundle_dir=args.bundle,
            command=(str(args.packaged_executable), "--semantic-worker"),
            idle_seconds=0,
        ))
        packaged_text = np.stack([
            np.asarray(decode_embedding(client.embed_text(query)[0]), dtype=np.float32)
            for query in QUERIES
        ])
        client.shutdown()
        gc.collect()

    import torch
    from transformers import AutoModel, AutoProcessor

    processor = AutoProcessor.from_pretrained(args.snapshot, local_files_only=True, use_fast=False)
    model = AutoModel.from_pretrained(args.snapshot, local_files_only=True).eval()
    with torch.inference_mode():
        image_inputs = processor(images=[Image.open(path).convert("RGB") for path in paths], return_tensors="pt")
        text_inputs = processor(text=list(QUERIES), padding="max_length", truncation=True, max_length=64, return_tensors="pt")
        reference_image = model.get_image_features(**image_inputs).float().numpy()
        reference_text = model.get_text_features(**text_inputs).float().numpy()
        pool_image = model.vision_model(pixel_values=image_inputs["pixel_values"]).pooler_output.float().numpy()
        pool_text = model.text_model(input_ids=text_inputs["input_ids"]).pooler_output.float().numpy()
    reference_image = np.stack([normalized(row) for row in reference_image])
    reference_text = np.stack([normalized(row) for row in reference_text])
    pool_image = np.stack([normalized(row) for row in pool_image])
    pool_text = np.stack([normalized(row) for row in pool_text])

    def score_table(text_vectors, image_vectors):
        values = text_vectors @ image_vectors.T
        return {
            query: {name: float(values[query_index, image_index]) for image_index, name in enumerate(comparison_names)}
            for query_index, query in enumerate(QUERIES)
        }

    report = {
        "record_count": len(records),
        "database_identity": {
            key: value for key, value in records[0][0].items()
            if key not in {"embedding", "image_id", "path"}
        } if records else None,
        "queries": list(QUERIES),
        "targets": list(TARGETS),
        "unrelated": unrelated_names,
        "database_onnx_ranking": db_ranks,
        **({"packaged_database_ranking": ranks(records, packaged_text)}
           if packaged_text is not None else {}),
        "comparison": {
            "capixe_onnx": score_table(onnx_text, onnx_image),
            "reference_get_features": score_table(reference_text, reference_image),
            "reference_pooler_outputs": score_table(pool_text, pool_image),
        },
        "parity": {
            "onnx_vs_pooler_image_cosine": [float(a @ b) for a, b in zip(onnx_image, pool_image)],
            "onnx_vs_pooler_text_cosine": [float(a @ b) for a, b in zip(onnx_text, pool_text)],
            "pooler_vs_get_features_image_cosine": [float(a @ b) for a, b in zip(pool_image, reference_image)],
            "pooler_vs_get_features_text_cosine": [float(a @ b) for a, b in zip(pool_text, reference_text)],
            "app_pixels_vs_processor_max_abs": float(np.max(np.abs(pixels - image_inputs["pixel_values"].numpy()))),
            **({"packaged_vs_onnx_text_cosine": [float(a @ b) for a, b in zip(packaged_text, onnx_text)]}
               if packaged_text is not None else {}),
        },
        "dimensions": {
            "db_image": int(records[0][1].size),
            "onnx_image": int(onnx_image.shape[1]),
            "onnx_text": int(onnx_text.shape[1]),
            "reference_image": int(reference_image.shape[1]),
            "reference_text": int(reference_text.shape[1]),
        },
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
