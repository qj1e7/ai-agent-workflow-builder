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
from platform_api.builder import Builder, Home, Watchlist
from platform_api.builder.cards import VERSION_CHECKER_ID
from platform_api.orchestration import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalStep,
    Schedule,
    ScheduleBook,
)
from platform_api.orchestration.people import Person
from platform_api.orchestration.people_store import People, PersonRow
from platform_api.orchestration.runs import AwaitingApproval, Failed, Leg, Pending, StepName
from platform_api.shared import (
    ExternalIdentity,
    N8nExecutionId,
    Principal,
    Role,
    RunId,
    SeedPerson,
    UseCaseId,
    UserId,
)
from tests.conftest import PostgresUrls
from tests.declared import declared_status
from tests.support import ALICE, LOCAL_ENV, SPEC
from tests.test_builder_http import NothingLearned
from tests.test_builder_lifecycle import ModelConnected
from tests.test_card_runs import output, ticket
from tests.test_orchestrator import Harness, open_harness

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
    "waiting_on_others": [],
    "waiting_on_others_total": 0,
    "drafts": [],
    "coming_up": None,
    "workflows": 0,
}


@dataclass
class Lab:
    h: Harness
    app: FastAPI
    client: httpx.AsyncClient
    people: People

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


@pytest.fixture
async def lab(postgres: PostgresUrls) -> AsyncIterator[Lab]:
    async with open_harness(postgres) as h:
        people = People(h.db)
        assert await people.seed_dev((*DEV_PEOPLE, DAVE, ERIN))
        watchlist = Watchlist(h.db, NothingLearned(), ScheduleBook(h.db))
        builder = Builder(
            h.db, h.orchestrator, watchlist, "http://localhost:8000", ModelConnected()
        )
        app = create_app(LOCAL_ENV)
        app.state.builder = builder
        app.state.watchlist = watchlist
        app.state.orchestrator = h.orchestrator
        app.state.people = people
        app.state.home = Home(builder, h.orchestrator, people)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Lab(h, app, client, people)


async def workflow(lab: Lab, owner: str = "alice", name: str = "Watch LangGraph") -> str:
    body = {
        "name": name,
        "instruction": "Check LangGraph for new releases.",
        "agents": [{"card_id": VERSION_CHECKER_ID, "values": VALUES}],
    }
    response = await lab.call(owner, "POST", "/api/v1/agent-use-cases", body)
    assert response.status_code == 201, response.text
    return response.json()["use_case_id"]


async def start(lab: Lab, use_case_id: str, by: str = "alice") -> RunId:
    response = await lab.call(by, "POST", f"/api/v1/use-cases/{use_case_id}/runs")
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


async def test_a_long_draft_name_is_cut_to_what_a_row_can_show(lab: Lab):
    long = {"step": 1, "content": {"name": "Nudge " * 40}}
    assert (await lab.call("alice", "PUT", "/api/v1/drafts/d-1", long)).status_code == 200

    (draft,) = (await lab.home("alice"))["drafts"]

    assert len(draft["name"]) == 80
    assert draft["name"].endswith("…")


async def test_coming_up_names_the_next_scheduled_workflow_and_how_many_more(lab: Lab):
    added = await lab.call(
        "alice",
        "POST",
        "/api/v1/watchlist/software",
        {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"},
    )
    assert added.status_code == 201, added.text
    scheduled = await lab.call(
        "alice", "PUT", "/api/v1/watchlist/schedule", {"day": "monday", "at": "09:00"}
    )
    assert scheduled.status_code == 200, scheduled.text
    await workflow(lab)

    home = await lab.home("bob")

    assert home["workflows"] == 2
    assert home["coming_up"] == {
        "use_case_id": added.json()["use_case_id"],
        "name": "Software watchlist",
        "template": "software_watchlist",
        "next_run_at": scheduled.json()["schedule"]["next_at"],
        "time_zone": "Asia/Singapore",
        "more": 0,
    }


async def test_coming_up_carries_its_schedules_own_time_zone(lab: Lab):
    use_case_id = await workflow(lab)
    london = Schedule("every_day", "09:00", "Europe/London")
    await ScheduleBook(lab.h.db).save(UseCaseId(use_case_id), london, ALICE_NOW)

    coming_up = (await lab.home("bob"))["coming_up"]

    assert coming_up["use_case_id"] == use_case_id
    assert coming_up["time_zone"] == "Europe/London"


async def test_someone_signed_in_but_not_on_the_list_is_refused(lab: Lab):
    async def stranger(request: object) -> ExternalIdentity:
        return ExternalIdentity(subject="oid-zed", user_name="zed@example.test", name="Zed")

    lab.app.state.authenticator = stranger

    response = await lab.client.get("/api/v1/home")

    assert response.status_code == 403
    declared_status(lab.app, "GET", "/api/v1/home", response)
