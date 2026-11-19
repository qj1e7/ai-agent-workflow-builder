import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder import Builder, Home, TeamRequests, Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.builder.models import WatchedSoftwareView
from platform_api.orchestration import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalStep,
    ScheduleBook,
    TeamsPost,
)
from platform_api.orchestration.connections import Reading
from platform_api.orchestration.people import Person
from platform_api.orchestration.people_store import People, PersonRow
from platform_api.orchestration.person_runs import runs_of
from platform_api.orchestration.runs import (
    AwaitingApproval,
    Failed,
    Leg,
    Pending,
    Rejected,
    StepName,
)
from platform_api.orchestration.service import RunDetail
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.orchestration.store import RunRecord
from platform_api.shared import (
    TEAM_TIME_ZONE,
    ApprovalId,
    ExternalIdentity,
    N8nExecutionId,
    Principal,
    ProposalId,
    Role,
    RunId,
    SeedPerson,
    UserId,
)
from tests.conftest import PostgresUrls
from tests.declared import declared_status
from tests.fake_n8n import FakeN8n
from tests.support import ALICE, LOCAL_ENV, NOW, SPEC
from tests.test_builder_http import NothingLearned
from tests.test_builder_lifecycle import ModelConnected
from tests.test_card_runs import output, ticket
from tests.test_connections import DOWN, Rig
from tests.test_n8n_builder import WRITES
from tests.test_n8n_lifecycle import Workflows
from tests.test_orchestrator import Harness, open_harness
from tests.test_setup_approvals import ASK, Channel

pytestmark = pytest.mark.anyio

ALICE_NOW = Principal(UserId("alice"), frozenset({Role.OPERATOR, Role.APPROVER}), "Alice")
DAVE = SeedPerson(
    UserId("dave"), "dave@example.test", "Dave", frozenset({Role.OPERATOR, Role.APPROVER})
)
ERIN = SeedPerson(UserId("erin"), "erin@example.test", "Erin", frozenset({Role.APPROVER}))
VALUES = {"GitHub repository": "langchain-ai/langgraph", "Jira project": "MOCK"}
TWO_STEPS = ApprovalPolicy(
    (ApprovalStep("First Approver", AnyApprover()), ApprovalStep("Second Approver", AnyApprover()))
)
EMPTY = {
    "approvals": [],
    "approvals_total": 0,
    "confirmations": [],
    "stopped": [],
    "stopped_total": 0,
    "declined": [],
    "declined_total": 0,
    "questions_for_me": [],
    "questions_for_me_total": 0,
    "needs_next": None,
    "setup_approvals": [],
    "waiting_on_others": [],
    "waiting_on_others_total": 0,
    "waiting_on_others_next": None,
    "drafts": [],
    "following_up": [],
    "following_up_total": 0,
    "following_up_next": None,
    "replied": [],
    "coming_up": None,
    "workflows": 0,
    "addresses": [],
    "connections": [],
    "changed_in_n8n": [],
}


def watched(
    name: str, ref: str, moved_to: str | None = None, not_found: bool = False
) -> WatchedSoftwareView:
    return WatchedSoftwareView.model_validate(
        {
            "id": f"sw_{name}",
            "name": name,
            "source": {"kind": "github", "ref": ref, "url": f"https://github.com/{ref}/releases"},
            "our_version": None,
            "our_version_source": None,
            "compared_from": None,
            "newest_version": None,
            "newest_read_at": None,
            "checked_at": None,
            "status": "cant_check",
            "problem": None,
            "open_ticket": None,
            "approval_id": None,
            "moved_to": moved_to,
            "not_found": not_found,
            "address_changes": [],
            "added_by": "alice",
            "added_at": "2026-11-01T00:00:00Z",
        }
    )


class NoTeams:
    async def post(self, notice: object) -> TeamsPost:
        return "no_channel"


@dataclass
class Lab:
    h: Harness
    app: FastAPI
    client: httpx.AsyncClient
    people: People
    rig: Rig
    setups: SetUpApprovals

    async def call(self, user: str, method: str, path: str, body: Any = None) -> httpx.Response:
        headers = {"X-Dev-User": user}
        if path.endswith("/runs") and method == "POST":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        return await self.client.request(method, path, headers=headers, json=body)

    async def home(self, user: str) -> dict[str, Any]:
        response = await self.call(user, "GET", "/api/v1/home")
        assert response.status_code == 200, response.text
        declared_status(self.app, "GET", "/api/v1/home", response)
        return response.json()

    async def run_ids(self, user: str, part: str) -> list[str]:
        return [item["run_id"] for item in (await self.home(user))[part]]

    async def page(self, user: str, path: str, after: str | None) -> dict[str, Any]:
        response = await self.client.get(
            path, params={} if after is None else {"after": after}, headers={"X-Dev-User": user}
        )
        assert response.status_code == 200, response.text
        declared_status(self.app, "GET", path, response)
        return response.json()

    async def every_page(self, user: str, path: str, first: str | None) -> list[dict[str, Any]]:
        """Home's cursor for a list, followed to its end: the pages after Home's first."""
        pages: list[dict[str, Any]] = []
        after = first
        while after is not None:
            pages.append(await self.page(user, path, after))
            after = pages[-1]["next"]
        return pages


