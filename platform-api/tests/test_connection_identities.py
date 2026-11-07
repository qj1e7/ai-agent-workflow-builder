"""The rule behind every connection result: Settings, Check now, the tick and Home show only what
was found with the address and key in use now. The platform is rebuilt from its settings at each
switch, as a restart does, over one database, and the systems it talks to answer over HTTP. Each
answer is logged under the address and key it reached, and that log is the only truth the
assertions use."""

import random
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import pytest

from platform_api.db import Database
from platform_api.monitoring import ActivityLog
from platform_api.orchestration.agents import GitHubWorking
from platform_api.orchestration.approvals import (
    AnyApprover,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
)
from platform_api.orchestration.connections import ConnectionCheck, Connections
from platform_api.orchestration.model_settings import SettingsState
from platform_api.orchestration.runs import Pending
from platform_api.orchestration.service import Orchestrator
from platform_api.orchestration.store import ANNOUNCE, RunRecord, Store
from platform_api.orchestration.teams import TeamsStub
from platform_api.orchestration.write_actions import Proposal, WriteAction, WriteGateway, digest
from platform_api.practice_jira import practice_token
from platform_api.settings import settings_from_env
from platform_api.shared import ApprovalId, ProposalId, RunId
from platform_api.wiring import approval_channel, connections_for, jira_for, key_hint
from tests.conftest import PostgresUrls, truncate_all
from tests.practice import PracticeKit
from tests.support import ALICE, LOCAL_ENV, SPEC, MovingClock
from tests.test_connections import FakeModels, FakeRuntime
from tests.test_orchestrator import PUBLIC_BASE_URL, FakeAgent, RecordingEngine, mint
from tests.test_settings_http import ACTIVE

pytestmark = pytest.mark.anyio

START = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
RUN = RunId("run_identities")
PRACTICE = "practice"
TEAMS_COPIES = (
    None,
    "https://teams.example/workflows/a?sig=first-signature-aaaa",
    "https://teams.example/workflows/b?sig=second-signature-bbbb",
    "https://teams.example/workflows/a?sig=regenerated-signature-cccc",
)
JIRA_COPIES = (
    None,
    ("https://jira-x.example", "first-token-for-x-k1"),
    ("https://jira-x.example", "second-token-for-x-k2"),
    ("https://jira-y.example", "first-token-for-x-k1"),
)
GITHUB_WORKING = GitHubWorking(using_token=False)
TEAMS_ANSWERS = (202, 500)
JIRA_ANSWERS = (200, 401, 503)
WAITS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=61), timedelta(hours=3))
FAILING = ("needs_attention", "not_answering")
PRACTICE_JIRA_TOKEN = practice_token(LOCAL_ENV["CALLBACK_SIGNING_KEY"])
PRACTICE_JIRA_BASE = f"{LOCAL_ENV['PLATFORM_INTERNAL_URL']}/practice-jira"

type Kind = Literal["jira", "teams"]
type Step = tuple[str, object]


@dataclass
class World:
    """What each copy answers now, and every reading the platform made of each one."""

    clock: MovingClock
    answers: dict[tuple[Kind, str], int] = field(default_factory=dict[tuple[Kind, str], int])
    readings: dict[tuple[Kind, str], list[tuple[datetime, str]]] = field(
        default_factory=dict[tuple[Kind, str], list[tuple[datetime, str]]]
    )

    def read(self, kind: Kind, copy: str, state: str) -> None:
        self.readings.setdefault((kind, copy), []).append((self.clock.now, state))

    def found(self, kind: Kind, copy: str) -> list[tuple[datetime, str]]:
        return self.readings.get((kind, copy), [])

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://teams.example/"):
            status = self.answers.get(("teams", url), 202)
            self.read("teams", url, "working" if status < 300 else "not_answering")
            return httpx.Response(status)
        base = url.split("/rest/", 1)[0]
        token = request.headers["Authorization"].removeprefix("Bearer ")
        copy = jira_copy(base, token)
        status = self.answers.get(("jira", copy), 200)
        states = {200: "working", 401: "needs_attention"}
        self.read("jira", copy, states.get(status, "not_answering"))
        return httpx.Response(status, json={"name": "platform"} if status == 200 else {})


def jira_copy(base: str, token: str) -> str:
    return PRACTICE if (base, token) == (PRACTICE_JIRA_BASE, PRACTICE_JIRA_TOKEN) else base + token


@dataclass
class Platform:
    """The parts the wiring builds from one set of settings."""

    connections: Connections
    orchestrator: Orchestrator
    teams: str
    jira: str
    jira_hint: str | None


