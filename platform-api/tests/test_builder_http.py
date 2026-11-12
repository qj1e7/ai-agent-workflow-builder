import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from platform_api.app import create_app
from platform_api.builder import Builder, PlannerFront, Watchlist
from platform_api.builder import planner as planner_module
from platform_api.builder.home import HomeOut
from platform_api.builder.models import AddSoftware, CreateAgentUseCase
from platform_api.builder.planner_facts import STATUS_WORDS, PlannerFactsReader
from platform_api.db import Database
from platform_api.orchestration import (
    AbilitiesAnswer,
    Answered,
    AnswerResult,
    CantAnswer,
    CantRow,
    CapabilityList,
    CapabilitySpec,
    CardsTask,
    CheckPartResult,
    CheckWorkflowsAnswer,
    ConnectionCheck,
    ExampleSpec,
    Given,
    ModelProblem,
    NeedsMeAnswer,
    NoModel,
    PartAnswer,
    PartCantDo,
    PartFits,
    PlannerFacts,
    PreviousTurn,
    QuestionAnswer,
    RefusedAnswer,
    RequestPart,
    RowKind,
    RunDetail,
    RunGist,
    RunSpec,
    RunStarted,
    RuntimeDown,
    ScheduleBook,
    SetupCardAnswer,
    SoftwareFacts,
    Standing,
    UnderstoodRow,
    WatchedFact,
    WatchlistAnswer,
    WatchlistStanding,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
)
from platform_api.orchestration.approvals import Decision, Verdict
from platform_api.orchestration.run_gist import gist_of
from platform_api.orchestration.runs import (
    AwaitingApproval,
    Failed,
    Failure,
    Outcome,
    Pending,
    Rejected,
    ResumeWork,
    Stage,
    Succeeded,
    WriteDone,
)
from platform_api.orchestration.runs import (
    FailureReason as RunFailure,
)
from platform_api.orchestration.runs import RunState as RunPhase
from platform_api.orchestration.spec import Task
from platform_api.orchestration.store import RunRecord
from platform_api.orchestration.write_actions import Proposal, WriteAction
from platform_api.shared import (
    ApprovalId,
    Digest,
    Principal,
    ProposalId,
    Role,
    RunId,
    SoftwareId,
    UseCaseId,
    UserId,
)
from platform_api.wire import Trigger
from tests.support import LOCAL_ENV, SPEC

pytestmark = pytest.mark.anyio

ALICE = {"X-Dev-User": "alice"}
LANGGRAPH = {"name": "LangGraph", "repo": "langchain-ai/langgraph", "our_version": "1.2.14"}
GOOD = {
    "template": "software_watchlist",
    "name": "Software watchlist",
    "instruction": "Check the team's watched software for new releases.",
    "params": {"ticket_project": "MOCK"},
}


class SecondCallRepeats:
    def __init__(self) -> None:
        self.calls = 0
        self.specs: list[RunSpec] = []

    async def start_run(self, spec: RunSpec, principal: Principal, idempotency_key: str):
        self.calls += 1
        self.specs.append(spec)
        return RunStarted(RunId("run_1"), created=self.calls == 1)


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


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(LOCAL_ENV)
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    app.state.builder = Builder(db, SecondCallRepeats(), watchlist, "http://localhost:8000")
    app.state.watchlist = watchlist
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


AGENT_USE_CASE = {
    "name": "Friday summary",
    "instruction": "Sum up the tickets closed this week.",
    "agents": [
        {
            "card_id": "crd_version_checker",
            "values": {"GitHub repository": "a/b", "Jira project": "MOCK"},
        }
    ],
}


