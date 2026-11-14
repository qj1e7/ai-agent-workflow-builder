"""The agent workflows still on the shared run workflow move to n8n workflows of their own
(ENGINE-PLAN 2.6, E10), and Restore to n8n saves a workflow n8n lost again from the version the
platform kept. A moved workflow writes only after its yes, keeps everyone whose work it is as a
party, and keeps its history. A workflow whose run has not ended stays until the run ends, and
that run's request still resolves. Restore puts back only a version that grades safe."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, LiteralString

import psycopg
import pytest

from platform_api.bootstrap import ask_for_restore
from platform_api.builder import Builder
from platform_api.builder.layout import CREATE_TICKET, schedule_rule
from platform_api.builder.models import UseCaseScheduleIn
from platform_api.builder.moves import (
    NOT_BACK,
    RESTORE_ASK_LIVES,
    Moves,
    Restored,
    ScheduleHeld,
)
from platform_api.builder.n8n_draft import DraftRefused, N8nNotReady, NotSafe
from platform_api.builder.watchlist import AlreadyOnN8n, MovedToN8n, WaitsForRun
from platform_api.db import json
from platform_api.orchestration import Publisher, RanVersion, Schedule
from platform_api.orchestration.approvals import Refusal, Verdict
from platform_api.orchestration.runs import Acting, AwaitingApproval, Succeeded
from platform_api.orchestration.schedule_store import ScheduleBook, schedule_owner
from platform_api.orchestration.service import Decided, DecisionRefused
from platform_api.orchestration.watch_store import WatchFacts
from platform_api.shared import N8nExecutionId, RunId, UseCaseId
from tests.conftest import PostgresUrls
from tests.fake_n8n import FakeN8n
from tests.support import ALICE, BOB, CAROL, SPEC
from tests.test_builder_lifecycle import Lab, ModelConnected
from tests.test_n8n_builder import BODY, ERROR_WORKFLOW, WRITES, lab
from tests.test_n8n_lifecycle import NEVER_LIVE, Workflows
from tests.test_n8n_wait import DAVE
from tests.test_n8n_write import Writes, w
from tests.test_orchestrator import ASK_APPROVAL, RUN_AGENTS, WRITE_ACTION

pytestmark = pytest.mark.anyio

__all__ = ["lab", "w"]

SCHEDULE_TRIGGER = "n8n-nodes-base.scheduleTrigger"
ASK_FOR_A_YES = "Ask for a yes"
NEW_ERROR_WORKFLOW = "wfErrorReporterAgain"

MOVED = RanVersion(
    "safe", Publisher(ALICE.user_id), (Publisher(CAROL.user_id), Publisher(DAVE.user_id))
)
"""Carol set the workflow up, Dave changed when it runs, and Alice changed it last and so owns
its schedule: the moved version is Alice's, and Carol's and Dave's work too."""


class Errors(Workflows):
    """The real store on a fake n8n, whose error workflow bootstrap may load again."""

    error_workflow = ERROR_WORKFLOW

    async def error_workflow_id(self) -> str | None:
        return self.error_workflow


@dataclass
class Cancels:
    """The orchestrator's cancel of a deleted workflow's open request, as asked."""

    asked: list[str] = field(default_factory=list[str])

    async def cancel_for_deleted(self, use_case_id: UseCaseId) -> int:
        self.asked.append(use_case_id)
        return 1


