"""User-facing Workflow blocks. Internal steps stay Find / Narrow / Act."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.actions.models import (
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
)
from app.i18n import t
from app.ui.design_tokens import COLORS
from app.workspace.context import ORIGIN_BROWSE, ORIGIN_MEANING, ORIGIN_TEXT
from app.workspace.plan import (
    ALLOWED_ACTION_IDS,
    ALLOWED_STEP_TYPES,
    STEP_ACTION,
    STEP_FIND,
    STEP_NARROW,
    PlanStep,
)

CATEGORY_TRIGGER = "trigger"
CATEGORY_SELECT = "select"
CATEGORY_TARGET = "target"
CATEGORY_SEARCH = "target"
CATEGORY_CONDITION = "condition"
CATEGORY_ACTION = "action"
CATEGORY_LOGIC = "logic"
CATEGORY_AI = "ai"

CATALOG_CATEGORY_ORDER = (
    CATEGORY_TRIGGER,
    CATEGORY_SELECT,
    CATEGORY_TARGET,
    CATEGORY_CONDITION,
    CATEGORY_ACTION,
)

BUILDER_SELECT_IDS = frozenset({"folder"})
BUILDER_SEARCH_IDS = frozenset({"all", "text", "meaning"})
BUILDER_ACTION_IDS = frozenset({ACTION_MOVE, ACTION_ADD_TAG, ACTION_REMOVE_TAG})

KIND_START = "start"
KIND_TARGET = "target"
KIND_ACT = "action"
KIND_UNSUPPORTED = "unsupported"

KIND_FIND = "find"
KIND_SELECT = "select"

TRIGGER_FOLDER = "folder"
TRIGGER_EVENT = "event"
TRIGGER_TIME = "time"

TARGET_ALL = "all"
TARGET_TEXT = "text"
TARGET_MEANING = "meaning"
TARGET_NARROW = "narrow"

START_BLOCK_ID = "start"
TARGET_BLOCK_ID = "target"

ACTION_LABEL_KEYS = {
    ACTION_MOVE: "automation.action_move",
    ACTION_ADD_TAG: "automation.action_add_tag",
    ACTION_REMOVE_TAG: "automation.action_remove_tag",
    ACTION_CREATE_FOLDER: "automation.action_create_folder",
    ACTION_RENAME: "automation.action_rename",
}


@dataclass(frozen=True)
class BlockCategoryStyle:
    key: str
    label_key: str
    ink: str
    fill: str
    glyph: str


CATEGORY_STYLES = {
    CATEGORY_SELECT: BlockCategoryStyle(
        CATEGORY_SELECT, "automation.category_select", COLORS.select, COLORS.select_soft, "\uE8B7"
    ),
    CATEGORY_TRIGGER: BlockCategoryStyle(
        CATEGORY_TRIGGER, "automation.category_trigger", COLORS.trigger, COLORS.trigger_soft, "\uEA6C"
    ),
    CATEGORY_TARGET: BlockCategoryStyle(
        CATEGORY_TARGET, "automation.category_search", COLORS.target, COLORS.target_soft, "\uE721"
    ),
    CATEGORY_ACTION: BlockCategoryStyle(
        CATEGORY_ACTION, "automation.category_action", COLORS.success, COLORS.success_soft, "\uE70F"
    ),
    CATEGORY_CONDITION: BlockCategoryStyle(
        CATEGORY_CONDITION, "automation.category_condition", COLORS.warning, COLORS.warning_soft, "\uE8FD"
    ),
    CATEGORY_LOGIC: BlockCategoryStyle(
        CATEGORY_LOGIC, "automation.category_logic", COLORS.warning, COLORS.warning_soft, "\uE8FD"
    ),
    CATEGORY_AI: BlockCategoryStyle(
        CATEGORY_AI, "automation.category_ai", COLORS.ai, COLORS.ai_soft, "\uE99A"
    ),
}


@dataclass(frozen=True)
class VisualBlock:
    """One Puzzle block. Start/Target may exist without a PlanStep."""

    block_id: str
    category: str
    visual_kind: str
    title: str
    summary: str
    locked: bool = False
    uses_ai: bool = False
    enabled: bool = True
    step: PlanStep | None = None
    target_mode: str = ""
    trigger_kind: str = ""
    icon_key: str = ""


@dataclass(frozen=True)
class CatalogItem:
    category: str
    item_id: str
    label_key: str
    icon_key: str = "folder"
    enabled: bool = True
    uses_ai: bool = False
    coming_soon: bool = False


def category_style(category: str) -> BlockCategoryStyle:
    return CATEGORY_STYLES.get(category, CATEGORY_STYLES[CATEGORY_LOGIC])


def block_can_delete(block: VisualBlock) -> bool:
    if block.locked or block.block_id == START_BLOCK_ID:
        return False
    if block.category in {CATEGORY_TRIGGER, CATEGORY_SELECT} and block.block_id == START_BLOCK_ID:
        return False
    if block.category == CATEGORY_TARGET and block.step is None:
        return False
    return True


def block_kind(step: PlanStep) -> str:
    if step.type == STEP_FIND:
        return KIND_FIND
    if step.type == STEP_NARROW:
        return KIND_SELECT
    if step.type == STEP_ACTION and step.action_id in ALLOWED_ACTION_IDS:
        return KIND_ACT
    return KIND_UNSUPPORTED


def block_category(step: PlanStep) -> str:
    kind = block_kind(step)
    if kind == KIND_FIND:
        return CATEGORY_TARGET
    if kind == KIND_SELECT:
        return CATEGORY_TARGET
    if kind == KIND_ACT:
        return CATEGORY_ACTION
    if step.type not in ALLOWED_STEP_TYPES:
        return CATEGORY_LOGIC
    return CATEGORY_LOGIC


def action_label(action_id: str) -> str:
    key = ACTION_LABEL_KEYS.get(action_id)
    if key:
        return t(key)
    text = str(action_id or "").replace("_", " ").strip()
    return text.title() if text else t("automation.block_action")


def block_title(step: PlanStep, *, origin: str = ORIGIN_MEANING) -> str:
    kind = block_kind(step)
    if kind == KIND_FIND:
        return target_title(target_mode_from_origin(origin))
    if kind == KIND_SELECT:
        return t("automation.block_narrow")
    if kind == KIND_ACT:
        return action_label(step.action_id)
    return t("automation.block_unsupported")


def block_summary(step: PlanStep, *, origin: str = ORIGIN_MEANING) -> str:
    kind = block_kind(step)
    if kind == KIND_FIND:
        return step.query or t("automation.param_query_empty")
    if kind == KIND_SELECT:
        return step.query or t("automation.param_query_empty")
    if kind != KIND_ACT:
        return t("automation.block_unsupported_hint")
    if step.action_id in {ACTION_ADD_TAG, ACTION_REMOVE_TAG}:
        return str(step.parameters.get("tag") or t("automation.param_tag_empty"))
    if step.action_id == ACTION_MOVE:
        dest = str(step.parameters.get("destination_name") or "").strip()
        return folder_display_name(dest) if dest else t("automation.param_destination_empty")
    if step.action_id == ACTION_CREATE_FOLDER:
        return str(step.parameters.get("name") or t("automation.param_folder_empty"))
    if step.action_id == ACTION_RENAME:
        if step.parameters.get("generate_names"):
            return t("automation.param_rename_generate")
        return str(step.parameters.get("new_name") or t("automation.param_name_empty"))
    return action_label(step.action_id)


def target_mode_from_origin(origin: str) -> str:
    if origin == ORIGIN_TEXT:
        return TARGET_TEXT
    if origin == ORIGIN_BROWSE:
        return TARGET_ALL
    return TARGET_MEANING


def origin_from_target_mode(mode: str) -> str:
    if mode == TARGET_TEXT:
        return ORIGIN_TEXT
    if mode == TARGET_ALL or not mode:
        return ORIGIN_BROWSE
    return ORIGIN_MEANING


def target_title(mode: str) -> str:
    if mode == TARGET_TEXT:
        return t("automation.block_text_search")
    if mode == TARGET_MEANING:
        return t("automation.block_meaning_search")
    if mode == TARGET_NARROW:
        return t("automation.block_narrow")
    return t("automation.block_all_images")


def folder_display_name(folder: str | None) -> str:
    text = str(folder or "").strip()
    if not text:
        return t("automation.choose_folder")
    return Path(text).name or text


def start_summary(folder: str | None) -> str:
    text = str(folder or "").strip()
    if not text:
        return t("automation.choose_folder")
    return text


def user_step_summary(step: PlanStep, *, origin: str = ORIGIN_MEANING) -> str:
    kind = block_kind(step)
    if kind == KIND_FIND:
        mode = target_mode_from_origin(origin)
        if mode == TARGET_ALL:
            return t("automation.block_all_images")
        return t("automation.step_target", name=target_title(mode), query=step.query or "—")
    if kind == KIND_SELECT:
        return t("automation.step_target", name=t("automation.block_narrow"), query=step.query or "—")
    if kind == KIND_ACT:
        return action_label(step.action_id)
    return t("automation.block_unsupported")


def workflow_step_summary(steps: tuple[PlanStep, ...], *, folder: str | None = None, origin: str = "") -> str:
    resolved_origin = origin or infer_origin_from_steps(steps)
    parts = [t("automation.block_folder", name=folder_display_name(folder))]
    search = [step for step in steps if step.type in {STEP_FIND, STEP_NARROW}]
    if not search:
        parts.append(t("automation.block_all_images"))
    else:
        parts.extend(user_step_summary(step, origin=resolved_origin) for step in search)
    parts.extend(user_step_summary(step, origin=resolved_origin) for step in steps if step.type == STEP_ACTION)
    parts.extend(user_step_summary(step, origin=resolved_origin) for step in steps if block_kind(step) == KIND_UNSUPPORTED)
    return " → ".join(parts)


def infer_origin_from_steps(steps: tuple[PlanStep, ...] | list[PlanStep]) -> str:
    if any(step.type == STEP_FIND for step in steps):
        return ORIGIN_MEANING
    return ORIGIN_BROWSE


def make_find_step(query: str = "") -> PlanStep:
    return PlanStep(step_id="", type=STEP_FIND, query=str(query or "").strip())


def make_select_step(query: str = "") -> PlanStep:
    return PlanStep(step_id="", type=STEP_NARROW, query=str(query or "").strip())


def make_act_step(action_id: str, parameters: dict | None = None) -> PlanStep:
    return PlanStep(
        step_id="",
        type=STEP_ACTION,
        action_id=str(action_id or "").strip(),
        parameters=dict(parameters or {}),
    )


def _catalog(
    category: str,
    item_id: str,
    label_key: str,
    icon_key: str,
    *,
    enabled: bool = True,
    uses_ai: bool = False,
) -> CatalogItem:
    return CatalogItem(
        category=category,
        item_id=item_id,
        label_key=label_key,
        icon_key=icon_key,
        enabled=enabled,
        uses_ai=uses_ai,
        coming_soon=False,
    )


def catalog_item_is_builder_ready(item: CatalogItem) -> bool:
    """Future catalog rows are visible but never added to a workflow."""
    if not item.enabled:
        return False
    if item.category == CATEGORY_SELECT:
        return item.item_id in BUILDER_SELECT_IDS
    if item.category == CATEGORY_TARGET:
        return item.item_id in BUILDER_SEARCH_IDS
    if item.category == CATEGORY_ACTION:
        return item.item_id in BUILDER_ACTION_IDS
    return False


def add_block_catalog() -> tuple[CatalogItem, ...]:
    """Visible Add Block rows. Enabled first in each category; future rows stay disabled."""
    later = dict(enabled=False)
    return (
        _catalog(CATEGORY_TRIGGER, "manual_run", "automation.trigger_manual_run", "play", **later),
        _catalog(CATEGORY_TRIGGER, "files_added", "automation.trigger_files_added", "file_plus", **later),
        _catalog(CATEGORY_TRIGGER, "daily", "automation.trigger_daily", "calendar", **later),
        _catalog(CATEGORY_TRIGGER, "specific_time", "automation.trigger_specific_time", "clock", **later),
        _catalog(CATEGORY_SELECT, TRIGGER_FOLDER, "automation.trigger_folder", "folder"),
        _catalog(CATEGORY_SELECT, "multiple_folders", "automation.select_multiple_folders", "folders", **later),
        _catalog(CATEGORY_SELECT, "favorites", "automation.select_favorites", "star", **later),
        _catalog(CATEGORY_SELECT, "tagged_images", "automation.select_tagged_images", "tag", **later),
        _catalog(CATEGORY_TARGET, TARGET_ALL, "automation.block_all_images", "images"),
        _catalog(CATEGORY_TARGET, TARGET_TEXT, "automation.block_text_search", "text_search"),
        _catalog(
            CATEGORY_TARGET,
            TARGET_MEANING,
            "automation.block_meaning_search",
            "meaning_search",
            uses_ai=True,
        ),
        _catalog(CATEGORY_TARGET, "similar", "automation.search_similar", "similar", **later),
        _catalog(CATEGORY_TARGET, "duplicates", "automation.search_duplicates", "copy", **later),
        _catalog(CATEGORY_CONDITION, "tag_exists", "automation.condition_tag_exists", "tag", **later),
        _catalog(CATEGORY_CONDITION, "filename_contains", "automation.condition_filename_contains", "file", **later),
        _catalog(CATEGORY_CONDITION, "is_favorite", "automation.condition_is_favorite", "star", **later),
        _catalog(CATEGORY_CONDITION, "duplicate_found", "automation.condition_duplicate_found", "copy", **later),
        _catalog(CATEGORY_ACTION, ACTION_MOVE, "automation.action_move", "move"),
        _catalog(CATEGORY_ACTION, ACTION_ADD_TAG, "automation.action_add_tag", "add_tag"),
        _catalog(CATEGORY_ACTION, ACTION_REMOVE_TAG, "automation.action_remove_tag", "remove_tag"),
        _catalog(CATEGORY_ACTION, ACTION_RENAME, "automation.action_rename", "rename", **later),
        _catalog(CATEGORY_ACTION, "favorites_add", "automation.action_favorites_add", "star", **later),
        _catalog(CATEGORY_ACTION, "delete", "automation.action_delete", "delete", **later),
    )


def visual_blocks_for(
    *,
    folder: str | None,
    origin: str,
    steps: tuple[PlanStep, ...] | list[PlanStep],
    include_default_target: bool = True,
) -> list[VisualBlock]:
    items: list[VisualBlock] = [
        VisualBlock(
            block_id=START_BLOCK_ID,
            category=CATEGORY_SELECT,
            visual_kind=TRIGGER_FOLDER,
            title=t("automation.trigger_folder"),
            summary=folder_display_name(folder) if folder else t("automation.choose_folder"),
            locked=True,
            trigger_kind=TRIGGER_FOLDER,
            icon_key="folder",
        )
    ]
    search = [step for step in steps if step.type in {STEP_FIND, STEP_NARROW}]
    actions = [step for step in steps if step.type == STEP_ACTION]
    other = [step for step in steps if block_kind(step) == KIND_UNSUPPORTED]
    if not search and include_default_target:
        items.append(
            VisualBlock(
                block_id=TARGET_BLOCK_ID,
                category=CATEGORY_TARGET,
                visual_kind=TARGET_ALL,
                title=t("automation.block_all_images"),
                summary=t("automation.target_all_hint"),
                locked=False,
                target_mode=TARGET_ALL,
                icon_key="images",
            )
        )
    if search:
        first = search[0]
        mode = TARGET_NARROW if first.type == STEP_NARROW else target_mode_from_origin(origin)
        items.append(
            VisualBlock(
                block_id=first.step_id or TARGET_BLOCK_ID,
                category=CATEGORY_TARGET,
                visual_kind=mode,
                title=target_title(mode if mode != TARGET_NARROW else TARGET_NARROW),
                summary=first.query or t("automation.param_query_empty"),
                locked=False,
                uses_ai=mode == TARGET_MEANING,
                step=first,
                target_mode=mode,
                icon_key=_search_icon_key(mode),
            )
        )
        for extra in search[1:]:
            extra_mode = TARGET_NARROW if extra.type == STEP_NARROW else target_mode_from_origin(origin)
            items.append(
                VisualBlock(
                    block_id=extra.step_id or f"target_{len(items)}",
                    category=CATEGORY_TARGET,
                    visual_kind=extra_mode,
                    title=target_title(extra_mode),
                    summary=extra.query or t("automation.param_query_empty"),
                    uses_ai=extra_mode == TARGET_MEANING,
                    step=extra,
                    target_mode=extra_mode,
                    icon_key=_search_icon_key(extra_mode),
                )
            )
    for step in actions:
        items.append(
            VisualBlock(
                block_id=step.step_id or f"action_{len(items)}",
                category=CATEGORY_ACTION,
                visual_kind=KIND_ACT,
                title=action_label(step.action_id),
                summary=block_summary(step, origin=origin),
                step=step,
                icon_key=_action_icon_key(step.action_id),
            )
        )
    for step in other:
        items.append(
            VisualBlock(
                block_id=step.step_id or f"bad_{len(items)}",
                category=CATEGORY_LOGIC,
                visual_kind=KIND_UNSUPPORTED,
                title=t("automation.block_unsupported"),
                summary=t("automation.block_unsupported_hint"),
                step=step,
                icon_key="logic",
            )
        )
    return items


def _search_icon_key(mode: str) -> str:
    if mode == TARGET_TEXT:
        return "text_search"
    if mode == TARGET_MEANING:
        return "meaning_search"
    return "images"


def _action_icon_key(action_id: str) -> str:
    return {
        ACTION_MOVE: "move",
        ACTION_RENAME: "rename",
        ACTION_ADD_TAG: "add_tag",
        ACTION_REMOVE_TAG: "remove_tag",
        ACTION_CREATE_FOLDER: "create_folder",
    }.get(action_id, "move")


def compile_search_steps(target_mode: str, query: str, extra: list[PlanStep] | None = None) -> list[PlanStep]:
    steps: list[PlanStep] = []
    if target_mode == TARGET_TEXT:
        steps.append(make_find_step(query))
    elif target_mode == TARGET_MEANING:
        steps.append(make_find_step(query))
    elif target_mode == TARGET_NARROW:
        steps.append(make_select_step(query))
    extras = extra or ()
    if target_mode == TARGET_NARROW:
        extras = extras[1:]
    for step in extras:
        if step.type == STEP_NARROW:
            steps.append(step)
    return steps


def default_target_mode(steps: tuple[PlanStep, ...] | list[PlanStep], origin: str) -> str:
    search = [step for step in steps if step.type in {STEP_FIND, STEP_NARROW}]
    if not search:
        return TARGET_ALL
    if search[0].type == STEP_NARROW:
        return TARGET_NARROW
    return target_mode_from_origin(origin)


def primary_search_query(steps: tuple[PlanStep, ...] | list[PlanStep]) -> str:
    for step in steps:
        if step.type in {STEP_FIND, STEP_NARROW}:
            return step.query
    return ""