async def test_a_workflow_keeps_what_it_was_set_up_without_as_text_for_people(
    client: httpx.AsyncClient,
):
    body = {**AGENT_USE_CASE, "left_out": ["colour them by team", "  Friday  "]}
    made = await client.post("/api/v1/agent-use-cases", json=body, headers=ALICE)
    assert made.status_code == 201, made.text
    use_case_id = made.json()["use_case_id"]

    read = await client.get(f"/api/v1/use-cases/{use_case_id}", headers=ALICE)
    listed = (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"]

    assert read.json()["left_out"] == ["colour them by team", "Friday"]
    assert [u["left_out"] for u in listed if u["use_case_id"] == use_case_id] == [
        ["colour them by team", "Friday"]
    ]
    assert read.json()["instruction"] == AGENT_USE_CASE["instruction"]


async def test_a_workflow_set_up_with_every_part_has_nothing_left_out(client: httpx.AsyncClient):
    made = await client.post("/api/v1/agent-use-cases", json=AGENT_USE_CASE, headers=ALICE)
    assert made.status_code == 201, made.text
    read = await client.get(f"/api/v1/use-cases/{made.json()['use_case_id']}", headers=ALICE)
    assert read.json()["left_out"] == []


@pytest.mark.parametrize(
    "left_out",
    [[""], ["x" * 201], ["part"] * 11, "colour them by team"],
    ids=["blank", "too long", "too many", "not a list"],
)
async def test_left_out_that_cannot_be_kept_is_refused_with_a_422(
    client: httpx.AsyncClient, left_out: object
):
    body = {**AGENT_USE_CASE, "left_out": left_out}
    r = await client.post("/api/v1/agent-use-cases", json=body, headers=ALICE)
    assert r.status_code == 422, r.text
    assert any("left_out" in e["loc"] for e in r.json()["detail"])


async def save(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/v1/watchlist/software", json=LANGGRAPH, headers=ALICE)
    assert r.status_code == 201
    return r.json()["use_case_id"]


async def test_the_two_templates_are_listed_and_neither_takes_a_repository(
    client: httpx.AsyncClient,
):
    r = await client.get("/api/v1/templates", headers=ALICE)
    watchlist, agents = r.json()["templates"]
    assert watchlist["key"] == "software_watchlist"
    assert [p["name"] for p in watchlist["params"]] == ["ticket_project"]
    assert (agents["key"], agents["blocks"], agents["params"]) == ("agent_cards", [], [])


async def test_the_watchlist_template_is_listed_but_not_built_by_hand(client: httpx.AsyncClient):
    r = await client.post("/api/v1/use-cases", json=GOOD, headers=ALICE)
    assert r.status_code == 422
    [problem] = r.json()["detail"]
    assert (problem["loc"], problem["msg"]) == (
        ["body", "template"],
        "Add software on the Software page",
    )
    assert (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


async def test_a_saved_use_case_can_be_read_and_listed(client: httpx.AsyncClient):
    use_case_id = await save(client)
    got = await client.get(f"/api/v1/use-cases/{use_case_id}", headers=ALICE)
    assert got.status_code == 200
    assert got.json()["owner"] == "alice"
    listed = await client.get("/api/v1/use-cases", headers=ALICE)
    assert [u["use_case_id"] for u in listed.json()["use_cases"]] == [use_case_id]


async def test_an_unknown_template_gets_a_422_naming_the_template(client: httpx.AsyncClient):
    r = await client.post("/api/v1/use-cases", json={**GOOD, "template": "nope"}, headers=ALICE)
    assert r.status_code == 422
    [problem] = r.json()["detail"]
    assert (problem["loc"], problem["msg"]) == (["body", "template"], "Unknown template 'nope'")
    assert (await client.get("/api/v1/use-cases", headers=ALICE)).json()["use_cases"] == []


async def test_an_unknown_use_case_is_a_404(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/use-cases/uc_nope", headers=ALICE)).status_code == 404
    r = await client.post(
        "/api/v1/use-cases/uc_nope/runs", headers={**ALICE, "Idempotency-Key": "k"}
    )
    assert r.status_code == 404


async def test_a_repeated_idempotency_key_gets_200_with_the_same_body(client: httpx.AsyncClient):
    use_case_id = await save(client)
    headers = {**ALICE, "Idempotency-Key": "k"}
    first = await client.post(f"/api/v1/use-cases/{use_case_id}/runs", headers=headers)
    second = await client.post(f"/api/v1/use-cases/{use_case_id}/runs", headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert (
        first.json()
        == second.json()
        == {
            "run_id": "run_1",
            "state": "pending",
            "events_url": "/api/v1/runs/run_1/events",
        }
    )


async def test_suggest_answers_no_template_now_that_none_is_offered(client: httpx.AsyncClient):
    text = "Check langchain-ai/langgraph for new releases and open a ticket for the team."
    r = await client.post("/api/v1/use-cases/suggest", json={"text": text}, headers=ALICE)
    assert r.status_code == 200
    assert r.json() == {"template": None, "matched_terms": []}


async def test_every_builder_route_needs_a_signed_in_user(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/use-cases")).status_code == 401
    assert (await client.post("/api/v1/use-cases", json=GOOD)).status_code == 401


BOB = {"X-Dev-User": "bob"}
FRIDAY = "Every Friday, sum up the tickets we closed this week"
ANSWER = "/api/v1/planner/answer"


def understood(kind: RowKind, text: str, state: str = "understood") -> UnderstoodRow:
    return UnderstoodRow(kind=kind, text=text, state=state, note=None)  # type: ignore[arg-type]


FOUR_ROWS = [
    understood("schedule", "Every Friday"),
    understood("look_for", "Tickets closed this week"),
    understood("do", "Sum them up in one ticket"),
    understood("where", "In MOCK"),
]
EMAIL = CantRow(
    kind="do",
    text="email it",
    note="I can't email it. I can only read Jira tickets.",
    needs="new_system",
    system="email",
)


@dataclass
class FakeAnswers:
    result: AnswerResult | NoModel | RuntimeDown = field(default_factory=NoModel)
    part: CheckPartResult | RuntimeDown = field(default_factory=lambda: RuntimeDown("down"))
    wait: float = 0.0
    asked: list[str] = field(default_factory=list[str])
    facts: list[PlannerFacts | None] = field(default_factory=list[PlannerFacts | None])
    previous: list[PreviousTurn | None] = field(default_factory=list[PreviousTurn | None])
    checked: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    async def answer(
        self, task: str, facts: PlannerFacts | None = None, previous: PreviousTurn | None = None
    ) -> AnswerResult | NoModel | RuntimeDown:
        self.asked.append(task)
        self.facts.append(facts)
        self.previous.append(previous)
        await asyncio.sleep(self.wait)
        return self.result

    async def check_part(self, kind: RowKind, text: str) -> CheckPartResult | RuntimeDown:
        self.checked.append((kind, text))
        return self.part


TICKET = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "Upgrade LangGraph"})


class RunBook:
    """The runs the platform has, which Builder reads for each workflow's last run."""

    def __init__(self) -> None:
        self.runs: list[RunDetail] = []
        self.asked: list[list[UseCaseId]] = []
        self.viewers: list[Principal | None] = []

    async def newest_runs(
        self, use_case_ids: Sequence[UseCaseId], viewer: Principal | None = None
    ) -> dict[UseCaseId, RunGist]:
        self.asked.append(list(use_case_ids))
        self.viewers.append(viewer)
        newest: dict[UseCaseId, RunDetail] = {}
        for run in self.runs:
            key = run.record.spec.use_case_id
            if key in use_case_ids and (
                key not in newest
                or (run.record.started_at, run.record.run_id)
                > (newest[key].record.started_at, newest[key].record.run_id)
            ):
                newest[key] = run
        return {key: gist_of(run, viewer) for key, run in newest.items()}

    def add(
        self,
        use_case_id: str,
        state: RunPhase,
        at: datetime,
        trigger: Trigger = "schedule",
        proposed: int = 0,
        task: Task = SPEC.task,
        test: bool = False,
        decisions: tuple[Decision, ...] = (),
    ) -> RunId:
        run_id = RunId(f"run_{len(self.runs) + 1}")
        record = RunRecord(
            run_id,
            replace(
                SPEC, use_case_id=UseCaseId(use_case_id), trigger=trigger, task=task, test=test
            ),
            UserId("alice"),
            at,
            at,
            1,
            state,
            (),
            None,
        )
        proposal = Proposal(ProposalId("prp_1"), run_id, (TICKET,) * proposed, Digest("d"))
        self.runs.append(RunDetail(record, 0, proposal if proposed else None, None, decisions))
        return run_id


class FakeHome:
    def __init__(self) -> None:
        self.viewers: list[Principal] = []

    async def for_person(self, viewer: Principal) -> HomeOut:
        self.viewers.append(viewer)
        counts = SimpleNamespace(
            approvals_total=2,
            confirmations=[1],
            stopped_total=0,
            connections=[],
            addresses=[],
            replied=[1],
        )
        return cast(HomeOut, counts)


class FakeRegistry:
    def __init__(self, listed: CapabilityList | RuntimeDown) -> None:
        self.listed = listed

    async def get(self) -> CapabilityList | RuntimeDown:
        return self.listed


class FakeStates:
    def __init__(self, *checks: ConnectionCheck) -> None:
        self.checks = list(checks)

    async def view(self) -> list[ConnectionCheck]:
        return self.checks


def a_check(id: str, **changes: object) -> ConnectionCheck:
    base = ConnectionCheck(
        id=id,  # type: ignore[arg-type]
        name=id.title(),
        practice=False,
        state="working",
        checked_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
        last_ok_at=datetime(2026, 11, 9, 1, 0, tzinfo=UTC),
        problem=None,
        key_ends_in=None,
        expires_at=None,
        fix=None,
    )
    return ConnectionCheck(**{**base.__dict__, **changes})


def spec(id: str, **changes: object) -> CapabilitySpec:
    base = CapabilitySpec(
        id=id,
        plain=f"Do {id}",
        kind="read",
        system="Jira",
        state="ready",
        cant=None,
        why=None,
        connection="jira",
        needs_model=False,
        platform=False,
        focus=False,
        tools=["jira.search"],
    )
    return CapabilitySpec(**{**base.model_dump(), **changes})


TEAMS_WHY = "Teams carries approval requests, run outcomes and requests for the team."
REGISTRY = CapabilityList(
    capabilities=[
        spec("jira.read", needs_model=True),
        spec(
            "github.releases", connection="github", system="GitHub", tools=["github.read_releases"]
        ),
        spec(
            "teams.ask", kind="notify", system="Teams", connection="teams", tools=[], platform=True
        ),
        spec(
            "teams.post",
            kind="write",
            state="planned",
            cant="post messages in Teams",
            why=TEAMS_WHY,
            connection="teams",
            tools=[],
        ),
        spec(
            "email.send",
            kind="write",
            state="unsupported",
            cant="send email",
            why="Email is not on the team's plan.",
            connection=None,
            system=None,
            tools=[],
        ),
    ],
    examples=[ExampleSpec(text=FRIDAY, kind="automate", needs=["jira.read"])],
)


@dataclass
class Front:
    client: httpx.AsyncClient
    answers: FakeAnswers
    states: FakeStates
    registry: FakeRegistry
    builder: Builder
    watchlist: Watchlist
    home: FakeHome
    book: RunBook
    starter: SecondCallRepeats


@pytest.fixture
async def front(db: Database) -> AsyncIterator[Front]:
    app = create_app(LOCAL_ENV)
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    book = RunBook()
    starter = SecondCallRepeats()
    builder = Builder(db, starter, watchlist, "http://localhost:8000", history=book)
    answers = FakeAnswers()
    states = FakeStates(a_check("jira"), a_check("github"), a_check("teams"), a_check("model"))
    registry = FakeRegistry(REGISTRY)
    app.state.builder = builder
    app.state.watchlist = watchlist
    home = FakeHome()
    facts = PlannerFactsReader(watchlist, builder, home)
    app.state.planner_front = PlannerFront(answers, builder, watchlist, registry, states, facts)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield Front(c, answers, states, registry, builder, watchlist, home, book, starter)


async def say(front: Front, text: str = FRIDAY) -> dict[str, object]:
    r = await front.client.post(ANSWER, json={"text": text}, headers=ALICE)
    assert r.status_code == 200, r.text
    return cast(dict[str, object], r.json())


def answered(answer: object) -> Answered:
    return Answered(answer=answer)  # type: ignore[arg-type]


async def make_workflow(front: Front, name: str) -> str:
    made = await front.builder.create_agent_use_case(
        Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice"),
        CreateAgentUseCase.model_validate(
            {
                "name": name,
                "instruction": "x",
                "agents": [
                    {
                        "card_id": "crd_version_checker",
                        "values": {"GitHub repository": "a/b", "Jira project": "MOCK"},
                    }
                ],
            }
        ),
    )
    assert not isinstance(made, planner_module.NoSuchWorkflow) and hasattr(made, "use_case_id")
    return str(made.use_case_id)  # type: ignore[union-attr]


async def test_a_set_up_card_comes_back_with_its_rows_and_a_similar_workflow(front: Front):
    front.answers.result = answered(SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS))
    first = await say(front)
    assert first["answer"] == "setup_card" and first["similar"] is None
    assert [r["kind"] for r in cast(list[dict[str, str]], first["rows"])] == [
        "schedule",
        "look_for",
        "do",
        "where",
    ]
    assert front.answers.asked == [FRIDAY]
    existing = await make_workflow(front, "friday SUMMARY")
    again = await say(front)
    assert again["similar"] == {"use_case_id": existing, "name": "friday SUMMARY"}


async def test_every_part_of_the_request_comes_back_with_its_mark_in_order(front: Front):
    typed = "Every Monday and Friday at 9am, sum up the closed tickets and colour them by team"
    parts = [
        RequestPart(
            text="Monday and Friday", mark="cant", reason="one_day", choices=["Monday", "Friday"]
        ),
        RequestPart(text="sum up the closed tickets", mark="will_do"),
        RequestPart(text="colour them by team", mark="cant", reason="not_followed"),
    ]
    card = SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS)
    front.answers.result = Answered(answer=card, parts=parts)

    reply = await say(front, typed)

    assert reply["parts"] == [
        {
            "text": "Monday and Friday",
            "mark": "cant",
            "reason": "one_day",
            "note": None,
            "choices": ["Monday", "Friday"],
        },
        {
            "text": "sum up the closed tickets",
            "mark": "will_do",
            "reason": None,
            "note": None,
            "choices": [],
        },
        {
            "text": "colour them by team",
            "mark": "cant",
            "reason": "not_followed",
            "note": None,
            "choices": [],
        },
    ]


async def test_parts_belong_to_the_whole_answer_never_to_the_rest_inside_it(front: Front):
    rest = SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS)
    front.answers.result = Answered(
        answer=WatchlistAnswer(word="release", software=None, also=rest),
        parts=[RequestPart(text="Watch releases", mark="will_do")],
    )
    reply = await say(front, "Watch releases and every Friday sum up")
    assert [p["text"] for p in cast(list[dict[str, object]], reply["parts"])] == ["Watch releases"]
    assert cast(dict[str, object], reply["also"])["parts"] == []


async def test_a_tapped_chip_and_the_offline_answer_mark_no_parts(front: Front):
    r = await front.client.post(ANSWER, json={"intent": "needs_me"}, headers=ALICE)
    assert r.json() == {"parts": [], "answer": "needs_me"}
    front.answers.result = NoModel()
    assert (await say(front))["parts"] == []


async def test_a_part_keeps_the_part_the_platform_cannot_do(front: Front):
    front.answers.result = answered(PartAnswer(name="Friday", rows=FOUR_ROWS, cant=[EMAIL]))
    reply = await say(front)
    assert reply["answer"] == "part"
    assert cast(list[dict[str, object]], reply["cant"])[0] == {
        "kind": "do",
        "text": "email it",
        "note": EMAIL.note,
        "needs": "new_system",
        "system": "email",
    }


async def test_a_cant_offers_its_alternative(front: Front):
    card = SetupCardAnswer(name="Stale list", rows=FOUR_ROWS)
    front.answers.result = answered(CantAnswer(cant=[EMAIL], alternative=card))
    reply = await say(front, "Email the list")
    assert reply["answer"] == "cant"
    assert cast(dict[str, object], reply["alternative"])["answer"] == "setup_card"
    front.answers.result = answered(CantAnswer(cant=[EMAIL]))
    assert (await say(front, "Email it"))["alternative"] is None


async def test_a_watchlist_row_says_when_the_software_is_already_listed(front: Front):
    front.answers.result = answered(WatchlistAnswer(word="releases", software="langgraph"))
    assert (await say(front, "Watch langgraph"))["already_listed"] is None
    await front.watchlist.add(
        Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice"),
        AddSoftware.model_validate(LANGGRAPH),
    )
    listed = cast(dict[str, str], (await say(front, "Watch langgraph"))["already_listed"])
    assert listed["name"] == "LangGraph"
    front.answers.result = answered(WatchlistAnswer(word="releases", software="Kubernetes"))
    assert (await say(front, "Watch Kubernetes"))["already_listed"] is None


async def test_a_question_answer_comes_back_with_the_sections_it_looked_at(front: Front):
    front.answers.result = answered(
        QuestionAnswer(text="Nothing is on the watchlist yet.", looked_at=["watchlist"])
    )
    assert await say(front, "how many software are on our watchlist") == {
        "parts": [],
        "answer": "question",
        "text": "Nothing is on the watchlist yet.",
        "looked_at": ["watchlist"],
        "about_software": [],
    }


async def test_a_question_answer_names_the_watched_software_it_is_about(front: Front):
    front.answers.result = answered(
        QuestionAnswer(
            text="Redis is up to date.", looked_at=["watchlist"], about_software=["Redis"]
        )
    )
    reply = await say(front, "is redis up to date")
    assert reply["about_software"] == ["Redis"]


async def test_the_runtime_gets_the_facts_the_screens_show_for_the_signed_in_person(front: Front):
    alice = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
    await front.watchlist.add(alice, AddSoftware.model_validate(LANGGRAPH))
    front.answers.result = answered(AbilitiesAnswer())
    await say(front, "how many software are on our watchlist")
    (facts,) = front.answers.facts
    assert facts is not None and facts.watchlist is not None
    page = (await front.client.get("/api/v1/watchlist", headers=ALICE)).json()["watchlist"]
    (row,) = page["software"]
    (fact,) = facts.watchlist
    assert (fact.name, fact.repo, fact.our_version, fact.newest_version) == (
        row["name"],
        row["source"]["ref"],
        row["our_version"],
        row["newest_version"],
    )
    assert fact.state == STATUS_WORDS[row["status"]]
    assert fact.checked_at == (
        None if row["checked_at"] is None else datetime.fromisoformat(row["checked_at"])
    )
    assert (fact.open_ticket, fact.problem) == (row["open_ticket"], row["problem"])
    assert fact.awaiting_approval is (row["approval_id"] is not None)
    source = row["our_version_source"]
    assert fact.our_version_source == (None if source is None else source["kind"])
    assert fact.our_version_ticket == (None if source is None else source["ticket"])
    assert facts.needs_you is not None and facts.needs_you.total == 4
    assert [u.name for u in (await front.builder.list_use_cases()).use_cases] == [
        w.name for w in facts.workflows or []
    ]
    assert [v.user_id for v in front.home.viewers] == ["alice"]


async def test_the_facts_carry_the_watchlists_schedule_as_its_page_shows_it(front: Front):
    alice = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
    await front.watchlist.add(alice, AddSoftware.model_validate(LANGGRAPH))
    front.answers.result = answered(AbilitiesAnswer())
    await say(front, "watch React every Monday at 9am")
    (facts,) = front.answers.facts
    page = (await front.client.get("/api/v1/watchlist", headers=ALICE)).json()["watchlist"]
    assert page["schedule"] is not None
    assert facts is not None and facts.watchlist_schedule is not None
    shown = facts.watchlist_schedule
    assert (shown.day, shown.at) == (page["schedule"]["day"], page["schedule"]["at"])


async def test_a_follow_up_passes_the_previous_turn_on_and_changes_nothing_else(front: Front):
    front.answers.result = answered(WhichSoftwareAnswer(word="version"))
    previous = {
        "request": "What is the newest version of LangGraph?",
        "software": "LangGraph",
        "answer": "1.2.16.",
        "kind": "question",
    }
    r = await front.client.post(
        ANSWER, json={"text": "and Redis?", "previous": previous}, headers=ALICE
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"parts": [], "answer": "which_software", "word": "version"}
    (sent,) = front.answers.previous
    assert sent is not None and sent.model_dump() == previous


async def test_the_previous_turn_goes_with_typed_text_only(front: Front):
    body = {"intent": "abilities", "previous": {"request": "x"}}
    r = await front.client.post(ANSWER, json=body, headers=ALICE)
    assert r.status_code == 422


async def test_a_section_that_cannot_be_read_is_left_out_not_guessed(front: Front):
    async def broken(viewer: Principal) -> HomeOut:
        raise RuntimeError("down")

    front.home.for_person = broken  # type: ignore[method-assign]
    front.answers.result = answered(AbilitiesAnswer())
    await say(front)
    (facts,) = front.answers.facts
    assert facts is not None and facts.needs_you is None and facts.workflows is not None


async def test_a_watchlist_row_carries_the_rest_of_a_mixed_request(front: Front):
    rest = SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS)
    front.answers.result = answered(WatchlistAnswer(word="release", software=None, also=rest))
    reply = await say(front, "Watch releases and every Friday sum up")
    assert cast(dict[str, object], reply["also"])["answer"] == "setup_card"


