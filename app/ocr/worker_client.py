"""Qt-free synchronous client for one local OCR worker process."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from app.ocr.worker_exceptions import OCRWorkerBusyError,OCRWorkerCrashedError,OCRWorkerInitializationError,OCRWorkerNotRunningError,OCRWorkerProtocolError,OCRWorkerStartupError,OCRWorkerTimeoutError
from app.ocr.worker_protocol import OUTPUT_TYPES,OCRWorkerRequest,OCRWorkerResult,ProtocolMessage,decode_message,encode_message,parse_result,request_message


@dataclass(frozen=True)
class OCRWorkerTimeouts:
    start: float=10.0
    initialize: float=30.0
    ping: float=3.0
    ocr: float=60.0
    shutdown: float=5.0


@dataclass(frozen=True)
class OCRWorkerConfig:
    model_dir: Path | None=None
    timeouts: OCRWorkerTimeouts=OCRWorkerTimeouts()
    fake_mode: str | None=None
    command: tuple[str,...] | None=None
    stderr_lines: int=50


class OCRWorkerClient:
    """One process, one in-flight request; public methods are thread-safe."""
    def __init__(self,config:OCRWorkerConfig):
        self.config=config; self.process:subprocess.Popen|None=None; self.state="stopped"
        self._responses:queue.Queue[str|None]=queue.Queue(); self._stderr=deque(maxlen=config.stderr_lines)
        self._request_lock=threading.Lock(); self._write_lock=threading.Lock()

    def start(self):
        with self._request_lock:
            if self.is_running(): return
            command=list(self.config.command or (sys.executable,"-m","app.ocr.worker_entry"))
            if self.config.model_dir: command.extend(("--model-dir",str(self.config.model_dir)))
            if self.config.fake_mode: command.extend(("--fake-mode",self.config.fake_mode))
            worker_env=os.environ.copy()
            # Do not leak a parent virtualenv's site-packages into a dedicated
            # OCR runtime.  Only make the Capixe source package importable.
            worker_env["PYTHONPATH"]=str(Path(__file__).resolve().parents[2])
            try:
                self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",bufsize=1,shell=False,env=worker_env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            except (OSError,ValueError) as exc: raise OCRWorkerStartupError("OCR worker could not be started.") from exc
            self.state="running"; self._responses=queue.Queue(); self._stderr.clear(); process=self.process; responses=self._responses
            threading.Thread(target=self._read_stdout,args=(process,responses),daemon=True).start(); threading.Thread(target=self._read_stderr,args=(process,),daemon=True).start()
            deadline=time.monotonic()+self.config.timeouts.start
            while time.monotonic()<deadline:
                if self.process.poll() is None: return
                time.sleep(.01)
            self.terminate(); raise OCRWorkerStartupError("OCR worker did not remain running.")

    def is_running(self): return self.process is not None and self.process.poll() is None and self.state in {"running","initialized"}

    def initialize(self):
        response=self._exchange(ProtocolMessage("initialize",uuid.uuid4().hex),self.config.timeouts.initialize)
        if response.type!="initialized" or not response.payload.get("success"):
            self.state="broken"; raise OCRWorkerInitializationError(str(response.payload.get("error_message_safe","OCR worker initialization failed.")))
        self.state="initialized"; return response.payload

    def ping(self):
        response=self._exchange(ProtocolMessage("ping",uuid.uuid4().hex),self.config.timeouts.ping)
        if response.type!="pong": raise OCRWorkerProtocolError("Expected pong response.")
        return True

    def submit_ocr(self,request:OCRWorkerRequest,timeout:float|None=None):
        if not self._request_lock.acquire(blocking=False): raise OCRWorkerBusyError("OCR worker already has an active request.")
        try:
            response=self._exchange_unlocked(request_message(request),timeout or self.config.timeouts.ocr)
            if response.request_id!=request.request_id: self.state="broken"; raise OCRWorkerProtocolError("OCR response request_id does not match.")
            if response.type=="error":
                return OCRWorkerResult(request.request_id,False,request.path,error_type=response.payload.get("error_type","internal_error"),error_message_safe=response.payload.get("error_message_safe","Worker request failed."),retryable=bool(response.payload.get("retryable")))
            return parse_result(response)
        finally: self._request_lock.release()

    def shutdown(self):
        if self.state=="broken": self.terminate(); return
        if not self.is_running(): self._close_pipes(); self.state="stopped"; return
        try: self._exchange(ProtocolMessage("shutdown",uuid.uuid4().hex),self.config.timeouts.shutdown)
        except (OCRWorkerTimeoutError,OCRWorkerCrashedError,OCRWorkerProtocolError): self.terminate(); return
        try: self.process.wait(timeout=self.config.timeouts.shutdown)
        except subprocess.TimeoutExpired: self.terminate(); return
        self._close_pipes(); self.state="stopped"

    def terminate(self):
        process=self.process
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        self._close_pipes(); self.state="stopped"

    def restart(self): self.terminate(); self.start(); return self.initialize()

    @property
    def stderr_tail(self): return "\n".join(self._stderr)

    def _exchange(self,message,timeout):
        if not self._request_lock.acquire(blocking=False): raise OCRWorkerBusyError("OCR worker already has an active request.")
        try: return self._exchange_unlocked(message,timeout)
        finally: self._request_lock.release()

    def _exchange_unlocked(self,message,timeout):
        if not self.is_running(): raise OCRWorkerNotRunningError("OCR worker is not running.")
        try:
            with self._write_lock:
                self.process.stdin.write(encode_message(message)); self.process.stdin.flush()
        except (OSError,BrokenPipeError) as exc: self.state="broken"; raise OCRWorkerCrashedError("OCR worker input is closed.") from exc
        try: line=self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            self.terminate(); self.state="broken"; raise OCRWorkerTimeoutError("OCR worker response timed out.") from exc
        if line is None:
            code=self.process.poll() if self.process else None; self.state="broken"
            raise OCRWorkerCrashedError(f"OCR worker exited unexpectedly (code={code}).")
        try: return decode_message(line,allowed_types=OUTPUT_TYPES)
        except OCRWorkerProtocolError: self.state="broken"; raise

    def _read_stdout(self,process,responses):
        try:
            for line in process.stdout: responses.put(line)
        finally: responses.put(None)

    def _read_stderr(self,process):
        for line in process.stderr: self._stderr.append(line.rstrip()[-2000:])

    def _close_pipes(self):
        process=self.process; self.process=None
        if process:
            for stream in (process.stdin,process.stdout,process.stderr):
                try: stream.close()
                except Exception: pass

    def __enter__(self): self.start(); return self
    def __exit__(self,*_args): self.shutdown()
