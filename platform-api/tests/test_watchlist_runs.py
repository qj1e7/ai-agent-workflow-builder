from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

import pytest

from platform_api.orchestration.agents import (
    CarryForward,
    Finding,
    GithubSource,
    ProposedIntentIn,
    SoftwareToCheck,
    TaskError,
    TaskOutput,
    WatchlistInputs,
)
from platform_api.orchestration.approvals import Verdict
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Failed,
    FailureReason,
    Proposed,
    StepName,
    Succeeded,
)
from platform_api.orchestration.service import Decided, StepReply
from platform_api.orchestration.spec import RunSpec
from platform_api.orchestration.watch import (
    Checked,
    CouldNotCheck,
    FromFirstCheck,
    FromTicketDone,
    Given,
    KnownNewest,
    OpenTicket,
    PendingTicket,
    ReadNewest,
    Reviewed,
    SoftwareFacts,
    Standing,
    TicketToPropose,
)
from platform_api.orchestration.watch_store import WatchFacts, WatchlistStanding, WatchStore
from platform_api.shared import N8nExecutionId, RunId, SoftwareId
from tests.conftest import PostgresUrls
from tests.support import (
    ALICE,
    BOB,
    FASTAPI,
    LANGGRAPH,
    NOW,
    POSTGRES,
    REDIS,
    WATCHLIST_SPEC,
    WATCHLIST_TASK,
    watched,
)
from tests.test_orchestrator import Harness, open_harness

pytestmark = pytest.mark.anyio

WORK = N8nExecutionId("41")
ACT = N8nExecutionId("42")
USE_CASE = WATCHLIST_SPEC.use_case_id
TASK = WATCHLIST_TASK
GIVEN = {
    LANGGRAPH: Given("1.2.14", NOW),
    REDIS: None,
    FASTAPI: Given("0.115.0", NOW),
    POSTGRES: Given("17.2.0", NOW),
}
SUMMARY = (
    "1 of 4 watched software has a new release: LangGraph 1.2.16. FastAPI could not be checked."
)
NOT_FOUND = "GitHub answered 404 Not Found."


def finding(software_id: SoftwareId, state: str, newest: str | None, detail: str = "") -> Finding:
    return Finding.model_validate(
        {
            "software_id": software_id,
            "state": state,
            "newest": newest,
            "new_versions": [newest] if state == "behind" and newest else [],
            "detail": detail,
        }
    )


def upgrade_ticket(subject: str | None, name: str, ours: str, newest: str) -> ProposedIntentIn:
    return ProposedIntentIn(
        kind="create_ticket",
        fields={"title": f"Upgrade {name} from {ours} to {newest}", "body": "..."},
        reason=f"{name} {newest} is out, and we run {ours}",
        subject=subject,
    )


LANGGRAPH_TICKET = upgrade_ticket(LANGGRAPH, "LangGraph", "1.2.14", "1.2.16")

ONE_BEHIND = TaskOutput(
    summary=SUMMARY,
    new_tags=[],
    proposed=[LANGGRAPH_TICKET],
    carry_forward=CarryForward(),
    findings=[
        finding(LANGGRAPH, "behind", "1.2.16"),
        finding(REDIS, "starting_point", "8.2.1"),
        finding(FASTAPI, "cant_check", None, NOT_FOUND),
        finding(POSTGRES, "up_to_date", "17.2.0"),
    ],
)


@pytest.fixture
async def h(postgres: PostgresUrls) -> AsyncIterator[Harness]:
    async with open_harness(postgres) as harness:
        harness.agent.output = ONE_BEHIND
        yield harness


def facts_of(h: Harness) -> WatchFacts:
    return WatchFacts(h.db, h.jira)


async def standings(h: Harness) -> WatchlistStanding:
    return await facts_of(h).standings(USE_CASE, GIVEN)


async def start_check(h: Harness, spec: RunSpec = WATCHLIST_SPEC, key: str = "check-1") -> RunId:
    started = await h.orchestrator.start_run(spec, ALICE, key)
    await h.orchestrator.tick()
    return started.run_id


