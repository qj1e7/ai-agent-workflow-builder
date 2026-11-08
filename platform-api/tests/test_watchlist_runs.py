from collections.abc import AsyncIterator, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import pytest

from platform_api.builder.lifecycle import On
from platform_api.builder.watchlist import ListedSoftware, WatchlistRecord, given_versions, task
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
from platform_api.orchestration.dispatch import identity_of
from platform_api.orchestration.jira import PRACTICE_SITE, JiraWriteConnector
from platform_api.orchestration.runs import (
    Acting,
    AwaitingApproval,
    Failed,
    FailureReason,
    Proposed,
    StepName,
    Succeeded,
)
from platform_api.orchestration.service import Decided, Orchestrator, StepReply
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
from platform_api.orchestration.write_actions import (
    Json,
    Site,
    WriteAction,
    WriteGateway,
    WriteKey,
)
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
from tests.test_orchestrator import PUBLIC_BASE_URL, Harness, mint, open_harness

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
    return WatchFacts(h.db, h.jira, h.jira.site.identity)


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


B_SITE = Site(identity_of("jira", "https://jira-b.example"), "jira-b.example")


@dataclass
class JiraB:
    """A second Jira site with a project MOCK. It makes MOCK-901 onwards, and its own MOCK-1 was
    closed long ago."""

    name = "jira"
    operations = JiraWriteConnector.operations
    site = B_SITE
    asked: list[list[str]] = field(default_factory=list[list[str]])
    made: list[str] = field(default_factory=list[str])

    async def execute(self, action: WriteAction, key: WriteKey) -> str:
        self.made.append(str(action.fields["title"]))
        return f"MOCK-{900 + len(self.made)}"

    def link(self, reference: str) -> str | None:
        return None

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]:
        self.asked.append(list(keys))
        return {key: NOW - timedelta(days=300) for key in keys if key == "MOCK-1"}


def restart_on_jira_b(h: Harness, b: JiraB) -> WatchFacts:
    """platform-api again with JIRA_BASE_URL set to Jira B, as wiring builds it: the write
    connector and the watchlist's Done check both go to Jira B."""
    h.orchestrator = Orchestrator(
        h.db,
        h.log,
        h.engine,
        h.teams,
        h.agent,
        WriteGateway(h.db, [b], poll=0.05),
        mint,
        public_base_url=PUBLIC_BASE_URL,
    )
    return WatchFacts(h.db, b, B_SITE.identity)


async def a_written_ticket(h: Harness) -> None:
    run_id = await work_leg(h)
    await bob_decides(h, run_id, Verdict.APPROVE)
    await h.orchestrator.on_step(run_id, StepName.WRITE_ACTION, ACT)
    assert [t.key for t in await h.jira.tickets()] == ["MOCK-1"]


LISTED = WatchlistRecord(
    USE_CASE,
    WATCHLIST_SPEC.use_case_version,
    ALICE.user_id,
    "MOCK",
    tuple(
        ListedSoftware(s.id, s.name, s.source, s.our_version, ALICE.user_id, NOW)
        for s in TASK.software
    ),
    On(),
)
CHECKED_AGAIN = ONE_BEHIND.model_copy(
    update={
        "findings": [
            finding(LANGGRAPH, "behind", "1.2.16"),
            finding(REDIS, "up_to_date", "8.2.1"),
            finding(FASTAPI, "cant_check", None, NOT_FOUND),
            finding(POSTGRES, "up_to_date", "17.2.0"),
        ]
    }
)


async def check_again(h: Harness, shown: WatchlistStanding) -> AwaitingApproval:
    """The next check, told what the watchlist shows, as the builder starts it."""
    assert given_versions(LISTED) == GIVEN
    h.agent.output = CHECKED_AGAIN
    run_id = await start_check(h, replace(WATCHLIST_SPEC, task=task(LISTED, shown)), "check-2")
    reply = await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, N8nExecutionId("43"))
    assert reply.outcome == "proposed", reply.detail
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, N8nExecutionId("43"))
    await h.orchestrator.tick()
    state = await h.state(run_id)
    assert isinstance(state, AwaitingApproval)
    return state


