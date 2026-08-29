"""Independent UTF-8 JSONL worker approximating Capixe's worker lifecycle."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path

import numpy as np

from runtime import OpenCLIPRuntime, PrototypeError


def envelope(request_id: str, *, result=None, error=None) -> dict:
    value = {"protocol_version": 1, "type": "response", "request_id": request_id, "status": "error" if error else "ok"}
    value["error" if error else "result"] = error or result or {}
    return value


def encode_array(values: np.ndarray) -> dict:
    data = np.asarray(values, dtype="<f4")
    return {"encoding": "base64", "dtype": "float32", "dimension": 512, "batch": len(data), "data": base64.b64encode(data.tobytes()).decode("ascii")}


def decode_pixels(payload: dict) -> np.ndarray:
    try:
        batch = int(payload["batch"])
        raw = base64.b64decode(payload["data"], validate=True)
        return np.frombuffer(raw, dtype="<f4").reshape(batch, 3, 224, 224)
    except Exception as exc:
        raise PrototypeError("Invalid image tensor envelope.", "INVALID_REQUEST") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    runtime = OpenCLIPRuntime(args.bundle)
    for line in sys.stdin:
        request_id = str(uuid.uuid4())
        try:
            message = json.loads(line)
            request_id = message["request_id"]
            command, payload = message["command"], message.get("payload", {})
            if message.get("protocol_version") != 1:
                raise PrototypeError("Unsupported protocol.", "INVALID_REQUEST")
            if command == "ping":
                result = {"pong": True}
            elif command == "get_status":
                result = {"worker_state": "ready" if runtime.loaded else "idle", "loaded_components": runtime.loaded, "pid": __import__("os").getpid()}
            elif command == "load_model":
                started = time.perf_counter(); runtime.load(list(payload["components"])); result = {"loaded_components": runtime.loaded, "elapsed_s": time.perf_counter() - started}
            elif command == "embed_image":
                result = {"embedding": encode_array(runtime.embed_image(Path(payload["path"])))}
            elif command == "embed_image_tensor":
                result = {"embedding": encode_array(runtime.embed_pixels(decode_pixels(payload)))}
            elif command == "embed_text":
                result = {"embedding": encode_array(runtime.embed_text(payload["texts"]))}
            elif command == "shutdown":
                print(json.dumps(envelope(request_id, result={"outcome": "shutdown"}), separators=(",", ":")), flush=True)
                return 0
            else:
                raise PrototypeError("Unknown command.", "INVALID_REQUEST")
            response = envelope(request_id, result=result)
        except PrototypeError as exc:
            response = envelope(request_id, error={"code": exc.code, "message": str(exc), "retryable": exc.retryable})
        except Exception as exc:
            response = envelope(request_id, error={"code": "INTERNAL_ERROR", "message": str(exc), "retryable": False})
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
