"""Run Ask AI Planner routing off the UI thread."""
from __future__ import annotations

import time
from typing import Any, Mapping

from PySide6.QtCore import QObject, QRunnable, Signal

from app.ai_proxy.errors import classify_ask_ai_failure, log_ask_ai_turn
from app.workspace.context import SearchResultContext
from app.workspace.planner import CompleteJson, NameGenerator
from app.workspace.router import route_ask_ai_turn


class AskAiTurnTaskSignals(QObject):
    finished = Signal(int, object, object)


class AskAiTurnTask(QRunnable):
    """Call route_ask_ai_turn away from the Qt event loop."""

    def __init__(
        self,
        request_id: int,
        instruction: str,
        context: SearchResultContext,
        *,
        images: tuple[dict[str, Any], ...] | None = None,
        conversation: Mapping[str, Any] | None = None,
        complete_json: CompleteJson | None = None,
        name_generator: NameGenerator | None = None,
        allow_ai: bool = True,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.request_id = request_id
        self.instruction = instruction
        self.context = context
        self.images = images
        self.conversation = dict(conversation or {})
        self.complete_json = complete_json
        self.name_generator = name_generator
        self.allow_ai = allow_ai
        self.signals = AskAiTurnTaskSignals()

    def run(self) -> None:
        started = time.perf_counter()
        previous_present = bool(
            (self.conversation or {}).get("planner_response_id")
            or (self.conversation or {}).get("previous_response_id")
        )
        try:
            turn = route_ask_ai_turn(
                self.instruction,
                self.context,
                name_generator=self.name_generator,
                images=self.images,
                allow_ai=self.allow_ai,
                complete_json=self.complete_json,
                conversation=self.conversation,
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            reasons = getattr(turn, "reasons", ()) or ()
            schema_valid = "invalid_schema" not in reasons
            category = ""
            if not schema_valid:
                category = "schema"
            elif "no_targets" in reasons:
                category = "validation"
            log_ask_ai_turn(
                operation="act_plan",
                stage="ok",
                category=category,
                previous_response_id_present=previous_present,
                structured_output=True,
                schema_valid=schema_valid,
                elapsed_ms=elapsed,
            )
            self.signals.finished.emit(self.request_id, turn, None)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            proxy_code = str(getattr(exc, "code", "") or getattr(exc, "reason", "") or "-")
            log_ask_ai_turn(
                operation="act_plan",
                stage="planner_error",
                category=classify_ask_ai_failure(exc),
                http_status=int(getattr(exc, "status", 0) or 0),
                proxy_code=proxy_code,
                retry_attempted=bool(getattr(exc, "retry_attempted", False)),
                previous_response_id_present=previous_present,
                stale_chain_retry=bool(getattr(exc, "stale_chain_retry", False)),
                auth_retry=bool(getattr(exc, "auth_retry", False)),
                elapsed_ms=elapsed,
            )
            self.signals.finished.emit(self.request_id, None, exc)