async def proposed_on(h: Harness, waiting: AwaitingApproval) -> list[tuple[Json, dict[str, Json]]]:
    detail = await h.orchestrator.get_approval(waiting.approval_id, BOB)
    assert detail is not None
    return [(a.fields["title"], dict(a.target)) for a in detail.proposal.actions]


async def test_on_jira_b_a_ticket_written_on_the_practice_jira_is_not_open_and_holds_nothing(
    h: Harness,
):
    """Live case A11: after a switch to Jira B, LangGraph's MOCK-1 on the practice Jira is not
    Jira B's open ticket. It is not shown, so never linked to Jira B's own MOCK-1, and the next
    check on Jira B proposes LangGraph's upgrade there."""
    await a_written_ticket(h)
    b = JiraB()
    on_b = restart_on_jira_b(h, b)
    shown = await on_b.standings(USE_CASE, GIVEN)
    langgraph = shown.software[LANGGRAPH]
    assert (langgraph.status, langgraph.facts.open_ticket) == ("behind", None)
    assert langgraph.facts.our_version == Given("1.2.14", NOW)
    assert b.asked == [], "Jira B's own MOCK-1 is another ticket"

    waiting = await check_again(h, shown)
    assert await proposed_on(h, waiting) == [
        ("Upgrade LangGraph from 1.2.14 to 1.2.16", {"project": "MOCK", "site": B_SITE.identity})
    ]
    await bob_decides(h, waiting.run_id, Verdict.APPROVE)
    reply = await h.orchestrator.on_step(
        waiting.run_id, StepName.WRITE_ACTION, N8nExecutionId("44")
    )
    assert reply.outcome == "written"
    assert b.made == ["Upgrade LangGraph from 1.2.14 to 1.2.16"]
    on_jira_b = (await on_b.standings(USE_CASE, GIVEN)).software[LANGGRAPH]
    assert on_jira_b.facts.open_ticket == OpenTicket("MOCK-901", "1.2.16")
    on_practice = (await standings(h)).software[LANGGRAPH]
    assert on_practice.facts.open_ticket == OpenTicket("MOCK-1", "1.2.16"), "each its own"


async def test_a_ticket_written_before_sites_were_kept_is_not_open_and_its_done_moves_nothing(
    h: Harness,
):
    """Live case A12: a ticket row from before migration 0016 has no site. Deny by default keeps
    its Done from moving our version, and it does not hold the software's next ticket either."""
    await a_written_ticket(h)
    async with h.db.transaction("orchestration") as uow:
        await uow.conn.execute("UPDATE orchestration.proposed_tickets SET site = NULL")
    await h.jira.mark_done("MOCK-1")
    shown = await standings(h)
    langgraph = shown.software[LANGGRAPH]
    assert (langgraph.status, langgraph.facts.open_ticket) == ("behind", None)
    assert langgraph.facts.our_version == Given("1.2.14", NOW), "not taken as the practice's"

    waiting = await check_again(h, shown)
    assert await proposed_on(h, waiting) == [
        ("Upgrade LangGraph from 1.2.14 to 1.2.16", {"project": "MOCK", "site": "practice"})
    ]


@dataclass
class SiteJira:
    """One Jira site's answer to the Done check. Once `closed`, every ticket asked about is Done."""

    closed: bool = False
    asked: list[str] = field(default_factory=list[str])

    async def done_tickets(self, keys: Collection[str]) -> Mapping[str, datetime]:
        self.asked.extend(keys)
        return {key: NOW + timedelta(days=1) for key in keys} if self.closed else {}


async def tickets_in_three_places(h: Harness) -> None:
    """LangGraph's MOCK-1 written on the practice Jira, Redis's MOCK-1 on Jira B, and FastAPI's
    MOCK-2 from before sites were kept."""
    await a_written_ticket(h)
    async with h.db.transaction("orchestration") as uow:
        row = await (
            await uow.conn.execute("SELECT proposal_id, run_id FROM orchestration.proposed_tickets")
        ).fetchone()
        assert row is not None
        for index, software, version, key, site in (
            (1, REDIS, "8.2.2", "MOCK-1", B_SITE.identity),
            (2, FASTAPI, "0.115.6", "MOCK-2", None),
        ):
            await uow.conn.execute(
                "INSERT INTO orchestration.proposed_tickets (proposal_id, action_index, run_id, "
                "use_case_id, software_id, version, status, ticket_key, site) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'written', %s, %s)",
                (row["proposal_id"], index, row["run_id"], USE_CASE, software, version, key, site),
            )


