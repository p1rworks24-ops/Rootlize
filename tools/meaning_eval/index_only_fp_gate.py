"""Eval-only helpers for free-form matching FP-suppression analysis."""

from __future__ import annotations

from tools.meaning_eval.analyze_index_coverage import CHROME_QUERIES
from tools.meaning_eval.freeform_doc_matching import BROAD_UI_QUERIES, FP_BASELINE_NAME, RECALL_FOCUS_NAME
from tools.meaning_eval.hybrid_phase_e import CONDITIONAL_GO, GO, NO_GO
from tools.meaning_eval.index_only_doc_matching import (
    CAUSE_MATCHING,
    FP_CAUSE_ENVIRONMENT,
    FP_CAUSE_GENERIC_UI,
    FP_CAUSE_LEXICAL,
    FP_CAUSE_SEMANTIC,
    _fmt,
    _method_row,
)
from tools.meaning_eval.index_only_freeform import CAUSE_AMBIGUOUS, CAUSE_GT_GAP, CAUSE_MISSING
from tools.meaning_eval.index_only_v3 import _compact_summary

FOCUS_RECALL_QUERIES = (
    "dog",
    "a dog",
    "dog photo",
    "cat",
    "image search application",
    "screenshot manager application",
    "dark themed application",
)

DEV_GUARD_QUERIES = (
    "dog",
    "image search application",
)


def _row_by_query(rows: list[dict]) -> dict[str, dict]:
    return {row["query"]: row for row in rows}


def broad_fp_total(rows: list[dict], *, split: str | None = None) -> int:
    total = 0
    for row in rows:
        if row["query"] not in BROAD_UI_QUERIES:
            continue
        if split is not None and row.get("split") != split:
            continue
        total += int(row.get("fp") or 0)
    return total


def query_recall(rows: list[dict], query: str) -> float | None:
    row = _row_by_query(rows).get(query)
    if row is None:
        return None
    return float(row["recall"])


def compare_query_rows(baseline_rows: list[dict], candidate_rows: list[dict]) -> dict:
    base = _row_by_query(baseline_rows)
    cand = _row_by_query(candidate_rows)
    dropped = []
    gained = []
    new_fp = []
    new_fn = []
    for query, row in cand.items():
        prev = base.get(query) or {}
        recall_delta = float(row["recall"]) - float(prev.get("recall") or 0.0)
        if recall_delta < -1e-9:
            dropped.append({
                "query": query,
                "split": row.get("split"),
                "baseline_recall": prev.get("recall"),
                "candidate_recall": row["recall"],
                "baseline_fn": prev.get("fn"),
                "candidate_fn": row["fn"],
                "delta_recall": round(recall_delta, 4),
            })
        elif recall_delta > 1e-9:
            gained.append({
                "query": query,
                "split": row.get("split"),
                "baseline_recall": prev.get("recall"),
                "candidate_recall": row["recall"],
                "delta_recall": round(recall_delta, 4),
            })
        prev_fp = set(prev.get("fp_names") or [])
        prev_fn = set(prev.get("fn_names") or [])
        cur_fp = set(row.get("fp_names") or [])
        cur_fn = set(row.get("fn_names") or [])
        added_fp = sorted(cur_fp - prev_fp)
        added_fn = sorted(cur_fn - prev_fn)
        if added_fp:
            new_fp.append({"query": query, "split": row.get("split"), "names": added_fp[:8], "count": len(added_fp)})
        if added_fn:
            new_fn.append({"query": query, "split": row.get("split"), "names": added_fn[:8], "count": len(added_fn)})
    dropped.sort(key=lambda item: (item["delta_recall"], item["query"]))
    return {
        "recall_dropped": dropped,
        "recall_gained": gained,
        "new_fp": new_fp,
        "new_fn": new_fn,
    }


