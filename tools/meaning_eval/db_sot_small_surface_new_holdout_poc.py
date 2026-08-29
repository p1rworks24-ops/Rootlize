"""Regenerate only remaining-FN images with the small-named-surface facts prompt.

Search meaning contract stays identity-bound. Frozen facts for other images are
reused. Crop / max_edge / schema are unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.meaning_eval import db_sot_poc as poc
from tools.meaning_eval.db_sot_facts_v6 import DEFAULT_MAX_EDGE
from tools.meaning_eval.db_sot_facts_small_surface import configure
from tools.meaning_eval.db_sot_surface_new_holdout_poc import IMAGES, QUERIES
from tools.meaning_eval.db_sot_surface_v8_identity import (
    copy_frozen_facts,
    evaluate_bound_surface,
    parse_bound_surface_query,
)
from tools.meaning_eval.describe_judge import empty_usage


FACTS_SOURCE = (
    poc.ROOT
    / "artifacts"
    / "meaning-eval"
    / "runs"
    / "db-source-of-truth-surface-v8-identity-new-holdout10"
    / "facts.json"
)
OUTPUT = (
    poc.ROOT
    / "artifacts"
    / "meaning-eval"
    / "runs"
    / "db-source-of-truth-small-named-surface-new-holdout10"
)

FN_IMAGES = (
    "20260718_202750.png",
    "20260718_212504.png",
    "20260718_212516.png",
    "20260720_233733.png",
    "20260721_203931.png",
    "20260721_204004.png",
)
REPRESENTATIVE_IMAGES = (
    "20260720_233733.png",
    "20260721_203931.png",
    "20260718_202750.png",
)
CHECK_CASES = (
    ("Chrome icon", "20260718_202750.png"),
    ("Chrome icon", "20260718_212504.png"),
    ("Chrome icon", "20260718_212516.png"),
    ("Chrome icon", "20260720_233733.png"),
    ("Tags button", "20260718_202750.png"),
    ("Tags button", "20260721_203931.png"),
    ("Tags button", "20260721_204004.png"),
    ("Tags button", "20260721_204338.png"),
    ("Microsoft VS Code folder", "20260718_202750.png"),
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def drop_records(facts_path: Path, names: set[str], *, reset_usage: bool) -> list[str]:
    data = json.loads(facts_path.read_text(encoding="utf-8"))
    kept = []
    dropped = []
    for record in data.get("records") or []:
        if record.get("filename") in names:
            dropped.append(record.get("filename"))
            continue
        kept.append(record)
    data["records"] = kept
    if reset_usage:
        data["usage"] = empty_usage()
    _write_json(facts_path, data)
    return dropped


def check_surfaces(facts_path: Path) -> str:
    data = json.loads(facts_path.read_text(encoding="utf-8"))
    records = {item["filename"]: item for item in data.get("records") or []}
    lines = [f"prompt {data.get('prompt_version')} records {len(records)}"]
    for query, name in CHECK_CASES:
        record = records.get(name)
        if record is None:
            lines.append(f"{query:28} {name:24} MISSING")
            continue
        bound = parse_bound_surface_query(query)
        ok = evaluate_bound_surface(bound, record)
        named = [
            f"{item.get('name')}|{item.get('attributes')}"
            for item in (record.get("entities") or [])
            if any(
                token in f"{item.get('name')} {' '.join(item.get('attributes') or [])}".lower()
                for token in ("chrome", "icon", "taskbar", "tags", "button", "quick", "nav", "folder", "vs")
            )
        ]
        lines.append(f"{query:28} {name:24} checker={ok} hits={named}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--regenerate", nargs="*", default=None)
    parser.add_argument("--representatives", action="store_true")
    parser.add_argument("--fn-images", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args, rest = parser.parse_known_args()
    sys.argv = [sys.argv[0], *rest]

    configure()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    facts_path = OUTPUT / "facts.json"

    if args.check_only:
        if not facts_path.is_file():
            raise SystemExit(f"missing facts: {facts_path}")
        text = check_surfaces(facts_path)
        (OUTPUT / "surface-check.txt").write_text(text, encoding="utf-8")
        print(text, end="")
        return 0

    reset = args.reset or not facts_path.is_file()
    if reset:
        copy_frozen_facts(FACTS_SOURCE, OUTPUT)

    names: list[str]
    if args.regenerate is not None:
        names = list(args.regenerate)
    elif args.representatives:
        names = list(REPRESENTATIVE_IMAGES)
    elif args.fn_images:
        names = list(FN_IMAGES)
    else:
        names = []

    dropped = drop_records(facts_path, set(names), reset_usage=reset) if names else []
    search_path = OUTPUT / "search.jsonl"
    if dropped and search_path.exists():
        search_path.unlink()

    poc.DEFAULT_OUTPUT = OUTPUT
    poc.SELECTED_IMAGES = IMAGES
    poc.QUERIES = () if args.skip_search else QUERIES
    if "--max-edge" not in sys.argv:
        sys.argv.extend(["--max-edge", str(DEFAULT_MAX_EDGE)])
    if "--reuse-facts" not in sys.argv:
        sys.argv.append("--reuse-facts")
    print(
        json.dumps(
            {
                "stage": "prepare",
                "regenerate": dropped,
                "skip_search": args.skip_search,
                "output": str(OUTPUT),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    code = poc.main()
    text = check_surfaces(facts_path)
    (OUTPUT / "surface-check.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
