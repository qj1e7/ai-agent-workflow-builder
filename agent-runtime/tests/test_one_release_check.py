"""ADR 0053 item 4: a request to check one software gets its own release check workflow, with
its own schedule and Jira project, even when the software is on the Software watchlist."""

from typing import Any

import pytest

from agent_runtime.abilities import why_not
from agent_runtime.answers import SkipRead, TaskRead, answer_of, decide, parts_of
from agent_runtime.contract import (
    CantAnswer,
    PlannerFacts,
    SetupCardAnswer,
    WatchedFact,
    WatchlistAnswer,
    WatchlistScheduleFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.reading import FILLED_IN, PlaceRead, SearchRead, TicketRead

THE_REQUEST = "Every day at 9am, check LangGraph for new releases and create a Jira ticket"
"""The prototype's "New release check" request."""
MONDAY_9 = WatchlistScheduleFact(day="monday", at="09:00")
TICKET = TicketRead(creates=True, says="list", said="create a Jira ticket")


def read(**fields: Any) -> TaskRead:
    watch = {"belongs_on_watchlist": True, "watchlist_word": "releases", "software": "LangGraph"}
    return TaskRead(**{"skips_the_yes": SkipRead(whose="nobody"), **watch, **fields})


def facts(*watched: str) -> PlannerFacts:
    held = [
        WatchedFact(name=n, repo=f"x/{n}", our_version=None, newest_version=None, state="On")
        for n in watched
    ]
    return PlannerFacts(watchlist=held, watchlist_schedule=MONDAY_9, watchlist_project="MOCK")


def rows(answer: SetupCardAnswer) -> dict[str, tuple[str, str, str | None]]:
    return {row.kind: (row.text, row.state, row.note) for row in answer.rows}


@pytest.mark.parametrize("watched", [(), ("LangGraph", "n8n")], ids=["not watched", "watched"])
@pytest.mark.parametrize("ticket", [TICKET, None], ids=["ticket read", "ticket not read"])
def test_a_release_check_of_one_software_is_a_card_of_its_own(
    watched: tuple[str, ...], ticket: TicketRead | None
):
    fields = read(schedule="Every day at 9am", ticket=ticket)
    answer = answer_of(fields, THE_REQUEST, facts(*watched))
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "LangGraph release check"
    card = rows(answer)
    assert card["schedule"][:2] == ("Every day at 9am", "understood"), "its own time, no can't"
    assert card["look_for"] == (
        "LangGraph releases on GitHub",
        "understood",
        'Read from your words "LangGraph".',
    )
    assert card["do"] == (
        "Create one ticket that lists them",
        "understood",
        'Read from your words "create a Jira ticket".',
    )
    assert card["where"][1] == "missing", "it asks for a Jira project of its own"
    assert "MOCK" not in answer.model_dump_json(), "never the watchlist's project"
    assert why_not("look_for", card["look_for"][0]) is None, "the card's own check accepts it"
    assert all(p.mark != "cant" for p in parts_of(fields, THE_REQUEST, answer))


def test_the_watchlists_own_schedule_and_ticket_are_its_own_too():
    task = "Every Monday, check LangGraph for a new release and create a Jira ticket"
    fields = read(watchlist_word="release", schedule="Every Monday", ticket=TICKET)
    answer = answer_of(fields, task, facts("LangGraph"))
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == "LangGraph release check"
    assert rows(answer)["schedule"][0] == "Every Monday"


@pytest.mark.parametrize("project", ["OPS", "MOCK"])
def test_a_project_it_names_is_its_own(project: str):
    task = f"Every Monday, check LangGraph for a new release and create a Jira ticket in {project}"
    place = PlaceRead(project=project, said=f"in {project}")
    fields = read(watchlist_word="release", schedule="Every Monday", ticket=TICKET, place=place)
    answer = answer_of(fields, task, facts("LangGraph"))
    assert isinstance(answer, SetupCardAnswer)
    assert rows(answer)["where"][:2] == (f"Jira project {project}", "understood")


@pytest.mark.parametrize(
    "more",
    [{"search": SearchRead()}, {"place": PlaceRead()}, {"place": PlaceRead(said="Jira")}],
    ids=["empty search", "empty place", "place with no project"],
)
def test_an_empty_search_or_place_the_model_read_changes_nothing(more: dict[str, Any]):
    fields = read(schedule="Every day at 9am", ticket=TICKET, **more)
    answer = answer_of(fields, THE_REQUEST, facts("LangGraph"))
    assert isinstance(answer, SetupCardAnswer)
    assert rows(answer)["look_for"][0] == "LangGraph releases on GitHub"


def test_a_release_check_with_no_ticket_shows_the_ticket_it_fills_in():
    task = "Check n8n for new releases"
    fields = read(software="n8n")
    answer = answer_of(fields, task, facts("n8n"))
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == "n8n release check"
    card = rows(answer)
    assert card["schedule"][1] == "missing", "a time is never guessed"
    assert card["do"] == ("Create one ticket that lists them", "changed", FILLED_IN)


def test_a_part_it_cant_do_comes_back_beside_its_own_card():
    task = THE_REQUEST + " and email me"
    fields = read(schedule="Every day at 9am", ticket=TICKET)
    answer = answer_of(fields, task, facts("LangGraph"))
    assert isinstance(answer, CantAnswer)
    assert isinstance(answer.alternative, SetupCardAnswer), "never the watchlist instead"
    assert answer.alternative.name == "LangGraph release check"


@pytest.mark.parametrize(
    ("task", "more"),
    [
        ("Add LangGraph to the watchlist", {"watchlist_word": "Add"}),
        ("Add LangGraph to the watchlist and check it for new releases", {}),
        ("Watch React every Monday at 9am", {"watchlist_word": "Watch", "software": "React"}),
        ("Which version of LangGraph do we run?", {"watchlist_word": "version"}),
    ],
)
def test_a_request_about_the_watchlist_itself_keeps_its_answer(task: str, more: dict[str, Any]):
    answer = answer_of(read(**more), task, facts("n8n"))
    assert not isinstance(answer, SetupCardAnswer), answer
    assert isinstance(answer, WatchlistAnswer) or (
        isinstance(answer, CantAnswer) and isinstance(answer.alternative, WatchlistAnswer)
    )


def test_the_card_for_watched_software_stands_and_never_goes_to_the_question_lane():
    request = answer_request(THE_REQUEST).model_copy(update={"facts": facts("LangGraph")})
    answer = decide(read(schedule="Every day at 9am", ticket=TICKET), request)
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == "LangGraph release check"
