import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("real_benchmark", HERE / "benchmark.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_query_manifest_has_required_queries_and_existing_labels():
    queries = json.loads((HERE / "queries.json").read_text(encoding="utf-8"))
    assert len(queries) >= 20
    names = {item["query"] for item in queries}
    assert {
        "Windows desktop", "Windows desktop screenshot", "desktop with application windows",
        "dog", "a dog", "dog photo", "image search application", "code editor",
        "browser window", "settings screen",
    } <= names
    available = {path.name for path in Path(r"D:\07_Programs\shotlogue_test").iterdir()}
    assert all(item["relevant"] and set(item["relevant"]) <= available for item in queries)


def test_evaluate_reports_cutoffs_and_false_negatives():
    paths = [Path("dog.png"), Path("wrong.png"), Path("other.png")]
    queries = [{"query": "dog", "relevant": ["dog.png", "other.png"]}]
    result = module.evaluate(np.array([[0.1, 0.9, 0.0]]), paths, queries)
    assert result["top_1"] == 0
    assert result["top_3"] == 1
    assert result["queries"][0]["false_positives_top_5"] == ["wrong.png"]
