import json

import psycopg
import pytest

from platform_api.bootstrap import OLD_RUN_WORKFLOW
from platform_api.db import Database
from platform_api.migrations import downgrade, upgrade
from platform_api.orchestration import WatchlistTask
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
)
from platform_api.orchestration.dispatch import PRACTICE, MessageRef
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.teams import TeamsWorkflowsWebhook
from platform_api.orchestration.write_actions import Proposal, WriteAction, digest
from platform_api.practice_jira import PracticeJira
from platform_api.shared import ApprovalId, ProposalId, RunId
from tests.conftest import PostgresUrls
from tests.support import NOW, SPEC

pytestmark = pytest.mark.anyio

OLD_STARTER_CARD = "crd_release_checker"


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
    old_spec = {**SPEC.__dict__, "workflow": OLD_RUN_WORKFLOW}
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
                    json.dumps({"workflow": OLD_RUN_WORKFLOW, "leg": "act", "attempt": 1}),
                    NOW,
                    status,
                    NOW,
                ),
            )

    upgrade("orchestration", postgres.owner)
    assert workflow_names(postgres.owner) == (
        "run",
        [("pending", "run"), ("sent", OLD_RUN_WORKFLOW)],
    )
    async with db.transaction("orchestration") as uow:
        loaded = await Store().load_run(uow, RunId("run_waiting"))
    assert loaded is not None and loaded.spec.workflow == "run"

    downgrade("orchestration", postgres.owner, "0004")
    assert workflow_names(postgres.owner) == (
        OLD_RUN_WORKFLOW,
        [("pending", OLD_RUN_WORKFLOW), ("sent", OLD_RUN_WORKFLOW)],
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
            "card_version, \"values\") VALUES ('uc_cards', 1, 0, %s, 1, '{}'), "
            "('uc_cards', 1, 1, 'crd_mine', 1, '{}')",
            (OLD_STARTER_CARD,),
        )

        def card_ids() -> list[str]:
            rows = conn.execute(
                "SELECT card_id FROM builder.use_case_cards ORDER BY position"
            ).fetchall()
            return [str(r[0]) for r in rows]

        upgrade("builder", postgres.owner)
        assert card_ids() == ["crd_version_checker", "crd_mine"]
        downgrade("builder", postgres.owner, "0003")
        assert card_ids() == [OLD_STARTER_CARD, "crd_mine"]
        upgrade("builder", postgres.owner)
        conn.execute("DELETE FROM builder.use_case_cards")


LIFECYCLE_COLUMNS = ["deleted_at", "deleted_by", "paused_at", "paused_by"]


