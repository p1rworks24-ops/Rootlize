from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from .models import RelevanceImage, RelevanceRun


class RelevanceProviderError(RuntimeError):
    """A safe, user-actionable relevance provider failure."""


class ImageRelevanceProvider(Protocol):
    def classify(
        self,
        query: str,
        images: Sequence[RelevanceImage],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> RelevanceRun:
        """Classify actual image pixels against the user's search intent."""
