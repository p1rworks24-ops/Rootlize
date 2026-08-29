"""Independent stdout-clean Semantic JSON Lines worker."""

from __future__ import annotations

import argparse
import base64
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from app.ocr.fingerprint import calculate_quick_fingerprint
from app.semantic.bundle import load_bundle
from app.semantic.image_decode import decode_semantic_image
from app.semantic.runtime import SemanticRuntime
from app.semantic.models import ModelIdentity
from app.semantic.worker_errors import SemanticWorkerError
from app.semantic.worker_protocol import PROTOCOL_VERSION, SemanticProtocolError, command as make_command, decode, encode

_write_lock = threading.Lock()


def send(data: dict) -> None:
    with _write_lock:
        sys.stdout.write(encode(data)); sys.stdout.flush()


def response(request_id: str, result: dict | None = None, *, error: SemanticWorkerError | None = None) -> None:
    data = {"protocol_version": PROTOCOL_VERSION, "type": "response", "request_id": request_id}
    if error:
        data.update(status="error", error={"code": error.code, "message": str(error), "retryable": error.retryable, "details": {}})
    else: data.update(status="ok", result=result or {})
    send(data)


def event(request_id: str, name: str, payload: dict) -> None:
    send({"protocol_version": PROTOCOL_VERSION, "type": "event", "request_id": request_id, "event": name, "payload": payload})