async def work_leg(h: Harness, spec: RunSpec = WATCHLIST_SPEC) -> RunId:
    run_id = await start_check(h, spec)
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, WORK)
    await h.orchestrator.tick()
    return run_id


async def bob_decides(h: Harness, run_id: RunId, verdict: Verdict) -> None:
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None
    decided = await h.orchestrator.decide(state.approval_id, BOB, 0, verdict, detail.request.digest)
    assert isinstance(decided, Decided)
    await h.orchestrator.tick()


async def test_a_check_asks_the_agents_about_every_watched_software(h: Harness):
    await work_leg(h)
    [request] = h.agent.requests
    assert request.inputs == WatchlistInputs(
        tag_pattern=TASK.tag_pattern,
        software=[
            SoftwareToCheck(
                id=LANGGRAPH,
                name="LangGraph",
                source=GithubSource(ref="langchain-ai/langgraph"),
                our_version="1.2.14",
            ),
            SoftwareToCheck(
                id=REDIS, name="Redis", source=GithubSource(ref="redis/redis"), our_version=None
            ),
            SoftwareToCheck(
                id=FASTAPI,
                name="FastAPI",
                source=GithubSource(ref="fastapi/fastapi"),
                our_version="0.115.0",
            ),
            SoftwareToCheck(
                id=POSTGRES,
                name="PostgreSQL",
                source=GithubSource(ref="postgres/postgres"),
                our_version="17.2.0",
            ),
        ],
    )
    assert request.carry_forward == CarryForward()
    assert request.instruction == WATCHLIST_SPEC.instruction


async def test_the_teams_message_names_every_ticket_of_the_check(h: Harness):
    h.agent.output = ONE_BEHIND.model_copy(
        update={
            "proposed": [
                LANGGRAPH_TICKET,
                upgrade_ticket(POSTGRES, "PostgreSQL", "17.2.0", "17.3.0"),
            ],
            "findings": [
                finding(LANGGRAPH, "behind", "1.2.16"),
                finding(REDIS, "starting_point", "8.2.1"),
                finding(FASTAPI, "cant_check", None, NOT_FOUND),
                finding(POSTGRES, "behind", "17.3.0"),
            ],
        }
    )
    await work_leg(h)
    [message] = await h.teams.messages()
    assert message.text == (
        "A run of the Software watchlist needs an Approver. It would create 2 Jira tickets in "
        'MOCK: "Upgrade LangGraph from 1.2.14 to 1.2.16" and '
        '"Upgrade PostgreSQL from 17.2.0 to 17.3.0". '
        f"Open the approval page to decide. The agents said: {SUMMARY}"
    )


async def test_a_check_records_what_it_found_and_proposes_one_ticket_per_software_behind(
    h: Harness,
):
    run_id = await work_leg(h)
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    detail = await h.orchestrator.get_approval(state.approval_id, BOB)
    assert detail is not None
    assert [a.fields["title"] for a in detail.proposal.actions] == [
        "Upgrade LangGraph from 1.2.14 to 1.2.16"
    ]

    found = await standings(h)
    assert found.last_check is not None
    assert (found.last_check.run_id, found.last_check.state) == (run_id, "awaiting_approval")
    checked_at = NOW
    assert found.software[LANGGRAPH] == Standing(
        SoftwareFacts(
            Given("1.2.14", NOW),
            Checked(run_id, checked_at, "1.2.16"),
            PendingTicket(detail.proposal.id, 0, "1.2.16", state.approval_id),
            None,
        ),
        "awaiting_approval",
    )
    assert found.software[REDIS] == Standing(
        SoftwareFacts(
            FromFirstCheck("8.2.1", checked_at), Checked(run_id, checked_at, "8.2.1"), None, None
        ),
        "up_to_date",
    )
    assert found.software[FASTAPI] == Standing(
        SoftwareFacts(
            Given("0.115.0", NOW), CouldNotCheck(run_id, checked_at, NOT_FOUND), None, None
        ),
        "cant_check",
    )
    assert found.software[POSTGRES].status == "up_to_date"
    assert await h.jira.tickets() == []


