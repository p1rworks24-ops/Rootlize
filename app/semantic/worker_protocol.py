"""Versioned UTF-8 JSON Lines protocol for the Semantic worker."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
COMMANDS = frozenset({"ping", "load_model", "embed_image", "embed_text", "analyze_images", "cancel", "get_status", "shutdown"})
MESSAGE_TYPES = frozenset({"command", "response", "event"})


class SemanticProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    type: str
    request_id: str
    command: str | None = None
    status: str | None = None
    event: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)


def _valid_request_id(value: object) -> bool:
    try:
        parsed = uuid.UUID(str(value))
        return str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def encode(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise SemanticProtocolError("IPC message exceeds size limit.")
    return encoded + "\n"


def decode(line: str) -> Message:
    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise SemanticProtocolError("IPC message exceeds size limit.")
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SemanticProtocolError("Invalid JSON message.") from exc
    if not isinstance(data, dict) or data.get("protocol_version") != PROTOCOL_VERSION:
        raise SemanticProtocolError("Unsupported protocol envelope.")
    kind = data.get("type")
    if kind not in MESSAGE_TYPES or not _valid_request_id(data.get("request_id")):
        raise SemanticProtocolError("Invalid message type or request_id.")
    command = data.get("command")
    if kind == "command" and command not in COMMANDS:
        raise SemanticProtocolError("Unknown command.")
    for key in ("payload", "result", "error"):
        if key in data and not isinstance(data[key], dict):
            raise SemanticProtocolError(f"{key} must be an object.")
    return Message(kind, data["request_id"], command, data.get("status"), data.get("event"), data.get("payload", {}), data.get("result", {}), data.get("error", {}))


def command(name: str, payload: dict[str, Any] | None = None, *, request_id: str | None = None) -> tuple[str, dict[str, Any]]:
    if name not in COMMANDS:
        raise SemanticProtocolError("Unknown command.")
    request_id = request_id or str(uuid.uuid4())
    return request_id, {"protocol_version": PROTOCOL_VERSION, "type": "command", "request_id": request_id, "command": name, "payload": payload or {}}