def select_fp_gate_policies(
    *,
    dev_by_config: dict[str, dict],
    chrome_by_config: dict[str, int],
    broad_fp_dev_by_config: dict[str, int],
    guard_recall_by_config: dict[str, dict[str, float]],
    baseline_dev: dict,
    baseline_guard_recall: dict[str, float],
    candidate_names: list[str] | None = None,
    recall_slack: float = 0.08,
) -> dict:
    if not dev_by_config:
        raise ValueError("dev_by_config is empty")
    names = list(candidate_names or dev_by_config)
    names = [name for name in names if name in dev_by_config]
    if not names:
        raise ValueError("no FP-gate candidates to select")

    baseline_recall = float(baseline_dev["macro_recall"])
    baseline_f1 = float(baseline_dev["macro_f1"])

    def eligible(name: str) -> bool:
        payload = dev_by_config[name]
        if int(chrome_by_config.get(name) or 0) < 12:
            return False
        if float(payload["macro_recall"]) + 1e-12 < baseline_recall - recall_slack:
            return False
        guards = guard_recall_by_config.get(name) or {}
        for query in DEV_GUARD_QUERIES:
            current = float(guards.get(query) or 0.0)
            floor = float(baseline_guard_recall.get(query) or 0.0)
            if current + 1e-12 < max(0.0, floor - 0.05):
                return False
        return True

    def rank_key(name: str) -> tuple:
        payload = dev_by_config[name]
        f1 = float(payload["macro_f1"])
        recall = float(payload["macro_recall"])
        precision = float(payload["macro_precision"])
        fp = int(broad_fp_dev_by_config.get(name) or 10**9)
        return (
            int(eligible(name)),
            int(recall + 1e-12 >= baseline_recall),
            f1,
            -fp,
            recall,
            precision,
            name,
        )

    selected = sorted(names, key=rank_key, reverse=True)[0]
    precision_name = sorted(
        names,
        key=lambda name: (
            int(eligible(name)),
            float(dev_by_config[name]["macro_precision"]),
            -int(broad_fp_dev_by_config.get(name) or 10**9),
            float(dev_by_config[name]["macro_f1"]),
            name,
        ),
        reverse=True,
    )[0]
    return {
        "selection_split": "dev",
        "holdout_used_for_retune": False,
        "selected": selected,
        "precision_first": precision_name,
        "eligible": [name for name in names if eligible(name)],
        "policies": {
            "fp_suppression": {
                "config": selected,
                "dev": _compact_summary(dev_by_config[selected]),
                "broad_fp_dev": broad_fp_dev_by_config.get(selected),
                "chrome_hits": chrome_by_config.get(selected),
            }
        },
        "notes": (
            "Compared FP-suppression configs on dev only. "
            "Hold-out was not used to choose gates or thresholds. "
            "Gates use generic UI token density, not hardcoded query names."
        ),
    }