@dataclass
class Walk:
    db: Database
    world: World
    client: httpx.AsyncClient
    platform: Platform | None = None
    teams_copy: str | None = None
    jira_copy: tuple[str, str] | None = None
    sent: int = 0
    situations: int = 0

    @property
    def now(self) -> Platform:
        assert self.platform is not None
        return self.platform

    def build(self) -> None:
        env = dict(LOCAL_ENV)
        if self.teams_copy is not None:
            env["TEAMS_WEBHOOK_URL"] = self.teams_copy
        if self.jira_copy is not None:
            env["JIRA_BASE_URL"], env["JIRA_API_TOKEN"] = self.jira_copy
        settings = settings_from_env(env)
        jira, _ = jira_for(settings, self.db, self.client)
        channel, _ = approval_channel(settings, TeamsStub(self.db, "Ops"), self.client)
        connections, channel = connections_for(
            settings,
            self.db,
            jira,
            channel,
            FakeRuntime(GITHUB_WORKING),
            FakeModels(SettingsState(True, ACTIVE, None, [])),
        )
        orchestrator = Orchestrator(
            self.db,
            ActivityLog(self.db),
            RecordingEngine(),
            channel,
            FakeAgent(),
            WriteGateway(self.db, [PracticeKit(self.db)], poll=0.05),
            mint,
            public_base_url=PUBLIC_BASE_URL,
        )
        self.platform = Platform(
            connections,
            orchestrator,
            self.teams_copy or PRACTICE,
            PRACTICE if self.jira_copy is None else "".join(self.jira_copy),
            None if self.jira_copy is None else key_hint(self.jira_copy[1]),
        )

    def copy_of(self, kind: Kind) -> str:
        return self.now.teams if kind == "teams" else self.now.jira

    async def step(self, action: str, value: object) -> None:
        self.world.clock.now += value if isinstance(value, timedelta) else timedelta(seconds=1)
        if self.now.teams == PRACTICE:
            self.world.read("teams", PRACTICE, "working")
        match action:
            case "teams":
                self.teams_copy = TEAMS_COPIES[int(str(value))]
                self.build()
            case "jira":
                self.jira_copy = JIRA_COPIES[int(str(value))]
                self.build()
            case "teams_answers":
                self.world.answers[("teams", self.now.teams)] = int(str(value))
            case "jira_answers":
                self.world.answers[("jira", self.now.jira)] = int(str(value))
            case "send":
                await self.send()
            case "outbox":
                await self.now.orchestrator.tick()
            case "view":
                for check in await self.now.connections.view():
                    self.holds(check, "the view")
            case "check_now":
                kind: Kind = "teams" if value == "teams" else "jira"
                check = await self.now.connections.check_now(kind)
                assert check is not None
                self.holds(check, "Check now")
                if kind == "jira":
                    assert self.world.found("jira", self.now.jira)[-1][0] == self.world.clock.now, (
                        "Check now asks Jira"
                    )
            case "tick":
                failing = [c.id for c in await self.now.connections.needing_attention()]
                await self.now.connections.check_due()
                if "jira" in failing:
                    assert self.world.found("jira", self.now.jira)[-1][0] == self.world.clock.now, (
                        "a tick checks a failing Jira again"
                    )
                for check in await self.now.connections.view():
                    self.holds(check, "the view after a tick")
            case "home":
                for check in await self.now.connections.needing_attention():
                    self.holds(check, "Home")
                    assert check.state in FAILING, "Home raises only what does not work"
            case "wait":
                pass
            case _:
                raise AssertionError(action)

    def holds(self, check: ConnectionCheck, where: str) -> None:
        """What `where` shows for a connection came from a reading of the copy in use now."""
        if check.id not in ("jira", "teams"):
            return
        kind: Kind = "teams" if check.id == "teams" else "jira"
        copy = self.copy_of(kind)
        found = self.world.found(kind, copy)
        said = f"{where} for {kind} on {copy!r}: {check.state} checked {check.checked_at}"
        self.situations += 1
        assert check.practice == (copy == PRACTICE), said
        if check.state == "not_checked":
            assert (check.checked_at, check.last_ok_at) == (None, None), said
            assert found == [], f"{said}, though it was tried: {found}"
            return
        assert found, f"{said}, though nothing was tried with this copy"
        assert (check.checked_at, check.state) in found, f"{said} is no reading of it: {found}"
        if check.last_ok_at is not None:
            assert (check.last_ok_at, "working") in found, f"{said} last worked at another copy"
        if kind == "jira":
            assert check.key_ends_in in (None, self.now.jira_hint), f"{said} with another key"

    async def send(self) -> None:
        """An approval request posted through the outbox, as a run asks for one."""
        self.sent += 1
        store = Store()
        approval = ApprovalId(f"apr_id{self.sent}")
        action = WriteAction("jira", "create_ticket", {"project": "MOCK"}, {"title": "t"})
        proposal = Proposal(ProposalId(f"prp_id{self.sent}"), RUN, (action,), digest((action,)))
        request = ApprovalRequest(
            approval,
            RUN,
            proposal.id,
            proposal.digest,
            ApprovalPolicy((ApprovalStep("Team approver", AnyApprover()),)),
            frozenset({ALICE.user_id}),
        )
        payload = {
            "approval_id": approval,
            "run_id": RUN,
            "use_case_name": SPEC.use_case_name,
            "actions": ["create a Jira ticket"],
            "link": f"/approvals/{approval}",
        }
        async with self.db.transaction("orchestration") as uow:
            await store.insert_proposal(uow, proposal)
            await store.insert_approval(uow, request)
            await store.enqueue(uow, RUN, ANNOUNCE, payload, uow.now)
        await self.now.orchestrator.tick()


