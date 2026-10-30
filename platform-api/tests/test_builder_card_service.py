"""Cards and agent use cases against the real tables, and through the routes."""

import asyncio
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder, Watchlist
from platform_api.builder.cards import VERSION_CHECKER
from platform_api.builder.models import (
    CardApprovalView,
    CardBlock,
    CardDefinition,
    CardInput,
    CreateAgentUseCase,
    UseCaseCreated,
    UseCaseView,
)
from platform_api.builder.service import AgentUseCaseRefused, NoModelToRun
from platform_api.db import Database
from platform_api.orchestration import (
    CardsTask,
    Choice,
    ChooseResult,
    Chosen,
    ChosenAgent,
    DraftResult,
    Given,
    LibraryCard,
    NoModel,
    RunSpec,
    RunStarted,
    RuntimeDown,
    ScheduleBook,
    SoftwareFacts,
    Standing,
    UnderstandResult,
    Understood,
    UnderstoodRow,
    WatchlistStanding,
)
from platform_api.shared import Principal, Role, RunId, SoftwareId, UseCaseId, UserId
from tests.support import LOCAL_ENV

pytestmark = pytest.mark.anyio

ALICE = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
AS_ALICE = {"X-Dev-User": "alice"}
AS_BOB = {"X-Dev-User": "bob"}
REPO = "GitHub repository"
PROJECT = "Jira project"
RELEASES = {REPO: "langchain-ai/langgraph", PROJECT: "MOCK"}


@dataclass
class Runs:
    started: list[RunSpec] = field(default_factory=lambda: [])

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.started.append(spec)
        return RunStarted(RunId("run_1"), created=True)


class NoFacts:
    async def standings(
        self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
    ) -> WatchlistStanding:
        raise AssertionError("not asked")


@dataclass
class Planner:
    model: bool = True
    chose: ChooseResult | NoModel | RuntimeDown = field(
        default_factory=lambda: Chosen(choice=Choice(decision="cannot_do", reason="No."))
    )
    seen: list[Sequence[LibraryCard]] = field(default_factory=lambda: [])
    understood: UnderstandResult | NoModel | RuntimeDown = field(default_factory=lambda: NoModel())
    wait: float = 0.0
    read: list[str] = field(default_factory=lambda: [])

    async def has_model(self) -> bool:
        return self.model

    async def choose(self, task: str, library: Sequence[LibraryCard]):
        self.seen.append(library)
        return self.chose

    async def draft(self, task: str) -> DraftResult | NoModel | RuntimeDown:
        return NoModel()

    async def understand(self, task: str) -> UnderstandResult | NoModel | RuntimeDown:
        self.read.append(task)
        await asyncio.sleep(self.wait)
        return self.understood


@pytest.fixture
def runs() -> Runs:
    return Runs()


@pytest.fixture
def planner() -> Planner:
    return Planner()


@pytest.fixture
def builder(db: Database, runs: Runs, planner: Planner) -> Builder:
    return Builder(
        db, runs, Watchlist(db, NoFacts(), ScheduleBook(db)), "http://localhost:8000", planner
    )


def reader(name: str = "Ticket reader", approvers: int = 1) -> CardDefinition:
    return CardDefinition(
        name=name,
        purpose="Raises a ticket.",
        inputs=[CardInput(name="Where", kind="jira_project", example="MOCK")],
        blocks=[CardBlock(say="Raise a ticket.", tool="jira.create_ticket")],
        approvals=[CardApprovalView(tool="jira.create_ticket", approvers=approvers)],
    )


async def use_case(builder: Builder, *agents: tuple[str, Mapping[str, str]]) -> UseCaseCreated:
    result = await builder.create_agent_use_case(
        ALICE,
        CreateAgentUseCase.model_validate(
            {
                "name": "Releases",
                "instruction": "Check releases.",
                "agents": [{"card_id": c, "values": dict(v)} for c, v in agents],
            }
        ),
    )
    assert isinstance(result, UseCaseCreated)
    return result


async def test_the_library_lists_starters_first_then_saved_cards_by_name(builder: Builder):
    await builder.create_card(ALICE, reader("Zed"))
    await builder.create_card(ALICE, reader("Alpha"))
    listed = await builder.list_cards()
    assert [c.name for c in listed.cards] == ["Version checker", "Alpha", "Zed"]
    assert [c.starter for c in listed.cards] == [True, False, False]


