"""Thread-safe multiplexed client for the independent Semantic worker."""

from __future__ import annotations

import base64
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path

from app.paths import get_local_app_data_dir
from app.utils.logger import setup_logger

from .models import ModelIdentity, SemanticWorkerEvent, SemanticWorkItem, SourceSnapshot
from .worker_errors import SemanticWorkerCrashedError, SemanticWorkerError, SemanticWorkerTimeoutError
from .worker_protocol import Message, SemanticProtocolError, command, decode, encode

logger = setup_logger()
SEMANTIC_SEARCH_LOG = get_local_app_data_dir() / "semantic-search.log"
_SECRET_LINE = re.compile(
    r"(?i)(openai_api_key|api[_-]?key|authorization|bearer)\s*[=:]\s*\S+"
)
_SECRET_TOKEN = re.compile(r"sk-[A-Za-z0-9_-]{10,}")


def _install_semantic_diagnostics_log() -> None:
    resolved = SEMANTIC_SEARCH_LOG.resolve()
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == resolved:
            return
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)


def _redact_worker_stderr(text: str) -> str:
    cleaned = _SECRET_LINE.sub(lambda match: f"{match.group(1)}=***", text or "")
    return _SECRET_TOKEN.sub("sk-***", cleaned)


def _missing_runtime_dependency(stderr: str) -> bool:
    text = stderr or ""
    return "ModuleNotFoundError" in text or "No module named" in text


_install_semantic_diagnostics_log()


@dataclass(frozen=True)
class SemanticTimeouts:
    start: float=10.0; ping: float=3.0; status: float=3.0; load: float=120.0
    embed_text: float=30.0; embed_image: float=120.0; stall: float=300.0; shutdown: float=30.0


@dataclass(frozen=True)
class SemanticWorkerConfig:
    bundle_dir: Path | None=None
    python_executable: Path | None=None
    command: tuple[str,...] | None=None
    fake_mode: str | None=None
    timeouts: SemanticTimeouts=SemanticTimeouts()
    idle_seconds: float=900.0
    stderr_lines: int=50
    python_paths: tuple[Path,...]=()


class _Pending:
    def __init__(self): self.messages: queue.Queue[Message|BaseException]=queue.Queue()