def verdict_from_fp_gate(
    *,
    candidate_all: dict,
    baseline_all: dict,
    recall_all: dict,
    b_v4_all: dict,
    chrome_hit_rate: float,
    stable: bool,
    matching_fns: int,
    baseline_matching_fns: int,
    broad_fp: int,
    broad_fp_v4: int,
    broad_fp_baseline: int,
    vision_sent: float,
) -> dict:
    recall_vs_baseline = candidate_all["macro_recall"] - baseline_all["macro_recall"]
    f1_vs_baseline = candidate_all["macro_f1"] - baseline_all["macro_f1"]
    precision_vs_baseline = candidate_all["macro_precision"] - baseline_all["macro_precision"]
    near_v4_fp = broad_fp <= broad_fp_v4 + 30
    matching_cut = matching_fns <= baseline_matching_fns - 10

    if not stable:
        label = NO_GO
        why = "same DB + same query is not deterministic"
        adopt = False
    elif vision_sent > 0:
        label = NO_GO
        why = "FP-suppression matching used Vision"
        adopt = False
    elif chrome_hit_rate + 1e-12 < 1.0:
        label = NO_GO
        why = "Chrome DB-only 12/12 was not maintained"
        adopt = False
    elif (
        chrome_hit_rate + 1e-12 >= 1.0
        and matching_cut
        and near_v4_fp
        and recall_vs_baseline >= 0.03
        and f1_vs_baseline > 0
        and vision_sent == 0
        and stable
    ):
        label = GO
        why = (
            "FP gates keep Chrome and matching-miss gains while bringing "
            "broad UI FP back toward v4 and beating free-form baseline F1"
        )
        adopt = True
    elif matching_fns < baseline_matching_fns and (
        near_v4_fp or candidate_all["micro_fp"] < recall_all["micro_fp"]
    ):
        label = CONDITIONAL_GO
        why = (
            "FP suppression improves Precision versus recall-leaning matching, "
            "but Recall, F1, or broad UI FP still miss the product bar"
        )
        adopt = False
    else:
        label = NO_GO
        why = "FP gates did not keep Recall gains while cutting broad UI FP enough"
        adopt = False

    return {
        "label": label,
        "adopt_fp_gate": adopt,
        "why": why,
        "recall_vs_baseline": round(recall_vs_baseline, 4),
        "f1_vs_baseline": round(f1_vs_baseline, 4),
        "precision_vs_baseline": round(precision_vs_baseline, 4),
        "matching_fns": matching_fns,
        "baseline_matching_fns": baseline_matching_fns,
        "broad_fp": broad_fp,
        "broad_fp_v4": broad_fp_v4,
        "broad_fp_baseline": broad_fp_baseline,
        "chrome_hit_rate": round(chrome_hit_rate, 4),
        "stable": stable,
        "vision_sent": vision_sent,
    }