def test_migration_0005_adds_the_lifecycle_and_drafts_and_stops_hard_deletes(
    postgres: PostgresUrls,
):
    with psycopg.connect(postgres.owner, autocommit=True) as conn:

        def lifecycle_columns() -> list[str]:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                "'builder' AND table_name = 'use_cases' AND column_name = ANY(%s) ORDER BY 1",
                (LIFECYCLE_COLUMNS,),
            ).fetchall()
            return [str(r[0]) for r in rows]

        def has_drafts() -> bool:
            row = conn.execute("SELECT to_regclass('builder.drafts') IS NOT NULL").fetchone()
            return bool(row and row[0])

        assert (lifecycle_columns(), has_drafts()) == (LIFECYCLE_COLUMNS, True)
        downgrade("builder", postgres.owner, "0004")
        assert (lifecycle_columns(), has_drafts()) == ([], False)
        conn.execute("DELETE FROM builder.use_case_versions")
        conn.execute("DELETE FROM builder.use_cases")
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version) "
            "VALUES ('uc_before', 'alice', %s, 1)",
            (NOW,),
        )
        upgrade("builder", postgres.owner)
        assert (lifecycle_columns(), has_drafts()) == (LIFECYCLE_COLUMNS, True)
        assert conn.execute(
            "SELECT paused_at, paused_by, deleted_at, deleted_by FROM builder.use_cases"
        ).fetchall() == [(None, None, None, None)]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE builder.use_cases SET paused_at = %s", (NOW,))

    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute("SELECT count(*) FROM builder.drafts")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("DELETE FROM builder.use_cases")
        builder.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("DELETE FROM builder.use_case_versions")
    with (
        psycopg.connect(postgres.contexts.orchestration) as other,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        other.execute("SELECT count(*) FROM builder.drafts")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM builder.use_cases")


def test_migration_0006_lets_a_draft_have_no_step_and_a_downgrade_gives_it_step_1(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO builder.drafts (author, draft_id, step, content, created_at, saved_at) "
        "VALUES ('alice', %s, %s, '{}', %s, %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM builder.drafts")
        downgrade("builder", postgres.owner, "0005")
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute(insert, ("d-none", None, NOW, NOW))
        conn.execute(insert, ("d-old", 3, NOW, NOW))
        upgrade("builder", postgres.owner)
        conn.execute(insert, ("d-new", None, NOW, NOW))
        steps = conn.execute("SELECT draft_id, step FROM builder.drafts ORDER BY 1").fetchall()
        assert steps == [("d-new", None), ("d-old", 3)]
        downgrade("builder", postgres.owner, "0005")
        steps = conn.execute("SELECT draft_id, step FROM builder.drafts ORDER BY 1").fetchall()
        assert steps == [("d-new", 1), ("d-old", 3)]
        upgrade("builder", postgres.owner)
        conn.execute("DELETE FROM builder.drafts")


def test_migration_0007_keeps_team_requests_and_a_downgrade_drops_them(postgres: PostgresUrls):
    tables = ["team_request_replies", "team_requests"]

    def present(conn: psycopg.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'builder' AND table_name = ANY(%s) ORDER BY 1",
            (tables,),
        ).fetchall()
        return [str(r[0]) for r in rows]

    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        assert present(conn) == tables
        conn.execute(
            "INSERT INTO builder.team_requests (request_id, kind, about, note, asked_by,"
            " asked_by_name, asked_at, idempotency_key, teams_post) VALUES ('trq_1',"
            " 'ask_the_team', '{}', 'n', 'alice', 'Alice', now(), 'k', 'posted')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO builder.team_requests (request_id, kind, about, note, asked_by,"
                " asked_by_name, asked_at, idempotency_key, teams_post) VALUES ('trq_2',"
                " 'support', '{}', 'n', 'alice', 'Alice', now(), 'k', 'posted')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE builder.team_requests SET status = 'done'")
        downgrade("builder", postgres.owner, "0006")
        assert present(conn) == []
        upgrade("builder", postgres.owner)
        assert present(conn) == tables
        assert conn.execute("SELECT count(*) FROM builder.team_requests").fetchone() == (0,)
    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute("SELECT count(*) FROM builder.team_request_replies")
        builder.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("DELETE FROM builder.team_requests")
        builder.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("UPDATE builder.team_requests SET note = 'changed'")
        builder.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("UPDATE builder.team_requests SET asked_by = 'bob'")


def test_migration_0008_adds_the_asker_seen_mark_and_a_downgrade_removes_it(
    postgres: PostgresUrls,
):
    def column_present(conn: psycopg.Connection) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'builder'"
                " AND table_name = 'team_requests' AND column_name = 'asker_seen_at'"
            ).fetchone()
            is not None
        )

    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        assert column_present(conn)
        conn.execute("DELETE FROM builder.team_request_replies")
        conn.execute("DELETE FROM builder.team_requests")
        downgrade("builder", postgres.owner, "0007")
        assert not column_present(conn)
        conn.execute(
            "INSERT INTO builder.team_requests (request_id, kind, about, note, asked_by,"
            " asked_by_name, asked_at, idempotency_key, teams_post) VALUES ('trq_old',"
            " 'ask_the_team', '{}', 'n', 'alice', 'Alice', now(), 'k', 'posted')"
        )
        conn.execute(
            "INSERT INTO builder.team_request_replies (reply_id, request_id, replied_by,"
            " replied_by_name, replied_at, text, status) VALUES ('trr_old', 'trq_old', 'bob',"
            " 'Bob', now(), 'Done.', 'answered')"
        )
        conn.execute(
            "INSERT INTO builder.team_request_replies (reply_id, request_id, replied_by,"
            " replied_by_name, replied_at, text, status) VALUES ('trr_mine', 'trq_old', 'alice',"
            " 'Alice', now(), 'Thanks.', 'answered')"
        )
        upgrade("builder", postgres.owner)
        assert column_present(conn)
        [seen] = conn.execute(
            "SELECT asker_seen_at IS NOT NULL FROM builder.team_requests"
        ).fetchone() or [None]
        assert seen is True
        stored = conn.execute(
            "SELECT reply_id, status FROM builder.team_request_replies ORDER BY reply_id"
        ).fetchall()
        assert stored == [("trr_mine", "added"), ("trr_old", "answered")]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE builder.team_request_replies SET status = 'bogus'")
        downgrade("builder", postgres.owner, "0007")
        back = conn.execute(
            "SELECT status FROM builder.team_request_replies ORDER BY reply_id"
        ).fetchall()
        assert back == [("answered",), ("answered",)]
        upgrade("builder", postgres.owner)
        conn.execute("DELETE FROM builder.team_request_replies")
        conn.execute("DELETE FROM builder.team_requests")
    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute("UPDATE builder.team_requests SET asker_seen_at = now()")
        builder.rollback()


