import json

import psycopg
import pytest

from platform_api.db import Database
from platform_api.migrations import downgrade, upgrade
from platform_api.orchestration import ReleaseTask
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import RunId
from tests.conftest import PostgresUrls
from tests.support import NOW, SPEC

pytestmark = pytest.mark.anyio

OLD_SPEC = {
    "use_case_id": SPEC.use_case_id,
    "use_case_version": 1,
    "use_case_name": SPEC.use_case_name,
    "owner": "alice",
    "workflow": "release_check",
    "instruction": SPEC.instruction,
    "repo": "langchain-ai/langgraph",
    "tag_pattern": r"^\d+\.\d+\.\d+$",
    "last_known_tag": "1.2.14",
    "bindings": {
        "create_ticket": {
            "connector": "jira",
            "operation": "create_ticket",
            "target": {"project": "MOCK"},
        }
    },
    "approval_policy": {"steps": [{"label": "Team approver", "eligible": {}}]},
}


async def test_a_run_saved_before_the_task_union_loads_as_a_release_task(
    postgres: PostgresUrls, db: Database
):
    downgrade("orchestration", postgres.owner, "0002")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, "
            "started_by, started_at, updated_at, version, state, state_data, deadline_at, "
            "retried_by, carry_forward) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, NULL, "
            "'[]', NULL)",
            (
                "run_old",
                SPEC.use_case_id,
                "key-old",
                json.dumps(OLD_SPEC),
                "alice",
                NOW,
                NOW,
                "Succeeded",
                json.dumps({"run_id": "run_old", "outcome": "nothing_to_write", "written": []}),
            ),
        )
    upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        record = await Store().load_run(uow, RunId("run_old"))
    assert record is not None
    assert record.spec.task == ReleaseTask("langchain-ai/langgraph", r"^\d+\.\d+\.\d+$", "1.2.14")
    assert record.spec.bindings == SPEC.bindings


async def test_a_release_check_run_survives_a_downgrade_and_upgrade(
    postgres: PostgresUrls, db: Database
):
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_new"), 1, None, NOW)
        record = RunRecord(RunId("run_new"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-new")
    downgrade("orchestration", postgres.owner, "0002")
    with psycopg.connect(postgres.owner) as conn:
        row = conn.execute(
            "SELECT spec FROM orchestration.runs WHERE run_id = 'run_new'"
        ).fetchone()
    assert row is not None
    assert (row[0]["repo"], row[0]["last_known_tag"]) == ("langchain-ai/langgraph", "1.2.14")
    assert "task" not in row[0]
    upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        loaded = await Store().load_run(uow, RunId("run_new"))
    assert loaded is not None and loaded.spec == SPEC


async def test_the_card_tables_come_and_go_with_migration_0003_and_belong_to_the_builder(
    postgres: PostgresUrls,
):
    tables = ("cards", "card_versions", "use_case_cards")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:

        def present() -> list[str]:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'builder' AND table_name = ANY(%s) ORDER BY 1",
                (list(tables),),
            ).fetchall()
            return [r[0] for r in rows]

        assert present() == sorted(tables)
        downgrade("builder", postgres.owner, "0002")
        assert present() == []
        upgrade("builder", postgres.owner)
        assert present() == sorted(tables)

    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute("SELECT count(*) FROM builder.use_case_cards")
        builder.rollback()
    with (
        psycopg.connect(postgres.contexts.orchestration) as other,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        other.execute("SELECT count(*) FROM builder.cards")
