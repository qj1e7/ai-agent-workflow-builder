"""Each typed turn's trace (ADR 0050): the platform makes its id, the runtime is told it with the
chat and a pseudonym for the person, and the next message flags it when it came within 60 s."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from platform_api.builder import PlannerFront
from platform_api.builder.models import CardList, UseCaseList, Via
from platform_api.db import Database
from platform_api.monitoring import LangfuseScores, TraceFlag, TraceIds, pseudonym
from platform_api.orchestration import CapabilityList, ConnectionCheck, PlannerFacts
from platform_api.orchestration.agents import HttpAgentRuntime, ModelAccess, PlatformReady
from platform_api.orchestration.planning import PlannerAnswers
from platform_api.shared import Principal, UserId
from tests.declared import ALICE, BOB, app_with
from tests.support import FIXTURES

pytestmark = pytest.mark.anyio

ANSWER = "/api/v1/planner/answer"
KEY = "pseudonym-key-not-real"
CHAT = "5f0c2a7e-3b1d-4e8f-9a6c-2d4b7e1f0a93"
QUESTION = json.loads((FIXTURES / "agent" / "planner-answered-question.json").read_text())
CARD = json.loads((FIXTURES / "agent" / "planner-answered-card.json").read_text())


def trace_made(ago: timedelta, person: str = "alice") -> str:
    """A trace id as the platform made it for `person`, `ago` before now."""
    return TraceIds(KEY.encode()).new(UserId(person), datetime.now(UTC) - ago)


@dataclass
class Runtime:
    """The agent runtime's Planner route, answering every request with one of its fixtures."""

    answered: dict[str, Any] = field(default_factory=lambda: QUESTION)
    seen: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(json.loads(request.content))
        return httpx.Response(200, json=self.answered)


class OneModel:
    async def access(self, uow: object) -> ModelAccess:
        return ModelAccess(
            style="anthropic", base_url="https://llm.example", model="m", api_key="k-not-real"
        )


class NoDatabase:
    @asynccontextmanager
    async def transaction(self, context: str) -> AsyncIterator[None]:
        yield None


class NoWorkflows:
    async def list_use_cases(self) -> UseCaseList:
        return UseCaseList(use_cases=[])

    async def get_use_case(self, use_case_id: str) -> None:
        return None

    async def list_cards(self) -> CardList:
        return CardList(cards=[])

    async def pause_use_case(self, use_case_id: str, principal: Principal, via: Via) -> None:
        return None

    async def resume_use_case(self, use_case_id: str, principal: Principal, via: Via) -> None:
        return None


class Quiet:
    async def view(self) -> Any:
        return None

    async def get(self) -> CapabilityList:
        return CapabilityList(capabilities=[], examples=[])

    async def read(self, viewer: Principal, request: str) -> PlannerFacts:
        return PlannerFacts()


class NoConnections:
    async def view(self) -> list[ConnectionCheck]:
        return []


@dataclass
class Flags:
    sent: list[TraceFlag] = field(default_factory=list[TraceFlag])

    def send(self, flag: TraceFlag) -> None:
        self.sent.append(flag)

    async def close(self) -> None:
        return None


@dataclass
class Home:
    client: httpx.AsyncClient
    runtime: Runtime


@asynccontextmanager
async def home(
    scores: Any = None, pseudonym_key: str | None = KEY, runtime: Runtime | None = None
) -> AsyncIterator[Home]:
    runtime = runtime or Runtime()
    agents = HttpAgentRuntime(
        "http://agent-runtime:8100",
        "agent-key-not-real",
        client=httpx.AsyncClient(transport=httpx.MockTransport(runtime.handle)),
    )
    answers = PlannerAnswers(cast(Database, NoDatabase()), OneModel(), agents)
    quiet = Quiet()
    front = PlannerFront(
        answers,
        NoWorkflows(),
        quiet,
        quiet,
        NoConnections(),
        quiet,
        scores=scores if scores is not None else Flags(),
        pseudonym_key=pseudonym_key,
    )
    transport = httpx.ASGITransport(app=app_with(planner_front=front))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Home(client, runtime)


async def ask(home: Home, body: dict[str, Any], who: dict[str, str] = ALICE) -> dict[str, Any]:
    r = await home.client.post(ANSWER, json=body, headers=who)
    assert r.status_code == 200, r.text
    return cast(dict[str, Any], r.json())


async def test_the_runtime_is_told_the_turns_trace_its_chat_and_a_pseudonym_never_the_person():
    async with home() as h:
        reply = await ask(h, {"text": "how many software are on our watchlist", "chat": CHAT})
    (sent,) = h.runtime.seen
    trace = sent["trace"]
    alice = pseudonym(KEY, UserId("alice"))
    assert trace == {"id": reply["trace_id"], "chat": CHAT, "person": alice}
    assert len(trace["id"]) == 32 and int(trace["id"], 16)
    assert "alice" not in json.dumps(trace)


async def test_each_typed_message_gets_its_own_trace():
    async with home() as h:
        first = await ask(h, {"text": "how many software are on our watchlist", "chat": CHAT})
        second = await ask(h, {"text": "and which are behind?", "chat": CHAT})
    assert first["trace_id"] != second["trace_id"]
    assert [s["trace"]["id"] for s in h.runtime.seen] == [first["trace_id"], second["trace_id"]]


async def test_without_a_pseudonym_key_the_trace_names_nobody():
    async with home(pseudonym_key=None) as h:
        await ask(h, {"text": "how many software are on our watchlist"})
    (sent,) = h.runtime.seen
    assert sent["trace"]["person"] is None and sent["trace"]["chat"] is None