def test_migration_0006_adds_the_people_tables_and_folds_the_model_history_into_them(
    postgres: PostgresUrls,
):
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM orchestration.settings_changes")
        conn.execute("DELETE FROM orchestration.confirmations")
        conn.execute("DELETE FROM orchestration.people")
        conn.execute(
            "INSERT INTO orchestration.settings_changes (changed_at, area, changed_by, summary) "
            "VALUES (%s, 'model', 'alice', 'Alice turned on a model.'), "
            "(%s, 'people', 'deploy', 'The deploy put people on the list.')",
            (NOW, NOW),
        )

        def tables() -> list[str]:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = "
                "'orchestration' AND table_name IN ('people', 'confirmations', "
                "'settings_changes', 'model_setting_changes') ORDER BY 1"
            ).fetchall()
            return [r[0] for r in rows]

        assert tables() == ["confirmations", "people", "settings_changes"]
        downgrade("orchestration", postgres.owner, "0005")
        assert tables() == ["model_setting_changes"]
        old = conn.execute(
            "SELECT changed_by, summary FROM orchestration.model_setting_changes"
        ).fetchall()
        assert old == [("alice", "Alice turned on a model.")]
        upgrade("orchestration", postgres.owner)
        assert tables() == ["confirmations", "people", "settings_changes"]
        kept = conn.execute(
            "SELECT area, changed_by, summary FROM orchestration.settings_changes"
        ).fetchall()
        assert kept == [("model", "alice", "Alice turned on a model.")]
        assert conn.execute("SELECT count(*) FROM orchestration.people").fetchone() == (0,)

    with psycopg.connect(postgres.contexts.orchestration) as orchestration:
        orchestration.execute("SELECT count(*) FROM orchestration.people")
        orchestration.execute("LOCK TABLE orchestration.people IN SHARE ROW EXCLUSIVE MODE")
        orchestration.rollback()


def test_migration_0006_downgrade_keeps_a_waiting_address(postgres: PostgresUrls):
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM orchestration.model_setting")
        conn.execute(
            "INSERT INTO orchestration.model_setting (slot, provider, style, base_url, model, "
            "sealed_key, key_hint, test_seconds, saved_by, saved_by_name, saved_at) VALUES "
            "('pending', 'ai-gateway.ncs.example', 'openai', 'https://ai-gateway.ncs.example/v1', "
            "'ncs-llm-small', 'sealed', 'x7', 1.4, 'alice', 'Alice', %s)",
            (NOW,),
        )
        downgrade("orchestration", postgres.owner, "0005")
        try:
            kept = conn.execute("SELECT slot, model FROM orchestration.model_setting").fetchall()
            assert kept == [("pending", "ncs-llm-small")]
        finally:
            conn.execute("DELETE FROM orchestration.model_setting")
            upgrade("orchestration", postgres.owner)