async def test_approving_writes_the_tickets_and_marking_one_done_moves_our_version(h: Harness):
    run_id = await work_leg(h)
    await bob_decides(h, run_id, Verdict.APPROVE)
    reply = await h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, ACT)
    assert reply == StepReply(True, "written", "Created MOCK-1")
    assert isinstance(await h.state(run_id), Succeeded)

    open_facts = (await standings(h)).software[LANGGRAPH]
    assert open_facts.status == "ticket_open"
    assert open_facts.facts.open_ticket == OpenTicket("MOCK-1", "1.2.16")
    assert open_facts.facts.our_version == Given("1.2.14", NOW)
    [ticket] = await h.jira.tickets()
    assert (ticket.status, ticket.done_at) == ("To Do", None)

    h.advance(timedelta(days=2))
    done_at = h.clock["now"]
    marked = await h.jira.mark_done("MOCK-1")
    assert marked is not None and (marked.status, marked.done_at) == ("Done", done_at)

    moved = (await standings(h)).software[LANGGRAPH]
    assert moved == Standing(
        SoftwareFacts(
            FromTicketDone("1.2.16", done_at, "MOCK-1"), Checked(run_id, NOW, "1.2.16"), None, None
        ),
        "up_to_date",
    )
    assert (await standings(h)).software[LANGGRAPH] == moved, "a second refresh changes nothing"


async def test_marking_a_ticket_done_twice_keeps_the_first_done_time(h: Harness):
    run_id = await work_leg(h)
    await bob_decides(h, run_id, Verdict.APPROVE)
    await h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, ACT)
    first = await h.jira.mark_done("MOCK-1")
    h.advance(timedelta(hours=1))
    again = await h.jira.mark_done("MOCK-1")
    assert first == again
    assert await h.jira.mark_done("MOCK-404") is None
    assert await h.jira.done_tickets(["MOCK-1", "MOCK-404"]) == {"MOCK-1": NOW}


async def test_declining_drops_the_tickets_and_the_software_shows_behind(h: Harness):
    run_id = await work_leg(h)
    await bob_decides(h, run_id, Verdict.DECLINE)
    found = (await standings(h)).software[LANGGRAPH]
    assert found.status == "behind"
    assert (found.facts.pending, found.facts.open_ticket) == (None, None)
    assert found.facts.latest_check == Checked(run_id, NOW, "1.2.16")
    assert await h.jira.tickets() == []


async def test_a_failed_write_drops_the_tickets_and_a_retry_still_writes_them(h: Harness):
    run_id = await work_leg(h)
    await bob_decides(h, run_id, Verdict.APPROVE)
    await h.orchestrator.on_workflow_failure(ACT, "run", "Do write action", "timed out")
    assert isinstance(await h.state(run_id), Failed)
    assert (await standings(h)).software[LANGGRAPH].status == "behind"

    await h.orchestrator.retry(run_id, ALICE)
    h.advance(timedelta(seconds=3))
    await h.orchestrator.tick()
    assert isinstance(await h.state(run_id), Acting)
    reply = await h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, N8nExecutionId("43"))
    assert reply.outcome == "written"
    found = (await standings(h)).software[LANGGRAPH]
    assert found.status == "ticket_open"
    assert found.facts.open_ticket == OpenTicket("MOCK-1", "1.2.16")


async def test_a_run_that_fails_after_proposing_drops_its_tickets(h: Harness):
    run_id = await start_check(h)
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    assert isinstance(await h.state(run_id), Proposed)
    assert (await standings(h)).software[LANGGRAPH].status == "awaiting_approval"
    await h.orchestrator.on_workflow_failure(WORK, "run", "Ask approval", "boom")
    assert isinstance(await h.state(run_id), Failed)
    assert (await standings(h)).software[LANGGRAPH].status == "behind"


