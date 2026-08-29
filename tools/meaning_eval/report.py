"""JSON + Markdown reports for Meaning-search evaluation runs."""

from __future__ import annotations

import json
from pathlib import Path

from .failure import FAILURE_MODES


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _sum_modes(rows: list[dict]) -> dict[str, int]:
    totals = {mode: 0 for mode in FAILURE_MODES}
    for row in rows:
        for mode, count in (row.get("failure_mode_counts") or {}).items():
            totals[mode] = totals.get(mode, 0) + int(count)
    return totals


def collect_false_negatives(e2e_rows: list[dict]) -> list[dict]:
    items = []
    for row in e2e_rows:
        items.extend(row.get("false_negatives") or [])
    return items


def compare_runs(current: dict, previous: dict | None) -> dict:
    if previous is None:
        return {"previous_identity": None, "improved": [], "worsened": []}
    prev_e2e = {
        row["query"]: row
        for row in (previous.get("end_to_end") or {}).get("queries") or []
    }
    improved = []
    worsened = []
    for row in (current.get("end_to_end") or {}).get("queries") or []:
        other = prev_e2e.get(row["query"])
        if other is None:
            continue
        delta_fn = int(row["fn"]) - int(other["fn"])
        delta_f1 = float(row["f1"]) - float(other.get("f1") or 0.0)
        entry = {
            "query": row["query"],
            "split": row["split"],
            "fn": row["fn"],
            "previous_fn": other["fn"],
            "delta_fn": delta_fn,
            "f1": row["f1"],
            "previous_f1": other.get("f1"),
            "delta_f1": delta_f1,
        }
        if delta_fn < 0 or (delta_fn == 0 and delta_f1 > 1e-9):
            improved.append(entry)
        elif delta_fn > 0 or (delta_fn == 0 and delta_f1 < -1e-9):
            worsened.append(entry)
    improved.sort(key=lambda item: (item["delta_fn"], -item["delta_f1"]))
    worsened.sort(key=lambda item: (-item["delta_fn"], item["delta_f1"]))
    return {
        "previous_identity": previous.get("identity"),
        "improved": improved,
        "worsened": worsened,
    }


