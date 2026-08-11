from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.ocr_poc.evaluate_ocr import (
    aggregate,
    cache_key,
    load_manifest,
    markdown_report,
    missing_ocr_result,
    searchable_status,
    write_outputs,
)


def _row(filename="日本語.png", categories=None, expected=None, matched=None, status="success"):
    expected = expected or []
    matched = matched or []
    return {
        "filename": filename, "categories": categories or [], "expected_keywords": expected,
        "matched_keywords": matched, "failed_keywords": [word for word in expected if word not in matched],
        "searchable_status": searchable_status({word: word in matched for word in expected}), "cache_hit": False,
        "ocr": {"status": status, "width": 100, "height": 50, "block_count": 2,
                "duration_ms": 20.0, "average_confidence": 0.9, "full_text": "設定",
                "blocks": [], "error": None if status == "success" else {"message": "bad"}},
    }


class ManifestTests(unittest.TestCase):
    def test_loads_manifest_and_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps({"images": [{"filename": "a.png"}]}), encoding="utf-8")
            item = load_manifest(path)[0]
            self.assertEqual(item["categories"], [])
            self.assertEqual(item["expected_keywords"], [])

    def test_rejects_missing_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text('{"images":[{}]}', encoding="utf-8")
            with self.assertRaises(ValueError): load_manifest(path)


class AggregateTests(unittest.TestCase):
    def test_searchable_classification(self):
        self.assertEqual(searchable_status({"a": True, "b": True}), "Searchable")
        self.assertEqual(searchable_status({"a": True, "b": False}), "Partially Searchable")
        self.assertEqual(searchable_status({"a": False}), "Not Searchable")

    def test_categories_keywords_and_failed_images(self):
        rows = [_row(categories=["Japanese UI", "Light theme"], expected=["設定", "保存"], matched=["設定"]), _row("bad.png", ["Light theme"], ["Login"], [], "error")]
        summary = aggregate(rows, 10, 50)
        self.assertAlmostEqual(summary["keyword_match_rate"], 1 / 3, places=6)
        self.assertEqual(summary["ocr_failure_count"], 1)
        self.assertEqual(summary["categories"]["Light theme"]["image_count"], 2)

    def test_empty_results_do_not_divide_by_zero(self):
        summary = aggregate([], 0, 0)
        self.assertEqual(summary["keyword_match_rate"], 0.0)
        self.assertIsNone(summary["duration_ms"]["average"])

    def test_missing_image_result_is_a_failure(self):
        result = missing_ocr_result()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "FileNotFoundError")

    def test_cache_key_changes_when_model_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "a.png"; image.write_bytes(b"image")
            first = {"engine_version":"3.9.1","models":{"recognition":{"sha256":"aaa"}}}
            second = {"engine_version":"3.9.1","models":{"recognition":{"sha256":"bbb"}}}
            self.assertNotEqual(cache_key(image, first), cache_key(image, second))


class OutputTests(unittest.TestCase):
    def test_json_csv_markdown_and_japanese_csv(self):
        row = _row(categories=["Japanese UI", "Light theme"], expected=["設定"], matched=["設定"])
        summary = aggregate([row], 1, 2)
        payload = {"environment": {"engine_version":"3.9.1","runtime_version":"1.27.0","device":"CPU","python":"3.12","platform":"Windows","cpu":"CPU","logical_cores":8}, "summary": summary, "results": [row]}
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_outputs(payload, Path(tmp))
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertIn("日本語.png", paths["csv"].read_text(encoding="utf-8-sig"))
            self.assertIn("Category Results", paths["markdown"].read_text(encoding="utf-8"))
            self.assertEqual(json.loads(paths["json"].read_text(encoding="utf-8"))["summary"]["image_count"], 1)

    def test_markdown_marks_manual_review(self):
        row = _row(expected=["設定", "保存"], matched=["設定"])
        payload = {"environment": {"engine_version":"3.9.1","runtime_version":"1.27.0","device":"CPU","python":"3.12","platform":"Windows","cpu":"CPU","logical_cores":8}, "summary":aggregate([row],0,0), "results":[row]}
        self.assertIn("Manual Review Required", markdown_report(payload))


if __name__ == "__main__": unittest.main()
