"""The Software watchlist on its own n8n workflow (D11): Read the watchlist, Check the watchlist,
Ask for a yes, Create tickets, through our API's node calls, and what the Software page reads
after each."""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from platform_api.orchestration.agents import TaskOutput, WatchlistInputs
from platform_api.orchestration.jira import PRACTICE_SITE
from platform_api.orchestration.n8n_calls import (
    NOT_A_WATCHLIST_RUN,
    AgentCall,
    Answer,
    AskCall,
    NothingToChange,
    ReadCall,
    Refused,
    Waiting,
    WriteAnswer,
)
from platform_api.orchestration.runs import Failed, FailureReason, Succeeded
from platform_api.orchestration.spec import CardsTask, WatchlistTask
from platform_api.orchestration.watch import Given
from platform_api.orchestration.watch_store import WatchFacts, WatchlistStanding
from tests.conftest import PostgresUrls
from tests.support import BOB, LANGGRAPH, NOW, REDIS, SPEC, fixture, watched
from tests.test_n8n_calls import CARD_RUN
from tests.test_n8n_wait import resume_url
from tests.test_n8n_write import Writes, open_writes

pytestmark = pytest.mark.anyio

READ = ReadCall("github_releases", "watchlist", None)
CHECK = AgentCall("watchlist_checker", {})
TICKET_TITLE = "Upgrade LangGraph from 1.2.14 to 1.2.16"


@pytest.fixture
async def wl(postgres: PostgresUrls) -> AsyncIterator[Writes]:
    async with open_writes(postgres) as writes:
        yield writes


async def check(w: Writes, execution: str) -> object:
    """One scheduled execution of the watchlist's workflow, up to its Ask for a yes."""
    w.started(execution)
    await w.call(execution, READ, "Read the watchlist")
    await w.call(execution, CHECK, "Check the watchlist")
    return await w.call(execution, AskCall(resume_url(execution)), "Ask for a yes")


async def page(w: Writes) -> WatchlistStanding:
    """What the Software page reads about the watched software."""
    facts = WatchFacts(w.h.db, w.h.jira, PRACTICE_SITE.identity)
    return await facts.standings(SPEC.use_case_id, {LANGGRAPH: Given("1.2.14", NOW)})


async def test_a_check_reads_its_own_list_and_raises_one_ticket_for_the_software_behind(
    wl: Writes,
):
    wl.started("101")
    read = await wl.call("101", READ, "Read the watchlist")
    assert read == Answer(
        (
            {
                "kind": "software",
                "id": LANGGRAPH,
                "name": "LangGraph",
                "repo": "langchain-ai/langgraph",
            },
        )
    )
    checked = await wl.call("101", CHECK, "Check the watchlist")
    assert isinstance(checked, Answer)
    [request] = wl.h.agent.requests
    assert isinstance(request.inputs, WatchlistInputs)
    assert [(s.id, s.our_version) for s in request.inputs.software] == [(LANGGRAPH, "1.2.14")]

    waiting = await wl.call("101", AskCall(resume_url("101")), "Ask for a yes")
    assert isinstance(waiting, Waiting)
    [langgraph] = (await page(wl)).software.values()
    assert langgraph.status == "awaiting_approval"
    assert langgraph.facts.pending is not None
    assert langgraph.facts.pending.approval_id == waiting.request_id
    assert langgraph.facts.latest_check is not None
    assert getattr(langgraph.facts.latest_check, "newest", None) == "1.2.16"

    await wl.decide(BOB)
    await wl.tick()
    made = await wl.write("101", "Create tickets")
    assert isinstance(made, WriteAnswer) and (made.made, made.of) == (1, 1)
    assert isinstance((await wl.run()).state, Succeeded)
    assert [t.title for t in await wl.h.jira.tickets()] == [TICKET_TITLE]
    [langgraph] = (await page(wl)).software.values()
    assert langgraph.status == "ticket_open"
    assert langgraph.facts.open_ticket is not None
    assert langgraph.facts.open_ticket.key == "MOCK-1"


async def test_an_upgrade_ticket_made_once_is_never_raised_again_for_that_version(wl: Writes):
    """A later check that still believes LangGraph has no ticket, as a list read before the first
    write would, proposes it again. The subject, LangGraph at 1.2.16, was made, so nobody is
    asked and nothing is written twice."""
    await check(wl, "101")
    await wl.decide(BOB)
    await wl.tick()
    await wl.write("101", "Create tickets")

    assert await check(wl, "102") == NothingToChange()
    assert await wl.tickets() == ["MOCK-1"]
    assert len(await wl.rows("SELECT 1 FROM orchestration.proposed_tickets")) == 1


async def test_a_check_github_would_not_answer_keeps_why_and_stops_safe_to_retry(wl: Writes):
    wl.h.agent.mode = "failed"
    wl.started("101")
    await wl.call("101", READ, "Read the watchlist")
    stopped = await wl.call("101", CHECK, "Check the watchlist")
    assert isinstance(stopped, Refused)
    run = await wl.run()
    assert isinstance(run.state, Failed)
    assert (run.state.failure.reason, run.state.failure.retryable) == (
        FailureReason.AGENT_ERROR,
        True,
    )
    [langgraph] = (await page(wl)).software.values()
    assert langgraph.status == "cant_check"
    assert getattr(langgraph.facts.latest_check, "problem", None) == (
        "GitHub returned 503 Service Unavailable three times."
    )


async def test_only_the_software_watchlist_reads_and_checks_the_watchlist(wl: Writes):
    wl.workflows.spec = replace(SPEC, task=CardsTask((CARD_RUN,)))
    wl.started("101")
    assert await wl.call("101", READ, "Read the watchlist") == NOT_A_WATCHLIST_RUN
    assert await wl.call("101", CHECK, "Check the watchlist") == NOT_A_WATCHLIST_RUN
    assert wl.h.agent.requests == []


async def test_the_approver_is_told_which_software_the_check_could_not_read(wl: Writes):
    assert isinstance(SPEC.task, WatchlistTask)
    redis = watched(REDIS, "Redis", "redis/redis", "8.2.1")
    wl.workflows.spec = replace(
        SPEC, task=replace(SPEC.task, software=(*SPEC.task.software, redis))
    )
    output = fixture("agent/task-finished.json")["output"]
    output["findings"].append(
        {
            "software_id": REDIS,
            "state": "cant_check",
            "newest": None,
            "new_versions": [],
            "detail": "GitHub returned 404 Not Found.",
            "full_name": None,
            "not_found": True,
        }
    )
    wl.h.agent.output = TaskOutput.model_validate(output)

    waiting = await check(wl, "101")

    assert isinstance(waiting, Waiting)
    shown = await wl.orchestrator.get_approval(waiting.request_id, BOB)
    assert shown is not None
    assert shown.not_checked == ("Redis",)
    assert [a.fields["title"] for a in shown.proposal.actions] == [TICKET_TITLE]


async def test_a_retry_once_github_answers_again_checks_again_and_asks(wl: Writes):
    wl.h.agent.mode = "failed"
    wl.started("101")
    await wl.call("101", READ, "Read the watchlist")
    assert isinstance(await wl.call("101", CHECK, "Check the watchlist"), Refused)

    wl.h.agent.mode = "finished"
    wl.retried("201", of="101")
    assert isinstance(await wl.call("201", CHECK, "Check the watchlist"), Answer)
    assert isinstance(await wl.call("201", AskCall(resume_url("201")), "Ask for a yes"), Waiting)
    assert len(wl.h.agent.requests) == 2, "the check ran again, not its stopped answer"
