import json

import psycopg
import pytest

from platform_api.db import Database
from platform_api.migrations import downgrade, upgrade
from platform_api.orchestration import WatchlistTask
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.shared import RunId
from tests.conftest import PostgresUrls
from tests.support import NOW, SPEC

pytestmark = pytest.mark.anyio


async def test_a_watchlist_run_survives_a_downgrade_to_0002_and_back(
    postgres: PostgresUrls, db: Database
):
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_new"), 1, None, NOW)
        record = RunRecord(RunId("run_new"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-new")
    downgrade("orchestration", postgres.owner, "0002")
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


def insert_run(owner_url: str, run_id: str, spec: dict[str, object]) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.runs (run_id, use_case_id, idempotency_key, spec, "
            "started_by, started_at, updated_at, version, state, state_data, deadline_at, "
            "retried_by, carry_forward) VALUES (%s, %s, %s, %s, 'alice', %s, %s, 1, "
            "'AwaitingApproval', %s, NULL, '[]', NULL)",
            (
                run_id,
                SPEC.use_case_id,
                f"key-{run_id}",
                json.dumps(spec),
                NOW,
                NOW,
                json.dumps({"run_id": run_id, "proposal_id": "prp_old", "approval_id": "apr_old"}),
            ),
        )


def workflow_names(owner_url: str) -> tuple[str, list[tuple[str, str]]]:
    with psycopg.connect(owner_url) as conn:
        spec = conn.execute(
            "SELECT spec ->> 'workflow' FROM orchestration.runs WHERE run_id = 'run_waiting'"
        ).fetchone()
        outbox = conn.execute(
            "SELECT status, payload ->> 'workflow' FROM orchestration.outbox "
            "WHERE run_id = 'run_waiting' ORDER BY id"
        ).fetchall()
    assert spec is not None
    return str(spec[0]), [(str(status), str(name)) for status, name in outbox]


async def test_migration_0005_moves_waiting_runs_and_their_pending_legs_to_the_run_workflow(
    postgres: PostgresUrls, db: Database
):
    downgrade("orchestration", postgres.owner, "0004")
    task = SPEC.task
    assert isinstance(task, WatchlistTask)
    old_spec = {**SPEC.__dict__, "workflow": "release_check"}
    old_spec["task"] = {
        "kind": "watchlist",
        "tag_pattern": task.tag_pattern,
        "software": [
            {
                "id": s.id,
                "name": s.name,
                "source": {"kind": "github", "ref": s.source.ref},
                "our_version": s.our_version,
                "open_ticket": None,
                "awaiting_approval": False,
            }
            for s in task.software
        ],
    }
    old_spec["bindings"] = {
        k: {"connector": b.connector, "operation": b.operation, "target": dict(b.target)}
        for k, b in SPEC.bindings.items()
    }
    old_spec["approval_policy"] = {"steps": [{"label": "Team approver", "eligible": {}}]}
    insert_run(postgres.owner, "run_waiting", old_spec)
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        for status in ("pending", "sent"):
            conn.execute(
                "INSERT INTO orchestration.outbox (run_id, kind, payload, attempt, next_at, "
                "status, created_at) VALUES ('run_waiting', 'start_leg', %s, 0, %s, %s, %s)",
                (
                    json.dumps({"workflow": "release_check", "leg": "act", "attempt": 1}),
                    NOW,
                    status,
                    NOW,
                ),
            )

    upgrade("orchestration", postgres.owner)
    assert workflow_names(postgres.owner) == (
        "run",
        [("pending", "run"), ("sent", "release_check")],
    )
    async with db.transaction("orchestration") as uow:
        loaded = await Store().load_run(uow, RunId("run_waiting"))
    assert loaded is not None and loaded.spec.workflow == "run"

    downgrade("orchestration", postgres.owner, "0004")
    assert workflow_names(postgres.owner) == (
        "release_check",
        [("pending", "release_check"), ("sent", "release_check")],
    )
    upgrade("orchestration", postgres.owner)


def test_migration_0004_renames_the_starter_card_on_saved_agent_use_cases(
    postgres: PostgresUrls,
):
    downgrade("builder", postgres.owner, "0003")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM builder.use_case_cards")
        conn.execute("DELETE FROM builder.use_case_versions")
        conn.execute("DELETE FROM builder.use_cases")
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version) "
            "VALUES ('uc_cards', 'alice', %s, 1)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO builder.use_case_versions (use_case_id, version, template, name, "
            "instruction, params, created_at) VALUES ('uc_cards', 1, 'agent_cards', 'n', 'i', "
            "'{}', %s)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO builder.use_case_cards (use_case_id, version, position, card_id, "
            "card_version, \"values\") VALUES ('uc_cards', 1, 0, 'crd_release_checker', 1, '{}'), "
            "('uc_cards', 1, 1, 'crd_mine', 1, '{}')"
        )

        def card_ids() -> list[str]:
            rows = conn.execute(
                "SELECT card_id FROM builder.use_case_cards ORDER BY position"
            ).fetchall()
            return [str(r[0]) for r in rows]

        upgrade("builder", postgres.owner)
        assert card_ids() == ["crd_version_checker", "crd_mine"]
        downgrade("builder", postgres.owner, "0003")
        assert card_ids() == ["crd_release_checker", "crd_mine"]
        upgrade("builder", postgres.owner)
        conn.execute("DELETE FROM builder.use_case_cards")
