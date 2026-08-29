from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import psutil
import torch
from PIL import Image
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModel, AutoProcessor

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "google/siglip2-base-patch16-224"
MODEL_CACHE = ROOT / "cache" / "models" / MODEL_ID.replace("/", "--")
CACHE = Path(__file__).resolve().parent / "cache"
FP32 = CACHE / "fp32"
INT8 = CACHE / "int8_dynamic_per_channel"


def local_snapshot() -> Path:
    snapshots = list(MODEL_CACHE.glob("models--*--*/snapshots/*"))
    if not snapshots:
        raise FileNotFoundError("Cached SigLIP 2 snapshot is missing; run the baseline benchmark first")
    return snapshots[0]


class ImageEncoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.encoder = model.vision_model

    def forward(self, pixel_values):
        value = self.encoder(pixel_values=pixel_values).pooler_output.float()
        return torch.nn.functional.normalize(value, p=2, dim=-1)


class TextEncoder(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.encoder = model.text_model

    def forward(self, input_ids):
        value = self.encoder(input_ids=input_ids).pooler_output.float()
        return torch.nn.functional.normalize(value, p=2, dim=-1)


def export_models(model, processor, force=False):
    FP32.mkdir(parents=True, exist_ok=True)
    image_path, text_path = FP32 / "image_encoder.onnx", FP32 / "text_encoder.onnx"
    if force or not image_path.exists():
        sample = processor(images=Image.new("RGB", (224, 224)), return_tensors="pt")["pixel_values"]
        torch.onnx.export(ImageEncoder(model).eval(), (sample,), image_path, input_names=["pixel_values"],
                          output_names=["embedding"], dynamic_axes={"pixel_values": {0: "batch"}, "embedding": {0: "batch"}},
                          opset_version=17, dynamo=False)
    if force or not text_path.exists():
        values = processor(text=["test"], padding="max_length", truncation=True, max_length=64, return_tensors="pt")
        torch.onnx.export(TextEncoder(model).eval(), (values["input_ids"],), text_path,
                          input_names=["input_ids"], output_names=["embedding"],
                          dynamic_axes={"input_ids": {0: "batch"}, "embedding": {0: "batch"}},
                          opset_version=17, dynamo=False)
    for path in (image_path, text_path):
        onnx.checker.check_model(onnx.load(path, load_external_data=False))
    return image_path, text_path


def quantize(image_path, text_path, force=False):
    INT8.mkdir(parents=True, exist_ok=True)
    outputs = []
    for source in (image_path, text_path):
        target = INT8 / source.name
        if force or not target.exists():
            quantize_dynamic(source, target, per_channel=True, weight_type=QuantType.QInt8)
        outputs.append(target)
    return outputs


def options(threads):
    result = ort.SessionOptions()
    if threads:
        result.intra_op_num_threads = threads
        result.inter_op_num_threads = 1
        result.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return result


class PeakMemory:
    def __enter__(self):
        self.stop = False
        self.peak = psutil.Process().memory_info().rss
        def sample():
            while not self.stop:
                self.peak = max(self.peak, psutil.Process().memory_info().rss)
                time.sleep(.02)
        self.thread = threading.Thread(target=sample, daemon=True); self.thread.start()
        return self
    def __exit__(self, *_):
        self.stop = True; self.thread.join()


def encode_pt(model, processor, records, queries, batch):
    paths = [ROOT / x["path"] for x in records]
    images, texts = [], []
    t0 = time.perf_counter()
    with torch.inference_mode():
        for pos in range(0, len(paths), batch):
            inp = processor(images=[Image.open(x).convert("RGB") for x in paths[pos:pos+batch]], return_tensors="pt")
            images.append(ImageEncoder(model)(inp["pixel_values"]).numpy())
    image_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    with torch.inference_mode():
        for pos in range(0, len(queries), batch):
            inp = processor(text=[x["text"] for x in queries[pos:pos+batch]], padding="max_length", truncation=True, max_length=64, return_tensors="pt")
            texts.append(TextEncoder(model)(inp["input_ids"]).numpy())
    return np.concatenate(images), np.concatenate(texts), image_s, time.perf_counter()-t0


def encode_ort(paths, processor, records, queries, batch, threads):
    started = time.perf_counter(); image_session = ort.InferenceSession(str(paths[0]), sess_options=options(threads), providers=["CPUExecutionProvider"]); text_session = ort.InferenceSession(str(paths[1]), sess_options=options(threads), providers=["CPUExecutionProvider"]); load_s=time.perf_counter()-started
    images=[]; t0=time.perf_counter()
    for pos in range(0,len(records),batch):
        inp=processor(images=[Image.open(ROOT/x["path"]).convert("RGB") for x in records[pos:pos+batch]],return_tensors="np")
        images.append(image_session.run(None,{"pixel_values":inp["pixel_values"]})[0])
    image_s=time.perf_counter()-t0; texts=[]; t0=time.perf_counter()
    for pos in range(0,len(queries),batch):
        inp=processor(text=[x["text"] for x in queries[pos:pos+batch]],padding="max_length",truncation=True,max_length=64,return_tensors="np")
        texts.append(text_session.run(None,{"input_ids":inp["input_ids"]})[0])
    return np.concatenate(images),np.concatenate(texts),load_s,image_s,time.perf_counter()-t0


def similarity(a,b):
    cos=np.sum(a*b,axis=1)/(np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1))
    return {"cosine_mean":float(cos.mean()),"cosine_min":float(cos.min()),"l2_mean":float(np.linalg.norm(a-b,axis=1).mean())}


