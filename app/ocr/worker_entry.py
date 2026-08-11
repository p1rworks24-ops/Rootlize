"""Dedicated stdout-clean JSON Lines OCR worker entry point."""

from __future__ import annotations

import argparse
import multiprocessing
import sys
import time
from pathlib import Path

from app.ocr.worker_process import FakeEngine,ProductionEngine,process_request
from app.ocr.worker_protocol import INPUT_TYPES,ProtocolMessage,decode_message,encode_message,parse_request,result_message
from app.ocr.worker_exceptions import OCRWorkerProtocolError


def send(message:ProtocolMessage):
    sys.stdout.write(encode_message(message)); sys.stdout.flush()


def main(argv=None):
    # JSON Lines is always UTF-8 regardless of the Windows console code page.
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"): stream.reconfigure(encoding="utf-8",errors="replace")
    parser=argparse.ArgumentParser(add_help=False); parser.add_argument("--model-dir",type=Path); parser.add_argument("--fake-mode"); args=parser.parse_args(argv)
    engine=None; initialized=False
    for line in sys.stdin:
        try: message=decode_message(line,allowed_types=INPUT_TYPES)
        except OCRWorkerProtocolError as exc:
            send(ProtocolMessage("error",payload={"error_type":"invalid_request","error_message_safe":str(exc),"retryable":False})); continue
        if message.type=="ping":
            if args.fake_mode=="malformed": sys.stdout.write("not-json\n"); sys.stdout.flush(); continue
            if args.fake_mode=="stderr": print("synthetic diagnostic",file=sys.stderr,flush=True)
            send(ProtocolMessage("pong",message.request_id)); continue
        if message.type=="shutdown": send(ProtocolMessage("shutting_down",message.request_id)); return 0
        if message.type=="initialize":
            if initialized: send(ProtocolMessage("initialized",message.request_id,{"success":True,"already_initialized":True,"duration_ms":0.0,**engine.metadata})); continue
            started=time.perf_counter()
            try:
                if args.fake_mode=="model-missing": raise FileNotFoundError()
                if args.fake_mode=="load-failed": raise RuntimeError()
                engine=FakeEngine(args.fake_mode or "success") if args.fake_mode else ProductionEngine(args.model_dir)
                initialized=True; send(ProtocolMessage("initialized",message.request_id,{"success":True,"already_initialized":False,"duration_ms":round((time.perf_counter()-started)*1000,3),**engine.metadata}))
            except FileNotFoundError: send(ProtocolMessage("initialized",message.request_id,{"success":False,"error_type":"model_missing","error_message_safe":"Required local OCR models are missing.","retryable":False}))
            except (ImportError,ModuleNotFoundError): send(ProtocolMessage("initialized",message.request_id,{"success":False,"error_type":"model_load_failed","error_message_safe":"OCR runtime is not installed in the worker environment.","retryable":False}))
            except Exception: send(ProtocolMessage("initialized",message.request_id,{"success":False,"error_type":"model_load_failed","error_message_safe":"OCR model initialization failed.","retryable":False}))
            continue
        if message.type=="ocr_request":
            if not initialized: send(ProtocolMessage("error",message.request_id,{"error_type":"not_initialized","error_message_safe":"Worker is not initialized.","retryable":False})); continue
            try: send(result_message(process_request(engine,parse_request(message))))
            except OCRWorkerProtocolError as exc: send(ProtocolMessage("error",message.request_id,{"error_type":"invalid_request","error_message_safe":str(exc),"retryable":False}))
            continue
        send(ProtocolMessage("error",message.request_id,{"error_type":"invalid_request","error_message_safe":"Request is not supported.","retryable":False}))
    return 0


if __name__=="__main__":
    multiprocessing.freeze_support(); raise SystemExit(main())
