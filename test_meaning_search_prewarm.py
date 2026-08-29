"""Background Meaning Search worker prewarm must not start after close."""

from __future__ import annotations

import time

from app.semantic.worker_client import SemanticWorkerClient, SemanticWorkerConfig, SemanticTimeouts
from app.ui.images_search import SemanticImagesSearchProvider


def _fake_provider() -> SemanticImagesSearchProvider:
    provider = SemanticImagesSearchProvider()
    provider.worker = SemanticWorkerClient(
        SemanticWorkerConfig(
            fake_mode="ok",
            idle_seconds=0,
            timeouts=SemanticTimeouts(start=3, ping=1, shutdown=2),
        )
    )
    return provider


def test_prewarm_loads_text_encoder():
    provider = _fake_provider()
    try:
        provider.prewarm()
        deadline = time.time() + 3
        while "text_encoder" not in provider.worker._loaded_components and time.time() < deadline:
            time.sleep(0.02)
        assert "text_encoder" in provider.worker._loaded_components
        provider.prewarm()
        assert provider._prewarm_started is True
    finally:
        provider.close()


def test_prewarm_after_close_does_not_start_worker():
    provider = _fake_provider()
    provider.close()
    provider._prewarm_started = False
    provider.prewarm()
    time.sleep(0.2)
    assert provider.worker.is_running() is False
    assert "text_encoder" not in provider.worker._loaded_components
