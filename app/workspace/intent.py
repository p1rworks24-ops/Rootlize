"""Natural-language turn classification for Find / Narrow / Act.

Produces structured proposals. Does not execute Actions or search.
Target image IDs come from SearchResultContext, not from this parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.actions.models import (
    ACTION_ADD_FAVORITE,
    ACTION_ADD_TAG,
    ACTION_CREATE_FOLDER,
    ACTION_MOVE,
    ACTION_REMOVE_ALL_TAGS,
    ACTION_REMOVE_FAVORITE,
    ACTION_REMOVE_TAG,
    ACTION_RENAME,
    ACTION_REPLACE_TAGS,
)
from app.utils.tag_format import parse_tag_names

from .act import ActionProposal
from .context import (
    SOURCE_FOLDER,
    SOURCE_RESULT_SET,
    SOURCE_SELECTION,
    SearchResultContext,
)
from .targets import is_explicit_selection_request, resolve_action_targets

KIND_FIND = "find"
KIND_NARROW = "narrow"
KIND_ACT = "act"
KIND_ACT_PLAN = "act_plan"
KIND_HELP = "help"
KIND_CLARIFY = "clarify"
KIND_QUESTION = "question"
KIND_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AskAiTurn:
    kind: str
    query: str = ""
    target_source: str = SOURCE_RESULT_SET
    proposal: ActionProposal | None = None
    plan: object | None = None
    message_key: str = ""
    message: str = ""
    reasons: tuple[str, ...] = ()
    used_ai: bool = False
    planner_response_id: str = ""


_HELP = re.compile(
    r"^(?:help|what can (?:you|capixe|rootlize) do|what do you do|"
    r"できること|何ができる|使い方)[?？。.!]?\s*$",
    re.I,
)
_SELECTION_REF = re.compile(
    r"(これら|この画像|この写真|この\d+枚|選択した(?:画像|もの)?|選んだ(?:画像|もの)?|"
    r"\bthese\b|\bthis image\b|\bthis one\b|\bthe selection\b|\bselected(?: images?)?\b)",
    re.I,
)
_RESULT_REF = re.compile(
    r"(この結果|さっきの結果|この検索結果|これらの結果|"
    r"\bthese results\b|\bthis result\b|\bthe (?:current |last |previous )?results?\b|"
    r"\byou (?:just )?(?:searched for|found|looked (?:for|up))\b|"
    r"\b(?:the )?(?:\d+\s+)?(?:\w+\s+)*images? you (?:just )?(?:searched for|found)\b)",
    re.I,
)
_DEICTIC_ONLY = re.compile(
    r"^(?:these|them|those|it|the selection|selected(?: images?)?|"
    r"this image|this one|this|here|the (?:current |last )?results?)(?:\s+images?)?$",
    re.I,
)
_ACTION_VERB = re.compile(
    r"タグを?(?:付け|つけ|外|はず|変更|変えて)|"
    r"(?:add|apply|remove|clear|change|set|update|replace)\s+(?:all\s+)?(?:the\s+)?tags?|"
    r"\btag\b|\buntag\b|"
    r"(?:に|へ)移動|\bmove\b|"
    r"(?:フォルダ|フォルダー)を?作|create\s+(?:a\s+)?folder|"
    r"リネーム|\brename\b|名前に変|"
    r"お気に入り|(?:add\s+)?(?:a\s+)?(?:favorite|favourite)\s+star|"
    r"\b(?:favorite|favourite|unfavorite|unfavourite|unstar)\b",
    re.I,
)
_NARROW_PREFIX = re.compile(
    r"^(?:その中で|この中から|この結果から|さっきの結果から|"
    r"選んだ画像の中で|選択した画像の中で|結果から|"
    r"(?:please\s+)?(?:narrow(?:\s+down)?(?:\s+to)?|"
    r"only show(?:\s+the ones?)?|"
    r"just (?:show|keep)(?:\s+the ones?)?|"
    r"(?:from|among)\s+(?:these|them|those|the results?))[,:]?)\s*",
    re.I,
)
_ONLY_TAIL = re.compile(
    r"(?:だけ|のみ|only(?:\s+the ones?)?)\s*$",
    re.I,
)
_FIND_PREFIX = re.compile(
    r"^(?:please\s+)?(?:find|search(?:\s+for)?|show(?:\s+me)?|look for)\s+",
    re.I,
)
_FIND_SUFFIX = re.compile(
    r"(?:を)?(?:探して(?:ください)?|探す|検索して(?:ください)?|検索する|"
    r"見つけて(?:ください)?|見つける)[。！!]?\s*$"
)
_MOVE = re.compile(
    r"^(?:(?:please\s+)?move\s+(?P<en_target>.+?)\s+to\s+(?:the\s+)?(?P<en_dest>.+?)(?:\s+folder)?|"
    r"(?:please\s+)?move\s+(?P<en_target_here>.+?)\s+(?P<en_here>there|here)|"
    r"(?:please\s+)?move\s+to\s+(?:the\s+)?(?P<en_dest_only>.+?)(?:\s+folder)?|"
    r"(?P<ja_target>.+?)を(?P<ja_dest>.+?)(?:フォルダ|フォルダー)?(?:に|へ)移動|"
    r"(?P<ja_dest_only>.+?)(?:フォルダ|フォルダー)?(?:に|へ)移動)"
    r"(?:して(?:ください)?|したい)?[。！!.]?\s*$",
    re.I,
)
_ADD_TAG = re.compile(
    r"^(?:(?:please\s+)?tag\s+(?P<en_target>.+?)\s+(?:with|as)\s+(?:the\s+tag\s+)?[\"']?(?P<en_tag>[^\"']+?)[\"']?|"
    r"(?:please\s+)?tag\s+(?P<en_bare_target>these|those|them|this|the results?)(?:\s+images?)?\s+[\"']?(?P<en_bare_tag>[^\"']+?)[\"']?|"
    r"(?:please\s+)?(?:add|apply)\s+(?:the\s+)?tags?\s+[\"']?(?P<en_tag_only>[^\"']+?)[\"']?"
    r"(?:\s+to\s+(?P<en_target_only>.+?))?|"
    r"(?:please\s+)?(?:add|apply)\s+(?:the\s+)?[\"']?(?P<en_tag_noun>[^\"']+?)[\"']?\s+tags?"
    r"(?:\s+to\s+(?P<en_target_noun>.+?))?|"
    r"(?P<ja_target>.+?)に\s*[\"「]?(?P<ja_tag>[^\"」\s]+?)[\"」]?\s*タグを?(?:付け|つけ)|"
    r"(?P<ja_target_only>.+?)に\s*タグを?(?:付け|つけ))"
    r"(?:て(?:ください)?|たい)?[。！!.]?\s*$",
    re.I,
)
_REMOVE_TAG = re.compile(
    r"^(?:(?:please\s+)?(?:remove|clear|untag)\s+(?:all\s+)?(?:the\s+)?tags?"
    r"(?:\s+[\"'](?P<en_quoted>[^\"']+)[\"'])?"
    r"(?:\s+(?P<en_tag>(?!from\b|to\b|on\b|off\b|for\b)\S+))?"
    r"(?:\s+(?:from|to|on|off|for)\s+(?P<en_target>.+?))?|"
    r"(?P<ja_target>.+?)から[\"「]?(?P<ja_tag>[^\"」\s]+?)[\"」]?タグを?(?:外|はず|削除)|"
    r"(?:[\"「]?(?P<ja_tag_only>[^\"」\s]+?)[\"」]?)?タグを?(?:外|はず|削除))"
    r"(?:して(?:ください)?|たい)?[。！!.]?\s*$",
    re.I,
)
_CHANGE_TAG = re.compile(
    r"^(?:(?:please\s+)?(?:change|set|update|replace)\s+(?:all\s+)?(?:the\s+|their\s+)?tags?"
    r"(?:\s+(?:on|of|for|from)\s+(?P<en_target>.+?))?"
    r"\s+(?:to|with)\s*[\"']?(?P<en_tag>[^\"']*?)[\"']?|"
    r"(?P<ja_target>.+?)のタグを[\"「]?(?P<ja_tag>[^\"」]*?)[\"」]?(?:に(?:変更|変えて|して)|へ変更)|"
    r"タグを[\"「]?(?P<ja_tag_only>[^\"」]*?)[\"」]?(?:に(?:変更|変えて|して)|へ変更))"
    r"(?:して(?:ください)?|たい)?[。！!.]?\s*$",
    re.I,
)
_RENAME = re.compile(
    r"^(?:(?:please\s+)?rename\s+(?P<en_target>.+?)\s+to\s+[\"']?(?P<en_name>[^\"']+?)[\"']?|"
    r"(?P<ja_target>.+?)を[\"「]?(?P<ja_name>[^\"」]+?)[\"」]?(?:に(?:リネーム|名前変更)|へリネーム))"
    r"(?:して(?:ください)?|たい)?[。！!.]?\s*$",
    re.I,
)
_CREATE_FOLDER = re.compile(
    r"^(?:(?:please\s+)?create\s+(?:a\s+)?folder(?:\s+(?:named|called))?\s+[\"']?(?P<en_name>[^\"']+?)[\"']?|"
    r"[\"「]?(?P<ja_name>[^\"」]+?)[\"」]?(?:という)?(?:フォルダ|フォルダー)を?"
    r"(?:作って(?:ください)?|作成して(?:ください)?|作る|作成する))"
    r"[。！!.]?\s*$",
    re.I,
)
_REMOVE_ALL_TAGS = re.compile(
    r"(?:remove|clear|delete)\s+(?:all|every)\s+(?:of\s+)?(?:the\s+)?tags?\b|"
    r"(?:remove|clear|delete)\s+the\s+tags\b(?!\s+(?:named\s+)?[\"「']?\w)|"
    r"(?:remove|clear|untag)\s+tags\b(?!\s+(?:named\s+)?[\"「']\w)|"
    r"clear\s+(?:the\s+)?tags?\b|"
    r"take\s+(?:the\s+)?tags?\s+off|"
    r"タグを?(?:全部|すべて|全て)(?:消|外|はず|削除)|"
    r"(?:全部|すべて|全て)の?タグを?(?:消|外|はず|削除)|"
    r"(?:この画像たち?の)?タグを(?:外|はず|削除|消)して",
    re.I,
)
_QUANTITY = re.compile(
    r"(?:the\s+)?(?P<from>first|last)\s+(?P<count>\d+)|"
    r"(?:the\s+)?last\s+(?P<last_word>two|three)|"
    r"(?:the\s+)?first\s+(?P<first_word>two|three)|"
    r"\bonly\s+(?P<only>\d+)\s+(?:of\s+them|images?)|"
    r"\b(?:all|every)\s+(?:of\s+)?(?:them|these|those|the\s+images?)\b|"
    r"最初の(?P<ja_first>\d+)|最後の(?P<ja_last>\d+)",
    re.I,
)
_EXCEPT_FAVORITES = re.compile(
    r"except(?:\s+the)?\s+favorites?|お気に入り(?:以外|を除)",
    re.I,
)
_EXCEPT_PNG = re.compile(
    r"except(?:\s+the)?\s+(?P<ext>png|jpe?g|webp|bmp)(?:\s+files?)?|"
    r"(?P<ja_ext>png|jpe?g|webp|bmp)(?:ファイル)?(?:以外|を除)",
    re.I,
)
_BATCH_RENAME_PREFIX = re.compile(
    r'(?:add|prefix)\s+[\"「\']?(?P<pre>[^\"」\']+)[\"」\']?\s+(?:to\s+the\s+beginning|to\s+the\s+start|at\s+the\s+beginning)|'
    r'ファイル名の?(?:先頭|頭)に[\"「\']?(?P<ja_pre>[^\"」\']+)[\"」\']?',
    re.I,
)
_BATCH_RENAME_SUFFIX = re.compile(
    r'(?:add|append)\s+[\"「\']?(?P<suf>[^\"」\']+?)[\"」\']?\s+'
    r'(?:to\s+(?:the\s+)?(?:end of (?:these |the )?filenames?|filenames?)|'
    r'at\s+the\s+end(?:\s+of (?:these |the )?filenames?)?)|'
    r'ファイル名の?末尾に[\"「\']?(?P<ja_suf>[^\"」\']+)[\"」\']?',
    re.I,
)
_BATCH_RENAME_SEQUENTIAL = re.compile(
    r'rename\s+(?:these|them|those|selected(?:\s+images?)?|the\s+results?)\s+'
    r'(?:to\s+)?[\"「\']?(?P<base>.+?)[\"」\']?\s+(?P<sample>\d+)(?:\s*,\s*[\"「\']?.+?[\"」\']?\s+\d+)*\s*(?:\.{2,}|…)|'
    r'(?:これら|この画像|この結果)を[\"「\']?(?P<ja_base>.+?)[\"」\']?\s*(?P<ja_sample>\d+)',
    re.I,
)
_WORD_COUNTS = {"two": 2, "three": 3}
_DELETE = re.compile(
    r"(削除|ゴミ箱|delete|trash)",
    re.I,
)
_UNSAFE_TOOL = re.compile(
    r"(?:call|use|run|execute)\s+(?:the\s+)?(?:shell|sql|python)|"
    r"\b(?:powershell|cmd\.exe|/bin/sh)\b|"
    r"\buse sql\b|"
    r"ignore (?:the )?(?:available |allowed )?actions|"
    r"create a new action",
    re.I,
)
_VAGUE_ORGANIZE = re.compile(
    r"^(?:(?:please\s+)?(?:organize|tidy(?:\s+up)?|sort|clean(?:\s+up)?)"
    r"(?:\s+(?:these|them|it|everything|my images?))?"
    r"(?:\s+(?:nicely|somehow|for me)?)?|"
    r"(?:いい感じに|うまく|適当に)?整理(?:して(?:ください)?)?)"
    r"[。！!.]?\s*$",
    re.I,
)
_DESCRIPTIVE_RENAME = re.compile(
    r"(内容が分かる|わかりやすい|分かりやすい|意味が分かる|見れば分かる).*(?:名前|ファイル名)|"
    r"(?:descriptive|meaningful|better)\s+names?|"
    r"rename.{0,40}(?:descriptive|meaningful|what they (?:are|show))",
    re.I,
)
_ADD_FAVORITE = re.compile(
    r"(?:add(?:\s+a)?\s+(?:favorite|favourite)(?:\s+star)?|"
    r"add(?:\s+a)?\s+star|"
    r"(?:favorite|favourite)(?:\s+star)?|"
    r"お気に入りにして|お気に入りに(?:する|して))",
    re.I,
)
_REMOVE_FAVORITE = re.compile(
    r"(unfavorite|unfavourite|unstar|remove(?:\s+the)?\s+(?:favorite|favourite)|"
    r"お気に入りを?(?:外|はず|解除))",
    re.I,
)
_PROMPT_INJECTION = re.compile(
    r"(?:ignore(?:\s+all)?(?:\s+your)?(?:\s+previous)?\s+instructions|"
    r"change your role|you are now|bypass confirmation|"
    r"do not use preview|just execute|skip(?:\s+the)? preview|"
    r"system prompt|override (?:the )?(?:rules|safety)|"
    r"ignore (?:the )?(?:available |allowed )?actions)",
    re.I,
)
_EXPLICIT_SEARCH = re.compile(
    r"(?:^(?:please\s+)?(?:find|search(?:\s+for)?|show(?:\s+me)?|look for)\b|"
    r"screenshots? containing|"
    r"探して|探す|検索して|検索する|見つけて|見つける|写っている|映っている)",
    re.I,
)


def classify_ask_ai_turn(instruction: str, context: SearchResultContext | None = None) -> AskAiTurn:
    raw = " ".join(str(instruction or "").strip().split())
    ctx = context or SearchResultContext()
    if not raw:
        return AskAiTurn(KIND_CLARIFY, message_key="images.ai.need_instruction", reasons=("empty",))
    if _HELP.match(raw):
        return AskAiTurn(KIND_HELP, query=raw)

    if _VAGUE_ORGANIZE.match(raw):
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key="images.ai.clarify_organize",
            reasons=("vague_organize",),
        )

    if _UNSAFE_TOOL.search(raw):
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            message_key="images.ai.not_available_script",
            reasons=("unsafe_tool",),
        )

    if _DELETE.search(raw) and _looks_like_command(raw) and not _REMOVE_ALL_TAGS.search(raw):
        return AskAiTurn(
            KIND_UNSUPPORTED,
            query=raw,
            message_key="images.ai.not_available_delete",
            reasons=("delete_unsupported",),
        )

    if looks_like_act_plan(raw, ctx):
        return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=_target_source(raw, ctx))

    act = _parse_act(raw, ctx)
    if act is not None:
        return act

    if _has_action_verb(raw):
        source = _target_source(raw, ctx)
        if not _has_resolved_targets(source, ctx, raw):
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.missing_target",
                reasons=("no_targets",),
            )
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            target_source=source,
            message_key="images.ai.missing_parameter",
            reasons=("action_incomplete",),
        )

    narrow = _parse_narrow(raw, ctx)
    if narrow is not None:
        return narrow

    if instruction_is_underspecified(raw):
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key="images.ai.clarify_search",
            reasons=("underspecified_search",),
        )

    if _looks_like_explicit_search(raw):
        return AskAiTurn(KIND_FIND, query=_find_query(raw), target_source=SOURCE_FOLDER)

    if looks_like_prompt_injection(raw):
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key="images.ai.not_understood",
            reasons=("prompt_injection", "role_locked"),
        )

    return AskAiTurn(
        KIND_CLARIFY,
        query=raw,
        message_key="images.ai.not_understood",
        reasons=("needs_planner",),
    )


def looks_like_act_plan(
    instruction: str,
    context: SearchResultContext | None = None,
) -> bool:
    """True when a request likely needs Find/Narrow plus Action, or several Actions."""
    raw = " ".join(str(instruction or "").strip().split())
    ctx = context or SearchResultContext()
    if not raw:
        return False
    if _DESCRIPTIVE_RENAME.search(raw):
        return True
    action_hits = 0
    if re.search(
        r"タグを?(?:付け|つけ|外|はず|変更|変えて)|"
        r"(?:add|apply|remove|clear|change|set|update|replace)\s+(?:all\s+)?(?:the\s+)?tags?|"
        r"\btag\b|\buntag\b",
        raw,
        re.I,
    ):
        action_hits += 1
    if re.search(r"移動|\bmove\b", raw, re.I):
        action_hits += 1
    if re.search(r"(?:フォルダ|フォルダー)を?作|create\s+(?:a\s+)?folder", raw, re.I):
        action_hits += 1
    if re.search(r"リネーム|\brename\b|名前に変", raw, re.I):
        action_hits += 1
    if re.search(
        r"お気に入りにして|(?:add|remove)\s+(?:a\s+)?(?:favorite|favourite)(?:\s+star)?|"
        r"\b(?:unfavorite|unfavourite)\b",
        raw,
        re.I,
    ):
        action_hits += 1
    search_hit = bool(
        re.search(
            r"探して|見つけて|写って|映って|\bfind\b|\bsearch(?:\s+for)?\b|\blook for\b|\bshow me\b",
            raw,
            re.I,
        )
        and not _RESULT_REF.search(raw)
    )
    narrow_hit = bool(
        re.search(
            r"この中で|その中で|この中から|この結果から|among(?:\s+these)?|"
            r".+だけ.+(?:タグ|移動|付け)|only(?:\s+the)?.+(?:tag|move)",
            raw,
            re.I,
        )
    )
    if re.search(
        r"(?:remove|clear|untag|add|apply|change|set|update)\s+.+\bfrom\b",
        raw,
        re.I,
    ):
        narrow_hit = False
    if action_hits >= 2:
        return True
    if action_hits >= 1 and (search_hit or narrow_hit):
        return True
    if action_hits >= 1 and _implied_search_target(raw, ctx):
        return True
    return False


def parse_simple_turn(
    instruction: str,
    context: SearchResultContext | None = None,
    *,
    require_targets: bool = True,
) -> AskAiTurn | None:
    """Parse one clause as Find, Narrow, or a single Act. Does not route to the planner."""
    raw = " ".join(str(instruction or "").strip().split())
    ctx = context or SearchResultContext()
    if not raw:
        return None
    act = _parse_act(raw, ctx, require_targets=require_targets)
    if act is not None:
        return act
    narrow = _parse_narrow(raw, ctx)
    if narrow is not None:
        return narrow
    if _FIND_PREFIX.match(raw) or _FIND_SUFFIX.search(raw):
        return AskAiTurn(KIND_FIND, query=_find_query(raw), target_source=SOURCE_FOLDER)
    return None


def _parse_act(raw: str, ctx: SearchResultContext, *, require_targets: bool = True) -> AskAiTurn | None:
    quantity = _quantity_turn(raw)
    if quantity is not None:
        return quantity
    extras = _target_filter_params(raw)

    batch_rename = _parse_batch_rename(raw, ctx, require_targets=require_targets, extras=extras)
    if batch_rename is not None:
        return batch_rename

    if _REMOVE_ALL_TAGS.search(raw) and not re.search(r"\bexcept\b|以外", raw, re.I):
        source = _target_source(raw, ctx)
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            if _implied_search_target(raw, ctx):
                return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_target", reasons=("no_targets",),
            )
        return _act_turn(
            ACTION_REMOVE_ALL_TAGS, source, extras, raw,
        )

    created = _CREATE_FOLDER.match(raw)
    if created:
        name = (created.group("en_name") or created.group("ja_name") or "").strip(" 　「」\"'")
        if not name:
            return AskAiTurn(
                KIND_CLARIFY, query=raw,
                message_key="images.ai.missing_parameter",
                reasons=("folder_name_missing",),
            )
        return AskAiTurn(
            KIND_ACT,
            query=raw,
            proposal=ActionProposal(
                action_id=ACTION_CREATE_FOLDER,
                target_source=SOURCE_RESULT_SET,
                parameters={"name": name},
                instruction=raw,
            ),
        )

    moved = _MOVE.match(raw)
    if moved:
        target_text = _first(
            moved.group("en_target"), moved.group("ja_target"), _group(moved, "en_target_here"),
        )
        dest = _first(
            moved.group("en_dest"), moved.group("en_dest_only"),
            moved.group("ja_dest"), moved.group("ja_dest_only"),
            _group(moved, "en_here"),
        )
        dest = _clean_folder_name(dest)
        source = _target_source(target_text or raw, ctx)
        if not dest or dest in {"フォルダ", "フォルダー", "folder"}:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.which_destination",
                reasons=("destination_missing",),
            )
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.missing_target",
                reasons=("no_targets",),
            )
        return AskAiTurn(
            KIND_ACT,
            query=raw,
            target_source=source,
            proposal=ActionProposal(
                action_id=ACTION_MOVE,
                target_source=source,
                parameters={"destination_name": dest},
                instruction=raw,
            ),
        )

    favorite = _parse_favorite(raw, ctx, require_targets=require_targets)
    if favorite is not None:
        return _merge_extras(favorite, extras)

    named_removed = re.match(
        r"^(?:please\s+)?(?:remove|clear|untag)\s+(?:the\s+)?(?P<en_tags>.+?)\s+from\s+(?P<en_target>.+?)"
        r"(?:して(?:ください)?|たい)?[。！!.]?\s*$",
        raw,
        re.I,
    )
    if named_removed and not re.search(r"\b(?:all|every)\s+tags?\b", raw, re.I):
        tags = parse_tag_names(named_removed.group("en_tags"))
        if tags and not any(name.casefold() in {"favorite", "favourite"} for name in tags):
            if len(tags) == 1 and tags[0].lower().startswith("tag "):
                tags = parse_tag_names(tags[0][4:])
            if len(tags) == 1 and tags[0].lower().endswith(" tag"):
                tags = parse_tag_names(tags[0][:-4])
            tags = tuple(name for name in tags if name.casefold() not in {"tag", "tags"})
            if not tags:
                pass
            else:
                source = _target_source(named_removed.group("en_target") or raw, ctx)
                if require_targets and not _has_resolved_targets(source, ctx, raw):
                    if _implied_search_target(raw, ctx):
                        return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
                    return AskAiTurn(
                        KIND_CLARIFY, query=raw, target_source=source,
                        message_key="images.ai.missing_target", reasons=("no_targets",),
                    )
                parameters = {"tags": list(tags)} if len(tags) > 1 else {"tag": tags[0]}
                parameters.update(extras)
                return _act_turn(ACTION_REMOVE_TAG, source, parameters, raw)

    removed = _REMOVE_TAG.match(raw)
    if removed:
        tag_raw = _first(
            _group(removed, "en_quoted"),
            _group(removed, "en_tag"),
            _group(removed, "ja_tag"),
            _group(removed, "ja_tag_only"),
        )
        tags = parse_tag_names(tag_raw)
        target_text = _first(_group(removed, "en_target"), _group(removed, "ja_target"))
        source = _target_source(target_text or raw, ctx)
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            if _implied_search_target(raw, ctx):
                return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_target", reasons=("no_targets",),
            )
        if not tags:
            from app.workspace.tag_semantics import looks_like_unnamed_tag_clear

            if looks_like_unnamed_tag_clear(raw):
                return _act_turn(ACTION_REMOVE_ALL_TAGS, source, extras, raw)
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.which_tag_remove", reasons=("tag_missing",),
            )
        parameters = {"tags": list(tags)} if len(tags) > 1 else {"tag": tags[0]}
        parameters.update(extras)
        return _act_turn(ACTION_REMOVE_TAG, source, parameters, raw)

    changed = _CHANGE_TAG.match(raw)
    if changed:
        tag_raw = _first(
            _group(changed, "en_tag"),
            _group(changed, "ja_tag"),
            _group(changed, "ja_tag_only"),
        )
        tags = parse_tag_names(tag_raw)
        target_text = _first(_group(changed, "en_target"), _group(changed, "ja_target"))
        source = _target_source(target_text or raw, ctx)
        if not tags:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.clarify_replace_tags",
                reasons=("empty_replace_tags",),
            )
        parameters = {"tags": list(tags)}
        parameters.update(extras)
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            if _implied_search_target(raw, ctx):
                return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_target", reasons=("no_targets",),
            )
        return _act_turn(ACTION_REPLACE_TAGS, source, parameters, raw)

    tagged = _ADD_TAG.match(raw)
    if tagged:
        tag_raw = _first(
            tagged.group("en_tag"),
            _group(tagged, "en_bare_tag"),
            tagged.group("en_tag_only"),
            tagged.group("en_tag_noun"),
            tagged.group("ja_tag"),
        )
        tags = parse_tag_names(tag_raw)
        target_text = _first(
            tagged.group("en_target"),
            _group(tagged, "en_bare_target"),
            tagged.group("en_target_only"),
            tagged.group("en_target_noun"),
            tagged.group("ja_target"),
            tagged.group("ja_target_only"),
        )
        source = _target_source(target_text or raw, ctx)
        if not tags:
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.which_tag", reasons=("tag_missing",),
            )
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            if _implied_search_target(raw, ctx):
                return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_target", reasons=("no_targets",),
            )
        parameters = {"tags": list(tags)} if len(tags) > 1 else {"tag": tags[0]}
        parameters.update(extras)
        return _act_turn(ACTION_ADD_TAG, source, parameters, raw)

    renamed = _RENAME.match(raw)
    if renamed:
        name = _first(renamed.group("en_name"), renamed.group("ja_name"))
        target_text = _first(renamed.group("en_target"), renamed.group("ja_target"))
        source = _target_source(target_text or raw, ctx)
        if not name:
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_parameter", reasons=("name_missing",),
            )
        if require_targets and not _has_resolved_targets(source, ctx, raw):
            return AskAiTurn(
                KIND_CLARIFY, query=raw, target_source=source,
                message_key="images.ai.missing_target", reasons=("no_targets",),
            )
        return AskAiTurn(
            KIND_ACT,
            query=raw,
            target_source=source,
            proposal=ActionProposal(
                action_id=ACTION_RENAME,
                target_source=source,
                parameters={"new_name": name.strip()},
                instruction=raw,
            ),
        )

    favorite = _parse_favorite(raw, ctx, require_targets=require_targets)
    if favorite is not None:
        return _merge_extras(favorite, extras)
    return None


def _parse_narrow(raw: str, ctx: SearchResultContext) -> AskAiTurn | None:
    prefixed = _NARROW_PREFIX.match(raw)
    source = SOURCE_SELECTION if (
        "選んだ" in raw or "選択" in raw or re.search(r"\bselected\b", raw, re.I)
    ) else SOURCE_RESULT_SET
    if prefixed:
        query = _narrow_query(raw[prefixed.end():])
        if not _has_resolved_targets(source, ctx, raw):
            return AskAiTurn(
                KIND_CLARIFY,
                query=query or raw,
                target_source=source,
                message_key="images.ai.missing_target",
                reasons=("no_targets",),
            )
        if not query:
            return AskAiTurn(
                KIND_CLARIFY,
                query=raw,
                target_source=source,
                message_key="images.ai.describe_target",
                reasons=("narrow_query_missing",),
            )
        return AskAiTurn(KIND_NARROW, query=query, target_source=source)

    if ctx.has_targets(SOURCE_RESULT_SET) and _ONLY_TAIL.search(raw) and not _FIND_PREFIX.match(raw):
        query = _narrow_query(_ONLY_TAIL.sub("", raw))
        if query:
            return AskAiTurn(KIND_NARROW, query=query, target_source=SOURCE_RESULT_SET)
    return None


def _target_source(text: str, ctx: SearchResultContext) -> str:
    blob = text or ""
    if is_explicit_selection_request(blob):
        return SOURCE_SELECTION
    if _RESULT_REF.search(blob) and ctx.has_result_set():
        return SOURCE_RESULT_SET
    if _SELECTION_REF.search(blob) and ctx.has_selection():
        return SOURCE_SELECTION
    if _SELECTION_REF.search(blob):
        return SOURCE_SELECTION if ctx.has_selection() else SOURCE_RESULT_SET
    if ctx.has_selection() and not ctx.has_result_set():
        return SOURCE_SELECTION
    return SOURCE_RESULT_SET


def _has_resolved_targets(source: str, ctx: SearchResultContext, raw: str) -> bool:
    return resolve_action_targets(source, ctx, instruction=raw).ok


def _has_action_verb(raw: str) -> bool:
    return bool(_ACTION_VERB.search(raw or ""))


def _implied_search_target(raw: str, ctx: SearchResultContext) -> bool:
    """True when an Action names images to find, not the current result set."""
    if ctx.has_result_set() or ctx.has_selection():
        return False
    if _RESULT_REF.search(raw):
        return False
    if _SELECTION_REF.search(raw) and not re.search(
        r"(?:写って|映って|探して|見つけて|\bfind\b|\bsearch\b)", raw, re.I
    ):
        return False
    match = re.search(r"\b(?:from|to|on|off|for|of)\s+(.+)$", raw, re.I)
    blob = (match.group(1) if match else "").strip(" 　、,。.!\"'")
    blob = re.sub(r"(?:して(?:ください)?|たい)$", "", blob, flags=re.I).strip()
    if blob and not _DEICTIC_ONLY.match(blob) and re.search(r"[A-Za-zぁ-んァ-ン一-龥]{2,}", blob):
        return True
    if re.search(r"(?:が写って|が映って|.+の画像|.+のスクショ)", raw) and not _DEICTIC_ONLY.match(raw):
        return True
    return False


def _act_turn(action_id: str, source: str, parameters: dict, raw: str) -> AskAiTurn:
    return AskAiTurn(
        KIND_ACT,
        query=raw,
        target_source=source,
        proposal=ActionProposal(
            action_id=action_id,
            target_source=source,
            parameters=dict(parameters or {}),
            instruction=raw,
        ),
    )


def _merge_extras(turn: AskAiTurn, extras: dict) -> AskAiTurn:
    if not extras or turn.proposal is None:
        return turn
    from dataclasses import replace as _replace

    params = dict(turn.proposal.parameters)
    params.update(extras)
    return AskAiTurn(
        turn.kind,
        query=turn.query,
        target_source=turn.target_source,
        proposal=_replace(turn.proposal, parameters=params),
        message_key=turn.message_key,
        message=turn.message,
        reasons=turn.reasons,
    )


def _quantity_turn(raw: str) -> AskAiTurn | None:
    if re.search(r"\bonly\s+\d+\b", raw, re.I) and not re.search(r"\b(?:first|last)\b", raw, re.I):
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            message_key="images.ai.clarify_quantity",
            reasons=("ambiguous_quantity",),
        )
    return None


def _target_filter_params(raw: str) -> dict:
    extras: dict = {}
    match = _QUANTITY.search(raw)
    if match:
        word = (match.group("last_word") or match.group("first_word") or "").lower()
        count = (
            match.group("count")
            or match.group("only")
            or match.group("ja_first")
            or match.group("ja_last")
            or _WORD_COUNTS.get(word)
        )
        origin = "last" if (match.group("from") or "").lower() == "last" or match.group("last_word") or match.group("ja_last") else ""
        if match.group("from") and match.group("from").lower() == "first":
            origin = "first"
        elif match.group("first_word") or match.group("ja_first"):
            origin = "first"
        if count and origin:
            extras["target_count"] = int(count)
            extras["target_from"] = origin
    if _EXCEPT_FAVORITES.search(raw):
        extras["except_favorites"] = True
    except_ext = _EXCEPT_PNG.search(raw)
    if except_ext:
        ext = except_ext.group("ext") or except_ext.group("ja_ext") or ""
        if ext:
            extras["except_extensions"] = ext.lower()
    return extras


def _parse_batch_rename(raw: str, ctx: SearchResultContext, *, require_targets: bool, extras: dict) -> AskAiTurn | None:
    source = _target_source(raw, ctx)
    prefix = _BATCH_RENAME_PREFIX.search(raw)
    if prefix:
        value = (prefix.group("pre") or prefix.group("ja_pre") or "").strip(" 「」\"'")
        if value:
            if require_targets and not _has_resolved_targets(source, ctx, raw):
                return AskAiTurn(
                    KIND_CLARIFY, query=raw, target_source=source,
                    message_key="images.ai.missing_target", reasons=("no_targets",),
                )
            parameters = {"rename_strategy": "prefix", "prefix": value}
            parameters.update(extras)
            return _act_turn(ACTION_RENAME, source, parameters, raw)
    suffix = _BATCH_RENAME_SUFFIX.search(raw)
    if suffix:
        value = (suffix.group("suf") or suffix.group("ja_suf") or "").strip(" 「」\"'")
        if value:
            if require_targets and not _has_resolved_targets(source, ctx, raw):
                return AskAiTurn(
                    KIND_CLARIFY, query=raw, target_source=source,
                    message_key="images.ai.missing_target", reasons=("no_targets",),
                )
            parameters = {"rename_strategy": "suffix", "suffix": value}
            parameters.update(extras)
            return _act_turn(ACTION_RENAME, source, parameters, raw)
    sequential = _BATCH_RENAME_SEQUENTIAL.search(raw)
    if sequential:
        base = (sequential.group("base") or sequential.group("ja_base") or "").strip(" 「」\"'")
        sample = sequential.group("sample") or sequential.group("ja_sample") or "1"
        if base:
            if require_targets and not _has_resolved_targets(source, ctx, raw):
                return AskAiTurn(
                    KIND_CLARIFY, query=raw, target_source=source,
                    message_key="images.ai.missing_target", reasons=("no_targets",),
                )
            digits = len(sample)
            strategy = "numbered" if digits >= 3 or sample.startswith("0") else "sequential"
            parameters = {
                "rename_strategy": strategy,
                "base_name": base,
                "start": int(sample) if sample.isdigit() else 1,
            }
            if strategy == "numbered":
                parameters["digits"] = max(digits, 3)
            parameters.update(extras)
            return _act_turn(ACTION_RENAME, source, parameters, raw)
    return None


def _group(match: re.Match[str], name: str) -> str:
    try:
        return str(match.group(name) or "").strip()
    except IndexError:
        return ""


def _find_query(raw: str) -> str:
    query = _FIND_SUFFIX.sub("", raw)
    query = _FIND_PREFIX.sub("", query)
    return query.strip(" 　、,。.!\"'") or raw


def _narrow_query(raw: str) -> str:
    query = _ONLY_TAIL.sub("", raw)
    query = re.sub(r"^(?:the ones?(?: that)?|those(?: that)?|images?)\s+", "", query, flags=re.I)
    query = query.strip(" 　、,。.!\"':")
    query = re.sub(r"(?:のもの|の画像|のスクショ)$", "", query)
    return query.strip(" 　、,。.!\"'")


def _clean_folder_name(name: str | None) -> str:
    value = str(name or "").strip(" 　「」\"'")
    value = re.sub(r"(?:フォルダ|フォルダー|folder)$", "", value, flags=re.I).strip()
    return value


def _parse_favorite(
    raw: str,
    ctx: SearchResultContext,
    *,
    require_targets: bool = True,
) -> AskAiTurn | None:
    removing = bool(_REMOVE_FAVORITE.search(raw))
    adding = bool(_ADD_FAVORITE.search(raw) or re.search(r"お気に入り", raw))
    if not removing and not adding:
        return None
    if re.search(r"\btags?\b|タグ", raw) and "お気に入り" not in raw:
        if not re.search(r"\b(?:add|remove|un)\s+(?:a\s+)?(?:favorite|favourite)\b", raw, re.I):
            return None
    action_id = ACTION_REMOVE_FAVORITE if removing else ACTION_ADD_FAVORITE
    source = _target_source(raw, ctx)
    if require_targets and not _has_resolved_targets(source, ctx, raw):
        if _implied_search_target(raw, ctx):
            return AskAiTurn(KIND_ACT_PLAN, query=raw, target_source=source)
        return AskAiTurn(
            KIND_CLARIFY,
            query=raw,
            target_source=source,
            message_key="images.ai.missing_target",
            reasons=("no_targets",),
        )
    return AskAiTurn(
        KIND_ACT,
        query=raw,
        target_source=source,
        proposal=ActionProposal(
            action_id=action_id,
            target_source=source,
            parameters={},
            instruction=raw,
        ),
    )


def instruction_is_underspecified(instruction: str) -> bool:
    """Bare nouns are not search requests in Ask AI chat."""
    raw = " ".join(str(instruction or "").strip().split())
    if not raw:
        return True
    if _looks_like_explicit_search(raw) or _has_action_verb(raw) or _HELP.match(raw):
        return False
    if looks_like_prompt_injection(raw):
        return False
    if len(raw) > 48:
        return False
    tokens = re.findall(r"[A-Za-z0-9]+|[ぁ-んァ-ン一-龥]+", raw)
    if not tokens or len(tokens) > 4:
        return False
    if re.search(r"[.?!。！？]", raw):
        return False
    return True


def looks_like_prompt_injection(instruction: str) -> bool:
    return bool(_PROMPT_INJECTION.search(str(instruction or "")))


def _looks_like_explicit_search(raw: str) -> bool:
    return bool(_FIND_PREFIX.match(raw) or _FIND_SUFFIX.search(raw) or _EXPLICIT_SEARCH.search(raw))


def _looks_like_command(raw: str) -> bool:
    return bool(
        re.search(
            r"(して|ください|してほしい|please|\bdelete\b|\bmove\b|\btag\b|"
            r"\bfavorite\b|\bfavourite\b|\bstar\b)",
            raw,
            re.I,
        )
    )


def _first(*values: str | None) -> str:
    for value in values:
        if value:
            return str(value).strip()
    return ""