@pytest.fixture
async def lab(postgres: PostgresUrls) -> AsyncIterator[Lab]:
    async with open_harness(postgres) as h:
        people = People(h.db)
        assert await people.seed_dev((*DEV_PEOPLE, DAVE, ERIN))
        watchlist = Watchlist(h.db, NothingLearned(), ScheduleBook(h.db))
        builder = Builder(
            h.db, h.orchestrator, watchlist, "http://localhost:8000", ModelConnected()
        )
        rig = Rig(h.db)
        connections = rig.connections
        app = create_app(LOCAL_ENV)
        app.state.builder = builder
        app.state.watchlist = watchlist
        app.state.orchestrator = h.orchestrator
        app.state.people = people
        requests = TeamRequests(h.db, NoTeams(), h.orchestrator, h.log, "http://localhost:8000")
        app.state.team_requests = requests
        setups = SetUpApprovals(h.db, Channel(), people, "http://localhost:8000", TEAM_TIME_ZONE)
        app.state.home = Home(
            builder, h.orchestrator, people, requests, connections, watchlist, setups
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Lab(h, app, client, people, rig, setups)


async def workflow(lab: Lab, owner: str = "alice", name: str = "Watch LangGraph") -> str:
    body = {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
    }
    response = await lab.call(owner, "POST", "/api/v1/agent-use-cases", body)
    assert response.status_code == 201, response.text
    return response.json()["use_case_id"]


async def start(lab: Lab, use_case_id: str, by: str = "alice", test: bool = False) -> RunId:
    path = f"/api/v1/use-cases/{use_case_id}/runs"
    response = await lab.call(by, "POST", path, {"test": True} if test else None)
    assert response.status_code == 201, response.text
    return RunId(response.json()["run_id"])


def execution_of(h: Harness, run_id: RunId) -> N8nExecutionId:
    last = max(
        i for i, (_, leg, rid) in enumerate(h.engine.legs) if rid == run_id and leg is Leg.WORK
    )
    return h.engine.executions[last]


async def work(lab: Lab, run_id: RunId, *, fail: bool = False, cards: bool = True) -> None:
    h = lab.h
    h.agent.mode = "failed" if fail else "finished"
    h.agent.output = output(ticket(VERSION_CHECKER_ID)) if cards else None
    await h.orchestrator.tick()
    execution = execution_of(h, run_id)
    await h.orchestrator.on_step(run_id, StepName.RUN_AGENTS, execution)
    if fail:
        assert isinstance(await h.state(run_id), Failed)
        return
    await h.orchestrator.on_step(run_id, StepName.ASK_APPROVAL, execution)
    await h.orchestrator.tick()
    assert isinstance(await h.state(run_id), AwaitingApproval)


async def waiting_run(lab: Lab, use_case_id: str, by: str = "alice") -> RunId:
    run_id = await start(lab, use_case_id, by)
    await work(lab, run_id)
    return run_id


async def stopped_run(lab: Lab, use_case_id: str, by: str = "alice") -> RunId:
    run_id = await start(lab, use_case_id, by)
    await work(lab, run_id, fail=True)
    return run_id


async def decide_first_step(lab: Lab, user: str, run_id: RunId) -> None:
    run = (await lab.call(user, "GET", f"/api/v1/runs/{run_id}")).json()
    approval_id = run["approval"]["approval_id"]
    seen = (await lab.call(user, "GET", f"/api/v1/approvals/{approval_id}")).json()
    decided = await lab.call(
        user,
        "POST",
        f"/api/v1/approvals/{seen['approval_id']}/decisions",
        {"step": 0, "verdict": "approve", "digest": seen["digest"]},
    )
    assert decided.status_code == 201, decided.text


async def test_a_new_person_on_a_new_team_has_nothing_on_home(lab: Lab):
    assert await lab.home("erin") == EMPTY


async def test_an_approver_sees_a_run_waiting_for_their_yes_with_what_it_would_change(lab: Lab):
    use_case_id = await workflow(lab)
    run_id = await waiting_run(lab, use_case_id, by="carol")

    home = await lab.home("bob")

    assert home["approvals_total"] == 1
    (item,) = home["approvals"]
    run = (await lab.call("bob", "GET", f"/api/v1/runs/{run_id}")).json()
    assert item == {
        "run_id": run_id,
        "approval_id": run["approval"]["approval_id"],
        "use_case_id": use_case_id,
        "use_case_name": "Watch LangGraph",
        "started_by": "carol",
        "started_by_name": "Carol",
        "trigger": "person",
        "started_at": run["started_at"],
        "step": 0,
        "steps": 1,
        "step_label": run["approval"]["steps"][0]["label"],
        "changes": 1,
        "first_changes": [
            {"connector": "jira", "operation": "create_ticket", "title": "New release"}
        ],
    }
    assert home["waiting_on_others"] == []


async def test_a_run_whose_starter_left_the_list_names_no_one(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab), by="carol")
    assert isinstance(await lab.people.remove(ALICE_NOW, "carol"), Person)

    (item,) = (await lab.home("bob"))["approvals"]

    assert (item["run_id"], item["started_by"], item["started_by_name"]) == (run_id, "carol", None)


