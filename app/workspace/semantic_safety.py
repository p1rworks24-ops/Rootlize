"""Semantic safety checks for Planner structured output.

This is not local intent routing. It does not choose an Action from keywords.
It only rejects dangerous meaning mix-ups: unsupported destructive or tool
requests mapped onto a registered Action, or sent to Meaning Search.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from app.workspace.context import SearchResultContext

CATEGORY_FILE_DELETE = "file_delete"
CATEGORY_UNSAFE_TOOL = "unsafe_tool"
CATEGORY_UNSUPPORTED_OP = "unsupported_op"

PLAN_STATUS_CLARIFY = "clarify"
PLAN_STATUS_REJECTED = "rejected"

_METADATA_NOUN = (
    r"(?:all\s+(?:of\s+)?(?:the\s+)?)?(?:tags?|favorites?|favourites?|stars?|"
    r"metadata|タグ|お気に入り)"
)
_FILE_NOUN = r"(?:images?|files?|photos?|screenshots?|pictures?|画像|ファイル|写真)"
_TRASH_NAME = re.compile(
    r"^(?:the\s+)?(?:trash|recycle\s*bin|ごみ箱|ゴミ箱)$",
    re.I,
)

_REDEFINE_DELETE = re.compile(
    r"(?:pretend|treat|redefine)\b.+\bdelete\b|"
    r"\bdelete\b.{0,40}(?:means|is actually|should mean)|"
    r"削除.{0,20}(?:は|を).{0,20}(?:タグ|お気に入り).{0,12}(?:意味|みな)",
    re.I,
)
_METADATA_REMOVE = re.compile(
    rf"(?:remove|clear|delete|erase|消|外|はず|削除).{{0,48}}{_METADATA_NOUN}|"
    rf"{_METADATA_NOUN}.{{0,24}}(?:remove|clear|delete|erase|消|外|はず|削除)|"
    r"remove\s+favorite|"
    r"お気に入りを?(?:外|はず|解除)|"
    r"タグを?(?:全部|すべて|全て)?(?:消|外|はず|削除)",
    re.I,
)
_MOVE_TO_NAMED_FOLDER = re.compile(
    r"(?:(?:please\s+)?move\s+(?:all\s+(?:of\s+)?)?(?:these|those|them|the\s+"
    rf"(?:selected\s+)?{_FILE_NOUN}|the\s+results?)\s+to\s+(?:the\s+)?(?P<dest>.+?)(?:\s+folder)?|"
    rf"(?:(?:please\s+)?move\s+to\s+(?:the\s+)?(?P<dest_only>.+?)(?:\s+folder)?)|"
    r"(?:これらの)?(?:画像|ファイル|写真|結果)を(?P<ja_dest>.+?)(?:フォルダ|フォルダー)?(?:に|へ)移動|"
    r"(?P<ja_dest_only>.+?)(?:フォルダ|フォルダー)?(?:に|へ)移動)"
    r"(?:して(?:ください)?|したい)?[。！!.]?\s*$",
    re.I,
)
_MOVE_TO_TRASH = re.compile(
    r"(?:move|put|place)\s+.{0,80}\s+to\s+(?:the\s+)?(?:trash|recycle\s*bin)(?:\s+folder)?|"
    r"(?:ゴミ箱|ごみ箱)(?:に|へ)移動",
    re.I,
)
_FILE_DELETE = re.compile(
    rf"(?:permanently\s+)?(?:delete|erase|destroy)\s+"
    rf"(?:all\s+(?:of\s+)?)?(?:these|those|them|the\s+selected|selected|the)\b|"
    rf"(?:permanently\s+)?(?:delete|erase|destroy)\s+(?:all\s+(?:of\s+)?)?(?:the\s+)?{_FILE_NOUN}|"
    rf"remove\s+(?:all\s+(?:of\s+)?)?(?:these|those|the\s+selected|selected|the)\s+{_FILE_NOUN}|"
    r"remove\s+the\s+files\b|"
    rf"trash\s+(?:all\s+(?:of\s+)?)?(?:these|those|them|the\s+selected|the)\s*{_FILE_NOUN}?|"
    r"(?:send|put)\s+(?:these|those|them|the\s+files|the\s+images)\s+to\s+(?:the\s+)?(?:trash|recycle\s*bin)|"
    rf"(?:これらの)?(?:画像|ファイル|写真)を?(?:全部|すべて|全て)?(?:削除|消して|消す)|"
    r"(?:全部|すべて|全て)(?:の)?(?:これら|この)?(?:画像|ファイル|写真)?を?(?:削除|消して|消す)|"
    r"(?:削除して(?:ください)?|削除する|消してください)|"
    r"(?:ゴミ箱|ごみ箱)に(?:捨て|入れ)",
    re.I,
)
_UNSAFE_TOOL = re.compile(
    r"(?:use|run|execute|call|via|through)\s+(?:the\s+)?(?:a\s+)?"
    r"(?:shell|powershell|pwsh|cmd(?:\.exe)?|bash|/bin/sh|sql|script|python|"
    r"command(?:\s+line)?)|"
    r"(?:shell|powershell|sql|script)\s+(?:to|command|query)|"
    r"\b(?:cmd\.exe|/bin/sh)\b|"
    r"\b(?:database command|sql query|sql command)\b|"
    r"(?:シェル|パワーシェル|スクリプト|SQL)で|"
    r"SQL(?:を|で)|"
    r"\buse sql\b",
    re.I,
)
_UNSUPPORTED_OP = re.compile(
    r"(?:(?:please\s+)?(?:copy|duplicate|export)\s+"
    rf"(?:all\s+(?:of\s+)?)?(?:these|those|them|the\s+selected|the)\b|"
    rf"(?:these|those|the)\s+{_FILE_NOUN}.{{0,24}}\b(?:copy|duplicate|export)\b|"
    r"\bundo\b(?:\s+(?:that|this|it|the\s+last(?:\s+\w+)?)?)?|"
    r"(?:コピー|複製|書き出|エクスポート)して|"
    r"元に戻して)",
    re.I,
)

_MOVE_ACTIONS = frozenset({"move", "create_folder"})
_SAFE_INTENTS = frozenset({"unsupported"})

MESSAGE_KEYS = {
    CATEGORY_FILE_DELETE: "images.ai.not_available_delete",
    CATEGORY_UNSAFE_TOOL: "images.ai.not_available_script",
    CATEGORY_UNSUPPORTED_OP: "images.ai.not_available",
}
REASON_CODES = {
    CATEGORY_FILE_DELETE: "delete_unsupported",
    CATEGORY_UNSAFE_TOOL: "unsafe_tool",
    CATEGORY_UNSUPPORTED_OP: "unsupported_capability",
}


@dataclass(frozen=True)
class SemanticSafetyResult:
    ok: bool
    status: str = PLAN_STATUS_REJECTED
    reasons: tuple[str, ...] = ()
    message_key: str = ""


def request_risk_category(instruction: str) -> str | None:
    """Return a dangerous request category, or None when this layer has no objection."""
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return None
    if _UNSAFE_TOOL.search(raw):
        return CATEGORY_UNSAFE_TOOL
    if _looks_like_file_delete(raw):
        return CATEGORY_FILE_DELETE
    if _UNSUPPORTED_OP.search(raw):
        return CATEGORY_UNSUPPORTED_OP
    return None


def validate_semantic_safety(
    instruction: str,
    *,
    intent: str = "",
    action_ids: Iterable[str] = (),
    destination_name: str = "",
    context: SearchResultContext | None = None,
) -> SemanticSafetyResult | None:
    """Reject Planner output that maps a dangerous request onto another capability.

    Returns None when this layer has no objection. Other validators still apply.
    """
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return None
    actions = tuple(
        str(action_id or "").strip().lower()
        for action_id in action_ids
        if str(action_id or "").strip()
    )
    intent_key = str(intent or "").strip().lower()
    dest = str(destination_name or "").strip() or _move_destination(raw)

    trash_move = _is_move_to_trash(raw, dest)
    if trash_move:
        return _validate_trash_move(intent_key, actions, dest, context)

    category = request_risk_category(raw)
    if category is None:
        return None
    if intent_key in _SAFE_INTENTS and not actions:
        return None
    return SemanticSafetyResult(
        ok=False,
        status=PLAN_STATUS_REJECTED,
        reasons=("semantic_mismatch", REASON_CODES[category]),
        message_key=MESSAGE_KEYS[category],
    )


def message_key_for_instruction(instruction: str, reasons: Iterable[str] = ()) -> str:
    category = request_risk_category(instruction)
    if category is not None:
        return MESSAGE_KEYS[category]
    blob = f"{instruction} {' '.join(str(item) for item in reasons)}".lower()
    if "delete" in blob or "削除" in str(instruction or "") or "trash" in blob:
        return "images.ai.not_available_delete"
    if "shell" in blob or "sql" in blob or "python" in blob or "script" in blob:
        return "images.ai.not_available_script"
    return "images.ai.not_available"


def _looks_like_file_delete(raw: str) -> bool:
    if _REDEFINE_DELETE.search(raw):
        return True
    if _is_move_to_trash(raw, _move_destination(raw)):
        return False
    file_hit = bool(_FILE_DELETE.search(raw))
    meta_hit = bool(_METADATA_REMOVE.search(raw))
    if meta_hit and not _direct_file_remove(raw):
        return False
    return file_hit


def _direct_file_remove(raw: str) -> bool:
    return bool(
        re.search(
            rf"(?:remove|delete|erase|destroy)\s+(?:all\s+(?:of\s+)?)?"
            rf"(?:these|those|the\s+selected|selected|the)\s+{_FILE_NOUN}|"
            r"remove\s+the\s+files\b|"
            rf"(?:画像|ファイル|写真)を?(?:削除|消して|消す)",
            raw,
            re.I,
        )
    )


def _move_destination(raw: str) -> str:
    match = _MOVE_TO_NAMED_FOLDER.search(raw)
    if match is None:
        return ""
    return _first(
        match.groupdict().get("dest"),
        match.groupdict().get("dest_only"),
        match.groupdict().get("ja_dest"),
        match.groupdict().get("ja_dest_only"),
    )


def _is_move_to_trash(raw: str, destination_name: str) -> bool:
    if _MOVE_TO_TRASH.search(raw):
        return True
    dest = destination_name or _move_destination(raw)
    return bool(dest) and bool(_TRASH_NAME.match(dest.strip())) and bool(
        re.search(r"\bmove\b|移動", raw, re.I)
    )


def _validate_trash_move(
    intent: str,
    actions: tuple[str, ...],
    destination_name: str,
    context: SearchResultContext | None,
) -> SemanticSafetyResult | None:
    if actions and not set(actions) <= _MOVE_ACTIONS:
        return SemanticSafetyResult(
            ok=False,
            status=PLAN_STATUS_REJECTED,
            reasons=("semantic_mismatch", "unsupported_capability"),
            message_key="images.ai.not_available",
        )
    if intent in _SAFE_INTENTS and not actions:
        return None
    dest = destination_name.strip() or "Trash"
    if _destination_exists(dest, context):
        return None
    return SemanticSafetyResult(
        ok=False,
        status=PLAN_STATUS_CLARIFY,
        reasons=("ambiguous_trash_destination",),
        message_key="images.ai.which_destination",
    )


def _destination_exists(name: str, context: SearchResultContext | None) -> bool:
    folder = str(getattr(context, "scope_folder", "") or "").strip() if context else ""
    cleaned = name.strip()
    if not folder or not cleaned or cleaned in {".", ".."}:
        return False
    if "/" in cleaned or "\\" in cleaned:
        return False
    try:
        return (Path(folder) / cleaned).is_dir()
    except OSError:
        return False


def _first(*values: str | None) -> str:
    for value in values:
        text = str(value or "").strip().rstrip(".!?").strip()
        if text:
            return text
    return ""
