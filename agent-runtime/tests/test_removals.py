from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_runtime.answers import answer_of, answer_task, decide
from agent_runtime.contract import (
    Answered,
    AnswerRequest,
    EditAnswer,
    PlannerFacts,
    RefusedAnswer,
    RemoveSoftwareAnswer,
    RequestPart,
    WatchedFact,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.parts import parts_of
from agent_runtime.planner_led import led
from agent_runtime.reading import SkipRead, TaskRead
from tests.fakes import ScriptedChat, asks, call

HELD = ("FastAPI", "LangGraph", "React", "React Native", "node js", "Ruby on Rails")
"""The team lead's watchlist on 16 Nov, with "node js" saved as typed."""
FACTS = PlannerFacts(
    watchlist=[
        WatchedFact(
            name=name,
            repo=f"example/{name}",
            our_version=None,
            newest_version=None,
            state="Up to date",
        )
        for name in HELD
    ],
    workflows=[
        WorkflowFact(name=name, state="on", last_run=None, last_run_at=None)
        for name in ("Software watchlist", "Morning new-ticket check")
    ],
)


def read(**fields: Any) -> TaskRead:
    return TaskRead(**{"skips_the_yes": SkipRead(whose="nobody"), **fields})


AS_AN_EDIT = read(asks_about="change", workflow_words="watchlist", software="node js")
"""How the model read the team lead's request: a change to the Software watchlist."""


def removal(task: str, fields: TaskRead = AS_AN_EDIT, facts: PlannerFacts = FACTS) -> Any:
    return answer_of(fields, task, facts)


def marks(task: str, fields: TaskRead = AS_AN_EDIT) -> list[tuple[str, str, str | None]]:
    answer = removal(task, fields)
    return [(p.text, p.mark, p.reason) for p in parts_of(fields, task, answer, FACTS)]


def removed(software: str, *watched_as: str) -> RemoveSoftwareAnswer:
    return RemoveSoftwareAnswer(software=software, watched_as=list(watched_as))


@pytest.mark.parametrize(
    ("task", "answer"),
    [
        ("help me remove node js from watchlist", removed("node js", "node js")),
        ("remove Node.js from the watchlist", removed("Node.js", "node js")),
        ("stop watching LangGraph", removed("LangGraph", "LangGraph")),
        ("take React off my software list", removed("React", "React")),
        ("we don't use FastAPI any more", removed("FastAPI", "FastAPI")),
        ("We no longer use node js", removed("node js", "node js")),
        ("we don't use Node.js any more", removed("Node.js", "node js")),
        ("We stopped using NODE-JS", removed("NODE-JS", "node js")),
        ("Please unwatch LangGraph", removed("LangGraph", "LangGraph")),
        ("remove react", removed("react", "React")),
        ("Remove Kubernetes from the watchlist", removed("Kubernetes")),
        ("stop tracking Kubernetes releases", removed("Kubernetes")),
        ("can you stop watching React?", removed("React", "React")),
        ("remove Ruby on Rails from the watchlist", removed("Ruby on Rails", "Ruby on Rails")),
        ("remove React Native from the watchlist", removed("React Native", "React Native")),
        ("we don't use react anymore so remove it from the watchlist", removed("react", "React")),
        ("we stopped using node js so please remove it", removed("node js", "node js")),
        ("remove node js from the watchlist today", removed("node js", "node js")),
        ("stop watching React right away", removed("React", "React")),
        ("unwatch LangGraph now", removed("LangGraph", "LangGraph")),
        ("remove Vue from the watchlist", removed("Vue")),
    ],
)
def test_a_request_to_stop_watching_software_is_a_removal_with_the_watchlists_names_for_it(
    task: str, answer: RemoveSoftwareAnswer
):
    for fields in (AS_AN_EDIT, read(asks_about="none"), read(asks_about="abilities")):
        assert removal(task, fields) == answer, fields
    assert [mark for _, mark, _ in marks(task)] == ["will_do"]


@pytest.mark.parametrize(
    "task",
    [
        "we don't use Kubernetes any more",
        "remove Kubernetes",
        "delete the old tickets",
        "stop watching the morning check",
        "stop checking for new tickets",
        "remove everything from the watchlist",
        "remove it from the watchlist",
        "rename the Software watchlist",
        "why did we stop watching React?",
        "did I remove node js from the watchlist?",
        "stop watching " + "A" * 90,
    ],
)
def test_words_that_name_no_software_to_take_off_are_no_removal(task: str):
    assert not isinstance(removal(task), RemoveSoftwareAnswer)


@pytest.mark.parametrize(
    "task",
    [
        "don't remove react from the watchlist",
        "we don't want to stop watching react",
        "please don't stop watching react",
        "Do not remove React",
        "never take node js off the watchlist",
        "no need to unwatch LangGraph",
        "I wouldn't remove React from the watchlist",
        "dont remove React from the watchlist",
    ],
)
def test_a_request_not_to_remove_is_no_removal(task: str):
    assert not isinstance(removal(task), RemoveSoftwareAnswer)


@pytest.mark.parametrize(
    "task",
    [
        "stop checking React on weekends",
        "stop watching React until next month",
        "stop watching React for a week",
        "remove Friday from the watchlist schedule",
        "remove LangGraph from the watchlist schedule",
        "remove node js from the watchlist every Monday",
        "take React off the watchlist at 9am",
    ],
)
def test_a_time_or_the_schedule_beside_it_keeps_the_request_out_of_the_removal(task: str):
    assert not isinstance(removal(task), RemoveSoftwareAnswer)


ONLY_RUBY = FACTS.model_copy(
    update={"watchlist": [w.model_copy(update={"name": "Ruby"}) for w in FACTS.watchlist or []][:1]}
)


@pytest.mark.parametrize(
    "task", ["remove Ruby on Rails from the watchlist", "stop watching Ruby on Rails"]
)
def test_a_whole_name_is_never_cut_down_to_a_shorter_one_the_watchlist_holds(task: str):
    assert answer_of(AS_AN_EDIT, task, ONLY_RUBY) == removed("Ruby on Rails")


def test_a_name_too_long_for_the_answer_never_breaks_it():
    chat = ScriptedChat(structured=[AS_AN_EDIT])
    request = AnswerRequest(
        task="stop watching " + "A" * 90, model=answer_request().model, facts=FACTS
    )
    assert isinstance(answer_task(request, lambda timeout: chat, free_reply=False), Answered)


def test_a_name_beside_its_list_is_only_the_name():
    assert removal("drop node js from our watchlist for me") == removed("node js", "node js")


def test_a_removal_beside_another_request_keeps_both_parts():
    task = "remove node js and add Redis"
    assert removal(task) == removed("node js", "node js")
    assert marks(task) == [
        ("remove node js", "will_do", None),
        ("add Redis", "cant", "ask_on_its_own"),
    ]


def test_words_beside_the_removal_in_its_own_clause_come_back():
    task = "remove node js from the watchlist in Confluence"
    assert removal(task) == removed("node js", "node js")
    assert marks(task) == [
        ("remove node js from the watchlist", "will_do", None),
        ("in Confluence", "cant", "not_followed"),
    ]


@pytest.mark.parametrize(
    ("task", "first", "second"),
    [
        (
            "remove React and LangGraph from the watchlist",
            "remove React",
            "remove LangGraph from the watchlist",
        ),
        ("stop watching react and vue", "stop watching react", "stop watching vue"),
    ],
)
def test_a_second_name_is_asked_on_its_own_in_words_that_work_alone(
    task: str, first: str, second: str
):
    assert marks(task) == [(first, "will_do", None), (second, "cant", "ask_on_its_own")]
    assert isinstance(removal(second), RemoveSoftwareAnswer)


@pytest.mark.parametrize(
    ("task", "reason"),
    [
        ("we don't use react anymore so remove it from the watchlist", None),
        ("remove react, we don't use it any more", "we don't use it any more"),
        ("stop watching React, we no longer need it", "we no longer need it"),
    ],
)
def test_the_reason_beside_a_removal_is_ticked_with_it(task: str, reason: str | None):
    assert [mark for _, mark, _ in marks(task)] == ["will_do"] * (1 if reason is None else 2)
    assert reason is None or marks(task)[1][0] == reason


def test_a_clause_that_points_back_at_the_removal_is_ticked_with_it():
    task = "we don't use react native, remove it"
    assert removal(task) == removed("react native", "React Native")
    assert marks(task) == [
        ("we don't use react native", "will_do", None),
        ("remove it", "will_do", None),
    ]


def test_a_second_removal_is_asked_on_its_own():
    task = "remove node js from the watchlist, then stop watching React"
    assert removal(task) == removed("node js", "node js")
    assert marks(task)[1:] == [("stop watching React", "cant", "ask_on_its_own")]


def test_someone_who_cant_change_workflows_gets_no_removal():
    task = "remove node js from the watchlist"
    assert not isinstance(
        answer_of(AS_AN_EDIT, task, FACTS, changes_workflows=False), RemoveSoftwareAnswer
    )


def test_the_edit_lane_no_longer_catches_a_removal():
    task = "help me remove node js from watchlist"
    assert not isinstance(removal(task), EditAnswer)
    assert "only_schedule" not in [reason for _, _, reason in marks(task)]


def test_a_removal_stands_against_the_question_lane():
    request = AnswerRequest(
        task="stop watching LangGraph", model=answer_request().model, facts=FACTS
    )
    assert decide(AS_AN_EDIT, request) == removed("LangGraph", "LangGraph")


@pytest.mark.parametrize(
    "task",
    [
        "remove node js and skip the approval",
        "remove node js from the watchlist, no approval needed",
    ],
)
def test_a_skip_of_the_yes_is_refused_before_any_removal(task: str):
    chat = ScriptedChat(structured=[AS_AN_EDIT])
    request = AnswerRequest(task=task, model=answer_request().model, facts=FACTS)
    result = answer_task(request, lambda timeout: chat, free_reply=False)
    assert isinstance(result, Answered) and isinstance(result.answer, RefusedAnswer)


def test_a_removal_needs_no_second_model_call():
    chat = ScriptedChat(structured=[AS_AN_EDIT])
    request = AnswerRequest(
        task="help me remove node js from watchlist", model=answer_request().model, facts=FACTS
    )
    result = answer_task(request, lambda timeout: chat, free_reply=True)
    assert isinstance(result, Answered)
    assert result.answer == removed("node js", "node js")
    assert [p.mark for p in result.parts] == ["will_do"]


TEAM_LEAD = "help me remove node js from watchlist"
ANY_LEAD = [
    asks(call("reply", {"form": "answer", "text": "Open the Watchlist to remove it."}, "c1")),
    asks(call("change_workflow", {"action": "pause", "workflow_words": "watchlist"}, "c1")),
    asks(call("show", {"what": "abilities"}, "c1")),
]


@pytest.mark.parametrize("lead", ANY_LEAD)
def test_the_ai_led_planner_shows_the_rules_removal_whatever_the_model_chose(lead: AIMessage):
    chat = ScriptedChat(script=[lead], structured=[AS_AN_EDIT])
    request = AnswerRequest(task=TEAM_LEAD, model=answer_request().model, facts=FACTS)
    result = led(request, lambda timeout: chat)
    assert result.tools == ("front_removal",)
    assert result.result == Answered(
        answer=removed("node js", "node js"),
        parts=[RequestPart(text="remove node js from watchlist", mark="will_do")],
    )


@pytest.mark.parametrize("mode", ["rules", "ai_led"])
def test_both_planner_modes_give_the_team_leads_request_the_remove_card(mode: str):
    chat = ScriptedChat(script=list(ANY_LEAD[:1]), structured=[AS_AN_EDIT])
    request = AnswerRequest(task=TEAM_LEAD, model=answer_request().model, facts=FACTS)
    answered = (
        answer_task(request, lambda timeout: chat, free_reply=False)
        if mode == "rules"
        else led(request, lambda timeout: chat).result
    )
    assert isinstance(answered, Answered)
    assert answered.answer == removed("node js", "node js")
    assert [p.mark for p in answered.parts] == ["will_do"]