async def test_no_party_to_a_run_sees_its_approval_item_and_each_waits_on_others(lab: Lab):
    use_case_id = await workflow(lab, owner="alice")
    run_id = await stopped_run(lab, use_case_id, by="carol")
    retried = await lab.call("dave", "POST", f"/api/v1/runs/{run_id}/retry")
    assert retried.status_code == 202, retried.text
    lab.h.advance(timedelta(seconds=5))
    await work(lab, run_id)

    for party, because in (("carol", "started"), ("dave", "retried"), ("alice", "owns")):
        home = await lab.home(party)
        assert home["approvals"] == [], party
        assert [(w["run_id"], w["because"]) for w in home["waiting_on_others"]] == [
            (run_id, because)
        ], party
    assert await lab.run_ids("bob", "approvals") == [run_id]
    assert await lab.run_ids("erin", "approvals") == [run_id]


async def test_an_operator_who_is_not_an_approver_never_gets_an_approval_item(lab: Lab):
    theirs = await waiting_run(lab, await workflow(lab, name="Alice's"), by="alice")
    mine = await waiting_run(lab, await workflow(lab, owner="carol", name="Carol's"), by="carol")

    home = await lab.home("carol")

    assert (home["approvals"], home["approvals_total"]) == ([], 0)
    assert [w["run_id"] for w in home["waiting_on_others"]] == [mine]
    assert theirs in await lab.run_ids("bob", "approvals")


async def test_after_step_one_of_two_its_approver_waits_and_another_approver_is_asked(lab: Lab):
    started = await lab.h.orchestrator.start_run(
        replace(SPEC, approval_policy=TWO_STEPS), ALICE, "two-steps"
    )
    run_id = started.run_id
    await work(lab, run_id, cards=False)
    assert [(a["step"], a["steps"]) for a in (await lab.home("bob"))["approvals"]] == [(0, 2)]

    await decide_first_step(lab, "bob", run_id)

    bob = await lab.home("bob")
    assert bob["approvals"] == []
    assert [(w["because"], w["step"]) for w in bob["waiting_on_others"]] == [("decided_earlier", 1)]
    (erin,) = (await lab.home("erin"))["approvals"]
    assert (erin["run_id"], erin["step"], erin["step_label"]) == (run_id, 1, "Second Approver")


async def test_an_approver_whose_role_is_taken_away_loses_the_item_at_once(lab: Lab):
    run_id = await waiting_run(lab, await workflow(lab))
    assert await lab.run_ids("dave", "approvals") == [run_id]

    assert isinstance(await lab.people.remove_approver(ALICE_NOW, "dave"), Person)

    assert (await lab.home("dave"))["approvals"] == []


async def test_the_newest_waiting_runs_come_first_and_home_counts_them_all(lab: Lab):
    started: list[RunId] = []
    for n in range(12):
        run = await lab.h.orchestrator.start_run(SPEC, ALICE, f"many-{n}")
        started.append(run.run_id)
        lab.h.advance(timedelta(seconds=1))
    for run_id in started:
        await work(lab, run_id, cards=False)

    home = await lab.home("bob")

    assert home["approvals_total"] == 12
    assert [a["run_id"] for a in home["approvals"]] == started[::-1][:10]


async def waiting_runs(
    lab: Lab, count: int, apart: timedelta = timedelta(seconds=1)
) -> list[RunId]:
    """`count` runs alice started, each waiting for a yes, `apart` apart, the oldest first."""
    started: list[RunId] = []
    for n in range(count):
        run = await lab.h.orchestrator.start_run(SPEC, ALICE, f"many-{n}-{uuid.uuid4()}")
        started.append(run.run_id)
        lab.h.advance(apart)
    for run_id in started:
        await work(lab, run_id, cards=False)
    return started


