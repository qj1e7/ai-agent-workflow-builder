"""A version edited in n8n never writes without its yes (ENGINE-PLAN 2.3.11, E6, D5, D7). A version
the safety checker graded anything but safe asks nobody and writes nothing, whatever yes is on
record. A version whose publisher we can't match stops every run of it, however it started.
Whoever published a version, or the workflow it puts back, joins every run of it. A deleted
workflow's run never writes, and its open request ends cancelled with its Approvers told."""

import pytest

from platform_api.orchestration.approvals import Ended
from platform_api.orchestration.n8n_calls import (
    DELETED_BEFORE,
    UNKNOWN_PUBLISHER,
    WRITES_REFUSED,
    Answer,
    Publisher,
    RanVersion,
)
from platform_api.orchestration.n8n_starts import issue_start
from platform_api.orchestration.runs import (
    DELETED_BEFORE_AN_ANSWER,
    Expired,
    Failed,
    FailureReason,
    Lost,
    RunState,
)
from platform_api.orchestration.store import SHOW_OUTCOME, WAKE, Store
from platform_api.shared import UseCaseId, UserId
from tests.support import BOB, SPEC
from tests.test_n8n_calls import ALICE, DAVE, RELEASE, WORKFLOW, Calls, t
from tests.test_n8n_write import Writes, w

pytestmark = pytest.mark.anyio

__all__ = ["t", "w"]

UNSAFE = [
    pytest.param(RanVersion("writes_refused", Publisher(ALICE)), id="writes-refused"),
    pytest.param(RanVersion("needs_a_fix", Publisher(ALICE)), id="needs-a-fix"),
]


def stopped_by(state: RunState, words: str) -> bool:
    return (
        isinstance(state, Failed)
        and state.failure.reason is FailureReason.SAFETY_DENIED
        and state.failure.message == words
        and not state.failure.retryable
    )


async def test_safety_a_version_graded_writes_refused_asks_nobody_and_stops(w: Writes):
    w.workflows.versions["v1"] = RanVersion("writes_refused", Publisher(ALICE))
    assert await w.ask() == WRITES_REFUSED
    assert stopped_by((await w.run()).state, WRITES_REFUSED.detail)
    assert await w.rows("SELECT 1 FROM orchestration.approval_requests") == []
    assert await w.ask() == WRITES_REFUSED, "n8n's retryOnFail gets the same refusal"


@pytest.mark.parametrize("unsafe", UNSAFE)
async def test_safety_a_version_graded_unsafe_after_its_yes_never_writes(
    w: Writes, unsafe: RanVersion
):
    """The yes was given on a version since graded unsafe, as a sweep graded it again: only
    the refusal at the write stops it, because the gateway alone would make the change."""
    await w.acting()
    w.workflows.versions["v1"] = unsafe
    assert await w.write() == WRITES_REFUSED
    assert await w.tickets() == []
    assert stopped_by((await w.run()).state, WRITES_REFUSED.detail)


async def test_safety_a_deleted_workflows_run_never_writes_though_its_yes_was_given(w: Writes):
    await w.acting()
    w.workflows.gone.add(WORKFLOW)
    assert await w.write() == DELETED_BEFORE
    assert await w.tickets() == []
    assert stopped_by((await w.run()).state, DELETED_BEFORE.detail)


async def test_safety_an_open_request_survives_a_deleted_workflow_as_cancelled(w: Writes):
    await w.ask()
    assert await w.orchestrator.cancel_for_deleted(UseCaseId(SPEC.use_case_id)) == 1
    run = await w.run()
    assert isinstance(run.state, Expired)
    async with w.h.db.transaction("orchestration") as uow:
        request = await Store().load_approval(uow, await w.approval_id())
    assert request is not None and request.ended is Ended.CANCELLED
    assert (await w.h.kinds(run.run_id))[-1] == "run_expired"
    [said] = [e.summary for e in await w.h.log.read_after(run.run_id, 0) if e.kind == "run_expired"]
    assert said == DELETED_BEFORE_AN_ANSWER == "Deleted before an answer. Nothing was written."
    outcomes = await w.rows(
        "SELECT payload FROM orchestration.outbox WHERE kind = %s", SHOW_OUTCOME
    )
    assert [o["payload"]["verdict"] for o in outcomes] == ["cancelled"]
    assert await w.wake_rows() == [], "an archived workflow's execution is never woken"
    refused = await w.decide(BOB)
    assert await w.wake_rows() == [], f"a late yes wakes nothing: {refused}"
    assert await w.write() != Answer(())
    assert await w.tickets() == []
    assert await w.orchestrator.cancel_for_deleted(UseCaseId(SPEC.use_case_id)) == 0


async def test_safety_a_yes_n8n_has_not_taken_is_lost_with_its_wake_held_back(w: Writes):
    await w.ask()
    w.waits.answer = "down"
    await w.decide(BOB)
    assert [r["status"] for r in await w.wake_rows()] == ["pending"]
    await w.orchestrator.cancel_for_deleted(UseCaseId(SPEC.use_case_id))
    assert isinstance((await w.run()).state, Lost)
    assert [r["status"] for r in await w.wake_rows()] == ["cancelled"]
    assert (
        await w.rows(
            "SELECT 1 FROM orchestration.outbox WHERE kind = %s AND status = 'pending'", WAKE
        )
        == []
    )


async def test_safety_a_run_now_of_a_version_published_by_someone_we_dont_know_stops(t: Calls):
    t.workflows.versions["v2"] = RanVersion("safe", Publisher(None))
    run_id = await t.pending_run()
    start = await issue_start(t.h.db, "test-start-secret", run_id, "run_now", WORKFLOW, "hook-1")
    t.started("101", "webhook", nonce=str(start.body["nonce"]), version="v2")
    assert await t.call("101") == UNKNOWN_PUBLISHER
    assert stopped_by((await t.only_run()).state, UNKNOWN_PUBLISHER.detail)
    assert t.sources.reads == []


async def test_safety_a_version_putting_back_an_unknown_publishers_workflow_stops(t: Calls):
    """Bob rolled back to a version published in n8n by someone we can't match: the run is
    theirs too, so it stops as theirs would."""
    t.workflows.versions["v2"] = RanVersion("safe", Publisher(UserId("bob")), (Publisher(None),))
    t.started("101", version="v2")
    assert await t.call("101") == UNKNOWN_PUBLISHER
    assert await t.runs() == []


async def test_safety_whoever_published_the_workflow_a_version_puts_back_joins_its_runs(
    t: Calls,
):
    t.workflows.versions["v2"] = RanVersion("safe", Publisher(UserId("bob")), (Publisher(DAVE),))
    t.started("101", version="v2")
    assert await t.call("101") == Answer((RELEASE,))
    run = await t.only_run()
    assert run.started_by == "bob"
    assert DAVE in run.parties


async def test_safety_the_publisher_joins_a_run_now_of_their_version(t: Calls):
    t.workflows.versions["v2"] = RanVersion("safe", Publisher(DAVE))
    run_id = await t.pending_run()
    start = await issue_start(t.h.db, "test-start-secret", run_id, "run_now", WORKFLOW, "hook-1")
    t.started("101", "webhook", nonce=str(start.body["nonce"]), version="v2")
    assert await t.call("101") == Answer((RELEASE,))
    assert DAVE in (await t.only_run()).parties
