"""Re-evaluate dev24 with identity-bound surface contract; reuse v8 facts."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval import db_sot_expanded_poc as dev
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE
from tools.meaning_eval.db_sot_surface_v8_identity import configure, copy_frozen_facts


FACTS_SOURCE = (
    poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-surface-v8-dev24" / "facts.json"
)
OUTPUT = (
    poc.ROOT / "artifacts" / "meaning-eval" / "runs" / "db-source-of-truth-surface-v8-identity-dev24"
)


if __name__ == "__main__":
    configure()
    copy_frozen_facts(FACTS_SOURCE, OUTPUT)
    poc.DEFAULT_OUTPUT = OUTPUT
    poc.SELECTED_IMAGES = poc.SELECTED_IMAGES + dev.NEW_IMAGES
    poc.QUERIES = dev.QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    if "--reuse-facts" not in sys.argv:
        sys.argv.append("--reuse-facts")
    raise SystemExit(poc.main())
