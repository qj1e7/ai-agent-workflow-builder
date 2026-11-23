"""The prototype's watch card (ADR 0053 item 4): a watch request with a time of its own is the
card's question, "How should I add LangGraph?", so the runtime reads that time as the watch's
own, never as words it didn't follow. A one-off question about a new release keeps the newest
version answer."""

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

MONDAY_9 = WatchlistScheduleFact(day="monday", at="09:00")


def read(**fields: Any) -> TaskRead:
    watch = {"belongs_on_watchlist": True, "watchlist_word": "Add", "software": "LangGraph"}
    return TaskRead(**{"skips_the_yes": SkipRead(whose="nobody"), **watch, **fields})


def facts(*watched: str) -> PlannerFacts:
    held = [
        WatchedFact(name=n, repo=f"x/{n}", our_version=None, newest_version=None, state="On")
        for n in watched
    ]
    return PlannerFacts(watchlist=held, watchlist_schedule=MONDAY_9, watchlist_project="MOCK")


@pytest.mark.parametrize(
    "task",
    [
        "Add LangGraph to the watchlist and check it every day",
        "Add LangGraph to the watchlist and keep track of it every day",
    ],
)
def test_the_prototypes_watch_request_asks_its_time_on_the_watch_card(task: str):
    fields = read(schedule="every day")
    answer = answer_of(fields, task, facts("n8n"))
    assert isinstance(answer, CantAnswer), answer
    assert isinstance(answer.alternative, WatchlistAnswer)
    assert answer.alternative.software == "LangGraph"
    marks = [(p.text, p.mark, p.reason) for p in parts_of(fields, task, answer)]
    assert ("every day", "cant", "own_time") in marks, marks
    assert not any(reason == "not_followed" for _, _, reason in marks), marks


@pytest.mark.parametrize(
    "task",
    [
        "Can you check if n8n has a new release?",
        "Can you check whether n8n has a new release?",
        "Check if n8n has a new release",
    ],
)
def test_a_one_off_question_about_a_new_release_keeps_the_newest_answer(task: str):
    fields = read(watchlist_word="release", software="n8n")
    answer = answer_of(fields, task, facts("n8n"))
    assert not isinstance(answer, SetupCardAnswer), answer
    assert isinstance(answer, WatchlistAnswer), answer


@pytest.mark.parametrize(
    ("task", "more"),
    [
        (
            "Watch LangGraph releases on the watchlist every Thursday at 7am",
            {"watchlist_word": "releases", "schedule": "every Thursday at 7am"},
        ),
        (
            "Watch LangGraph every day at 9am",
            {"watchlist_word": "Watch", "schedule": "every day at 9am"},
        ),
    ],
)
def test_watched_software_with_a_time_of_its_own_gets_its_own_release_check(
    task: str, more: dict[str, Any]
):
    fields = read(**more)
    answer = answer_of(fields, task, facts("LangGraph", "n8n"))
    assert isinstance(answer, SetupCardAnswer), answer
    assert answer.name == "LangGraph release check"
    [when] = [row for row in answer.rows if row.kind == "schedule"]
    assert when.state == "understood", when
    assert all(p.reason != "own_time" for p in parts_of(fields, task, answer))


def test_a_version_beside_a_release_check_is_crossed_as_one_version():
    task = "Every day at 9am, check LangGraph for new releases since 1.2.14"
    fields = read(watchlist_word="releases", schedule="Every day at 9am")
    answer = answer_of(fields, task, facts())
    assert isinstance(answer, CantAnswer) and isinstance(answer.alternative, SetupCardAnswer)
    assert [(row.text, row.note) for row in answer.cant] == [
        ("1.2.14", "I check for any new release, not one version.")
    ]


def test_a_version_inside_a_watched_softwares_own_time_is_crossed_never_dropped():
    task = "Check n8n every day for 1.2.14"
    fields = read(watchlist_word="Check", software="n8n", schedule="every day")
    answer = answer_of(fields, task, facts("n8n"))
    assert isinstance(answer, CantAnswer), answer
    assert isinstance(answer.alternative, SetupCardAnswer)
    assert [(row.text, row.note) for row in answer.cant] == [
        ("1.2.14", "I check for any new release, not one version.")
    ]


def test_a_time_as_9_30_is_never_crossed_as_a_version():
    task = "Check n8n every day since 9.30"
    fields = read(watchlist_word="Check", software="n8n", schedule="every day")
    answer = answer_of(fields, task, facts("n8n"))
    assert "not one version" not in answer.model_dump_json()


def test_tell_me_if_keeps_its_answer_from_before():
    task = "Tell me if n8n has a new release"
    answer = answer_of(read(watchlist_word="release", software="n8n"), task, facts("n8n"))
    assert isinstance(answer, SetupCardAnswer), answer
