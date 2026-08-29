"""Real-image Text/Semantic/Hybrid quality evaluation for the current product ranking."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BENCH))

from app.ocr.database import OCRDatabase
from app.ocr.repository import OCRRepository
from app.ocr.search_service import OCRSearchService
from app.search.hybrid_service import HybridSearchService
from app.semantic.models import SemanticSearchResult
from semantic_benchmark.models import TransformersAdapter


EXACT_QUERIES = [
    ("exact-error-title-en", "en", "Something went wrong", "exact", [f"synthetic-{n:03d}" for n in range(2, 60, 9)]),
    ("exact-error-body-en", "en", "The request could not be completed", "exact", [f"synthetic-{n:03d}" for n in range(2, 60, 9)]),
    ("exact-login-error-en", "en", "Incorrect password", "exact", ["synthetic-015", "synthetic-033", "synthetic-051"]),
    ("exact-doc-ui-en", "en", "Semantic Search API", "exact", [f"synthetic-{n:03d}" for n in range(8, 60, 9)]),
    ("exact-settings-ui-en", "en", "Search indexing", "exact", [f"synthetic-{n:03d}" for n in range(3, 60, 9)]),
    ("exact-product-en", "en", "Aurora Headphones", "exact", [f"synthetic-{n:03d}" for n in range(4, 60, 9)]),
    ("exact-comparison-en", "en", "Cloud sync", "exact", [f"synthetic-{n:03d}" for n in range(5, 60, 9)]),
    ("exact-terminal-en", "en", "capixe analyze ./images", "exact", [f"synthetic-{n:03d}" for n in range(1, 60, 9)]),
]


@dataclass
class Semantic:
    ranks: dict[str, list[tuple[int, float]]]
    def search(self, query, top_k, **_kwargs):
        return [SemanticSearchResult(image_id, score) for image_id, score in self.ranks[query][:top_k]]


def first_rank(ids, relevant):
    return next((rank for rank, item in enumerate(ids, 1) if item in relevant), None)


def metric(rows, method, subset=lambda row: True):
    chosen = [row for row in rows if subset(row)]
    ranks = [row[method] for row in chosen]
    return {f"top_{k}": round(sum(rank is not None and rank <= k for rank in ranks) / len(ranks), 4) for k in (1, 3, 5)} | {"queries": len(ranks)}


def fuse(text_ids, semantic_ids, k=60, text_weight=1.0, semantic_weight=1.0, limit=100):
    scores = {}
    for rank, item in enumerate(text_ids[:limit], 1): scores[item] = scores.get(item, 0) + text_weight / (k + rank)
    for rank, item in enumerate(semantic_ids[:limit], 1): scores[item] = scores.get(item, 0) + semantic_weight / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))]


def main():
    manifest = json.loads((BENCH / "data/manifest.json").read_text(encoding="utf-8"))
    ocr = json.loads((BENCH / "results/hybrid_ocr.json").read_text(encoding="utf-8"))
    queries = json.loads((BENCH / "data/queries.json").read_text(encoding="utf-8"))
    queries += [{"id": i, "language": lang, "text": text, "category": cat, "relevant": rel} for i, lang, text, cat, rel in EXACT_QUERIES]
    spec = {"id": "google/siglip2-base-patch16-224", "family": "SigLIP 2"}
    model = TransformersAdapter(spec, BENCH / "cache/models/google--siglip2-base-patch16-224")
    text_vectors, _ = model.encode_texts([q["text"] for q in queries], 8)
    image_vectors = np.load(BENCH / "artifacts/siglip_2_image_embeddings.npy")
    id_by_pos = [item["id"] for item in manifest]
    id_to_num = {item_id: pos + 1 for pos, item_id in enumerate(id_by_pos)}
    num_to_id = {value: key for key, value in id_to_num.items()}
    semantic_ranks = {}
    for query, vector in zip(queries, text_vectors):
        scores = image_vectors @ vector
        order = np.argsort(-scores, kind="stable")
        semantic_ranks[query["text"]] = [(id_to_num[id_by_pos[pos]], float(scores[pos])) for pos in order]

    db_path = BENCH / "results/hybrid_eval.sqlite3"
    db_path.unlink(missing_ok=True)
    database = OCRDatabase(db_path).open()
    repository = OCRRepository(database)
    for pos, item in enumerate(manifest, 1):
        # Neutral timestamp-like filenames prevent benchmark labels leaking into Text Search.
        path = f"D:/HybridFixture/20260812_{pos:06d}.png"
        image = repository.upsert_image(path, size_bytes=1, mtime_ns=pos)
        value = ocr[item["id"]]
        repository.save_ocr_document(image.image_id, status="ready", ocr_text=value["text"], average_confidence=value["confidence"])
    text_service = OCRSearchService(repository)
    semantic = Semantic(semantic_ranks)
    hybrid = HybridSearchService(text_service, semantic, repository)
    rows = []
    raw_rankings = {}
    for query in queries:
        text_page = text_service.search_images(query["text"], limit=500)
        text_ids = [result.image_id for result in text_page.results]
        sem_ids = [item for item, _score in semantic_ranks[query["text"]]]
        hybrid_ids = [result.image_id for result in hybrid.search(query["text"], 130, candidate_limit=100).results]
        relevant = {id_to_num[item] for item in query["relevant"]}
        row = {"id": query["id"], "language": query["language"], "query": query["text"],
               "category": query.get("category", f"level_{query.get('level')}"), "relevant_count": len(relevant),
               "text": first_rank(text_ids, relevant), "semantic": first_rank(sem_ids, relevant), "hybrid": first_rank(hybrid_ids, relevant),
               "text_hits": len(text_ids), "top5_text": [num_to_id[x] for x in text_ids[:5]],
               "top5_semantic": [num_to_id[x] for x in sem_ids[:5]], "top5_hybrid": [num_to_id[x] for x in hybrid_ids[:5]]}
        rows.append(row); raw_rankings[query["id"]] = (text_ids, sem_ids, relevant)
    summary = {name: metric(rows, name) for name in ("text", "semantic", "hybrid")}
    summary["ja"] = {name: metric(rows, name, lambda row: row["language"] == "ja") for name in ("text", "semantic", "hybrid")}
    summary["en"] = {name: metric(rows, name, lambda row: row["language"] == "en") for name in ("text", "semantic", "hybrid")}
    improvements = [row["id"] for row in rows if (row["text"] is None or (row["hybrid"] or 999) < row["text"]) or (row["semantic"] is None or (row["hybrid"] or 999) < row["semantic"])]
    regressions = [row["id"] for row in rows if (row["text"] is not None and (row["hybrid"] is None or row["hybrid"] > row["text"])) or (row["semantic"] is not None and (row["hybrid"] is None or row["hybrid"] > row["semantic"]))]
    grid = []
    for k in (0, 10, 30, 60, 100):
        for limit in (5, 10, 20, 50, 100):
            for tw, sw in ((1, 1), (2, 1), (1, 2)):
                ranks = []
                for query in queries:
                    text_ids, sem_ids, relevant = raw_rankings[query["id"]]
                    ranks.append(first_rank(fuse(text_ids, sem_ids, k, tw, sw, limit), relevant))
                grid.append({"k": k, "candidate_limit": limit, "text_weight": tw, "semantic_weight": sw,
                             **{f"top_{n}": round(sum(rank is not None and rank <= n for rank in ranks) / len(ranks), 4) for n in (1, 3, 5)}})
    grid.sort(key=lambda x: (-x["top_1"], -x["top_3"], -x["top_5"], abs(x["k"] - 60)))
    result = {"dataset": {"images": len(manifest), "photos": 70, "screenshots": 60, "queries": len(queries)},
              "baseline": {"rrf_k": 60, "candidate_limit": 100, "text_weight": 1, "semantic_weight": 1},
              "summary": summary, "improved_queries": improvements, "regressed_queries": regressions,
              "rows": rows, "tuning_grid_top10": grid[:10], "all_grid": grid}
    (BENCH / "results/hybrid_quality_evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Hybrid Search 実画像品質評価", "", f"画像: 130（写真70、疑似UI 60） / query: {len(queries)}（同一set）", "", "## Baseline集計", "", "|方式|Top-1|Top-3|Top-5|", "|---|---:|---:|---:|"]
    for name in ("text", "semantic", "hybrid"):
        value = summary[name]; md.append(f"|{name.title()}|{value['top_1']:.1%}|{value['top_3']:.1%}|{value['top_5']:.1%}|")
    md += ["", "## Query別順位", "", "`-` は正解なし。", "", "|ID|Lang|Query|Text|Semantic|Hybrid|", "|---|---|---|---:|---:|---:|"]
    for row in rows: md.append(f"|{row['id']}|{row['language']}|{row['query']}|{row['text'] or '-'}|{row['semantic'] or '-'}|{row['hybrid'] or '-'}|")
    md += ["", "## 改善・悪化", "", "改善: " + (", ".join(improvements) or "なし"), "", "悪化: " + (", ".join(regressions) or "なし"), "", "## Parameter grid 上位", "", "|k|候補|Text重み|Semantic重み|Top-1|Top-3|Top-5|", "|---:|---:|---:|---:|---:|---:|---:|"]
    for item in grid[:10]: md.append(f"|{item['k']}|{item['candidate_limit']}|{item['text_weight']}|{item['semantic_weight']}|{item['top_1']:.1%}|{item['top_3']:.1%}|{item['top_5']:.1%}|")
    (BENCH / "results/hybrid_quality_evaluation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    database.close(); db_path.unlink(missing_ok=True)
    print(json.dumps({"summary": summary, "improved": len(improvements), "regressed": len(regressions), "best": grid[0]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