async def test_every_request_waiting_for_a_yes_is_reached_through_the_pages(lab: Lab):
    started = await waiting_runs(lab, 27)

    home = await lab.home("bob")
    pages = await lab.every_page("bob", "/api/v1/home/needs", home["needs_next"])

    reached = [a["run_id"] for a in home["approvals"]]
    reached += [a["run_id"] for page in pages for a in page["approvals"]]
    assert reached == started[::-1], "every request once, the newest first"
    assert [len(page["approvals"]) for page in pages] == [10, 7]
    assert {home["approvals_total"], *(page["approvals_total"] for page in pages)} == {27}
    assert pages[-1]["next"] is None


async def test_a_page_goes_on_where_the_last_one_ended_when_a_new_request_arrives(lab: Lab):
    started = await waiting_runs(lab, 12)
    first = await lab.home("bob")

    (newest,) = await waiting_runs(lab, 1)
    after = await lab.page("bob", "/api/v1/home/needs", first["needs_next"])

    assert [a["run_id"] for a in after["approvals"]] == started[::-1][10:]
    assert after["approvals_total"] == 13, "the count is the list as it is now"
    assert [a["run_id"] for a in (await lab.home("bob"))["approvals"]][0] == newest


async def test_a_request_decided_between_pages_skips_nothing_and_repeats_nothing(lab: Lab):
    started = await waiting_runs(lab, 13)
    first = await lab.home("bob")
    on_first_page, not_read_yet = started[-1], started[0]

    await decide_first_step(lab, "bob", on_first_page)
    await decide_first_step(lab, "bob", not_read_yet)
    after = await lab.page("bob", "/api/v1/home/needs", first["needs_next"])

    read = [a["run_id"] for a in first["approvals"]] + [a["run_id"] for a in after["approvals"]]
    assert len(read) == len(set(read)), "no request twice"
    assert set(started[1:-1]) <= set(read), "every request still waiting was reached"
    assert not_read_yet not in read
    assert after["approvals_total"] == 11, "the count is what still waits"
    again = await lab.home("bob")
    pages = await lab.every_page("bob", "/api/v1/home/needs", again["needs_next"])
    fresh = [a["run_id"] for a in again["approvals"]]
    fresh += [a["run_id"] for page in pages for a in page["approvals"]]
    assert fresh == started[1:-1][::-1] and again["approvals_total"] == len(fresh)


async def test_requests_started_at_the_same_moment_are_each_reached_once_by_their_id(lab: Lab):
    started = await waiting_runs(lab, 23, apart=timedelta(0))

    home = await lab.home("bob")
    pages = await lab.every_page("bob", "/api/v1/home/needs", home["needs_next"])

    reached = [a["run_id"] for a in home["approvals"]]
    reached += [a["run_id"] for page in pages for a in page["approvals"]]
    assert len({a["started_at"] for a in home["approvals"]}) == 1, "one moment for all"
    assert reached == sorted(started, reverse=True), "each once, the larger id first"
    assert [len(home["approvals"]), *(len(p["approvals"]) for p in pages)] == [10, 10, 3]


async def test_every_stopped_run_is_reached_through_the_pages(lab: Lab):
    stopped = [await stopped_run(lab, await workflow(lab, name=f"Check {n}")) for n in range(12)]

    home = await lab.home("alice")
    pages = await lab.every_page("alice", "/api/v1/home/needs", home["needs_next"])

    reached = [s["run_id"] for s in home["stopped"]]
    reached += [s["run_id"] for page in pages for s in page["stopped"]]
    assert sorted(reached) == sorted(stopped) and len(reached) == 12
    assert [home["stopped_total"], *(page["stopped_total"] for page in pages)] == [12, 12]
    assert [page["approvals"] for page in pages] == [[]], "a part with no more sends no rows"


async def test_every_run_waiting_on_others_is_reached_through_the_pages(lab: Lab):
    started = await waiting_runs(lab, 52)

    home = await lab.home("alice")
    pages = await lab.every_page(
        "alice", "/api/v1/home/waiting-on-others", home["waiting_on_others_next"]
    )

    reached = [w["run_id"] for w in home["waiting_on_others"]]
    reached += [w["run_id"] for page in pages for w in page["waiting_on_others"]]
    assert reached == started[::-1]
    assert [len(home["waiting_on_others"]), *(len(p["waiting_on_others"]) for p in pages)] == [
        50,
        2,
    ]
    assert {page["waiting_on_others_total"] for page in pages} == {52}
    bob = await lab.home("bob")
    assert (bob["approvals_total"], len(bob["approvals"])) == (52, 10)


async def test_a_page_read_with_no_cursor_is_homes_first_page(lab: Lab):
    await waiting_runs(lab, 3)
    home = await lab.home("bob")

    first = await lab.page("bob", "/api/v1/home/needs", None)

    assert first["approvals"] == home["approvals"]
    assert first["next"] == home["needs_next"] is None