@dataclass
class Moving:
    lab: Lab
    n8n: FakeN8n
    store: Errors
    builder: Builder
    owner_url: str
    cancels: Cancels

    @property
    def moves(self) -> Moves:
        assert self.builder.moves is not None
        return self.builder.moves

    async def rows(self, sql: LiteralString, *args: object) -> list[dict[str, Any]]:
        async with self.lab.h.db.connection("builder") as conn:
            return [dict(r) for r in await (await conn.execute(sql, args)).fetchall()]

    async def use_case(self, use_case_id: str) -> dict[str, Any]:
        [row] = await self.rows(
            "SELECT engine, n8n_workflow_id, n8n_draft_id, current_version FROM builder.use_cases"
            " WHERE use_case_id = %s",
            use_case_id,
        )
        return row

    async def version(self, use_case_id: str, version: int) -> dict[str, Any]:
        [row] = await self.rows(
            "SELECT n8n_version_id, document, grade, published_by, published_in, made, also"
            " FROM builder.use_case_versions WHERE use_case_id = %s AND version = %s",
            use_case_id,
            version,
        )
        return row

    def nodes(self, workflow_id: str) -> list[dict[str, Any]]:
        return self.n8n.workflows[workflow_id]["nodes"]

    async def shared(self, on: bool = True) -> str:
        """Set up on the shared run workflow, as before E10: Carol set it up, Dave changed when
        it runs, then Alice did."""
        created = await self.lab.call(
            "carol", "POST", "/api/v1/agent-use-cases", {**BODY, "on": on}
        )
        assert created.status_code == 201, created.text
        use_case_id = str(created.json()["use_case_id"])
        old = self.lab.builder
        await old.save_schedule(use_case_id, DAVE, UseCaseScheduleIn(day="monday", at="07:00"))
        await old.save_schedule(use_case_id, ALICE, UseCaseScheduleIn(day="tuesday", at="07:30"))
        assert (await self.use_case(use_case_id))["engine"] == "shared_run"
        return use_case_id

    async def waiting_run(self, use_case_id: str) -> RunId:
        """A run of it on the shared run workflow, waiting for a yes."""
        h = self.lab.h
        spec = replace(SPEC, use_case_id=UseCaseId(use_case_id))
        run_id = (await h.orchestrator.start_run(spec, ALICE, "waiting")).run_id
        await h.orchestrator.tick()
        await h.orchestrator.on_step(run_id, RUN_AGENTS, N8nExecutionId("41"))
        await h.orchestrator.on_step(run_id, ASK_APPROVAL, N8nExecutionId("41"))
        assert isinstance(await h.state(run_id), AwaitingApproval)
        return run_id


@pytest.fixture
async def m(lab: Lab, postgres: PostgresUrls) -> AsyncIterator[Moving]:
    n8n = FakeN8n()
    store = Errors(n8n, lab.h.db)
    cancels = Cancels()
    builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "https://portal.example",
        ModelConnected(),
        n8n=store,
        writes=WRITES,
        open_runs=WatchFacts(lab.h.db, lab.h.jira, lab.h.jira.site.identity),
        requests=cancels,
    )
    yield Moving(lab, n8n, store, builder, postgres.owner, cancels)


def before(nodes: list[dict[str, Any]], connections: dict[str, Any], name: str) -> set[str]:
    return {
        source
        for source, outputs in connections.items()
        for exit_ in outputs["main"]
        for link in exit_
        if link["node"] == name
    } & {n["name"] for n in nodes}


async def test_the_move_lays_it_out_in_n8n_with_its_schedule_and_puts_it_live(m: Moving):
    use_case_id = await m.shared()

    moved = await m.moves.move(use_case_id)

    assert isinstance(moved, MovedToN8n) and moved.version == 4
    trigger = next(n for n in m.nodes(moved.workflow_id) if n["type"] == SCHEDULE_TRIGGER)
    assert trigger["parameters"] == schedule_rule(Schedule("tuesday", "07:30"))
    row = await m.use_case(use_case_id)
    assert (row["engine"], row["n8n_workflow_id"], row["current_version"]) == (
        "own",
        moved.workflow_id,
        4,
    )
    version = await m.version(use_case_id, 4)
    assert (version["grade"], version["made"]) == ("safe", "moved_to_n8n")
    assert m.n8n.workflows[moved.workflow_id]["activeVersionId"] == version["n8n_version_id"]
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.state == "on" and view.next_run_at is not None
    listed = await m.builder.list_versions(use_case_id)
    assert listed is not None
    assert [(v.version, v.made) for v in listed.versions] == [
        (4, "moved_to_n8n"),
        (3, None),
        (2, None),
        (1, None),
    ]


async def test_safety_a_moved_workflow_asks_for_a_yes_before_its_write(m: Moving):
    use_case_id = await m.shared()
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    workflow = m.n8n.workflows[moved.workflow_id]
    assert before(workflow["nodes"], workflow["connections"], CREATE_TICKET) == {ASK_FOR_A_YES}
    assert (await m.version(use_case_id, 4))["grade"] == "safe"


async def test_safety_everyone_whose_work_it_was_stays_a_party_after_the_move(m: Moving):
    use_case_id = await m.shared()
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    version_id = (await m.version(use_case_id, 4))["n8n_version_id"]
    assert await m.builder.facts.version(moved.workflow_id, version_id) == MOVED
    async with m.lab.h.db.connection("orchestration") as conn:
        assert await schedule_owner(conn, UseCaseId(use_case_id)) == ALICE.user_id