@pytest.mark.parametrize(
    ("site", "own", "version"),
    [(PRACTICE_SITE, LANGGRAPH, "1.2.16"), (B_SITE, REDIS, "8.2.2")],
    ids=["practice Jira", "Jira B"],
)
async def test_the_open_check_and_the_done_check_read_the_same_tickets_on_each_jira(
    h: Harness, site: Site, own: SoftwareId, version: str
):
    await tickets_in_three_places(h)
    jira = SiteJira()
    facts = WatchFacts(h.db, jira, site.identity)
    shown = (await facts.standings(USE_CASE, GIVEN)).software
    assert {sid: s.facts.open_ticket for sid, s in shown.items() if s.facts.open_ticket} == {
        own: OpenTicket("MOCK-1", version)
    }
    assert jira.asked == ["MOCK-1"], "the Done check asks about the open ticket and no other"

    jira.closed = True
    moved = (await facts.standings(USE_CASE, GIVEN)).software
    assert {sid: s.facts.our_version for sid, s in moved.items() if s.facts.our_version} == {
        **{sid: shown[sid].facts.our_version for sid in shown if shown[sid].facts.our_version},
        own: FromTicketDone(version, NOW + timedelta(days=1), "MOCK-1"),
    }
    assert all(s.facts.open_ticket is None for s in moved.values())


async def test_the_ticket_our_version_came_from_is_named_only_on_its_own_jira(h: Harness):
    await a_written_ticket(h)
    await h.jira.mark_done("MOCK-1")
    here = (await standings(h)).software[LANGGRAPH].facts.our_version
    assert here == FromTicketDone("1.2.16", NOW, "MOCK-1")
    on_b = WatchFacts(h.db, JiraB(), B_SITE.identity)
    there = (await on_b.standings(USE_CASE, GIVEN)).software[LANGGRAPH].facts.our_version
    assert there == FromTicketDone("1.2.16", NOW, None), "Jira B's MOCK-1 is another ticket"


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
    own = {LANGGRAPH: "GitHub returned 503 Service Unavailable three times."}
    assert {sid: s.facts.latest_check for sid, s in found.software.items()} == {
        sid: CouldNotCheck(failed, later, own.get(sid, f"{UNREADABLE}."), KnownNewest(read, NOW))
        for sid, read in READ_FIRST.items()
    }
    assert {s.status for s in found.software.values()} == {"cant_check"}
    assert found.software[REDIS].facts.our_version == FromFirstCheck("8.2.1", NOW)
    assert found.last_check is not None
    assert (found.last_check.run_id, found.last_check.state) == (failed, "failed")


async def test_when_no_software_can_be_checked_each_keeps_the_reason_the_runtime_gave_it(
    h: Harness,
):
    h.agent.mode = "failed"
    h.agent.error = TaskError(
        type="UpstreamRejected",
        message="None of the 4 watched software could be checked. GitHub answered 404 Not Found",
        retryable=False,
    )
    h.agent.findings = [
        finding(LANGGRAPH, "cant_check", None, NOT_FOUND),
        finding(REDIS, "cant_check", None, "GitHub answered 403 Forbidden."),
        finding(FASTAPI, "cant_check", None, "No release has a plain version number."),
        finding(POSTGRES, "cant_check", None, "GitHub answered 403 Forbidden."),
    ]
    run_id = await start_check(h)
    reply = await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, WORK)
    assert (reply.proceed, reply.outcome) == (False, "failed")
    found = await standings(h)
    assert {sid: s.facts.latest_check for sid, s in found.software.items()} == {
        LANGGRAPH: CouldNotCheck(run_id, NOW, NOT_FOUND),
        REDIS: CouldNotCheck(run_id, NOW, "GitHub answered 403 Forbidden."),
        FASTAPI: CouldNotCheck(run_id, NOW, "No release has a plain version number."),
        POSTGRES: CouldNotCheck(run_id, NOW, "GitHub answered 403 Forbidden."),
    }


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
        once = await store.facts(uow, USE_CASE, PRACTICE_SITE.identity)
        await store.record_review(uow, record, reviewed, None)
        twice = await store.facts(uow, USE_CASE, PRACTICE_SITE.identity)
    assert once == twice
    assert once.learned == {REDIS: FromFirstCheck("8.2.1", NOW)}
    assert once.checks[LANGGRAPH] == Checked(run_id, NOW, "1.2.16")


