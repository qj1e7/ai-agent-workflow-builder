"""ADR 0053 item 4, the routes left after #353: a bare "check n8n for new releases", a release
check beside a change or a ticket search, and the AI-led watch tool all give the one software's
own release check card."""

from typing import Any

import pytest

from agent_runtime.answers import SkipRead, TaskRead, answer_of, parts_of
from agent_runtime.contract import (
    CantAnswer,
    PlannerFacts,
    SetupCardAnswer,
    WatchedFact,
    WatchlistAnswer,
    WatchlistScheduleFact,
)
from agent_runtime.reading import DaysRead, SearchRead, TicketRead
from tests.test_planner_led import run, shown, tool

MONDAY_9 = WatchlistScheduleFact(day="monday", at="09:00")


def read(**fields: Any) -> TaskRead:
    watch = {"belongs_on_watchlist": True, "watchlist_word": "releases", "software": "n8n"}
    return TaskRead(**{"skips_the_yes": SkipRead(whose="nobody"), **watch, **fields})


def facts(*watched: str) -> PlannerFacts:
    held = [
        WatchedFact(name=n, repo=f"x/{n}", our_version=None, newest_version=None, state="On")
        for n in watched
    ]
    return PlannerFacts(watchlist=held, watchlist_schedule=MONDAY_9, watchlist_project="MOCK")


def rows(card: SetupCardAnswer) -> dict[str, tuple[str, str]]:
    return {row.kind: (row.text, row.state) for row in card.rows}


@pytest.mark.parametrize("watched", [(), ("n8n",)], ids=["not watched", "watched"])
@pytest.mark.parametrize(
    "task",
    ["Check n8n for new releases", "please check n8n for new versions", "Track n8n releases"],
)
def test_a_bare_order_to_check_one_software_is_its_own_card(task: str, watched: tuple[str, ...]):
    answer = answer_of(read(), task, facts(*watched))
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "n8n release check"
    assert rows(answer)["look_for"] == ("New releases of n8n", "understood")
    assert rows(answer)["schedule"][1] == "missing", "a time is never guessed"


@pytest.mark.parametrize(
    "task",
    [
        "latest version of n8n",
        "Can you check the latest version of n8n?",
        "Is there a newer version of n8n?",
        "any updates for n8n",
    ],
)
def test_a_question_about_the_newest_version_keeps_its_answer(task: str):
    answer = answer_of(read(), task, facts("n8n"))
    assert isinstance(answer, WatchlistAnswer), answer


def test_a_change_beside_a_release_check_is_crossed_beside_its_own_card():
    task = "Watch Redis releases, and update Redis to 9.0.0"
    answer = answer_of(read(software="Redis"), task, facts("Redis"))
    assert isinstance(answer, CantAnswer), answer
    assert isinstance(answer.alternative, SetupCardAnswer), "never the watchlist instead"
    assert answer.alternative.name == "Redis release check"
    assert [row.text for row in answer.cant] == ["update Redis to 9.0.0"]


def test_a_change_with_no_check_keeps_the_watchlists_answer():
    task = "Change the Redis version to 9.0.0"
    answer = answer_of(read(software="Redis", watchlist_word="version"), task, facts("Redis"))
    assert isinstance(answer, CantAnswer)
    assert isinstance(answer.alternative, WatchlistAnswer)


MIXED = "Watch React releases and list stale bug tickets every Friday"
MIXED_READ: dict[str, Any] = {
    "software": "React",
    "name": "Stale bug list",
    "schedule": "every Friday",
    "search": SearchRead(
        issue_types=["bug"], updated=DaysRead(how="before", days=14), said="stale bug tickets"
    ),
    "ticket": TicketRead(creates=False, says="list", said="list"),
}


@pytest.mark.parametrize("watched", [(), ("React",)], ids=["not watched", "watched"])
def test_a_ticket_search_beside_a_release_check_is_the_rest_after_its_own_card(
    watched: tuple[str, ...],
):
    fields = read(**MIXED_READ)
    answer = answer_of(fields, MIXED, facts(*watched))
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "React release check"
    card = rows(answer)
    assert card["look_for"] == ("New releases of React", "understood")
    assert card["schedule"][1] == "missing", "Friday is the list's, never the release check's"
    assert card["where"][1] == "missing"
    rest = answer.also
    assert isinstance(rest, SetupCardAnswer), "the list is a workflow of its own"
    assert rows(rest)["look_for"][0] == "Bug tickets, with no update for 14 days"
    assert rows(rest)["schedule"] == ("Every Friday", "understood")
    marks = [(p.text, p.mark) for p in parts_of(fields, MIXED, answer)]
    assert all(mark != "cant" for _, mark in marks), marks


@pytest.mark.parametrize("watched", [(), ("LangGraph",)], ids=["not watched", "watched"])
def test_the_ai_led_watch_tool_shows_the_release_check_card(watched: tuple[str, ...]):
    task = "Every day at 9am, check LangGraph for new releases and create a Jira ticket"
    rules = read(
        software="LangGraph",
        schedule="Every day at 9am",
        ticket=TicketRead(creates=True, says="list", said="create a Jira ticket"),
    )
    result, _ = run(
        task, tool("watch_software", software="LangGraph"), read=rules, facts=facts(*watched)
    )
    answer = shown(result)
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "LangGraph release check"
