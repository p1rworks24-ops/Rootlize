from __future__ import annotations

from collections import defaultdict

import numpy as np


def summarize_rows(rows: list[dict], records: list[dict]) -> dict:
    record_kind = {item["id"]: item.get("kind") for item in records}
    groups = defaultdict(list)
    for row in rows:
        groups["overall"].append(row)
        groups[f"language_{row['language']}"] .append(row)
        groups[f"level_{row['level']}"] .append(row)
        groups["challenge" if row["challenge"] else "required"].append(row)
        kinds = {record_kind.get(item_id) for item_id in row["relevant"]}
        if kinds == {"photo"}:
            groups["no_text_photos"].append(row)
        if kinds == {"screenshot"}:
            groups["screenshots"].append(row)
    summary = {}
    for name, items in groups.items():
        summary[name] = {f"top_{k}": round(sum(x[f"top_{k}"] for x in items) / len(items), 4) for k in [1, 3, 5, 10]}
        summary[name]["mrr"] = round(sum(x["mrr"] for x in items) / len(items), 4)
        summary[name]["queries"] = len(items)
    return summary


def evaluate(image_embeddings: np.ndarray, query_embeddings: np.ndarray, records: list[dict], queries: list[dict]) -> tuple[dict, list[dict]]:
    ids = [item["id"] for item in records]
    scores = query_embeddings @ image_embeddings.T
    rows = []
    for q_index, query in enumerate(queries):
        order = np.argsort(-scores[q_index])
        relevant = set(query["relevant"])
        ranked = [ids[i] for i in order]
        first_rank = next((rank + 1 for rank, item_id in enumerate(ranked) if item_id in relevant), None)
        row = {**query, "first_relevant_rank": first_rank, "mrr": 0.0 if first_rank is None else 1.0 / first_rank}
        for k in [1, 3, 5, 10]:
            row[f"top_{k}"] = float(any(item_id in relevant for item_id in ranked[:k]))
        row["top_results"] = [{"id": ids[i], "score": round(float(scores[q_index, i]), 6)} for i in order[:10]]
        rows.append(row)
    return summarize_rows(rows, records), rows
