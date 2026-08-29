"""Frozen-v5 DB Source-of-Truth PoC on a 24-image generalization set.

This module changes only the evaluation corpus, human ground truth, and output
location. Vision extraction, DB representation, query parsing, condition
evaluation, and final relevance logic are imported unchanged from
``db_sot_poc``.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc


OUTPUT = poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-poc-expanded-v5"

NEW_IMAGES = (
    {"name": "test1.jpg", "reason": "白い折れ耳猫の写真。未知の動物属性を評価。"},
    {"name": "test3.jpg", "reason": "複数のアニメ人物と都市背景。写真/UI以外のentityを評価。"},
    {"name": "タイトルなし.jpg", "reason": "OCR開発パネル。特殊なapplication/UI/stateを評価。"},
    {"name": "_001.png", "reason": "暗いOBS Studio録画設定。application/attribute/settingsを評価。"},
    {"name": "_003.png", "reason": "明るいスクリーンショット管理ギャラリーとPreview。"},
    {"name": "20260718_160712_001.png", "reason": "Windows desktop上の暗いCursor Agent UI。"},
    {"name": "20260718_202718.png", "reason": "湖の壁紙と多数のアイコンが見えるWindows desktop。"},
    {"name": "20260718_212500.png", "reason": "Chrome/YouTubeのVALORANT配信とライブチャット。"},
    {"name": "20260815_221055.png", "reason": "多数の動物サムネイルを含むCapixeギャラリー。"},
    {"name": "20260815_231828.png", "reason": "別レイアウトのCapixeギャラリーと動物サムネイル。"},
    {"name": "20260818_000310_001.png", "reason": "Ask AIで犬2件を表示中のCapixe。"},
    {"name": "20260815_225500.png", "reason": "Windows desktop検索結果を示すCapixe UIモック。"},
)


def q(query, kind, difficulty, must_include, notes=""):
    return {
        "query": query,
        "kind": kind,
        "difficulty": difficulty,
        "must_include": must_include,
        "notes": notes,
    }


# Human GT follows the product rule: a match needs every condition explicitly
# stated by the query, but unrelated coexisting content never makes it wrong.
QUERIES = (
    q("dog", "entity", "easy", ["A2.png", "images.jpg", "20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("cat", "entity", "easy", ["27750021_m.jpg", "test1.jpg", "20260815_221055.png", "20260815_231828.png"]),
    q("orange brown dog", "attribute", "medium", ["A2.png", "20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("sitting dog", "state", "medium", ["A2.png", "20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("standing dog", "state", "medium", ["images.jpg", "20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("sitting orange brown dog", "and", "hard", ["A2.png", "20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("Google Chrome", "application", "easy", ["20260716_194437.png", "20260718_201711.png", "20260718_205213.png", "ScreenShot_Atest_002.png", "20260718_212500.png"]),
    q("Windows desktop", "environment", "easy", ["20260716_194437.png", "20260718_201711.png", "20260718_210026.png", "20260718_204024.png", "Screenshot_001.png", "20260718_205213.png", "ScreenShot_Atest_002.png", "20260718_160712_001.png", "20260718_202718.png", "20260718_212500.png"]),
    q("Google Chrome in Windows desktop", "app_env", "medium", ["20260716_194437.png", "20260718_201711.png", "20260718_205213.png", "ScreenShot_Atest_002.png", "20260718_212500.png"]),
    q("ChatGPT in a browser", "relationship", "medium", ["20260718_201711.png", "ScreenShot_Atest_002.png"]),
    q("Google Chrome showing YouTube VALORANT", "relationship", "hard", ["20260718_205213.png", "20260718_212500.png"]),
    q("code editor", "ui", "easy", ["20260718_210026.png", "20260718_204024.png", "20260718_160712_001.png"]),
    q("dark code editor", "attribute", "medium", ["20260718_210026.png", "20260718_204024.png", "20260718_160712_001.png"]),
    q("code editor with terminal visible", "relationship", "hard", ["20260718_204024.png"]),
    q("file explorer window", "ui", "easy", ["Screenshot_001.png"]),
    q("screenshot manager", "application", "easy", ["about.png", "20260813_225929.png", "ScreenShot_Atest_002.png", "_003.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png", "20260815_225500.png"]),
    q("screenshot manager showing a dog", "coexistence", "hard", ["20260813_225929.png", "20260815_221055.png", "20260815_231828.png", "20260818_000310_001.png"]),
    q("PowerShell", "application", "easy", ["20260716_194437.png", "20260718_204024.png", "ScreenShot_Atest_002.png"]),
    q("Windows desktop with Chrome and PowerShell", "and", "hard", ["20260716_194437.png", "ScreenShot_Atest_002.png"]),
    q("calico cat lying on a wooden floor", "and", "hard", ["27750021_m.jpg"]),
    q("File Explorer with Capixe.exe selected", "state", "hard", ["Screenshot_001.png"]),
    q("white cat", "attribute", "medium", ["27750021_m.jpg", "test1.jpg", "20260815_221055.png", "20260815_231828.png"]),
    q("white cat with folded ears", "and", "hard", ["test1.jpg", "20260815_221055.png", "20260815_231828.png"]),
    q("anime characters", "entity", "easy", ["test3.jpg"]),
    q("anime characters above a village", "relationship", "hard", ["test3.jpg"]),
    q("OBS Studio settings", "application", "medium", ["_001.png"]),
    q("dark recording settings screen", "and", "hard", ["_001.png"]),
    q("OCR test panel", "ui", "medium", ["タイトルなし.jpg"]),
    q("screenshot manager with a preview panel", "relationship", "hard", ["ScreenShot_Atest_002.png", "_003.png"]),
    q("screenshot manager with Ask AI open", "state", "hard", ["20260818_000310_001.png"]),
    q("Windows desktop with lake wallpaper", "and", "hard", ["20260718_202718.png"]),
    q("Windows desktop with many game shortcuts", "and", "hard", ["20260718_202718.png"]),
    q("YouTube showing a VALORANT match", "relationship", "medium", ["20260718_205213.png", "20260718_212500.png"]),
    q("live chat beside a VALORANT video", "relationship", "hard", ["20260718_205213.png", "20260718_212500.png"]),
)


if __name__ == "__main__":
    poc.DEFAULT_OUTPUT = OUTPUT
    poc.SELECTED_IMAGES = poc.SELECTED_IMAGES + NEW_IMAGES
    poc.QUERIES = QUERIES
    raise SystemExit(poc.main())
