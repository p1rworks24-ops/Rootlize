"""Unseen 10-image holdout for facts v6; search logic remains frozen."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval.db_sot_expanded_poc import q
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE, configure


HOLDOUT_IMAGES = (
    {"name": "20260717_000902.png", "reason": "フォルダツリーとPreviewを持つ未知の画像管理UI。"},
    {"name": "ScreenShot_Atest_001.png", "reason": "山岳壁紙と多数のshortcutがあるWindows desktop。"},
    {"name": "20260718_205234.png", "reason": "Chrome/YouTubeのVALORANT映像とlive chat。"},
    {"name": "testshot_001.png", "reason": "Windows desktop上のChrome/ChatGPT。"},
    {"name": "bcaa36cf-f68d-435b-bcdf-26dd1ea7dffa.png", "reason": "多様な画像とPreviewを持つCAPIXEギャラリー。"},
    {"name": "20260815_225418.png", "reason": "動物・アニメ・UIを多数含むCapixeギャラリー。"},
    {"name": "20260816_204701_001.png", "reason": "ブランド表示のない空フォルダ画像UI。"},
    {"name": "20260812_222344.png", "reason": "No screenshots found状態の画像ライブラリUI。"},
    {"name": "20260721_210812.png", "reason": "暗いWeb modalとlocked state。"},
    {"name": "20260729_234504.png", "reason": "画像・動画未追加のproject submission UI。"},
)

HOLDOUT_QUERIES = (
    q("screenshot manager", "application", "easy", ["20260717_000902.png", "bcaa36cf-f68d-435b-bcdf-26dd1ea7dffa.png", "20260815_225418.png", "20260812_222344.png"]),
    q("screenshot manager with a preview panel", "relationship", "hard", ["20260717_000902.png", "bcaa36cf-f68d-435b-bcdf-26dd1ea7dffa.png"]),
    q("dog", "entity", "easy", ["20260815_225418.png"]),
    q("cat", "entity", "easy", ["20260815_225418.png"]),
    q("white cat", "attribute", "medium", ["20260815_225418.png"]),
    q("sitting orange brown dog", "and", "hard", ["20260815_225418.png"]),
    q("standing dog", "state", "medium", ["20260815_225418.png"]),
    q("anime characters", "entity", "easy", ["20260815_225418.png"]),
    q("screenshot manager showing a dog", "coexistence", "hard", ["20260815_225418.png"]),
    q("Windows desktop", "environment", "easy", ["ScreenShot_Atest_001.png", "20260718_205234.png", "testshot_001.png"]),
    q("Windows desktop with mountain wallpaper", "and", "hard", ["ScreenShot_Atest_001.png"]),
    q("Windows desktop with many game shortcuts", "and", "hard", ["ScreenShot_Atest_001.png"]),
    q("code editor", "ui", "easy", ["bcaa36cf-f68d-435b-bcdf-26dd1ea7dffa.png"], "Code editors are visibly depicted in gallery thumbnails; desktop shortcuts alone do not count."),
    q("Google Chrome", "application", "easy", ["20260718_205234.png", "testshot_001.png"]),
    q("ChatGPT in a browser", "relationship", "medium", ["testshot_001.png"]),
    q("YouTube showing a VALORANT match", "relationship", "medium", ["20260718_205234.png"]),
    q("live chat beside a VALORANT video", "relationship", "hard", ["20260718_205234.png"]),
    q("empty image library", "state", "medium", ["20260816_204701_001.png", "20260812_222344.png"]),
    q("dark website modal", "and", "medium", ["20260721_210812.png"]),
    q("project submission with no images or videos", "state", "hard", ["20260729_234504.png"]),
)


if __name__ == "__main__":
    configure()
    poc.DEFAULT_OUTPUT = poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-poc-facts-v6b-holdout10"
    poc.SELECTED_IMAGES = HOLDOUT_IMAGES
    poc.QUERIES = HOLDOUT_QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    raise SystemExit(poc.main())
