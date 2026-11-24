"""Shared fixtures. Unit tests never read the developer's real `.env` or environment."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from commerce_agent.common.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env is picked up
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
