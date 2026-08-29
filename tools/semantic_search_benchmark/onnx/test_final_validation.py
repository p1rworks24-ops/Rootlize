import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def validation():
    return json.loads((RESULTS / "siglip2_runtime_final_validation.json").read_text(encoding="utf-8"))


def test_torch_transformers_free_offline_runtime():
    result = validation()
    assert result["imports"] == {"torch": False, "transformers": False, "runtime_dependencies": ["onnxruntime", "numpy", "Pillow", "tokenizers"]}
    assert result["offline"] == {"environment_flags": True, "worker_completed": True, "network_required": False}


def test_tokenizer_and_preprocessing_parity():
    parity = validation()["parity_accuracy"]
    assert parity["tokenizer_ids_equal"] is True
    assert parity["tokenizer_max_abs_diff"] == 0
    assert parity["preprocessing_max_abs_diff"] < 2e-7


def test_accuracy_matches_fp32_baseline():
    metrics = validation()["parity_accuracy"]["metrics"]
    assert metrics["language_ja"]["top_3"] == 0.5357
    assert metrics["language_en"]["top_3"] == 0.7143
    assert metrics["screenshots"]["top_3"] == 0.8333
    assert metrics["no_text_photos"]["top_3"] == 0.5


def test_batch_output_consistency():
    batches = [np.load(RESULTS / f"runtime_embeddings_b{batch}_t4.npz") for batch in (1, 4, 8)]
    for candidate in batches[1:]:
        assert np.allclose(batches[0]["images"], candidate["images"], atol=2e-6)
        assert np.allclose(batches[0]["texts"], candidate["texts"], atol=2e-6)


def test_worker_startup_and_shutdown_records_distinct_processes():
    workers = validation()["workers"][:3]
    assert len({row["pid"] for row in workers}) == 3
    assert all(row["load_s"] > 0 and row["wall_s"] > row["load_s"] for row in workers)


def test_ocr_128_regression_matches_127():
    old = json.loads((RESULTS / "ocr_127.json").read_text(encoding="utf-8"))
    new = json.loads((RESULTS / "ocr_128.json").read_text(encoding="utf-8"))
    assert old["onnxruntime"] == "1.27.0"
    assert new["onnxruntime"] == "1.28.0"
    assert len(old["fixtures"]) == len(new["fixtures"]) == 3
    for before, after in zip(old["fixtures"], new["fixtures"]):
        assert before["text"] == after["text"]
        assert before["confidence"] == after["confidence"]
        assert before["blocks"] == after["blocks"]
        assert after["error"] is None
