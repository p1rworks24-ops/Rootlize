# Real OCR worker verification

The regular test suite uses the JSON Lines fake worker and does not load OCR models.
To run the explicit local RapidOCR worker test, set these environment variables:

- `OCR_WORKER_INTEGRATION_IMAGE`: absolute path to a non-sensitive PNG test image
- `OCR_WORKER_MODEL_DIR`: directory containing the three PP-OCRv6 Small ONNX files
- `OCR_WORKER_PYTHON`: optional Python executable containing RapidOCR and ONNX Runtime

Then run:

```powershell
python -m pytest test_ocr_worker.py::test_real_rapidocr_worker_when_explicitly_configured -q
```

The worker is offline-only. It never downloads models and never writes OCR results to SQLite.
Do not commit model files, evaluation images, OCR text, or local absolute paths.
