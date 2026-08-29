"""Developer-only Ask AI chat UI preview: local replies, no AI APIs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ASK_AI_PREVIEW_ENV = "CAPIXE_ASK_AI_PREVIEW"
ASK_AI_PREVIEW_CONFIG_KEY = "developer_ask_ai_preview"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_GREETINGS = (
    "hello",
    "hi",
    "hey",
    "yo",
    "good morning",
    "good afternoon",
    "good evening",
)

_GREETING_REPLIES = (
    "Hi! What kind of screenshots are you looking for?",
    "Hello — what should I search for?",
    "Hi there. Describe the screenshot you have in mind.",
)

_CHROME_ASK = (
    "I found a few Chrome-related screenshots. Do you want all of them, "
    "or only screenshots where Chrome is clearly visible?"
)
_CHROME_NARROW = (
    "Got it. I’ll narrow it down to screenshots where Chrome is clearly visible."
)
_CHROME_ALL = "Okay. I’ll keep all Chrome-related screenshots."

_DOG_ASK = (
    "I found a couple of screenshots with animals. Want me to focus on the "
    "ones where a dog is clearly visible?"
)
_DOG_NARROW = "Sure. I’ll keep the screenshots where a dog is easy to see."

_GENERIC_REPLIES = (
    "I can look for that. Want me to search the current folder?",
    "Got it. Any extra detail that would help narrow it down?",
    "Okay — I’ll look for screenshots that match that.",
    "Sure. Should I keep this broad, or focus on a specific app or window?",
    "Alright. Tell me if you want all matches, or only the clearest ones.",
)

_SHORT_REPLY = "Found a few screenshots that match that description."

_LONG_REPLY = (
    "Here is a slightly longer local reply so wrapping and scroll can be checked. "
    "It stays conversational on purpose: a few sentences, not a generated report. "
    "You can keep sending messages after this one to review spacing, bubble width, "
    "and how the composer sits under the history."
)

_ERROR_DETAIL = "Preview error for layout review. No request was sent."


@dataclass(frozen=True)
class AskAiPreviewReply:
    kind: str
    text: str
    delay_ms: int = 280
    result_count: int = 0
    result_offset: int = 0


def ask_ai_ui_preview_enabled(config: dict | None = None) -> bool:
    """True only for an explicit developer env var or config flag."""
    env = (os.environ.get(ASK_AI_PREVIEW_ENV) or "").strip().lower()
    if env in _TRUE:
        return True
    if env in _FALSE:
        return False
    if config is not None:
        return bool(config.get(ASK_AI_PREVIEW_CONFIG_KEY))
    return False


def _normalize(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _is_greeting(key: str) -> bool:
    return key in _GREETINGS or key.startswith("hello ") or key.startswith("hi ")


def _history_mentions(history: list[str], *needles: str) -> bool:
    blob = " ".join(_normalize(item) for item in history)
    return any(needle in blob for needle in needles)


def _wants_narrow(key: str) -> bool:
    return any(
        token in key
        for token in ("clear", "only", "narrow", "visible", "those")
    )


def _wants_all(key: str) -> bool:
    return key in {"all", "all of them", "everything"} or key.startswith("all ")


def preview_reply_for(
    query: str, *, index: int = 0, history: list[str] | None = None
) -> AskAiPreviewReply:
    """Pick a short local reply from simple keywords. No APIs, no LLM."""
    key = _normalize(query)
    prior = list(history or [])
    if key in {"error", "/error"} or key.startswith("error "):
        return AskAiPreviewReply("error", _ERROR_DETAIL, delay_ms=220)
    if key in {"short", "/short"}:
        return AskAiPreviewReply("text", _SHORT_REPLY, delay_ms=160)
    if key in {"long", "/long"}:
        return AskAiPreviewReply("text", _LONG_REPLY, delay_ms=420)
    if key in {"slow", "/slow"}:
        return AskAiPreviewReply("text", _GENERIC_REPLIES[0], delay_ms=900)
    if key in {"dog", "/results"}:
        return AskAiPreviewReply(
            "results", "", delay_ms=240, result_count=2, result_offset=0
        )
    if key == "chrome":
        return AskAiPreviewReply(
            "results", "", delay_ms=240, result_count=2, result_offset=1
        )
    if _is_greeting(key):
        return AskAiPreviewReply(
            "text", _GREETING_REPLIES[index % len(_GREETING_REPLIES)], delay_ms=180
        )
    if "chrome" in key or "browser" in key:
        return AskAiPreviewReply("text", _CHROME_ASK, delay_ms=240)
    if "dog" in key or "animal" in key or "puppy" in key:
        return AskAiPreviewReply("text", _DOG_ASK, delay_ms=240)
    if _history_mentions(prior, "chrome", "browser"):
        if _wants_all(key):
            return AskAiPreviewReply("text", _CHROME_ALL, delay_ms=200)
        if _wants_narrow(key) or key in {"yes", "yep", "ok", "okay"}:
            return AskAiPreviewReply("text", _CHROME_NARROW, delay_ms=200)
    if _history_mentions(prior, "dog", "animal", "puppy") and (
        _wants_narrow(key) or key in {"yes", "yep", "ok", "okay"}
    ):
        return AskAiPreviewReply("text", _DOG_NARROW, delay_ms=200)
    if len(query.strip()) > 80:
        return AskAiPreviewReply("text", _LONG_REPLY, delay_ms=360)
    return AskAiPreviewReply(
        "text", _GENERIC_REPLIES[index % len(_GENERIC_REPLIES)], delay_ms=220
    )


def preview_result_paths(
    files: list[Path], reply: AskAiPreviewReply
) -> list[Path]:
    """Pick a local slice of already-loaded images. No copies, no dummy IDs."""
    if reply.kind != "results" or not files:
        return []
    offset = max(0, reply.result_offset)
    count = max(1, reply.result_count)
    if offset >= len(files):
        offset = 0
    selected = files[offset : offset + count]
    return list(selected) if selected else files[:1]