class SemanticWorkerClient:
    def __init__(self, config: SemanticWorkerConfig):
        self.config=config; self.process: subprocess.Popen|None=None; self.state="worker stopped"
        self._pending: dict[str,_Pending]={}; self._lock=threading.RLock(); self._write_lock=threading.Lock()
        self._stderr=deque(maxlen=config.stderr_lines); self._idle_timer: threading.Timer|None=None; self._closing=False
        self._loaded_components: set[str]=set()
        self._text_cache: OrderedDict[str, tuple[bytes, ModelIdentity]] = OrderedDict()

    def is_running(self) -> bool: return self.process is not None and self.process.poll() is None

    @staticmethod
    def _default_command(executable: str) -> tuple[str, ...]:
        if bool(getattr(sys, "frozen", False)):
            return (executable, "--semantic-worker")
        return (executable, "-m", "app.semantic.worker")

    def start(self) -> None:
        with self._lock:
            if self.is_running(): return
            started=time.perf_counter()
            self.state="worker starting"; self._closing=False
            executable=str(self.config.python_executable or sys.executable)
            argv=list(self.config.command or self._default_command(executable))
            if self.config.bundle_dir: argv.extend(("--bundle-dir",str(self.config.bundle_dir)))
            if self.config.fake_mode: argv.extend(("--fake-mode",self.config.fake_mode))
            env=os.environ.copy(); env["PYTHONPATH"]=os.pathsep.join(str(path) for path in (Path(__file__).resolve().parents[2],*self.config.python_paths))
            last_error=None
            for _attempt in range(2):
                try:
                    process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",bufsize=1,shell=False,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
                    self.process=process; self._stderr.clear()
                    threading.Thread(target=self._read_stdout,args=(process,),daemon=True).start(); threading.Thread(target=self._read_stderr,args=(process,),daemon=True).start()
                    deadline=time.monotonic()+self.config.timeouts.start
                    while time.monotonic()<deadline:
                        code=process.poll()
                        if code is None:
                            self.state="worker ready"
                            logger.info(
                                "Semantic worker process start elapsed_ms=%.1f",
                                (time.perf_counter()-started)*1000,
                            )
                            return
                        time.sleep(0.05)
                        last_error=self._crash_error(process, "could not be started")
                        break
                except (OSError,ValueError) as exc: last_error=exc
                self._terminate_unlocked()
            self.state="failed"
            if isinstance(last_error, SemanticWorkerError):
                raise last_error
            raise SemanticWorkerCrashedError("Semantic worker could not be started.") from last_error

    def _register(self, name: str, payload: dict | None=None, request_id: str|None=None) -> tuple[str,_Pending]:
        self.start(); request_id,data=command(name,payload,request_id=request_id); pending=_Pending()
        with self._lock:
            if request_id in self._pending: raise SemanticProtocolError("Duplicate active request_id.")
            self._pending[request_id]=pending; self._cancel_idle()
        try:
            with self._write_lock:
                assert self.process and self.process.stdin
                self.process.stdin.write(encode(data)); self.process.stdin.flush()
        except (OSError,BrokenPipeError) as exc:
            with self._lock: self._pending.pop(request_id,None)
            time.sleep(0.05)
            raise self._crash_error(self.process, "input is closed") from exc
        return request_id,pending

    def _finish(self, request_id: str) -> None:
        with self._lock:
            self._pending.pop(request_id,None)
            if not self._pending and not self._closing: self._schedule_idle()

    def _wait(self, pending: _Pending, timeout: float) -> Message:
        try: item=pending.messages.get(timeout=timeout)
        except queue.Empty as exc: raise SemanticWorkerTimeoutError("Semantic worker response timed out.") from exc
        if isinstance(item,BaseException): raise item
        return item

    @staticmethod
    def _result(message: Message) -> dict:
        if message.type!="response": raise SemanticProtocolError("Expected final response.")
        if message.status=="error":
            error=message.error; raise SemanticWorkerError(str(error.get("message","Semantic worker failed.")),code=str(error.get("code","INTERNAL_ERROR")),retryable=bool(error.get("retryable")))
        if message.status!="ok": raise SemanticProtocolError("Invalid response status.")
        return message.result

    def request(self,name: str,payload: dict|None=None,*,timeout: float|None=None) -> dict:
        request_id,pending=self._register(name,payload)
        limit=timeout or self._timeout(name); deadline=time.monotonic()+limit
        try:
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0: raise SemanticWorkerTimeoutError("Semantic worker response timed out.")
                try: message=self._wait(pending,min(remaining,1.0 if name not in {"ping","get_status"} else remaining))
                except SemanticWorkerTimeoutError:
                    # A lightweight control message keeps Windows pipe/worker
                    # scheduling responsive during large ORT session loads.
                    self.request("ping",timeout=self.config.timeouts.ping)
                    continue
                if message.type=="response": return self._result(message)
        except SemanticWorkerTimeoutError:
            self.terminate(); raise
        finally: self._finish(request_id)

    def ping(self) -> bool: self.request("ping"); return True
    def get_status(self) -> dict: return self.request("get_status")
    def load_model(self,components: list[str]) -> dict:
        needed=[component for component in components if component not in self._loaded_components]
        if not needed: return self.get_status()
        self.state="model loading"
        started=time.perf_counter()
        result=self.request("load_model",{"components":needed})
        self._loaded_components.update(needed); self.state="ready"
        logger.info(
            "Semantic load_model components=%s validation_ms=%s onnx_load_ms=%s total_seconds=%.3f",
            needed,
            result.get("bundle_validation_ms"),
            result.get("onnx_load_ms"),
            time.perf_counter()-started,
        )
        return result
    def embed_text(self,text: str) -> tuple[bytes,ModelIdentity]:
        load_started=time.perf_counter()
        self.load_model(["text_encoder"])
        load_seconds=time.perf_counter()-load_started
        cached=self._text_cache.get(text)
        if cached is not None:
            self._text_cache.move_to_end(text)
            logger.info(
                "Semantic embed_text cache=hit load_seconds=%.3f embed_seconds=0.000 chars=%d",
                load_seconds, len(text),
            )
            return cached
        embed_started=time.perf_counter()
        result=self.request("embed_text",{"text":text})
        decoded=self._decode_result(result)
        self._text_cache[text]=decoded
        while len(self._text_cache) > 16:
            self._text_cache.popitem(last=False)
        logger.info(
            "Semantic embed_text cache=miss load_seconds=%.3f embed_seconds=%.3f chars=%d",
            load_seconds, time.perf_counter()-embed_started, len(text),
        )
        return decoded
    def embed_image(self,item: SemanticWorkItem) -> tuple[bytes,ModelIdentity]:
        self.load_model(["image_encoder"])
        result=self.request("embed_image",self._item_payload(item)); return self._decode_result(result)

    def analyze(self, items: tuple[SemanticWorkItem,...], *, request_id: str, cancel_event: threading.Event):
        self.load_model(["image_encoder"])
        rid,pending=self._register("analyze_images",{"items":[self._item_payload(item) for item in items]},request_id=request_id); cancel_sent=False; self.state="busy"
        last_activity=time.monotonic()
        try:
            while True:
                if cancel_event.is_set() and not cancel_sent:
                    self.cancel(rid); cancel_sent=True
                try: message=self._wait(pending,min(0.1,self.config.timeouts.stall))
                except SemanticWorkerTimeoutError:
                    if self.is_running() and time.monotonic()-last_activity < self.config.timeouts.stall: continue
                    try: self.cancel(rid)
                    finally: self.terminate()
                    raise
                last_activity=time.monotonic()
                if message.type=="response":
                    result=self._result(message)
                    if result.get("outcome")=="cancelled": cancel_event.set()
                    return
                yield self._event(message)
        finally: self.state="ready" if self.is_running() else "worker stopped"; self._finish(rid)

    def cancel(self,target_request_id: str) -> dict:
        return self.request("cancel",{"target_request_id":target_request_id},timeout=self.config.timeouts.ping)

    def shutdown(self) -> None:
        with self._lock: self._closing=True; self._cancel_idle(); active=tuple(self._pending)
        for request_id in active:
            try: self.cancel(request_id)
            except SemanticWorkerError: pass
        if self.is_running():
            try: self.request("shutdown",{"graceful":True},timeout=self.config.timeouts.shutdown)
            except (SemanticWorkerError,SemanticProtocolError): pass
            process=self.process
            if process:
                try: process.wait(timeout=self.config.timeouts.shutdown)
                except subprocess.TimeoutExpired: self.terminate(); return
        with self._lock: self._close_unlocked(); self.state="worker stopped"; self._closing=False

    def terminate(self) -> None:
        with self._lock: self._terminate_unlocked(); self._closing=False

    def _terminate_unlocked(self):
        process=self.process
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        self._close_unlocked(); self.state="worker stopped"

    def _close_unlocked(self):
        process=self.process; self.process=None
        self._loaded_components.clear()
        self._text_cache.clear()
        if process:
            for stream in (process.stdin,process.stdout,process.stderr):
                try: stream.close()
                except Exception: pass

    def _read_stdout(self,process):
        try:
            for line in process.stdout:
                try: message=decode(line)
                except SemanticProtocolError as exc: self._fail_all(exc); self.terminate(); return
                with self._lock: pending=self._pending.get(message.request_id)
                if pending is None: self._fail_all(SemanticProtocolError("Unknown response request_id.")); self.terminate(); return
                pending.messages.put(message)
        finally:
            if not self._closing:
                time.sleep(0.05)
                self._fail_all(self._crash_error(process, "exited unexpectedly"))

    def _read_stderr(self,process):
        for line in process.stderr: self._stderr.append(line.rstrip()[-2000:])

    def _crash_error(self, process, reason: str) -> SemanticWorkerError:
        code = None if process is None else process.poll()
        stderr = _redact_worker_stderr(self.stderr_tail)
        logger.error(
            "Semantic worker crash reason=%s exit_code=%s stderr_tail=%r",
            reason, code, stderr[-4000:],
        )
        if _missing_runtime_dependency(stderr):
            return SemanticWorkerError(
                "Semantic runtime is not installed.", code="MODEL_LOAD_FAILED"
            )
        return SemanticWorkerCrashedError(
            f"Semantic worker {reason} (code={code})."
        )

    def _fail_all(self,error: BaseException):
        with self._lock:
            for pending in self._pending.values(): pending.messages.put(error)
            self.state="failed"

    def _timeout(self,name: str) -> float:
        return {"ping":self.config.timeouts.ping,"get_status":self.config.timeouts.status,"load_model":self.config.timeouts.load,"embed_text":self.config.timeouts.embed_text,"embed_image":self.config.timeouts.embed_image,"shutdown":self.config.timeouts.shutdown}.get(name,self.config.timeouts.stall)

    def _schedule_idle(self):
        if self.config.idle_seconds<=0: return
        self._idle_timer=threading.Timer(self.config.idle_seconds,self.shutdown); self._idle_timer.daemon=True; self._idle_timer.start()
    def _cancel_idle(self):
        if self._idle_timer: self._idle_timer.cancel(); self._idle_timer=None

    @staticmethod
    def _item_payload(item: SemanticWorkItem) -> dict:
        return {"image_id":str(item.image_id),"path":item.path,"source_snapshot":{"size_bytes":item.source_snapshot.size_bytes,"mtime_ns":item.source_snapshot.mtime_ns,"quick_fingerprint":item.source_snapshot.quick_fingerprint}}

    @staticmethod
    def _decode_result(result: dict) -> tuple[bytes,ModelIdentity]:
        embedding=result["embedding"]; model=result["model"]
        dimension = embedding.get("dimension")
        if embedding.get("encoding")!="base64" or embedding.get("dtype")!="float32" or embedding.get("byte_order")!="little" or dimension not in {512,768}: raise SemanticProtocolError("Invalid embedding envelope.")
        try: blob=base64.b64decode(embedding["data"],validate=True); identity=ModelIdentity(model["model_id"],model["bundle_version"],model["model_revision"],int(model["pipeline_version"]),int(model["embedding_format_version"]),int(model["dimension"]))
        except (KeyError,TypeError,ValueError) as exc: raise SemanticProtocolError("Invalid embedding result.") from exc
        if identity.dimension != dimension or len(blob) != dimension * 4:
            raise SemanticProtocolError("Embedding identity does not match its envelope.")
        return blob,identity

    def _event(self,message: Message) -> SemanticWorkerEvent:
        if message.type!="event": raise SemanticProtocolError("Expected event.")
        payload=message.payload; image_id=int(payload["image_id"]) if payload.get("image_id") else None
        if message.event=="item_result":
            blob,identity=self._decode_result(payload); source=SourceSnapshot(**payload["source_snapshot"])
            return SemanticWorkerEvent("item_result",message.request_id,0,0,image_id=image_id,embedding=blob,model_identity=identity,source_snapshot=source)
        if message.event=="item_error":
            error=payload.get("error",{}); return SemanticWorkerEvent("item_error",message.request_id,0,0,image_id=image_id,error_code=error.get("code"),retryable=bool(error.get("retryable")))
        if message.event=="progress": return SemanticWorkerEvent("progress",message.request_id,int(payload.get("processed",0)),int(payload.get("total",0)))
        raise SemanticProtocolError("Unknown Semantic event.")

    @property
    def stderr_tail(self) -> str: return "\n".join(self._stderr)
    def __enter__(self): self.start(); return self
    def __exit__(self,*_args): self.shutdown()
