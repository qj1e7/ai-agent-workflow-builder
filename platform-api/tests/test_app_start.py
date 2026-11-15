"""What platform-api does as it starts, before any run can start (ENGINE-PLAN E11): it ends each
run left on the shared run workflow, moves the workflows still on it, and sweeps every workflow
n8n carries, which grades each again under this release's rules."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from platform_api import wiring
from platform_api.app import create_app
from platform_api.builder.moves import Moves
from platform_api.builder.sweep import VersionsSweep
from platform_api.orchestration.service import Orchestrator
from tests.conftest import PostgresUrls, truncate_all
from tests.test_ready import env_for


def test_the_platform_ends_old_runs_moves_and_sweeps_before_any_run_starts(
    postgres: PostgresUrls, monkeypatch: pytest.MonkeyPatch
):
    truncate_all(postgres.owner)
    said: list[str] = []

    async def ended(self: Orchestrator) -> list[Any]:
        said.append("old runs ended")
        return []

    async def moved(self: Moves) -> dict[str, Any]:
        said.append("moved")
        return {}

    async def swept(self: VersionsSweep, use_case_id: str | None = None) -> list[Any]:
        said.append("swept")
        return []

    starts = wiring.Runner.start

    def runs_may_start(self: wiring.Runner) -> None:
        said.append("runs may start")
        starts(self)

    monkeypatch.setattr(Orchestrator, "stop_old_engine_runs", ended)
    monkeypatch.setattr(Moves, "move_all", moved)
    monkeypatch.setattr(VersionsSweep, "sweep", swept)
    monkeypatch.setattr(wiring.Runner, "start", runs_may_start)
    env = {
        **env_for(postgres),
        "N8N_OWNER_EMAIL": "owner@example.com",
        "N8N_OWNER_PASSWORD": "Aa1secret",
    }
    with TestClient(create_app(env)):
        pass

    assert said[:4] == ["old runs ended", "moved", "swept", "runs may start"]
