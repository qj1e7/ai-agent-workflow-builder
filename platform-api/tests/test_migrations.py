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
from platform_api.orchestration.questions import insert_question, load_questions_for
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.store import RunRecord, Store
from platform_api.orchestration.teams import TeamsWorkflowsWebhook
from platform_api.orchestration.write_actions import Proposal, WriteAction, digest
from platform_api.practice_jira import PracticeJira
from platform_api.shared import ApprovalId, ProposalId, RunId, UserId
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
    # A spec stored then had no expiry wait (ADR 0024 came later).
    old_spec = {k: v for k, v in SPEC.__dict__.items() if k != "expires_after"}
    old_spec["workflow"] = OLD_RUN_WORKFLOW
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


def test_migration_0010_keeps_each_schedule_change_beside_its_version_and_a_downgrade_drops_it(
    postgres: PostgresUrls,
):
    def present(conn: psycopg.Connection) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'builder'"
                " AND table_name = 'use_case_version_changes'"
            ).fetchone()
            is not None
        )

    change = (
        "INSERT INTO builder.use_case_version_changes (use_case_id, version, changed_by, via,"
        " schedule_before, schedule_after, undid) VALUES ('uc_1', %s, 'alice', %s, NULL, '{}', %s)"
    )

    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        assert present(conn)
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
            " VALUES ('uc_1', 'alice', now(), 2)"
        )
        for version in (1, 2):
            conn.execute(
                "INSERT INTO builder.use_case_versions (use_case_id, version, template, name,"
                " instruction, params, created_at) VALUES ('uc_1', %s, 'agent_cards', 'n', 'i',"
                " '{}', now())",
                (version,),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(change, (3, "page", None))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(change, (2, "teams", None))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(change, (2, "page", 2))
        downgrade("builder", postgres.owner, "0009")
        assert not present(conn)
        upgrade("builder", postgres.owner)
        assert present(conn)
    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute(change, (2, "chat", 1))
        assert builder.execute(
            "SELECT via, undid FROM builder.use_case_version_changes"
        ).fetchall() == [("chat", 1)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("UPDATE builder.use_case_version_changes SET changed_by = 'bob'")
        builder.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("DELETE FROM builder.use_case_version_changes")
        builder.rollback()


def test_migration_0011_keeps_what_a_workflow_left_out_and_a_row_from_before_has_nothing(
    postgres: PostgresUrls,
):
    def column(conn: psycopg.Connection) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = 'builder'"
                " AND table_name = 'use_cases' AND column_name = 'left_out'"
            ).fetchone()
            is not None
        )

    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("builder", postgres.owner, "0010")
        assert not column(conn)
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
            " VALUES ('uc_before', 'alice', now(), 1)"
        )
        upgrade("builder", postgres.owner)
        assert column(conn)
    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version,"
            " left_out) VALUES ('uc_after', 'alice', now(), 1, %s)",
            (["colour them by team"],),
        )
        assert builder.execute(
            "SELECT use_case_id, left_out FROM builder.use_cases"
            " WHERE use_case_id IN ('uc_before', 'uc_after') ORDER BY use_case_id"
        ).fetchall() == [("uc_after", ["colour them by team"]), ("uc_before", [])]
        builder.commit()
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("builder", postgres.owner, "0010")
        assert not column(conn)
        assert conn.execute(
            "SELECT count(*) FROM builder.use_cases WHERE use_case_id IN ('uc_before', 'uc_after')"
        ).fetchone() == (2,)
        upgrade("builder", postgres.owner)


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


def test_migration_0022_keeps_confluences_checks_and_a_downgrade_drops_only_those(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO orchestration.connection_checks (connection, identity, state, checked_at) "
        "VALUES (%s, %s, %s, %s)"
    )
    count = "SELECT connection, count(*) FROM orchestration.connection_checks GROUP BY 1"
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute("DELETE FROM orchestration.connection_checks")
        conn.execute(insert, ("jira", "practice", "working", NOW))
        conn.execute(insert, ("confluence", "confluence:0123456789abcdef", "working", NOW))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("sharepoint", "sharepoint", "working", NOW))
        downgrade("orchestration", postgres.owner, "0021")
        try:
            assert dict(conn.execute(count).fetchall()) == {"jira": 1}
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(insert, ("confluence", "confluence:0", "working", NOW))
        finally:
            upgrade("orchestration", postgres.owner)
        conn.execute("DELETE FROM orchestration.connection_checks")


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


