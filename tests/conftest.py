"""Fixtures for the ticket-script tests (registry, ticket_state, watch_board)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tickets_helpers import filled_registry_text


@pytest.fixture
def filled_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A ready registry.md (GitHub, a real clone folder, no example values) and its path.

    Every CLI the registry check looks for counts as installed, so a result does not depend on
    the machine running the tests.
    """
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    clone = tmp_path / "code" / "shop-app"
    clone.mkdir(parents=True)
    path = tmp_path / "pack" / "registry.md"
    path.parent.mkdir()
    path.write_text(filled_registry_text(clone), encoding="utf-8")
    return path