@pytest.mark.parametrize(
    "path", ["/api/v1/home/needs", "/api/v1/home/waiting-on-others", "/api/v1/home/following-up"]
)
async def test_a_cursor_this_list_did_not_give_out_is_refused(lab: Lab, path: str):
    await waiting_runs(lab, 12)
    other = (await lab.home("bob"))["needs_next"]
    for after in ("not-a-cursor", "e30", other if path != "/api/v1/home/needs" else "W10"):
        response = await lab.client.get(
            path, params={"after": after}, headers={"X-Dev-User": "bob"}
        )
        assert response.status_code == 422, (after, response.text)
        declared_status(lab.app, "GET", path, response)


async def test_a_stopped_run_shows_to_the_operators_who_started_or_own_it_with_the_reason(
    lab: Lab,
):
    use_case_id = await workflow(lab, owner="alice")
    run_id = await stopped_run(lab, use_case_id, by="carol")

    for operator in ("alice", "carol"):
        home = await lab.home(operator)
        assert home["stopped_total"] == 1, operator
        (item,) = home["stopped"]
        assert item["run_id"] == run_id
        assert (item["reason"], item["retryable"]) == ("AgentError", True)
        assert item["advice"]["explanation"] == "An agent could not finish its work."
        assert item["advice"]["suggested_action"] == "retry"
    for not_a_party in ("dave", "bob"):
        assert (await lab.home(not_a_party))["stopped"] == [], not_a_party


async def test_a_stopped_run_leaves_home_when_it_is_retried_or_a_newer_run_starts(lab: Lab):
    use_case_id = await workflow(lab)
    first = await stopped_run(lab, use_case_id)
    assert await lab.run_ids("alice", "stopped") == [first]

    await start(lab, use_case_id)
    assert await lab.run_ids("alice", "stopped") == []

    other = await stopped_run(lab, await workflow(lab, name="Another"))
    assert (await lab.call("alice", "POST", f"/api/v1/runs/{other}/retry")).status_code == 202
    assert isinstance(await lab.h.state(other), Pending)
    assert await lab.run_ids("alice", "stopped") == []


async def test_a_deleted_workflow_s_stopped_run_is_not_shown(lab: Lab):
    use_case_id = await workflow(lab)
    await stopped_run(lab, use_case_id)
    assert (
        await lab.call("alice", "DELETE", f"/api/v1/use-cases/{use_case_id}")
    ).status_code == 200

    assert (await lab.home("alice"))["stopped"] == []


async def declined_run(
    lab: Lab, use_case_id: str, by: str, test: bool, reason: str | None = None
) -> RunId:
    run_id = await start(lab, use_case_id, by, test=test)
    await work(lab, run_id)
    run = (await lab.call("bob", "GET", f"/api/v1/runs/{run_id}")).json()
    seen = (
        await lab.call("bob", "GET", f"/api/v1/approvals/{run['approval']['approval_id']}")
    ).json()
    body = {"step": 0, "verdict": "decline", "digest": seen["digest"]}
    if reason is not None:
        body["reason"] = reason
    path = f"/api/v1/approvals/{seen['approval_id']}/decisions"
    assert (await lab.call("bob", "POST", path, body)).status_code == 201
    return run_id


async def test_a_declined_test_run_is_in_its_starters_needs_you_with_who_declined_and_why(
    lab: Lab,
):
    use_case_id = await workflow(lab, owner="carol")
    run_id = await declined_run(lab, use_case_id, "alice", test=True, reason="Wrong version")

    home = await lab.home("alice")
    assert home["declined_total"] == 1
    (item,) = home["declined"]
    assert {k: item[k] for k in ("run_id", "use_case_id", "use_case_name")} == {
        "run_id": run_id,
        "use_case_id": use_case_id,
        "use_case_name": "Watch LangGraph",
    }
    assert (item["declined_by"], item["declined_by_name"], item["decline_reason"]) == (
        "bob",
        "Bob",
        "Wrong version",
    )
    for not_the_starter in ("carol", "bob", "dave"):
        assert (await lab.home(not_the_starter))["declined"] == [], not_the_starter


async def test_only_a_test_run_declined_counts_and_it_leaves_when_the_workflow_runs_again(
    lab: Lab,
):
    run_now = await workflow(lab, name="Run now")
    await declined_run(lab, run_now, "alice", test=False)
    assert await lab.run_ids("alice", "declined") == []

    tried = await workflow(lab, name="Tried")
    first = await declined_run(lab, tried, "alice", test=True)
    assert await lab.run_ids("alice", "declined") == [first]
    assert (await lab.home("alice"))["declined"][0]["decline_reason"] is None

    await start(lab, tried, test=True)
    assert await lab.run_ids("alice", "declined") == []