NOTHING_BEHIND = TaskOutput(
    summary="All 4 watched software are up to date.",
    new_tags=[],
    proposed=[],
    carry_forward=CarryForward(),
    findings=[
        finding(LANGGRAPH, "up_to_date", "1.2.14"),
        finding(REDIS, "starting_point", "8.2.1"),
        finding(FASTAPI, "up_to_date", "0.115.0"),
        finding(POSTGRES, "up_to_date", "17.2.0"),
    ],
)
UNREADABLE = "Could not check LangGraph: GitHub returned 503 Service Unavailable three times"


async def test_a_check_with_nothing_behind_records_the_findings_and_writes_nothing(h: Harness):
    h.agent.output = NOTHING_BEHIND
    run_id = await start_check(h)
    reply = await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    assert reply == StepReply(False, "nothing_to_write", "All 4 watched software are up to date.")
    found = await standings(h)
    assert {sid: s.status for sid, s in found.software.items()} == {
        LANGGRAPH: "up_to_date",
        REDIS: "up_to_date",
        FASTAPI: "up_to_date",
        POSTGRES: "up_to_date",
    }
    assert found.software[REDIS].facts.our_version == FromFirstCheck("8.2.1", NOW)
    assert found.last_check is not None and found.last_check.state == "succeeded"


async def checked_once_then_failed(
    h: Harness, error: TaskError | None = None
) -> tuple[RunId, RunId]:
    h.agent.output = NOTHING_BEHIND
    first = await start_check(h)
    await h.orchestrator.on_step(first, StepName.RUN_AGENTS, WORK)
    h.advance(timedelta(hours=1))
    h.agent.mode = "failed"
    h.agent.error = error
    second = await start_check(h, key="check-2")
    reply = await h.orchestrator.on_step(second, StepName.RUN_AGENTS, N8nExecutionId("42"))
    assert (reply.proceed, reply.outcome) == (False, "failed")
    assert isinstance(await h.state(second), Failed)
    return first, second


READ_FIRST = {LANGGRAPH: "1.2.14", REDIS: "8.2.1", FASTAPI: "0.115.0", POSTGRES: "17.2.0"}


async def test_a_check_that_reads_no_source_marks_every_software_cant_check_and_says_why(
    h: Harness,
):
    _, failed = await checked_once_then_failed(h)
    found = await standings(h)
    later = NOW + timedelta(hours=1)
    assert {sid: s.facts.latest_check for sid, s in found.software.items()} == {
        sid: CouldNotCheck(failed, later, f"{UNREADABLE}.", KnownNewest(read, NOW))
        for sid, read in READ_FIRST.items()
    }
    assert {s.status for s in found.software.values()} == {"cant_check"}
    assert found.software[REDIS].facts.our_version == FromFirstCheck("8.2.1", NOW)
    assert found.last_check is not None
    assert (found.last_check.run_id, found.last_check.state) == (failed, "failed")


async def test_a_software_that_cannot_be_read_keeps_the_newest_version_read_before_and_when(
    h: Harness,
):
    h.agent.output = NOTHING_BEHIND
    first = await start_check(h)
    await h.orchestrator.on_step(first, StepName.RUN_AGENTS, WORK)
    h.advance(timedelta(hours=1))
    h.agent.output = NOTHING_BEHIND.model_copy(
        update={
            "findings": [
                finding(LANGGRAPH, "up_to_date", "1.2.14"),
                finding(REDIS, "starting_point", "8.2.1"),
                finding(FASTAPI, "cant_check", None, NOT_FOUND),
                finding(POSTGRES, "up_to_date", "17.2.0"),
            ]
        }
    )
    second = await start_check(h, key="check-2")
    await h.orchestrator.on_step(second, StepName.RUN_AGENTS, N8nExecutionId("42"))
    found = await standings(h)
    later = NOW + timedelta(hours=1)
    assert found.software[FASTAPI].facts.latest_check == CouldNotCheck(
        second, later, NOT_FOUND, KnownNewest("0.115.0", NOW)
    )
    assert found.software[FASTAPI].status == "cant_check"
    assert found.software[POSTGRES].facts.latest_check == Checked(second, later, "17.2.0")

    h.advance(timedelta(hours=1))
    h.agent.output = NOTHING_BEHIND
    third = await start_check(h, key="check-3")
    await h.orchestrator.on_step(third, StepName.RUN_AGENTS, N8nExecutionId("43"))
    read_again = (await standings(h)).software[FASTAPI].facts.latest_check
    assert read_again == Checked(third, later + timedelta(hours=1), "0.115.0")


