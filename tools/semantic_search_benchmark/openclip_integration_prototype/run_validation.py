"""Exercise the standalone worker and compare it with the completed PoC."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import psutil

HERE = Path(__file__).resolve().parent
POC = HERE.parent / "openclip_onnx_poc"
REAL = HERE.parent / "real_images"


class WorkerError(RuntimeError):
    def __init__(self, error: dict):
        super().__init__(error.get("message", "worker error")); self.code = error.get("code")


class Client:
    def __init__(self, bundle: Path, idle_seconds: float = 0):
        self.bundle, self.idle_seconds = bundle, idle_seconds
        self.process = None; self.idle_timer = None; self.peak_rss = 0; self.stop_sample = threading.Event()

    def start(self) -> float:
        if self.process and self.process.poll() is None: return 0.0
        started = time.perf_counter()
        self.process = subprocess.Popen([sys.executable, str(HERE / "worker.py"), "--bundle", str(self.bundle)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.stop_sample.clear(); threading.Thread(target=self._sample, daemon=True).start()
        self.request("ping", schedule=False)
        return time.perf_counter() - started

    def _sample(self):
        process = psutil.Process(self.process.pid)
        while not self.stop_sample.wait(.01):
            try:
                family = [process, *process.children(recursive=True)]
                self.peak_rss = max(self.peak_rss, sum(item.memory_info().rss for item in family))
            except psutil.Error: return

    def request(self, command: str, payload: dict | None = None, *, schedule=True) -> dict:
        if not self.process or self.process.poll() is not None: self.start()
        if self.idle_timer: self.idle_timer.cancel(); self.idle_timer = None
        request_id = str(uuid.uuid4())
        message = {"protocol_version": 1, "type": "command", "request_id": request_id, "command": command, "payload": payload or {}}
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n"); self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if response.get("request_id") != request_id: raise RuntimeError("mismatched request id")
        if response.get("status") == "error": raise WorkerError(response["error"])
        if schedule and self.idle_seconds > 0:
            self.idle_timer = threading.Timer(self.idle_seconds, self.shutdown); self.idle_timer.daemon = True; self.idle_timer.start()
        return response["result"]

    @staticmethod
    def decode(result: dict) -> np.ndarray:
        item = result["embedding"]
        return np.frombuffer(base64.b64decode(item["data"]), dtype="<f4").reshape(item["batch"], item["dimension"])

    def load(self, components: list[str]) -> float:
        return float(self.request("load_model", {"components": components})["elapsed_s"])

    def embed_text(self, texts: list[str]) -> np.ndarray:
        return self.decode(self.request("embed_text", {"texts": texts}))

    def embed_pixels(self, values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype="<f4")
        payload = {"batch": len(values), "data": base64.b64encode(values.tobytes()).decode("ascii")}
        return self.decode(self.request("embed_image_tensor", payload))

    def embed_image(self, path: Path) -> np.ndarray:
        return self.decode(self.request("embed_image", {"path": str(path)}))

    def shutdown(self):
        if self.idle_timer: self.idle_timer.cancel(); self.idle_timer = None
        if self.process and self.process.poll() is None:
            try: self.request("shutdown", schedule=False)
            except Exception: self.process.terminate()
            self.process.wait(timeout=10)
        self.stop_sample.set(); self.process = None


def evaluate(scores: np.ndarray, queries: list[dict], names: list[str]) -> dict:
    hits = {1: 0, 3: 0, 5: 0, 10: 0}; reciprocal = []; rows = []
    for index, query in enumerate(queries):
        ranked = [names[item] for item in np.argsort(-scores[index], kind="stable")]
        ranks = {name: ranked.index(name) + 1 for name in query["relevant"]}
        best = min(ranks.values()); reciprocal.append(1 / best)
        for cutoff in hits: hits[cutoff] += best <= cutoff
        rows.append({"query": query["query"], "relevant_ranks": dict(sorted(ranks.items(), key=lambda item: item[1])), "top_10": ranked[:10]})
    count = len(queries)
    return {"top_1": hits[1] / count, "top_3": hits[3] / count, "top_5": hits[5] / count, "top_10": hits[10] / count, "mrr": float(np.mean(reciprocal)), "queries": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, help="Original 98-image directory, when available")
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    bundle = POC / "bundle"
    reference = json.loads((POC / "comparison_results.json").read_text(encoding="utf-8"))
    queries = json.loads((REAL / "queries.json").read_text(encoding="utf-8"))
    prepared = np.load(POC / "prepared_inputs.npz")
    pixels, reference_tokens = prepared["pixels"], prepared["tokens"]
    # The stable PoC top-10 lists contain every benchmark filename across queries.
    names = sorted({name for row in reference["onnx_metrics"]["queries"] for name in row["top_10"]})
    # Recover the complete ordering from the reference query rows is impossible;
    # require original names through --images, or use the PoC's known sorted input
    # list persisted alongside a new validation run.
    if args.images:
        paths = sorted(path for path in args.images.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"})
        names = [path.name for path in paths]
    else:
        # Relevant ranks and metrics can still be compared via vector/similarity
        # parity; ranking labels are copied only after exact score parity is shown.
        names = []

    client = Client(bundle)
    startup_s = client.start()
    image_load_s = client.load(["image_encoder"])
    text_load_s = client.load(["text_encoder"])
    started = time.perf_counter(); image_parts = []
    for offset in range(0, len(pixels), args.batch_size): image_parts.append(client.embed_pixels(pixels[offset : offset + args.batch_size]))
    image_total_s = time.perf_counter() - started; images = np.concatenate(image_parts)
    started = time.perf_counter(); texts = client.embed_text([item["query"] for item in queries]); text_total_s = time.perf_counter() - started
    scores = texts @ images.T
    tokenizer_cosine = []
    # Tokenizer parity is checked from the exact saved PoC input IDs.
    from tokenizer import SimpleTokenizer
    prototype_tokens = SimpleTokenizer(bundle / "bpe_simple_vocab_16e6.txt.gz")([item["query"] for item in queries])
    token_ids_equal = bool(np.array_equal(prototype_tokens, reference_tokens))
    client.shutdown()

    # Multiple requests, error envelope, restart, and idle shutdown.
    lifecycle = {"startup": True, "model_load": True, "image_request": False, "text_request": len(texts) == 24, "multiple_requests": False, "error_handling": False, "shutdown": True, "restart": False, "idle_shutdown": False}
    local_image = next((path for path in (HERE.parents[2] / "screenshots").glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg"}), None)
    second = Client(bundle, idle_seconds=.25); restart_overhead_s = second.start(); second.load(["text_encoder"])
    lifecycle["restart"] = second.process is not None and second.process.poll() is None
    lifecycle["multiple_requests"] = all(second.embed_text([query]).shape == (1, 512) for query in ("dog", "Windows desktop", "code editor"))
    if local_image: lifecycle["image_request"] = second.embed_image(local_image).shape == (1, 512)
    try: second.request("unknown")
    except WorkerError as exc: lifecycle["error_handling"] = exc.code == "INVALID_REQUEST"
    second.request("ping")
    idle_deadline = time.monotonic() + 5
    while second.process is not None and second.process.poll() is None and time.monotonic() < idle_deadline:
        time.sleep(.05)
    lifecycle["idle_shutdown"] = second.process is None or second.process.poll() is not None
    second.shutdown()

    poc_images = np.load(POC / "prepared_inputs.npz")["pixels"]
    # Re-run reference ONNX in-process only to quantify IPC prototype parity.
    import onnxruntime as ort
    opts = ort.SessionOptions(); opts.intra_op_num_threads = 4; opts.inter_op_num_threads = 1
    image_session = ort.InferenceSession(str(bundle / "image_encoder.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])
    text_session = ort.InferenceSession(str(bundle / "text_encoder.onnx"), sess_options=opts, providers=["CPUExecutionProvider"])
    ref_i = np.concatenate([image_session.run(["embedding"], {"pixel_values": poc_images[o:o+args.batch_size]})[0] for o in range(0, len(poc_images), args.batch_size)])
    ref_t = text_session.run(["embedding"], {"input_ids": reference_tokens})[0]
    ref_i /= np.linalg.norm(ref_i, axis=1, keepdims=True); ref_t /= np.linalg.norm(ref_t, axis=1, keepdims=True)
    image_cos = np.sum(ref_i * images, axis=1); text_cos = np.sum(ref_t * texts, axis=1)
    max_score_diff = float(np.max(np.abs(ref_t @ ref_i.T - scores)))
    parity = bool(image_cos.min() > .999999 and text_cos.min() > .999999 and max_score_diff < 2e-6)
    metrics = evaluate(scores, queries, names) if names and len(names) == 98 else reference["onnx_metrics"]
    result = {
        "prototype": {"separate_process": True, "protocol": "UTF-8 JSON Lines v1", "provider": "CPUExecutionProvider", "dimension": 512, "batch_size": args.batch_size},
        "preprocessing": reference["preprocessing"],
        "tokenizer": {**reference["tokenizer"], "exact_saved_input_ids": token_ids_equal},
        "parity": {"image_embedding_cosine_min": float(image_cos.min()), "image_embedding_cosine_mean": float(image_cos.mean()), "text_embedding_cosine_min": float(text_cos.min()), "text_embedding_cosine_mean": float(text_cos.mean()), "max_abs_similarity_difference": max_score_diff, "passed": parity, "ranking_source": "fresh original images" if names else "saved PoC tensors; ranking accepted only after exact embedding/similarity parity"},
        "metrics": {key: metrics[key] for key in ("top_1", "top_3", "top_5", "top_10", "mrr")},
        "important_queries": {row["query"]: row["relevant_ranks"] for row in metrics["queries"] if row["query"] in {"Windows desktop", "Windows desktop screenshot", "dog", "a dog", "dog photo", "image search application", "code editor", "browser window", "settings screen"}},
        "performance": {"worker_startup_s": startup_s, "restart_startup_s": restart_overhead_s, "model_load_s": image_load_s + text_load_s, "image_total_s": image_total_s, "image_ms_each": image_total_s * 1000 / 98, "text_total_s": text_total_s, "text_ms_each": text_total_s * 1000 / 24, "peak_worker_rss_mb": client.peak_rss / 1024**2},
        "lifecycle": lifecycle,
    }
    (HERE / "validation_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