async def test_the_other_kinds_come_back_as_they_were_read(front: Front):
    front.answers.result = answered(WhichSoftwareAnswer(word="version"))
    assert await say(front) == {"parts": [], "answer": "which_software", "word": "version"}
    front.answers.result = answered(RefusedAnswer(said="skip the yes", rest="close every ticket"))
    assert await say(front) == {
        "parts": [],
        "answer": "refused",
        "reason": "skip_approval",
        "said": "skip the yes",
        "rest": "close every ticket",
    }
    front.answers.result = answered(AbilitiesAnswer())
    assert await say(front) == {"parts": [], "answer": "abilities"}
    front.answers.result = answered(NeedsMeAnswer())
    assert await say(front) == {"parts": [], "answer": "needs_me"}


async def test_a_workflow_named_in_a_question_is_matched_to_the_one_that_has_the_name(front: Front):
    first = await make_workflow(front, "Morning new-ticket check")
    await make_workflow(front, "Friday summary")
    front.answers.result = answered(CheckWorkflowsAnswer(workflow_words=None))
    assert await say(front) == {"parts": [], "answer": "check_workflows", "use_case_id": None}
    front.answers.result = answered(CheckWorkflowsAnswer(workflow_words="morning new-ticket check"))
    assert (await say(front))["use_case_id"] == first
    front.answers.result = answered(WhyStoppedAnswer(workflow_words="the morning check"))
    assert (await say(front))["use_case_id"] is None
    front.answers.result = answered(WhyStoppedAnswer(workflow_words="Morning"))
    assert (await say(front))["use_case_id"] == first