class Worker:
    def __init__(self, bundle_dir: Path | None, fake_mode: str | None = None):
        self.bundle_dir=bundle_dir; self.fake_mode=fake_mode; self.bundle=None; self.runtime=None
        self.state="idle"; self.active_request=None; self.cancel_flags: dict[str, threading.Event]={}; self.lock=threading.Lock(); self.exit_event=threading.Event()
        self.primary_queue: queue.Queue[tuple[str,str,dict]] = queue.Queue()

    def run(self):
        # Keep model loading and every ONNX call on one stable main thread.
        # The stdin reader remains responsive to cancel/status/shutdown.
        while not self.exit_event.is_set() or self.active_request is not None:
            try: request_id,name,payload=self.primary_queue.get(timeout=.05)
            except queue.Empty: continue
            self.primary(request_id,name,payload)

    def status(self) -> dict:
        identity=None if self.bundle is None else self.bundle.identity
        return {"worker_state": self.state, "loaded_encoders": [] if self.runtime is None else self.runtime.loaded,
                "model_identity": None if identity is None else {"model_id":identity.model_id,"bundle_version":identity.bundle_version,"model_revision":identity.model_revision,"pipeline_version":identity.pipeline_version,"embedding_format_version":identity.embedding_format_version,"dimension":identity.dimension},
                "active_request": self.active_request}

    def ensure_runtime(self, components: list[str]):
        validation_ms=0.0; onnx_ms=0.0
        if self.fake_mode:
            if self.fake_mode == "model-missing":
                from app.semantic.worker_errors import ModelNotInstalledError
                raise ModelNotInstalledError("Semantic model is not installed.")
            if self.bundle is None:
                version="fake-v2" if self.fake_mode == "fake-v2" else "fake-v1"
                identity=ModelIdentity("fake-semantic",version,"fake-revision")
                self.bundle=SimpleNamespace(identity=identity)
                class FakeRuntime:
                    def __init__(self): self.loaded=[]
                    def load(inner, requested): inner.loaded=list(dict.fromkeys(inner.loaded+requested))
                    def embed_image(inner, _path):
                        if self.fake_mode == "slow": time.sleep(.15)
                        return [1.0]+[0.0]*767
                    def embed_text(inner, text):
                        index=sum(text.encode("utf-8"))%768; values=[0.0]*768; values[index]=1.0; return values
                self.runtime=FakeRuntime()
        elif self.bundle is None:
            started=time.perf_counter(); self.bundle=load_bundle(self.bundle_dir)
            validation_ms=(time.perf_counter()-started)*1000
            self.runtime=SemanticRuntime(self.bundle)
        self.state="loading"
        started=time.perf_counter(); self.runtime.load(components)
        onnx_ms=(time.perf_counter()-started)*1000
        self.state="ready"
        return {"bundle_validation_ms": round(validation_ms,1), "onnx_load_ms": round(onnx_ms,1)}

    @staticmethod
    def snapshot(path: Path) -> dict:
        stat=path.stat(); return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "quick_fingerprint": calculate_quick_fingerprint(path)}

    def validate_image(self, payload: dict) -> tuple[Path, dict, dict]:
        raw=str(payload.get("path", "")); path=Path(raw)
        if not raw or "://" in raw or path.is_symlink():
            raise SemanticWorkerError("The image path is not supported.", code="UNSUPPORTED_IMAGE")
        if not path.is_file(): raise SemanticWorkerError("The image is no longer available.", code="FILE_NOT_FOUND", retryable=True)
        expected=payload.get("source_snapshot"); actual=self.snapshot(path)
        if (not isinstance(expected, dict)
                or actual["size_bytes"] != expected.get("size_bytes")
                or actual["mtime_ns"] != expected.get("mtime_ns")
                or (expected.get("quick_fingerprint") is not None
                    and actual["quick_fingerprint"] != expected["quick_fingerprint"])):
            raise SemanticWorkerError("The image changed before processing.", code="FILE_CHANGED", retryable=True)
        # Pillow selects its decoder from the file signature/content.  Do not
        # trust the suffix: managed files may have been renamed independently.
        decode_semantic_image(path).close()
        # Persist the repository snapshot verbatim. Older/scan-failed image
        # records can legitimately lack a fingerprint even when size and mtime
        # are known; returning a newly calculated value would make the
        # repository reject an otherwise valid result as a changed source.
        persisted={"size_bytes": actual["size_bytes"], "mtime_ns": actual["mtime_ns"],
                   "quick_fingerprint": expected.get("quick_fingerprint")}
        return path,actual,persisted

    def embedding_result(self, image_id: str, values: list[float], snapshot: dict, duration: float) -> dict:
        identity=self.bundle.identity; dimension=identity.dimension
        blob=struct.pack(f"<{dimension}f", *values)
        return {"image_id": image_id, "embedding": {"encoding":"base64","dtype":"float32","byte_order":"little","dimension":dimension,"data":base64.b64encode(blob).decode("ascii")},
                "model":{"model_id":identity.model_id,"bundle_version":identity.bundle_version,"model_revision":identity.model_revision,"pipeline_version":identity.pipeline_version,"embedding_format_version":identity.embedding_format_version,"dimension":identity.dimension},
                "source_snapshot":snapshot,"duration_ms":round(duration*1000,3)}

    def primary(self, request_id: str, name: str, payload: dict):
        cancel=self.cancel_flags[request_id]
        try:
            if self.fake_mode == "crash": os._exit(92)
            if name == "load_model":
                timings=self.ensure_runtime(list(payload.get("components", []))); response(request_id,{**self.status(), **timings}); return
            if name == "embed_text":
                text=payload.get("text")
                if not isinstance(text,str) or not text or len(text)>10_000: raise SemanticWorkerError("Invalid text payload.",code="INVALID_REQUEST")
                self.ensure_runtime(["text_encoder"]); self.state="busy"; started=time.perf_counter(); values=self.runtime.embed_text(text)
                response(request_id,{**self.embedding_result("",values,{},time.perf_counter()-started)}); return
            items = payload.get("items") if name == "analyze_images" else [payload]
            if not isinstance(items,list) or len(items)>100_000: raise SemanticWorkerError("Invalid image payload.",code="INVALID_REQUEST")
            self.ensure_runtime(["image_encoder"]); self.state="busy"; total=len(items); succeeded=failed=0
            if name == "analyze_images": event(request_id,"progress",{"processed":0,"succeeded":0,"failed":0,"total":total,"elapsed_ms":0})
            batch_started=time.perf_counter()
            for index,item in enumerate(items):
                if cancel.is_set(): break
                image_id=str(item.get("image_id", "")); started=time.perf_counter()
                try:
                    path,before,persisted=self.validate_image(item); values=self.runtime.embed_image(path); after=self.snapshot(path)
                    if before != after: raise SemanticWorkerError("The image changed during processing.",code="FILE_CHANGED",retryable=True)
                    result=self.embedding_result(image_id,values,persisted,time.perf_counter()-started); succeeded+=1
                    if name == "analyze_images": event(request_id,"item_result",result)
                    else: response(request_id,result); return
                except SemanticWorkerError as exc:
                    failed+=1
                    if name == "analyze_images": event(request_id,"item_error",{"image_id":image_id,"error":{"code":exc.code,"message":str(exc),"retryable":exc.retryable}})
                    else: response(request_id,error=exc); return
                if name == "analyze_images": event(request_id,"progress",{"processed":index+1,"succeeded":succeeded,"failed":failed,"total":total,"elapsed_ms":round((time.perf_counter()-batch_started)*1000,3)})
                if self.fake_mode == "crash-after-one" and index == 0: os._exit(93)
                if cancel.is_set(): break
            processed=succeeded+failed; outcome="cancelled" if cancel.is_set() else "completed"
            response(request_id,{"outcome":outcome,"processed":processed,"succeeded":succeeded,"failed":failed,"remaining":total-processed})
        except SemanticWorkerError as exc: response(request_id,error=exc)
        except Exception: response(request_id,error=SemanticWorkerError("Semantic worker failed."))
        finally:
            with self.lock: self.active_request=None; self.cancel_flags.pop(request_id,None); self.state="ready" if self.runtime else "idle"

    def handle(self, message) -> None:
        name=message.command; payload=message.payload
        if name=="ping": response(message.request_id,{"worker_state":self.state,"protocol_version":PROTOCOL_VERSION}); return
        if name=="get_status": response(message.request_id,self.status()); return
        if name=="cancel":
            target=payload.get("target_request_id"); flag=self.cancel_flags.get(target)
            if flag: flag.set(); result="accepted"
            else: result="already_finished" if target else "not_found"
            response(message.request_id,{"outcome":result}); return
        if name=="shutdown":
            for flag in self.cancel_flags.values(): flag.set()
            self.state="shutting_down"; response(message.request_id,{"accepted":True}); self.exit_event.set(); return
        with self.lock:
            if self.active_request is not None: response(message.request_id,error=SemanticWorkerError("Semantic worker is busy.",code="WORKER_BUSY",retryable=True)); return
            self.active_request=message.request_id; self.cancel_flags[message.request_id]=threading.Event()
        self.primary_queue.put((message.request_id,name,payload))


def main(argv=None) -> int:
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"): stream.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser(add_help=False); parser.add_argument("--bundle-dir",type=Path); parser.add_argument("--fake-mode"); args=parser.parse_args(argv)
    worker=Worker(args.bundle_dir,args.fake_mode)
    def read_commands():
        for line in sys.stdin:
            try: worker.handle(decode(line))
            except SemanticProtocolError as exc:
                try:
                    import json
                    request_id=json.loads(line).get("request_id") or str(__import__("uuid").uuid4())
                except Exception: request_id=str(__import__("uuid").uuid4())
                response(request_id,error=SemanticWorkerError(str(exc),code="INVALID_REQUEST"))
            if worker.exit_event.is_set(): return
        worker.exit_event.set()
    threading.Thread(target=read_commands,daemon=True).start()
    worker.run()
    return 0


if __name__=="__main__": raise SystemExit(main())
