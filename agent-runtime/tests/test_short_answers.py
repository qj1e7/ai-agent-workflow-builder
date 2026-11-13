"""The Planner's short answers in the chat-first sketch: the capabilities card, the can'ts,
and pause and resume."""

from typing import Any

import pytest

from agent_runtime.abilities import CAPABILITIES, why_not
from agent_runtime.answers import answer_of, check_one_part, parts_of
from agent_runtime.contract import (
    CantAnswer,
    CantRow,
    CheckPartRequest,
    EditAnswer,
    PartCantDo,
    PauseAnswer,
    PlannerAnswer,
    PlannerFacts,
    ResumeAnswer,
    WatchlistAnswer,
    WorkflowFact,
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


TEAMS = ("I can't post in Teams channels yet.", "Run results show here, in the chat.", False)
EMAIL = ("I can't send email yet.", "Run results show here, in the chat.", False)
CONFLUENCE = ("I can't update Confluence yet.", "I can create a Jira ticket, after a yes.", False)
DELETE = ("I don't delete anything in Jira.", "A Jira admin can do that.", True)


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


def test_a_text_message_is_the_registrys_unsupported_entry():
    note = why_not("do", "send me a text message")
    assert note is not None and note.startswith("I can't send me a text message.")


def test_removing_a_label_from_tickets_is_not_deleting_them():
    task = "remove the old label from the MOCK tickets"
    rows = _cants(answer_of(read(), task))
    assert [r.note for r in rows if r.instead is not None] == []


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


@pytest.mark.parametrize(
    ("task", "beside"),
    [
        ("pause the React check and create a Jira ticket", "create a Jira ticket"),
        ("pause the React check and email me", "email me"),
        ("pause the React check and post in Teams", "post in Teams"),
        ("Pause the React check and send it to Teams", "send it to Teams"),
        ("Pause the React check and delete the MOCK ticket", "delete the MOCK ticket"),
    ],
)
def test_a_write_beside_a_pause_keeps_its_cross_and_only_the_order_is_ticked(
    task: str, beside: str
):
    answer = answer_of(read(**CHANGE), task, WORKFLOWS)
    assert isinstance(answer, PauseAnswer)
    parts = [(p.text, p.mark, p.reason) for p in parts_of(read(**CHANGE), task, answer, WORKFLOWS)]
    assert parts == [(task.split(" and ")[0], "will_do", None), (beside, "cant", "ask_on_its_own")]


def test_a_second_workflow_named_beside_the_pause_is_crossed_not_ticked():
    task = "Pause the Morning new-ticket check and the Weekly closed-ticket summary"
    fields = read(asks_about="change", workflow_words="Morning new-ticket check")
    answer = answer_of(fields, task, WORKFLOWS)
    assert isinstance(answer, PauseAnswer)
    assert answer.workflow_words == "Morning new-ticket check"
    assert [(p.text, p.mark, p.reason) for p in parts_of(fields, task, answer, WORKFLOWS)] == [
        ("Pause the Morning new-ticket check", "will_do", None),
        ("Weekly closed-ticket summary", "cant", "ask_on_its_own"),
    ]


def test_disable_is_a_pause_not_a_write_beside_it():
    task = "disable the React check"
    answer = answer_of(read(**CHANGE), task, WORKFLOWS)
    assert isinstance(answer, PauseAnswer)
    assert [p.mark for p in parts_of(read(**CHANGE), task, answer, WORKFLOWS)] == ["will_do"]


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


CHECKS = PlannerFacts(
    workflows=[
        WorkflowFact(name=name, state="on", last_run=None, last_run_at=None)
        for name in (
            "Morning check bbeda",
            "Evening check bbeda",
            "Morning check cddeb",
            "Morning check decaf",
        )
    ]
)
"""Newest first, as the platform lists them: the workflow named in full is not the first whose
words the request holds."""


@pytest.mark.parametrize(
    ("task", "about", "kind"),
    [
        (
            "how are my workflows doing? make the Morning check decaf run at 10am",
            "my_workflows",
            EditAnswer,
        ),
        ("pause the Morning check decaf", "change", PauseAnswer),
        ("resume the Morning check decaf", "change", ResumeAnswer),
    ],
)
def test_a_whole_name_wins_over_the_words_it_shares_with_other_workflows(
    task: str, about: str, kind: type[EditAnswer | PauseAnswer | ResumeAnswer]
):
    answer = answer_of(read(asks_about=about), task, CHECKS)
    assert isinstance(answer, kind)
    assert answer.workflow_words == "Morning check decaf"


def test_words_two_workflows_share_name_both_so_she_picks():
    answer = answer_of(read(asks_about="change"), "pause the bbeda check", CHECKS)
    assert isinstance(answer, PauseAnswer)
    assert answer.workflow_words == "bbeda check"