async def test_a_declined_test_run_leaves_needs_you_when_its_starter_is_no_longer_an_operator(
    lab: Lab,
):
    use_case_id = await workflow(lab, owner="dave")
    run_id = await declined_run(lab, use_case_id, "dave", test=True, reason="Wrong version")
    assert await lab.run_ids("dave", "declined") == [run_id]

    assert isinstance(await lab.people.set_operator(ALICE_NOW, "dave", False), Person)

    home = await lab.home("dave")
    assert (home["declined"], home["declined_total"]) == ([], 0)


async def test_a_confirmation_shows_to_approvers_who_may_decide_it_and_not_to_the_asker(lab: Lab):
    assert isinstance(await lab.people.ask_approver(ALICE_NOW, "carol"), PersonRow)

    (item,) = (await lab.home("bob"))["confirmations"]
    assert {k: item[k] for k in ("kind", "about_name", "summary", "asked_by_name")} == {
        "kind": "approver",
        "about_name": "Carol",
        "summary": "Make Carol an Approver",
        "asked_by_name": "Alice",
    }
    for cannot in ("alice", "carol"):
        assert (await lab.home(cannot))["confirmations"] == [], cannot


async def test_a_set_up_approval_is_in_needs_you_for_each_approver_who_may_decide_it(lab: Lab):
    request = await lab.setups.send(ASK)

    bob = await lab.home("bob")
    assert bob["setup_approvals"] == [
        {
            "approval_id": request.id,
            "drafted_id": "dw_1",
            "name": "Release check",
            "sent_by_name": "Alice",
            "sent_at": bob["setup_approvals"][0]["sent_at"],
            "link": f"/setup-approvals/{request.id}",
        }
    ]
    assert (await lab.home("alice"))["setup_approvals"] == [], "Alice sent it"
    assert (await lab.home("carol"))["setup_approvals"] == [], "Carol is no Approver"


async def test_confirmations_come_the_newest_first(lab: Lab):
    assert isinstance(await lab.people.ask_approver(ALICE_NOW, "carol"), PersonRow)
    lab.h.advance(timedelta(minutes=1))
    added = await lab.people.add(ALICE_NOW, "frank@example.test", "Frank", False, True)
    assert isinstance(added, PersonRow)

    confirmations = (await lab.home("bob"))["confirmations"]

    assert [c["about_name"] for c in confirmations] == ["Frank", "Carol"]


async def test_drafts_show_to_their_author_and_only_to_an_operator(lab: Lab):
    named = {"step": 2, "content": {"intent": "Nudge", "name": "  Nudge stale tickets "}}
    first = await lab.call("alice", "PUT", "/api/v1/drafts/d-1", named)
    lab.h.advance(timedelta(minutes=1))
    unnamed = {"step": 1, "content": {"name": ["not", "a", "name"]}}
    second = await lab.call("alice", "PUT", "/api/v1/drafts/d-2", unnamed)
    assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)

    drafts = (await lab.home("alice"))["drafts"]

    assert drafts == [
        {"draft_id": "d-2", "name": None, "step": 1, "saved_at": second.json()["saved_at"]},
        {
            "draft_id": "d-1",
            "name": "Nudge stale tickets",
            "step": 2,
            "saved_at": first.json()["saved_at"],
        },
    ]
    assert (await lab.home("carol"))["drafts"] == []
    assert (await lab.home("bob"))["drafts"] == []