def render_fp_gate_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_v4 = methods["B_v4"]["all"]
    baseline = methods["B_freeform_baseline"]["all"]
    recall_m = methods["B_freeform_recall"]["all"]
    fp_base = methods["B_freeform_fp_baseline"]["all"]
    gated = methods["B_freeform_fp_gate"]["all"]
    c_all = methods["C_v3"]["all"]
    verdict = report["verdict"]
    causes = report["fn_cause_counts"]
    fp_causes = report["fp_cause_counts"]
    baseline_causes = report["baseline_fn_cause_counts"]
    compare = report.get("vs_baseline") or {}
    lines = [
        "# Free-form matching FP suppression PoC",
        "",
        "製品 Ask AI / Hybrid / Vision Judge / v4 Index / UI / DB schema は変更していない。",
        "dev で FP 抑制候補を選定し、hold-out は凍結確認のみ。",
        "",
        "## 1. 評価した FP 抑制方式",
        "",
    ]
    for item in report.get("evaluated_methods") or []:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 2. 採用候補",
        "",
        f"- selected: `{report['matcher']['name']}`",
        f"- chunk strategy: `{report['matcher']['chunk_strategy']}`",
        f"- aggregation: `{report['matcher']['aggregation']}`",
        f"- opening_gate={report['matcher'].get('opening_gate')} "
        f"min_evidence={report['matcher'].get('min_evidence')} "
        f"generic_density_min={report['matcher'].get('generic_density_min')} "
        f"generic_txt_boost={report['matcher'].get('generic_txt_boost')} "
        f"generic_lex_min={report['matcher'].get('generic_lex_min')}",
        f"- short_generic_full_coverage={report['matcher'].get('short_generic_full_coverage')}",
        f"- selection split: {report['selection']['selection_split']}; "
        f"hold-out retune: {report['selection']['holdout_used_for_retune']}",
        f"- eligible on dev: {', '.join(f'`{name}`' for name in report['selection'].get('eligible') or []) or '(none)'}",
        "",
        "## 3. A / v4 / freeform baseline / recall寄り / FP抑制 / Hybrid 比較",
        "",
        "| method | source | macro P | macro R | macro F1 | micro P | micro R | micro F1 | TP | FP | FN | Vision/query | API req/query | USD/query | latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        _method_row("A Vision Judge", "A", a_all),
        _method_row("B-v4 fixed-schema", "B_v4", b_v4),
        _method_row("B-freeform baseline", "B_freeform_baseline", baseline),
        _method_row("B-freeform recall-leaning", "B_freeform_recall", recall_m),
        _method_row("B-freeform FP baseline sent_top2", "B_freeform_fp_baseline", fp_base),
        _method_row("B-freeform FP suppression", "B_freeform_fp_gate", gated),
        _method_row("C Hybrid", "C_v3", c_all),
        "",
        "## 4. Precision / Recall / F1",
        "",
        f"- selected all: P {_fmt(gated['macro_precision'])} / R {_fmt(gated['macro_recall'])} / F1 {_fmt(gated['macro_f1'])}",
        f"- baseline all: P {_fmt(baseline['macro_precision'])} / R {_fmt(baseline['macro_recall'])} / F1 {_fmt(baseline['macro_f1'])}",
        f"- recall-leaning all: P {_fmt(recall_m['macro_precision'])} / R {_fmt(recall_m['macro_recall'])} / F1 {_fmt(recall_m['macro_f1'])}",
        f"- sent_top2 all: P {_fmt(fp_base['macro_precision'])} / R {_fmt(fp_base['macro_recall'])} / F1 {_fmt(fp_base['macro_f1'])}",
        f"- selected dev: P {_fmt(methods['B_freeform_fp_gate']['dev']['macro_precision'])} / "
        f"R {_fmt(methods['B_freeform_fp_gate']['dev']['macro_recall'])} / "
        f"F1 {_fmt(methods['B_freeform_fp_gate']['dev']['macro_f1'])}",
        f"- selected hold-out (frozen): P {_fmt(methods['B_freeform_fp_gate']['holdout']['macro_precision'])} / "
        f"R {_fmt(methods['B_freeform_fp_gate']['holdout']['macro_recall'])} / "
        f"F1 {_fmt(methods['B_freeform_fp_gate']['holdout']['macro_f1'])}",
        f"- vs baseline: ΔP {verdict['precision_vs_baseline']:+.3f} / "
        f"ΔR {verdict['recall_vs_baseline']:+.3f} / ΔF1 {verdict['f1_vs_baseline']:+.3f}",
        "",
        "## 5. broad UI query別 FP",
        "",
    ])
    for row in report.get("broad_ui") or []:
        lines.append(
            f"- `{row['query']}` ({row['split']}): FP {row['fp']} / TP {row['tp']} / "
            f"P {_fmt(row['precision'])} / R {_fmt(row['recall'])} / predicted {row.get('predicted_count')}"
        )
    lines.extend([
        "",
        f"- selected broad UI FP total: {report.get('broad_fp_total')}",
        f"- v4 broad UI FP total: {report.get('broad_fp_v4')}",
        f"- baseline broad UI FP total: {report.get('broad_fp_baseline')}",
        f"- recall-leaning broad UI FP total: {report.get('broad_fp_recall')}",
        "",
        "## 6. matching miss 59件",
        "",
        f"- baseline matching miss: **{baseline_causes[CAUSE_MATCHING]}**",
        f"- selected matching miss: **{causes[CAUSE_MATCHING]}**",
        f"- reduction: **{baseline_causes[CAUSE_MATCHING] - causes[CAUSE_MATCHING]}**",
        "",
        "## 7. Chrome 12件",
        "",
        f"- DB-only Chrome hits: **{report['chrome_hits']}/12** "
        f"(baseline {report['baseline_chrome_hits']}/12, v4 {report['chrome_v4_hits']}/12)",
        "",
    ])
    for query in CHROME_QUERIES:
        hits = sum(1 for row in report["chrome"]["by_query"][query] if row["in_result"])
        named = sum(1 for row in report["chrome"]["by_query"][query] if row["index_has_chrome"])
        lines.append(f"- `{query}`: result {hits}/12, named in document {named}/12")
    lines.extend([
        "",
        "## 8. category別影響",
        "",
        "| category | n | macro P | macro R | macro F1 | FP | FN |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report.get("categories") or []:
        lines.append(
            f"| {row['label']} | {row['n_queries']} | {_fmt(row['macro_precision'])} | "
            f"{_fmt(row['macro_recall'])} | {_fmt(row['macro_f1'])} | "
            f"{row['micro_fp']} | {row['micro_fn']} |"
        )
    lines.extend([
        "",
        "## 9. Recallを落としたquery",
        "",
    ])
    dropped = compare.get("recall_dropped") or []
    if not dropped:
        lines.append("- none versus free-form baseline")
    for item in dropped:
        lines.append(
            f"- `{item['query']}` ({item.get('split')}): "
            f"R {_fmt(item['baseline_recall'])} → {_fmt(item['candidate_recall'])} "
            f"(FN {item.get('baseline_fn')} → {item.get('candidate_fn')})"
        )
    lines.extend([
        "",
        "Focus recall:",
        "",
    ])
    for row in report.get("focus_queries") or []:
        if row["query"] not in FOCUS_RECALL_QUERIES:
            continue
        lines.append(
            f"- `{row['query']}` ({row['split']}): P {_fmt(row['precision'])} "
            f"R {_fmt(row['recall'])} TP {row['tp']} FP {row['fp']} FN {row['fn']}"
        )
    lines.extend([
        "",
        "## 10. 新規 FP / FN",
        "",
        "FN causes:",
        f"- missing_from_document: {causes[CAUSE_MISSING]}",
        f"- present_but_matching_miss: {causes[CAUSE_MATCHING]}",
        f"- query_ambiguous: {causes[CAUSE_AMBIGUOUS]}",
        f"- gt_interpretation_gap: {causes[CAUSE_GT_GAP]}",
        "",
        "FP causes:",
        f"- environment/background: {fp_causes[FP_CAUSE_ENVIRONMENT]}",
        f"- generic UI: {fp_causes[FP_CAUSE_GENERIC_UI]}",
        f"- semantic overmatch: {fp_causes[FP_CAUSE_SEMANTIC]}",
        f"- lexical overmatch: {fp_causes[FP_CAUSE_LEXICAL]}",
        "",
        "New FN versus baseline (sample):",
    ])
    new_fn = compare.get("new_fn") or []
    if not new_fn:
        lines.append("- none")
    for item in new_fn[:12]:
        lines.append(f"- `{item['query']}` +{item['count']}: {', '.join(item['names'])}")
    lines.extend([
        "",
        "New FP versus baseline (sample):",
    ])
    new_fp = compare.get("new_fp") or []
    if not new_fp:
        lines.append("- none")
    for item in new_fp[:12]:
        lines.append(f"- `{item['query']}` +{item['count']}: {', '.join(item['names'])}")
    lines.extend([
        "",
        "## 11. latency / index size",
        "",
        f"- chunk index build: {report['cost']['chunk_index_build_seconds']:.3f}s",
        f"- mean search latency/query selected: {report['cost']['selected_search_latency']:.4f}s",
        f"- mean search latency/query baseline: {report['cost']['baseline_search_latency']:.4f}s",
        f"- hits/query: {_fmt(gated.get('mean_predicted_count'), 2)}",
        f"- primary chunks: {report['cost']['primary_total_chunks']}",
        f"- estimated chunk index: {report['cost'].get('index_bytes', 0):,} bytes",
        f"- search USD/query: ${report['cost']['search_usd_per_query']:.4f}",
        f"- Vision/query: {gated.get('mean_vision_sent')}",
        "",
        "## 12. DB-only 採用可能性",
        "",
        f"- verdict: **{verdict['label']}** adopt_fp_gate={verdict.get('adopt_fp_gate')}",
        f"- why: {verdict['why']}",
        "",
        "## 13. 最大の残課題",
        "",
        report.get("max_risk") or "",
        "",
        "## 14. 次にやる 1 タスク",
        "",
        report.get("next_task") or "",
        "",
        f"- `{FP_BASELINE_NAME}` and `{RECALL_FOCUS_NAME}` were re-evaluated as fixed references.",
        "",
    ])
    return "\n".join(lines)