def with_address(output: TaskOutput, **named: Mapping[str, object]) -> TaskOutput:
    """The output with `full_name` and `not_found` set on the findings of the named software."""
    return output.model_copy(
        update={
            "findings": [f.model_copy(update=named.get(f.software_id, {})) for f in output.findings]
        }
    )


async def test_each_check_keeps_the_name_github_answered_and_a_later_check_replaces_it(h: Harness):
    h.agent.output = with_address(
        NOTHING_BEHIND, **{FASTAPI: {"full_name": "tiangolo/fastapi-new"}}
    )
    first = await start_check(h)
    await h.orchestrator.on_step(first, StepName.RUN_AGENTS, WORK)
    found = await standings(h)
    assert found.software[FASTAPI].facts.latest_check == Checked(
        first, NOW, "0.115.0", github_name="tiangolo/fastapi-new"
    )
    assert found.software[POSTGRES].facts.latest_check == Checked(first, NOW, "17.2.0")

    h.advance(timedelta(hours=1))
    h.agent.output = with_address(NOTHING_BEHIND, **{FASTAPI: {"full_name": "fastapi/fastapi"}})
    second = await start_check(h, key="check-2")
    await h.orchestrator.on_step(second, StepName.RUN_AGENTS, N8nExecutionId("42"))
    latest = (await standings(h)).software[FASTAPI].facts.latest_check
    assert latest == Checked(
        second, NOW + timedelta(hours=1), "0.115.0", github_name="fastapi/fastapi"
    )


async def test_a_404_is_kept_as_not_found_with_no_name_and_a_later_read_clears_it(h: Harness):
    h.agent.output = with_address(
        NOTHING_BEHIND.model_copy(
            update={
                "findings": [
                    finding(LANGGRAPH, "up_to_date", "1.2.14"),
                    finding(REDIS, "starting_point", "8.2.1"),
                    finding(FASTAPI, "cant_check", None, NOT_FOUND),
                    finding(POSTGRES, "up_to_date", "17.2.0"),
                ]
            }
        ),
        **{FASTAPI: {"not_found": True}},
    )
    first = await start_check(h)
    await h.orchestrator.on_step(first, StepName.RUN_AGENTS, WORK)
    lost = (await standings(h)).software[FASTAPI].facts.latest_check
    assert lost == CouldNotCheck(first, NOW, NOT_FOUND, None, None, True)

    h.advance(timedelta(hours=1))
    h.agent.output = NOTHING_BEHIND
    second = await start_check(h, key="check-2")
    await h.orchestrator.on_step(second, StepName.RUN_AGENTS, N8nExecutionId("42"))
    again = (await standings(h)).software[FASTAPI].facts.latest_check
    assert again == Checked(second, NOW + timedelta(hours=1), "0.115.0")


async def test_a_check_that_could_not_ask_for_the_name_keeps_the_last_one_it_got(h: Harness):
    h.agent.output = with_address(NOTHING_BEHIND, **{FASTAPI: {"full_name": "fastapi/fastapi"}})
    first = await start_check(h)
    await h.orchestrator.on_step(first, StepName.RUN_AGENTS, WORK)
    h.advance(timedelta(hours=1))
    h.agent.output = NOTHING_BEHIND.model_copy(
        update={
            "findings": [
                finding(LANGGRAPH, "up_to_date", "1.2.14"),
                finding(REDIS, "starting_point", "8.2.1"),
                finding(FASTAPI, "cant_check", None, "GitHub answered 503 Service Unavailable."),
                finding(POSTGRES, "up_to_date", "17.2.0"),
            ]
        }
    )
    second = await start_check(h, key="check-2")
    await h.orchestrator.on_step(second, StepName.RUN_AGENTS, N8nExecutionId("42"))
    latest = (await standings(h)).software[FASTAPI].facts.latest_check
    assert isinstance(latest, CouldNotCheck)
    assert (latest.github_name, latest.not_found) == ("fastapi/fastapi", False)
