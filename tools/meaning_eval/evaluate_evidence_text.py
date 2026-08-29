"""Independent Semantic Index Evidence → Text AI ternary Meaning PoC.

Judges every query-image pair from Semantic Index v4 evidence only.
Does not change product search, matcher, threshold, Hybrid, Vision Judge
prompts, Semantic Index generation, GT v2, or the query set.
Does not overwrite artifacts/meaning-eval/latest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.relevance import RelevanceImage
from app.relevance.openai_provider import DEFAULT_MODEL
from tools.meaning_eval.dataset import QuerySpec, load_dataset
from tools.meaning_eval.describe_judge import add_usage, empty_usage, estimate_usd
from tools.meaning_eval.evidence_text import (
    DECISIONS,
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    NESTED_DOG_IMAGES,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    EvidenceTextJudgeProvider,
    QuotaExhaustedError,
    classify_nested_dog_index,
    classify_nested_dog_outcome,
    flatten_index_text,
    format_index_evidence,
)
from tools.meaning_eval.identity import corpus_identity, git_identity
from tools.meaning_eval.metrics import end_to_end_counts, f1_score, summarize_end_to_end
from tools.meaning_eval.semantic_index import load_index_cache
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-evidence-text-gt-v2"
DEFAULT_INDEX_CACHE = ROOT / "artifacts" / "meaning-eval" / "semantic-index" / "index-v4.json"
HYBRID_RESULTS = (
    RUNS_DIR / "semantic-index-hybrid-phase-e-gt-v2-meaning-units" / "results.json"
)
JUDGE_RESULTS = RUNS_DIR / "vision-judge-gt-v2-meaning-units" / "results.json"
INDEX_ONLY_RESULTS = RUNS_DIR / "semantic-index-v4-only-gt-v2" / "results.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
FOCUS_QUERIES = (
    "Google Chrome",
    "Google Chrome in Windows desktop",
    "dog",
    "orange brown dog",
    "sitting orange brown dog",
    "ChatGPT in a browser",
    "empty folder in screenshot manager",
    "code editor",
    "command prompt",
    "file explorer window",
    "Windows desktop",
    "image gallery",
)
BROAD_UI_QUERIES = (
    "file explorer window",
    "Windows desktop",
    "image gallery",
)
HYBRID_MEAN_VISION = 32.0


def list_images(folder: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda path: path.name.lower(),
    )


def _json_load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_by_query(payload: dict | None, *, path: tuple[str, ...]) -> dict[str, dict]:
    if not payload:
        return {}
    cursor: object = payload
    for key in path:
        if not isinstance(cursor, dict):
            return {}
        cursor = cursor.get(key)
    if isinstance(cursor, list):
        return {row["query"]: row for row in cursor if isinstance(row, dict) and "query" in row}
    return {}


def _load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["query"]] = row
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rewrite_checkpoint(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [rows[query] for query in rows]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered),
        encoding="utf-8",
    )


def _gt_label(spec: QuerySpec, name: str) -> str:
    if name in spec.must_include_set:
        return "positive"
    if name in spec.acceptable_set:
        return "acceptable"
    if name in spec.must_exclude_set:
        return "exclude"
    return "unlabeled_negative"


def _decision_counts(decisions: dict[str, dict]) -> dict[str, int]:
    counts = {name: 0 for name in DECISIONS}
    counts["unknown"] = 0
    for item in decisions.values():
        decision = item.get("decision")
        if item.get("unknown_reason"):
            counts["unknown"] += 1
        if decision in counts:
            counts[decision] += 1
        else:
            counts["unknown"] += 1
    return counts


def _routing_counts(spec: QuerySpec, decisions: dict[str, dict], names: list[str]) -> dict:
    counts = {
        "gt_positive_relevant": 0,
        "gt_positive_insufficient": 0,
        "gt_positive_irrelevant": 0,
        "gt_negative_irrelevant": 0,
        "gt_negative_insufficient": 0,
        "gt_negative_relevant": 0,
        "acceptable_relevant": 0,
        "acceptable_insufficient": 0,
        "acceptable_irrelevant": 0,
        "pos_irrelevant_names": [],
        "neg_relevant_names": [],
    }
    for name in names:
        decision = (decisions.get(name) or {}).get("decision")
        if name in spec.must_include_set:
            if decision == "relevant":
                counts["gt_positive_relevant"] += 1
            elif decision == "insufficient_evidence":
                counts["gt_positive_insufficient"] += 1
            else:
                counts["gt_positive_irrelevant"] += 1
                counts["pos_irrelevant_names"].append(name)
        elif name in spec.acceptable_set:
            if decision == "relevant":
                counts["acceptable_relevant"] += 1
            elif decision == "insufficient_evidence":
                counts["acceptable_insufficient"] += 1
            else:
                counts["acceptable_irrelevant"] += 1
        else:
            if decision == "irrelevant":
                counts["gt_negative_irrelevant"] += 1
            elif decision == "insufficient_evidence":
                counts["gt_negative_insufficient"] += 1
            else:
                counts["gt_negative_relevant"] += 1
                counts["neg_relevant_names"].append(name)
    return counts


def _text_only_row(spec: QuerySpec, decisions: dict[str, dict], names: list[str]) -> dict:
    predicted = [
        name for name in names
        if (decisions.get(name) or {}).get("decision") == "relevant"
    ]
    counts = end_to_end_counts(
        must_include=spec.must_include_set,
        acceptable=spec.acceptable_set,
        predicted=set(predicted),
    )
    settled_predicted = []
    settled_must = set()
    settled_acceptable = set()
    for name in names:
        decision = (decisions.get(name) or {}).get("decision")
        if decision not in ("relevant", "irrelevant"):
            continue
        if name in spec.must_include_set:
            settled_must.add(name)
        elif name in spec.acceptable_set:
            settled_acceptable.add(name)
        if decision == "relevant":
            settled_predicted.append(name)
    settled = end_to_end_counts(
        must_include=settled_must,
        acceptable=settled_acceptable,
        predicted=set(settled_predicted),
    )
    decision_counts = _decision_counts(decisions)
    routing = _routing_counts(spec, decisions, names)
    n = len(names)
    pos = len(spec.must_include)
    insufficient = decision_counts["insufficient_evidence"]
    settled_n = decision_counts["relevant"] + decision_counts["irrelevant"]
    return {
        "query": spec.query,
        "split": spec.split,
        "kind": spec.kind,
        "notes": spec.notes,
        "predicted": predicted,
        **counts,
        "f1": f1_score(counts["precision"], counts["recall"]),
        "decision_counts": decision_counts,
        "routing": routing,
        "settled_only": {
            **settled,
            "f1": f1_score(settled["precision"], settled["recall"]),
            "n": settled_n,
        },
        "coverage": {
            "n": n,
            "settled": settled_n,
            "settled_rate": 0.0 if not n else settled_n / n,
            "insufficient": insufficient,
            "insufficient_rate": 0.0 if not n else insufficient / n,
            "positive_n": pos,
            "positive_insufficient": routing["gt_positive_insufficient"],
            "positive_insufficient_rate": (
                0.0 if not pos else routing["gt_positive_insufficient"] / pos
            ),
            "positive_irrelevant": routing["gt_positive_irrelevant"],
            "positive_relevant": routing["gt_positive_relevant"],
        },
    }


def _replay_row(
    spec: QuerySpec,
    decisions: dict[str, dict],
    names: list[str],
    vision_predicted: set[str],
) -> dict:
    predicted = []
    sources = {}
    missing_vision = []
    for name in names:
        decision = (decisions.get(name) or {}).get("decision")
        if decision == "relevant":
            predicted.append(name)
            sources[name] = "text_relevant"
        elif decision == "insufficient_evidence":
            if name in vision_predicted:
                predicted.append(name)
                sources[name] = "vision_fallback"
            else:
                sources[name] = "vision_negative"
        else:
            sources[name] = "text_irrelevant"
        if decision == "insufficient_evidence" and name not in vision_predicted and name in spec.must_include_set:
            # Vision replay is complete for judged corpus; missing means Vision said false.
            pass
        if decision == "insufficient_evidence" and not vision_predicted and name not in sources:
            missing_vision.append(name)
    counts = end_to_end_counts(
        must_include=spec.must_include_set,
        acceptable=spec.acceptable_set,
        predicted=set(predicted),
    )
    vision_sent = [
        name for name in names
        if (decisions.get(name) or {}).get("decision") == "insufficient_evidence"
    ]
    return {
        "query": spec.query,
        "split": spec.split,
        "kind": spec.kind,
        "predicted": predicted,
        **counts,
        "f1": f1_score(counts["precision"], counts["recall"]),
        "vision_sent_images": len(vision_sent),
        "vision_sent_names": vision_sent,
        "fallback_sources": sources,
    }


def _mean(values: list[float]) -> float:
    return 0.0 if not values else sum(values) / len(values)


def _summarize_text_rows(rows: list[dict]) -> dict:
    e2e = summarize_end_to_end(rows)
    routing = {
        "gt_positive_relevant": sum(row["routing"]["gt_positive_relevant"] for row in rows),
        "gt_positive_insufficient": sum(row["routing"]["gt_positive_insufficient"] for row in rows),
        "gt_positive_irrelevant": sum(row["routing"]["gt_positive_irrelevant"] for row in rows),
        "gt_negative_irrelevant": sum(row["routing"]["gt_negative_irrelevant"] for row in rows),
        "gt_negative_insufficient": sum(row["routing"]["gt_negative_insufficient"] for row in rows),
        "gt_negative_relevant": sum(row["routing"]["gt_negative_relevant"] for row in rows),
    }
    coverage = {
        "mean_settled_rate": _mean([row["coverage"]["settled_rate"] for row in rows]),
        "mean_insufficient_rate": _mean([row["coverage"]["insufficient_rate"] for row in rows]),
        "mean_positive_insufficient_rate": _mean(
            [row["coverage"]["positive_insufficient_rate"] for row in rows]
        ),
        "mean_vision_fallback": _mean(
            [float(row["coverage"]["insufficient"]) for row in rows]
        ),
        "total_insufficient": sum(row["coverage"]["insufficient"] for row in rows),
        "total_settled": sum(row["coverage"]["settled"] for row in rows),
    }
    return {
        **e2e,
        "routing": routing,
        "coverage": coverage,
        "queries": [
            {
                "query": row["query"],
                "split": row["split"],
                "kind": row["kind"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "tp": row["tp"],
                "fp": row["fp"],
                "fn": row["fn"],
                "relevant": row["decision_counts"]["relevant"],
                "irrelevant": row["decision_counts"]["irrelevant"],
                "insufficient_evidence": row["decision_counts"]["insufficient_evidence"],
                "unknown": row["decision_counts"]["unknown"],
                "gt_positive_relevant": row["routing"]["gt_positive_relevant"],
                "gt_positive_insufficient": row["routing"]["gt_positive_insufficient"],
                "gt_positive_irrelevant": row["routing"]["gt_positive_irrelevant"],
                "gt_negative_relevant": row["routing"]["gt_negative_relevant"],
                "gt_negative_insufficient": row["routing"]["gt_negative_insufficient"],
                "gt_negative_irrelevant": row["routing"]["gt_negative_irrelevant"],
                "settled_rate": row["coverage"]["settled_rate"],
                "insufficient_rate": row["coverage"]["insufficient_rate"],
                "positive_insufficient_rate": row["coverage"]["positive_insufficient_rate"],
            }
            for row in rows
        ],
    }


def _summarize_replay_rows(rows: list[dict]) -> dict:
    e2e = summarize_end_to_end(rows)
    return {
        **e2e,
        "mean_vision_sent": _mean([float(row["vision_sent_images"]) for row in rows]),
        "total_vision_sent": sum(row["vision_sent_images"] for row in rows),
        "queries": [
            {
                "query": row["query"],
                "split": row["split"],
                "precision": row["precision"],
                "recall": row["recall"],
                "f1": row["f1"],
                "tp": row["tp"],
                "fp": row["fp"],
                "fn": row["fn"],
                "vision_sent_images": row["vision_sent_images"],
            }
            for row in rows
        ],
    }


def _prf(row: dict | None) -> str:
    if not row:
        return "n/a"
    return (
        f"{row.get('precision', 0):.3f}/"
        f"{row.get('recall', 0):.3f}/"
        f"{row.get('f1', 0):.3f}"
    )


def _should_expand_all(focus_summary: dict, chrome: dict, broad_ui: dict) -> tuple[bool, str]:
    routing = focus_summary["routing"]
    coverage = focus_summary["coverage"]
    pos = (
        routing["gt_positive_relevant"]
        + routing["gt_positive_insufficient"]
        + routing["gt_positive_irrelevant"]
    )
    pos_irr_rate = 0.0 if not pos else routing["gt_positive_irrelevant"] / pos
    reasons = []
    if pos_irr_rate > 0.15:
        reasons.append(
            f"GT positive→irrelevant {routing['gt_positive_irrelevant']}/{pos} "
            f"({pos_irr_rate:.1%}) exceeds 15%"
        )
    if coverage["mean_insufficient_rate"] > 0.80:
        reasons.append(
            f"mean insufficient {coverage['mean_insufficient_rate']:.1%} "
            "is too high for Text to settle"
        )
    if focus_summary["macro_precision"] < 0.45 and coverage["mean_insufficient_rate"] < 0.25:
        reasons.append(
            f"Text-only precision {focus_summary['macro_precision']:.3f} is low "
            "while settling most pairs"
        )
    signal = []
    if chrome.get("distinction_holds"):
        signal.append("Chrome short vs compound distinction holds")
    if broad_ui.get("fp_improved"):
        signal.append("broad UI FP improved vs Hybrid C")
    if routing["gt_positive_irrelevant"] <= 3:
        signal.append("unknown!=false is mostly holding")
    if coverage["mean_insufficient_rate"] <= 0.55:
        signal.append("Text settles a useful share without Vision")
    if reasons:
        return False, "; ".join(reasons)
    if not signal:
        return False, "no clear contract or cost signal on the focus set"
    return True, "; ".join(signal)


def _chrome_view(dataset, decisions_by_query: dict[str, dict], names: list[str]) -> dict:
    empty = {
        "short_relevant": 0,
        "compound_relevant": 0,
        "both_relevant": [],
        "short_only_relevant": [],
        "compound_only_relevant": [],
        "short_gt_positive_relevant": [],
        "compound_gt_positive_relevant": [],
        "distinction_holds": False,
        "note": "Chrome queries were not in this run.",
    }
    if (
        "Google Chrome" not in decisions_by_query
        or "Google Chrome in Windows desktop" not in decisions_by_query
    ):
        return empty
    short_spec = dataset.spec("Google Chrome")
    long_spec = dataset.spec("Google Chrome in Windows desktop")
    short = decisions_by_query.get("Google Chrome") or {}
    long = decisions_by_query.get("Google Chrome in Windows desktop") or {}
    both_relevant = []
    short_only = []
    long_only = []
    short_pos_rel = []
    long_pos_rel = []
    for name in names:
        short_d = (short.get(name) or {}).get("decision")
        long_d = (long.get(name) or {}).get("decision")
        if short_d == "relevant" and long_d == "relevant":
            both_relevant.append(name)
        elif short_d == "relevant":
            short_only.append(name)
        elif long_d == "relevant":
            long_only.append(name)
        if name in short_spec.must_include_set and short_d == "relevant":
            short_pos_rel.append(name)
        if name in long_spec.must_include_set and long_d == "relevant":
            long_pos_rel.append(name)
    short_rel = sum(1 for name in names if (short.get(name) or {}).get("decision") == "relevant")
    long_rel = sum(1 for name in names if (long.get(name) or {}).get("decision") == "relevant")
    distinction_holds = long_rel <= short_rel and not long_only
    return {
        "short_relevant": short_rel,
        "compound_relevant": long_rel,
        "both_relevant": both_relevant,
        "short_only_relevant": short_only,
        "compound_only_relevant": long_only,
        "short_gt_positive_relevant": short_pos_rel,
        "compound_gt_positive_relevant": long_pos_rel,
        "distinction_holds": distinction_holds,
        "note": (
            "Short query may confirm Chrome alone. Compound query also needs a "
            "Windows desktop environment and the Chrome-in-desktop relation."
        ),
    }


def _broad_ui_view(
    dataset,
    text_rows: list[dict],
    hybrid_by_query: dict[str, dict],
    index_by_query: dict[str, dict],
) -> dict:
    by_query = {row["query"]: row for row in text_rows}
    rows = []
    improved = 0
    compared = 0
    for query in BROAD_UI_QUERIES:
        if query not in by_query:
            continue
        text = by_query[query]
        hybrid = hybrid_by_query.get(query) or {}
        index_row = index_by_query.get(query) or {}
        compared += 1
        text_fp = int(text.get("fp") or 0)
        hybrid_fp = int(hybrid.get("fp") or 0)
        if text_fp < hybrid_fp:
            improved += 1
        rows.append({
            "query": query,
            "text_fp": text_fp,
            "text_tp": int(text.get("tp") or 0),
            "text_fn": int(text.get("fn") or 0),
            "text_prf": _prf(text),
            "hybrid_fp": hybrid_fp,
            "hybrid_prf": _prf(hybrid),
            "index_fp": int(index_row.get("fp") or 0),
            "index_prf": _prf(index_row),
            "insufficient": text["decision_counts"]["insufficient_evidence"],
            "gt_positive_irrelevant": text["routing"]["gt_positive_irrelevant"],
        })
    return {
        "queries": rows,
        "fp_improved": compared > 0 and improved == compared,
        "improved_count": improved,
        "compared_count": compared,
    }


def _nested_dog_view(
    dataset,
    index_by_name: dict[str, dict],
    decisions_by_query: dict[str, dict],
) -> list[dict]:
    if "dog" not in decisions_by_query:
        return []
    spec = dataset.spec("dog")
    rows = []
    for name in NESTED_DOG_IMAGES:
        index_info = classify_nested_dog_index(index_by_name.get(name))
        decision_row = (decisions_by_query.get("dog") or {}).get(name) or {}
        decision = decision_row.get("decision") or "insufficient_evidence"
        rows.append({
            "name": name,
            "gt_positive": name in spec.must_include_set,
            **index_info,
            "text_decision": decision,
            "text_confidence": decision_row.get("confidence"),
            "text_reason": decision_row.get("short_reason"),
            "missing_evidence": decision_row.get("missing_evidence"),
            "outcome": classify_nested_dog_outcome(index_info["index_class"], decision),
        })
    return rows


def _split_rows(rows: list[dict], split: str) -> list[dict]:
    return [row for row in rows if row["split"] == split]


def _render_query_table(rows: list[dict]) -> list[str]:
    lines = [
        "| query | split | P | R | F1 | TP | FP | FN | relevant | irrelevant | insufficient | pos→rel | pos→ins | pos→irr | neg→rel |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| `{query}` | {split} | {precision:.3f} | {recall:.3f} | {f1:.3f} | "
            "{tp} | {fp} | {fn} | {relevant} | {irrelevant} | {insufficient} | "
            "{pos_rel} | {pos_ins} | {pos_irr} | {neg_rel} |".format(
                query=row["query"],
                split=row["split"],
                precision=row["precision"],
                recall=row["recall"],
                f1=row["f1"],
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                relevant=row["relevant"],
                irrelevant=row["irrelevant"],
                insufficient=row["insufficient_evidence"],
                pos_rel=row["gt_positive_relevant"],
                pos_ins=row["gt_positive_insufficient"],
                pos_irr=row["gt_positive_irrelevant"],
                neg_rel=row["gt_negative_relevant"],
            )
        )
    return lines


def render_summary(report: dict) -> str:
    focus = report["focus"]["text_only"]["all"]
    replay = report["focus"]["replay"]["all"]
    model = report["model"]
    nested = report["nested_dogs"]
    chrome = report["chrome"]
    broad = report["broad_ui"]
    expand = report["expansion"]
    lines = [
        "# Semantic Index Evidence Text ternary PoC",
        "",
        "## Run identity",
        "",
        f"- timestamp: `{report['identity']['timestamp']}`",
        f"- git commit: `{report['identity']['git_commit']}` dirty={report['identity']['git_dirty']}",
        f"- model: `{model['model']}`",
        f"- API: `{model['endpoint']}`",
        f"- temperature: `{model['temperature']}`",
        f"- structured output: `{model['schema_version']}` / prompt `{model['prompt_version']}`",
        f"- query set: `{report['identity']['query_set_version']}`",
        f"- GT: `{report['identity']['gt_version']}`",
        f"- Index: `{report['identity']['index_prompt_version']}` / `{report['identity']['index_schema_version']}`",
        f"- corpus: count={report['identity']['corpus_count']}",
        f"- stage: `{report['stage']}`",
        "",
        "## Evidence input",
        "",
        "Query-independent Semantic Index v4 fields, formatted as a compact evidence document:",
        "summary, media_type, scene_environment, identities (name/kind/importance/confidence/evidence),",
        "objects_entities, ui_interface_concepts, visible_activities, visual_attributes,",
        "searchable_concepts, incidental_notes.",
        "No image bytes. No raw JSON dump. Empty fields are marked as not recorded, not as absence.",
        "",
        "## A. Text-only settled relevant",
        "",
        "Predicted = `relevant` only. `insufficient_evidence` is not retrieved (hurts recall, not counted as FP).",
        "",
        "| split | n | macro P | macro R | macro F1 | micro TP | micro FP | micro FN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split in ("all", "dev", "holdout"):
        block = report["focus"]["text_only"].get(split) or {}
        if not block:
            continue
        lines.append(
            f"| {split} | {block.get('n', 0)} | {block.get('macro_precision', 0):.3f} | "
            f"{block.get('macro_recall', 0):.3f} | {block.get('macro_f1', 0):.3f} | "
            f"{block.get('micro_tp', 0)} | {block.get('micro_fp', 0)} | {block.get('micro_fn', 0)} |"
        )
    routing = focus["routing"]
    coverage = focus["coverage"]
    lines += [
        "",
        "### Per query",
        "",
        *_render_query_table(focus["queries"]),
        "",
        "## B. Insufficient routing",
        "",
        f"- GT positive → relevant: **{routing['gt_positive_relevant']}**",
        f"- GT positive → insufficient: **{routing['gt_positive_insufficient']}**",
        f"- GT positive → irrelevant: **{routing['gt_positive_irrelevant']}** (worst failure)",
        f"- GT negative → irrelevant: **{routing['gt_negative_irrelevant']}**",
        f"- GT negative → insufficient: **{routing['gt_negative_insufficient']}**",
        f"- GT negative → relevant: **{routing['gt_negative_relevant']}**",
        "",
        "## C. Evidence coverage",
        "",
        f"- mean settled rate: {coverage['mean_settled_rate']:.3f}",
        f"- mean insufficient rate: {coverage['mean_insufficient_rate']:.3f}",
        f"- mean positive insufficient rate: {coverage['mean_positive_insufficient_rate']:.3f}",
        f"- mean Vision fallback images/query: {coverage['mean_vision_fallback']:.1f}",
        f"- Hybrid C mean Vision images/query: {HYBRID_MEAN_VISION:.1f}",
        "",
        "## Replay: Text relevant + insufficient→existing Vision Judge",
        "",
        "| split | n | macro P | macro R | macro F1 | micro TP | micro FP | micro FN | mean Vision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for split in ("all", "dev", "holdout"):
        block = report["focus"]["replay"].get(split) or {}
        if not block:
            continue
        lines.append(
            f"| {split} | {block.get('n', 0)} | {block.get('macro_precision', 0):.3f} | "
            f"{block.get('macro_recall', 0):.3f} | {block.get('macro_f1', 0):.3f} | "
            f"{block.get('micro_tp', 0)} | {block.get('micro_fp', 0)} | {block.get('micro_fn', 0)} | "
            f"{block.get('mean_vision_sent', 0):.1f} |"
        )
    lines += [
        "",
        f"Focus replay vs Hybrid C 0.812/0.769/0.790: "
        f"{replay.get('macro_precision', 0):.3f}/"
        f"{replay.get('macro_recall', 0):.3f}/"
        f"{replay.get('macro_f1', 0):.3f}.",
        "",
        "## Nested dogs",
        "",
        "| image | index class | text decision | outcome |",
        "|---|---|---|---|",
    ]
    for row in nested:
        lines.append(
            f"| `{row['name']}` | {row['index_class']} | {row['text_decision']} | {row['outcome']} |"
        )
    lines += [
        "",
        "## Chrome short vs compound",
        "",
        f"- short relevant: {chrome['short_relevant']}",
        f"- compound relevant: {chrome['compound_relevant']}",
        f"- short-only relevant: {len(chrome['short_only_relevant'])}",
        f"- compound-only relevant: {len(chrome['compound_only_relevant'])}",
        f"- distinction holds: {chrome['distinction_holds']}",
        "",
        "## Broad UI FP",
        "",
        "| query | Text P/R/F1 | Text FP | Hybrid C P/R/F1 | Hybrid FP | Index-only FP | insufficient |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for row in broad["queries"]:
        lines.append(
            f"| `{row['query']}` | {row['text_prf']} | {row['text_fp']} | "
            f"{row['hybrid_prf']} | {row['hybrid_fp']} | {row['index_fp']} | {row['insufficient']} |"
        )
    lines += [
        "",
        f"- broad UI FP improved on all compared queries: {broad['fp_improved']}",
        "",
        "## Expansion to 35 queries",
        "",
        f"- ran all 35: {expand['ran_all']}",
        f"- reason: {expand['reason']}",
        "",
        "## Usage",
        "",
        f"- requests: {report['usage']['request_count']}",
        f"- input tokens: {report['usage']['input_tokens']}",
        f"- output tokens: {report['usage']['output_tokens']}",
        f"- estimated USD: {report['usage']['estimated_usd']:.4f}",
        f"- api seconds: {report['usage']['api_seconds']:.1f}",
        "",
        "Details: `evidence-text-analysis.md`",
        "",
    ]
    if report.get("all35"):
        all_text = report["all35"]["text_only"]["all"]
        all_replay = report["all35"]["replay"]["all"]
        lines += [
            "## All 35 queries",
            "",
            f"- Text-only macro P/R/F1: {all_text['macro_precision']:.3f}/"
            f"{all_text['macro_recall']:.3f}/{all_text['macro_f1']:.3f}",
            f"- Replay macro P/R/F1: {all_replay['macro_precision']:.3f}/"
            f"{all_replay['macro_recall']:.3f}/{all_replay['macro_f1']:.3f}",
            f"- mean Vision fallback: {all_replay['mean_vision_sent']:.1f}",
            "",
        ]
    return "\n".join(lines) + "\n"


def render_analysis(report: dict) -> str:
    focus = report["focus"]["text_only"]["all"]
    replay = report["focus"]["replay"]["all"]
    routing = focus["routing"]
    coverage = focus["coverage"]
    expand = report["expansion"]
    nested = report["nested_dogs"]
    chrome = report["chrome"]
    broad = report["broad_ui"]
    verdict = report["verdict"]
    lines = [
        "# Semantic Index Evidence Text ternary analysis",
        "",
        "Eval-only. Product search / OpenCLIP / matcher / Hybrid / GT v2 / Index v4 generation were not changed.",
        "No confidence-threshold sweep. The Text AI `decision` is used as-is.",
        "",
        "## Decision",
        "",
        f"**{verdict['label']}** as next Meaning Search candidate.",
        "",
        verdict["why"],
        "",
        "## What ran",
        "",
        f"* Model: `{report['model']['model']}`",
        f"* Endpoint: `{report['model']['endpoint']}`",
        f"* temperature: `{report['model']['temperature']}`",
        f"* structured output: json_schema strict `{report['model']['schema_version']}`",
        f"* prompt: `{report['model']['prompt_version']}`",
        f"* batch_size: {report['model']['batch_size']}, max_workers: {report['model']['max_workers']}",
        f"* Index cache: `{report['model']['index_cache']}`",
        f"* Images sent to the Text API: 0. Evidence text only.",
        "",
        "## Contract",
        "",
        "* `relevant` only when Index evidence reasonably confirms every independent query condition",
        "* `irrelevant` only when evidence rules a required condition out",
        "* otherwise `insufficient_evidence` (unknown != false)",
        "* short queries match identifiable presence, including nested/thumbnail",
        "* compound queries AND the extra independent conditions",
        "",
        "## Focus metrics",
        "",
        f"Text-only (predicted=`relevant`) macro P/R/F1 "
        f"**{focus['macro_precision']:.3f} / {focus['macro_recall']:.3f} / {focus['macro_f1']:.3f}**",
        f"(micro TP/FP/FN {focus['micro_tp']} / {focus['micro_fp']} / {focus['micro_fn']})",
        "",
        "Routing of GT labels:",
        "",
        f"* GT+ → relevant {routing['gt_positive_relevant']}",
        f"* GT+ → insufficient {routing['gt_positive_insufficient']} (Vision-recoverable)",
        f"* GT+ → irrelevant {routing['gt_positive_irrelevant']} (**worst**)",
        f"* GT− → relevant {routing['gt_negative_relevant']}",
        f"* GT− → insufficient {routing['gt_negative_insufficient']}",
        f"* GT− → irrelevant {routing['gt_negative_irrelevant']}",
        "",
        f"Mean insufficient rate {coverage['mean_insufficient_rate']:.3f}; "
        f"mean Vision fallback {coverage['mean_vision_fallback']:.1f}/query vs Hybrid C {HYBRID_MEAN_VISION:.1f}.",
        "",
        "## Nested dogs",
        "",
    ]
    for row in nested:
        lines.append(
            f"* `{row['name']}`: Index `{row['index_class']}`, Text `{row['text_decision']}`, "
            f"class `{row['outcome']}`. reason: {row.get('text_reason') or ''}"
        )
    lines += [
        "",
        "These three are GT positives for `dog` because nested/gallery thumbnails are identifiable.",
        "If Index never named a dog, Text should say insufficient, not irrelevant.",
        "",
        "## Chrome",
        "",
        f"* short `Google Chrome` relevant count: {chrome['short_relevant']}",
        f"* compound `Google Chrome in Windows desktop` relevant count: {chrome['compound_relevant']}",
        f"* short-only: {', '.join(f'`{name}`' for name in chrome['short_only_relevant']) or '(none)'}",
        f"* compound-only: {', '.join(f'`{name}`' for name in chrome['compound_only_relevant']) or '(none)'}",
        f"* distinction holds: {chrome['distinction_holds']}",
        "",
        "## Broad UI",
        "",
    ]
    for row in broad["queries"]:
        lines.append(
            f"* `{row['query']}`: Text FP {row['text_fp']} vs Hybrid {row['hybrid_fp']} vs Index-only {row['index_fp']}"
        )
    lines += [
        "",
        "## Replay E2E",
        "",
        f"Text `relevant` plus existing Vision Judge on `insufficient_evidence` only: "
        f"macro P/R/F1 {replay['macro_precision']:.3f} / {replay['macro_recall']:.3f} / {replay['macro_f1']:.3f}.",
        f"Hybrid C remains 0.812 / 0.769 / 0.790 on all 35.",
        "",
        "## Expansion",
        "",
        f"* ran all 35: {expand['ran_all']}",
        f"* reason: {expand['reason']}",
        "",
        "## Next smallest task",
        "",
        verdict["next"],
        "",
    ]
    if report.get("all35"):
        all_text = report["all35"]["text_only"]["all"]
        all_replay = report["all35"]["replay"]["all"]
        all_routing = all_text["routing"]
        lines += [
            "## All 35",
            "",
            f"Text-only macro P/R/F1 {all_text['macro_precision']:.3f} / "
            f"{all_text['macro_recall']:.3f} / {all_text['macro_f1']:.3f}.",
            f"Replay macro P/R/F1 {all_replay['macro_precision']:.3f} / "
            f"{all_replay['macro_recall']:.3f} / {all_replay['macro_f1']:.3f}.",
            f"GT+ → irrelevant {all_routing['gt_positive_irrelevant']}; "
            f"GT− → relevant {all_routing['gt_negative_relevant']}.",
            f"mean Vision {all_replay['mean_vision_sent']:.1f}/query.",
            "",
        ]
    return "\n".join(lines)


def _verdict(report_partial: dict) -> dict:
    focus = report_partial["focus"]["text_only"]["all"]
    replay = report_partial["focus"]["replay"]["all"]
    routing = focus["routing"]
    coverage = focus["coverage"]
    chrome = report_partial["chrome"]
    nested = report_partial["nested_dogs"]
    expand = report_partial["expansion"]
    nested_bad = [
        row for row in nested
        if row["outcome"] in {"evidence_gap_treated_as_negative", "evidence_present_text_failed"}
    ]
    pos_irr = routing["gt_positive_irrelevant"]
    mean_ins = coverage["mean_insufficient_rate"]
    mean_vis = coverage["mean_vision_fallback"]
    replay_f1 = replay.get("macro_f1") or 0.0
    if pos_irr >= 8 and mean_ins < 0.3:
        return {
            "label": "NO-GO",
            "why": (
                f"Text still converts Index silence into negatives "
                f"({pos_irr} GT+ → irrelevant). unknown!=false is not holding."
            ),
            "next": "Stop this design. Do not change product Hybrid. Inspect the pos→irrelevant cases.",
        }
    if mean_ins > 0.85:
        return {
            "label": "NO-GO",
            "why": (
                f"Almost every pair is insufficient ({mean_ins:.0%}). "
                "Text is not a useful first-stage filter."
            ),
            "next": "Stop. Index evidence is too thin for this judge, or the prompt refuses to settle.",
        }
    if nested_bad and all(row["outcome"] == "evidence_gap_treated_as_negative" for row in nested_bad):
        return {
            "label": "NO-GO",
            "why": (
                "Nested dog GT positives were marked irrelevant because Index omitted the dog. "
                "That is the Hybrid clear-negative FN failure mode again."
            ),
            "next": "Keep insufficient as the required behavior for Index gaps; do not productize this prompt.",
        }
    promising = (
        pos_irr <= 3
        and mean_vis < HYBRID_MEAN_VISION
        and (chrome.get("distinction_holds") or replay_f1 >= 0.75)
    )
    if promising and expand.get("ran_all"):
        all_replay = (report_partial.get("all35") or {}).get("replay", {}).get("all") or {}
        all_f1 = all_replay.get("macro_f1") or 0.0
        if all_f1 >= 0.79 and (all_replay.get("mean_vision_sent") or 99) <= HYBRID_MEAN_VISION:
            return {
                "label": "CONDITIONAL GO",
                "why": (
                    "Focus contract checks passed and 35-query replay is at least Hybrid-competitive "
                    "with equal or lower Vision load. Still eval-only; do not wire into product yet."
                ),
                "next": "Review pos→irrelevant leftovers and a small live Vision fallback on insufficient only.",
            }
        return {
            "label": "CONDITIONAL GO",
            "why": (
                "Focus set shows the contract can hold: Index is evidence, silence is insufficient, "
                "and Vision load is lower than Hybrid C. Full 35 was run because the focus set looked viable."
            ),
            "next": "Read the 35-query pos→irrelevant and broad UI leftovers before any product wiring.",
        }
    if promising:
        return {
            "label": "CONDITIONAL GO",
            "why": (
                "Focus set keeps unknown!=false, distinguishes Chrome short vs compound, "
                f"and would send {mean_vis:.1f} images/query to Vision vs Hybrid 32."
            ),
            "next": "Expand the same PoC to all 35 GT v2 queries without changing prompts.",
        }
    return {
        "label": "INCONCLUSIVE / pause",
        "why": (
            "Some contract behavior is present, but precision, nested-dog handling, "
            "or Vision load is not yet a clear win over frozen Hybrid C."
        ),
        "next": "Do not productize. Inspect remaining pos→irrelevant and whether Index v4 omits the needed facts.",
    }


def _usage_from_run(run) -> dict:
    usage = empty_usage()
    usage.update({
        "request_count": int(run.request_count),
        "request_attempt_count": int(run.request_attempt_count),
        "retry_count": int(run.retry_count),
        "input_tokens": int(run.input_tokens),
        "output_tokens": int(run.output_tokens),
        "api_seconds": float(run.api_seconds),
        "total_seconds": float(run.total_seconds),
        "sent_image_count": 0,
    })
    return usage


def _judge_query(
    *,
    spec: QuerySpec,
    paths: list[Path],
    evidence_by_image_id: dict[int, dict],
    provider: EvidenceTextJudgeProvider,
    checkpoint_row: dict | None,
) -> tuple[dict[str, dict], dict]:
    if checkpoint_row and checkpoint_row.get("decisions"):
        return checkpoint_row["decisions"], dict(checkpoint_row.get("usage") or empty_usage())
    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    run = provider.judge(spec.query, images)
    decisions = {}
    for item, result in zip(images, run.results):
        decisions[item.path.name] = {
            "name": item.path.name,
            "image_id": item.image_id,
            "decision": result.decision,
            "confidence": result.confidence,
            "short_reason": result.short_reason,
            "missing_evidence": result.missing_evidence,
            "unknown_reason": result.unknown_reason,
        }
    return decisions, _usage_from_run(run)


def _select_queries(dataset, stage: str, query_filter: list[str] | None) -> list[QuerySpec]:
    if query_filter:
        return [dataset.spec(query) for query in query_filter]
    if stage == "focus":
        return [dataset.spec(query) for query in FOCUS_QUERIES]
    return list(dataset.queries)


CHROME_NAME_RE = re.compile(r"\bgoogle chrome\b", re.IGNORECASE)
CHROME_FALSE_FRIEND_RE = re.compile(r"browser chrome|toolbar chrome|ui chrome", re.IGNORECASE)
DESKTOP_ENV_RE = re.compile(
    r"windows desktop|desktop wallpaper|taskbar|desktop icons|wallpaper and (?:taskbar|icons)",
    re.IGNORECASE,
)
DESKTOP_APP_RE = re.compile(r"desktop app|desktop application|desktop software", re.IGNORECASE)


def _has_google_chrome(record: dict) -> dict:
    identities = [
        item for item in (record.get("identities") or [])
        if isinstance(item, dict) and CHROME_NAME_RE.search(str(item.get("name") or ""))
    ]
    text = flatten_index_text(record)
    text_hit = bool(CHROME_NAME_RE.search(text))
    false_friend = bool(CHROME_FALSE_FRIEND_RE.search(text)) and not text_hit and not identities
    return {
        "identity": bool(identities),
        "text": text_hit,
        "false_friend_only": false_friend,
        "identity_names": [str(item.get("name")) for item in identities],
        "identity_confidence": [str(item.get("confidence")) for item in identities],
        "identity_importance": [str(item.get("importance")) for item in identities],
    }


def _has_windows_desktop_env(record: dict) -> dict:
    text = flatten_index_text(record)
    env_hit = bool(DESKTOP_ENV_RE.search(text))
    app_only = bool(DESKTOP_APP_RE.search(text)) and not env_hit
    ui = [str(item).lower() for item in (record.get("ui_interface_concepts") or [])]
    desktop_ui = "desktop" in ui
    return {
        "environment_text": env_hit,
        "desktop_ui_concept": desktop_ui,
        "desktop_app_only": app_only,
        "likely_environment": env_hit or (desktop_ui and not app_only),
    }


def build_index_capability_report(
    dataset,
    index_by_name: dict[str, dict],
    names: list[str],
) -> dict:
    nested = []
    for name in NESTED_DOG_IMAGES:
        info = classify_nested_dog_index(index_by_name.get(name))
        nested.append({
            "name": name,
            "gt_positive_for_dog": name in dataset.spec("dog").must_include_set,
            **info,
            "expected_text_if_contract_holds": (
                "insufficient_evidence"
                if info["index_class"] != "index_has_dog"
                else "relevant"
            ),
        })
    chrome_rows = []
    for name in names:
        record = index_by_name[name]
        chrome = _has_google_chrome(record)
        desktop = _has_windows_desktop_env(record)
        chrome_rows.append({
            "name": name,
            "gt_chrome": name in dataset.spec("Google Chrome").must_include_set,
            "gt_chrome_desktop": name in dataset.spec(
                "Google Chrome in Windows desktop"
            ).must_include_set,
            **{f"chrome_{k}": v for k, v in chrome.items()},
            **{f"desktop_{k}": v for k, v in desktop.items()},
        })
    chrome_identity = {row["name"] for row in chrome_rows if row["chrome_identity"]}
    chrome_text = {row["name"] for row in chrome_rows if row["chrome_text"]}
    desktop_env = {row["name"] for row in chrome_rows if row["desktop_likely_environment"]}
    both = chrome_identity & desktop_env
    gt_chrome = dataset.spec("Google Chrome").must_include_set
    gt_compound = dataset.spec("Google Chrome in Windows desktop").must_include_set
    broad = {}
    for query in BROAD_UI_QUERIES:
        spec = dataset.spec(query)
        token = query.lower()
        hits = []
        for name in names:
            text = flatten_index_text(index_by_name[name]).lower()
            if token in text or all(part in text for part in token.split() if part != "in"):
                hits.append(name)
        broad[query] = {
            "gt_positive": sorted(spec.must_include),
            "index_phrase_or_token_hits": hits,
            "hit_count": len(hits),
            "gt_hit": sorted(set(hits) & spec.must_include_set),
            "gt_miss": sorted(spec.must_include_set - set(hits)),
            "non_gt_hits": sorted(set(hits) - spec.must_include_set - spec.acceptable_set),
        }
    return {
        "nested_dogs": nested,
        "chrome": {
            "identity_count": len(chrome_identity),
            "text_count": len(chrome_text),
            "desktop_env_count": len(desktop_env),
            "identity_and_desktop_env": sorted(both),
            "identity_not_desktop": sorted(chrome_identity - desktop_env),
            "gt_chrome_with_identity": sorted(gt_chrome & chrome_identity),
            "gt_chrome_missing_identity": sorted(gt_chrome - chrome_identity),
            "gt_compound_with_both": sorted(gt_compound & both),
            "gt_compound_missing_both": sorted(gt_compound - both),
            "rows": chrome_rows,
            "distinction_possible_from_index": bool(chrome_identity - both) or bool(both),
        },
        "broad_ui": broad,
    }


def render_index_capability_markdown(report: dict) -> str:
    nested = report["nested_dogs"]
    chrome = report["chrome"]
    lines = [
        "# Semantic Index v4 evidence capability (no Text AI)",
        "",
        "This is not a ternary judgement. It only records whether Index v4 already",
        "contains the facts a later Text AI would need. Product code was not changed.",
        "",
        "## Nested dogs",
        "",
        "| image | GT+ dog | index class | dog mention | animal mention | expected if unknown!=false |",
        "|---|---|---|---|---|---|",
    ]
    for row in nested:
        lines.append(
            f"| `{row['name']}` | {row['gt_positive_for_dog']} | {row['index_class']} | "
            f"{row['dog_mention']} | {row['animal_mention']} | `{row['expected_text_if_contract_holds']}` |"
        )
    lines += [
        "",
        "If Text AI marks these `irrelevant` because the Index omitted the dog, that is",
        "the Hybrid clear-negative FN failure mode. The contract requires `insufficient_evidence`.",
        "",
        "## Chrome vs Chrome in Windows desktop",
        "",
        f"- Google Chrome identity rows: {chrome['identity_count']}",
        f"- Google Chrome text mentions: {chrome['text_count']}",
        f"- likely Windows desktop environment: {chrome['desktop_env_count']}",
        f"- identity AND desktop env: {len(chrome['identity_and_desktop_env'])}",
        f"- identity without desktop env: {len(chrome['identity_not_desktop'])}",
        f"- GT Chrome with identity: {len(chrome['gt_chrome_with_identity'])} / "
        f"{len(chrome['gt_chrome_with_identity']) + len(chrome['gt_chrome_missing_identity'])}",
        f"- GT compound with both: {len(chrome['gt_compound_with_both'])} / "
        f"{len(chrome['gt_compound_with_both']) + len(chrome['gt_compound_missing_both'])}",
        f"- distinction possible from Index facts: {chrome['distinction_possible_from_index']}",
        "",
        "Short query can use Chrome identity alone. Compound query needs desktop environment",
        "plus the in-desktop relation. Index silence on wallpaper/taskbar must not become `irrelevant`.",
        "",
        "## Broad UI lexical coverage in Index",
        "",
        "| query | GT+ | Index token hits | GT hit | GT miss | non-GT hits |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for query, row in report["broad_ui"].items():
        lines.append(
            f"| `{query}` | {len(row['gt_positive'])} | {row['hit_count']} | "
            f"{len(row['gt_hit'])} | {len(row['gt_miss'])} | {len(row['non_gt_hits'])} |"
        )
    lines += [
        "",
        "High non-GT hits are why Index-only / lexical Hybrid FP is large. Text AI must read",
        "the whole evidence document instead of token overlap.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence Text ternary Meaning PoC")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stage", choices=("focus", "all", "auto"), default="auto")
    parser.add_argument("--queries", nargs="+")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    parser.add_argument(
        "--index-report-only",
        action="store_true",
        help="Write Index evidence capability report without calling Text AI.",
    )
    args = parser.parse_args()

    dataset = load_dataset(args.gt)
    folder = args.folder
    paths = list_images(folder)
    if not paths:
        raise SystemExit(f"no images in {folder}")
    cached = load_index_cache(args.index_cache)
    if cached is None:
        raise SystemExit(f"missing Semantic Index v4 cache: {args.index_cache}")
    index_by_name, _index_usage = cached
    names_in_index = [path for path in paths if path.name in index_by_name]
    extra_folder = [path.name for path in paths if path.name not in index_by_name]
    if extra_folder:
        print(
            f"ignoring {len(extra_folder)} folder images not in Index v4 cache",
            flush=True,
        )
    paths = names_in_index
    if len(paths) != 119:
        raise SystemExit(
            f"expected 119 Index v4 images present in folder, found {len(paths)}"
        )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.jsonl"
    decisions_path = output_dir / "decisions.jsonl"
    checkpoint = _load_checkpoint(checkpoint_path) if args.resume else {}

    images = [RelevanceImage(index, path) for index, path in enumerate(paths, 1)]
    evidence_by_image_id = {
        item.image_id: index_by_name[item.path.name] for item in images
    }
    names = [path.name for path in paths]
    index_capability = build_index_capability_report(dataset, index_by_name, names)
    (output_dir / "index-capability.json").write_text(
        json.dumps(index_capability, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "index-capability.md").write_text(
        render_index_capability_markdown(index_capability),
        encoding="utf-8",
    )
    if args.index_report_only:
        print(render_index_capability_markdown(index_capability))
        print(f"wrote {output_dir} (index report only)")
        return 0
    provider = EvidenceTextJudgeProvider(
        evidence_by_image_id=evidence_by_image_id,
        model=args.model,
        batch_size=args.batch_size,
        max_workers=args.max_workers,
        temperature=0,
        timeout_seconds=120,
        retries=2,
    )

    hybrid_payload = _json_load(HYBRID_RESULTS)
    judge_payload = _json_load(JUDGE_RESULTS)
    index_payload = _json_load(INDEX_ONLY_RESULTS)
    hybrid_by_query = _rows_by_query(hybrid_payload, path=("query_rows", "C"))
    if not hybrid_by_query:
        hybrid_by_query = _rows_by_query(
            ((hybrid_payload or {}).get("methods") or {}).get("C"),
            path=("all", "queries"),
        )
    judge_by_query = {
        row["query"]: row
        for row in ((judge_payload or {}).get("end_to_end") or {}).get("queries") or []
    }
    index_by_query = _rows_by_query(
        ((index_payload or {}).get("methods") or {}).get("B_v4") or index_payload,
        path=("all", "queries"),
    )
    if not index_by_query:
        index_by_query = {
            row["query"]: row
            for row in ((index_payload or {}).get("queries") or [])
            if isinstance(row, dict) and "query" in row
        }

    total_usage = empty_usage()
    started = time.perf_counter()

    def write_blocked(reason: str) -> int:
        git = git_identity()
        corpus = corpus_identity(paths)
        blocked = {
            "identity": {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "git_commit": git["git_commit"],
                "git_dirty": git["git_dirty"],
                "query_set_version": dataset.query_set_version,
                "query_set_hash": dataset.query_set_hash,
                "gt_version": dataset.gt_version,
                "gt_hash": dataset.gt_hash,
                "index_prompt_version": INDEX_PROMPT_VERSION,
                "index_schema_version": INDEX_SCHEMA_VERSION,
                "corpus_count": corpus["count"],
                "corpus_sha256": corpus["names_sizes_sha256"],
            },
            "blocked": True,
            "block_reason": reason,
            "model": {
                "model": args.model,
                "endpoint": "https://api.openai.com/v1/chat/completions",
                "temperature": 0,
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "images_attached": False,
                "threshold_sweep": False,
            },
            "index_capability": {
                "nested_dogs": index_capability["nested_dogs"],
                "chrome_summary": {
                    key: index_capability["chrome"][key]
                    for key in index_capability["chrome"]
                    if key != "rows"
                },
                "broad_ui": {
                    query: {
                        k: v for k, v in row.items()
                        if k != "index_phrase_or_token_hits"
                    }
                    for query, row in index_capability["broad_ui"].items()
                },
            },
            "hybrid_c_reference": {
                "macro_precision": 0.812,
                "macro_recall": 0.769,
                "macro_f1": 0.790,
                "mean_vision_sent": HYBRID_MEAN_VISION,
            },
            "verdict": {
                "label": "BLOCKED",
                "why": reason,
                "next": (
                    "Add OpenAI credits for the existing gpt-5.4-mini Text path, "
                    "then rerun tools/meaning_eval/evaluate_evidence_text.py "
                    "--stage auto. Do not change product Hybrid meanwhile."
                ),
            },
        }
        (output_dir / "results.json").write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary = "\n".join([
            "# Semantic Index Evidence Text ternary PoC",
            "",
            "## BLOCKED",
            "",
            reason,
            "",
            "Text AI ternary metrics were not computed. Index evidence capability is in",
            "`index-capability.md`. The eval harness is ready and does not change product code.",
            "",
            "Re-run after credits:",
            "",
            "```",
            ".\\.build-venv\\Scripts\\python.exe tools\\meaning_eval\\evaluate_evidence_text.py --stage auto",
            "```",
            "",
        ])
        (output_dir / "summary.md").write_text(summary, encoding="utf-8")
        (output_dir / "evidence-text-analysis.md").write_text(
            "\n".join([
                "# Semantic Index Evidence Text ternary analysis",
                "",
                "## BLOCKED",
                "",
                reason,
                "",
                "No Text AI decisions were written. See `index-capability.md` for nested dog,",
                "Chrome, and broad UI Index facts.",
                "",
            ]),
            encoding="utf-8",
        )
        print(summary)
        print(f"wrote {output_dir}")
        return 2

    def run_specs(specs: list[QuerySpec]) -> dict[str, dict]:
        decisions_by_query: dict[str, dict] = {}
        for spec in specs:
            cached_row = checkpoint.get(spec.query)
            decisions, usage = _judge_query(
                spec=spec,
                paths=paths,
                evidence_by_image_id=evidence_by_image_id,
                provider=provider,
                checkpoint_row=cached_row,
            )
            add_usage(total_usage, usage)
            row = {
                "query": spec.query,
                "split": spec.split,
                "kind": spec.kind,
                "decisions": decisions,
                "usage": usage,
            }
            checkpoint[spec.query] = row
            _rewrite_checkpoint(checkpoint_path, checkpoint)
            decisions_by_query[spec.query] = decisions
            print(
                f"{spec.query}: relevant="
                f"{sum(1 for item in decisions.values() if item['decision']=='relevant')} "
                f"irrelevant="
                f"{sum(1 for item in decisions.values() if item['decision']=='irrelevant')} "
                f"insufficient="
                f"{sum(1 for item in decisions.values() if item['decision']=='insufficient_evidence')}",
                flush=True,
            )
        return decisions_by_query

    focus_specs = _select_queries(dataset, "focus", args.queries)
    if args.stage == "all" and not args.queries:
        focus_specs = list(dataset.queries)
    try:
        decisions_by_query = run_specs(focus_specs)
    except QuotaExhaustedError as exc:
        return write_blocked(
            "OpenAI API credit_balance_exhausted on the existing gpt-5.4-mini Text path. "
            f"Detail: {exc}"
        )

    def pack_stage(specs: list[QuerySpec], local_decisions: dict[str, dict]) -> dict:
        text_rows = [
            _text_only_row(spec, local_decisions[spec.query], names) for spec in specs
        ]
        replay_rows = []
        for spec in specs:
            vision_predicted = set((judge_by_query.get(spec.query) or {}).get("predicted") or [])
            replay_rows.append(
                _replay_row(spec, local_decisions[spec.query], names, vision_predicted)
            )
        return {
            "text_only": {
                "all": _summarize_text_rows(text_rows),
                "dev": _summarize_text_rows(_split_rows(text_rows, "dev")),
                "holdout": _summarize_text_rows(_split_rows(text_rows, "holdout")),
                "rows": text_rows,
            },
            "replay": {
                "all": _summarize_replay_rows(replay_rows),
                "dev": _summarize_replay_rows(_split_rows(replay_rows, "dev")),
                "holdout": _summarize_replay_rows(_split_rows(replay_rows, "holdout")),
                "rows": replay_rows,
            },
        }

    focus_pack = pack_stage(focus_specs, decisions_by_query)
    chrome = _chrome_view(dataset, decisions_by_query, names)
    broad_ui = _broad_ui_view(
        dataset,
        focus_pack["text_only"]["rows"],
        hybrid_by_query,
        index_by_query,
    )
    nested = _nested_dog_view(dataset, index_by_name, decisions_by_query)
    ran_all = args.stage == "all" and not args.queries
    expand_ok, expand_reason = _should_expand_all(
        focus_pack["text_only"]["all"], chrome, broad_ui
    )
    all_pack = None
    if args.stage == "auto" and not args.queries and expand_ok:
        remaining = [spec for spec in dataset.queries if spec.query not in decisions_by_query]
        try:
            extra = run_specs(remaining)
        except QuotaExhaustedError as exc:
            return write_blocked(
                "OpenAI API credit_balance_exhausted after the focus set. "
                f"Detail: {exc}"
            )
        decisions_by_query.update(extra)
        all_pack = pack_stage(list(dataset.queries), decisions_by_query)
        ran_all = True
        expand_reason = f"auto-expanded: {expand_reason}"
    elif args.stage == "all" and not args.queries:
        all_pack = focus_pack
        ran_all = True
        expand_reason = "requested --stage all"
    elif args.queries:
        expand_reason = "query filter; 35-query expansion skipped"
    else:
        expand_reason = f"stopped after focus: {expand_reason}"

    if all_pack is None and ran_all:
        all_pack = pack_stage(list(dataset.queries), decisions_by_query)

    decisions_path.write_text("", encoding="utf-8")
    for query, decisions in decisions_by_query.items():
        spec = dataset.spec(query)
        for name, item in decisions.items():
            _append_jsonl(decisions_path, {
                "query": query,
                "split": spec.split,
                "kind": spec.kind,
                "gt_label": _gt_label(spec, name),
                **item,
            })

    git = git_identity()
    corpus = corpus_identity(paths)
    total_usage["total_seconds"] = time.perf_counter() - started
    total_usage["estimated_usd"] = estimate_usd(
        int(total_usage["input_tokens"]), int(total_usage["output_tokens"])
    )
    report = {
        "identity": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_commit": git["git_commit"],
            "git_dirty": git["git_dirty"],
            "query_set_version": dataset.query_set_version,
            "query_set_hash": dataset.query_set_hash,
            "gt_version": dataset.gt_version,
            "gt_hash": dataset.gt_hash,
            "index_prompt_version": INDEX_PROMPT_VERSION,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "corpus_count": corpus["count"],
            "corpus_sha256": corpus["names_sizes_sha256"],
        },
        "model": {
            "model": provider.model,
            "endpoint": provider.endpoint,
            "temperature": provider.temperature,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "batch_size": provider.batch_size,
            "max_workers": provider.max_workers,
            "index_cache": str(args.index_cache),
            "images_attached": False,
            "threshold_sweep": False,
        },
        "stage": "all35" if ran_all else "focus",
        "focus": focus_pack if not (ran_all and args.stage == "all" and not args.queries) else all_pack,
        "all35": all_pack,
        "chrome": chrome,
        "broad_ui": broad_ui,
        "nested_dogs": nested,
        "expansion": {
            "ran_all": ran_all,
            "reason": expand_reason,
            "criteria_ok": expand_ok,
        },
        "usage": total_usage,
        "folder": str(folder),
        "hybrid_c_reference": {
            "macro_precision": 0.812,
            "macro_recall": 0.769,
            "macro_f1": 0.790,
            "mean_vision_sent": HYBRID_MEAN_VISION,
        },
        "sample_evidence": {
            name: format_index_evidence(index_by_name[name])
            for name in NESTED_DOG_IMAGES
            if name in index_by_name
        },
    }
    if args.stage == "all" and not args.queries:
        report["focus"] = pack_stage(
            [dataset.spec(query) for query in FOCUS_QUERIES],
            decisions_by_query,
        )
        report["all35"] = all_pack
    report["verdict"] = _verdict(report)
    (output_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(render_summary(report), encoding="utf-8")
    (output_dir / "evidence-text-analysis.md").write_text(
        render_analysis(report), encoding="utf-8"
    )
    print(render_summary(report))
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