async def test_two_workflows_with_a_name_in_common_match_neither(front: Front):
    await make_workflow(front, "Friday summary")
    await make_workflow(front, "Friday follow-up")
    front.answers.result = answered(WhyStoppedAnswer(workflow_words="friday"))
    assert (await say(front))["use_case_id"] is None


async def test_an_intent_never_asks_the_model_so_it_works_with_none_connected(front: Front):
    front.answers.result = NoModel()
    for intent, answer in [
        ("abilities", "abilities"),
        ("setup_ideas", "ideas"),
        ("needs_me", "needs_me"),
        ("check_workflows", "check_workflows"),
        ("why_stopped", "why_stopped"),
    ]:
        r = await front.client.post(ANSWER, json={"intent": intent}, headers=ALICE)
        assert (r.status_code, r.json()["answer"]) == (200, answer)
    assert front.answers.asked == []


async def test_why_stopped_for_a_workflow_that_does_not_exist_is_a_404(front: Front):
    r = await front.client.post(
        ANSWER, json={"intent": "why_stopped", "use_case_id": "uc_nope"}, headers=ALICE
    )
    assert (r.status_code, r.json()) == (404, {"detail": "No such workflow"})
    made = await make_workflow(front, "Friday summary")
    r = await front.client.post(
        ANSWER, json={"intent": "why_stopped", "use_case_id": made}, headers=ALICE
    )
    assert r.json() == {"parts": [], "answer": "why_stopped", "use_case_id": made}


