# RapidOCR independent PoC

This directory is an isolated technical PoC for local screenshot OCR. It does
not import, modify, or store data in the Capixe application.

## Fixed stack

- Python 3.12
- RapidOCR 3.9.1
- ONNX Runtime 1.27.0 CPU package
- PP-OCRv6 Small detection and recognition models
- PP-OCRv4 Mobile text-direction classifier bundled by RapidOCR

The recognition model supports Japanese and Latin text. All three ONNX files
must exist in `models/` before a run. The runner never downloads models and
does not call a cloud service.

## Setup

From the repository root in PowerShell:

```powershell
python -m venv tools\ocr_poc\.venv
tools\ocr_poc\.venv\Scripts\python.exe -m pip install -r tools\ocr_poc\requirements-ocr-poc.txt
tools\ocr_poc\.venv\Scripts\python.exe tools\ocr_poc\prepare_models.py
```

`prepare_models.py` copies the exact models bundled in the pinned RapidOCR
wheel into the PoC-local `models/` directory and writes SHA-256 checksums. The
environment and models are deliberately ignored by Git.

## One image

```powershell
tools\ocr_poc\.venv\Scripts\python.exe tools\ocr_poc\run_ocr_poc.py --image "D:\screenshots\example.png"
```

## One folder (non-recursive)

```powershell
tools\ocr_poc\.venv\Scripts\python.exe tools\ocr_poc\run_ocr_poc.py --folder "D:\screenshots"
```

Supported file extensions are PNG, JPG/JPEG, WEBP, and BMP. Subfolders are
never scanned.

## Literal keyword checks

```powershell
tools\ocr_poc\.venv\Scripts\python.exe tools\ocr_poc\run_ocr_poc.py --image "D:\screenshots\example.png" --keywords "error,ログイン,404"
```

Matching normalizes Unicode with NFKC, folds case, and collapses whitespace.
It is intentionally literal substring matching; this PoC adds no fuzzy,
semantic, or AI search.

## Output

Each run writes a unique UTF-8 JSON file to `output/`. It contains:

- source/image metadata and timestamps;
- recognized full text and per-block text, confidence, and quadrilateral box;
- keyword match results;
- engine/runtime/model versions and SHA-256 hashes;
- per-image and aggregate timings, confidence, and Python peak allocation.

A broken image is recorded as an error and remaining folder images continue.
The process returns 1 if any image failed, 2 for invalid arguments or engine
initialization failure, and 0 when all selected images succeeded.

## Large image safety

Images above 100 million pixels are rejected before OCR to reduce decompression
bomb and memory-exhaustion risk. `--allow-large-images` exists for controlled
evaluation only. RapidOCR also limits the inference-side longest dimension to
2000 pixels. Original files are never rewritten.

## Tests

Lightweight tests do not initialize OCR:

```powershell
tools\ocr_poc\.venv\Scripts\python.exe -m unittest discover -s tools\ocr_poc\tests -p "test_*.py"
```

The optional integration test runs only when `OCR_POC_INTEGRATION_IMAGE` points
to a real screenshot and the three local model files are present.

## Offline verification

For an offline check, prepare models once, disconnect networking (or deny the
process network access), and run the same command. Initialization fails clearly
when a local model is missing rather than fetching it. Network-dependent image
paths and URLs are not accepted.
