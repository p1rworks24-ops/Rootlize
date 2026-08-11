"""Versioned UTF-8 JSON Lines protocol for the local OCR child process."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.ocr.worker_exceptions import OCRWorkerProtocolError

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
INPUT_TYPES = frozenset({"initialize","ocr_request","ping","shutdown"})
OUTPUT_TYPES = frozenset({"initialized","ocr_result","pong","error","shutting_down"})


@dataclass(frozen=True)
class FileSnapshot:
    size_bytes: int
    mtime_ns: int
    quick_fingerprint: str


@dataclass(frozen=True)
class OCRBlockResult:
    text: str
    confidence: float
    box: tuple[tuple[float,float], ...] = ()


@dataclass(frozen=True)
class OCRWorkerRequest:
    request_id: str
    path: str
    expected_size_bytes: int
    expected_mtime_ns: int
    expected_quick_fingerprint: str
    options: dict[str,Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OCRWorkerResult:
    request_id: str
    success: bool
    path: str
    file_before: FileSnapshot | None = None
    file_after: FileSnapshot | None = None
    file_changed_before_processing: bool = False
    file_changed_during_processing: bool = False
    full_text: str = ""
    blocks: tuple[OCRBlockResult,...] = ()
    average_confidence: float | None = None
    duration_ms: float = 0.0
    engine_name: str | None = None
    engine_version: str | None = None
    model_name: str | None = None
    model_sha256: str | None = None
    pipeline_version: int = 1
    error_type: str | None = None
    error_message_safe: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ProtocolMessage:
    type: str
    request_id: str | None = None
    payload: dict[str,Any] = field(default_factory=dict)


def encode_message(message: ProtocolMessage) -> str:
    data={"protocol_version":PROTOCOL_VERSION,"type":message.type,**message.payload}
    if message.request_id is not None: data["request_id"]=message.request_id
    encoded=json.dumps(data,ensure_ascii=False,separators=(",",":"))
    if len(encoded.encode("utf-8"))>MAX_MESSAGE_BYTES: raise OCRWorkerProtocolError("IPC message exceeds size limit.")
    return encoded+"\n"


def decode_message(line: str, *, allowed_types: frozenset[str]) -> ProtocolMessage:
    if len(line.encode("utf-8"))>MAX_MESSAGE_BYTES: raise OCRWorkerProtocolError("IPC message exceeds size limit.")
    try: data=json.loads(line)
    except (json.JSONDecodeError,UnicodeError) as exc: raise OCRWorkerProtocolError("Invalid JSON message.") from exc
    if not isinstance(data,dict): raise OCRWorkerProtocolError("IPC message must be an object.")
    if data.get("protocol_version")!=PROTOCOL_VERSION: raise OCRWorkerProtocolError("Unsupported protocol version.")
    kind=data.get("type")
    if kind not in allowed_types: raise OCRWorkerProtocolError("Unknown IPC message type.")
    request_id=data.get("request_id")
    payload={key:value for key,value in data.items() if key not in {"protocol_version","type","request_id"}}
    return ProtocolMessage(kind,request_id,payload)


def request_message(request: OCRWorkerRequest) -> ProtocolMessage:
    values=asdict(request); request_id=values.pop("request_id")
    return ProtocolMessage("ocr_request",request_id,values)


def result_message(result: OCRWorkerResult) -> ProtocolMessage:
    values=asdict(result); request_id=values.pop("request_id")
    return ProtocolMessage("ocr_result",request_id,values)


def parse_request(message: ProtocolMessage) -> OCRWorkerRequest:
    if message.type!="ocr_request" or not message.request_id: raise OCRWorkerProtocolError("Invalid OCR request.")
    try: return OCRWorkerRequest(request_id=message.request_id,**message.payload)
    except (TypeError,ValueError) as exc: raise OCRWorkerProtocolError("Invalid OCR request fields.") from exc


def parse_result(message: ProtocolMessage) -> OCRWorkerResult:
    if message.type!="ocr_result" or not message.request_id: raise OCRWorkerProtocolError("Invalid OCR result.")
    try:
        values=dict(message.payload)
        for key in ("file_before","file_after"):
            if values.get(key) is not None: values[key]=FileSnapshot(**values[key])
        values["blocks"]=tuple(OCRBlockResult(text=b["text"],confidence=b["confidence"],box=tuple(tuple(p) for p in b.get("box",()))) for b in values.get("blocks",[]))
        return OCRWorkerResult(request_id=message.request_id,**values)
    except (TypeError,ValueError,KeyError) as exc: raise OCRWorkerProtocolError("Invalid OCR result fields.") from exc
