"""Compare describe-judge-v1 smoke/full runs with a Phase D baseline results.json.

Eval-only. Does not call the Vision API or change product search.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "artifacts" / "meaning-eval" / "latest" / "results.json"
SMOKE_QUERIES = (
    "dog",
    "cat",
    "anime",
    "Windows desktop screenshot",
    "desktop with application windows",
    "settings screen",
    "mountain desktop wallpaper",
    "code editor",
)
UI_QUERIES = {
    "Windows desktop screenshot",
    "desktop with application windows",
    "settings screen",
    "code editor",
}
NOISE_QUERIES = {
    "Windows desktop screenshot",
    "desktop with application windows",
    "settings screen",
}
OBJECT_QUERIES = ("dog", "cat", "anime")
QUERY_STOPWORDS = {"a", "an", "the", "with", "of", "and", "or", "to", "for", "in", "on"}
MOUNTAIN_NAMES = (
    "20260718_202718.png",
    "20260718_202724.png",
    "20260718_203016.png",
)
MOUNTAIN_HINTS = (
    "mountain", "snow", "lake", "shore", "wallpaper", "desktop",
    "background", "landscape", "peak", "hill",
)


def _rows(report: dict) -> dict[str, dict]:
    return {
        row["query"]: row
        for row in (report.get("end_to_end") or {}).get("queries") or []
    }


def _load_judgements(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[row["query"]] = row
    return rows


def _load_descriptions(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload.get("by_name") or {})


def _vision(item: dict) -> dict:
    return item.get("vision") or {}


def _desc_text(description: dict | None) -> str:
    if not description:
        return ""
    return " ".join(
        str(description.get(name) or "")
        for name in (
            "primary_subject",
            "visual_contents",
            "presentation",
            "prominent_elements",
            "primary_vs_background",
        )
    )


def _hint_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [hint for hint in MOUNTAIN_HINTS if hint in lowered]


def _query_tokens(query: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if token not in QUERY_STOPWORDS and len(token) > 1
    ]


def _description_hits(description: dict | None, query: str) -> list[str]:
    text = _desc_text(description).lower()
    return [token for token in _query_tokens(query) if token in text]


def _inconsistency(judgement: dict | None) -> str | None:
    if not judgement or judgement.get("relevant") is None:
        return None
    score = judgement.get("relevance_score")
    if score is None:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    relevant = judgement.get("relevant")
    if relevant is True and score < 0.2:
        return "relevant_true_low_score"
    if relevant is False and score > 0.8:
        return "relevant_false_high_score"
    return None


def _compare_query(query: str, before: dict | None, after: dict | None) -> dict:
    def counts(row: dict | None) -> dict:
        if row is None:
            return {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None}
        return {
            "tp": int(row["tp"]),
            "fp": int(row["fp"]),
            "fn": int(row["fn"]),
            "precision": row["precision"],
            "recall": row["recall"],
            "split": row.get("split"),
            "kind": row.get("kind"),
        }

    left = counts(before)
    right = counts(after)
    return {
        "query": query,
        "split": (after or before or {}).get("split"),
        "kind": (after or before or {}).get("kind"),
        "before": left,
        "after": right,
        "delta_fp": None if left["fp"] is None or right["fp"] is None else right["fp"] - left["fp"],
        "delta_fn": None if left["fn"] is None or right["fn"] is None else right["fn"] - left["fn"],
        "delta_tp": None if left["tp"] is None or right["tp"] is None else right["tp"] - left["tp"],
    }


def _fp_items(row: dict | None) -> list[dict]:
    return list((row or {}).get("false_positives") or [])


def _fn_items(row: dict | None) -> list[dict]:
    return list((row or {}).get("false_negatives") or [])


def analyze(
    *,
    baseline: dict,
    current: dict,
    descriptions: dict[str, dict],
    judgements: dict[str, dict],
    queries: tuple[str, ...] = SMOKE_QUERIES,
) -> dict:
    before_rows = _rows(baseline)
    after_rows = _rows(current)
    per_query = [
        _compare_query(query, before_rows.get(query), after_rows.get(query))
        for query in queries
        if query in before_rows or query in after_rows
    ]
    ui_fp_before = sum(item["before"]["fp"] or 0 for item in per_query if item["query"] in UI_QUERIES)
    ui_fp_after = sum(item["after"]["fp"] or 0 for item in per_query if item["query"] in UI_QUERIES)
    fn_before = sum(item["before"]["fn"] or 0 for item in per_query)
    fn_after = sum(item["after"]["fn"] or 0 for item in per_query)
    object_ok = True
    object_notes = []
    for query in OBJECT_QUERIES:
        item = next((row for row in per_query if row["query"] == query), None)
        if item is None or item["after"]["fn"] is None:
            continue
        if item["after"]["fn"] > 0 or (item["after"]["fp"] or 0) > (item["before"]["fp"] or 0):
            object_ok = False
            object_notes.append(item)

    ui_fp_cases = []
    for query in UI_QUERIES:
        after = after_rows.get(query)
        before = before_rows.get(query)
        after_fp = {item["name"]: item for item in _fp_items(after)}
        before_fp = {item["name"]: item for item in _fp_items(before)}
        fixed = sorted(set(before_fp) - set(after_fp))
        remaining = sorted(set(after_fp) & set(before_fp))
        new_fp = sorted(set(after_fp) - set(before_fp))
        samples = []
        for name in remaining[:12] + fixed[:8] + new_fp[:8]:
            judgement = ((judgements.get(query) or {}).get("judgements") or {}).get(name)
            description = (
                (judgement or {}).get("description")
                or _vision(after_fp.get(name) or before_fp.get(name) or {}).get("description")
                or descriptions.get(name)
            )
            after_item = after_fp.get(name)
            samples.append({
                "name": name,
                "status": (
                    "remaining_fp" if name in after_fp and name in before_fp else
                    "fixed" if name in before_fp else "new_fp"
                ),
                "baseline_score": _vision(before_fp.get(name) or {}).get("relevance_score"),
                "baseline_reason": _vision(before_fp.get(name) or {}).get("reason"),
                "candidate_relevant": None if after_item is None else _vision(after_item).get("relevant"),
                "candidate_score": None if judgement is None else judgement.get("relevance_score"),
                "candidate_confidence": None if judgement is None else judgement.get("confidence"),
                "candidate_reason": None if judgement is None else judgement.get("reason"),
                "description": description,
            })
        ui_fp_cases.append({
            "query": query,
            "before_fp": 0 if before is None else int(before["fp"]),
            "after_fp": 0 if after is None else int(after["fp"]),
            "fixed": len(fixed),
            "remaining": len(remaining),
            "new_fp": len(new_fp),
            "samples": samples,
        })

    mountain_after = after_rows.get("mountain desktop wallpaper")
    mountain_before = before_rows.get("mountain desktop wallpaper")
    mountain_judgements = (judgements.get("mountain desktop wallpaper") or {}).get("judgements") or {}
    mountain = []
    for name in MOUNTAIN_NAMES:
        judgement = mountain_judgements.get(name)
        description = (
            None if judgement is None else judgement.get("description")
        ) or descriptions.get(name)
        text = _desc_text(description)
        mountain.append({
            "name": name,
            "baseline_fn": name in set(mountain_before.get("fn_names") or []) if mountain_before else None,
            "candidate_relevant": None if judgement is None else judgement.get("relevant"),
            "candidate_score": None if judgement is None else judgement.get("relevance_score"),
            "candidate_confidence": None if judgement is None else judgement.get("confidence"),
            "candidate_reason": None if judgement is None else judgement.get("reason"),
            "description": description,
            "hint_hits": _hint_hits(text),
            "description_side": bool(description) and not _hint_hits(text),
            "judge_side": (
                bool(description)
                and bool(_hint_hits(text))
                and judgement is not None
                and judgement.get("relevant") is False
            ),
        })

    ui_fp_drop = ui_fp_before - ui_fp_after
    ui_fp_drop_ratio = 0.0 if not ui_fp_before else ui_fp_drop / ui_fp_before
    mountain_fn_before = 0 if mountain_before is None else int(mountain_before["fn"])
    mountain_fn_after = 0 if mountain_after is None else int(mountain_after["fn"])
    mountain_desc_ok = sum(1 for item in mountain if item["hint_hits"])
    go = (
        ui_fp_drop_ratio >= 0.20
        and object_ok
        and fn_after <= fn_before + 3
        and (mountain_fn_after < mountain_fn_before or mountain_desc_ok >= 2)
    )
    return {
        "queries": per_query,
        "ui_fp_before": ui_fp_before,
        "ui_fp_after": ui_fp_after,
        "ui_fp_drop": ui_fp_drop,
        "ui_fp_drop_ratio": round(ui_fp_drop_ratio, 3),
        "fn_before": fn_before,
        "fn_after": fn_after,
        "object_ok": object_ok,
        "object_notes": object_notes,
        "ui_fp_cases": ui_fp_cases,
        "mountain": mountain,
        "mountain_fn_before": mountain_fn_before,
        "mountain_fn_after": mountain_fn_after,
        "cost": current.get("cost"),
        "go_full_eval": go,
        "go_reasons": {
            "ui_fp_meaningful_drop": ui_fp_drop_ratio >= 0.20,
            "object_queries_ok": object_ok,
            "fn_not_much_worse": fn_after <= fn_before + 3,
            "mountain_improved_or_description_ok": (
                mountain_fn_after < mountain_fn_before or mountain_desc_ok >= 2
            ),
        },
    }


def render(analysis: dict) -> str:
    lines = [
        "# Describe → Judge A/B analysis",
        "",
        f"- UI FP: {analysis['ui_fp_before']} → {analysis['ui_fp_after']} "
        f"(Δ{analysis['ui_fp_drop']}, {analysis['ui_fp_drop_ratio']:.1%})",
        f"- FN: {analysis['fn_before']} → {analysis['fn_after']}",
        f"- dog/cat/anime ok: {analysis['object_ok']}",
        f"- mountain FN: {analysis['mountain_fn_before']} → {analysis['mountain_fn_after']}",
        f"- go_full_eval: {analysis['go_full_eval']}",
        f"- go_reasons: {json.dumps(analysis['go_reasons'], ensure_ascii=False)}",
        "",
        "## Per query",
        "",
        "| query | split | TP before/after | FP before/after | FN before/after | P after | R after |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in analysis["queries"]:
        b, a = item["before"], item["after"]
        lines.append(
            f"| `{item['query']}` | {item.get('split')} | "
            f"{b['tp']}→{a['tp']} | {b['fp']}→{a['fp']} | {b['fn']}→{a['fn']} | "
            f"{a['precision']} | {a['recall']} |"
        )
    lines.extend(["", "## Mountain wallpaper rank 2–4", ""])
    for item in analysis["mountain"]:
        desc = item.get("description") or {}
        lines.append(f"### `{item['name']}`")
        lines.append("")
        lines.append(
            f"- candidate relevant={item['candidate_relevant']} "
            f"score={item['candidate_score']} confidence={item['candidate_confidence']}"
        )
        lines.append(f"- reason: {item['candidate_reason']}")
        lines.append(f"- hint_hits: {item['hint_hits']}")
        lines.append(
            f"- cause: "
            f"{'description_side' if item['description_side'] else ''}"
            f"{'judge_side' if item['judge_side'] else ''}"
            f"{'unclear' if not item['description_side'] and not item['judge_side'] else ''}"
        )
        for key in (
            "primary_subject", "visual_contents", "presentation",
            "prominent_elements", "primary_vs_background",
        ):
            lines.append(f"- {key}: {desc.get(key)}")
        lines.append("")
    lines.extend(["", "## UI FP samples", ""])
    for case in analysis["ui_fp_cases"]:
        lines.append(
            f"### `{case['query']}` FP {case['before_fp']}→{case['after_fp']} "
            f"fixed={case['fixed']} remaining={case['remaining']} new={case['new_fp']}"
        )
        lines.append("")
        for sample in case["samples"][:10]:
            desc = sample.get("description") or {}
            lines.append(f"- `{sample['name']}` [{sample['status']}]")
            lines.append(f"  - baseline: score={sample['baseline_score']} reason={sample['baseline_reason']}")
            lines.append(
                f"  - candidate: relevant={sample['candidate_relevant']} "
                f"score={sample['candidate_score']} confidence={sample['candidate_confidence']} "
                f"reason={sample['candidate_reason']}"
            )
            lines.append(f"  - primary_subject: {desc.get('primary_subject')}")
            lines.append(f"  - presentation: {desc.get('presentation')}")
            lines.append(f"  - primary_vs_background: {desc.get('primary_vs_background')}")
        lines.append("")
    cost = analysis.get("cost") or {}
    if cost:
        lines.extend(["## Cost", "", json.dumps(cost, ensure_ascii=False, indent=2), ""])
    return "\n".join(lines)


def _side_counts(
    *,
    queries: tuple[str, ...],
    current_rows: dict[str, dict],
    descriptions: dict[str, dict],
    judgements: dict[str, dict],
) -> dict:
    description_side_fn = 0
    judge_side_fn = 0
    description_side_fp = 0
    judge_side_fp = 0
    inconsistencies = []
    samples = []
    for query in queries:
        row = current_rows.get(query) or {}
        judged = (judgements.get(query) or {}).get("judgements") or {}
        for item in _fn_items(row):
            name = item["name"]
            judgement = judged.get(name) or {}
            description = judgement.get("description") or descriptions.get(name)
            hits = _description_hits(description, query)
            if hits:
                judge_side_fn += 1
                cause = "judge_side"
            else:
                description_side_fn += 1
                cause = "description_side"
            samples.append({
                "kind": "fn", "query": query, "name": name, "cause": cause,
                "hits": hits, "reason": judgement.get("reason"),
                "score": judgement.get("relevance_score"),
                "relevant": judgement.get("relevant"),
                "primary_subject": (description or {}).get("primary_subject"),
            })
        for item in _fp_items(row):
            name = item["name"]
            judgement = judged.get(name) or {}
            description = judgement.get("description") or descriptions.get(name)
            hits = _description_hits(description, query)
            if hits:
                description_side_fp += 1
                cause = "description_side"
            else:
                judge_side_fp += 1
                cause = "judge_side"
            samples.append({
                "kind": "fp", "query": query, "name": name, "cause": cause,
                "hits": hits, "reason": judgement.get("reason"),
                "score": judgement.get("relevance_score"),
                "relevant": judgement.get("relevant"),
                "primary_subject": (description or {}).get("primary_subject"),
            })
        for name, judgement in judged.items():
            flag = _inconsistency(judgement)
            if flag:
                inconsistencies.append({
                    "query": query,
                    "name": name,
                    "flag": flag,
                    "relevant": judgement.get("relevant"),
                    "score": judgement.get("relevance_score"),
                    "reason": judgement.get("reason"),
                })
    return {
        "description_side_fn": description_side_fn,
        "judge_side_fn": judge_side_fn,
        "description_side_fp": description_side_fp,
        "judge_side_fp": judge_side_fp,
        "inconsistencies": inconsistencies,
        "samples": samples,
    }


def _metric(row: dict | None, key: str):
    if row is None:
        return None
    return row.get(key)


def analyze_three(
    *,
    baseline: dict,
    candidate_a: dict,
    candidate_b: dict,
    descriptions: dict[str, dict],
    judgements_b: dict[str, dict],
    queries: tuple[str, ...] = SMOKE_QUERIES,
) -> dict:
    base_rows = _rows(baseline)
    a_rows = _rows(candidate_a)
    b_rows = _rows(candidate_b)
    per_query = []
    for query in queries:
        if query not in base_rows and query not in a_rows and query not in b_rows:
            continue
        base = base_rows.get(query)
        a_row = a_rows.get(query)
        b_row = b_rows.get(query)
        per_query.append({
            "query": query,
            "split": (b_row or a_row or base or {}).get("split"),
            "kind": (b_row or a_row or base or {}).get("kind"),
            "baseline": _compare_query(query, base, base)["before"],
            "candidate_a": _compare_query(query, a_row, a_row)["before"],
            "candidate_b": _compare_query(query, b_row, b_row)["before"],
        })

    def sum_fn(label: str) -> int:
        return sum(int(item[label]["fn"] or 0) for item in per_query)

    def sum_fp(label: str, names: set[str] | None = None) -> int:
        return sum(
            int(item[label]["fp"] or 0)
            for item in per_query
            if names is None or item["query"] in names
        )

    def sum_tp(label: str) -> int:
        return sum(int(item[label]["tp"] or 0) for item in per_query)

    object_fn_ok = True
    object_notes = []
    for query in OBJECT_QUERIES:
        item = next((row for row in per_query if row["query"] == query), None)
        if item is None:
            continue
        base_fn = int(item["baseline"]["fn"] or 0)
        b_fn = int(item["candidate_b"]["fn"] or 0)
        if b_fn > base_fn:
            object_fn_ok = False
            object_notes.append(item)

    code_a = next((row for row in per_query if row["query"] == "code editor"), None)
    code_editor_improved = False
    if code_a is not None:
        code_editor_improved = int(code_a["candidate_b"]["fn"] or 0) < int(code_a["candidate_a"]["fn"] or 0)

    fn_base = sum_fn("baseline")
    fn_a = sum_fn("candidate_a")
    fn_b = sum_fn("candidate_b")
    recall_ok = fn_b <= fn_base
    noise_fp_base = sum_fp("baseline", NOISE_QUERIES)
    noise_fp_a = sum_fp("candidate_a", NOISE_QUERIES)
    noise_fp_b = sum_fp("candidate_b", NOISE_QUERIES)
    ui_fp_improved = noise_fp_b < noise_fp_base
    recall_clearly_improved = fn_b < fn_base
    fn_clearly_worse = fn_b > fn_base
    go = (
        recall_ok
        and object_fn_ok
        and code_editor_improved
        and (ui_fp_improved or recall_clearly_improved)
        and not fn_clearly_worse
    )
    sides = _side_counts(
        queries=queries,
        current_rows=b_rows,
        descriptions=descriptions,
        judgements=judgements_b,
    )
    mountain = []
    mountain_judgements = (judgements_b.get("mountain desktop wallpaper") or {}).get("judgements") or {}
    mountain_base = base_rows.get("mountain desktop wallpaper")
    mountain_a = a_rows.get("mountain desktop wallpaper")
    mountain_b = b_rows.get("mountain desktop wallpaper")
    for name in MOUNTAIN_NAMES:
        judgement = mountain_judgements.get(name)
        description = (None if judgement is None else judgement.get("description")) or descriptions.get(name)
        text = _desc_text(description)
        mountain.append({
            "name": name,
            "candidate_relevant": None if judgement is None else judgement.get("relevant"),
            "candidate_score": None if judgement is None else judgement.get("relevance_score"),
            "candidate_confidence": None if judgement is None else judgement.get("confidence"),
            "candidate_reason": None if judgement is None else judgement.get("reason"),
            "description": description,
            "hint_hits": _hint_hits(text),
        })
    return {
        "queries": per_query,
        "tp": {
            "baseline": sum_tp("baseline"),
            "candidate_a": sum_tp("candidate_a"),
            "candidate_b": sum_tp("candidate_b"),
        },
        "fp": {
            "baseline": sum_fp("baseline"),
            "candidate_a": sum_fp("candidate_a"),
            "candidate_b": sum_fp("candidate_b"),
        },
        "fn": {"baseline": fn_base, "candidate_a": fn_a, "candidate_b": fn_b},
        "judge_fp": {
            "baseline": sum(
                int((base_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fp") or 0)
                for query in queries
            ),
            "candidate_a": sum(
                int((a_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fp") or 0)
                for query in queries
            ),
            "candidate_b": sum(
                int((b_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fp") or 0)
                for query in queries
            ),
        },
        "judge_fn": {
            "baseline": sum(
                int((base_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fn") or 0)
                for query in queries
            ),
            "candidate_a": sum(
                int((a_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fn") or 0)
                for query in queries
            ),
            "candidate_b": sum(
                int((b_rows.get(query) or {}).get("failure_mode_counts", {}).get("judge_fn") or 0)
                for query in queries
            ),
        },
        "noise_fp": {
            "baseline": noise_fp_base,
            "candidate_a": noise_fp_a,
            "candidate_b": noise_fp_b,
        },
        "object_fn_ok": object_fn_ok,
        "object_notes": object_notes,
        "code_editor_improved": code_editor_improved,
        "recall_ok": recall_ok,
        "ui_fp_improved": ui_fp_improved,
        "recall_clearly_improved": recall_clearly_improved,
        "fn_clearly_worse": fn_clearly_worse,
        "mountain": mountain,
        "mountain_fn": {
            "baseline": _metric(mountain_base, "fn"),
            "candidate_a": _metric(mountain_a, "fn"),
            "candidate_b": _metric(mountain_b, "fn"),
        },
        "sides": sides,
        "cost_a": candidate_a.get("cost"),
        "cost_b": candidate_b.get("cost"),
        "go_full_eval": go,
        "go_reasons": {
            "recall_maintained_or_improved": recall_ok,
            "object_fn_ok": object_fn_ok,
            "code_editor_improved_vs_a": code_editor_improved,
            "ui_fp_improved_or_recall_clear": ui_fp_improved or recall_clearly_improved,
            "fn_not_clearly_worse": not fn_clearly_worse,
        },
    }


def render_three(analysis: dict) -> str:
    lines = [
        "# Describe → text-only Judge A/B analysis",
        "",
        f"- TP baseline/A/B: {analysis['tp']['baseline']} / {analysis['tp']['candidate_a']} / {analysis['tp']['candidate_b']}",
        f"- FP baseline/A/B: {analysis['fp']['baseline']} / {analysis['fp']['candidate_a']} / {analysis['fp']['candidate_b']}",
        f"- FN baseline/A/B: {analysis['fn']['baseline']} / {analysis['fn']['candidate_a']} / {analysis['fn']['candidate_b']}",
        f"- judge_fp baseline/A/B: {analysis['judge_fp']['baseline']} / {analysis['judge_fp']['candidate_a']} / {analysis['judge_fp']['candidate_b']}",
        f"- judge_fn baseline/A/B: {analysis['judge_fn']['baseline']} / {analysis['judge_fn']['candidate_a']} / {analysis['judge_fn']['candidate_b']}",
        f"- noise FP (Windows/desktop/settings) baseline/A/B: {analysis['noise_fp']['baseline']} / {analysis['noise_fp']['candidate_a']} / {analysis['noise_fp']['candidate_b']}",
        f"- dog/cat/anime FN ok: {analysis['object_fn_ok']}",
        f"- code editor improved vs A: {analysis['code_editor_improved']}",
        f"- mountain FN baseline/A/B: {analysis['mountain_fn']['baseline']} / {analysis['mountain_fn']['candidate_a']} / {analysis['mountain_fn']['candidate_b']}",
        f"- description-side FN/FP: {analysis['sides']['description_side_fn']} / {analysis['sides']['description_side_fp']}",
        f"- judge-side FN/FP: {analysis['sides']['judge_side_fn']} / {analysis['sides']['judge_side_fp']}",
        f"- output inconsistencies: {len(analysis['sides']['inconsistencies'])}",
        f"- go_full_eval: {analysis['go_full_eval']}",
        f"- go_reasons: {json.dumps(analysis['go_reasons'], ensure_ascii=False)}",
        "",
        "## Per query",
        "",
        "| query | split | TP base/A/B | FP base/A/B | FN base/A/B | P base/A/B | R base/A/B |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for item in analysis["queries"]:
        b0, a, b = item["baseline"], item["candidate_a"], item["candidate_b"]
        def _p(row):
            value = row.get("precision")
            return "-" if value is None else f"{value:.3f}"
        def _r(row):
            value = row.get("recall")
            return "-" if value is None else f"{value:.3f}"
        lines.append(
            f"| `{item['query']}` | {item.get('split')} | "
            f"{b0['tp']}/{a['tp']}/{b['tp']} | "
            f"{b0['fp']}/{a['fp']}/{b['fp']} | "
            f"{b0['fn']}/{a['fn']}/{b['fn']} | "
            f"{_p(b0)}/{_p(a)}/{_p(b)} | "
            f"{_r(b0)}/{_r(a)}/{_r(b)} |"
        )
    lines.extend(["", "## Mountain wallpaper rank 2–4", ""])
    for item in analysis["mountain"]:
        desc = item.get("description") or {}
        lines.append(f"### `{item['name']}`")
        lines.append("")
        lines.append(
            f"- B relevant={item['candidate_relevant']} "
            f"score={item['candidate_score']} confidence={item['candidate_confidence']}"
        )
        lines.append(f"- reason: {item['candidate_reason']}")
        lines.append(f"- hint_hits: {item['hint_hits']}")
        lines.append(f"- primary_subject: {desc.get('primary_subject')}")
        lines.append("")
    lines.extend(["", "## FN/FP cause samples", ""])
    for sample in analysis["sides"]["samples"][:40]:
        lines.append(
            f"- `{sample['query']}` `{sample['name']}` [{sample['kind']}/{sample['cause']}] "
            f"relevant={sample['relevant']} score={sample['score']} hits={sample['hits']}"
        )
        lines.append(f"  - reason: {sample['reason']}")
        lines.append(f"  - primary_subject: {sample['primary_subject']}")
    if analysis["sides"]["inconsistencies"]:
        lines.extend(["", "## Output inconsistencies", ""])
        for item in analysis["sides"]["inconsistencies"]:
            lines.append(
                f"- `{item['query']}` `{item['name']}` {item['flag']} "
                f"relevant={item['relevant']} score={item['score']} reason={item['reason']}"
            )
    if analysis.get("cost_b"):
        lines.extend(["", "## Cost B", "", json.dumps(analysis["cost_b"], ensure_ascii=False, indent=2), ""])
    if analysis.get("cost_a"):
        lines.extend(["## Cost A", "", json.dumps(analysis["cost_a"], ensure_ascii=False, indent=2), ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate-a", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current_dir = args.current.parent if args.current.name == "results.json" else args.current
    results_path = args.current if args.current.name == "results.json" else args.current / "results.json"
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(results_path.read_text(encoding="utf-8"))
    descriptions = _load_descriptions(current_dir / "descriptions.json")
    judgements = _load_judgements(current_dir / "judgements.jsonl")
    if args.candidate_a is not None:
        a_path = args.candidate_a if args.candidate_a.name == "results.json" else args.candidate_a / "results.json"
        candidate_a = json.loads(a_path.read_text(encoding="utf-8"))
        analysis = analyze_three(
            baseline=baseline,
            candidate_a=candidate_a,
            candidate_b=current,
            descriptions=descriptions,
            judgements_b=judgements,
        )
        text = render_three(analysis)
        summary = {
            "go_full_eval": analysis["go_full_eval"],
            "fn": analysis["fn"],
            "fp": analysis["fp"],
            "object_fn_ok": analysis["object_fn_ok"],
            "code_editor_improved": analysis["code_editor_improved"],
            "output": None,
        }
    else:
        analysis = analyze(
            baseline=baseline,
            current=current,
            descriptions=descriptions,
            judgements=judgements,
        )
        text = render(analysis)
        summary = {
            "go_full_eval": analysis["go_full_eval"],
            "ui_fp_before": analysis["ui_fp_before"],
            "ui_fp_after": analysis["ui_fp_after"],
            "fn_before": analysis["fn_before"],
            "fn_after": analysis["fn_after"],
            "object_ok": analysis["object_ok"],
            "output": None,
        }
    output = args.output or (current_dir / "ab-analysis.md")
    output.write_text(text, encoding="utf-8")
    json_path = output.with_suffix(".json")
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["output"] = str(output)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