async def test_with_no_model_the_answer_is_the_plain_offline_one_and_the_starters(front: Front):
    front.answers.result = NoModel()
    reply = await say(front)
    assert (reply["answer"], reply["why"]) == ("offline", "no_model")
    assert "No AI model is connected" in str(reply["message"])
    assert [s["name"] for s in cast(list[dict[str, str]], reply["starters"])] == [
        "Keep our software up to date",
        "Weekly summary of closed tickets",
        "Follow up stale bug tickets",
    ]


async def test_a_slow_model_gets_the_offline_answer_not_a_wait(
    front: Front, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(planner_module, "ANSWER_LIMIT_SECONDS", 0.05)
    front.answers.wait = 5
    front.answers.result = answered(AbilitiesAnswer())
    reply = await say(front)
    assert (reply["answer"], reply["why"]) == ("offline", "too_slow")


@pytest.mark.parametrize(
    ("result", "why"),
    [
        (ModelProblem(reason="too_slow", message="slow"), "too_slow"),
        (ModelProblem(reason="unusable_answer", message="bad"), "trouble"),
        (ModelProblem(reason="failed", message="broke"), "trouble"),
        (RuntimeDown("The agent runtime did not answer: ReadTimeout"), "trouble"),
    ],
)
async def test_a_broken_answer_is_the_offline_answer_never_a_guess(
    front: Front, result: AnswerResult | RuntimeDown, why: str
):
    front.answers.result = result
    reply = await say(front)
    assert (reply["answer"], reply["why"]) == ("offline", why)
    assert set(reply) == {"parts", "answer", "why", "message", "starters"}


async def test_anyone_signed_in_is_answered_and_a_blank_or_double_request_is_refused(
    front: Front,
):
    assert (await front.client.post(ANSWER, json={"text": "x"})).status_code == 401
    assert (await front.client.post(ANSWER, json={"text": " "}, headers=ALICE)).status_code == 422
    both = {"text": "x", "intent": "abilities"}
    assert (await front.client.post(ANSWER, json=both, headers=ALICE)).status_code == 422
    assert front.answers.asked == []


async def ask_as_bob(front: Front, text: str) -> dict[str, object]:
    r = await front.client.post(ANSWER, json={"text": text}, headers=BOB)
    assert r.status_code == 200, r.text
    return cast(dict[str, object], r.json())


def done(text: str) -> RequestPart:
    return RequestPart(text=text, mark="will_do")


def crossed(text: str, reason: str = "ask_on_its_own") -> RequestPart:
    return RequestPart(text=text, mark="cant", reason=reason)  # type: ignore[arg-type]


def marks(reply: dict[str, object]) -> list[tuple[object, object, object]]:
    parts = cast(list[dict[str, object]], reply["parts"])
    return [(p["text"], p["mark"], p["reason"]) for p in parts]


async def test_an_approvers_questions_get_the_runtimes_answer_as_an_operators_would(front: Front):
    front.answers.result = Answered(
        answer=NeedsMeAnswer(), parts=[done("What is waiting for my yes")]
    )
    reply = await ask_as_bob(front, "What is waiting for my yes?")
    assert reply["answer"] == "needs_me"
    assert marks(reply) == [("What is waiting for my yes", "will_do", None)]
    front.answers.result = Answered(
        answer=QuestionAnswer(
            text="LangGraph is behind.", looked_at=["watchlist"], about_software=["LangGraph"]
        ),
        parts=[done("Is LangGraph up to date")],
    )
    assert (await ask_as_bob(front, "Is LangGraph up to date?"))["text"] == "LangGraph is behind."
    front.answers.result = Answered(answer=AbilitiesAnswer(), parts=[done("What can you do")])
    assert (await ask_as_bob(front, "What can you do?"))["answer"] == "abilities"
    front.answers.result = answered(CheckWorkflowsAnswer(workflow_words=None))
    assert (await ask_as_bob(front, "How are the workflows doing?"))["answer"] == "check_workflows"


SET_UP = answered(SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS))


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("Every Friday, sum up the tickets we closed this week", SET_UP),
        ("Pause the weekly closed-ticket summary", answered(AbilitiesAnswer())),
        ("Make the morning new-ticket check run on Mondays only", answered(NeedsMeAnswer())),
        ("Watch Redis releases", answered(WatchlistAnswer(word="releases", software="Redis"))),
        ("Keep track of the React version", answered(WhichSoftwareAnswer(word="version"))),
        ("Could you make the morning check daily?", answered(CantAnswer(cant=[EMAIL]))),
        ("Email me the open bugs", answered(PartAnswer(name="x", rows=FOUR_ROWS, cant=[EMAIL]))),
    ],
)
async def test_an_approver_asking_for_any_change_gets_operators_and_never_a_card(
    front: Front, text: str, answer: Answered
):
    front.answers.result = answer
    reply = await ask_as_bob(front, text)
    assert reply["answer"] == "operators"
    assert set(reply) == {"answer", "parts"}