async def test_a_saved_card_reads_back_and_a_card_with_problems_is_not_saved(builder: Builder):
    saved = await builder.create_card(ALICE, reader())
    assert not hasattr(saved, "problems")
    card = await builder.get_card(saved.card_id)  # pyright: ignore[reportAttributeAccessIssue]
    assert card is not None and (card.version, card.owner, card.starter) == (1, "alice", False)
    assert card.tools == ["jira.create_ticket"]
    refused = await builder.create_card(ALICE, reader().model_copy(update={"inputs": []}))
    assert hasattr(refused, "refused")
    assert len((await builder.list_cards()).cards) == 2


async def test_the_rules_raise_the_saved_approvals(builder: Builder):
    saved = await builder.create_card(ALICE, reader(approvers=0))
    assert saved.approvals == [CardApprovalView(tool="jira.create_ticket", approvers=1)]  # pyright: ignore[reportAttributeAccessIssue]


async def test_an_edit_is_the_next_version_and_a_use_case_keeps_the_one_it_was_made_with(
    builder: Builder, runs: Runs
):
    saved = await builder.create_card(ALICE, reader())
    card_id = saved.card_id  # pyright: ignore[reportAttributeAccessIssue]
    made = await use_case(builder, (card_id, {"Where": "MOCK"}))
    edited = await builder.update_card(ALICE, card_id, reader("Renamed", approvers=2))
    assert (edited.version, edited.name) == (2, "Renamed")  # pyright: ignore[reportAttributeAccessIssue]
    view = await builder.get_use_case(made.use_case_id)
    assert view is not None
    assert [(a.card_version, a.name) for a in view.agents] == [(1, "Ticket reader")]
    spec = await builder.run_spec_for(UseCaseId(made.use_case_id))
    assert isinstance(spec, RunSpec) and isinstance(spec.task, CardsTask)
    assert [(r.card.version, r.card.name) for r in spec.task.agents] == [(1, "Ticket reader")]
    assert len(spec.approval_policy.steps) == 1


async def test_a_starter_cannot_be_edited_and_an_unknown_card_is_missing(builder: Builder):
    starter = await builder.update_card(ALICE, "crd_version_checker", reader())
    assert type(starter).__name__ == "StarterCard"
    assert type(await builder.update_card(ALICE, "crd_nope", reader())).__name__ == "NoSuchCard"


async def test_an_agent_use_case_shows_its_agents_and_the_line_a_run_draws(builder: Builder):
    made = await use_case(builder, ("crd_version_checker", RELEASES))
    view = await builder.get_use_case(made.use_case_id)
    assert view is not None
    assert (view.template, view.params, view.instruction) == (
        "agent_cards",
        {},
        "Check releases.",
    )
    [agent] = view.agents
    assert (agent.card_id, agent.card_version, agent.name, agent.values) == (
        "crd_version_checker",
        1,
        "Version checker",
        RELEASES,
    )
    assert [(b.kind, b.key) for b in view.plan] == [
        ("agent", "crd_version_checker"),
        ("approval", "approval_gate"),
        ("write_action", "jira_create_ticket"),
    ]
    listed = await builder.list_use_cases()
    assert listed.use_cases[0] == view


async def test_a_schedule_saved_with_the_use_case_belongs_to_the_person_who_set_it_up(
    builder: Builder, db: Database
):
    made = await builder.create_agent_use_case(
        ALICE,
        CreateAgentUseCase.model_validate(
            {
                "name": "Follow up stale bugs",
                "instruction": "Find stale bugs and list them in one ticket.",
                "agents": [{"card_id": "crd_version_checker", "values": RELEASES}],
                "schedule": {"day": "weekdays", "at": "15:00"},
            }
        ),
    )
    assert isinstance(made, UseCaseCreated)
    view = await builder.get_use_case(made.use_case_id)
    assert view is not None and view.schedule is not None
    assert (view.schedule.day, view.schedule.at, view.schedule.time_zone) == (
        "weekdays",
        "15:00",
        "Asia/Singapore",
    )
    assert view.next_run_at is not None and view.next_run_at > db.clock()
    saved = await ScheduleBook(db).get(UseCaseId(made.use_case_id))
    assert saved is not None and (saved.owner, saved.owner_name) == ("alice", "Alice")


async def test_a_use_case_made_without_a_schedule_has_none(builder: Builder):
    made = await use_case(builder, ("crd_version_checker", RELEASES))
    view = await builder.get_use_case(made.use_case_id)
    assert view is not None and (view.schedule, view.next_run_at) == (None, None)