async def test_a_check_that_fails_for_another_reason_keeps_what_the_last_check_found(
    h: Harness,
):
    crashed = TaskError(type="AgentError", message="The agent stopped", retryable=False)
    first, failed = await checked_once_then_failed(h, crashed)
    found = await standings(h)
    assert {s.status for s in found.software.values()} == {"up_to_date"}
    assert found.software[FASTAPI].facts.latest_check == Checked(first, NOW, "0.115.0")
    assert found.last_check is not None
    assert (found.last_check.run_id, found.last_check.state) == (failed, "failed")


HELD_SPEC = replace(
    WATCHLIST_SPEC,
    task=replace(
        TASK,
        software=(
            watched(
                LANGGRAPH, "LangGraph", "langchain-ai/langgraph", "1.2.14", open_ticket="MOCK-3"
            ),
            *TASK.software[1:],
        ),
    ),
)


@pytest.mark.parametrize(
    ("spec", "proposed", "words"),
    [
        (
            WATCHLIST_SPEC,
            [upgrade_ticket("sw_ghost", "Ghost", "1.0.0", "1.0.1")],
            "not on the list",
        ),
        (WATCHLIST_SPEC, [upgrade_ticket(None, "LangGraph", "1.2.14", "1.2.16")], "without naming"),
        (WATCHLIST_SPEC, [LANGGRAPH_TICKET, LANGGRAPH_TICKET], "two tickets for LangGraph"),
        (HELD_SPEC, [LANGGRAPH_TICKET], "LangGraph, which has one already"),
        (
            WATCHLIST_SPEC,
            [upgrade_ticket(LANGGRAPH, "LangGraph", "1.2.14", "1.2.17")],
            'differently from "Upgrade LangGraph from 1.2.14 to 1.2.16"',
        ),
    ],
    ids=["unknown", "unnamed", "twice", "held", "mistitled"],
)
async def test_a_ticket_for_unknown_or_held_software_fails_the_run_for_good(
    h: Harness, spec: RunSpec, proposed: list[ProposedIntentIn], words: str
):
    h.agent.output = ONE_BEHIND.model_copy(update={"proposed": proposed})
    run_id = await start_check(h, spec)
    reply = await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    assert (reply.proceed, reply.outcome) == (False, "failed")
    assert words in reply.detail
    state = await h.state(run_id)
    assert isinstance(state, Failed)
    assert (state.failure.reason, state.failure.retryable) == (FailureReason.AGENT_ERROR, False)
    assert (await h.kinds(run_id))[-2:] == ["step_finished", "run_failed"]
    found = await standings(h)
    assert all(s.facts.latest_check is None for s in found.software.values())


async def test_recording_the_same_review_twice_changes_nothing(h: Harness):
    run_id = await start_check(h)
    reviewed = Reviewed(
        (ReadNewest(REDIS, "8.2.1", True), ReadNewest(LANGGRAPH, "1.2.16", False)),
        (TicketToPropose(0, LANGGRAPH, "1.2.16"),),
    )
    store = WatchStore()
    async with h.db.transaction("orchestration") as uow:
        record = await h.orchestrator._store.load_run(uow, run_id)  # pyright: ignore[reportPrivateUsage]
        assert record is not None
        await store.record_review(uow, record, reviewed, None)
        once = await store.facts(uow, USE_CASE)
        await store.record_review(uow, record, reviewed, None)
        twice = await store.facts(uow, USE_CASE)
    assert once == twice
    assert once.learned == {REDIS: FromFirstCheck("8.2.1", NOW)}
    assert once.checks[LANGGRAPH] == Checked(run_id, NOW, "1.2.16")