def size_mb(path): return sum(x.stat().st_size for x in path.rglob("*") if x.is_file())/1024**2


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--force-export",action="store_true"); parser.add_argument("--quick",action="store_true"); args=parser.parse_args()
    sys.path.insert(0,str(ROOT)); from semantic_benchmark.metrics import evaluate
    records=json.loads((ROOT/"data/manifest.json").read_text(encoding="utf-8")); queries=json.loads((ROOT/"data/queries.json").read_text(encoding="utf-8"))
    if args.quick: records,queries=records[:8],queries[:4]
    snapshot=local_snapshot(); os.environ["HF_HUB_OFFLINE"]="1"; os.environ["TRANSFORMERS_OFFLINE"]="1"
    load0=time.perf_counter(); processor=AutoProcessor.from_pretrained(snapshot,local_files_only=True,use_fast=False); model=AutoModel.from_pretrained(snapshot,local_files_only=True).eval(); pt_load=time.perf_counter()-load0
    image_path,text_path=export_models(model,processor,args.force_export); int8_paths=quantize(image_path,text_path,args.force_export)
    with PeakMemory() as mem: pt_i,pt_t,pt_is,pt_ts=encode_pt(model,processor,records,queries,4)
    results={"environment":{"python":sys.version,"torch":torch.__version__,"transformers":__import__('transformers').__version__,"onnx":onnx.__version__,"onnxruntime":ort.__version__,"cpu":os.environ.get('PROCESSOR_IDENTIFIER'),"logical_threads":os.cpu_count(),"providers":ort.get_available_providers()},"export":{"opset":17,"image_inputs":["pixel_values"],"text_inputs":["input_ids"],"output":"embedding","dynamic_axis":"batch","image_shape":["batch",3,224,224],"text_shape":["batch",64],"dimension":768},"runtimes":{},"compatibility":{}}
    pt_metrics,pt_rows=evaluate(pt_i,pt_t,records,queries); results["runtimes"]["pytorch"]={"metrics":pt_metrics,"rows":pt_rows,"load_s":pt_load,"image_ms":pt_is*1000/len(records),"query_ms":pt_ts*1000/len(queries),"peak_rss_mb":mem.peak/1024**2,"model_mb":size_mb(snapshot)}
    for name,paths,threads in [("onnx_fp32",(image_path,text_path),None),("onnx_fp32_balanced",(image_path,text_path),max(1,(os.cpu_count() or 4)//2)),("onnx_int8",int8_paths,max(1,(os.cpu_count() or 4)//2))]:
        with PeakMemory() as mem:
            oi,ot,load_s,isec,tsec=encode_ort(paths,processor,records,queries,4,threads)
        metrics,rows=evaluate(oi,ot,records,queries)
        results["runtimes"][name]={"metrics":metrics,"rows":rows,"load_s":load_s,"image_ms":isec*1000/len(records),"query_ms":tsec*1000/len(queries),"peak_rss_mb":mem.peak/1024**2,"model_mb":sum(x.stat().st_size for x in paths)/1024**2,"threads":threads or "default"}
        results["compatibility"][name]={"image":similarity(pt_i,oi),"text":similarity(pt_t,ot),"rank_agreement":float(np.mean(np.argmax(pt_t@pt_i.T,axis=1)==np.argmax(ot@oi.T,axis=1))),"cross_pt_image_ort_text":evaluate(pt_i,ot,records,queries)[0],"cross_ort_image_pt_text":evaluate(oi,pt_t,records,queries)[0]}
    CACHE.mkdir(parents=True,exist_ok=True); out=ROOT/"results/siglip2_onnx_benchmark.json"; out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(out); return 0
if __name__=="__main__": raise SystemExit(main())
