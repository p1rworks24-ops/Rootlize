from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from tools.ocr_poc.ocr_engine import RapidOCREngine
from tools.ocr_poc.run_ocr_poc import (
    build_parser,
    collect_images,
    performance_summary,
    save_json,
    unique_output_path,
)
from tools.ocr_poc.text_normalization import (
    match_keywords,
    normalize_search_text,
    parse_keywords,
)


class ArgumentTests(unittest.TestCase):
    def test_requires_exactly_one_source(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--image", "a.png", "--folder", "folder"])


class CollectionTests(unittest.TestCase):
    def test_folder_is_non_recursive_and_filters_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("日本語.PNG", "b.jpg", "c.WEBP", "ignore.txt"):
                (root / name).write_bytes(b"x")
            nested = root / "nested"
            nested.mkdir()
            (nested / "hidden.png").write_bytes(b"x")
            self.assertEqual(
                [path.name for path in collect_images(None, root)],
                ["b.jpg", "c.WEBP", "日本語.PNG"],
            )


class NormalizationTests(unittest.TestCase):
    def test_nfkc_case_and_whitespace(self) -> None:
        self.assertEqual(normalize_search_text(" ＥＲＲＯＲ\n  ４０４ "), "error 404")

    def test_keywords_are_deduplicated_after_normalization(self) -> None:
        self.assertEqual(parse_keywords("Error, error, ログイン, "), ["Error", "ログイン"])

    def test_literal_matches_support_japanese(self) -> None:
        self.assertEqual(
            match_keywords("ログイン ERROR ４０４", ["ログイン", "error", "404", "timeout"]),
            {"ログイン": True, "error": True, "404": True, "timeout": False},
        )


class OutputTests(unittest.TestCase):
    def test_unique_output_path_avoids_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixed = datetime(2026, 8, 3, 12, 0, 0, 123456)
            first = unique_output_path(root, fixed)
            first.write_text("existing", encoding="utf-8")
            second = unique_output_path(root, fixed)
            self.assertNotEqual(first, second)

    def test_json_is_utf8_and_preserves_japanese(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = save_json({"text": "日本語"}, Path(temporary))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"text": "日本語"})
            self.assertIn("日本語", path.read_text(encoding="utf-8"))

    def test_performance_ignores_failed_items(self) -> None:
        summary = performance_summary(
            [
                {"status": "success", "duration_ms": 10.0, "average_confidence": 0.8},
                {"status": "success", "duration_ms": 30.0, "average_confidence": None},
                {"status": "error", "duration_ms": 2.0, "average_confidence": None},
            ]
        )
        self.assertEqual(summary["successful_images"], 2)
        self.assertEqual(summary["failed_images"], 1)
        self.assertEqual(summary["duration_ms"]["average"], 20.0)


class ErrorIsolationTests(unittest.TestCase):
    def test_engine_records_per_file_failure(self) -> None:
        engine = RapidOCREngine.__new__(RapidOCREngine)
        engine._read_image_metadata = Mock(side_effect=OSError("broken image"))
        result = engine.process(Path("broken.png"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["type"], "OSError")
        self.assertIn("broken image", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
