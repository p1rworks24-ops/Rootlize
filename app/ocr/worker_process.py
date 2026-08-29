"""Worker-side OCR execution. This module is imported only by worker_entry."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import os
import time
from pathlib import Path
from typing import Any

from app.ocr.fingerprint import calculate_quick_fingerprint,calculate_sha256
from app.ocr.worker_protocol import FileSnapshot, OCRBlockResult, OCRWorkerRequest, OCRWorkerResult

MODEL_FILES=("PP-OCRv6_det_small.onnx","ch_ppocr_mobile_v2.0_cls_mobile.onnx","PP-OCRv6_rec_small.onnx")
MAX_OCR_TEXT_CHARS=4_000_000
MAX_OCR_BLOCKS=50_000


def snapshot(path: Path) -> FileSnapshot:
    stat=path.stat()
    return FileSnapshot(stat.st_size,stat.st_mtime_ns,calculate_quick_fingerprint(path))


class ProductionEngine:
    """Local CPU-only RapidOCR adapter with explicit local model paths."""
    def __init__(self, model_dir: Path, max_side: int=2000):
        paths=[model_dir/name for name in MODEL_FILES]
        if not all(path.is_file() for path in paths): raise FileNotFoundError("Required local OCR models are missing.")
        with contextlib.redirect_stdout(os.sys.stderr):
            from rapidocr import EngineType,LangDet,LangRec,ModelType,OCRVersion,RapidOCR
            self.ocr=RapidOCR(params={"Global.log_level":"warning","Global.max_side_len":max_side,"Det.engine_type":EngineType.ONNXRUNTIME,"Det.lang_type":LangDet.MULTI,"Det.model_type":ModelType.SMALL,"Det.ocr_version":OCRVersion.PPOCRV6,"Det.model_path":str(paths[0]),"Cls.engine_type":EngineType.ONNXRUNTIME,"Cls.model_path":str(paths[1]),"Rec.engine_type":EngineType.ONNXRUNTIME,"Rec.lang_type":LangRec.JAPAN,"Rec.model_type":ModelType.SMALL,"Rec.ocr_version":OCRVersion.PPOCRV6,"Rec.model_path":str(paths[2])})
        digest=hashlib.sha256()
        for path in paths: digest.update(calculate_sha256(path).encode("ascii"))
        self.metadata={"engine_name":"RapidOCR","engine_version":importlib.metadata.version("rapidocr"),"model_name":"PP-OCRv6 Small Japanese","model_sha256":digest.hexdigest()}

    def process(self,path:Path,_options:dict[str,Any]):
        with contextlib.redirect_stdout(os.sys.stderr): raw=self.ocr(path)
        boxes=getattr(raw,"boxes",None); texts=getattr(raw,"txts",None); scores=getattr(raw,"scores",None)
        if boxes is None or texts is None or scores is None: return "",(),None
        blocks=tuple(OCRBlockResult(str(text),round(float(score),6),tuple((round(float(x),3),round(float(y),3)) for x,y in box)) for box,text,score in zip(boxes,texts,scores))
        confidence=round(sum(block.confidence for block in blocks)/len(blocks),6) if blocks else None
        return "\n".join(block.text for block in blocks),blocks,confidence


class FakeEngine:
    def __init__(self, mode:str): self.mode=mode; self.metadata={"engine_name":"FakeOCR","engine_version":"1","model_name":"fake","model_sha256":"fake-sha"}
    def process(self,path:Path,options:dict[str,Any]):
        delay=float(options.get("delay_seconds",0)); time.sleep(delay)
        if self.mode=="crash" or options.get("crash"): os._exit(91)
        if self.mode=="error" or options.get("fail"): raise RuntimeError("Synthetic OCR failure")
        if options.get("mutate_after"): path.write_bytes(path.read_bytes()+b"changed")
        text=str(options.get("text","日本語\nEnglish")); block=OCRBlockResult(text,0.95,((0.0,0.0),(1.0,1.0)))
        return text,(block,),0.95


def process_request(engine:Any, request:OCRWorkerRequest, *, max_pixels:int=100_000_000) -> OCRWorkerResult:
    started=time.perf_counter(); path=Path(request.path)
    base=dict(request_id=request.request_id,path=request.path,pipeline_version=1)
    if "://" in request.path: return OCRWorkerResult(**base,success=False,error_type="invalid_request",error_message_safe="Only local filesystem paths are supported.",retryable=False)
    try: before=snapshot(path)
    except FileNotFoundError: return OCRWorkerResult(**base,success=False,error_type="file_missing",error_message_safe="The image is no longer available.",retryable=True)
    except OSError: return OCRWorkerResult(**base,success=False,error_type="image_decode_failed",error_message_safe="The image could not be read.",retryable=True)
    if (before.size_bytes,before.mtime_ns,before.quick_fingerprint)!=(request.expected_size_bytes,request.expected_mtime_ns,request.expected_quick_fingerprint):
        return OCRWorkerResult(**base,success=False,file_before=before,file_changed_before_processing=True,error_type="file_changed_before_processing",error_message_safe="The image changed before OCR started.",retryable=True)
    try:
        # Decode by file contents, not the suffix. Managed files can be normal
        # JPEGs or can have been renamed independently of their encoded format.
        from app.ocr.scanner import _image_dimensions
        width,height=_image_dimensions(path)
        if width*height>max_pixels: return OCRWorkerResult(**base,success=False,file_before=before,error_type="image_too_large",error_message_safe="The image exceeds the safe pixel limit.",retryable=False)
        full_text,blocks,confidence=engine.process(path,request.options)
        if len(full_text)>MAX_OCR_TEXT_CHARS or len(blocks)>MAX_OCR_BLOCKS:
            return OCRWorkerResult(**base,success=False,file_before=before,error_type="ocr_failed",error_message_safe="OCR result exceeds the safe IPC size limit.",retryable=False)
    except (OSError, ValueError, SyntaxError):
        return OCRWorkerResult(**base,success=False,file_before=before,error_type="image_decode_failed",error_message_safe="The image is invalid or unsupported.",retryable=False)
    except Exception:
        return OCRWorkerResult(**base,success=False,file_before=before,error_type="ocr_failed",error_message_safe="OCR processing failed.",retryable=True)
    try: after=snapshot(path); changed=before!=after
    except (FileNotFoundError,OSError):
        after=None; changed=True
    meta=engine.metadata
    return OCRWorkerResult(**base,success=True,file_before=before,file_after=after,file_changed_during_processing=changed,full_text=full_text,blocks=blocks,average_confidence=confidence,duration_ms=round((time.perf_counter()-started)*1000,3),error_type="file_changed_during_processing" if changed else None,error_message_safe="The image changed during OCR; do not save this result." if changed else None,retryable=changed,**meta)
