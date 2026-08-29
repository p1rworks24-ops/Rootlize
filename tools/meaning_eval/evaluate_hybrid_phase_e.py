"""Phase E full A/C evaluation of the frozen Semantic Index Hybrid band.

Eval-only. Reuses Ground Truth, dev/hold-out, Index cache, and the stored
product Judge. Does not retune thresholds. Does not change Ask AI.
Does not overwrite artifacts/meaning-eval/latest or the Hybrid selection run.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.relevance.openai_provider import PROMPT_VERSION as PRODUCT_JUDGE_VERSION
from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import DEFAULT_QUERY_EMBEDDING, QUERY_EMBEDDING_RAW
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.describe_judge import estimate_usd as estimate_index_usd
from tools.meaning_eval.evaluate import _providers
from tools.meaning_eval.evaluate_index_hybrid import (
    DEFAULT_OUTPUT as HYBRID_SELECTION_DIR,
    _baseline_eval_row,
    _baseline_rows,
    _break_even_searches,
    _compact_row,
    _config_by_name,
    _fmt,
    _index_only_row,
    _load_baseline,
    _mean,
    _pct,
    _scale_table,
    _score_query,
    _summarize_method,
)
from tools.meaning_eval.evaluate_semantic_index import (
    DEFAULT_COMPARE,
    DEFAULT_CORPUS_NAMES,
    DEFAULT_INDEX_CACHE,
    _encode_corpus,
    _load_name_set,
)
from tools.meaning_eval.hybrid_phase_e import (
    FROZEN_BAND,
    FROZEN_POLICY,
    LIVE_SAMPLE_MAX_IMAGES,
    QUERY_CATEGORIES,
    category_summary,
    collect_a_tp_c_fn,
    collect_reduced_fp,
    count_negative_rescues,
    previous_fn_outcomes,
    query_category,
    returned_reduced_fps,
    select_live_sample,
    snapshot_previous_phase_e,
    verdict_from_metrics,
)
from tools.meaning_eval.identity import build_identity, corpus_identity
from tools.meaning_eval.pipeline import judge_ranked_paths
from tools.meaning_eval.semantic_index import (
    INDEX_PROMPT_VERSION,
    INDEX_SCHEMA_VERSION,
    PRIMARY_SEARCH,
    SEARCH_VERSION,
    clip_index_text,
    load_or_index_paths,
    search_records,
)
from tools.retriever_eval import encode_query, list_images, load_runtime, rank_names
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

RUNS_DIR = ROOT / "artifacts" / "meaning-eval" / "runs"
DEFAULT_OUTPUT = RUNS_DIR / "semantic-index-hybrid-phase-e"


def _load_previous_phase_e(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    nested = payload.get("previous_phase_e")
    identity = payload.get("identity") or {}
    if identity.get("clear_negative_rescue") and nested and nested.get("C_all"):
        return nested
    return snapshot_previous_phase_e(payload)


def _assert_frozen_band(selection_path: Path) -> dict:
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    recommended = payload.get("recommended") or {}
    if recommended.get("policy") != FROZEN_POLICY:
        raise SystemExit(
            f"frozen policy {FROZEN_POLICY!r} != selection {recommended.get('policy')!r}"
        )
    if recommended.get("band") != FROZEN_BAND.name:
        raise SystemExit(
            f"frozen band {FROZEN_BAND.name!r} != selection {recommended.get('band')!r}"
        )
    return payload


def _split_rows(rows: list[dict], split: str) -> list[dict]:
    return [row for row in rows if row["split"] == split]


def _method_payload(
    rows: list[dict],
    *,
    band: str,
    baseline_dev_sent: float,
    baseline_hold_sent: float,
    baseline_all_sent: float,
) -> dict:
    return {
        "band": band,
        "all": _summarize_method(rows, baseline_sent=baseline_all_sent),
        "dev": _summarize_method(_split_rows(rows, "dev"), baseline_sent=baseline_dev_sent),
        "holdout": _summarize_method(
            _split_rows(rows, "holdout"), baseline_sent=baseline_hold_sent
        ),
    }


def _publish_rows(rows: list[dict]) -> list[dict]:
    published = []
    for row in rows:
        item = _compact_row(row)
        item["tp_names"] = list(row.get("tp_names") or [])
        item["fp_names"] = list(row.get("fp_names") or [])
        item["fn_names"] = list(row.get("fn_names") or [])
        item["index_positive"] = row.get("index_positive")
        item["index_negative"] = row.get("index_negative")
        item["uncertain"] = row.get("uncertain")
        published.append(item)
    return published


def _live_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _run_live_sample(
    *,
    sample: list[dict],
    folder: Path,
    enabled: bool,
) -> dict:
    if not enabled:
        return {
            "status": "skipped",
            "reason": "live sample disabled",
            "compared": 0,
            "agreement_rate": None,
            "items": [],
        }
    if not sample:
        return {
            "status": "skipped",
            "reason": "no sample images",
            "compared": 0,
            "agreement_rate": None,
            "items": [],
        }
    if not _live_available():
        return {
            "status": "skipped",
            "reason": "OPENAI_API_KEY missing",
            "compared": 0,
            "agreement_rate": None,
            "items": sample,
        }
    path_by_name = {path.name: path for path in list_images(folder)}
    missing = [item["name"] for item in sample if item["name"] not in path_by_name]
    if missing:
        raise SystemExit(f"live sample names missing from folder: {missing[:8]}")
    low_provider, high_provider = _providers("baseline")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in sample:
        grouped[item["query"]].append(item)
    compared = []
    agree = 0
    disagree = 0
    unknown = 0
    print(
        json.dumps({
            "stage": "live_sample",
            "queries": len(grouped),
            "images": len(sample),
        }, ensure_ascii=False),
        flush=True,
    )
    for query, items in grouped.items():
        ranked = [path_by_name[item["name"]] for item in items]
        judged = judge_ranked_paths(query, ranked, low_provider, high_provider)
        judgements = judged.get("judgements") or {}
        for item in items:
            live = judgements.get(item["name"]) or {}
            live_relevant = live.get("relevant")
            replay_relevant = bool(item["replay_relevant"])
            if live_relevant is None:
                match = "unknown"
                unknown += 1
            elif bool(live_relevant) == replay_relevant:
                match = "agree"
                agree += 1
            else:
                match = "disagree"
                disagree += 1
            compared.append({
                **item,
                "live_relevant": live_relevant,
                "live_low_relevant": live.get("low_relevant"),
                "live_high_relevant": live.get("high_relevant"),
                "live_reason": live.get("reason"),
                "match": match,
            })
            print(
                json.dumps({
                    "live": True,
                    "query": query,
                    "name": item["name"],
                    "match": match,
                    "replay": replay_relevant,
                    "live_relevant": live_relevant,
                }, ensure_ascii=False),
                flush=True,
            )
    decided = agree + disagree
    return {
        "status": "ran",
        "judge": PRODUCT_JUDGE_VERSION,
        "compared": decided,
        "agree": agree,
        "disagree": disagree,
        "unknown": unknown,
        "agreement_rate": None if decided == 0 else agree / decided,
        "items": compared,
    }


def _render_query_table(a_rows: list[dict], c_rows: list[dict]) -> list[str]:
    a_by = {row["query"]: row for row in a_rows}
    lines = [
        "| query | split | category | A P | C P | A R | C R | A F1 | C F1 | A FP | C FP | A FN | C FN | A Vision | C Vision |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c_row in c_rows:
        a_row = a_by[c_row["query"]]
        lines.append(
            f"| `{c_row['query']}` | {c_row['split']} | {query_category(c_row['query'])} | "
            f"{_fmt(a_row['precision'])} | {_fmt(c_row['precision'])} | "
            f"{_fmt(a_row['recall'])} | {_fmt(c_row['recall'])} | "
            f"{_fmt(a_row['f1'])} | {_fmt(c_row['f1'])} | "
            f"{a_row['fp']} | {c_row['fp']} | {a_row['fn']} | {c_row['fn']} | "
            f"{a_row.get('vision_sent_images', '-')} | {c_row.get('vision_sent_images', '-')} |"
        )
    return lines


def _render_method_row(label: str, band: str, payload: dict) -> str:
    return (
        f"| {label} | `{band}` | {_fmt(payload['macro_precision'])} | "
        f"{_fmt(payload['macro_recall'])} | {_fmt(payload['macro_f1'])} | "
        f"{payload['micro_tp']} | {payload['micro_fp']} | {payload['micro_fn']} | "
        f"{_fmt(payload['mean_vision_sent'], 1)} | "
        f"{_fmt(payload['mean_api_requests'], 1)} | "
        f"{_pct(payload['vision_reduction'])} | "
        f"{_fmt(payload['mean_estimated_usd'], 4)} | "
        f"{_fmt(payload['mean_estimated_latency_seconds'], 2)} |"
    )


def _render_compact_compare_row(label: str, payload: dict | None) -> str:
    if not payload:
        return f"| {label} | - | - | - | - | - | - | - | - |"
    return (
        f"| {label} | {_fmt(payload.get('macro_precision'))} | "
        f"{_fmt(payload.get('macro_recall'))} | {_fmt(payload.get('macro_f1'))} | "
        f"{payload.get('micro_fp', '-')} | {payload.get('micro_fn', '-')} | "
        f"{_fmt(payload.get('mean_vision_sent'), 1)} | "
        f"{_pct(payload.get('vision_reduction'))} | "
        f"{_fmt(payload.get('mean_estimated_usd'), 4)} |"
    )


def _render_analysis(report: dict) -> str:
    methods = report["methods"]
    a_all = methods["A"]["all"]
    b_all = methods["B"]["all"]
    c_all = methods["C"]["all"]
    a_hold = methods["A"]["holdout"]
    c_hold = methods["C"]["holdout"]
    a_dev = methods["A"]["dev"]
    c_dev = methods["C"]["dev"]
    verdict = report["verdict"]
    live = report.get("live") or {}
    previous = report.get("previous_phase_e") or {}
    previous_c = previous.get("C_all")
    lines = [
        "# Semantic Index Hybrid Phase E",
        "",
        "製品 Ask AI / Meaning Search は変更していない。Hybrid の Vision ラベルは",
        f"保存済み製品 Judge（`{methods['A']['band']}`）の replay。帯域は前回 dev で",
        f"選んだ `{FROZEN_BAND.name}` を凍結し、hold-out で再選定していない。",
        "clear-negative だけ、Index テキスト埋め込み ≥ 0.70、または複合概念",
        "（例: dark theme）が Index にある場合に Vision 送り（uncertain）へ救済する。",
        "単一トークン一致は採用しない。Index positive にはしない。",
        "",
        "## 1. A / C 全量比較",
        "",
        f"- 凍結 policy: **{FROZEN_POLICY}**",
        f"- 凍結 band: `{FROZEN_BAND.name}`",
        "",
        "全 Ground Truth（dev + hold-out）:",
        "",
        "| method | band | macro P | macro R | macro F1 | micro TP | micro FP | micro FN | mean Vision | mean API req | Vision reduction | est. USD / query | est. latency s |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        _render_method_row("A current Vision Judge", methods["A"]["band"], a_all),
        _render_method_row("B Semantic Index only", methods["B"]["band"], b_all),
        _render_method_row("C Hybrid precision_first", methods["C"]["band"], c_all),
        "",
        "A / 改善前C / 改善後C:",
        "",
        "| method | macro P | macro R | macro F1 | micro FP | micro FN | mean Vision | Vision reduction | est. USD / query |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        _render_compact_compare_row("A", a_all),
        _render_compact_compare_row("改善前C", previous_c),
        _render_compact_compare_row("改善後C", c_all),
        "",
        "Hold-out（凍結確認。再選定には未使用）:",
        "",
        "| method | macro P | macro R | macro F1 | micro FP | micro FN | Vision reduction |",
        "|---|---:|---:|---:|---:|---:|---:|",
        (
            f"| A | {_fmt(a_hold['macro_precision'])} | {_fmt(a_hold['macro_recall'])} | "
            f"{_fmt(a_hold['macro_f1'])} | {a_hold['micro_fp']} | {a_hold['micro_fn']} | 0.0% |"
        ),
        (
            f"| C | {_fmt(c_hold['macro_precision'])} | {_fmt(c_hold['macro_recall'])} | "
            f"{_fmt(c_hold['macro_f1'])} | {c_hold['micro_fp']} | {c_hold['micro_fn']} | "
            f"{_pct(c_hold['vision_reduction'])} |"
        ),
        "",
        (
            f"Dev: A F1={_fmt(a_dev['macro_f1'])} FN={a_dev['micro_fn']} → "
            f"C F1={_fmt(c_dev['macro_f1'])} FN={c_dev['micro_fn']} "
            f"Vision {_fmt(a_dev['mean_vision_sent'], 1)}→{_fmt(c_dev['mean_vision_sent'], 1)} "
            f"({_pct(c_dev['vision_reduction'])})"
        ),
        "",
        "Query 別 Precision / Recall / F1:",
        "",
    ]
    lines.extend(_render_query_table(report["query_rows"]["A"], report["query_rows"]["C"]))
    lines.extend([
        "",
        "## 2. Query カテゴリ別",
        "",
        "| category | n | A P | C P | A R | C R | A F1 | C F1 | A FN | C FN | new FN | Vision reduction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report["categories"]:
        lines.append(
            f"| {row['label']} | {row['n_queries']} | "
            f"{_fmt(row['A']['macro_precision'])} | {_fmt(row['C']['macro_precision'])} | "
            f"{_fmt(row['A']['macro_recall'])} | {_fmt(row['C']['macro_recall'])} | "
            f"{_fmt(row['A']['macro_f1'])} | {_fmt(row['C']['macro_f1'])} | "
            f"{row['A']['micro_fn']} | {row['C']['micro_fn']} | {row['new_fn']} | "
            f"{_pct(row['C']['vision_reduction'])} |"
        )
    lines.extend([
        "",
        "安全さの見立て:",
        "",
    ])
    for row in report["categories"]:
        if row["new_fn"] == 0 and row["C"]["macro_recall"] + 1e-12 >= row["A"]["macro_recall"] - 0.02:
            safety = "Hybrid は相対的に安全（追加 FN なし）"
        elif row["new_fn"] == 0:
            safety = "追加 FN はないが Recall は A 依存のまま"
        elif row["category"] in ("object", "concrete_ui"):
            safety = "Vision 依存が残る。clear-negative で TP を落とす"
        else:
            safety = "Vision 依存が大きい。Index の clear-negative が危険"
        lines.append(
            f"- **{row['label']}** (`{', '.join(row['queries'])}`): {safety}"
        )
    lines.extend([
        "",
        "## 3. Vision 送信削減",
        "",
        (
            f"- 全量 mean images / query: A {_fmt(a_all['mean_vision_sent'], 1)} → "
            f"C {_fmt(c_all['mean_vision_sent'], 1)}（**{_pct(c_all['vision_reduction'])}**）"
        ),
        (
            f"- Hold-out: A {_fmt(a_hold['mean_vision_sent'], 1)} → "
            f"C {_fmt(c_hold['mean_vision_sent'], 1)}（{_pct(c_hold['vision_reduction'])}）"
        ),
        f"- 全量 total Vision images: A {a_all['total_vision_sent']} → C {c_all['total_vision_sent']}",
        "",
    ])
    rescues = report.get("negative_rescues") or {}
    prev_c_sent = (previous_c or {}).get("mean_vision_sent")
    if prev_c_sent is not None:
        lines.append(
            f"- 改善前C mean Vision / query: {_fmt(prev_c_sent, 1)} → "
            f"改善後C {_fmt(c_all['mean_vision_sent'], 1)}"
        )
    lines.append(
        f"- clear-negative 救済で Vision 送りにした query-image 数: "
        f"{rescues.get('images', 0)}"
    )
    if rescues.get("reasons"):
        reason_text = ", ".join(
            f"{name}={count}" for name, count in sorted(rescues["reasons"].items())
        )
        lines.append(f"- 救済理由: {reason_text}")
    lines.extend([
        "",
        "## 4. API コスト削減",
        "",
        (
            f"- Index 生成（1回, {report['cost']['index_images']} images）: "
            f"${_fmt(report['cost']['index_generation_usd'], 4)} "
            f"cache_reused={report['cost']['index_cache_reused']}"
        ),
        (
            f"- 全量 mean USD / query: A ${_fmt(a_all['mean_estimated_usd'], 4)} → "
            f"C ${_fmt(c_all['mean_estimated_usd'], 4)}"
        ),
        (
            f"- 全量 mean API requests / query: A {_fmt(a_all['mean_api_requests'], 1)} → "
            f"C {_fmt(c_all['mean_api_requests'], 1)}"
        ),
        (
            f"- 全量 mean latency s / query: A {_fmt(a_all['mean_estimated_latency_seconds'], 2)} → "
            f"C {_fmt(c_all['mean_estimated_latency_seconds'], 2)}"
        ),
        "",
        "Break-even（Index + Hybrid vs 現行 Judge, 全量送信率）:",
        "",
        "| images | searches | A search USD | C index+search USD | C better? |",
        "|---:|---:|---:|---:|---|",
    ])
    for row in report["cost"].get("scale") or []:
        lines.append(
            f"| {row['images']} | {row['searches']} | {row['A_search_usd']} | "
            f"{row['C_index_plus_search_usd']} | {row['C_better']} |"
        )
    be = report["cost"].get("break_even_searches_per_library")
    lines.extend([
        "",
        f"- 同じライブラリサイズで Index 生成を回収する検索回数: "
        f"{'-' if be is None else _fmt(be, 2)}",
        "",
        "## 5. A→C で新たに発生した FN",
        "",
        f"- 件数: **{len(report['new_fns'])}**（A では TP、C では FN）",
        "",
    ])
    previous_outcomes = report.get("previous_fn_outcomes") or []
    if previous_outcomes:
        still = sum(1 for item in previous_outcomes if item.get("still_fn"))
        lines.extend([
            f"- 前回の新規 FN 5件のうち残件: **{still}** / {len(previous_outcomes)}",
            "",
            "| query | image | still FN | decision | predicted | rescue reasons |",
            "|---|---|---|---|---|---|",
        ])
        for item in previous_outcomes:
            reasons = ", ".join(item.get("negative_rescue_reasons") or []) or "-"
            lines.append(
                f"| `{item['query']}` | `{item['name']}` | "
                f"{item.get('still_fn')} | {item.get('decision')} | "
                f"{item.get('predicted')} | {reasons} |"
            )
        lines.append("")
    if not report["new_fns"]:
        lines.append("なし。")
    else:
        lines.extend([
            "| query | split | category | image | cause | lex | txt | img | combined | hit | tokens found |",
            "|---|---|---|---|---|---:|---:|---:|---:|---|---|",
        ])
        split_by_query = {row["query"]: row["split"] for row in report["query_rows"]["A"]}
        for item in report["new_fns"]:
            found = ", ".join(item.get("tokens_found") or []) or "-"
            lines.append(
                f"| `{item['query']}` | {split_by_query.get(item['query'], '-')} | "
                f"{item['category']} | `{item['name']}` | {item['cause']} | "
                f"{_fmt(item['lex'])} | {_fmt(item['txt'])} | {_fmt(item['img'])} | "
                f"{_fmt(item['combined'])} | {item['include_hit']} | {found} |"
            )
        lines.extend(["", "原因の詳細:", ""])
        for item in report["new_fns"]:
            index = item.get("index") or {}
            summary = (index.get("visual_summary") or "").replace("\n", " ")
            lines.append(
                f"- `{item['query']}` / `{item['name']}`: **{item['cause']}** "
                f"(decision={item['decision']}, lex={_fmt(item['lex'])}, "
                f"txt={_fmt(item['txt'])}, missing={item.get('tokens_missing')}). "
                f"summary: {summary[:240]}"
            )
        cause_counts = report["verdict"].get("cause_counts") or {}
        lines.extend([
            "",
            "原因分類カウント:",
            "",
        ])
        for cause, count in sorted(cause_counts.items(), key=lambda pair: (-pair[1], pair[0])):
            lines.append(f"- {cause}: {count}")
    reduced = report.get("reduced_fps") or []
    lines.extend([
        "",
        "## 6. C で削減できた A の FP",
        "",
        f"- 件数: **{len(reduced)}**（A の FP を C の clear-negative が除外）",
        "",
    ])
    by_query: dict[str, list[dict]] = defaultdict(list)
    for item in reduced:
        by_query[item["query"]].append(item)
    if not reduced:
        lines.append("なし。")
    else:
        lines.extend([
            "| query | removed FP | examples |",
            "|---|---:|---|",
        ])
        for query, items in by_query.items():
            examples = ", ".join(f"`{item['name']}`" for item in items[:5])
            extra = "" if len(items) <= 5 else f" … +{len(items) - 5}"
            lines.append(f"| `{query}` | {len(items)} | {examples}{extra} |")
    returned = report.get("returned_fps") or []
    prev_reduced_n = len((previous.get("reduced_fps") or []))
    if prev_reduced_n or returned:
        lines.extend([
            "",
            f"- 改善前C が消していた A の FP: {prev_reduced_n} → 改善後C: {len(reduced)}",
            f"- 救済で戻った FP: **{len(returned)}**",
            "",
        ])
        if returned:
            lines.extend([
                "| query | returned FP examples |",
                "|---|---|",
            ])
            returned_by_query: dict[str, list[dict]] = defaultdict(list)
            for item in returned:
                returned_by_query[item["query"]].append(item)
            for query, items in returned_by_query.items():
                examples = ", ".join(f"`{item['name']}`" for item in items[:5])
                extra = "" if len(items) <= 5 else f" … +{len(items) - 5}"
                lines.append(f"| `{query}` | {len(items)}: {examples}{extra} |")
    lines.extend([
        "",
        "## 7. Replay と live Judge の差",
        "",
        f"- status: {live.get('status')}",
    ])
    if live.get("reason"):
        lines.append(f"- reason: {live.get('reason')}")
    if live.get("status") == "ran":
        lines.extend([
            f"- compared (decided): {live.get('compared')}",
            f"- agree: {live.get('agree')} / disagree: {live.get('disagree')} / unknown: {live.get('unknown')}",
            f"- agreement rate: {_pct(live.get('agreement_rate'))}",
            "",
            "| query | image | role | replay | live | match |",
            "|---|---|---|---|---|---|",
        ])
        for item in live.get("items") or []:
            lines.append(
                f"| `{item['query']}` | `{item['name']}` | {item['role']} | "
                f"{item.get('replay_relevant')} | {item.get('live_relevant')} | "
                f"{item.get('match')} |"
            )
    else:
        lines.append("- ライブ比較は未実施またはスキップ。C の本表は replay のまま。")
    lines.extend([
        "",
        "## 8. 採用判定",
        "",
        f"- **{verdict['decision']}**",
        f"- frozen band: `{verdict['band']}`（hold-out で変更していない）",
        "",
    ])
    for reason in verdict.get("reasons") or []:
        lines.append(f"- {reason}")
    lines.extend([
        "",
        "## 9. 製品接続する場合の具体的リスク",
        "",
        "- Hybrid precision_first は Index hit を自動採用しない（`pos_lex_min=1.01`）。",
        "  効果は clear-negative による Vision 送信削減と、誤 negative の Vision 救済。",
        "  救済画像は positive 確定せず Vision Judge へ送る。",
        "- object 以外、とくに broad UI / abstract-style は Index が「種類名」や",
        "  「見た目」を十分に書いていても query 語と coverage ゲートで落ちることがある。",
        "- replay と live の二段 Judge は一致しない可能性がある。一致率が低いと、",
        "  本評価の F1 / 削減率は製品実測とずれる。",
        "- Index はファイル変更で stale になる。生成コストは検索の前払いであり、",
        "  API budget はまだ製品未接続。",
        "- 現行 Ask AI の FP（broad UI）は Hybrid でも Vision に回る分が残る。",
        "  Precision 改善は clear-negative で削れた FP の範囲に限る。",
        "",
        "## 10. 次に実施すべき 1 タスク",
        "",
        f"{verdict['next_task']}",
        "",
        "## Validation",
        "",
        f"- frozen band matches previous Hybrid selection: {report['validation']['frozen_band_matches_selection']}",
        f"- `vision_all` matched A predicted sets: {report['validation']['vision_all_matches_A']}",
        f"- category coverage: {report['validation']['category_coverage_ok']}",
        "",
        "Hold-out は帯域選定に使っていない。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase E frozen Hybrid A/C eval")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--gt", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_COMPARE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--selection", type=Path, default=HYBRID_SELECTION_DIR / "results.json")
    parser.add_argument("--search", default=PRIMARY_SEARCH)
    parser.add_argument(
        "--live-sample",
        choices=("auto", "always", "never"),
        default="auto",
        help="Limited live product Judge vs stored replay. auto runs only with OPENAI_API_KEY.",
    )
    parser.add_argument("--live-max-images", type=int, default=LIVE_SAMPLE_MAX_IMAGES)
    args = parser.parse_args()
    previous_phase_e = _load_previous_phase_e(args.output_dir / "results.json")

    selection_payload = _assert_frozen_band(args.selection)
    dataset = load_dataset(args.gt)
    missing_categories = [spec.query for spec in dataset.queries if spec.query not in QUERY_CATEGORIES]
    if missing_categories:
        raise SystemExit(f"Phase E categories missing: {missing_categories}")

    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
        missing = keep_names - {path.name for path in paths}
        if missing:
            raise SystemExit(f"match-corpus-from names missing from folder: {sorted(missing)[:8]}")
    corpus = corpus_identity(paths)
    corpus_count = len(paths)
    baseline_payload = _load_baseline(args.baseline)
    baseline_by_query = _baseline_rows(baseline_payload)
    missing_queries = [spec.query for spec in dataset.queries if spec.query not in baseline_by_query]
    if missing_queries:
        raise SystemExit(f"baseline missing queries: {missing_queries[:8]}")

    print(f"indexing {len(paths)} images cache={args.index_cache}", flush=True)
    records, index_usage, cache_reused = load_or_index_paths(paths, args.index_cache)
    print(
        json.dumps({
            "stage": "index",
            "images": len(paths),
            "cache_reused": cache_reused,
            "request_count": index_usage.get("request_count"),
        }, ensure_ascii=False),
        flush=True,
    )

    print(f"loading official retriever {OPENCLIP_MODEL_KEY}", flush=True)
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    identity = runtime.bundle.identity
    print(f"encoding {len(paths)} images", flush=True)
    embedded_names, image_vectors, embed_failed = _encode_corpus(runtime, paths)
    image_vector_map = dict(zip(embedded_names, image_vectors))
    print("encoding semantic index text", flush=True)
    text_vectors = {}
    for path in paths:
        record = records.get(path.name) or {}
        if record.get("unknown_reason"):
            continue
        text_vectors[path.name] = runtime.embed_text(clip_index_text(record))
    query_vectors = {
        spec.query: encode_query(runtime, spec.query, QUERY_EMBEDDING_RAW)
        for spec in dataset.queries
    }
    rankings = {
        spec.query: rank_names(query_vectors[spec.query], embedded_names, image_vectors)
        for spec in dataset.queries
    }

    search_config = _config_by_name()[args.search]
    embedded_set = set(embedded_names)
    index_by_query = {}
    local_started = time.perf_counter()
    for spec in dataset.queries:
        index_by_query[spec.query] = search_records(
            spec.query,
            rankings[spec.query],
            records,
            query_vector=query_vectors[spec.query],
            image_vectors=image_vector_map,
            text_vectors=text_vectors,
            config=search_config,
        )
    local_seconds = time.perf_counter() - local_started

    a_rows = []
    b_rows = []
    c_rows = []
    vision_all_ok = True
    for spec in dataset.queries:
        baseline_row = baseline_by_query[spec.query]
        vision_true = set(baseline_row.get("predicted") or [])
        a_row = _baseline_eval_row(spec, baseline_row, corpus_count)
        b_row = _index_only_row(
            spec,
            ranking=rankings[spec.query],
            index_judged=index_by_query[spec.query],
            search_config=search_config,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
        )
        c_row = _score_query(
            spec,
            ranking=rankings[spec.query],
            index_judged=index_by_query[spec.query],
            band=FROZEN_BAND,
            search_config=search_config,
            vision_true=vision_true,
            corpus_count=corpus_count,
            embedded_set=embedded_set,
            full_vision=False,
            records=records,
        )
        if set(a_row.get("predicted") or []) != vision_true:
            vision_all_ok = False
        a_rows.append(a_row)
        b_rows.append(b_row)
        c_rows.append(c_row)

    a_dev_sent = _mean([row["vision_sent_images"] for row in a_rows if row["split"] == "dev"])
    a_hold_sent = _mean([row["vision_sent_images"] for row in a_rows if row["split"] == "holdout"])
    a_all_sent = _mean([row["vision_sent_images"] for row in a_rows])
    methods = {
        "A": _method_payload(
            a_rows, band=PRODUCT_JUDGE_VERSION,
            baseline_dev_sent=a_dev_sent, baseline_hold_sent=a_hold_sent,
            baseline_all_sent=a_all_sent,
        ),
        "B": _method_payload(
            b_rows, band="index_only",
            baseline_dev_sent=a_dev_sent, baseline_hold_sent=a_hold_sent,
            baseline_all_sent=a_all_sent,
        ),
        "C": _method_payload(
            c_rows, band=FROZEN_BAND.name,
            baseline_dev_sent=a_dev_sent, baseline_hold_sent=a_hold_sent,
            baseline_all_sent=a_all_sent,
        ),
    }

    new_fns = []
    reduced_fps = []
    a_by_query = {row["query"]: row for row in a_rows}
    for spec, c_row in zip(dataset.queries, c_rows):
        new_fns.extend(collect_a_tp_c_fn(
            spec=spec,
            a_row=a_by_query[spec.query],
            c_row=c_row,
            records=records,
            ranking=rankings[spec.query],
            search_config=search_config,
        ))
        reduced_fps.extend(collect_reduced_fp(a_by_query[spec.query], c_row))

    previous_outcomes = previous_fn_outcomes(c_rows=c_rows, new_fns=new_fns)
    returned_fps = returned_reduced_fps(
        (previous_phase_e or {}).get("reduced_fps"),
        reduced_fps,
    )
    negative_rescues = count_negative_rescues(c_rows)
    categories = category_summary(a_rows, c_rows, new_fns)
    live_wanted = args.live_sample == "always" or (
        args.live_sample == "auto" and _live_available()
    )
    if args.live_sample == "always" and not _live_available():
        raise SystemExit("OPENAI_API_KEY missing; --live-sample always requires it")
    sample = select_live_sample(
        new_fns=new_fns,
        c_rows=c_rows,
        a_rows=a_rows,
        reduced_fps=reduced_fps,
        max_images=args.live_max_images,
    )
    live = _run_live_sample(sample=sample, folder=args.folder, enabled=live_wanted)
    verdict = verdict_from_metrics(
        new_fns=new_fns,
        category_rows=categories,
        live=live,
        a_all=methods["A"]["all"],
        c_all=methods["C"]["all"],
        a_hold=methods["A"]["holdout"],
        c_hold=methods["C"]["holdout"],
    )

    index_usd = estimate_index_usd(
        int(index_usage.get("input_tokens") or 0),
        int(index_usage.get("output_tokens") or 0),
    )
    index_per_image = 0.0 if corpus_count == 0 else index_usd / corpus_count
    a_per_image_search = 0.0 if corpus_count == 0 else methods["A"]["all"]["mean_estimated_usd"] / corpus_count
    c_per_image_search = 0.0 if corpus_count == 0 else methods["C"]["all"]["mean_estimated_usd"] / corpus_count
    scale = _scale_table(
        index_usd_per_image=index_per_image,
        a_usd_per_image_per_search=a_per_image_search,
        c_usd_per_image_per_search=c_per_image_search,
    )
    break_even = _break_even_searches(
        index_usd_per_image=index_per_image,
        a_usd_per_image_per_search=a_per_image_search,
        c_usd_per_image_per_search=c_per_image_search,
    )

    run_identity = build_identity(
        dataset=dataset,
        corpus=corpus,
        model_id=identity.model_id,
        query_embedding=DEFAULT_QUERY_EMBEDDING,
        prompt_version=INDEX_PROMPT_VERSION,
        schema_version=INDEX_SCHEMA_VERSION,
    )
    run_identity["judge_candidate"] = "semantic-index-hybrid-phase-e"
    run_identity["judge_structure"] = "frozen_index_then_replayed_product_judge"
    run_identity["baseline_prompt_version"] = (
        (baseline_payload.get("identity") or {}).get("vision_prompt_version")
    )
    run_identity["frozen_hybrid_band"] = FROZEN_BAND.name
    run_identity["frozen_hybrid_policy"] = FROZEN_POLICY
    run_identity["clear_negative_rescue"] = True

    report = {
        "identity": run_identity,
        "folder": str(args.folder),
        "embed_failed": embed_failed,
        "search_config": args.search,
        "search_version": SEARCH_VERSION,
        "splits": {
            "dev": [spec.query for spec in dataset.by_split()["dev"]],
            "holdout": [spec.query for spec in dataset.by_split()["holdout"]],
        },
        "local_index_search_seconds": round(local_seconds, 3),
        "methods": methods,
        "query_rows": {
            "A": _publish_rows(a_rows),
            "B": _publish_rows(b_rows),
            "C": _publish_rows(c_rows),
        },
        "categories": categories,
        "new_fns": new_fns,
        "reduced_fps": reduced_fps,
        "previous_fn_outcomes": previous_outcomes,
        "returned_fps": returned_fps,
        "negative_rescues": negative_rescues,
        "previous_phase_e": previous_phase_e,
        "live": live,
        "verdict": verdict,
        "previous_selection": {
            "path": str(args.selection),
            "policy": (selection_payload.get("recommended") or {}).get("policy"),
            "band": (selection_payload.get("recommended") or {}).get("band"),
        },
        "validation": {
            "frozen_band_matches_selection": True,
            "vision_all_matches_A": vision_all_ok,
            "category_coverage_ok": not missing_categories,
            "holdout_used_for_retune": False,
        },
        "cost": {
            "index_cache_reused": cache_reused,
            "index_images": corpus_count,
            "index_input_tokens": index_usage.get("input_tokens"),
            "index_output_tokens": index_usage.get("output_tokens"),
            "index_requests": index_usage.get("request_count"),
            "index_generation_usd": round(index_usd, 4),
            "index_usd_per_image": round(index_per_image, 6),
            "search_cost_source": (
                "Stage-1 from measured gpt-5.4-mini 512px run; "
                "Stage-2 input tokens estimated at 4x Stage-1. "
                "Index generation is separate from per-query Judge cost."
            ),
            "A_all_usd_per_query": round(methods["A"]["all"]["mean_estimated_usd"], 6),
            "C_all_usd_per_query": round(methods["C"]["all"]["mean_estimated_usd"], 6),
            "break_even_searches_per_library": (
                None if break_even is None else round(break_even, 3)
            ),
            "scale": scale,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    analysis_path = args.output_dir / "phase-e-analysis.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_path.write_text(_render_analysis(report), encoding="utf-8")
    summary_path = args.output_dir / "summary.md"
    summary_path.write_text(
        "\n".join([
            "# Semantic Index Hybrid Phase E summary",
            "",
            f"- frozen: {FROZEN_POLICY} `{FROZEN_BAND.name}`",
            f"- all C vs A F1: {_fmt(methods['C']['all']['macro_f1'])} vs {_fmt(methods['A']['all']['macro_f1'])}",
            f"- all Vision reduction: {_pct(methods['C']['all']['vision_reduction'])}",
            f"- new FN (A TP → C FN): {len(new_fns)}",
            (
                f"- previous FN remaining: "
                f"{sum(1 for item in previous_outcomes if item.get('still_fn'))}"
                f"/{len(previous_outcomes)}"
            ),
            f"- reduced FP: {len(reduced_fps)}",
            f"- returned FP vs previous C: {len(returned_fps)}",
            f"- negative rescues: {negative_rescues.get('images', 0)}",
            f"- live: {live.get('status')} agreement={live.get('agreement_rate')}",
            f"- verdict: {verdict['decision']}",
            f"- next: {verdict['next_task']}",
            f"- details: `{analysis_path.name}`",
            "",
        ]),
        encoding="utf-8",
    )
    print(json_path)
    print(analysis_path)
    print(summary_path)
    print(json.dumps({
        "verdict": verdict["decision"],
        "new_fn": len(new_fns),
        "previous_fn_remaining": sum(
            1 for item in previous_outcomes if item.get("still_fn")
        ),
        "reduced_fp": len(reduced_fps),
        "returned_fp": len(returned_fps),
        "negative_rescues": negative_rescues.get("images", 0),
        "vision_reduction": methods["C"]["all"]["vision_reduction"],
        "live": live.get("status"),
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
