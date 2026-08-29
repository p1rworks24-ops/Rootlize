from __future__ import annotations

import json
import os
import struct
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from app.ocr.fingerprint import calculate_quick_fingerprint
from app.ocr.worker_client import OCRWorkerClient,OCRWorkerConfig,OCRWorkerTimeouts
from app.ocr.worker_exceptions import OCRWorkerBusyError,OCRWorkerCrashedError,OCRWorkerInitializationError,OCRWorkerNotRunningError,OCRWorkerProtocolError,OCRWorkerTimeoutError
from app.ocr.worker_process import FakeEngine,process_request
from app.ocr.worker_protocol import INPUT_TYPES,MAX_MESSAGE_BYTES,OUTPUT_TYPES,FileSnapshot,OCRBlockResult,OCRWorkerRequest,OCRWorkerResult,ProtocolMessage,decode_message,encode_message,parse_request,parse_result,request_message,result_message


def write_png(path:Path,payload=b"data",width=10,height=20):
    path.write_bytes(b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\x0dIHDR"+struct.pack(">II",width,height)+payload); return path


def make_request(path:Path,**options):
    stat=path.stat(); return OCRWorkerRequest(uuid.uuid4().hex,str(path),stat.st_size,stat.st_mtime_ns,calculate_quick_fingerprint(path),options)


def client(mode="success",**timeouts):
    values=dict(start=3,initialize=3,ping=1,ocr=2,shutdown=1); values.update(timeouts)
    return OCRWorkerClient(OCRWorkerConfig(fake_mode=mode,timeouts=OCRWorkerTimeouts(**values)))


def test_request_round_trip_and_japanese_path():
    request=OCRWorkerRequest("id","D:\\画像.png",1,2,"qf1:value",{"text":"日本語\nEnglish"})
    decoded=decode_message(encode_message(request_message(request)),allowed_types=INPUT_TYPES)
    assert parse_request(decoded)==request


def test_result_round_trip_preserves_newlines_blocks_and_snapshots():
    snapshot=FileSnapshot(1,2,"qf1:x"); block=OCRBlockResult("日本語\nEnglish",.9,((1.0,2.0),))
    result=OCRWorkerResult("id",True,"D:\\a.png",snapshot,snapshot,full_text=block.text,blocks=(block,))
    decoded=parse_result(decode_message(encode_message(result_message(result)),allowed_types=OUTPUT_TYPES))
    assert decoded==result


@pytest.mark.parametrize("line", ["not-json\n",json.dumps({"protocol_version":999,"type":"ping"}),json.dumps({"protocol_version":1,"type":"unknown"})])
def test_protocol_rejects_invalid_version_type_or_json(line):
    with pytest.raises(OCRWorkerProtocolError): decode_message(line,allowed_types=INPUT_TYPES)


def test_protocol_rejects_oversized_message():
    with pytest.raises(OCRWorkerProtocolError): encode_message(ProtocolMessage("ping",payload={"value":"x"*MAX_MESSAGE_BYTES}))


def test_client_lifecycle_double_start_ping_shutdown_and_ended_send():
    worker=client(); worker.start(); pid=worker.process.pid; worker.start()
    assert worker.process.pid==pid and worker.is_running(); assert worker.initialize()["success"]; assert worker.ping()
    worker.shutdown(); assert not worker.is_running() and worker.process is None
    with pytest.raises(OCRWorkerNotRunningError): worker.ping()


def test_initialize_is_idempotent_and_engine_is_not_reloaded():
    worker=client(); worker.start()
    try:
        first=worker.initialize(); second=worker.initialize()
        assert not first["already_initialized"] and second["already_initialized"]
    finally: worker.shutdown()


@pytest.mark.parametrize("mode,error", [("model-missing","model_missing"),("load-failed","model_load_failed")])
def test_initialization_failure_is_typed(mode,error):
    worker=client(mode); worker.start()
    try:
        with pytest.raises(OCRWorkerInitializationError) as captured: worker.initialize()
        assert error.replace("_"," ") in str(captured.value).lower() or captured.value
        assert worker.state=="broken"
    finally: worker.terminate()


def test_submit_success_with_japanese_and_newline(tmp_path):
    path=write_png(tmp_path/"画像.png"); worker=client(); worker.start(); worker.initialize()
    try:
        result=worker.submit_ocr(make_request(path,text="日本語\nEnglish"))
        assert result.success and result.full_text=="日本語\nEnglish" and result.average_confidence==.95
        assert not result.file_changed_during_processing
    finally: worker.shutdown()


def test_submit_error_does_not_kill_worker(tmp_path):
    path=write_png(tmp_path/"a.png"); worker=client("error"); worker.start(); worker.initialize()
    try:
        result=worker.submit_ocr(make_request(path)); assert not result.success and result.error_type=="ocr_failed"
        assert worker.ping()
    finally: worker.shutdown()


def test_before_mismatch_does_not_run_ocr(tmp_path):
    path=write_png(tmp_path/"a.png"); request=replace(make_request(path),expected_size_bytes=999)
    result=process_request(FakeEngine("crash"),request)
    assert result.error_type=="file_changed_before_processing" and result.retryable


def test_missing_before_processing(tmp_path):
    path=write_png(tmp_path/"a.png"); request=make_request(path); path.unlink()
    result=process_request(FakeEngine("success"),request)
    assert result.error_type=="file_missing" and result.retryable


def test_normal_jpeg_is_accepted(tmp_path):
    from PIL import Image
    path=tmp_path/"a.jpg"; Image.new("RGB",(10,20),"white").save(path,"JPEG")
    result=process_request(FakeEngine("success"),make_request(path))
    assert result.success


def test_fingerprint_mismatch_is_detected(tmp_path):
    path=write_png(tmp_path/"a.png"); request=replace(make_request(path),expected_quick_fingerprint="qf1:wrong")
    assert process_request(FakeEngine("success"),request).file_changed_before_processing


def test_changed_during_processing_returns_but_marks_unsafe(tmp_path):
    path=write_png(tmp_path/"a.png"); result=process_request(FakeEngine("success"),make_request(path,mutate_after=True))
    assert result.success and result.file_changed_during_processing and result.retryable
    assert result.error_type=="file_changed_during_processing"


def test_file_deleted_during_processing_is_marked_changed(tmp_path):
    path=write_png(tmp_path/"a.png"); engine=FakeEngine("success")
    original=engine.process
    def remove(p,o): value=original(p,o); p.unlink(); return value
    engine.process=remove
    result=process_request(engine,make_request(path)); assert result.file_changed_during_processing and result.file_after is None


def test_timeout_terminates_worker_and_allows_restart(tmp_path):
    path=write_png(tmp_path/"a.png"); worker=client(ocr=.05); worker.start(); worker.initialize()
    with pytest.raises(OCRWorkerTimeoutError): worker.submit_ocr(make_request(path,delay_seconds=.5))
    assert worker.state=="broken" and worker.process is None
    worker.restart(); assert worker.ping(); worker.shutdown()


def test_worker_crash_detected_and_restartable(tmp_path):
    path=write_png(tmp_path/"a.png"); worker=client("crash"); worker.start(); worker.initialize()
    with pytest.raises(OCRWorkerCrashedError): worker.submit_ocr(make_request(path))
    worker.config=replace(worker.config,fake_mode="success"); worker.restart(); assert worker.ping(); worker.shutdown()


def test_malformed_stdout_marks_protocol_broken():
    worker=client("malformed"); worker.start(); worker.initialize()
    try:
        with pytest.raises(OCRWorkerProtocolError): worker.ping()
        assert worker.state=="broken"
    finally: worker.terminate()


def test_stderr_is_bounded_and_available():
    worker=client("stderr"); worker.start(); worker.initialize()
    try:
        for _ in range(5): worker.ping()
        time.sleep(.05); assert "synthetic diagnostic" in worker.stderr_tail
        assert len(worker._stderr)<=worker.config.stderr_lines
    finally: worker.shutdown()


def test_concurrent_submit_is_rejected(tmp_path):
    path=write_png(tmp_path/"a.png"); worker=client(); worker.start(); worker.initialize(); errors=[]
    thread=threading.Thread(target=lambda: worker.submit_ocr(make_request(path,delay_seconds=.3))); thread.start(); time.sleep(.05)
    try:
        with pytest.raises(OCRWorkerBusyError): worker.submit_ocr(make_request(path))
    finally: thread.join(); worker.shutdown()


def test_terminate_leaves_no_live_child():
    worker=client(); worker.start(); process=worker.process; worker.terminate()
    assert process.poll() is not None and worker.process is None


def test_real_rapidocr_worker_when_explicitly_configured():
    image_value=os.environ.get("OCR_WORKER_INTEGRATION_IMAGE")
    model_value=os.environ.get("OCR_WORKER_MODEL_DIR")
    worker_python=os.environ.get("OCR_WORKER_PYTHON")
    if not image_value or not model_value:
        pytest.skip("Set OCR_WORKER_INTEGRATION_IMAGE and OCR_WORKER_MODEL_DIR for the real worker test.")
    command=(worker_python,"-m","app.ocr.worker_entry") if worker_python else None
    path=Path(image_value); worker=OCRWorkerClient(OCRWorkerConfig(model_dir=Path(model_value),command=command,timeouts=OCRWorkerTimeouts(initialize=60,ocr=120)))
    worker.start()
    try:
        pid=worker.process.pid; initialized=worker.initialize(); repeated=worker.initialize()
        first_request=make_request(path); second_request=make_request(path)
        first=worker.submit_ocr(first_request); second=worker.submit_ocr(second_request)
        mismatch=replace(make_request(path),expected_mtime_ns=path.stat().st_mtime_ns+1)
        changed=worker.submit_ocr(mismatch)
        assert initialized["success"] and repeated["already_initialized"]
        assert first.success and second.success and first.full_text and second.full_text
        assert first.blocks and second.blocks and 0 <= first.average_confidence <= 1
        assert first.file_before==first.file_after and second.file_before==second.file_after
        assert not first.file_changed_during_processing and not second.file_changed_during_processing
        assert first.request_id==first_request.request_id and second.request_id==second_request.request_id
        assert worker.process.pid==pid and worker.is_running()
        assert changed.error_type=="file_changed_before_processing" and changed.retryable
    finally: worker.shutdown()
