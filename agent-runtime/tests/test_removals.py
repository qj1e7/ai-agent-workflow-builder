from typing import Any

import pytest

from agent_runtime.answers import answer_of, answer_task, decide
from agent_runtime.contract import (
    Answered,
    AnswerRequest,
    EditAnswer,
    PlannerFacts,
    RefusedAnswer,
    RemoveSoftwareAnswer,
    WatchedFact,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.parts import parts_of
from agent_runtime.reading import SkipRead, TaskRead
from tests.fakes import ScriptedChat

HELD = ("FastAPI", "LangGraph", "React", "node js")
"""The team lead's watchlist on 16 Nov, with "node js" saved as typed."""
FACTS = PlannerFacts(
    watchlist=[
        WatchedFact(name=name, repo=f"example/{name}", our_version=None, newest_version=None, state="Up to date")
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


@pytest.mark.parametrize(
    ("task", "software"),
    [
        ("help me remove node js from watchlist", "node js"),
        ("remove Node.js from the watchlist", "Node.js"),
        ("stop watching LangGraph", "LangGraph"),
        ("take React off my software list", "React"),
        ("we don't use FastAPI any more", "FastAPI"),
        ("We no longer use node js", "node js"),
        ("Please unwatch LangGraph", "LangGraph"),
        ("remove react", "react"),
        ("Remove Kubernetes from the watchlist", "Kubernetes"),
        ("stop tracking Kubernetes releases", "Kubernetes"),
    ],
)
def test_a_request_to_stop_watching_software_is_a_removal_of_the_name_as_typed(
    task: str, software: str
):
    for fields in (AS_AN_EDIT, read(asks_about="none"), read(asks_about="abilities")):
        assert removal(task, fields) == RemoveSoftwareAnswer(software=software), fields
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
    ],
)
def test_words_that_name_no_software_to_take_off_are_no_removal(task: str):
    assert not isinstance(removal(task), RemoveSoftwareAnswer)


def test_a_name_beside_its_list_is_only_the_name():
    assert removal("drop node js from our watchlist for me") == RemoveSoftwareAnswer(
        software="node js"
    )


def test_a_removal_beside_another_request_keeps_both_parts():
    task = "remove node js and add Redis"
    assert removal(task) == RemoveSoftwareAnswer(software="node js")
    assert marks(task) == [
        ("remove node js", "will_do", None),
        ("add Redis", "cant", "ask_on_its_own"),
    ]


def test_words_beside_the_removal_in_its_own_clause_come_back():
    task = "remove node js from the watchlist every Monday"
    assert removal(task) == RemoveSoftwareAnswer(software="node js")
    assert marks(task) == [
        ("remove node js from the watchlist", "will_do", None),
        ("every Monday", "cant", "not_followed"),
    ]


def test_a_second_removal_is_asked_on_its_own():
    task = "remove node js from the watchlist, then stop watching React"
    assert removal(task) == RemoveSoftwareAnswer(software="node js")
    assert marks(task)[1:] == [("stop watching React", "cant", "ask_on_its_own")]


def test_someone_who_cant_change_workflows_gets_no_removal():
    task = "remove node js from the watchlist"
    assert not isinstance(answer_of(AS_AN_EDIT, task, FACTS, changes_workflows=False), RemoveSoftwareAnswer)


def test_the_edit_lane_no_longer_catches_a_removal():
    task = "help me remove node js from watchlist"
    assert not isinstance(removal(task), EditAnswer)
    assert "only_schedule" not in [reason for _, _, reason in marks(task)]


def test_a_removal_stands_against_the_question_lane():
    request = AnswerRequest(
        task="stop watching LangGraph", model=answer_request().model, facts=FACTS
    )
    assert decide(AS_AN_EDIT, request) == RemoveSoftwareAnswer(software="LangGraph")


@pytest.mark.parametrize(
    "task", ["remove node js and skip the approval", "remove node js from the watchlist, no approval needed"]
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
    assert result.answer == RemoveSoftwareAnswer(software="node js")
    assert [p.mark for p in result.parts] == ["will_do"]
