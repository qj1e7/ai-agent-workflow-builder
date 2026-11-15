"""Writes e2e/old_engine/seed.json, the database of a platform from before ENGINE-PLAN E10, from
the platform's own code: two agent workflows on the shared run workflow, one whose run Bob
declined and one that never ran. The e2e test of the move starts a stack from it. No run on it is
open: from E11 n8n's allow list turns the shared run workflow's blocks off, so bootstrap stops
for one, and the release before finishes it.

It runs only when asked, as it rewrites the seed:
    WRITE_OLD_ENGINE_SEED=../e2e/old_engine/seed.json uv run pytest tests/test_old_engine_seed.py
"""

import json
import os
from pathlib import Path
from typing import Any

import psycopg
import pytest

from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.runs import AwaitingApproval, Pending, Rejected, StepName
from platform_api.shared import N8nExecutionId, RunId
from tests.conftest import PostgresUrls
from tests.support import BOB
from tests.test_builder_lifecycle import Lab, lab
from tests.test_card_runs import output, ticket

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.environ.get("WRITE_OLD_ENGINE_SEED"), reason="writes the seed only when asked"
    ),
]

__all__ = ["lab"]

SCHEMAS = ("builder", "orchestration", "monitoring")
LEFT_TO_THE_STACK = frozenset(
    {
        "alembic_version",
        "engine_status",
        "people",
        "settings_changes",
        "connection_checks",
        "mock_jira_tickets",
    }
)
"""Rows the stack makes for itself: its migrations, bootstrap's record, the dev People list and
the Settings line that says so, its own connection checks and its practice Jira."""


def body(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [
            {
                "card_id": VERSION_CHECKER_ID,
                "values": {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"},
            }
        ],
        "schedule": {"day": "every_day", "at": "09:00"},
        "on": True,
    }


async def set_up(lab: Lab, name: str) -> str:
    made = await lab.call("carol", "POST", "/api/v1/agent-use-cases", body(name))
    assert made.status_code == 201, made.text
    return str(made.json()["use_case_id"])


async def waiting_run(lab: Lab, name: str) -> RunId:
    """Carol set it up, Alice pressed Run now, and the shared run workflow asked for a yes."""
    use_case_id = await set_up(lab, name)
    started = await lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert started.status_code == 201, started.text
    run_id = RunId(started.json()["run_id"])
    h = lab.h
    h.agent.output = output(ticket(VERSION_CHECKER_ID, "Upgrade LangGraph from 1.2.14 to 1.2.16"))
    await h.orchestrator.tick()
    pending = await h.state(run_id)
    assert isinstance(pending, Pending) and pending.claimant is not None
    execution = N8nExecutionId(pending.claimant)
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, execution)
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, execution)
    await h.orchestrator.tick()
    assert isinstance(await h.state(run_id), AwaitingApproval)
    return run_id


def dump(owner_url: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    with psycopg.connect(owner_url) as conn:
        listed = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
            " WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'"
            " ORDER BY table_schema, table_name",
            (list(SCHEMAS),),
        ).fetchall()
        for schema, name in listed:
            if name in LEFT_TO_THE_STACK:
                continue
            table = f"{schema}.{name}"
            columns = [
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (schema, name),
                )
            ]
            with conn.cursor().copy(f"COPY {table} TO STDOUT") as copy:  # type: ignore[arg-type]
                data = b"".join(bytes(chunk) for chunk in copy).decode()
            if data:
                tables.append({"table": table, "columns": columns, "data": data})
    return tables


async def test_write_the_old_engine_seed(lab: Lab, postgres: PostgresUrls):
    declined = await waiting_run(lab, "Old release check")
    await set_up(lab, "Old idle check")
    h = lab.h
    state = await h.state(declined)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None
    await h.orchestrator.decide(state.approval_id, BOB, 0, Verdict.DECLINE, detail.request.digest)
    await h.orchestrator.tick()
    assert isinstance(await h.state(declined), Rejected)
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        # Requests from before ADR 0024 never expired, so the stack's clock decides nothing.
        conn.execute("UPDATE orchestration.approval_requests SET expires_at = NULL")
        engines = conn.execute("SELECT DISTINCT engine FROM builder.use_cases").fetchall()
    assert engines == [("shared_run",)]

    Path(os.environ["WRITE_OLD_ENGINE_SEED"]).write_text(
        json.dumps({"tables": dump(postgres.owner)}, indent=1) + "\n"
    )