async def test_the_previous_turns_trace_id_is_not_passed_to_the_runtime():
    previous = {"request": "What is LangGraph at?", "software": "LangGraph", "answer": "1.2.16."}
    async with home() as h:
        await ask(
            h,
            {
                "text": "and Redis?",
                "previous": {**previous, "kind": "question", "trace_id": trace_made(timedelta(0))},
            },
        )
    (sent,) = h.runtime.seen
    assert sent["previous"] == {**previous, "kind": "question"}


async def test_an_answer_the_runtime_never_gave_carries_no_trace():
    async with home() as h:
        chip = await ask(h, {"intent": "abilities", "chat": CHAT})
        n8n = await ask(h, {"text": "open the release check in n8n", "chat": CHAT})
    assert (chip["trace_id"], n8n["trace_id"]) == (None, None)
    assert h.runtime.seen == []


async def test_someone_who_isnt_an_operator_keeps_the_trace_of_the_turn_the_runtime_read():
    async with home(runtime=Runtime(answered=CARD)) as h:
        reply = await ask(h, {"text": "every Friday sum up the closed tickets"}, who=BOB)
    (sent,) = h.runtime.seen
    assert reply["answer"] == "operators" and reply["trace_id"] == sent["trace"]["id"]


@pytest.mark.parametrize(
    ("made", "flagged"),
    [
        pytest.param(lambda: trace_made(timedelta(seconds=59)), True, id="59 s"),
        pytest.param(lambda: trace_made(timedelta(seconds=61)), False, id="61 s"),
        pytest.param(lambda: trace_made(timedelta(seconds=-30)), False, id="from the future"),
        pytest.param(lambda: uuid4().hex, False, id="not a trace the platform made"),
        pytest.param(
            lambda: trace_made(timedelta(seconds=5), "bob"), False, id="someone else's trace"
        ),
    ],
)
async def test_typing_again_within_a_minute_flags_the_earlier_turn(
    made: Callable[[], str], flagged: bool
):
    flags = Flags()
    trace_id = made()
    previous = {"request": "watch it", "kind": "reply_clarify", "trace_id": trace_id}
    async with home(scores=flags) as h:
        await ask(h, {"text": "Redis", "chat": CHAT, "previous": previous})
    sent = [(f.score_id, f.trace_id, f.name) for f in flags.sent]
    expected = [(f"{trace_id}-flag_typed_again", trace_id, "flag_typed_again")]
    assert sent == (expected if flagged else [])


async def test_a_trace_id_that_is_not_32_hex_digits_is_refused():
    previous = {"request": "watch it", "trace_id": "not-a-trace"}
    async with home() as h:
        r = await h.client.post(ANSWER, json={"text": "Redis", "previous": previous}, headers=ALICE)
    assert r.status_code == 422


async def test_a_chat_that_is_not_a_uuid_is_refused():
    async with home() as h:
        r = await h.client.post(ANSWER, json={"text": "Redis", "chat": "chat 1"}, headers=ALICE)
    assert r.status_code == 422


async def test_langfuse_down_or_slow_never_holds_up_or_changes_the_answer():
    release = asyncio.Event()
    tried: list[httpx.Request] = []

    async def stuck_then_down(request: httpx.Request) -> httpx.Response:
        tried.append(request)
        await release.wait()
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(stuck_then_down))
    scores = LangfuseScores("http://langfuse-web:3000", "pk", "sk", None, client)
    previous = {"request": "what can you do", "trace_id": trace_made(timedelta(seconds=5))}
    async with home(scores=scores) as h, asyncio.timeout(5):
        quiet = await ask(h, {"text": "how many software are on our watchlist"})
        flagged = await ask(
            h, {"text": "how many software are on our watchlist", "previous": previous}
        )
    await asyncio.sleep(0)
    assert len(tried) == 1, "the answer came back while the write still waited on Langfuse"
    release.set()
    await scores.close()
    assert {**flagged, "trace_id": None} == {**quiet, "trace_id": None}
    assert flagged["answer"] == "question" and flagged["trace_id"] is not None


@pytest.mark.parametrize("pseudonym_key", [KEY, None])
async def test_the_answers_own_trace_id_sent_back_at_once_flags_that_turn(
    pseudonym_key: str | None,
):
    flags = Flags()
    async with home(scores=flags, pseudonym_key=pseudonym_key) as h:
        first = await ask(h, {"text": "how many software are on our watchlist", "chat": CHAT})
        previous = {
            "request": "how many software",
            "kind": "question",
            "trace_id": first["trace_id"],
        }
        await ask(h, {"text": "and on Monday?", "chat": CHAT, "previous": previous})
        await ask(h, {"text": "and Tuesday?", "chat": CHAT, "previous": previous}, who=BOB)
    assert [f.trace_id for f in flags.sent] == [first["trace_id"]]


@pytest.mark.parametrize("ready_here", [(), ("workflows.simulate",)])
async def test_the_runtime_is_told_what_the_platform_turned_on_here(
    ready_here: tuple[PlatformReady, ...],
):
    """So the Planner's prompts call Simulation mode Ready only where there is a simulation n8n
    (ADR 0054, PR 7)."""
    runtime = Runtime()
    agents = HttpAgentRuntime(
        "http://agent-runtime:8100",
        "agent-key-not-real",
        client=httpx.AsyncClient(transport=httpx.MockTransport(runtime.handle)),
    )
    answers = PlannerAnswers(
        cast(Database, NoDatabase()), OneModel(), agents, ready_here=ready_here
    )

    await answers.answer("how many software are on our watchlist")

    (sent,) = runtime.seen
    assert sent["ready_here"] == list(ready_here)