async def test_the_watchlist_use_case_has_its_templates_blocks_and_no_agents(
    builder: Builder, db: Database
):
    from platform_api.builder.models import AddSoftware, WatchlistView

    class NothingLearned:
        async def standings(
            self, use_case_id: UseCaseId, given: Mapping[SoftwareId, Given | None]
        ) -> WatchlistStanding:
            return WatchlistStanding(
                {
                    software_id: Standing(SoftwareFacts(typed, None, None, None), "not_checked")
                    for software_id, typed in given.items()
                },
                None,
            )

    added = await Watchlist(db, NothingLearned(), ScheduleBook(db)).add(
        ALICE, AddSoftware(name="LangGraph", repo="langchain-ai/langgraph", our_version="1.2.14")
    )
    assert isinstance(added, WatchlistView)
    view = await builder.get_use_case(added.use_case_id)
    assert view is not None and view.agents == []
    assert [b.key for b in view.plan] == ["read_versions", "approval_gate", "create_tickets"]


async def test_values_are_checked_by_kind_before_anything_is_saved(builder: Builder):
    bad = await builder.create_agent_use_case(
        ALICE,
        CreateAgentUseCase.model_validate(
            {
                "name": "n",
                "instruction": "i",
                "agents": [
                    {"card_id": "crd_version_checker", "values": {REPO: "x", PROJECT: "mock"}},
                    {"card_id": "crd_missing", "values": {}},
                ],
            }
        ),
    )
    assert isinstance(bad, AgentUseCaseRefused)
    where = {loc: msg for loc, msg in bad.errors}
    assert set(where) == {
        ("body", "agents", 0, "values", REPO),
        ("body", "agents", 0, "values", PROJECT),
        ("body", "agents", 1, "card_id"),
    }
    assert (await builder.list_use_cases()).use_cases == []


async def test_the_same_agent_twice_is_refused(builder: Builder):
    body = CreateAgentUseCase.model_validate(
        {
            "name": "n",
            "instruction": "i",
            "agents": [{"card_id": "crd_version_checker", "values": RELEASES}] * 2,
        }
    )
    bad = await builder.create_agent_use_case(ALICE, body)
    assert isinstance(bad, AgentUseCaseRefused)
    assert bad.errors[0][0] == ("body", "agents", 1, "card_id")


async def test_two_agents_in_two_projects_are_bound_separately_with_the_most_approvers(
    builder: Builder, runs: Runs
):
    other = await builder.create_card(ALICE, reader(approvers=2))
    made = await use_case(
        builder,
        ("crd_version_checker", {REPO: "a/b", PROJECT: "AAA"}),
        (other.card_id, {"Where": "BBB"}),  # pyright: ignore[reportAttributeAccessIssue]
    )
    spec = await builder.run_spec_for(UseCaseId(made.use_case_id))
    assert isinstance(spec, RunSpec) and isinstance(spec.task, CardsTask)
    first, second = spec.task.agents
    assert first.bindings["jira.create_ticket"].target == {"project": "AAA"}
    assert second.bindings["jira.create_ticket"].target == {"project": "BBB"}
    assert spec.bindings == {}
    assert [s.label for s in spec.approval_policy.steps] == ["Team approver", "Second approver"]


async def test_a_card_run_without_a_model_is_refused_before_a_run_exists(
    builder: Builder, runs: Runs, planner: Planner
):
    made = await use_case(builder, ("crd_version_checker", RELEASES))
    planner.model = False
    result = await builder.start_run(UseCaseId(made.use_case_id), ALICE, "k")
    assert isinstance(result, NoModelToRun) and runs.started == []
    planner.model = True
    started = await builder.start_run(UseCaseId(made.use_case_id), ALICE, "k")
    assert isinstance(started, RunStarted) and len(runs.started) == 1


# The routes


@pytest.fixture
async def client(db: Database, builder: Builder) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(LOCAL_ENV)
    app.state.builder = builder
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


CARD_JSON = reader().model_dump(mode="json")


async def test_tools_and_cards_can_be_read_by_anyone_signed_in(client: httpx.AsyncClient):
    tools = await client.get("/api/v1/tools", headers=AS_BOB)
    assert [t["id"] for t in tools.json()["tools"]][-1] == "jira.create_ticket"
    cards = await client.get("/api/v1/agent-cards", headers=AS_BOB)
    assert cards.json()["cards"][0]["card_id"] == "crd_version_checker"
    one = await client.get("/api/v1/agent-cards/crd_version_checker", headers=AS_BOB)
    assert one.json()["starter"] is True
    assert (await client.get("/api/v1/agent-cards/crd_nope", headers=AS_BOB)).status_code == 404
    assert (await client.get("/api/v1/tools")).status_code == 401


