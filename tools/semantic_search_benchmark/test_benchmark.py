from pathlib import Path

import numpy as np

from semantic_benchmark.dataset import _synthetic_screen
from semantic_benchmark.metrics import evaluate
from semantic_benchmark.queries import build_queries


def test_synthetic_metadata_and_queries(tmp_path: Path):
    path = tmp_path / "comparison.png"
    metadata = _synthetic_screen(path, "comparison_page", 0)
    records = [{"id": "synthetic-000", "path": str(path), "source": "test", "kind": "screenshot", "level": 5, "labels": metadata["expected_concepts"], "captions": metadata["action"], "metadata": metadata, "no_text_expected": False}]
    queries = build_queries(records)
    assert path.exists()
    assert any(item["language"] == "ja" and item["level"] == 5 for item in queries)


def test_top_k_uses_multiple_relevant_images():
    records = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    queries = [{"id": "q", "language": "ja", "text": "犬", "level": 1, "challenge": False, "relevant": ["b", "c"]}]
    images = np.array([[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]], dtype=np.float32)
    texts = np.array([[0.0, 1.0]], dtype=np.float32)
    summary, rows = evaluate(images, texts, records, queries)
    assert rows[0]["top_1"] == 1.0
    assert summary["required"]["top_3"] == 1.0
