"""Aggregate completed real-image benchmark JSON into a reviewable report."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = [
    "openclip_vit-b_32_laion-2b.json",
    "siglip_2_base_224.json",
    "nomic_embed_vision_text_v1.5.json",
    "metaclip_2_worldwide_b_32.json",
    "jina_clip_v2.json",
]
DEPLOYMENT_MB = {
    "OpenCLIP ViT-B/32 LAION-2B": 577.1,
    "SigLIP 2 Base/224": 1468.1,
    "Nomic Embed Vision/Text v1.5": 876.2,
    "MetaCLIP 2 Worldwide B/32": 2317.5,
    "Jina CLIP v2": 1667.0,
}

models = [json.loads((HERE / name).read_text(encoding="utf-8")) for name in RESULTS]
lines = [
    "# Capixe Real-image Semantic Retrieval Benchmark",
    "",
    "98 local images from `D:\\07_Programs\\shotlogue_test`; 24 English queries; cosine ranking; no DB, threshold, result-limit, or Hybrid weighting.",
    "",
    "## Aggregate accuracy and measured CPU performance",
    "",
    "|Model|License|Top-1|Top-3|Top-5|Top-10|MRR|Dim|Image ms/item|Text ms/query|Peak RSS MB|Payload/checkpoint MB|",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for model in models:
    metrics, perf, spec = model["metrics"], model["performance"], model["model"]
    lines.append(
        f"|{spec['name']}|{spec['license']}|{metrics['top_1']:.1%}|{metrics['top_3']:.1%}|"
        f"{metrics['top_5']:.1%}|{metrics['top_10']:.1%}|{metrics['mrr']:.3f}|{model['dimension']}|"
        f"{perf['image_ms_each']:.1f}|{perf['text_ms_each']:.1f}|{perf['peak_rss_mb']:.0f}|"
        f"{DEPLOYMENT_MB[spec['name']]:.1f}|"
    )

lines += ["", "## Best relevant rank by query", ""]
header = "|Query|" + "|".join(model["model"]["name"] for model in models) + "|"
lines += [header, "|---|" + "|".join("---:" for _ in models) + "|"]
queries = [row["query"] for row in models[0]["metrics"]["queries"]]
for query in queries:
    ranks = []
    for model in models:
        row = next(item for item in model["metrics"]["queries"] if item["query"] == query)
        ranks.append(str(row["best_relevant_rank"]))
    lines.append("|" + query + "|" + "|".join(ranks) + "|")

lines += ["", "## Required-query detailed relevant ranks", ""]
required = {
    "Windows desktop", "Windows desktop screenshot", "desktop with application windows",
    "dog", "a dog", "dog photo", "image search application", "code editor",
    "browser window", "settings screen",
}
for model in models:
    lines += [f"### {model['model']['name']}", ""]
    for row in model["metrics"]["queries"]:
        if row["query"] in required:
            ranks = ", ".join(f"{name}={rank}" for name, rank in row["relevant_ranks"].items())
            lines.append(f"- `{row['query']}`: {ranks}")
    lines.append("")

lines += [
    "## Decision",
    "",
    "1. OpenCLIP ViT-B/32 LAION-2B: recommended migration prototype. Best commercially usable aggregate result and 4/4 Windows desktop ranks 1-4.",
    "2. Current SigLIP 2 Base/224: fallback. Good broad Top-10 but materially weaker on desktop, image-search application, and code-editor intent.",
    "3. Nomic Embed Vision/Text v1.5: Apache alternative, but lower real-library retrieval quality and two-tower integration work.",
    "",
    "MetaCLIP 2 is the raw accuracy winner but CC-BY-NC-4.0 prevents commercial product distribution. Jina CLIP v2 is also non-commercial and measured at 4.36 s/image with 6.5 GB peak RSS.",
    "",
]
(HERE / "real_image_benchmark_report.md").write_text("\n".join(lines), encoding="utf-8")
print(HERE / "real_image_benchmark_report.md")
