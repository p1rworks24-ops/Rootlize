"""Completely unused 10-image presence-role holdout."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval.db_sot_expanded_poc import q
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE
from tools.meaning_eval.db_sot_presence_v7 import configure

IMAGES = (
    {"name": "20260718_202750.png", "reason": "Chrome/ChatGPT背景、前景画像管理UI、Preview、folder names、nested thumbnails。"},
    {"name": "20260718_203006.png", "reason": "Chromeで開いたChatGPTと文章。"},
    {"name": "20260718_212504.png", "reason": "Chrome/YouTube/VALORANT/live chatと保存通知。"},
    {"name": "20260718_212516.png", "reason": "別場面のYouTube VALORANT replayとlive chat。"},
    {"name": "20260720_220408.png", "reason": "Capixeロゴだけを描いたsplash image。"},
    {"name": "20260720_233733.png", "reason": "Chrome/ChatGPTと保存通知。"},
    {"name": "20260721_203901.png", "reason": "browser chromeのないWeb rules content。"},
    {"name": "20260721_203931.png", "reason": "Capixe Homeのopen UIと複数control。"},
    {"name": "20260721_204004.png", "reason": "Capixe Tags UI、Chrome文字tag、controls。"},
    {"name": "20260721_204338.png", "reason": "別レイアウトのCapixe Home UI。"},
)

QUERIES = (
    q("Google Chrome", "application", "easy", ["20260718_202750.png", "20260718_203006.png", "20260718_212504.png", "20260718_212516.png", "20260720_233733.png"]),
    q("Google Chrome open", "presence", "medium", ["20260718_202750.png", "20260718_203006.png", "20260718_212504.png", "20260718_212516.png", "20260720_233733.png"]),
    q("Chrome icon", "presence", "medium", ["20260718_202750.png", "20260718_212504.png", "20260718_212516.png", "20260720_233733.png"]),
    q("Chrome text mention", "presence", "hard", ["20260721_204004.png"]),
    q("ChatGPT in a browser", "relationship", "medium", ["20260718_202750.png", "20260718_203006.png", "20260720_233733.png"]),
    q("screenshot manager", "application", "easy", ["20260718_202750.png", "20260721_203931.png", "20260721_204004.png", "20260721_204338.png"]),
    q("screenshot manager with a preview panel", "relationship", "hard", ["20260718_202750.png"]),
    q("Preview panel", "ui", "medium", ["20260718_202750.png"]),
    q("Microsoft VS Code folder", "presence", "medium", ["20260718_202750.png"]),
    q("Visual Studio Code", "application", "easy", []),
    q("YouTube showing a VALORANT match", "relationship", "medium", ["20260718_212504.png", "20260718_212516.png"]),
    q("live chat beside a VALORANT video", "relationship", "hard", ["20260718_212504.png", "20260718_212516.png"]),
    q("Screenshot Saved notification", "ui", "medium", ["20260718_212504.png", "20260720_233733.png"]),
    q("Capixe logo", "subject", "easy", ["20260720_220408.png", "20260721_203931.png", "20260721_204004.png", "20260721_204338.png"]),
    q("Tags button", "presence", "medium", ["20260718_202750.png", "20260721_203931.png", "20260721_204004.png", "20260721_204338.png"]),
    q("Tags panel open", "presence", "hard", ["20260721_204004.png"]),
    q("Home panel open", "presence", "hard", ["20260721_203931.png", "20260721_204338.png"]),
    q("web page", "ui", "easy", ["20260718_202750.png", "20260718_203006.png", "20260718_212504.png", "20260718_212516.png", "20260720_233733.png", "20260721_203901.png"]),
    q("VALORANT round win", "state", "medium", ["20260718_212504.png"]),
    q("VALORANT replay", "state", "medium", ["20260718_212516.png"]),
)

if __name__ == "__main__":
    configure()
    poc.DEFAULT_OUTPUT = poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-presence-v7c-new-holdout10"
    poc.SELECTED_IMAGES = IMAGES
    poc.QUERIES = QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    raise SystemExit(poc.main())
