"""The Planner's short answers in the chat-first sketch: the capabilities card, the can'ts,
and pause and resume."""

from typing import Any

import pytest

from agent_runtime.abilities import CAPABILITIES
from agent_runtime.answers import answer_of, check_one_part, parts_of
from agent_runtime.contract import (
    CantAnswer,
    CantRow,
    CheckPartRequest,
    EditAnswer,
    PartCantDo,
    PauseAnswer,
    PlannerAnswer,
    ResumeAnswer,
    WatchlistAnswer,
)
from tests.test_answers import WORKFLOWS, read


def test_the_capabilities_card_lists_the_ready_entries_by_their_short_words():
    lines = [c.short for c in CAPABILITIES if c.state == "ready" and c.short]
    assert lines == [
        "Watch software for new releases",
        "Create Jira tickets, after a yes",
        "Explain a stopped run, and retry it",
        "Change or pause your workflows",
    ]


def test_the_not_yet_note_names_the_entries_that_are_not_ready_by_their_short_words():
    assert [c.short for c in CAPABILITIES if c.state != "ready" and c.short] == [
        "Teams channels",
        "email",
        "Confluence",
    ]


def test_only_an_entry_that_is_not_ready_says_what_the_person_has_instead():
    assert [c.id for c in CAPABILITIES if c.state == "ready" and c.instead] == []
    assert all(c.cant for c in CAPABILITIES if c.instead)


def _cants(answer: PlannerAnswer) -> list[CantRow]:
    match answer:
        case CantAnswer():
            return answer.cant
        case WatchlistAnswer() if isinstance(answer.also, CantAnswer):
            return answer.also.cant
        case _:
            raise AssertionError(answer)


TEAMS = ("I can’t post in Teams channels yet.", "Run results show here, in the chat.", False)
EMAIL = ("I can’t send email yet.", "Run results show here, in the chat.", False)
CONFLUENCE = ("I can’t update Confluence yet.", "I can create a Jira ticket, after a yes.", False)
DELETE = ("I don’t delete anything in Jira.", "A Jira admin can do that.", True)


@pytest.mark.parametrize(
    ("task", "fields", "said"),
    [
        ("Post the FastAPI news in our Teams channel", {}, TEAMS),
        ("Email me the weekly list of stale tickets", {}, EMAIL),
        (
            "watch Kubernetes and email me",
            {"software": "Kubernetes", "belongs_on_watchlist": True, "watchlist_word": "watch"},
            EMAIL,
        ),
        ("Update the Confluence page", {}, CONFLUENCE),
        ("delete the MOCK ticket", {}, DELETE),
        ("delete the MOCK ticket", {"asks_about": "change"}, DELETE),
        (
            "delete the MOCK ticket",
            {"asks_about": "change", "workflow_words": "MOCK ticket"},
            DELETE,
        ),
    ],
)
def test_a_cant_the_registry_names_says_its_one_liner_and_what_she_has_instead(
    task: str, fields: dict[str, Any], said: tuple[str, str, bool]
):
    answer = answer_of(read(**fields), task, WORKFLOWS)
    [row] = [r for r in _cants(answer) if r.instead is not None]
    assert (row.note, row.instead, row.unsupported) == said
    marked = [p for p in parts_of(read(**fields), task, answer, WORKFLOWS) if p.mark == "cant"]
    assert [p.note for p in marked] == [said[0]]


def test_a_cant_no_entry_names_keeps_the_words_it_had():
    task = "Every quarter, list who has admin access in Entra ID"
    [row] = _cants(answer_of(read(schedule="Every quarter"), task))
    assert (row.note, row.instead, row.unsupported) == ("I didn't follow this part.", None, False)


def test_reading_teams_is_not_posting_in_it():
    task = "Every Monday, read the messages in our Teams channel"
    rows = _cants(answer_of(read(schedule="Every Monday"), task))
    assert [r.note for r in rows if r.instead is not None] == []


def test_a_part_she_changes_gets_the_same_one_liner():
    checked = check_one_part(CheckPartRequest(kind="where", text="Post it in our Teams channel"))
    assert isinstance(checked, PartCantDo)
    assert checked.note == TEAMS[0]


CHANGE = {"asks_about": "change", "workflow_words": "React check", "software": "React"}


@pytest.mark.parametrize(
    ("task", "kind"),
    [
        ("pause the React check", PauseAnswer),
        ("Stop the React check", PauseAnswer),
        ("turn the React check off", PauseAnswer),
        ("resume the React check", ResumeAnswer),
        ("Turn the React check back on", ResumeAnswer),
        ("unpause the React check", ResumeAnswer),
    ],
)
def test_pause_and_resume_name_the_workflow_and_tick_the_order(
    task: str, kind: type[PauseAnswer | ResumeAnswer]
):
    answer = answer_of(read(**CHANGE), task, WORKFLOWS)
    assert isinstance(answer, kind)
    assert (answer.workflow_words, answer.software) == ("React check", "React")
    parts = parts_of(read(**CHANGE), task, answer, WORKFLOWS)
    assert [(p.text, p.mark) for p in parts] == [(task, "will_do")]


def test_it_names_no_workflow_so_she_picks_one():
    answer = answer_of(read(asks_about="change"), "pause it", WORKFLOWS)
    assert isinstance(answer, PauseAnswer) and answer.workflow_words is None


@pytest.mark.parametrize(
    "task",
    [
        "Pause the React check and rename it",
        "pause the React check and make it run at 9am",
        "Rename the React check",
    ],
)
def test_pause_beside_another_change_is_still_the_change_the_chat_cant_make(task: str):
    answer = answer_of(read(**CHANGE), task, WORKFLOWS)
    assert isinstance(answer, EditAnswer) and answer.cant == "only_schedule"


def test_deleting_a_workflow_whose_name_holds_ticket_is_still_a_change_to_it():
    answer = answer_of(read(asks_about="change"), "delete the morning new-ticket check", WORKFLOWS)
    assert isinstance(answer, EditAnswer) and answer.cant == "only_schedule"


def test_a_question_beside_a_pause_is_kept_to_ask_on_its_own():
    task = "What needs my attention? Pause the morning check"
    fields = read(asks_about="needs_me")
    answer = answer_of(fields, task, WORKFLOWS)
    assert isinstance(answer, PauseAnswer)
    assert [(p.text, p.mark, p.reason) for p in parts_of(fields, task, answer, WORKFLOWS)] == [
        ("What needs my attention", "cant", "ask_on_its_own"),
        ("Pause the morning check", "will_do", None),
    ]


def test_someone_who_cant_change_workflows_gets_no_pause():
    answer = answer_of(read(**CHANGE), "pause the React check", WORKFLOWS, changes_workflows=False)
    assert not isinstance(answer, PauseAnswer | ResumeAnswer)


def test_why_it_stopped_is_a_question_not_a_pause():
    answer = answer_of(read(asks_about="why_stopped"), "why did the morning check stop?", WORKFLOWS)
    assert not isinstance(answer, PauseAnswer | ResumeAnswer)