async def test_safety_nobody_whose_work_a_moved_workflow_is_approves_its_scheduled_run(w: Writes):
    """The run n8n's Schedule Trigger starts of the version the move made: Alice owns the
    schedule and published it, Carol set it up and Dave changed it. Bob, who is none of them,
    may say yes."""
    w.workflows.versions = {"v1": MOVED}
    await ScheduleBook(w.h.db).save(SPEC.use_case_id, Schedule("tuesday", "07:30"), ALICE)
    await w.ask()
    run = await w.run()
    assert {ALICE.user_id, CAROL.user_id, DAVE.user_id} <= run.parties
    for party in (ALICE, DAVE):
        assert await w.decide(party) == DecisionRefused(Refusal.OWN_WORK), party.display
    assert not isinstance(await w.decide(BOB), DecisionRefused)


async def test_asking_again_changes_nothing(m: Moving):
    use_case_id = await m.shared()
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    assert await m.moves.move(use_case_id) == AlreadyOnN8n()
    assert await m.moves.left() == []
    assert list(m.n8n.workflows) == [moved.workflow_id]


async def test_safety_a_workflow_with_a_waiting_request_stays_until_it_resolves(m: Moving):
    h = m.lab.h
    use_case_id = await m.shared()
    run_id = await m.waiting_run(use_case_id)

    assert await m.moves.move(use_case_id) == WaitsForRun(run_id)
    assert (await m.use_case(use_case_id))["engine"] == "shared_run"
    assert m.n8n.workflows == {}
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.moving_to_n8n

    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None
    decided = await h.orchestrator.decide(
        state.approval_id, BOB, 0, Verdict.APPROVE, detail.request.digest
    )
    assert isinstance(decided, Decided) and isinstance(await h.state(run_id), Acting)
    await h.orchestrator.tick()
    await h.orchestrator.on_step(run_id, WRITE_ACTION, N8nExecutionId("42"))
    assert isinstance(await h.state(run_id), Succeeded)
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]

    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and not view.moving_to_n8n
    runs = (await m.lab.call("alice", "GET", "/api/v1/runs")).json()["runs"]
    assert [(r["run_id"], r["use_case_id"]) for r in runs] == [(run_id, use_case_id)]


async def test_a_move_cut_off_after_the_save_is_finished_by_the_next(m: Moving):
    use_case_id = await m.shared()
    m.n8n.publishing = list(NEVER_LIVE)
    assert not isinstance(await m.moves.move(use_case_id), MovedToN8n)
    assert m.n8n.workflows == {}, "a workflow n8n would not turn on is removed"
    assert (await m.use_case(use_case_id))["n8n_workflow_id"] is None

    m.n8n.publishing = []
    left = await m.store.save_draft(
        {"name": "Cut off", "nodes": [], "connections": {}, "settings": {}}
    )
    async with m.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_cases SET n8n_workflow_id = %s WHERE use_case_id = %s",
            (left.workflow_id, use_case_id),
        )
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    assert list(m.n8n.workflows) == [moved.workflow_id]


async def test_a_paused_workflow_moves_off_with_no_publisher(m: Moving):
    use_case_id = await m.shared()
    assert (await m.lab.move("alice", "pause", use_case_id)).status_code == 200
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    assert m.n8n.workflows[moved.workflow_id]["activeVersionId"] is None
    version = await m.version(use_case_id, 4)
    assert (version["published_by"], version["published_in"]) == (None, None)
    assert version["also"] == [
        {"by": "carol", "in": "portal"},
        {"by": "dave", "in": "portal"},
        {"by": "alice", "in": "portal"},
    ], "the schedule's owner is an author of it until someone resumes it and publishes it"


async def refused_layout(m: Moving, use_case_id: str) -> None:
    """Its card writes to a Jira project the platform no longer writes to."""
    async with m.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            'UPDATE builder.use_case_cards SET "values" = jsonb_set("values",'
            " '{Jira project}', '\"OPS\"') WHERE use_case_id = %s",
            (use_case_id,),
        )


async def test_a_workflow_that_cannot_move_says_why_and_never_that_it_runs(
    m: Moving, caplog: pytest.LogCaptureFixture
):
    use_case_id = await m.shared()
    await refused_layout(m, use_case_id)

    assert isinstance(await m.moves.move(use_case_id), DraftRefused)
    assert isinstance(await m.moves.move(use_case_id), DraftRefused)

    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.next_run_at is None and not view.moving_to_n8n
    assert view.move_refused == (
        "Not running. It could not move to its own n8n workflow:"
        ' "Compare" writes to a place the platform does not allow.'
        " Fix that step, or ask for help."
    )
    refusals = [r for r in caplog.records if r.levelname == "ERROR" and "stays" in r.message]
    assert len(refusals) == 1, "a refusal is logged once, not on every pass"


