"""Contract tests for identity-bound surface matching against frozen v8 facts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.meaning_eval.db_sot_poc import enforce_condition_consistency
from tools.meaning_eval.db_sot_surface_v8_identity import apply_surface_contract, ensure_bound_conditions
from tools.meaning_eval.db_sot_surface_new_holdout_poc import IMAGES as NEW_HOLDOUT_IMAGES

ROOT = Path(__file__).resolve().parents[2]
NEW_FACTS = ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-surface-v8-new-holdout10" / "facts.json"
DEV_FACTS = ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-surface-v8-dev24" / "facts.json"
DEV_SEARCH = ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-surface-v8-dev24" / "search.jsonl"


def _load_named_facts(path: Path, names: list[str]) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {name: payload["records"][index] for index, name in enumerate(names)}


def _dev_names() -> list[str]:
    first = json.loads(DEV_SEARCH.read_text(encoding="utf-8").splitlines()[0])
    return [item["name"] for item in first["judgements"]]


def _decide(query: str, record: dict, conditions: list[dict]) -> dict:
    item = {"independent_conditions": [dict(row) for row in conditions], "reason": ""}
    ensure_bound_conditions(item, query=query)
    apply_surface_contract(item, query=query, record=record)
    return enforce_condition_consistency(item, query=query, record=record)


class IdentitySurfaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.new = _load_named_facts(NEW_FACTS, [item["name"] for item in NEW_HOLDOUT_IMAGES])
        cls.dev = _load_named_facts(DEV_FACTS, _dev_names())

    def test_tags_panel_rejects_images_tag_controls(self):
        result = _decide(
            "Tags panel open",
            self.new["20260718_202750.png"],
            [
                {"condition": "tags panel", "confirmed": True, "evidence": "entities: tags panel"},
                {"condition": "open", "confirmed": True, "evidence": "window open"},
            ],
        )
        self.assertFalse(result["relevant"])

    def test_tags_panel_rejects_home_text_and_statistics(self):
        result = _decide(
            "Tags panel open",
            self.new["20260721_203931.png"],
            [
                {"condition": "Tags panel", "confirmed": True, "evidence": "notable_text: Tags; Statistics panel"},
                {"condition": "open", "confirmed": True, "evidence": "home screen open"},
            ],
        )
        self.assertFalse(result["relevant"])

    def test_tags_panel_does_not_flip_home_false_to_true(self):
        result = _decide(
            "Tags panel open",
            self.new["20260721_204338.png"],
            [
                {"condition": "Tags panel", "confirmed": False, "evidence": "", "reason": "Tags panel is not present"},
                {"condition": "open", "confirmed": True, "evidence": "Capixe is open"},
            ],
        )
        self.assertFalse(result["relevant"])
        tags = next(row for row in result["independent_conditions"] if "tag" in row["condition"].lower())
        self.assertFalse(tags["confirmed"])

    def test_tags_panel_accepts_tags_page(self):
        result = _decide(
            "Tags panel open",
            self.new["20260721_204004.png"],
            [
                {"condition": "Tags panel", "confirmed": False, "evidence": "notable_text: Tags"},
                {"condition": "open", "confirmed": True, "evidence": "Tags page"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_preview_panel_still_matches_real_pane(self):
        result = _decide(
            "Preview panel",
            self.new["20260718_202750.png"],
            [{"condition": "preview panel", "confirmed": True, "evidence": "preview pane"}],
        )
        self.assertTrue(result["relevant"])

    def test_home_panel_still_matches_home_screen(self):
        result = _decide(
            "Home panel open",
            self.new["20260721_204338.png"],
            [
                {"condition": "Home panel", "confirmed": True, "evidence": "home screen"},
                {"condition": "open", "confirmed": True, "evidence": "open"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_chrome_text_mention_rejects_open_window(self):
        result = _decide(
            "Chrome text mention",
            self.new["20260720_233733.png"],
            [
                {"condition": "Chrome", "confirmed": True, "evidence": "Google Chrome window"},
                {"condition": "text mention", "confirmed": True, "evidence": "notable_text ChatGPT"},
            ],
        )
        self.assertFalse(result["relevant"])

    def test_chrome_text_mention_accepts_hash_tag(self):
        result = _decide(
            "Chrome text mention",
            self.new["20260721_204004.png"],
            [
                {"condition": "Chrome", "confirmed": True, "evidence": "tag chip #Chrome"},
                {"condition": "text mention", "confirmed": True, "evidence": "#Chrome"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_chrome_icon_does_not_match_open_window(self):
        result = _decide(
            "Chrome icon",
            self.new["20260720_233733.png"],
            [{"condition": "Chrome icon", "confirmed": True, "evidence": "Google Chrome window plus taskbar icons"}],
        )
        self.assertFalse(result["relevant"])

    def test_splash_is_not_screenshot_manager_ui(self):
        result = _decide(
            "screenshot manager",
            self.new["20260720_220408.png"],
            [
                {
                    "condition": "screenshot manager",
                    "confirmed": True,
                    "evidence": "applications: Capixe [screenshot manager] branding/splash",
                }
            ],
        )
        self.assertFalse(result["relevant"])

    def test_real_screenshot_manager_ui_still_matches(self):
        result = _decide(
            "screenshot manager",
            self.new["20260721_203931.png"],
            [{"condition": "screenshot manager", "confirmed": True, "evidence": "Capixe home screen"}],
        )
        self.assertTrue(result["relevant"])

    def test_ask_ai_button_is_not_ask_ai_open(self):
        result = _decide(
            "screenshot manager with Ask AI open",
            self.dev["20260815_221055.png"],
            [
                {"condition": "screenshot manager", "confirmed": True, "evidence": "ui_types screenshot manager"},
                {"condition": "Ask AI open", "confirmed": True, "evidence": "notable_text: Ask AI"},
                {"condition": "open", "confirmed": True, "evidence": "Capixe open"},
            ],
        )
        self.assertFalse(result["relevant"])

    def test_ask_ai_side_panel_still_matches(self):
        result = _decide(
            "screenshot manager with Ask AI open",
            self.dev["20260818_000310_001.png"],
            [
                {"condition": "screenshot manager", "confirmed": True, "evidence": "ui_types screenshot manager"},
                {"condition": "Ask AI open", "confirmed": True, "evidence": "Ask AI side panel"},
                {"condition": "open", "confirmed": True, "evidence": "Capixe open"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_windows_desktop_is_not_branding(self):
        rec = self.dev["20260718_204024.png"]
        result = _decide(
            "Windows desktop",
            rec,
            [
                {
                    "condition": "Windows desktop",
                    "confirmed": True,
                    "evidence": "environment: Windows desktop environment; taskbar visible",
                }
            ],
        )
        self.assertTrue(result["relevant"])

    def test_dark_code_editor_keeps_rendered_editor(self):
        rec = self.dev["20260718_210026.png"]
        result = _decide(
            "dark code editor",
            rec,
            [
                {
                    "condition": "dark code editor",
                    "confirmed": True,
                    "evidence": "Cursor IDE dark-themed code editor window",
                }
            ],
        )
        self.assertTrue(result["relevant"])
        result = _decide(
            "file explorer window",
            self.dev["20260818_000310_001.png"],
            [
                {
                    "condition": "file explorer window",
                    "confirmed": True,
                    "evidence": "file explorer window thumbnail nested",
                }
            ],
        )
        self.assertTrue(result["relevant"])

    def test_omitted_preview_panel_does_not_match(self):
        result = _decide(
            "screenshot manager with a preview panel",
            self.dev["20260818_000310_001.png"],
            [{"condition": "screenshot manager", "confirmed": True, "evidence": "ui_types screenshot manager"}],
        )
        self.assertFalse(result["relevant"])
        result = _decide(
            "ChatGPT in a browser",
            self.new["20260718_202750.png"],
            [
                {"condition": "ChatGPT", "confirmed": False, "evidence": ""},
                {"condition": "browser", "confirmed": True, "evidence": "Chrome browser"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_web_page_is_not_a_workspace_query(self):
        result = _decide(
            "web page",
            self.new["20260718_203006.png"],
            [{"condition": "web page", "confirmed": True, "evidence": "ChatGPT page in Chrome"}],
        )
        self.assertTrue(result["relevant"])

    def test_chatgpt_in_a_browser_keeps_relation_glue(self):
        result = _decide(
            "ChatGPT in a browser",
            self.new["20260718_203006.png"],
            [
                {"condition": "ChatGPT", "confirmed": True, "evidence": "ChatGPT page"},
                {"condition": "browser", "confirmed": True, "evidence": "Google Chrome"},
                {"condition": "in a browser", "confirmed": True, "evidence": "displayed inside Google Chrome"},
            ],
        )
        self.assertTrue(result["relevant"])

    def test_google_chrome_does_not_match_window_chrome_or_tag_chip(self):
        result = _decide(
            "Google Chrome",
            self.new["20260721_204004.png"],
            [{"condition": "Google Chrome", "confirmed": False, "evidence": ""}],
        )
        self.assertFalse(result["relevant"])
        result = _decide(
            "Google Chrome",
            self.new["20260718_212516.png"],
            [
                {
                    "condition": "Google Chrome",
                    "confirmed": True,
                    "evidence": "scene Google Chrome open",
                    "contract_override": "",
                }
            ],
        )
        apply_surface_contract(result, query="Google Chrome", record=self.new["20260718_212516.png"])
        chrome = result["independent_conditions"][0]
        # Simulate v8 dropping then identity keeping host identity from scene.
        self.assertTrue(chrome["confirmed"] or result.get("relevant") is True)
        kept = _decide(
            "Google Chrome",
            self.new["20260718_212516.png"],
            [{"condition": "Google Chrome", "confirmed": True, "evidence": "scene Google Chrome open"}],
        )
        self.assertTrue(kept["relevant"])


if __name__ == "__main__":
    unittest.main()
