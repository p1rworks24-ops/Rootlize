"""Re-evaluate the prior 24-image development set with facts v6 only."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_expanded_poc as dev
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE, configure


if __name__ == "__main__":
    configure()
    poc.DEFAULT_OUTPUT = poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-poc-facts-v6b-dev24"
    poc.SELECTED_IMAGES = poc.SELECTED_IMAGES + dev.NEW_IMAGES
    poc.QUERIES = dev.QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    raise SystemExit(poc.main())