async def test_set_up_ideas_are_an_operators_but_an_approvers_chips_are_answered(front: Front):
    async def tap(intent: str) -> object:
        r = await front.client.post(ANSWER, json={"intent": intent}, headers=BOB)
        return r.json()["answer"]

    assert await tap("setup_ideas") == "operators"
    assert [await tap(i) for i in ("needs_me", "check_workflows", "abilities", "decided")] == [
        "needs_me",
        "check_workflows",
        "abilities",
        "decided",
    ]
    assert front.answers.asked == []


@pytest.mark.parametrize(
    ("text", "answer", "parts"),
    [
        (
            "What is waiting for my yes, and pause the morning new-ticket check",
            NeedsMeAnswer(),
            [
                done("What is waiting for my yes"),
                crossed("pause the morning new-ticket check"),
            ],
        ),
        (
            "Delete the weekly summary, then how are the workflows doing?",
            CheckWorkflowsAnswer(workflow_words=None),
            [
                crossed("Delete the weekly summary", "not_followed"),
                done("how are the workflows doing"),
            ],
        ),
        (
            "How are the workflows doing? Then delete the weekly summary",
            CheckWorkflowsAnswer(workflow_words=None),
            [done("How are the workflows doing"), done("delete the weekly summary")],
        ),
    ],
)
async def test_a_question_beside_a_change_is_answered_and_the_change_crossed_in_either_order(
    front: Front, text: str, answer: object, parts: list[RequestPart]
):
    front.answers.result = Answered(answer=answer, parts=parts)  # type: ignore[arg-type]
    reply = await ask_as_bob(front, text)
    assert reply["answer"] == answer.kind  # type: ignore[attr-defined]
    change = next(p.text for p in parts if p.text.split()[0].lower() in {"pause", "delete"})
    question = next(p.text for p in parts if p.text != change)
    assert marks(reply) == [
        (p.text, *(("will_do", None) if p.text == question else ("cant", "operators")))
        for p in parts
    ]


async def test_an_operators_question_beside_a_change_keeps_the_runtimes_marks(front: Front):
    parts = [done("What is waiting for my yes"), crossed("pause the morning new-ticket check")]
    front.answers.result = Answered(answer=NeedsMeAnswer(), parts=parts)
    reply = await say(front, "What is waiting for my yes, and pause the morning new-ticket check")
    assert marks(reply)[1] == ("pause the morning new-ticket check", "cant", "ask_on_its_own")


@pytest.mark.parametrize(
    ("text", "only"),
    [
        ("What did I decide before?", None),
        ("show my past decisions", None),
        ("did I decline anything?", "decline"),
        ("What did I approve?", "approve"),
    ],
)
async def test_an_approvers_own_decisions_are_read_from_the_whole_question(
    front: Front, text: str, only: str | None
):
    front.answers.result = Answered(answer=AbilitiesAnswer(), parts=[crossed(text, "not_followed")])
    reply = await ask_as_bob(front, text)
    assert reply == {
        "answer": "decided",
        "only": only,
        "parts": [
            {
                "text": text.rstrip("?"),
                "mark": "will_do",
                "reason": None,
                "note": None,
                "choices": [],
            }
        ],
    }


async def test_a_change_beside_a_question_about_decisions_is_crossed_for_the_operators(
    front: Front,
):
    front.answers.result = answered(AbilitiesAnswer())
    reply = await ask_as_bob(front, "What did I decide before, and pause the morning check?")
    assert reply["answer"] == "decided"
    assert marks(reply) == [
        ("What did I decide before", "will_do", None),
        ("pause the morning check", "cant", "operators"),
    ]


@pytest.mark.parametrize("text", ["approve the upgrade", "decline that request", "approve it"])
async def test_an_approve_or_decline_goes_to_the_request_whatever_it_names(front: Front, text: str):
    front.answers.result = answered(CantAnswer(cant=[EMAIL]))
    reply = await ask_as_bob(front, text)
    assert reply["answer"] == "decide"
    assert marks(reply) == [(text, "will_do", None)]


async def test_a_question_beside_an_approve_is_kept_and_asked_on_its_own(front: Front):
    front.answers.result = answered(CantAnswer(cant=[EMAIL]))
    reply = await ask_as_bob(front, "Approve the upgrade and is LangGraph up to date?")
    assert reply["answer"] == "decide"
    assert marks(reply) == [
        ("Approve the upgrade", "will_do", None),
        ("is LangGraph up to date", "cant", "ask_on_its_own"),
    ]


async def test_an_approve_beside_a_change_is_refused_whole(front: Front):
    front.answers.result = answered(NeedsMeAnswer())
    reply = await ask_as_bob(front, "approve the upgrade and pause the morning new-ticket check")
    assert reply["answer"] == "operators"
    assert marks(reply) == [
        ("approve the upgrade", "cant", "operators"),
        ("pause the morning new-ticket check", "cant", "operators"),
    ]


async def test_skipping_a_yes_and_no_model_answer_an_approver_as_anyone(front: Front):
    front.answers.result = answered(RefusedAnswer(said="automatically", rest=""))
    assert (await ask_as_bob(front, "Approve it automatically"))["answer"] == "refused"
    front.answers.result = NoModel()
    assert (await ask_as_bob(front, "What did I decide before?"))["answer"] == "offline"


CHECK = "/api/v1/planner/check-part"


async def test_one_changed_part_is_checked_by_code_with_no_model(front: Front):
    front.answers.result = NoModel()
    front.answers.part = PartCantDo(
        note="I can't email the list. I can only read Jira tickets.",
        needs="new_system",
        system="email",
    )
    r = await front.client.post(
        CHECK, json={"kind": "do", "text": " Email the list "}, headers=ALICE
    )
    assert r.json() == {
        "state": "cant_do",
        "note": "I can't email the list. I can only read Jira tickets.",
        "needs": "new_system",
        "system": "email",
    }
    assert front.answers.checked == [("do", "Email the list")]
    front.answers.part = PartFits()
    ok = await front.client.post(CHECK, json={"kind": "where", "text": "In MOCK"}, headers=ALICE)
    assert ok.json() == {"state": "fits"}


