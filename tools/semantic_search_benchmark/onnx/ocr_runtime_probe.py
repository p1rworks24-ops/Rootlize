"""Run identical local OCR fixtures under the active ONNX Runtime version."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import time
from pathlib import Path

from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    names = ("PP-OCRv6_det_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "PP-OCRv6_rec_small.onnx")
    paths = [args.models / name for name in names]
    started = time.perf_counter()
    engine = RapidOCR(params={"Global.log_level": "warning", "Global.max_side_len": 2000, "Det.engine_type": EngineType.ONNXRUNTIME, "Det.lang_type": LangDet.MULTI, "Det.model_type": ModelType.SMALL, "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_path": str(paths[0]), "Cls.engine_type": EngineType.ONNXRUNTIME, "Cls.model_path": str(paths[1]), "Rec.engine_type": EngineType.ONNXRUNTIME, "Rec.lang_type": LangRec.JAPAN, "Rec.model_type": ModelType.SMALL, "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_path": str(paths[2])})
    result = {"onnxruntime": importlib.metadata.version("onnxruntime"), "rapidocr": importlib.metadata.version("rapidocr"), "load_s": round(time.perf_counter() - started, 4), "fixtures": []}
    for image in args.images:
        started = time.perf_counter()
        raw = engine(image)
        texts = list(getattr(raw, "txts", None) or [])
        scores = [round(float(value), 6) for value in (getattr(raw, "scores", None) or [])]
        result["fixtures"].append({"path": str(image), "text": "\n".join(texts), "confidence": round(sum(scores) / len(scores), 6) if scores else None, "blocks": len(texts), "runtime_s": round(time.perf_counter() - started, 4), "error": None})
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