async def test_a_workflow_n8n_would_not_take_says_so_and_clears_once_it_moves(m: Moving):
    use_case_id = await m.shared()
    m.n8n.keeps = lambda document: {**document, "name": "Not what was sent"}
    assert isinstance(await m.moves.move(use_case_id), N8nNotReady)
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.move_refused == (
        "Not running. n8n did not take it yet, so it can't run on its schedule."
        " The platform tries again every minute. If this stays, ask for help."
    )

    m.n8n.keeps = lambda document: document
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.move_refused is None


async def test_a_held_schedule_stays_until_an_operator_saves_it(m: Moving):
    use_case_id = await m.shared()
    async with m.lab.h.db.transaction("orchestration") as uow:
        await uow.conn.execute(
            "UPDATE orchestration.people SET removed_at = now() WHERE id = 'alice'"
        )
    assert await m.moves.move(use_case_id) == ScheduleHeld("owner_removed")
    await m.lab.builder.save_schedule(
        use_case_id, CAROL, UseCaseScheduleIn(day="friday", at="09:00")
    )
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)


async def test_run_now_moves_it_first(m: Moving):
    use_case_id = await m.shared()
    m.lab.app.state.builder = m.builder
    started = await m.lab.call("alice", "POST", f"/api/v1/use-cases/{use_case_id}/runs")
    assert started.status_code == 201, started.text
    assert (await m.use_case(use_case_id))["engine"] == "own"
    async with m.lab.h.db.connection("orchestration") as conn:
        row = await (
            await conn.execute(
                "SELECT spec -> 'n8n' ->> 'workflow_id' AS workflow_id FROM orchestration.runs"
            )
        ).fetchone()
    assert row is not None
    assert row["workflow_id"] == (await m.use_case(use_case_id))["n8n_workflow_id"]


async def test_a_deleted_workflow_is_left_where_it_is(m: Moving):
    use_case_id = await m.shared()
    assert (await m.lab.move("alice", "delete", use_case_id)).status_code == 200
    assert await m.moves.left() == []
    assert await m.moves.move(use_case_id) is None


async def lose_n8n(m: Moving) -> list[str]:
    """n8n's database is lost: bootstrap found none of the workflows on record, asked for a
    restore of them, and loaded the error workflow anew."""
    lost = [
        row["n8n_workflow_id"]
        for row in await m.rows(
            "SELECT n8n_workflow_id FROM builder.use_cases WHERE engine = 'own'"
        )
    ]
    m.n8n.workflows.clear()
    m.store.error_workflow = NEW_ERROR_WORKFLOW
    ask_for_restore(m.owner_url, lost, lambda _: None)
    return lost


async def sweep(m: Moving) -> None:
    assert m.builder.sweep is not None
    await m.builder.sweep.sweep()


async def marked(m: Moving, use_case_id: str) -> bool:
    [row] = await m.rows(
        "SELECT deleted_in_n8n_at FROM builder.use_cases WHERE use_case_id = %s", use_case_id
    )
    return row["deleted_in_n8n_at"] is not None


async def test_restore_saves_each_lost_workflow_again_from_the_version_kept(m: Moving):
    use_case_id = await m.shared()
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    published = await m.version(use_case_id, 4)
    await lose_n8n(m)

    [restored] = await m.moves.restore_if_asked()

    assert isinstance(restored, Restored) and restored.workflow_id != moved.workflow_id
    workflow = m.n8n.workflows[restored.workflow_id]
    assert workflow["settings"]["errorWorkflow"] == NEW_ERROR_WORKFLOW
    version = await m.version(use_case_id, 4)
    assert workflow["activeVersionId"] == version["n8n_version_id"]
    assert (version["published_by"], version["also"]) == (
        published["published_by"],
        published["also"],
    )
    assert (await m.use_case(use_case_id))["n8n_workflow_id"] == restored.workflow_id
    assert await m.rows("SELECT 1 FROM builder.n8n_restore") == [], "the ask is answered"
    assert await m.moves.restore_if_asked() == ()


async def test_safety_restore_never_puts_back_a_version_kept_as_unsafe(m: Moving):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    async with m.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET grade = 'writes_refused' WHERE use_case_id = %s"
            " AND version = 4",
            (use_case_id,),
        )
    await lose_n8n(m)
    assert await m.moves.restore_if_asked() == [NotSafe()]
    assert m.n8n.workflows == {}


async def test_safety_restore_never_puts_back_a_version_that_no_longer_grades_safe(m: Moving):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    document = (await m.version(use_case_id, 4))["document"]
    document["nodes"] = [n for n in document["nodes"] if n["name"] != ASK_FOR_A_YES]
    async with m.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_case_versions SET document = %s WHERE use_case_id = %s"
            " AND version = 4",
            (json(document), use_case_id),
        )
    await lose_n8n(m)
    assert await m.moves.restore_if_asked() == [NotSafe()]
    assert m.n8n.workflows == {}