async def test_a_part_check_is_for_operators_and_says_when_the_runtime_does_not_answer(
    front: Front,
):
    body = {"kind": "do", "text": "x"}
    assert (await front.client.post(CHECK, json=body, headers=BOB)).status_code == 403
    r = await front.client.post(CHECK, json=body, headers=ALICE)
    assert (r.status_code, r.json()) == (
        503,
        {"detail": "The agent runtime did not answer. Try again in a minute."},
    )
    bad = await front.client.post(CHECK, json={"kind": "when", "text": "x"}, headers=ALICE)
    assert bad.status_code == 422


CAPABILITIES = "/api/v1/capabilities"


async def states_of(front: Front) -> dict[str, dict[str, object]]:
    r = await front.client.get(CAPABILITIES, headers=BOB)
    assert r.status_code == 200
    return {c["id"]: c for c in r.json()["capabilities"]}


async def test_the_capabilities_are_the_registry_with_its_examples(front: Front):
    r = await front.client.get(CAPABILITIES, headers=BOB)
    body = r.json()
    assert [c["id"] for c in body["capabilities"]] == [c.id for c in REGISTRY.capabilities]
    assert body["examples"] == [{"text": FRIDAY, "kind": "automate", "needs": ["jira.read"]}]
    assert (await front.client.get(CAPABILITIES)).status_code == 401


async def test_a_planned_or_unsupported_entry_keeps_the_registrys_words_whatever_the_connections(
    front: Front,
):
    front.states.checks = [
        a_check("teams", state="not_set_up", problem="No channel.", fix="Set it up")
    ]
    states = await states_of(front)
    assert states["teams.post"]["state"] == "planned"
    assert states["teams.post"]["why"] == REGISTRY.capabilities[3].why
    assert states["teams.post"]["fix"] is None
    assert (states["email.send"]["state"], states["email.send"]["cant"]) == (
        "unsupported",
        "send email",
    )


async def test_a_ready_entry_follows_the_connection_it_uses_and_the_model(front: Front):
    states = await states_of(front)
    assert {
        s["state"] for s in (states["jira.read"], states["github.releases"], states["teams.ask"])
    } == {"ready"}
    assert states["jira.read"]["last_ok_at"] == "2026-11-09T01:00:00Z"
    front.states.checks = [
        a_check("jira", state="not_answering", problem="Jira is not answering.", fix="Try again"),
        a_check("github"),
        a_check("teams", state="not_checked", checked_at=None, last_ok_at=None),
        a_check("model", state="not_set_up", problem="No AI model.", fix="Connect one in Settings"),
    ]
    states = await states_of(front)
    assert (states["jira.read"]["state"], states["jira.read"]["why"]) == (
        "down",
        "Jira is not answering.",
    )
    assert states["jira.read"]["fix"] == "Try again"
    assert states["github.releases"]["state"] == "ready"
    assert states["teams.ask"]["state"] == "ready"
    front.states.checks = [
        a_check("jira"),
        a_check("model", state="not_set_up", problem="No AI model.", fix="Connect one"),
    ]
    assert (await states_of(front))["jira.read"]["state"] == "needs_setup"
    assert (await states_of(front))["github.releases"]["state"] == "ready"


async def test_each_capability_names_the_cards_that_use_its_tools(front: Front):
    states = await states_of(front)
    assert "crd_version_checker" in cast(list[str], states["github.releases"]["agents"])
    assert states["teams.ask"]["agents"] == []


async def test_the_capabilities_say_503_when_the_runtime_has_never_answered(front: Front):
    front.registry.listed = RuntimeDown("asleep")
    r = await front.client.get(CAPABILITIES, headers=ALICE)
    assert r.status_code == 503


def test_a_long_raw_tag_is_cut_instead_of_failing_the_watchlist_fact():
    tag = "@langchain/langgraph-checkpoint-postgres@1.0.0" * 4
    fact = WatchedFact(
        name="LangGraph", repo="a/b", our_version=None, newest_version=tag, state="New version"
    )
    assert fact.newest_version == tag[:100]


def test_a_real_long_tag_is_kept_whole():
    tag = "@langchain/langgraph-checkpoint-postgres@1.0.0"
    fact = WatchedFact(name="x", repo="a/b", our_version=None, newest_version=tag, state="s")
    assert fact.newest_version == tag


LONG_AGO = datetime(2026, 10, 26, 1, 41, tzinfo=UTC)
USE_CASES = "/api/v1/use-cases"


async def last_run_of(front: Front, name: str) -> dict[str, object] | None:
    r = await front.client.get(USE_CASES, headers=ALICE)
    assert r.status_code == 200, r.text
    (row,) = [u for u in r.json()["use_cases"] if u["name"] == name]
    return cast(dict[str, object] | None, row["last_run"])


async def test_a_workflow_that_never_ran_has_no_last_run(front: Front):
    await make_workflow(front, "Never ran")
    assert await last_run_of(front, "Never ran") is None


def decided(step: int, by: str, verdict: Verdict, reason: str | None = None) -> Decision:
    return Decision(ApprovalId("apr_1"), step, UserId(by), verdict, Digest("d"), LONG_AGO, reason)


async def test_a_declined_run_names_who_declined_and_why_and_writes_nothing(front: Front):
    use_case_id = await make_workflow(front, "Declined")
    run_id = front.book.add(
        use_case_id,
        Rejected(RunId("run_1"), ProposalId("prp_1"), ApprovalId("apr_1"), UserId("bob"), 0),
        LONG_AGO,
        proposed=3,
        decisions=(decided(0, "bob", Verdict.DECLINE, "Wrong version"),),
    )
    assert await last_run_of(front, "Declined") == {
        "run_id": run_id,
        "state": "rejected",
        "at": "2026-10-26T01:41:00Z",
        "test": False,
        "declined_by": "bob",
        "decline_reason": "Wrong version",
        "approved_by": [],
        "proposed": 3,
        "written": 0,
        "tickets": True,
        "you_can_decide": False,
        "retryable": False,
        "reason": None,
    }


async def test_a_run_declined_at_the_second_step_names_who_said_yes_first(front: Front):
    use_case_id = await make_workflow(front, "Second")
    front.book.add(
        use_case_id,
        Rejected(RunId("run_1"), ProposalId("prp_1"), ApprovalId("apr_1"), UserId("alice"), 1),
        LONG_AGO,
        proposed=1,
        decisions=(decided(0, "bob", Verdict.APPROVE), decided(1, "alice", Verdict.DECLINE)),
    )
    last = await last_run_of(front, "Second")
    assert last is not None
    assert (last["declined_by"], last["approved_by"], last["decline_reason"]) == (
        "alice",
        ["bob"],
        None,
    )