async def test_migration_0016_keeps_each_tickets_jira_site_and_a_row_from_before_has_none(
    postgres: PostgresUrls, db: Database
):
    run_id, proposal_id = RunId("run_site"), ProposalId("prp_site")
    action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
    async with db.transaction("orchestration") as uow:
        pending = Pending(run_id, 1, None, NOW)
        record = RunRecord(run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await Store().insert_run(uow, record, "key-site")
        await Store().insert_proposal(
            uow, Proposal(proposal_id, run_id, (action, action), digest((action, action)))
        )
    insert = (
        "INSERT INTO orchestration.proposed_tickets (proposal_id, action_index, run_id, "
        "use_case_id, software_id, version, status, ticket_key) "
        "VALUES (%s, %s, %s, 'uc_1', 'sw_1', '1.0.0', 'written', 'MOCK-1')"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("orchestration", postgres.owner, "0015")
        conn.execute(insert, (proposal_id, 0, run_id))
        conn.execute(
            "INSERT INTO orchestration.our_versions (use_case_id, software_id, version, source, "
            "learned_at, ticket_key) VALUES ('uc_1', 'sw_1', '1.0.0', 'ticket_done', %s, 'MOCK-1')",
            (NOW,),
        )
        upgrade("orchestration", postgres.owner)
        assert conn.execute(
            "SELECT ticket_key, site FROM orchestration.our_versions"
        ).fetchall() == [("MOCK-1", None)]
        conn.execute(
            "INSERT INTO orchestration.proposed_tickets (proposal_id, action_index, run_id, "
            "use_case_id, software_id, version, status, ticket_key, site) "
            "VALUES (%s, 1, %s, 'uc_1', 'sw_1', '1.0.0', 'written', 'MOCK-2', 'practice')",
            (proposal_id, run_id),
        )
        sites = conn.execute(
            "SELECT ticket_key, site FROM orchestration.proposed_tickets ORDER BY action_index"
        ).fetchall()
        assert sites == [("MOCK-1", None), ("MOCK-2", "practice")], "no row is filled in"
        downgrade("orchestration", postgres.owner, "0015")
        try:
            for table in ("proposed_tickets", "our_versions"):
                columns = conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE "
                    "table_schema = 'orchestration' AND table_name = %s",
                    (table,),
                ).fetchall()
                assert ("site",) not in columns, table
            assert conn.execute(
                "SELECT count(*) FROM orchestration.proposed_tickets"
            ).fetchone() == (2,)
        finally:
            upgrade("orchestration", postgres.owner)


async def test_migration_0017_keeps_a_reason_only_on_a_decline_and_a_decision_from_before_has_none(
    postgres: PostgresUrls, db: Database
):
    store = Store()
    approval_id, run_id = ApprovalId("apr_reason"), RunId("run_reason")
    two = ApprovalPolicy(
        (ApprovalStep("First", AnyApprover()), ApprovalStep("Second", AnyApprover()))
    )
    async with db.transaction("orchestration") as uow:
        pending = Pending(run_id, 1, None, NOW)
        record = RunRecord(run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await store.insert_run(uow, record, "key-reason")
        action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
        proposal = Proposal(ProposalId("prp_reason"), run_id, (action,), digest((action,)))
        await store.insert_proposal(uow, proposal)
        await store.insert_approval(
            uow,
            ApprovalRequest(
                approval_id, run_id, proposal.id, proposal.digest, two, frozenset({SPEC.owner})
            ),
        )
    insert = (
        "INSERT INTO orchestration.approval_decisions (approval_id, step_index, decided_by, "
        "verdict, seen_digest, decided_at{}) VALUES (%s, %s, 'bob', %s, 'd', %s{})"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("orchestration", postgres.owner, "0016")
        conn.execute(insert.format("", ""), (approval_id, 0, "approve", NOW))
        upgrade("orchestration", postgres.owner)
        with_reason = insert.format(", reason", ", %s")
        for verdict, reason in (
            ("approve", "Wrong version"),
            ("decline", ""),
            ("decline", "x" * 201),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(with_reason, (approval_id, 1, verdict, NOW, reason))
        conn.execute(with_reason, (approval_id, 1, "decline", NOW, "Wrong version"))
        rows = conn.execute(
            "SELECT step_index, verdict, reason FROM orchestration.approval_decisions "
            "WHERE approval_id = %s ORDER BY step_index",
            (approval_id,),
        ).fetchall()
        assert rows == [(0, "approve", None), (1, "decline", "Wrong version")]
        downgrade("orchestration", postgres.owner, "0016")
        try:
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema = 'orchestration' AND table_name = 'approval_decisions'"
            ).fetchall()
            assert ("reason",) not in columns
            assert conn.execute(
                "SELECT count(*) FROM orchestration.approval_decisions WHERE approval_id = %s",
                (approval_id,),
            ).fetchone() == (2,), "a downgrade keeps the decisions"
        finally:
            upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        loaded = await store.load_decisions(uow, approval_id)
    assert [(d.step_index, d.reason) for d in loaded] == [(0, None), (1, None)]


async def test_migration_0018_keeps_questions_with_whole_answers_and_a_downgrade_drops_them(
    postgres: PostgresUrls, db: Database
):
    store = Store()
    approval_id, run_id = ApprovalId("apr_question"), RunId("run_question")
    async with db.transaction("orchestration") as uow:
        pending = Pending(run_id, 1, None, NOW)
        record = RunRecord(run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None)
        await store.insert_run(uow, record, "key-question")
        action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
        proposal = Proposal(ProposalId("prp_question"), run_id, (action,), digest((action,)))
        await store.insert_proposal(uow, proposal)
        await store.insert_approval(
            uow,
            ApprovalRequest(
                approval_id,
                run_id,
                proposal.id,
                proposal.digest,
                SPEC.approval_policy,
                frozenset({SPEC.owner}),
            ),
        )
        asked = await insert_question(uow, approval_id, UserId("bob"), "Is it urgent?", "k1")
    insert = (
        "INSERT INTO orchestration.approval_questions (question_id, approval_id, asked_by, "
        "asked_at, text, idempotency_key, answer, answered_by, answered_at) "
        "VALUES (%s, %s, 'bob', %s, %s, %s, %s, %s, %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        for question_id, text, answer, by, at in (
            ("q_empty", "", None, None, None),
            ("q_long", "x" * 1001, None, None, None),
            ("q_no_one_answered", "Is it?", "Yes", None, None),
            ("q_no_time", "Is it?", "Yes", "alice", None),
            ("q_no_words", "Is it?", None, "alice", NOW),
            ("q_empty_answer", "Is it?", "", "alice", NOW),
            ("q_long_answer", "Is it?", "x" * 1001, "alice", NOW),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    insert, (question_id, approval_id, NOW, text, question_id, answer, by, at)
                )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, ("q_again", approval_id, NOW, "Again?", "k1", None, None, None))
        downgrade("orchestration", postgres.owner, "0017")
        try:
            assert conn.execute(
                "SELECT to_regclass('orchestration.approval_questions')"
            ).fetchone() == (None,)
            assert conn.execute(
                "SELECT count(*) FROM orchestration.approval_requests WHERE approval_id = %s",
                (approval_id,),
            ).fetchone() == (1,), "a downgrade keeps the request"
        finally:
            upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        assert await load_questions_for(uow, [approval_id]) == {}, "the table starts empty again"
    assert asked.answer is None


def test_migration_0012_leaves_every_workflow_from_before_on_and_a_downgrade_pauses_a_draft(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
        " VALUES (%s, 'alice', %s, 1)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("builder", postgres.owner, "0011")
        conn.execute(insert, ("uc_before", NOW))
        upgrade("builder", postgres.owner)
        conn.execute(insert, ("uc_draft", NOW))
        conn.execute("UPDATE builder.use_cases SET draft = true WHERE use_case_id = 'uc_draft'")
        assert conn.execute(
            "SELECT use_case_id, draft FROM builder.use_cases"
            " WHERE use_case_id IN ('uc_before', 'uc_draft') ORDER BY use_case_id"
        ).fetchall() == [("uc_before", False), ("uc_draft", True)]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE builder.use_cases SET paused_at = now(), paused_by = 'alice'"
                " WHERE use_case_id = 'uc_draft'"
            )
        downgrade("builder", postgres.owner, "0011")
        try:
            assert conn.execute(
                "SELECT use_case_id, paused_at, paused_by FROM builder.use_cases"
                " WHERE use_case_id IN ('uc_before', 'uc_draft') ORDER BY use_case_id"
            ).fetchall() == [("uc_before", None, None), ("uc_draft", NOW, "alice")]
        finally:
            upgrade("builder", postgres.owner)


async def test_migration_0019_keeps_starts_links_and_node_calls_whole_and_a_downgrade_drops_them(
    postgres: PostgresUrls, db: Database
):
    store = Store()
    run_id = RunId("run_n8n")
    async with db.transaction("orchestration") as uow:
        pending = Pending(run_id, 1, None, NOW)
        record = RunRecord(
            run_id, SPEC, SPEC.owner, NOW, NOW, 1, pending, (), None, (UserId("dave"),)
        )
        await store.insert_run(uow, record, "key-n8n")
    start = (
        "INSERT INTO orchestration.starts (nonce, run_id, kind, n8n_workflow_id, issued_at, "
        "expires_at, used_at, used_by) VALUES (%s, %s, %s, 'wf1', %s, %s, %s, %s)"
    )
    call = (
        "INSERT INTO orchestration.node_calls (execution_id, node_name, run_id, kind, "
        "content_hash, attempts, outcome, call_id, claimed_at, status, answer, answered_at) "
        "VALUES ('41', %s, %s, %s, 'h', 1, %s, %s, %s, %s, %s, %s)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(start, ("n_ok", run_id, "run_now", NOW, NOW, None, None))
        for nonce, kind, at, by in (
            ("n_kind", "later", None, None),
            ("n_no_execution", "run_now", NOW, None),
            ("n_no_time", "run_now", None, "41"),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(start, (nonce, run_id, kind, NOW, NOW, at, by))
        refusal = '{"detail": "This start was already used."}'
        conn.execute(call, ("Read", run_id, "read", "working", "c1", NOW, None, None, None))
        conn.execute(call, ("Agent", None, "agent", "refused", "c2", NOW, 403, refusal, NOW))
        for node, run, kind, outcome, status, answer, at in (
            ("Odd", run_id, "loop", "working", None, None, None),
            ("No run", None, "read", "answered", None, '{"items": []}', NOW),
            ("No time", run_id, "agent", "answered", None, '{"items": []}', None),
            ("No answer", run_id, "agent", "answered", None, None, NOW),
            ("Status", run_id, "agent", "answered", 403, '{"items": []}', NOW),
            ("No status", run_id, "agent", "refused", None, refusal, NOW),
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(call, (node, run, kind, outcome, node, NOW, status, answer, at))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(call, ("Read", run_id, "read", "working", "c3", NOW, None, None, None))
        downgrade("orchestration", postgres.owner, "0018")
        try:
            for table in ("starts", "executions", "node_calls"):
                assert conn.execute(
                    "SELECT to_regclass(%s)", (f"orchestration.{table}",)
                ).fetchone() == (None,)
            assert conn.execute(
                "SELECT count(*) FROM orchestration.runs WHERE run_id = %s", (run_id,)
            ).fetchone() == (1,), "a downgrade keeps the run"
        finally:
            upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        kept = await store.load_run(uow, run_id)
    assert kept is not None and kept.joined_by == (), "the joined people go with the downgrade"


def test_builder_migration_0014_puts_every_use_case_on_the_shared_run_and_back(
    postgres: PostgresUrls,
):
    insert = (
        "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
        " VALUES (%s, 'alice', %s, 1)"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("builder", postgres.owner, "0013")
        conn.execute(insert, ("uc_engine_before", NOW))
        upgrade("builder", postgres.owner)
        conn.execute(insert, ("uc_engine_own", NOW))
        conn.execute(
            "UPDATE builder.use_cases SET engine = 'own' WHERE use_case_id = 'uc_engine_own'"
        )
        assert conn.execute(
            "SELECT use_case_id, engine FROM builder.use_cases"
            " WHERE use_case_id LIKE 'uc_engine_%' ORDER BY use_case_id"
        ).fetchall() == [("uc_engine_before", "shared_run"), ("uc_engine_own", "own")]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE builder.use_cases SET engine = 'n8n' WHERE use_case_id = 'uc_engine_own'"
            )
        downgrade("builder", postgres.owner, "0013")
        try:
            assert conn.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'builder'"
                " AND table_name = 'use_cases' AND column_name = 'engine'"
            ).fetchone() == (0,)
        finally:
            upgrade("builder", postgres.owner)


def test_migration_0013_keeps_who_paused_or_resumed_a_workflow_and_from_where(
    postgres: PostgresUrls,
):
    def present(conn: psycopg.Connection) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'builder'"
                " AND table_name = 'use_case_moves'"
            ).fetchone()
            is not None
        )

    moved = (
        "INSERT INTO builder.use_case_moves (use_case_id, move, moved_by, via, moved_at)"
        " VALUES ('uc_moved', %s, 'alice', %s, now())"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        assert present(conn)
        conn.execute(
            "INSERT INTO builder.use_cases (use_case_id, owner, created_at, current_version)"
            " VALUES ('uc_moved', 'alice', now(), 1)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(moved, ("delete", "chat"))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(moved, ("pause", "teams"))
        downgrade("builder", postgres.owner, "0012")
        assert not present(conn)
        upgrade("builder", postgres.owner)
        assert present(conn)
    with psycopg.connect(postgres.contexts.builder) as builder:
        builder.execute(moved, ("pause", "chat"))
        assert builder.execute(
            "SELECT move, moved_by, via FROM builder.use_case_moves"
        ).fetchall() == [("pause", "alice", "chat")]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            builder.execute("DELETE FROM builder.use_case_moves")
        builder.rollback()


async def test_migration_0020_keeps_a_request_from_before_without_expiry_and_a_wake_once(
    postgres: PostgresUrls, db: Database
):
    store = Store()
    run_id = RunId("run_wait")
    async with db.transaction("orchestration") as uow:
        record = RunRecord(
            run_id, SPEC, SPEC.owner, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
        )
        await store.insert_run(uow, record, "key-wait")
        action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
        proposal = Proposal(ProposalId("prp_wait"), run_id, (action,), digest((action,)))
        await store.insert_proposal(uow, proposal)
    policy = '{"steps": [{"label": "Team approver", "eligible": {}}]}'
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        downgrade("orchestration", postgres.owner, "0019")
        conn.execute(
            "INSERT INTO orchestration.approval_requests (approval_id, run_id, proposal_id, "
            "digest, policy, parties, created_at) VALUES ('apr_before', %s, 'prp_wait', 'd', "
            "%s, '[]', %s)",
            (run_id, policy, NOW),
        )
        upgrade("orchestration", postgres.owner)
        update = "UPDATE orchestration.approval_requests SET {} WHERE approval_id = 'apr_before'"
        for change in (
            "ended = 'expired'",
            "ended = 'gone', ended_at = now()",
            "execution_id = '41'",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(update.format(change))
        wake = (
            "INSERT INTO orchestration.outbox (run_id, kind, payload, next_at, status, created_at, "
            "idempotency_key) VALUES (%s, 'wake', '{}', now(), 'pending', now(), 'wake:apr_before')"
        )
        conn.execute(wake, (run_id,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(wake, (run_id,))
        downgrade("orchestration", postgres.owner, "0019")
        try:
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                "'orchestration' AND table_name IN ('approval_requests', 'outbox')"
            ).fetchall()
            assert not {("expires_at",), ("resume_url",), ("idempotency_key",)} & set(columns)
        finally:
            upgrade("orchestration", postgres.owner)
    async with db.transaction("orchestration") as uow:
        before = await store.load_approval(uow, ApprovalId("apr_before"))
        assert await store.held_wait(uow, ApprovalId("apr_before")) is None
    assert before is not None and (before.expires_at, before.ended) == (None, None)


async def test_migration_0021_keeps_one_practice_notice_per_block_of_a_run_and_goes_back(
    postgres: PostgresUrls, db: Database
):
    run_id = RunId("run_tell")
    async with db.transaction("orchestration") as uow:
        record = RunRecord(
            run_id, SPEC, SPEC.owner, NOW, NOW, 1, Pending(run_id, 1, None, NOW), (), None
        )
        await Store().insert_run(uow, record, "key-tell")
    notice = (
        "INSERT INTO orchestration.tell_practice_messages (id, ts, run_id, block, body) "
        "VALUES (%s, %s, %s, 'Tell you', '{}')"
    )
    with psycopg.connect(postgres.owner, autocommit=True) as conn:
        conn.execute(notice, ("tell_1", NOW, run_id))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(notice, ("tell_2", NOW, run_id))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(notice, ("tell_3", NOW, "run_nobody"))
        downgrade("orchestration", postgres.owner, "0020")
        try:
            assert conn.execute(
                "SELECT to_regclass('orchestration.tell_practice_messages')"
            ).fetchone() == (None,)
        finally:
            upgrade("orchestration", postgres.owner)
