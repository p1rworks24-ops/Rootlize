"""Extract OCR for the existing real-image benchmark corpus."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("results/hybrid_ocr.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    models = Path(__import__("rapidocr").__file__).parent / "models"
    names = ("PP-OCRv6_det_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "PP-OCRv6_rec_small.onnx")
    paths = [models / name for name in names]
    engine = RapidOCR(params={
        "Global.log_level": "warning", "Global.max_side_len": 2000,
        "Det.engine_type": EngineType.ONNXRUNTIME, "Det.lang_type": LangDet.MULTI,
        "Det.model_type": ModelType.SMALL, "Det.ocr_version": OCRVersion.PPOCRV6,
        "Det.model_path": str(paths[0]), "Cls.engine_type": EngineType.ONNXRUNTIME,
        "Cls.model_path": str(paths[1]), "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.lang_type": LangRec.JAPAN, "Rec.model_type": ModelType.SMALL,
        "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_path": str(paths[2]),
    })
    manifest = json.loads((root / "data/manifest.json").read_text(encoding="utf-8"))
    output = {}
    for pos, item in enumerate(manifest, 1):
        # The photo subset is explicitly curated as no-text-expected. Running OCR
        # on it mainly adds incidental signage and does not improve this evaluation.
        if item.get("no_text_expected"):
            output[item["id"]] = {"text": "", "confidence": None, "blocks": 0}
            continue
        result = engine(root / item["path"])
        texts = list(getattr(result, "txts", None) or [])
        scores = [float(value) for value in (getattr(result, "scores", None) or [])]
        output[item["id"]] = {
            "text": "\n".join(texts),
            "confidence": sum(scores) / len(scores) if scores else None,
            "blocks": len(texts),
        }
        print(f"OCR {pos}/{len(manifest)} {item['id']}")
    target = root / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
