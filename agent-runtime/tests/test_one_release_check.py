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
        "New releases of LangGraph",
        "understood",
        'Read from your words "LangGraph".',
    )
    assert card["do"] == (
        "Create 1 Jira ticket",
        "understood",
        'Read from your words "create a Jira ticket".',
    )
    assert card["where"][1] == "missing", "it asks for a Jira project of its own"
    assert "MOCK" not in answer.model_dump_json(), "never the watchlist's project"
    assert why_not("look_for", card["look_for"][0]) is None, "the card's own check accepts it"
    assert why_not("do", card["do"][0]) is None
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
    assert rows(answer)["look_for"][0] == "New releases of LangGraph"


def test_a_release_check_with_no_ticket_shows_the_ticket_it_fills_in():
    task = "Every Monday, check n8n for new releases"
    fields = read(software="n8n", schedule="Every Monday")
    answer = answer_of(fields, task, facts("n8n"))
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == "n8n release check"
    card = rows(answer)
    assert card["schedule"][0] == "Every Monday"
    assert card["do"] == ("Create 1 Jira ticket", "changed", FILLED_IN)


@pytest.mark.parametrize(
    ("task", "more"),
    [
        ("track the n8n releases", {"software": "n8n"}),
        ("Monitor Kubernetes releases", {"software": "Kubernetes"}),
        ("Check LangGraph for new releases every weekday at 9", {}),
    ],
)
def test_other_ways_to_ask_for_a_release_check_get_its_card(task: str, more: dict[str, Any]):
    answer = answer_of(read(**more), task, facts())
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == f"{more.get('software', 'LangGraph')} release check"


def test_words_beside_the_release_check_come_back_crossed_never_dropped():
    task = "Check LangGraph for new releases and post it in Slack"
    answer = answer_of(read(), task, facts())
    assert isinstance(answer, CantAnswer) and isinstance(answer.alternative, SetupCardAnswer)
    assert [(row.text, row.system) for row in answer.cant] == [("Slack", "Slack")]


@pytest.mark.parametrize("task", ["Check n8n for new releases?", "latest version of n8n"])
def test_a_question_about_the_newest_version_keeps_its_answer(task: str):
    answer = answer_of(read(software="n8n"), task, facts("n8n"))
    assert isinstance(answer, WatchlistAnswer), "a question, not a workflow"


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


def test_the_ticket_for_a_new_release_quotes_all_its_words():
    task = THE_REQUEST + " if there's a new one"
    answer = answer_of(read(schedule="Every day at 9am", ticket=TICKET), task, facts())
    assert isinstance(answer, SetupCardAnswer)
    assert rows(answer)["do"] == (
        "Create 1 Jira ticket",
        "understood",
        'Read from your words "create a Jira ticket if there\'s a new one".',
    )


@pytest.mark.parametrize(
    ("task", "schedule"),
    [
        ("Can you check LangGraph for new releases every day at 9am?", "every day at 9am"),
        (
            "Could you please check LangGraph for new releases every day at 9am?",
            "every day at 9am",
        ),
        ("Do a release check of LangGraph every Monday at 9am", "every Monday at 9am"),
    ],
)
def test_a_request_said_as_a_question_is_still_a_request(task: str, schedule: str):
    answer = answer_of(read(schedule=schedule), task, facts("LangGraph"))
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "LangGraph release check"


@pytest.mark.parametrize(
    ("words", "crossed"),
    [
        ("for new major releases", "major"),
        ("for new releases since 1.2.14", "1.2.14"),
        ("for new releases newer than our version", "newer"),
        ("for new pre-releases", "pre-releases"),
        ("for new releases from langchain-ai/langgraph", "langchain-ai/langgraph"),
        ("and n8n for new releases", "n8n for new releases"),
    ],
)
def test_words_beside_the_software_the_card_doesnt_hold_come_back_crossed(words: str, crossed: str):
    task = f"Every day at 9am, check LangGraph {words}"
    fields = read(schedule="Every day at 9am")
    answer = answer_of(fields, task, facts("LangGraph"))
    assert isinstance(answer, CantAnswer), answer
    assert isinstance(answer.alternative, SetupCardAnswer)
    assert [row.text for row in answer.cant] == [crossed]
    held = [p.text for p in parts_of(fields, task, answer) if p.mark == "will_do"]
    assert not any(crossed in text for text in held), held


ON_GITHUB = (
    "Check FastAPI on GitHub for new releases every weekday at 9am, and create a Jira ticket "
    "when there's a new one."
)
"""The 25 Nov walk-through's request, typed on Home with the local stack's model."""
DAILY_ON_GITHUB = ON_GITHUB.replace("every weekday at 9am", "every day at 9:00")
IN_MOCK = (
    "Check FastAPI on GitHub for new releases every weekday at 9am, and create a Jira ticket "
    "in the MOCK project when there is a new one."
)
FASTAPI_TICKET = TicketRead(creates=True, says="list", said="create a Jira ticket")


def fastapi(**fields: Any) -> TaskRead:
    return read(software="FastAPI", ticket=FASTAPI_TICKET, **fields)


@pytest.mark.parametrize(
    ("task", "schedule", "shown"),
    [
        (ON_GITHUB, "Weekdays at 9am", "Every weekday at 9am"),
        (ON_GITHUB, "Every weekday at 9:00", "Every weekday at 9am"),
        (ON_GITHUB, "every weekday 9am", "Every weekday at 9am"),
        (DAILY_ON_GITHUB, "Daily at 9:00", "Every day at 9:00"),
        (DAILY_ON_GITHUB, "Every day at 9am", "Every day at 9:00"),
    ],
)
def test_a_schedule_the_model_wrote_another_way_is_read_and_never_also_crossed(
    task: str, schedule: str, shown: str
):
    """25 Nov walk-through: "on" in "on GitHub" stood before the schedule, so its words were never
    found when the model wrote them another way. The card held the schedule, and the same words
    came back crossed: "Can't do: Weekday at 9am. I couldn't read this as a schedule."."""
    fields = fastapi(schedule=schedule)
    answer = answer_of(fields, task, facts())
    assert isinstance(answer, SetupCardAnswer), answer
    assert rows(answer)["schedule"][:2] == (shown, "understood")
    assert all(p.mark != "cant" for p in parts_of(fields, task, answer))


@pytest.mark.parametrize(
    "place",
    [PlaceRead(project="MOCK", said="in the MOCK project"), PlaceRead(project="MOCK"), None],
    ids=["place read", "key only", "place not read"],
)
def test_the_project_its_ticket_names_is_its_own_and_never_also_crossed(place: PlaceRead | None):
    """25 Nov walk-through: with the project between the ticket and "when there is a new one", the
    ticket's own words stopped before it, so "new" came back crossed. With no place read, "MOCK
    project when there is a new" did, though the builder read MOCK as the ticket's project."""
    fields = fastapi(schedule="every weekday at 9am", place=place)
    answer = answer_of(fields, IN_MOCK, facts())
    assert isinstance(answer, SetupCardAnswer), answer
    assert rows(answer)["where"][:2] == ("Jira project MOCK", "understood")
    assert all(p.mark != "cant" for p in parts_of(fields, IN_MOCK, answer))
