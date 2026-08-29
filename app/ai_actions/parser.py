"""Small local Japanese/English intent parser for the first prototype."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ActionParameters, ActionType


@dataclass(frozen=True)
class ParsedInstruction:
    action: ActionType
    search_query: str
    parameters: ActionParameters
    confidence: float
    ambiguity_reasons: tuple[str, ...] = ()


class LocalActionParser:
    """Recognize a deliberately narrow grammar without an external LLM."""

    _JA_ENDINGS = re.compile(
        r"(?:を)?(?:探して(?:ください)?|検索して(?:ください)?|見つけて(?:ください)?)[。！!]?\s*$"
    )
    _EN_FIND = re.compile(
        r"^\s*(?:please\s+)?(?:find|search\s+for|show\s+me)\s+(.+?)[.!]?\s*$", re.I
    )

    def parse(self, instruction: str) -> ParsedInstruction:
        raw = " ".join(str(instruction or "").strip().split())
        if not raw:
            return self._unknown("empty_instruction")

        parsed = self._parse_japanese_mutation(raw) or self._parse_english_mutation(raw)
        if parsed:
            return parsed

        if self._JA_ENDINGS.search(raw):
            query = self._JA_ENDINGS.sub("", raw).strip(" 、,。")
            return self._result(ActionType.SEARCH, query, confidence=0.98)
        match = self._EN_FIND.match(raw)
        if match:
            return self._result(ActionType.SEARCH, match.group(1), confidence=0.98)

        return self._unknown("unrecognized_intent")

    def _parse_japanese_mutation(self, raw: str) -> ParsedInstruction | None:
        tag = re.match(
            r"^(.+?)(?:に|へ)([^\s「」]+?)タグを?(?:付け|つけ)(?:たい|て|てください)?[。！!]?\s*$", raw
        )
        if tag:
            return self._result(
                ActionType.TAG, tag.group(1), ActionParameters(tag=tag.group(2)), 0.98
            )

        move = re.match(
            r"^(.+?)(?:を)(.+?)(?:フォルダ)?(?:に|へ)移動(?:し?たい|して|してください)?[。！!]?\s*$", raw
        )
        if move:
            query = re.sub(r"の画像$", "", move.group(1)).strip()
            destination = re.sub(r"フォルダ$", "", move.group(2)).strip()
            return self._result(
                ActionType.MOVE, query, ActionParameters(destination_folder=destination), 0.98
            )
        return None

    def _parse_english_mutation(self, raw: str) -> ParsedInstruction | None:
        tag = re.match(
            r"^(?:please\s+)?tag\s+(.+?)\s+(?:with|as)\s+(?:the\s+tag\s+)?[\"']?([^\"']+?)[\"']?[.!]?\s*$",
            raw, re.I,
        )
        if tag:
            return self._result(
                ActionType.TAG, tag.group(1), ActionParameters(tag=tag.group(2)), 0.96
            )
        move = re.match(
            r"^(?:please\s+)?move\s+(.+?)\s+to\s+(?:the\s+)?(.+?)(?:\s+folder)?[.!]?\s*$",
            raw, re.I,
        )
        if move:
            destination = re.sub(r"\s+folder$", "", move.group(2), flags=re.I).strip()
            return self._result(
                ActionType.MOVE, move.group(1),
                ActionParameters(destination_folder=destination), 0.96,
            )
        return None

    @staticmethod
    def _result(action, query, parameters=ActionParameters(), confidence=1.0):
        query = query.strip(" \t、,。.!\"'")
        reasons = () if query else ("missing_search_query",)
        return ParsedInstruction(action, query, parameters, confidence if query else 0.0, reasons)

    @staticmethod
    def _unknown(reason: str) -> ParsedInstruction:
        return ParsedInstruction(
            ActionType.UNKNOWN, "", ActionParameters(), 0.0, (reason,)
        )

