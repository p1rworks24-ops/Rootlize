"""Presence-role v7 evaluation on the unchanged v6b holdout10."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_improved_holdout_poc as holdout
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE
from tools.meaning_eval.db_sot_presence_v7 import configure

if __name__ == "__main__":
    configure()
    poc.DEFAULT_OUTPUT = poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-presence-v7c-holdout10"
    poc.SELECTED_IMAGES = holdout.HOLDOUT_IMAGES
    poc.QUERIES = holdout.HOLDOUT_QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    raise SystemExit(poc.main())