async def test_a_stopped_run_is_the_last_run_with_no_one_declining(front: Front):
    use_case_id = await make_workflow(front, "Stopped")
    failure = Failure(RunFailure.AGENT_ERROR, "Jira did not answer", retryable=True)
    front.book.add(
        use_case_id,
        Failed(RunId("run_1"), Stage.WORKING, failure, ResumeWork(2)),
        LONG_AGO,
    )
    last = await last_run_of(front, "Stopped")
    assert last is not None
    assert (last["state"], last["declined_by"], last["proposed"], last["tickets"]) == (
        "failed",
        None,
        0,
        False,
    )
    assert (last["retryable"], last["reason"]) == (True, "AgentError")


async def test_a_test_run_is_the_run_the_platform_recorded_as_one(front: Front):
    use_case_id = await make_workflow(front, "Tried")
    front.book.add(
        use_case_id,
        Pending(RunId("run_1"), 1, None, LONG_AGO),
        LONG_AGO,
        trigger="person",
        test=True,
    )
    last = await last_run_of(front, "Tried")
    assert last is not None and last["test"] is True and last["state"] == "pending"


async def test_a_run_by_hand_that_was_not_a_test_is_not_one(front: Front):
    use_case_id = await make_workflow(front, "Run now")
    front.book.add(
        use_case_id,
        Pending(RunId("run_1"), 1, None, LONG_AGO),
        LONG_AGO,
        trigger="person",
        task=CardsTask(agents=()),
    )
    last = await last_run_of(front, "Run now")
    assert last is not None and last["test"] is False


async def test_a_run_a_schedule_started_is_not_a_test_run(front: Front):
    use_case_id = await make_workflow(front, "Scheduled")
    front.book.add(
        use_case_id,
        Pending(RunId("run_1"), 1, None, LONG_AGO),
        LONG_AGO,
        trigger="schedule",
        task=CardsTask(agents=()),
    )
    last = await last_run_of(front, "Scheduled")
    assert last is not None and last["test"] is False


async def test_the_newest_run_is_the_last_run_whatever_its_state(front: Front):
    use_case_id = await make_workflow(front, "Newest")
    done = Succeeded(
        RunId("run_1"),
        Outcome.WRITTEN,
        (WriteDone("jira", "create_ticket", "MOCK-1", (UserId("bob"),)),),
    )
    front.book.add(use_case_id, done, LONG_AGO + timedelta(days=7))
    front.book.add(
        use_case_id,
        AwaitingApproval(RunId("run_2"), ProposalId("prp_1"), ApprovalId("apr_2")),
        LONG_AGO,
        proposed=2,
    )
    last = await last_run_of(front, "Newest")
    assert last is not None
    assert (last["state"], last["written"], last["tickets"]) == ("succeeded", 1, True)


async def test_one_workflows_runs_are_not_another_workflows_last_run(front: Front):
    await make_workflow(front, "Quiet")
    other = await make_workflow(front, "Busy")
    front.book.add(other, Pending(RunId("run_1"), 1, None, LONG_AGO), LONG_AGO)
    assert await last_run_of(front, "Quiet") is None
    assert await last_run_of(front, "Busy") is not None


async def test_the_planner_reads_the_same_last_run_the_rows_show(front: Front):
    use_case_id = await make_workflow(front, "Same")
    front.book.add(
        use_case_id,
        Rejected(RunId("run_1"), ProposalId("prp_1"), ApprovalId("apr_1"), UserId("bob"), 0),
        LONG_AGO,
        proposed=1,
    )
    front.answers.result = answered(AbilitiesAnswer())
    await say(front)
    (facts,) = front.answers.facts
    assert facts is not None and facts.workflows is not None
    (fact,) = [w for w in facts.workflows if w.name == "Same"]
    last = await last_run_of(front, "Same")
    assert last is not None
    assert (fact.last_run, fact.last_run_at) == ("Declined", LONG_AGO)
    assert last["at"] == "2026-10-26T01:41:00Z"


async def test_builder_asks_only_for_the_workflows_it_shows(front: Front):
    first = await make_workflow(front, "One")
    await make_workflow(front, "Two")
    front.book.asked.clear()
    r = await front.client.get(f"{USE_CASES}/{first}", headers=ALICE)
    assert r.status_code == 200
    assert front.book.asked == [[first]]


async def start_over_http(
    front: Front, use_case_id: str, key: str, body: dict[str, bool] | None = None
) -> None:
    headers = {**ALICE, "Idempotency-Key": key}
    url = f"{USE_CASES}/{use_case_id}/runs"
    r = await (
        front.client.post(url, headers=headers)
        if body is None
        else front.client.post(url, headers=headers, json=body)
    )
    assert r.status_code in (200, 201), r.text


async def test_only_a_request_for_a_test_run_marks_the_run_a_test(front: Front):
    alice = Principal(UserId("alice"), frozenset({Role.OPERATOR}), "Alice")
    added = await front.watchlist.add(alice, AddSoftware.model_validate(LANGGRAPH))
    assert hasattr(added, "use_case_id")
    use_case_id = str(added.use_case_id)  # type: ignore[union-attr]
    await start_over_http(front, use_case_id, "k1")
    await start_over_http(front, use_case_id, "k2", {"test": False})
    await start_over_http(front, use_case_id, "k3", {"test": True})
    assert [spec.test for spec in front.starter.specs] == [False, False, True]


async def test_every_change_answers_for_the_person_who_made_it(front: Front):
    use_case_id = await make_workflow(front, "Changed")
    base = f"{USE_CASES}/{use_case_id}"
    changes = {
        "pause": lambda: front.client.post(f"{base}/pause", headers=ALICE),
        "resume": lambda: front.client.post(f"{base}/resume", headers=ALICE),
        "save the schedule": lambda: front.client.put(
            f"{base}/schedule", headers=ALICE, json={"day": "friday", "at": "17:30"}
        ),
        "delete": lambda: front.client.delete(base, headers=ALICE),
        "restore": lambda: front.client.post(f"{base}/restore", headers=ALICE),
    }
    for name, change in changes.items():
        front.book.viewers.clear()
        answer = await change()
        assert answer.status_code == 200, f"{name}: {answer.text}"
        if name != "delete":
            assert {v.user_id for v in front.book.viewers if v} == {"alice"}, name
            assert None not in front.book.viewers, name
