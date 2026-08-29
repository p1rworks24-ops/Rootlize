"""Compare PyTorch and ONNX Runtime on the 98-image/24-query benchmark."""

from __future__ import annotations

import argparse
import json
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
import onnxruntime as ort
import open_clip
import psutil
import torch
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REAL = ROOT / "real_images"
CACHE = ROOT / "cache" / "models"
MODEL_ID = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def normalize(x):
    x = np.asarray(x, dtype=np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


class PeakRSS:
    def __enter__(self):
        self.process, self.peak, self.stop = psutil.Process(), 0, False
        self.peak = self.process.memory_info().rss
        def sample():
            while not self.stop:
                self.peak = max(self.peak, self.process.memory_info().rss)
                time.sleep(.01)
        self.thread = threading.Thread(target=sample, daemon=True); self.thread.start(); return self
    def __exit__(self, *_):
        self.stop = True; self.thread.join()


def evaluate(scores, paths, queries):
    names = [p.name for p in paths]
    hits = {1: 0, 3: 0, 5: 0, 10: 0}; rr = []; rows = []
    for qi, item in enumerate(queries):
        order = np.argsort(-scores[qi], kind="stable")
        ranked = [names[i] for i in order]
        ranks = {name: ranked.index(name) + 1 for name in item["relevant"]}
        best = min(ranks.values()); rr.append(1 / best)
        for k in hits: hits[k] += best <= k
        rows.append({"query": item["query"], "relevant_ranks": dict(sorted(ranks.items(), key=lambda p: p[1])), "top_10": ranked[:10]})
    n = len(queries)
    return {"top_1": hits[1]/n, "top_3": hits[3]/n, "top_5": hits[5]/n,
            "top_10": hits[10]/n, "mrr": float(np.mean(rr)), "queries": rows}


def run_session(path, feeds, optimization=ort.GraphOptimizationLevel.ORT_ENABLE_ALL):
    options = ort.SessionOptions(); options.graph_optimization_level = optimization
    started = time.perf_counter()
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    load = time.perf_counter() - started
    rows = []; started = time.perf_counter()
    for feed in feeds: rows.append(session.run(["embedding"], feed)[0])
    return np.concatenate(rows), load, time.perf_counter() - started


def batches(values, size, name):
    return [{name: values[i:i+size]} for i in range(0, len(values), size)]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--images", type=Path, required=True); parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args(); bundle = HERE / "bundle"
    paths = [p for p in sorted(args.images.iterdir()) if p.suffix.lower() in SUPPORTED]
    queries = json.loads((REAL / "queries.json").read_text(encoding="utf-8")); texts = [q["query"] for q in queries]
    with PeakRSS() as memory:
        started = time.perf_counter(); model, _, preprocess = open_clip.create_model_and_transforms("hf-hub:" + MODEL_ID, cache_dir=str(CACHE)); tokenizer = open_clip.get_tokenizer("hf-hub:" + MODEL_ID); model.eval().cpu(); pt_load = time.perf_counter()-started
        pixels = np.stack([preprocess(Image.open(p).convert("RGB")).numpy() for p in paths]).astype(np.float32)
        tokens = tokenizer(texts).numpy().astype(np.int64)
        np.savez(HERE / "prepared_inputs.npz", pixels=pixels, tokens=tokens)
        with torch.inference_mode():
            started=time.perf_counter(); pt_images=model.encode_image(torch.from_numpy(pixels)).numpy(); pt_image_s=time.perf_counter()-started
            started=time.perf_counter(); pt_texts=model.encode_text(torch.from_numpy(tokens)).numpy(); pt_text_s=time.perf_counter()-started
        image_feeds=batches(pixels,args.batch_size,"pixel_values"); text_feeds=batches(tokens,args.batch_size,"input_ids")
        onnx_images,image_load,image_s=run_session(bundle/"image_encoder.onnx",image_feeds)
        onnx_texts,text_load,text_s=run_session(bundle/"text_encoder.onnx",text_feeds)
        basic_images,_,_=run_session(bundle/"image_encoder.onnx",image_feeds,ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
        basic_texts,_,_=run_session(bundle/"text_encoder.onnx",text_feeds,ort.GraphOptimizationLevel.ORT_DISABLE_ALL)
    pti,ptt,oni,ont=map(normalize,(pt_images,pt_texts,onnx_images,onnx_texts))
    pt_scores=ptt@pti.T; onnx_scores=ont@oni.T
    pt_order=np.argsort(-pt_scores,axis=1,kind="stable"); onnx_order=np.argsort(-onnx_scores,axis=1,kind="stable")
    image_cos=np.sum(pti*oni,axis=1); text_cos=np.sum(ptt*ont,axis=1)
    files=[p for p in bundle.iterdir() if p.is_file()]; zip_path=HERE/"openclip_onnx_fp32_bundle.zip"
    with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in files: archive.write(p,p.name)
    result={
        "model_id":MODEL_ID,"images":len(paths),"queries":len(queries),"providers":["CPUExecutionProvider"],"dimension":{"image":int(oni.shape[1]),"text":int(ont.shape[1])},
        "preprocessing":{"size":224,"mode":"RGB","mean":[.48145466,.4578275,.40821073],"std":[.26862954,.26130258,.27577711],"resize":"shortest side bicubic then center crop"},
        "tokenizer":{"type":"OpenAI SimpleTokenizer byte-level BPE","context_length":77,"vocab_size":49408,"eot_pooling":"argmax token id"},
        "comparison":{"image_cosine":{"min":float(image_cos.min()),"mean":float(image_cos.mean()),"max":float(image_cos.max())},"text_cosine":{"min":float(text_cos.min()),"mean":float(text_cos.mean()),"max":float(text_cos.max())},"max_abs_score_difference":float(np.abs(pt_scores-onnx_scores).max()),"exact_top_10_query_count":int(sum(np.array_equal(pt_order[i,:10],onnx_order[i,:10]) for i in range(len(queries)))),"max_rank_displacement":int(np.max(np.abs(np.argsort(pt_order,axis=1)-np.argsort(onnx_order,axis=1)))),"optimized_vs_unoptimized":{"image_max_abs":float(np.max(np.abs(normalize(basic_images)-oni))),"text_max_abs":float(np.max(np.abs(normalize(basic_texts)-ont)))}},
        "pytorch_metrics":evaluate(pt_scores,paths,queries),"onnx_metrics":evaluate(onnx_scores,paths,queries),
        "performance":{"pytorch_load_s":pt_load,"pytorch_image_ms_each":pt_image_s*1000/len(paths),"pytorch_text_ms_each":pt_text_s*1000/len(queries),"onnx_model_load_s":image_load+text_load,"onnx_image_total_s":image_s,"onnx_image_ms_each":image_s*1000/len(paths),"onnx_text_total_s":text_s,"onnx_text_ms_each":text_s*1000/len(queries),"peak_rss_mb":memory.peak/1024**2},
        "bundle":{"files":{p.name:p.stat().st_size for p in files},"total_bytes":sum(p.stat().st_size for p in files),"zip_bytes":zip_path.stat().st_size},
    }
    (HERE/"comparison_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(HERE/"comparison_results.json")


if __name__ == "__main__": main()