SCRIPTED: list[Step] = [
    ("view", None),
    ("check_now", "jira"),
    ("tick", None),
    ("home", None),
    ("teams", 1),
    ("jira", 1),
    ("view", None),
    ("send", None),
    ("teams", 2),
    ("view", None),
    ("check_now", "teams"),
    ("home", None),
    ("jira_answers", 401),
    ("check_now", "jira"),
    ("home", None),
    ("jira", 2),
    ("view", None),
    ("check_now", "jira"),
    ("home", None),
    ("teams", 1),
    ("view", None),
    ("teams_answers", 500),
    ("send", None),
    ("view", None),
    ("home", None),
    ("teams", 3),
    ("view", None),
    ("jira", 3),
    ("jira_answers", 503),
    ("check_now", "jira"),
    ("jira_answers", 200),
    ("wait", timedelta(minutes=5)),
    ("tick", None),
    ("tick", None),
    ("view", None),
    ("jira", 1),
    ("view", None),
    ("teams", 0),
    ("jira", 0),
    ("view", None),
    ("tick", None),
    ("home", None),
]


def generated(seed: int, length: int = 40) -> Iterator[Step]:
    pick = random.Random(seed)
    makers: list[Callable[[], Step]] = [
        lambda: ("teams", pick.randrange(len(TEAMS_COPIES))),
        lambda: ("jira", pick.randrange(len(JIRA_COPIES))),
        lambda: ("teams_answers", pick.choice(TEAMS_ANSWERS)),
        lambda: ("jira_answers", pick.choice(JIRA_ANSWERS)),
        lambda: ("send", None),
        lambda: ("outbox", None),
        lambda: ("view", None),
        lambda: ("check_now", pick.choice(("jira", "teams"))),
        lambda: ("tick", None),
        lambda: ("home", None),
        lambda: ("wait", pick.choice(WAITS)),
    ]
    for _ in range(length):
        yield pick.choice(makers)()


@pytest.fixture
async def walk(postgres: PostgresUrls) -> AsyncIterator[Walk]:
    truncate_all(postgres.owner)
    clock = MovingClock(START)
    db = Database(postgres.contexts, clock=clock)
    await db.open()
    world = World(clock)
    client = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    store = Store()
    async with db.transaction("orchestration") as uow:
        pending = Pending(RUN, 1, None, START)
        await store.insert_run(
            uow, RunRecord(RUN, SPEC, ALICE.user_id, START, START, 1, pending, (), None), "k"
        )
    try:
        walk = Walk(db, world, client)
        walk.build()
        yield walk
    finally:
        await client.aclose()
        await db.close()


@pytest.mark.parametrize("seed", ["scripted", *range(12)])
async def test_every_screen_shows_only_what_the_copy_in_use_now_was_found_to_do(
    walk: Walk, seed: str | int
):
    steps = SCRIPTED if seed == "scripted" else list(generated(int(seed)))
    for number, (action, value) in enumerate(steps):
        try:
            await walk.step(action, value)
        except AssertionError as error:
            done = ", ".join(f"{a}={v}" for a, v in steps[: number + 1])
            raise AssertionError(f"seed {seed}, step {number + 1} of: {done}\n{error}") from None
    print(f"seed {seed}: {len(steps)} steps, {walk.situations} results checked")
