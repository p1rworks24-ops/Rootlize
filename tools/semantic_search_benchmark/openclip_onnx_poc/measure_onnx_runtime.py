"""Measure a clean ONNX Runtime-only process using prepared benchmark tensors."""

import json
import threading
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import psutil

HERE = Path(__file__).resolve().parent


def main():
    process = psutil.Process(); peak = process.memory_info().rss; stop = False
    def sample():
        nonlocal peak
        while not stop:
            peak = max(peak, process.memory_info().rss); time.sleep(.01)
    thread = threading.Thread(target=sample, daemon=True); thread.start()
    arrays = np.load(HERE / "prepared_inputs.npz")
    options = ort.SessionOptions(); options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    started=time.perf_counter()
    image=ort.InferenceSession(str(HERE/"bundle"/"image_encoder.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    text=ort.InferenceSession(str(HERE/"bundle"/"text_encoder.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    load_s=time.perf_counter()-started
    started=time.perf_counter()
    for i in range(0,len(arrays["pixels"]),4): image.run(["embedding"],{"pixel_values":arrays["pixels"][i:i+4]})
    image_s=time.perf_counter()-started
    started=time.perf_counter()
    for i in range(0,len(arrays["tokens"]),4): text.run(["embedding"],{"input_ids":arrays["tokens"][i:i+4]})
    text_s=time.perf_counter()-started
    stop=True; thread.join()
    result={"model_load_s":load_s,"image_total_s":image_s,"image_ms_each":image_s*1000/len(arrays["pixels"]),
            "text_total_s":text_s,"text_ms_each":text_s*1000/len(arrays["tokens"]),"peak_rss_mb":peak/1024**2}
    (HERE/"onnx_runtime_performance.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__": main()
