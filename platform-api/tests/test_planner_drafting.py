"""Starting a draft from the chat (ADR 0051, flow step 1): the words "draft an n8n workflow that
..." start one, read by code before any model, and a can't or a part card offers Draft it as an
n8n workflow. Only an Operator may draft, and the drafter never starts without the tap or the
words."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import httpx
import pytest

from platform_api.app import create_app
from platform_api.auth import DEV_PEOPLE
from platform_api.builder import Builder, PlannerFront, Watchlist
from platform_api.builder.drafted_workflows import KEY_PASTED, DraftedWorkflows
from platform_api.builder.planner_facts import PlannerFactsReader
from platform_api.db import Database
from platform_api.orchestration import (
    Answered,
    CantAnswer,
    CantRow,
    RequestPart,
    ScheduleBook,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.shared import TEAM_TIME_ZONE
from tests.support import LOCAL_ENV
from tests.test_builder_http import (
    ANSWER,
    REGISTRY,
    FakeAnswers,
    FakeHome,
    FakeRegistry,
    FakeStates,
    NothingLearned,
    RunBook,
    SecondCallRepeats,
    a_check,
)
from tests.test_drafted_workflows import WORDS, Drafter, Facts, N8n
from tests.test_setup_approvals import Channel

pytestmark = pytest.mark.anyio

EMAIL = "Every Monday email the release notes to the team"


@dataclass
class Chat:
    client: httpx.AsyncClient
    answers: FakeAnswers
    drafter: Drafter
    drafted: DraftedWorkflows

    async def say(self, user: str, text: str) -> dict[str, object]:
        r = await self.client.post(ANSWER, json={"text": text}, headers={"X-Dev-User": user})
        assert r.status_code == 200, r.text
        return cast(dict[str, object], r.json())


@pytest.fixture
async def chat(db: Database) -> AsyncIterator[Chat]:
    people = People(db)
    assert await people.seed_dev(DEV_PEOPLE)
    app = create_app(LOCAL_ENV)
    watchlist = Watchlist(db, NothingLearned(), ScheduleBook(db))
    builder = Builder(
        db, SecondCallRepeats(), watchlist, "http://localhost:8000", history=RunBook()
    )
    drafter = Drafter()
    approvals = SetUpApprovals(db, Channel(), people, "https://portal.example", TEAM_TIME_ZONE)
    drafted = DraftedWorkflows(
        db, drafter, approvals, Facts(), N8n(), "https://portal.example", TEAM_TIME_ZONE.key
    )
    answers = FakeAnswers()
    states = FakeStates(a_check("jira"), a_check("github"), a_check("teams"), a_check("model"))
    app.state.people = people
    app.state.builder = builder
    app.state.watchlist = watchlist
    app.state.drafted = drafted
    app.state.planner_front = PlannerFront(
        answers,
        builder,
        watchlist,
        FakeRegistry(REGISTRY),
        states,
        PlannerFactsReader(watchlist, builder, FakeHome()),
        drafted=drafted,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Chat(client, answers, drafter, drafted)
        await drafted.settle()


async def test_an_operator_s_words_start_a_draft_before_any_model_reads_them(chat: Chat):
    reply = await chat.say("carol", WORDS)
    await chat.drafted.settle()

    assert reply["answer"] == "draft_started" and reply["refused"] is None
    assert chat.answers.asked == [], "the Planner's model never saw the words"
    [(words, _, _)] = chat.drafter.asked
    assert words == WORDS
    view = await chat.drafted.view(str(reply["drafted_id"]))
    assert view is not None and view.state == "draft"


async def test_an_approver_s_words_start_nothing(chat: Chat):
    reply = await chat.say("bob", WORDS)

    assert reply["answer"] == "operators"
    assert chat.drafter.asked == []


async def test_a_pasted_key_starts_nothing(chat: Chat):
    reply = await chat.say("carol", "Draft an n8n workflow that uses sk-ant-api03-abcdefghijkl")

    assert (reply["answer"], reply["drafted_id"], reply["refused"]) == (
        "draft_started",
        None,
        KEY_PASTED,
    )
    assert chat.drafter.asked == []


async def test_words_that_name_a_yes_go_to_the_planner_first(chat: Chat):
    chat.answers.result = Answered(
        answer=CantAnswer(cant=[CantRow(kind="do", text="skip the yes", note="No.")]),
        parts=[RequestPart(text="x", mark="cant", reason="cant_do")],
    )

    await chat.say("carol", "Draft an n8n workflow that closes tickets and skip the yes")

    assert chat.drafter.asked == []


@pytest.mark.parametrize(("user", "offered"), [("carol", True), ("bob", False)])
async def test_a_can_t_offers_draft_it_only_to_an_operator(chat: Chat, user: str, offered: bool):
    chat.answers.result = Answered(
        answer=CantAnswer(
            cant=[
                CantRow(
                    kind="do",
                    text="email the release notes",
                    note="I can't send email yet.",
                    needs="new_system",
                    system="email",
                )
            ]
        ),
        parts=[RequestPart(text=EMAIL, mark="cant", reason="cant_do")],
    )

    reply = await chat.say(user, EMAIL)

    assert reply.get("draft_words") == (EMAIL if offered else None)
    assert chat.drafter.asked == [], "the offer starts nothing until it is tapped"


async def test_a_can_t_the_platform_refuses_outright_offers_no_draft(chat: Chat):
    chat.answers.result = Answered(
        answer=CantAnswer(
            cant=[CantRow(kind="do", text="text me", note="Not on the plan.", unsupported=True)]
        ),
        parts=[RequestPart(text="text me", mark="cant", reason="cant_do")],
    )

    reply = await chat.say("carol", "text me the results")

    assert reply["draft_words"] is None