async def test_safety_while_a_restore_is_asked_the_sweep_never_marks_a_lost_workflow_deleted(
    m: Moving,
):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)

    await sweep(m)

    assert not await marked(m, use_case_id) and m.cancels.asked == []
    [restored] = await m.moves.restore_if_asked()
    assert isinstance(restored, Restored)
    await sweep(m)
    assert not await marked(m, use_case_id), "n8n holds it again"


async def test_safety_a_workflow_deleted_in_n8n_after_the_ask_is_marked_and_its_request_ends(
    m: Moving,
):
    lost_one = await m.shared()
    assert isinstance(await m.moves.move(lost_one), MovedToN8n)
    await lose_n8n(m)
    later = await m.shared()
    moved = await m.moves.move(later)
    assert isinstance(moved, MovedToN8n)
    del m.n8n.workflows[moved.workflow_id]

    await sweep(m)

    assert (await marked(m, lost_one), await marked(m, later)) == (False, True)
    assert m.cancels.asked == [later]


async def test_safety_an_ask_never_answered_expires_and_the_sweep_marks_what_is_still_missing(
    m: Moving,
):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)
    with psycopg.connect(m.owner_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE builder.n8n_restore SET asked_at = now() - %s", (RESTORE_ASK_LIVES * 1.1,)
        )

    await sweep(m)

    assert await marked(m, use_case_id) and m.cancels.asked == [use_case_id]


async def test_one_restore_pass_answers_the_ask_even_when_n8n_did_not_take_a_workflow(
    m: Moving,
):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)
    m.n8n.keeps = lambda document: {**document, "name": "Not what was sent"}

    assert await m.moves.restore_if_asked() == [N8nNotReady(NOT_BACK)]

    assert await m.rows("SELECT 1 FROM builder.n8n_restore") == []
    await sweep(m)
    assert await marked(m, use_case_id), "deleted in n8n, which a person may restore"


async def mark_deleted_in_n8n(m: Moving, use_case_id: str, since_the_ask: timedelta) -> None:
    with psycopg.connect(m.owner_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE builder.use_cases SET deleted_in_n8n_at ="
            " (SELECT asked_at FROM builder.n8n_restore) + %s WHERE use_case_id = %s",
            (since_the_ask, use_case_id),
        )


async def test_a_workflow_marked_deleted_after_the_restore_was_asked_comes_back(m: Moving):
    """An older replica's sweep got there first, during a rolling deploy."""
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)
    await mark_deleted_in_n8n(m, use_case_id, timedelta(seconds=30))

    [restored] = await m.moves.restore_if_asked()

    assert isinstance(restored, Restored)
    view = await m.builder.get_use_case(use_case_id)
    assert view is not None and view.deleted_in_n8n_at is None


async def test_a_workflow_deleted_in_n8n_before_the_restore_was_asked_stays_deleted(m: Moving):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)
    await mark_deleted_in_n8n(m, use_case_id, -timedelta(days=1))

    assert await m.moves.restore_if_asked() == []
    assert m.n8n.workflows == {}


async def test_a_restore_cut_off_before_it_went_live_is_finished_by_the_next(m: Moving):
    use_case_id = await m.shared()
    assert isinstance(await m.moves.move(use_case_id), MovedToN8n)
    await lose_n8n(m)
    live = m.store.go_live

    async def dies(workflow_id: str, version_id: str) -> None:
        raise asyncio.CancelledError("platform-api stopped")

    m.store.go_live = dies  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await m.moves.restore_if_asked()
    m.store.go_live = live  # type: ignore[method-assign]

    [restored] = await m.moves.restore_if_asked()

    assert isinstance(restored, Restored)
    assert list(m.n8n.workflows) == [restored.workflow_id], "the cut-off draft is gone"
    version = await m.version(use_case_id, 4)
    assert m.n8n.workflows[restored.workflow_id]["activeVersionId"] == version["n8n_version_id"]


async def test_restore_leaves_a_workflow_n8n_still_holds(m: Moving):
    use_case_id = await m.shared()
    moved = await m.moves.move(use_case_id)
    assert isinstance(moved, MovedToN8n)
    await lose_n8n(m)
    kept = await m.store.save_draft(
        {"name": "Still there", "nodes": [], "connections": {}, "settings": {}}
    )
    async with m.lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.use_cases SET n8n_workflow_id = %s WHERE use_case_id = %s",
            (kept.workflow_id, use_case_id),
        )
    assert await m.moves.restore_if_asked() == []
    assert list(m.n8n.workflows) == [kept.workflow_id]