async def test_check_answers_problems_without_saving(client: httpx.AsyncClient):
    r = await client.post(
        "/api/v1/agent-cards/check", json={**CARD_JSON, "inputs": []}, headers=AS_BOB
    )
    assert r.status_code == 200
    assert [p["field"] for p in r.json()["problems"]] == ["inputs"]
    assert r.json()["approvals"] == [{"tool": "jira.create_ticket", "approvers": 1}]
    assert len((await client.get("/api/v1/agent-cards", headers=AS_BOB)).json()["cards"]) == 1


async def test_saving_needs_an_operator_and_no_problems(client: httpx.AsyncClient):
    assert (
        await client.post("/api/v1/agent-cards", json=CARD_JSON, headers=AS_BOB)
    ).status_code == 403
    refused = await client.post(
        "/api/v1/agent-cards", json={**CARD_JSON, "name": "Forge"}, headers=AS_ALICE
    )
    assert refused.status_code == 422
    assert refused.json()["problems"][0]["field"] == "name"
    saved = await client.post("/api/v1/agent-cards", json=CARD_JSON, headers=AS_ALICE)
    assert saved.status_code == 201 and saved.json()["version"] == 1
    card_id = saved.json()["card_id"]
    again = await client.put(f"/api/v1/agent-cards/{card_id}", json=CARD_JSON, headers=AS_ALICE)
    assert (again.status_code, again.json()["version"]) == (200, 2)
    bad = await client.put(
        f"/api/v1/agent-cards/{card_id}", json={**CARD_JSON, "blocks": []}, headers=AS_ALICE
    )
    assert bad.status_code == 422


async def test_a_starter_card_cannot_be_overwritten_and_an_unknown_one_is_404(
    client: httpx.AsyncClient,
):
    starter = await client.put(
        "/api/v1/agent-cards/crd_version_checker", json=CARD_JSON, headers=AS_ALICE
    )
    assert (starter.status_code, starter.json()["detail"]) == (
        409,
        "Starter agents cannot be changed. Copy it instead.",
    )
    assert (
        await client.put("/api/v1/agent-cards/crd_nope", json=CARD_JSON, headers=AS_ALICE)
    ).status_code == 404


async def test_plan_picks_a_saved_agent_and_saves_nothing(
    client: httpx.AsyncClient, planner: Planner
):
    planner.chose = Chosen(
        choice=Choice(
            decision="use_one",
            agents=[ChosenAgent(card_id="crd_version_checker", part="Check", values=RELEASES)],
            reason="It fits.",
        )
    )
    r = await client.post(
        "/api/v1/builder/plan", json={"task": "check langgraph"}, headers=AS_ALICE
    )
    assert r.status_code == 200
    assert (r.json()["decision"], r.json()["agents"][0]["values"]) == ("use_one", RELEASES)
    assert (await client.get("/api/v1/use-cases", headers=AS_ALICE)).json()["use_cases"] == []


async def test_plan_without_a_model_is_409_and_with_the_runtime_down_503(
    client: httpx.AsyncClient, planner: Planner
):
    planner.chose = NoModel()
    r = await client.post("/api/v1/builder/plan", json={"task": "x"}, headers=AS_ALICE)
    assert (r.status_code, r.json()["detail"]) == (409, "Connect an AI model in Settings first.")
    planner.chose = RuntimeDown("boom")
    assert (
        await client.post("/api/v1/builder/plan", json={"task": "x"}, headers=AS_ALICE)
    ).status_code == 503
    assert (
        await client.post("/api/v1/builder/plan", json={"task": "x"}, headers=AS_BOB)
    ).status_code == 403
    assert (
        await client.post("/api/v1/builder/plan", json={"task": " "}, headers=AS_ALICE)
    ).status_code == 422


async def test_an_agent_use_case_is_made_started_and_refused_without_a_model(
    client: httpx.AsyncClient, planner: Planner
):
    body = {
        "name": "Releases",
        "instruction": "Check.",
        "agents": [{"card_id": "crd_version_checker", "values": RELEASES}],
    }
    assert (
        await client.post("/api/v1/agent-use-cases", json=body, headers=AS_BOB)
    ).status_code == 403
    bad = await client.post(
        "/api/v1/agent-use-cases",
        json={**body, "agents": [{"card_id": "crd_version_checker", "values": {}}]},
        headers=AS_ALICE,
    )
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"][:3] == ["body", "agents", 0]
    none = await client.post(
        "/api/v1/agent-use-cases", json={**body, "agents": []}, headers=AS_ALICE
    )
    assert none.status_code == 422
    made = await client.post("/api/v1/agent-use-cases", json=body, headers=AS_ALICE)
    assert made.status_code == 201
    uc = made.json()["use_case_id"]
    view = UseCaseView.model_validate(
        (await client.get(f"/api/v1/use-cases/{uc}", headers=AS_BOB)).json()
    )
    assert view.agents[0].name == "Version checker"
    planner.model = False
    start = await client.post(
        f"/api/v1/use-cases/{uc}/runs", headers={**AS_ALICE, "Idempotency-Key": "k"}
    )
    assert (start.status_code, start.json()["detail"]) == (
        409,
        "Connect an AI model in Settings to run agents.",
    )
    planner.model = True
    ok = await client.post(
        f"/api/v1/use-cases/{uc}/runs", headers={**AS_ALICE, "Idempotency-Key": "k"}
    )
    assert ok.status_code == 201