def latest_previous_results(runs_dir: Path, current_dir: Path) -> dict | None:
    if not runs_dir.is_dir():
        return None
    candidates = sorted(
        (
            path for path in runs_dir.glob("*/results.json")
            if path.parent.resolve() != current_dir.resolve()
        ),
        key=lambda path: path.parent.name,
    )
    if not candidates:
        return None
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def render_summary(report: dict) -> str:
    identity = report["identity"]
    retriever = report["retriever"]
    e2e = report.get("end_to_end") or {}
    comparison = report.get("comparison") or {}
    lines = [
        "# Meaning search evaluation",
        "",
        "## Run identity",
        "",
        f"- timestamp: `{identity.get('timestamp')}`",
        f"- git commit: `{identity.get('git_commit')}` dirty={identity.get('git_dirty')}",
        f"- retrieval model_id: `{identity.get('retrieval_model_id')}`",
        f"- query embedding: `{identity.get('query_embedding')}`",
        f"- Vision prompt_version: `{identity.get('vision_prompt_version')}`",
        f"- Vision schema_version: `{identity.get('vision_schema_version')}`",
        f"- query set: `{identity.get('query_set_version')}` hash=`{identity.get('query_set_hash')}`",
        f"- GT: `{identity.get('gt_version')}` hash=`{identity.get('gt_hash')}`",
        f"- corpus: count={identity.get('corpus_count')} sha256=`{identity.get('corpus_sha256')}`",
    ]
    if identity.get("judge_candidate"):
        lines.append(f"- judge candidate: `{identity.get('judge_candidate')}`")
    if identity.get("judge_structure"):
        lines.append(f"- judge structure: `{identity.get('judge_structure')}`")
    lines.append("")
    lines.append("## Acceptable policy")
    lines.append("")
    lines.append(
        "Precision/Recall use `lenient_ignore`: `must_include` is relevant, "
        "`acceptable` is neither TP nor FP nor FN, unlabeled retrieved images are FP. "
        "Retriever Recall@K and MRR use `must_include` only."
    )
    lines.append("")
    lines.append("## Query splits")
    lines.append("")
    dev_names = ", ".join(f"`{name}`" for name in report["splits"]["dev"])
    hold_names = ", ".join(f"`{name}`" for name in report["splits"]["holdout"])
    lines.append(f"- dev: {dev_names}")
    lines.append(f"- hold-out: {hold_names}")
    lines.append("")
    lines.append("Hold-out is not for prompt or settings tuning.")
    lines.append("")
    lines.append("## Retriever")
    lines.append("")
    lines.append("| split | n | Recall@10 | Recall@20 | Recall@40 | Recall@80 | MRR |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for split_name in ("dev", "holdout"):
        summary = retriever["splits"][split_name]
        lines.append(
            f"| {split_name} | {summary['n']} | {_fmt(summary['recall_at_10'])} | "
            f"{_fmt(summary.get('recall_at_20'))} | {_fmt(summary['recall_at_40'])} | "
            f"{_fmt(summary.get('recall_at_80'))} | {_fmt(summary['mrr'])} |"
        )
    lines.extend(["", "### Retriever per query", ""])
    lines.append("| query | split | kind | R@10 | R@20 | R@40 | R@80 | MRR | best rank | worst rank |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in retriever["queries"]:
        lines.append(
            f"| `{row['query']}` | {row['split']} | {row['kind']} | "
            f"{_fmt(row['recall_at_10'])} | {_fmt(row.get('recall_at_20'))} | "
            f"{_fmt(row['recall_at_40'])} | {_fmt(row.get('recall_at_80'))} | "
            f"{_fmt(row['mrr'])} | "
            f"{row['best_relevant_rank'] if row['best_relevant_rank'] is not None else '-'} | "
            f"{row.get('worst_relevant_rank') if row.get('worst_relevant_rank') is not None else '-'} |"
        )

    lines.extend(["", "## End-to-end", ""])
    if not e2e:
        lines.append("End-to-end Vision judge was not run.")
    else:
        lines.append("| split | n | macro P | macro R | macro F1 | micro P | micro R | micro TP | micro FP | micro FN |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for split_name in ("dev", "holdout"):
            summary = e2e["splits"][split_name]
            lines.append(
                f"| {split_name} | {summary['n']} | {_fmt(summary['macro_precision'])} | "
                f"{_fmt(summary['macro_recall'])} | {_fmt(summary['macro_f1'])} | "
                f"{_fmt(summary['micro_precision'])} | {_fmt(summary['micro_recall'])} | "
                f"{summary['micro_tp']} | {summary['micro_fp']} | {summary['micro_fn']} |"
            )
        lines.extend(["", "### End-to-end per query", ""])
        lines.append("| query | split | kind | P | R | F1 | TP | FP | FN |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
        for row in e2e["queries"]:
            lines.append(
                f"| `{row['query']}` | {row['split']} | {row['kind']} | "
                f"{_fmt(row['precision'])} | {_fmt(row['recall'])} | {_fmt(row['f1'])} | "
                f"{row['tp']} | {row['fp']} | {row['fn']} |"
            )
        lines.extend(["", "## Failure modes", ""])
        lines.append("| mode | all | dev | hold-out |")
        lines.append("|---|---:|---:|---:|")
        all_modes = e2e["failure_mode_counts"]
        dev_modes = _sum_modes([row for row in e2e["queries"] if row["split"] == "dev"])
        hold_modes = _sum_modes([row for row in e2e["queries"] if row["split"] == "holdout"])
        for mode in FAILURE_MODES:
            lines.append(
                f"| `{mode}` | {all_modes.get(mode, 0)} | {dev_modes.get(mode, 0)} | {hold_modes.get(mode, 0)} |"
            )
        fns = collect_false_negatives(e2e["queries"])
        lines.extend(["", "## False negatives", ""])
        if not fns:
            lines.append("None.")
        else:
            lines.append("| query | image | retrieval rank | Vision | failure mode |")
            lines.append("|---|---|---:|---|---|")
            for item in fns:
                vision = item.get("vision") or {}
                vision_text = (
                    f"relevant={vision.get('relevant')} score={vision.get('relevance_score')} "
                    f"low={vision.get('low_relevant')} high={vision.get('high_relevant')}"
                )
                rank = item.get("retrieval_rank")
                lines.append(
                    f"| `{item['query']}` | `{item['name']}` | "
                    f"{'-' if rank is None else rank} | {vision_text} | `{item['failure_mode']}` |"
                )

    improved = comparison.get("improved") or []
    worsened = comparison.get("worsened") or []
    lines.extend(["", "## Comparison with previous run", ""])
    previous_identity = comparison.get("previous_identity")
    if previous_identity is None:
        lines.append("No previous Phase D run was found. Improved/worsened lists are empty.")
    else:
        lines.append(
            f"Previous timestamp `{previous_identity.get('timestamp')}` "
            f"commit `{previous_identity.get('git_commit')}`."
        )
        lines.append("")
        lines.append("### Main improved queries")
        lines.append("")
        if not improved:
            lines.append("None.")
        else:
            for item in improved[:8]:
                lines.append(
                    f"- `{item['query']}` ({item['split']}): FN {item['previous_fn']}→{item['fn']} "
                    f"(Δ{item['delta_fn']}), F1 {_fmt(item['previous_f1'])}→{_fmt(item['f1'])}"
                )
        lines.extend(["", "### Main worsened queries", ""])
        if not worsened:
            lines.append("None.")
        else:
            for item in worsened[:8]:
                lines.append(
                    f"- `{item['query']}` ({item['split']}): FN {item['previous_fn']}→{item['fn']} "
                    f"(Δ{item['delta_fn']}), F1 {_fmt(item['previous_f1'])}→{_fmt(item['f1'])}"
                )
    if e2e:
        weakest = sorted(e2e["queries"], key=lambda row: (-row["fn"], row["f1"], row["query"]))
        lines.extend(["", "## Weakest queries this run (by FN, then F1)", ""])
        for row in weakest[:8]:
            if row["fn"] == 0 and row["fp"] == 0:
                continue
            lines.append(
                f"- `{row['query']}` ({row['split']}): FN={row['fn']} FP={row['fp']} "
                f"P={_fmt(row['precision'])} R={_fmt(row['recall'])}"
            )
    cost = report.get("cost") or {}
    if cost:
        lines.extend(["", "## Cost", ""])
        total = cost.get("total") or {}
        estimated = cost.get("estimated_usd") or {}
        latency = cost.get("latency_seconds") or {}
        per_image = cost.get("requests_per_image_judgement") or {}
        lines.append(
            f"- requests/image judgement: describe={per_image.get('describe')} "
            f"judge={per_image.get('judge')} ({per_image.get('notes', '')})"
        )
        lines.append(
            f"- tokens: input={total.get('input_tokens')} "
            f"output={total.get('output_tokens')} "
            f"requests={total.get('request_count')}"
        )
        lines.append(
            f"- estimated USD (gpt-5.4-mini $0.75/$4.50 per 1M): "
            f"total={estimated.get('total')} "
            f"describe={estimated.get('describe')} "
            f"judge={estimated.get('judge')}"
        )
        lines.append(
            f"- latency seconds: total={latency.get('total')} "
            f"describe={latency.get('describe')} "
            f"judge={latency.get('judge')}"
        )
        baseline = cost.get("baseline_comparison") or {}
        if baseline:
            lines.append(
                f"- vs baseline (structural): request multiplier~="
                f"{baseline.get('request_multiplier')} "
                f"token/USD measured for candidate only"
            )
            if baseline.get("notes"):
                lines.append(f"- {baseline['notes']}")
    lines.append("")
    return "\n".join(lines)


def write_report(output_dir: Path, report: dict) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    md_path = output_dir / "summary.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_summary(report), encoding="utf-8")
    return json_path, md_path
