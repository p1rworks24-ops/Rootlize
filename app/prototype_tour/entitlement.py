"""Prototype AI usage marker. Separate from product budget (D-026)."""

from __future__ import annotations

# Hint only. Product reserve/finalize stays on the existing entitlement.
PROTOTYPE_AI_HINT_MAX = 2
SOURCE_PROTOTYPE_TOUR = "prototype_tour"


class PrototypeEntitlement:
    """Counts tour-era AI calls so a later prototype quota can be split out."""

    def __init__(self, used: int = 0) -> None:
        self.used = max(0, int(used))

    def note_call(self) -> int:
        self.used += 1
        return self.used

    def remaining_hint(self) -> int:
        return max(0, PROTOTYPE_AI_HINT_MAX - self.used)

    def should_request_more_ai(self) -> bool:
        return self.used < PROTOTYPE_AI_HINT_MAX