async def test_a_schedule_off_the_five_minute_step_is_refused_and_nothing_is_made(
    client: httpx.AsyncClient,
):
    body = {
        "name": "Releases",
        "instruction": "Check.",
        "agents": [{"card_id": "crd_version_checker", "values": RELEASES}],
        "schedule": {"day": "weekdays", "at": "15:03"},
    }
    bad = await client.post("/api/v1/agent-use-cases", json=body, headers=AS_ALICE)
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["loc"][:3] == ["body", "schedule", "at"]
    listed = await client.get("/api/v1/use-cases", headers=AS_ALICE)
    assert listed.json()["use_cases"] == []
    made = await client.post(
        "/api/v1/agent-use-cases",
        json={**body, "schedule": {"day": "weekdays", "at": "15:00"}},
        headers=AS_ALICE,
    )
    assert made.status_code == 201
    view = await client.get(f"/api/v1/use-cases/{made.json()['use_case_id']}", headers=AS_BOB)
    assert view.json()["schedule"]["day"] == "weekdays"


async def test_the_agent_template_cannot_be_built_by_hand(client: httpx.AsyncClient):
    r = await client.post(
        "/api/v1/use-cases",
        json={"template": "agent_cards", "name": "n", "instruction": "i", "params": {}},
        headers=AS_ALICE,
    )
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "Describe the task on the Builder page"


def test_the_starter_is_the_one_the_tests_assume():
    assert VERSION_CHECKER.card_id == "crd_version_checker"


FOLLOW_UP = (
    "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one "
    "follow-up ticket that lists them"
)
FOUR_ROWS = Understood(
    rows=[
        UnderstoodRow(kind="schedule", text="Every weekday at 3pm", state="understood"),
        UnderstoodRow(kind="look_for", text="Bug tickets in MOCK", state="understood"),
        UnderstoodRow(kind="do", text="Create one follow-up ticket", state="understood"),
        UnderstoodRow(kind="where", text="Jira project MOCK", state="understood"),
    ]
)


async def test_understand_reads_the_task_back_for_an_operator_and_saves_nothing(
    client: httpx.AsyncClient, planner: Planner
):
    planner.understood = FOUR_ROWS
    r = await client.post("/api/v1/builder/understand", json={"text": FOLLOW_UP}, headers=AS_ALICE)
    assert r.status_code == 200
    assert r.json()["answer"] == "rows"
    assert [row["state"] for row in r.json()["rows"]] == ["understood"] * 4
    assert planner.read == [FOLLOW_UP]
    assert (await client.get("/api/v1/use-cases", headers=AS_ALICE)).json()["use_cases"] == []


async def test_understand_is_for_operators_only_and_needs_some_text(
    client: httpx.AsyncClient, planner: Planner
):
    planner.understood = FOUR_ROWS
    refused = await client.post("/api/v1/builder/understand", json={"text": "x"}, headers=AS_BOB)
    assert refused.status_code == 403
    blank = await client.post("/api/v1/builder/understand", json={"text": " "}, headers=AS_ALICE)
    assert blank.status_code == 422
    assert planner.read == []


async def test_understand_without_a_model_answers_the_starter_workflows(
    client: httpx.AsyncClient, planner: Planner
):
    r = await client.post("/api/v1/builder/understand", json={"text": "x"}, headers=AS_ALICE)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "starters"
    assert "No AI model is connected" in body["message"]
    assert [s["name"] for s in body["starters"]][0] == "Keep our software up to date"


async def test_understand_answers_the_starters_when_the_planner_is_slower_than_the_limit(
    client: httpx.AsyncClient, planner: Planner, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("platform_api.builder.planning.UNDERSTAND_LIMIT_SECONDS", 0.2)
    planner.understood, planner.wait = FOUR_ROWS, 3.0
    started = time.monotonic()
    r = await client.post("/api/v1/builder/understand", json={"text": "x"}, headers=AS_ALICE)
    assert time.monotonic() - started < 2
    assert (r.status_code, r.json()["answer"]) == (200, "starters")
    assert "took too long" in r.json()["message"]
