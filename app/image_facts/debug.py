"""Local Meaning Search traces. Not sent to telemetry or cloud usage."""

from __future__ import annotations

from app.image_facts.contracts import apply_facts_contracts
from app.image_facts.format import facts_only, prepare_facts_record
from app.image_facts.query import meaning_query_target


def _facts_excerpt(record: dict) -> dict:
    prepared = facts_only(record)
    return {
        "scene": (prepared.get("scene_description") or "")[:240],
        "environment": prepared.get("environment") or "",
        "ui_types": list(prepared.get("ui_types") or []),
        "applications": [
            {
                "name": item.get("name"),
                "category": item.get("category"),
                "role": item.get("role"),
                "visible_content": (item.get("visible_content") or "")[:160],
            }
            for item in (prepared.get("applications") or [])[:8]
        ],
        "entities": [
            {
                "name": item.get("name"),
                "kind": item.get("kind"),
                "attributes": list(item.get("attributes") or [])[:6],
                "visibility": item.get("visibility"),
            }
            for item in (prepared.get("entities") or [])[:8]
        ],
        "notable_text": list(prepared.get("notable_text") or [])[:8],
        "relationships": list(prepared.get("relationships") or [])[:8],
    }


def local_match_trace(
    *,
    query: str,
    record: dict,
    conditions: list[dict],
    reason: str = "",
    image_id: int | None = None,
    path: str = "",
    rank: int | None = None,
    similarity: float | None = None,
    shortlist_included: bool | None = None,
    favorite: bool | None = None,
) -> dict:
    """Return a local-only trace for one query / one stored facts record.

    Callers must not write this dict to telemetry, cloud usage, or analytics.
    Favorite is accepted only to prove it is ignored.
    """
    del favorite
    target = meaning_query_target(query) or query
    prepared = prepare_facts_record(dict(record))
    if image_id is not None:
        prepared["image_id"] = int(image_id)
    judged = apply_facts_contracts(
        {
            "independent_conditions": [dict(row) for row in conditions],
            "reason": reason,
        },
        query=target,
        record=prepared,
    )
    unconfirmed = list(judged.get("unconfirmed_conditions") or [])
    relevant = bool(judged.get("relevant"))
    return {
        "query": query,
        "meaning_target": target,
        "image_id": image_id,
        "path": path,
        "candidate_rank": rank,
        "openclip_score": similarity,
        "shortlist_included": shortlist_included,
        "stored_facts_excerpt": _facts_excerpt(record),
        "interpreted_conditions": [
            {
                "condition": row.get("condition"),
                "confirmed": row.get("confirmed"),
                "evidence": row.get("evidence"),
                "contract_override": row.get("contract_override"),
            }
            for row in (judged.get("independent_conditions") or [])
            if isinstance(row, dict)
        ],
        "ignored_extra_conditions": list(judged.get("ignored_extra_conditions") or []),
        "final_judge_result": relevant,
        "rejection_reason": "" if relevant else (judged.get("reason") or "; ".join(unconfirmed)),
    }
