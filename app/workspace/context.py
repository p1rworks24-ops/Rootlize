"""Current Find / Narrow result set, distinct from folder scope and selection."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

ORIGIN_BROWSE = "browse"
ORIGIN_TEXT = "text"
ORIGIN_MEANING = "meaning"

SOURCE_FOLDER = "folder"
SOURCE_RESULT_SET = "result_set"
SOURCE_SELECTION = "selection"

FOCUS_RESULTS = "results"
FOCUS_SELECTION = "selection"


def path_key(path: Path | str | None) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    try:
        return str(candidate.resolve())
    except OSError:
        return str(candidate)


@dataclass(frozen=True)
class SearchResultContext:
    """Reusable working set for Narrow and Act. Prefer image_id over path."""

    result_image_ids: tuple[int, ...] = ()
    result_paths: tuple[str, ...] = ()
    selected_image_ids: tuple[int, ...] = ()
    selected_paths: tuple[str, ...] = ()
    scope_folder: str | None = None
    query: str = ""
    find_query: str = ""
    narrow_query: str = ""
    narrowed: bool = False
    origin: str = ORIGIN_BROWSE
    last_target_focus: str = ""
    path_to_image_id: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_image_ids", tuple(self.result_image_ids))
        object.__setattr__(self, "result_paths", tuple(self.result_paths))
        object.__setattr__(self, "selected_image_ids", tuple(self.selected_image_ids))
        object.__setattr__(self, "selected_paths", tuple(self.selected_paths))
        object.__setattr__(self, "path_to_image_id", dict(self.path_to_image_id or {}))

    def has_result_set(self) -> bool:
        return bool(self.result_image_ids or self.result_paths)

    def has_selection(self) -> bool:
        return bool(self.selected_image_ids or self.selected_paths)

    def has_targets(self, source: str = SOURCE_RESULT_SET) -> bool:
        ids, paths = self.targets(source)
        return bool(ids or paths)

    def targets(self, source: str = SOURCE_RESULT_SET) -> tuple[tuple[int, ...], tuple[str, ...]]:
        if source == SOURCE_SELECTION:
            return self.selected_image_ids, self.selected_paths
        return self.result_image_ids, self.result_paths

    def with_results(
        self,
        *,
        image_ids: tuple[int, ...] | list[int] = (),
        paths: tuple[str, ...] | list[str] | list[Path] = (),
        query: str,
        scope_folder: Path | str | None,
        origin: str,
        narrowed: bool = False,
        path_to_image_id: dict[str, int] | None = None,
    ) -> SearchResultContext:
        normalized_paths = tuple(path_key(path) for path in paths if path)
        mapping = dict(self.path_to_image_id)
        if path_to_image_id:
            mapping.update(
                {path_key(path): int(image_id) for path, image_id in path_to_image_id.items()}
            )
        ids = tuple(int(image_id) for image_id in image_ids)
        if not ids:
            ids = tuple(
                mapping[path]
                for path in normalized_paths
                if path in mapping
            )
        latest = str(query or "")
        return replace(
            self,
            result_image_ids=ids,
            result_paths=normalized_paths,
            query=latest,
            find_query=self.find_query if narrowed and self.find_query else latest,
            narrow_query=latest if narrowed else "",
            scope_folder=path_key(scope_folder) if scope_folder else None,
            origin=origin,
            narrowed=bool(narrowed),
            last_target_focus=FOCUS_RESULTS if (ids or normalized_paths) else "",
            path_to_image_id=mapping,
        )

    def with_selection(
        self,
        *,
        image_ids: tuple[int, ...] | list[int] = (),
        paths: tuple[str, ...] | list[str] | list[Path] = (),
    ) -> SearchResultContext:
        normalized_paths = tuple(path_key(path) for path in paths if path)
        ids = tuple(int(image_id) for image_id in image_ids)
        if not ids:
            ids = tuple(
                self.path_to_image_id[path]
                for path in normalized_paths
                if path in self.path_to_image_id
            )
        if ids or normalized_paths:
            focus = FOCUS_SELECTION
        elif self.has_result_set():
            focus = FOCUS_RESULTS
        else:
            focus = ""
        return replace(
            self,
            selected_image_ids=ids,
            selected_paths=normalized_paths,
            last_target_focus=focus,
        )

    def with_index(self, path_to_image_id: dict[str, int]) -> SearchResultContext:
        mapping = dict(self.path_to_image_id)
        mapping.update(
            {path_key(path): int(image_id) for path, image_id in path_to_image_id.items()}
        )
        result_ids = self.result_image_ids or tuple(
            mapping[path] for path in self.result_paths if path in mapping
        )
        selected_ids = self.selected_image_ids or tuple(
            mapping[path] for path in self.selected_paths if path in mapping
        )
        return replace(
            self,
            path_to_image_id=mapping,
            result_image_ids=result_ids,
            selected_image_ids=selected_ids,
        )

    def with_relocated_paths(self, replacements: Mapping[str, str] | None) -> SearchResultContext:
        mapping_repl = {
            path_key(source): path_key(dest)
            for source, dest in dict(replacements or {}).items()
            if source and dest
        }
        if not mapping_repl:
            return self

        def remap(path: str) -> str:
            key = path_key(path)
            return mapping_repl.get(key, key)

        new_index = {remap(path): image_id for path, image_id in self.path_to_image_id.items()}
        return replace(
            self,
            result_paths=tuple(remap(path) for path in self.result_paths),
            selected_paths=tuple(remap(path) for path in self.selected_paths),
            path_to_image_id=new_index,
        )

    def cleared(self) -> SearchResultContext:
        return SearchResultContext(scope_folder=self.scope_folder)


class WorkspaceSession:
    """Mutable holder for the current SearchResultContext."""

    def __init__(self) -> None:
        self._context = SearchResultContext()

    @property
    def context(self) -> SearchResultContext:
        return self._context

    def set_find(
        self,
        *,
        image_ids: tuple[int, ...] | list[int] = (),
        paths: tuple[str, ...] | list[str] | list[Path] = (),
        query: str,
        scope_folder: Path | str | None,
        origin: str,
        path_to_image_id: dict[str, int] | None = None,
    ) -> SearchResultContext:
        self._context = self._context.with_results(
            image_ids=image_ids,
            paths=paths,
            query=query,
            scope_folder=scope_folder,
            origin=origin,
            narrowed=False,
            path_to_image_id=path_to_image_id,
        )
        return self._context

    def set_narrow(
        self,
        *,
        image_ids: tuple[int, ...] | list[int] = (),
        paths: tuple[str, ...] | list[str] | list[Path] = (),
        query: str,
        path_to_image_id: dict[str, int] | None = None,
    ) -> SearchResultContext:
        self._context = self._context.with_results(
            image_ids=image_ids,
            paths=paths,
            query=query,
            scope_folder=self._context.scope_folder,
            origin=self._context.origin or ORIGIN_MEANING,
            narrowed=True,
            path_to_image_id=path_to_image_id,
        )
        return self._context

    def set_selection(
        self,
        *,
        image_ids: tuple[int, ...] | list[int] = (),
        paths: tuple[str, ...] | list[str] | list[Path] = (),
    ) -> SearchResultContext:
        self._context = self._context.with_selection(image_ids=image_ids, paths=paths)
        return self._context

    def remember_ids(self, path_to_image_id: dict[str, int]) -> SearchResultContext:
        self._context = self._context.with_index(path_to_image_id)
        return self._context

    def relocate_paths(self, replacements: Mapping[str, str] | None) -> SearchResultContext:
        self._context = self._context.with_relocated_paths(replacements)
        return self._context

    def reset(self, *, scope_folder: Path | str | None = None) -> SearchResultContext:
        folder = path_key(scope_folder) if scope_folder else None
        self._context = SearchResultContext(scope_folder=folder)
        return self._context
