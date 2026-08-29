"""Compare Semantic Index coverage before/after a prompt version change.

Eval-only. Does not retune Hybrid thresholds or change product search.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.semantic.catalog import OPENCLIP_MODEL_KEY
from app.semantic.query_embedding import QUERY_EMBEDDING_RAW
from app.semantic_index.hybrid import (
    DECISION_NEGATIVE,
    PRODUCT_HYBRID_BAND,
    PRODUCT_SEARCH_CONFIG,
    decide_hybrid,
)
from app.semantic_index.schema import INDEX_FIELDS, clip_index_text
from app.semantic_index.scoring import (
    combined_score,
    content_tokens,
    incidental_text,
    index_judgement,
    tokenize,
)
from tools.meaning_eval.dataset import load_dataset
from tools.meaning_eval.evaluate_semantic_index import (
    DEFAULT_CORPUS_NAMES,
    DEFAULT_INDEX_CACHE,
    _encode_corpus,
    _load_name_set,
)
from tools.retriever_eval import encode_query, list_images, load_runtime
from tools.vision_judge_ab_eval import DEFAULT_FOLDER

# Real-device Chrome-visible set from the 2026-08-18 Ask AI investigation.
# Not Ground Truth. Used only to check named-container recall.
CHROME_VISIBLE = (
    "20260718_163013.png",
    "testshot_001.png",
    "20260718_201711.png",
    "20260718_201717.png",
    "20260718_203006.png",
    "20260720_233733.png",
    "20260718_212504.png",
    "20260718_205234.png",
    "20260718_212516.png",
    "20260716_194437.png",
    "20260716_194523_001.png",
    "ScreenShot_Atest_002.png",
)
CHROME_QUERIES = ("Google Chrome", "Chrome")
GENERIC_PROBES = (
    ("object", "dog"),
    ("application", "code editor"),
    ("ui", "browser window"),
    ("game", "video game screenshot"),
    ("person", "people"),
    ("scene", "Windows desktop"),
    ("style", "dark themed application"),
    ("secondary", "sitting"),
)
PRIMARY_LISTS = (
    "searchable_concepts",
    "objects_entities",
    "ui_interface_concepts",
    "visible_activities",
    "visual_attributes",
)
PRIMARY_TEXT = ("visual_summary", "scene_environment")


def _load_cache(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_name = payload.get("by_name")
    if not isinstance(by_name, dict):
        raise SystemExit(f"invalid index cache: {path}")
    return {
        "path": str(path),
        "prompt_version": payload.get("prompt_version"),
        "schema_version": payload.get("schema_version"),
        "usage": payload.get("usage") or {},
        "by_name": by_name,
    }


def _field_text(record: dict, name: str) -> str:
    value = record.get(name)
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item).lower()
    return str(value or "").lower()


def _tokens_in(text: str, tokens: list[str]) -> list[str]:
    hay = set(tokenize(text))
    return [token for token in tokens if token in hay]


def _placement(record: dict, query: str) -> dict:
    tokens = content_tokens(query)
    fields = {}
    primary_hits = []
    incidental_hits = []
    for name in (*PRIMARY_LISTS, *PRIMARY_TEXT):
        matched = _tokens_in(_field_text(record, name), tokens)
        fields[name] = matched
        if matched:
            primary_hits.append(name)
    incidental_matched = _tokens_in(incidental_text(record), tokens)
    fields["incidental_notes"] = incidental_matched
    if incidental_matched:
        incidental_hits.append("incidental_notes")
    if "visual_summary" in primary_hits or "searchable_concepts" in primary_hits:
        band = "primary"
    elif primary_hits:
        band = "secondary"
    elif incidental_hits:
        band = "incidental"
    else:
        band = "missing"
    return {
        "band": band,
        "primary_fields": primary_hits,
        "incidental_fields": incidental_hits,
        "fields": fields,
        "clip_index_text": clip_index_text(record),
        "visual_summary": record.get("visual_summary") or "",
        "objects_entities": list(record.get("objects_entities") or []),
        "searchable_concepts": list(record.get("searchable_concepts") or []),
        "ui_interface_concepts": list(record.get("ui_interface_concepts") or []),
        "incidental_notes": record.get("incidental_notes") or "",
    }


def _hybrid_row(query: str, name: str, record: dict, query_vector, image_vector, text_vector) -> dict:
    judged = index_judgement(
        query,
        record,
        query_vector=query_vector,
        image_vector=image_vector,
        text_vector=text_vector,
        config=PRODUCT_SEARCH_CONFIG,
    )
    decision = decide_hybrid(
        judged,
        PRODUCT_HYBRID_BAND,
        PRODUCT_SEARCH_CONFIG,
        query=query,
        record=record,
    )
    lex = float(judged.get("lex") or 0.0)
    txt = float(judged.get("txt") or 0.0)
    img = float(judged.get("img") or 0.0)
    return {
        "name": name,
        "lex": round(lex, 4),
        "txt": round(txt, 4),
        "img": round(img, 4),
        "combined": round(combined_score(img, txt, lex, PRODUCT_SEARCH_CONFIG), 4),
        "decision": decision,
        "reaches_vision": decision != DECISION_NEGATIVE,
        "placement": _placement(record, query),
    }


def _summarize_chrome(rows: list[dict]) -> dict:
    bands = {}
    vision = 0
    for row in rows:
        band = (row.get("placement") or {}).get("band") or "missing"
        bands[band] = bands.get(band, 0) + 1
        if row.get("reaches_vision"):
            vision += 1
    return {
        "images": len(rows),
        "reaches_vision": vision,
        "clear_negative": len(rows) - vision,
        "bands": bands,
    }


def _count_decisions(records, names, query, query_vector, image_vectors, text_vectors) -> dict:
    counts = {"positive": 0, "negative": 0, "uncertain": 0, "missing": 0}
    for name in names:
        record = records.get(name)
        if not record or record.get("unknown_reason"):
            counts["missing"] += 1
            continue
        judged = index_judgement(
            query,
            record,
            query_vector=query_vector,
            image_vector=image_vectors.get(name),
            text_vector=text_vectors.get(name),
            config=PRODUCT_SEARCH_CONFIG,
        )
        decision = decide_hybrid(
            judged,
            PRODUCT_HYBRID_BAND,
            PRODUCT_SEARCH_CONFIG,
            query=query,
            record=record,
        )
        counts[decision] = counts.get(decision, 0) + 1
    counts["reaches_vision"] = counts["positive"] + counts["uncertain"] + counts["missing"]
    counts["vision_reduction"] = (
        counts["negative"] / len(names) if names else 0.0
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Semantic Index coverage")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--match-corpus-from", type=Path, default=DEFAULT_CORPUS_NAMES)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    before = _load_cache(args.before)
    after = _load_cache(args.after)
    paths = list_images(args.folder)
    keep_names = _load_name_set(args.match_corpus_from)
    if keep_names is not None:
        paths = [path for path in paths if path.name in keep_names]
    names = [path.name for path in paths]
    missing_chrome = [name for name in CHROME_VISIBLE if name not in after["by_name"]]
    runtime = load_runtime(OPENCLIP_MODEL_KEY)
    embedded_names, image_vectors, embed_failed = _encode_corpus(runtime, paths)
    image_vector_map = dict(zip(embedded_names, image_vectors))

    def text_map(cache: dict) -> dict[str, list[float]]:
        vectors = {}
        for path in paths:
            record = cache["by_name"].get(path.name) or {}
            if record.get("unknown_reason"):
                continue
            vectors[path.name] = runtime.embed_text(clip_index_text(record))
        return vectors

    before_text = text_map(before)
    after_text = text_map(after)
    query_vectors = {
        query: encode_query(runtime, query, QUERY_EMBEDDING_RAW)
        for query in (*CHROME_QUERIES, *(item[1] for item in GENERIC_PROBES))
    }
    dataset = load_dataset()
    for spec in dataset.queries:
        query_vectors.setdefault(
            spec.query,
            encode_query(runtime, spec.query, QUERY_EMBEDDING_RAW),
        )

    chrome = {}
    for query in CHROME_QUERIES:
        chrome[query] = {"before": [], "after": []}
        for name in CHROME_VISIBLE:
            for label, cache, texts in (
                ("before", before, before_text),
                ("after", after, after_text),
            ):
                record = cache["by_name"].get(name) or {}
                chrome[query][label].append(
                    _hybrid_row(
                        query,
                        name,
                        record,
                        query_vectors[query],
                        image_vector_map.get(name),
                        texts.get(name),
                    )
                )

    generic = []
    for kind, query in GENERIC_PROBES:
        generic.append({
            "kind": kind,
            "query": query,
            "before": _count_decisions(
                before["by_name"], names, query, query_vectors[query],
                image_vector_map, before_text,
            ),
            "after": _count_decisions(
                after["by_name"], names, query, query_vectors[query],
                image_vector_map, after_text,
            ),
        })

    gt_gate = []
    for spec in dataset.queries:
        gt_gate.append({
            "query": spec.query,
            "split": spec.split,
            "kind": spec.kind,
            "before": _count_decisions(
                before["by_name"], names, spec.query, query_vectors[spec.query],
                image_vector_map, before_text,
            ),
            "after": _count_decisions(
                after["by_name"], names, spec.query, query_vectors[spec.query],
                image_vector_map, after_text,
            ),
        })

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index_fields": list(INDEX_FIELDS),
        "before": {
            "path": before["path"],
            "prompt_version": before["prompt_version"],
            "schema_version": before["schema_version"],
            "images": len(before["by_name"]),
        },
        "after": {
            "path": after["path"],
            "prompt_version": after["prompt_version"],
            "schema_version": after["schema_version"],
            "images": len(after["by_name"]),
            "usage": after["usage"],
        },
        "embed_failed": embed_failed,
        "missing_chrome_after": missing_chrome,
        "chrome_visible": list(CHROME_VISIBLE),
        "chrome_summary": {
            query: {
                "before": _summarize_chrome(rows["before"]),
                "after": _summarize_chrome(rows["after"]),
            }
            for query, rows in chrome.items()
        },
        "chrome": chrome,
        "generic_probes": generic,
        "gt_hybrid_gate": gt_gate,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "coverage.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Semantic Index coverage",
        "",
        f"- before: `{before['prompt_version']}` ({len(before['by_name'])} images)",
        f"- after: `{after['prompt_version']}` ({len(after['by_name'])} images)",
        "",
        "## Chrome visible set",
        "",
        "| query | before Vision | after Vision | before neg | after neg |",
        "|---|---:|---:|---:|---:|",
    ]
    for query, summary in report["chrome_summary"].items():
        lines.append(
            f"| `{query}` | {summary['before']['reaches_vision']}/12 | "
            f"{summary['after']['reaches_vision']}/12 | "
            f"{summary['before']['clear_negative']} | "
            f"{summary['after']['clear_negative']} |"
        )
    lines.extend(["", "## Generic Hybrid gate (clear-negative count)", "",
                  "| kind | query | before neg | after neg | before vision | after vision |",
                  "|---|---|---:|---:|---:|---:|"])
    for item in generic:
        lines.append(
            f"| {item['kind']} | `{item['query']}` | "
            f"{item['before']['negative']} | {item['after']['negative']} | "
            f"{item['before']['reaches_vision']} | {item['after']['reaches_vision']} |"
        )
    (args.output_dir / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
