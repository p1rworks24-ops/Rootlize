"""Tag-removal interpretation for Ask AI plans.

Not a keyword router. The Planner still chooses the Action; this only
stops guessed tags and maps unnamed collective removal to remove_all_tags.
"""
from __future__ import annotations

import re
from dataclasses import replace

from app.actions.models import ACTION_REMOVE_ALL_TAGS, ACTION_REMOVE_TAG
from app.utils.tag_format import parse_tag_names

STEP_ACTION = "action"

GENERIC_TAG_WORDS = frozenset(
    {"tag", "tags", "the", "the tag", "the tags", "these", "those", "them", "this", "タグ"}
)

_ALL_TAGS = re.compile(
    r"(?:remove|clear|delete|untag)\s+(?:all|every)\s+(?:of\s+)?(?:the\s+)?tags?\b|"
    r"clear\s+(?:the\s+)?tags?\b|"
    r"take\s+(?:the\s+)?tags?\s+off|"
    r"タグを?(?:全部|すべて|全て)(?:消|外|はず|削除)|"
    r"(?:全部|すべて|全て)の?タグを?(?:消|外|はず|削除)",
    re.I,
)
_UNNAMED_TAGS = re.compile(
    r"(?:remove|clear|delete|untag)\s+(?:the\s+)?tags?"
    r"(?:\s+(?:from|off|on|for)\b|\s*$)|"
    r"(?:この|その)?(?:画像たち?の)?タグを(?:外|はず|削除|消)",
    re.I,
)
_NAMED_TAG = re.compile(
    r"(?:remove|clear|untag|delete)\s+(?:the\s+)?(?!all\b|every\b|the\s+tags?\b|tags?\b)(.+?)\s+tags?\b|"
    r"(?:remove|clear|untag|delete)\s+(?:the\s+)?(?!all\b|every\b|the\s+tags?\b|tags?\b)(.+?)\s+from\b|"
    r"[\"「']([^\"」']+)[\"」']\s*タグ|"
    r"(?:^|[\s、])(?!この|その|画像|たち)([\w\-]+)タグを?(?:外|はず|削除)",
    re.I,
)
_LATIN_WORD = re.compile(r"[A-Za-z0-9_\-]+")


def looks_like_unnamed_tag_clear(instruction: str) -> bool:
    """True when the user asked to clear tags as a set, without naming one."""
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return False
    if named_tags_in_instruction(raw):
        return False
    if _ALL_TAGS.search(raw):
        return True
    return bool(_UNNAMED_TAGS.search(raw))


def named_tags_in_instruction(instruction: str) -> tuple[str, ...]:
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return ()
    match = _NAMED_TAG.search(raw)
    if match is None:
        return ()
    blob = next((group for group in match.groups() if group), "")
    names = []
    for tag in parse_tag_names(blob):
        cleaned = _strip_tag_word(tag)
        if cleaned and cleaned.casefold() not in GENERIC_TAG_WORDS:
            names.append(cleaned)
    return tuple(dict.fromkeys(names))


def tag_mentioned_in_instruction(tag: str, instruction: str) -> bool:
    name = str(tag or "").strip()
    raw = " ".join(str(instruction or "").strip().split())
    if not name or not raw:
        return False
    folded = raw.casefold()
    needle = name.casefold()
    if needle in GENERIC_TAG_WORDS:
        return False
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", name):
        return needle in folded
    return any(token.casefold() == needle for token in _LATIN_WORD.findall(raw))


def apply_tag_removal_semantics(plan):
    """Rewrite guessed/unnamed remove_tag steps. Does not invent tags from the catalog."""
    if plan is None or not plan.steps:
        return plan, ()
    instruction = plan.instruction
    unnamed = looks_like_unnamed_tag_clear(instruction)
    reasons: list[str] = []
    steps = []
    changed = False
    for step in plan.steps:
        if step.type != STEP_ACTION or step.action_id != ACTION_REMOVE_TAG:
            steps.append(step)
            continue
        tags = parse_tag_names(step.parameters.get("tags") or step.parameters.get("tag"))
        tags = tuple(tag for tag in tags if tag.casefold() not in GENERIC_TAG_WORDS)
        if not tags:
            if unnamed:
                steps.append(_as_remove_all(step))
                changed = True
                continue
            reasons.append("missing_parameter")
            steps.append(step)
            continue
        mentioned = tuple(tag for tag in tags if tag_mentioned_in_instruction(tag, instruction))
        if unnamed and (not mentioned or mentioned != tags):
            steps.append(_as_remove_all(step))
            changed = True
            continue
        if mentioned != tags:
            reasons.append("guessed_tag")
            steps.append(step)
            continue
        if mentioned != tuple(parse_tag_names(step.parameters.get("tags") or step.parameters.get("tag"))):
            parameters = dict(step.parameters)
            if len(mentioned) == 1:
                parameters.pop("tags", None)
                parameters["tag"] = mentioned[0]
            else:
                parameters.pop("tag", None)
                parameters["tags"] = list(mentioned)
            steps.append(replace(step, parameters=parameters))
            changed = True
            continue
        steps.append(step)
    if not changed:
        return plan, tuple(dict.fromkeys(reasons))
    return replace(plan, steps=tuple(steps)), tuple(dict.fromkeys(reasons))


def _as_remove_all(step):
    parameters = {
        key: value
        for key, value in dict(step.parameters).items()
        if key not in {"tag", "tags"}
    }
    return replace(step, action_id=ACTION_REMOVE_ALL_TAGS, parameters=parameters)


def _strip_tag_word(tag: str) -> str:
    text = str(tag or "").strip()
    text = re.sub(r"^(?:the\s+)?tags?\s+", "", text, flags=re.I)
    text = re.sub(r"\s+tags?$", "", text, flags=re.I)
    return text.strip(" 　「」\"'")