async def test_migration_0007_keeps_the_newest_version_beside_a_problem_and_back(
    postgres: PostgresUrls, db: Database
):
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_kept"), 1, None, NOW)
        record = RunRecord(RunId("run_kept"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-kept")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
            "checked_at, newest_version, newest_at, problem) VALUES "
            "('uc_1', 'sw_kept', 'run_kept', %s, '1.2.0', %s, 'GitHub answered 503.')",
            (NOW, NOW),
        )
        downgrade("orchestration", postgres.owner, "0006")
        try:
            old = conn.execute(
                "SELECT newest_version, problem FROM orchestration.software_checks"
            ).fetchall()
            assert old == [(None, "GitHub answered 503.")]
            conn.execute(
                "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
                "checked_at, newest_version, problem) VALUES "
                "('uc_1', 'sw_read', 'run_kept', %s, '2.0.0', NULL)",
                (NOW,),
            )
        finally:
            upgrade("orchestration", postgres.owner)
        read = conn.execute(
            "SELECT newest_version, newest_at FROM orchestration.software_checks "
            "WHERE software_id = 'sw_read'"
        ).fetchall()
        assert read == [("2.0.0", NOW)]


def test_migration_0008_lets_a_schedule_run_on_weekdays_and_a_downgrade_drops_those(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO orchestration.schedules (use_case_id, day, at, time_zone, owner_id, "
        "owner_name, saved_at) VALUES (%s, %s, '15:00', 'Asia/Singapore', 'alice', 'Alice', %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(insert, ("uc_weekdays", "weekdays", NOW))
        conn.execute(insert, ("uc_monday", "monday", NOW))
        downgrade("orchestration", postgres.owner, "0007")
        try:
            days = conn.execute("SELECT day FROM orchestration.schedules").fetchall()
            assert days == [("monday",)]
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(insert, ("uc_again", "weekdays", NOW))
        finally:
            upgrade("orchestration", postgres.owner)
        conn.execute(insert, ("uc_again", "weekdays", NOW))


async def test_migration_0010_records_each_old_practice_ticket_as_the_write_that_made_it(
    postgres: PostgresUrls, db: Database
):
    downgrade("orchestration", postgres.owner, "0009")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.mock_jira_tickets (key, number, project, title, body, "
            "created_at, run_id, proposal_id, idempotency_key) VALUES ('MOCK-7', 7, 'MOCK', 't', "
            "'b', now(), 'run_old', 'prp_old', 'run_old/prp_old/0')"
        )
    upgrade("orchestration", postgres.owner)
    with psycopg.connect(postgres.owner) as conn:
        row = conn.execute(
            "SELECT ticket_key FROM orchestration.jira_writes WHERE idempotency_key = %s",
            ("run_old/prp_old/0",),
        ).fetchone()
    assert row is not None and row[0] == "MOCK-7"


async def test_migration_0012_gives_each_practice_ticket_a_last_update_and_goes_back(
    postgres: PostgresUrls,
):
    downgrade("orchestration", postgres.owner, "0011")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO orchestration.mock_jira_tickets (key, number, project, title, body, "
            "created_at, done_at, status) VALUES "
            "('OLD-901', 901, 'OLD', 'open', '', '2026-11-01T01:00Z', NULL, 'To Do'), "
            "('OLD-902', 902, 'OLD', 'done', '', '2026-11-01T01:00Z', '2026-11-03T05:00Z', 'Done')"
        )
        upgrade("orchestration", postgres.owner)
        rows = conn.execute(
            "SELECT key, updated_at, assignee FROM orchestration.mock_jira_tickets "
            "WHERE project = 'OLD' ORDER BY key"
        ).fetchall()
        assert [(r[0], r[1].isoformat(), r[2]) for r in rows] == [
            ("OLD-901", "2026-11-01T01:00:00+00:00", None),
            ("OLD-902", "2026-11-03T05:00:00+00:00", None),
        ]
        downgrade("orchestration", postgres.owner, "0011")
        try:
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                "'orchestration' AND table_name = 'mock_jira_tickets'"
            ).fetchall()
            assert {"updated_at", "assignee"}.isdisjoint(c[0] for c in columns)
        finally:
            upgrade("orchestration", postgres.owner)
            conn.execute("DELETE FROM orchestration.mock_jira_tickets WHERE project = 'OLD'")


async def test_code_from_before_0012_still_makes_a_practice_ticket_after_it(
    postgres: PostgresUrls, db: Database
):
    with psycopg.connect(postgres.contexts.orchestration, autocommit=True) as conn:
        written = conn.execute("SELECT now()").fetchone()
        assert written is not None
        conn.execute(
            "INSERT INTO orchestration.mock_jira_tickets "
            "(key, number, project, title, body, created_at, run_id, proposal_id, "
            "labels, issue_type, creator) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ("MOCK-1", 1, "MOCK", "Made after a revert", "", NOW, None, None, [], "Task", None),
        )
    ticket = await PracticeJira(db, "token", "http://localhost:8080").get("MOCK-1")
    assert ticket is not None and ticket.assignee is None
    assert ticket.updated_at >= written[0]


def test_migration_0013_adds_the_connection_checks_and_a_downgrade_drops_them(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO orchestration.connection_checks (connection, identity, state, checked_at) "
        "VALUES (%s, %s, %s, %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM orchestration.connection_checks")
        conn.execute(insert, ("jira", "practice", "working", NOW))
        conn.execute(insert, ("jira", "jira:0123456789abcdef", "needs_attention", NOW))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("email", "practice", "working", NOW))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("github", "github", "fine", NOW))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("teams", "practice", "not_checked", NOW))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, ("jira", "practice", "working", NOW))
        downgrade("orchestration", postgres.owner, "0012")
        try:
            gone = conn.execute("SELECT to_regclass('orchestration.connection_checks')").fetchone()
            assert gone == (None,)
        finally:
            upgrade("orchestration", postgres.owner)
        kept = conn.execute("SELECT count(*) FROM orchestration.connection_checks").fetchone()
        assert kept == (0,)

    with psycopg.connect(postgres.contexts.orchestration) as orchestration:
        orchestration.execute(insert, ("model", "model", "not_set_up", NOW))
        orchestration.rollback()
    with (
        psycopg.connect(postgres.contexts.builder) as builder,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        builder.execute("SELECT * FROM orchestration.connection_checks")


async def test_migration_0014_keeps_each_posts_channel_and_a_webhook_post_from_before_matches_none(
    postgres: PostgresUrls, db: Database
):
    store = Store()
    sent = {ApprovalId("apr_practice"): "practice", ApprovalId("apr_webhook"): "teams_workflows"}
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_old"), 1, None, NOW)
        record = RunRecord(RunId("run_old"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await store.insert_run(uow, record, "key-old")
        for approval_id in sent:
            action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
            proposal = Proposal(
                ProposalId(f"prp_{approval_id}"), RunId("run_old"), (action,), digest((action,))
            )
            await store.insert_proposal(uow, proposal)
            await store.insert_approval(
                uow,
                ApprovalRequest(
                    approval_id,
                    RunId("run_old"),
                    proposal.id,
                    proposal.digest,
                    ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
                    frozenset({SPEC.owner}),
                ),
            )
    downgrade("orchestration", postgres.owner, "0013")
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        for approval_id, adapter in sent.items():
            conn.execute(
                "INSERT INTO orchestration.approval_messages "
                "(approval_id, channel, message_id, adapter, posted_at) "
                "VALUES (%s, 'CODESparks Ops', %s, %s, %s)",
                (approval_id, f"m-{approval_id}", adapter, NOW),
            )
    upgrade("orchestration", postgres.owner)
    webhook = TeamsWorkflowsWebhook("https://teams.example/hook?sig=s", "CODESparks Ops")
    async with db.transaction("orchestration") as uow:
        practice = await store.message_ref(uow, ApprovalId("apr_practice"))
        posted = await store.message_ref(uow, ApprovalId("apr_webhook"))
        await store.save_message_ref(
            uow, ApprovalId("apr_webhook"), MessageRef("CODESparks Ops", "m-new", webhook.identity)
        )
    await webhook.close()
    assert practice is not None and practice.identity == PRACTICE
    assert posted is not None and posted.identity not in (PRACTICE, webhook.identity)

    downgrade("orchestration", postgres.owner, "0013")
    try:
        with psycopg.connect(postgres.owner) as conn:
            rows = conn.execute(
                "SELECT approval_id, adapter FROM orchestration.approval_messages ORDER BY 1"
            ).fetchall()
        assert rows == [("apr_practice", "practice"), ("apr_webhook", "teams_workflows")]
    finally:
        upgrade("orchestration", postgres.owner)


async def test_migration_0015_keeps_what_github_said_about_the_address_and_back(
    postgres: PostgresUrls, db: Database
):
    async with db.transaction("orchestration") as uow:
        pending = Pending(RunId("run_addr"), 1, None, NOW)
        record = RunRecord(RunId("run_addr"), SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-addr")
    insert = (
        "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
        "checked_at, newest_version, newest_at, problem, full_name, not_found) "
        "VALUES ('uc_1', %s, 'run_addr', %s, %s, %s, %s, %s, %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("orchestration", postgres.owner, "0014")
        conn.execute(
            "INSERT INTO orchestration.software_checks (use_case_id, software_id, run_id, "
            "checked_at, newest_version, newest_at) VALUES ('uc_1', 'sw_old', 'run_addr', %s, "
            "'1.0.0', %s)",
            (NOW, NOW),
        )
        upgrade("orchestration", postgres.owner)
        before = conn.execute(
            "SELECT full_name, not_found FROM orchestration.software_checks "
            "WHERE software_id = 'sw_old'"
        ).fetchone()
        assert before == (None, False), "a row from before says nothing about the address"
        conn.execute(insert, ("sw_moved", NOW, "2.0.0", NOW, None, "fastapi/fastapi", False))
        conn.execute(insert, ("sw_lost", NOW, None, None, "GitHub answered 404.", None, True))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("sw_bad", NOW, "2.0.0", NOW, None, None, True))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("sw_bad2", NOW, None, None, "404", "a/b", True))
        downgrade("orchestration", postgres.owner, "0014")
        try:
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema = 'orchestration' AND table_name = 'software_checks'"
            ).fetchall()
            assert ("full_name",) not in columns and ("not_found",) not in columns
        finally:
            upgrade("orchestration", postgres.owner)
