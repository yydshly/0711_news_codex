"""Suite-wide isolation for optional external services."""

from __future__ import annotations

import pytest

from newsradar.settings import Settings


@pytest.fixture(autouse=True)
def disable_live_minimax_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep EventPipeline tests deterministic when a developer has a local API key.

    Production pipelines may call MiniMax when configured.  Tests exercise the
    rule fallback unless they explicitly supply a mock transport or a Settings
    object, so they must never inherit a developer's ``.env`` credential.
    """
    monkeypatch.setattr(
        "newsradar.events.pipeline.get_settings",
        lambda: Settings(minimax_api_key=None),
    )
