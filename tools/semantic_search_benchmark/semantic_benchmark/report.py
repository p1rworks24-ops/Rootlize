from __future__ import annotations

import json
from pathlib import Path


def _pct(value):
    return f"{100 * value:.1f}%"


def write_report(root: Path, payload: dict) -> Path:
    results = payload["results"]
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)
    winner = next((x for x in ranked if x["model"]["commercial_redistribution"]), ranked[0])
    lines = ["# Capixe Semantic Image Search Benchmark Report", "", "## Executive Summary", "", f"推薦: **{winner['model']['id']}**。実測精度、Windows CPU性能、配布ライセンスを合わせた総合判断です。", "", "## Compared Models", "", "| Rank | Model | Family | License | Score |", "|---:|---|---|---|---:|"]
    for rank, item in enumerate(ranked, 1):
        model = item["model"]
        lines.append(f"| {rank} | `{model['id']}` | {model['family']} | {model['license']} | {item['score']:.1f} |")
    lines += ["", "## Dataset", "", f"Wikimedia Commons metadata-grounded subset: {payload['dataset']['public']} images. Capixe synthetic UI: {payload['dataset']['synthetic']} images. Total: {payload['dataset']['total']} images.", "", "Each Commons record retains its source page, creator, and per-file license in `data/manifest.json`. Downloads stay outside Git and are not redistributed. Synthetic UI images are generated locally from project-owned code.", "", "## Accuracy", "", "| Model | JA Top-1 | JA Top-3 | JA Top-5 | JA Top-10 | EN Top-1 | EN Top-3 | EN Top-5 | EN Top-10 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in ranked:
        ja, en = item["metrics"]["language_ja"], item["metrics"]["language_en"]
        lines.append(f"| {item['model']['family']} | {_pct(ja['top_1'])} | {_pct(ja['top_3'])} | {_pct(ja['top_5'])} | {_pct(ja['top_10'])} | {_pct(en['top_1'])} | {_pct(en['top_3'])} | {_pct(en['top_5'])} | {_pct(en['top_10'])} |")
    lines += ["", "## Level Accuracy", "", "Top-3 accuracy by query level:", "", "| Model | L1 Object | L2 Scene | L3 Action | L4 Screenshot | L5 Challenge |", "|---|---:|---:|---:|---:|---:|"]
    for item in ranked:
        cells = [_pct(item["metrics"].get(f"level_{level}", {}).get("top_3", 0)) for level in range(1, 6)]
        lines.append(f"| {item['model']['family']} | {' | '.join(cells)} |")
    lines += ["", "## No-text / Screenshot Accuracy", "", "| Model | No-text Top-1 | No-text Top-3 | Screenshot Top-1 | Screenshot Top-3 |", "|---|---:|---:|---:|---:|"]
    for item in ranked:
        photo, screen = item["metrics"]["no_text_photos"], item["metrics"]["screenshots"]
        lines.append(f"| {item['model']['family']} | {_pct(photo['top_1'])} | {_pct(photo['top_3'])} | {_pct(screen['top_1'])} | {_pct(screen['top_3'])} |")
    lines += ["", "Wikimedia Commons photographs are the no-text subset. Screenshot includes Level 4 and Level 5 synthetic UI; Level 5 remains a separate Challenge.", "", "## Performance", "", "| Model | Load | Image / item | Query / item | Search 10k (measured/extrapolated) | Peak RAM | Dim | 10k vectors | Model cache |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in ranked:
        p = item["performance"]
        lines.append(f"| {item['model']['family']} | {p['load_seconds']:.2f}s | {p['image_ms_each']:.1f}ms | {p['query_ms_each']:.1f}ms | {p['search_10000_ms']:.2f}ms | {p['peak_rss_mb']:.0f}MB | {p['embedding_dimension']} | {p['vectors_10000_mb']:.1f}MB | {p['model_cache_mb']:.0f}MB |")
    lines += ["", "## Deployment", "", "| Model | Windows CPU | ONNX | Offline | Commercial redistribution |", "|---|---|---|---|---|"]
    for item in ranked:
        model = item["model"]
        commercial = "Yes" if model["commercial_redistribution"] else "No under downloaded-weight license"
        lines.append(f"| {model['family']} | Measured | Feasibility only; model-specific validation required | Yes after caching | {commercial} |")
    lines += ["", "## Failure Cases", ""]
    for item in ranked:
        failures = [row for row in item["queries"] if not row["top_3"]][:8]
        lines.append(f"### {item['model']['family']}")
        lines.append("")
        if not failures:
            lines.append("No Top-3 failures.")
        else:
            lines += ["| Query | Language | Level | Expected IDs | Top result | Failure type |", "|---|---|---:|---|---|---|"]
            for row in failures:
                failure_type = "Abstract meaning weakness" if row["level"] == 5 else ("Screenshot weakness" if row["level"] == 4 else ("Relationship/action weakness" if row["level"] == 3 else "Retrieval mismatch"))
                lines.append(f"| {row['text']} | {row['language']} | {row['level']} | {', '.join(row['relevant'][:3])} | {row['top_results'][0]['id']} ({row['top_results'][0]['score']:.3f}) | {failure_type} |")
        lines.append("")
    lines += ["## Ranking Method", "", "Retrieval accuracy 35%, Japanese/multilingual 25%, CPU performance 15%, model/runtime size 10%, Windows deployment 10%, license/maintainability 5%. The numerical ranking describes benchmark fitness; downloaded weights that prohibit commercial redistribution are ineligible for the Capixe recommendation regardless of score.", "", "## Main Weaknesses", "", "The recommended model's UI and abstract-relation weaknesses are visible in Level 4/5 and failure cases. Visual embeddings cannot replace OCR for exact error messages, product attributes, or other text-heavy intent; those remain Hybrid Search candidates.", "", "## Reproduction", "", "```powershell", ".\\run_benchmark.ps1", "```", ""]
    path = root / "semantic_search_benchmark_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (root / "results" / "benchmark_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