async def test_a_draft_saved_without_a_step_lists_with_no_step(lab: Lab):
    saved = await lab.call("alice", "PUT", "/api/v1/drafts/d-card", {"content": {"name": "Card"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["step"] is None

    listed = await lab.call("alice", "GET", "/api/v1/drafts")

    assert [(d["draft_id"], d["step"]) for d in listed.json()["drafts"]] == [("d-card", None)]
    (item,) = (await lab.home("alice"))["drafts"]
    assert (item["name"], item["step"]) == ("Card", None)


async def test_a_long_draft_name_is_cut_to_what_a_row_can_show(lab: Lab):
    long = {"step": 1, "content": {"name": "Nudge " * 40}}
    assert (await lab.call("alice", "PUT", "/api/v1/drafts/d-1", long)).status_code == 200

    (draft,) = (await lab.home("alice"))["drafts"]

    assert len(draft["name"]) == 80
    assert draft["name"].endswith("…")


def on_n8n(lab: Lab) -> None:
    """Each new workflow is laid out as its own n8n workflow, whose Schedule Trigger runs it."""
    builder = Builder(
        lab.h.db,
        lab.h.orchestrator,
        lab.app.state.watchlist,
        "http://localhost:8000",
        ModelConnected(),
        n8n=Workflows(FakeN8n(), lab.h.db),
        writes=WRITES,
    )
    lab.app.state.builder = builder
    lab.app.state.home = Home(
        builder,
        lab.h.orchestrator,
        lab.people,
        lab.app.state.team_requests,
        lab.rig.connections,
        lab.app.state.watchlist,
    )


async def scheduled(lab: Lab, name: str, day: str, at: str) -> str:
    body = {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
        "schedule": {"day": day, "at": at},
        "on": True,
    }
    response = await lab.call("alice", "POST", "/api/v1/agent-use-cases", body)
    assert response.status_code == 201, response.text
    return response.json()["use_case_id"]


async def test_coming_up_names_the_next_scheduled_workflow_and_how_many_more(lab: Lab):
    on_n8n(lab)
    await scheduled(lab, "Weekly", "monday", "09:00")
    daily = await scheduled(lab, "Daily", "every_day", "08:00")
    await workflow(lab)

    home = await lab.home("bob")

    view = (await lab.call("bob", "GET", f"/api/v1/use-cases/{daily}")).json()
    assert home["workflows"] == 3
    assert home["coming_up"] == {
        "use_case_id": daily,
        "name": "Daily",
        "template": "agent_cards",
        "next_run_at": view["next_run_at"],
        "time_zone": "Asia/Singapore",
        "more": 1,
    }


async def test_someone_signed_in_but_not_on_the_list_is_refused(lab: Lab):
    async def stranger(request: object) -> ExternalIdentity:
        return ExternalIdentity(subject="oid-zed", user_name="zed@example.test", name="Zed")

    lab.app.state.authenticator = stranger

    response = await lab.client.get("/api/v1/home")

    assert response.status_code == 403
    declared_status(lab.app, "GET", "/api/v1/home", response)


async def ask(lab: Lab, user: str, body: dict[str, Any], key: str) -> dict[str, Any]:
    response = await lab.client.post(
        "/api/v1/team-requests", json=body, headers={"X-Dev-User": user, "Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_following_up_shows_a_persons_own_requests_with_the_latest_reply(lab: Lab):
    use_case_id = await workflow(lab)
    run_id = await stopped_run(lab, use_case_id)
    report = await ask(
        lab, "alice", {"kind": "support", "about": {"run_id": run_id}, "note": "It stopped."}, "a"
    )
    ask_the_team = await ask(
        lab,
        "alice",
        {"kind": "ask_the_team", "about": {"capability": "email.send"}, "note": "By email."},
        "b",
    )
    await ask(
        lab,
        "bob",
        {"kind": "ask_the_team", "about": {"capability": "chat.post"}, "note": "Bob's."},
        "c",
    )
    await lab.client.post(
        f"/api/v1/team-requests/{report['request_id']}/replies",
        json={"text": "Fixed in the next release."},
        headers={"X-Dev-User": "bob"},
    )

    mine = await lab.home("alice")

    assert mine["following_up_total"] == 2
    assert [(i["request_id"], i["kind"], i["status"]) for i in mine["following_up"]] == [
        (ask_the_team["request_id"], "ask_the_team", "open"),
        (report["request_id"], "support", "answered"),
    ]
    assert mine["following_up"][0]["latest_reply"] is None
    reply = mine["following_up"][1]["latest_reply"]
    assert (reply["replied_by_name"], reply["text"]) == ("Bob", "Fixed in the next release.")
    assert mine["following_up"][1]["about"] == {"run_id": run_id}
    assert [i["note"] for i in (await lab.home("bob"))["following_up"]] == ["Bob's."]
    assert (await lab.home("erin"))["following_up"] == []


async def test_every_request_to_the_team_is_reached_through_the_pages(lab: Lab):
    for n in range(103):
        await ask(
            lab,
            "alice",
            {"kind": "ask_the_team", "about": {"capability": "x"}, "note": f"n{n}"},
            f"k{n}",
        )
        lab.h.advance(timedelta(seconds=1))

    home = await lab.home("alice")
    pages = await lab.every_page("alice", "/api/v1/home/following-up", home["following_up_next"])

    notes = [i["note"] for i in home["following_up"]]
    notes += [i["note"] for page in pages for i in page["following_up"]]
    assert notes == [f"n{n}" for n in range(102, -1, -1)]
    assert [len(home["following_up"]), *(len(p["following_up"]) for p in pages)] == [50, 50, 3]
    assert {home["following_up_total"], *(p["following_up_total"] for p in pages)} == {103}
    assert (await lab.home("bob"))["following_up_next"] is None


async def test_a_done_request_leaves_following_up_after_30_days(lab: Lab):
    made = await ask(
        lab, "alice", {"kind": "ask_the_team", "about": {"capability": "x"}, "note": "n"}, "k"
    )
    await lab.client.post(
        f"/api/v1/team-requests/{made['request_id']}/replies",
        json={"text": "No.", "status": "done"},
        headers={"X-Dev-User": "bob"},
    )
    assert (await lab.home("alice"))["following_up_total"] == 1

    async with lab.h.db.transaction("builder") as uow:
        await uow.conn.execute(
            "UPDATE builder.team_requests SET done_at = %s", (uow.now - timedelta(days=31),)
        )

    assert (await lab.home("alice"))["following_up"] == []


async def test_home_shows_an_operator_the_connections_that_do_not_work_and_starts_no_check(
    lab: Lab,
):
    assert (await lab.home("alice"))["connections"] == []
    assert [lab.rig.probes[id].calls for id in ("jira", "github", "teams")] == [0, 0, 0]

    lab.rig.probes["jira"].reading = DOWN
    checked = await lab.rig.connections.check_now("jira")
    await lab.rig.connections.check_now("github")
    assert checked is not None and checked.checked_at is not None

    (item,) = (await lab.home("alice"))["connections"]
    assert item == {
        "id": "jira",
        "name": "Jira",
        "state": "not_answering",
        "problem": "Jira is not answering.",
        "fix": "Nothing to change yet. Check again in a few minutes.",
        "checked_at": checked.checked_at.isoformat().replace("+00:00", "Z"),
        "last_ok_at": None,
        "expires_at": None,
    }
    assert [lab.rig.probes[id].calls for id in ("jira", "github", "teams")] == [1, 1, 0]


async def test_home_lists_no_ai_model_for_an_operator_while_none_is_set_up(lab: Lab):
    lab.rig.probes["model"].reading = Reading("not_set_up", "No AI model is turned on.")
    (item,) = (await lab.home("alice"))["connections"]
    assert (item["id"], item["state"], item["fix"]) == (
        "model",
        "not_set_up",
        "Add an AI model under Settings, AI model.",
    )
    assert (await lab.home("bob"))["connections"] == []


async def test_home_leaves_connections_to_the_operators(lab: Lab):
    lab.rig.probes["jira"].reading = DOWN
    await lab.rig.connections.check_now("jira")
    assert (await lab.home("bob"))["connections"] == []
    assert len((await lab.home("carol"))["connections"]) == 1


async def test_a_reply_is_in_the_askers_needs_you_list_until_they_open_it(lab: Lab):
    made = await ask(
        lab, "alice", {"kind": "ask_the_team", "about": {"capability": "x"}, "note": "n"}, "k"
    )
    base = f"/api/v1/team-requests/{made['request_id']}"
    assert (await lab.home("alice"))["replied"] == []
    reply = await lab.client.post(
        base + "/replies", json={"text": "Not on the plan."}, headers={"X-Dev-User": "bob"}
    )

    mine = await lab.home("alice")

    assert [(i["request_id"], i["latest_reply"]["text"]) for i in mine["replied"]] == [
        (made["request_id"], "Not on the plan.")
    ]
    assert [i["request_id"] for i in mine["following_up"]] == [made["request_id"]]
    assert (await lab.home("bob"))["replied"] == []
    assert (await lab.home("carol"))["replied"] == []

    through = reply.json()["replies"][-1]["replied_at"]
    seen = await lab.client.post(
        base + "/seen", json={"through": through}, headers={"X-Dev-User": "alice"}
    )
    assert seen.status_code == 200
    after = await lab.home("alice")
    assert after["replied"] == []
    assert [i["request_id"] for i in after["following_up"]] == [made["request_id"]]


class StubAddresses:
    def __init__(self, rows: list[WatchedSoftwareView]) -> None:
        self.rows = rows

    async def needing_attention(self) -> list[WatchedSoftwareView]:
        return self.rows


async def test_home_lists_the_moved_and_missing_software_for_an_operator_only(lab: Lab):
    lost = watched("LangServe", "langchain-ai/langserve", not_found=True)
    moved = watched("FastAPI", "tiangolo/fastapi", moved_to="fastapi/fastapi")
    home: Home = lab.app.state.home
    home._addresses = StubAddresses([moved, lost])  # pyright: ignore[reportPrivateUsage]
    assert (await lab.home("bob"))["addresses"] == []
    items = (await lab.home("alice"))["addresses"]
    assert [(i["name"], i["repo"], i["moved_to"], i["not_found"]) for i in items] == [
        ("FastAPI", "tiangolo/fastapi", "fastapi/fastapi", False),
        ("LangServe", "langchain-ai/langserve", None, True),
    ]


def test_a_declined_test_run_with_no_recorded_decline_is_left_out_rather_than_failing_home():
    rejected = Rejected(RunId("run_1"), ProposalId("prp_1"), ApprovalId("apr_1"), UserId("bob"), 0)
    record = RunRecord(
        RunId("run_1"), replace(SPEC, test=True), UserId("alice"), NOW, NOW, 1, rejected, (), None
    )
    assert runs_of([RunDetail(record, 0, None, None, ())], ALICE_NOW, {}).declined == ()
