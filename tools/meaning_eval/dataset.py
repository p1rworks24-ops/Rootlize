"""Load the Phase D evaluation set. Not imported by app/ product code."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

QUERY_KINDS = (
    "object",
    "person",
    "place",
    "ui",
    "style",
    "color",
    "activity",
    "state",
    "abstract",
)
SPLITS = ("dev", "holdout")
ACCEPTABLE_POLICY_NAME = "lenient_ignore"
DEFAULT_GT_PATH = Path(__file__).resolve().parent / "data" / "ground_truth.json"


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _names(value: object) -> list[str]:
    if not value:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError("Image lists must be arrays of non-empty strings.")
    return list(value)


@dataclass(frozen=True)
class QuerySpec:
    query: str
    split: str
    kind: str
    must_include: tuple[str, ...]
    must_exclude: tuple[str, ...]
    acceptable: tuple[str, ...]
    notes: str = ""

    @property
    def must_include_set(self) -> set[str]:
        return set(self.must_include)

    @property
    def must_exclude_set(self) -> set[str]:
        return set(self.must_exclude)

    @property
    def acceptable_set(self) -> set[str]:
        return set(self.acceptable)


@dataclass(frozen=True)
class EvalDataset:
    path: Path
    query_set_version: str
    gt_version: str
    query_set_hash: str
    gt_hash: str
    acceptable_policy: dict
    gt_corrections: tuple[dict, ...]
    queries: tuple[QuerySpec, ...]

    def by_split(self) -> dict[str, list[QuerySpec]]:
        grouped = {split: [] for split in SPLITS}
        for spec in self.queries:
            grouped[spec.split].append(spec)
        return grouped

    def query_names(self, split: str | None = None) -> list[str]:
        if split is None:
            return [spec.query for spec in self.queries]
        return [spec.query for spec in self.queries if spec.split == split]

    def spec(self, query: str) -> QuerySpec:
        for item in self.queries:
            if item.query == query:
                return item
        raise KeyError(query)


def _query_set_payload(queries: list[QuerySpec]) -> list[dict]:
    return [
        {"query": item.query, "split": item.split, "kind": item.kind}
        for item in queries
    ]


def _gt_payload(queries: list[QuerySpec]) -> list[dict]:
    return [
        {
            "query": item.query,
            "must_include": list(item.must_include),
            "must_exclude": list(item.must_exclude),
            "acceptable": list(item.acceptable),
        }
        for item in queries
    ]


def load_dataset(path: Path | None = None) -> EvalDataset:
    gt_path = Path(path) if path is not None else DEFAULT_GT_PATH
    raw = json.loads(gt_path.read_text(encoding="utf-8"))
    query_set_version = str(raw.get("query_set_version") or "")
    gt_version = str(raw.get("gt_version") or "")
    if not query_set_version or not gt_version:
        raise ValueError("Ground truth file must set query_set_version and gt_version.")
    queries: list[QuerySpec] = []
    seen = set()
    for item in raw.get("queries") or []:
        query = str(item.get("query") or "").strip()
        split = str(item.get("split") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not query:
            raise ValueError("Each evaluation query needs a non-empty query string.")
        if query in seen:
            raise ValueError(f"Duplicate evaluation query: {query}")
        if split not in SPLITS:
            raise ValueError(f"Query {query!r} has invalid split {split!r}.")
        if kind not in QUERY_KINDS:
            raise ValueError(f"Query {query!r} has invalid kind {kind!r}.")
        must_include = _names(item.get("must_include"))
        must_exclude = _names(item.get("must_exclude"))
        acceptable = _names(item.get("acceptable"))
        overlap = (
            (set(must_include) & set(must_exclude))
            | (set(must_include) & set(acceptable))
            | (set(must_exclude) & set(acceptable))
        )
        if overlap:
            raise ValueError(f"Query {query!r} has overlapping GT labels: {sorted(overlap)}")
        seen.add(query)
        queries.append(
            QuerySpec(
                query=query,
                split=split,
                kind=kind,
                must_include=tuple(must_include),
                must_exclude=tuple(must_exclude),
                acceptable=tuple(acceptable),
                notes=str(item.get("notes") or ""),
            )
        )
    if not queries:
        raise ValueError("Ground truth file contains no queries.")
    splits = {spec.split for spec in queries}
    if splits != set(SPLITS):
        raise ValueError("Evaluation queries must include both dev and holdout.")
    kinds = {spec.kind for spec in queries}
    missing_kinds = [kind for kind in QUERY_KINDS if kind not in kinds]
    if missing_kinds:
        raise ValueError(f"Evaluation queries missing kinds: {missing_kinds}")
    policy = raw.get("acceptable_policy") or {}
    if str(policy.get("name") or "") != ACCEPTABLE_POLICY_NAME:
        raise ValueError("acceptable_policy.name must be lenient_ignore.")
    return EvalDataset(
        path=gt_path,
        query_set_version=query_set_version,
        gt_version=gt_version,
        query_set_hash=canonical_sha256(_query_set_payload(queries)),
        gt_hash=canonical_sha256(_gt_payload(queries)),
        acceptable_policy=dict(policy),
        gt_corrections=tuple(raw.get("gt_corrections") or ()),
        queries=tuple(queries),
    )
