from __future__ import annotations

import os
import unittest
from pathlib import Path

from tools.ocr_poc.ocr_engine import MODEL_FILES, RapidOCREngine


class RealOCRIntegrationTest(unittest.TestCase):
    def test_real_screenshot_when_explicitly_configured(self) -> None:
        value = os.environ.get("OCR_POC_INTEGRATION_IMAGE")
        if not value:
            self.skipTest("Set OCR_POC_INTEGRATION_IMAGE to a real screenshot.")
        image = Path(value)
        model_dir = Path(__file__).resolve().parents[1] / "models"
        if not image.is_file() or any(not (model_dir / name).is_file() for name in MODEL_FILES.values()):
            self.skipTest("Integration image or local models are unavailable.")
        result = RapidOCREngine(model_dir).process(image)
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertIsInstance(result["full_text"], str)


if __name__ == "__main__":
    unittest.main()
