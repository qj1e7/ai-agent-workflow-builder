"""Starting a draft from the chat (ADR 0051, flow step 1, and ADR 0053, item 5): the words "draft
an n8n workflow that ..." start one, read by code before any model. A can't our blocks don't cover
at all goes to the drafter, so the person never picks a path, and every other card offers Build it
with any n8n block. Only an Operator may draft."""

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
    PartAnswer,
    RequestPart,
    ScheduleBook,
    SetupCardAnswer,
    WatchlistAnswer,
)
from platform_api.orchestration.people_store import People
from platform_api.orchestration.setup_approvals import SetUpApprovals
from platform_api.shared import TEAM_TIME_ZONE
from tests.support import LOCAL_ENV
from tests.test_builder_http import (
    ANSWER,
    FOUR_ROWS,
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


EMAIL_ROW = CantRow(
    kind="do",
    text="email the release notes",
    note="I can't send email yet.",
    needs="new_system",
    system="email",
)


async def test_a_can_t_our_blocks_don_t_cover_goes_to_the_drafter_for_an_operator(chat: Chat):
    """The Planner picks how to build it: nothing of ours covers email, so the drafter starts on
    the words unchanged, with no button to press first (ADR 0053, item 5)."""
    chat.answers.result = Answered(
        answer=CantAnswer(cant=[EMAIL_ROW]),
        parts=[RequestPart(text=EMAIL, mark="cant", reason="cant_do")],
    )

    reply = await chat.say("carol", EMAIL)
    await chat.drafted.settle()

    assert reply["answer"] == "draft_started" and reply["refused"] is None
    [(words, _, _)] = chat.drafter.asked
    assert words == EMAIL
    view = await chat.drafted.view(str(reply["drafted_id"]))
    assert view is not None and view.state == "draft"


async def test_an_approver_s_can_t_starts_nothing_and_offers_nothing(chat: Chat):
    chat.answers.result = Answered(
        answer=CantAnswer(cant=[EMAIL_ROW]),
        parts=[RequestPart(text=EMAIL, mark="cant", reason="cant_do")],
    )

    reply = await chat.say("bob", EMAIL)

    assert reply["answer"] == "operators" and reply.get("draft_words") is None
    assert chat.drafter.asked == []


async def test_a_can_t_with_something_close_keeps_it_and_offers_the_drafter(chat: Chat):
    """Our blocks offer something close, so the card stays and Build it with any n8n block sends
    the words unchanged when it is pressed."""
    words = "Check LangGraph for new releases every weekday at 9"
    chat.answers.result = Answered(
        answer=CantAnswer(
            cant=[
                CantRow(
                    kind="schedule",
                    text="every weekday at 9",
                    note="The Software watchlist checks all your software together, on one "
                    "schedule. I can't give one software its own time yet.",
                    needs="new_tool",
                )
            ],
            alternative=WatchlistAnswer(word="releases", software="LangGraph"),
        ),
        parts=[RequestPart(text="every weekday at 9", mark="cant", reason="own_time")],
    )

    reply = await chat.say("carol", words)

    assert reply["answer"] == "cant" and reply["draft_words"] == words
    assert chat.drafter.asked == [], "nothing is drafted until the link is pressed"


async def test_a_part_the_planner_didn_t_follow_starts_nothing(chat: Chat):
    """A clause the Planner didn't follow names nothing to build, so it is never sent on its own
    to the drafter. The link still offers it."""
    words = "Check LangGraph, but only the major releases"
    chat.answers.result = Answered(
        answer=CantAnswer(
            cant=[
                CantRow(
                    kind="look_for",
                    text="only the major releases",
                    note="I didn't follow this part.",
                )
            ]
        ),
        parts=[RequestPart(text="only the major releases", mark="cant", reason="not_followed")],
    )

    reply = await chat.say("carol", words)

    assert reply["answer"] == "cant" and reply["draft_words"] == words
    assert chat.drafter.asked == []


@pytest.mark.parametrize(
    "answer",
    [
        SetupCardAnswer(name="Friday summary", rows=FOUR_ROWS),
        PartAnswer(name="Friday summary", rows=FOUR_ROWS, cant=[EMAIL_ROW]),
    ],
    ids=["setup_card", "part"],
)
async def test_a_card_from_our_blocks_offers_build_it_with_any_n8n_block(
    chat: Chat, answer: SetupCardAnswer | PartAnswer
):
    words = "Every Friday, sum up the tickets we closed this week"
    chat.answers.result = Answered(answer=answer, parts=[RequestPart(text=words, mark="will_do")])

    reply = await chat.say("carol", words)

    assert reply["answer"] == answer.kind and reply["draft_words"] == words
    assert chat.drafter.asked == [], "nothing is drafted until the link is pressed"
    chat.answers.result = Answered(answer=answer, parts=[RequestPart(text=words, mark="will_do")])
    assert (await chat.say("bob", words)).get("draft_words") is None


async def test_a_can_t_the_platform_refuses_outright_offers_no_draft(chat: Chat):
    chat.answers.result = Answered(
        answer=CantAnswer(
            cant=[CantRow(kind="do", text="text me", note="Not on the plan.", unsupported=True)]
        ),
        parts=[RequestPart(text="text me", mark="cant", reason="cant_do")],
    )

    reply = await chat.say("carol", "text me the results")

    assert reply["draft_words"] is None


async def test_the_same_words_sent_twice_in_a_row_start_one_draft(chat: Chat):
    first = await chat.say("carol", WORDS)
    again = await chat.say("carol", WORDS)
    await chat.drafted.settle()

    assert first["drafted_id"] == again["drafted_id"]
    assert len(chat.drafter.asked) == 1
