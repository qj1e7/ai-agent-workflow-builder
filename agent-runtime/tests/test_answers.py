import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent_runtime.abilities import VULNERABILITIES_PLANNED
from agent_runtime.answers import (
    ANSWER_SYSTEM,
    CHOOSE_INSTEAD,
    FILLED_IN,
    AnswerRow,
    TaskRead,
    answer_of,
    answer_task,
)
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    CantAnswer,
    CheckWorkflowsAnswer,
    ModelProblem,
    NeedsMeAnswer,
    PartAnswer,
    RefusedAnswer,
    SetupCardAnswer,
    WatchlistAnswer,
    WhichSoftwareAnswer,
    WhyStoppedAnswer,
    answer_result_adapter,
)
from agent_runtime.contracts import FOLLOW_UP_TASK, answer_request
from tests.fakes import ScriptedChat
from tests.test_cards_api import make_app

EMAIL_TASK = "Every Friday, email me the list of stale tickets in MOCK"
COMPONENT_TASK = "Find bug tickets in MOCK and change their component"


def row(
    kind: str,
    text: str,
    state: str = "understood",
    note: str | None = None,
    alternative: str | None = None,
) -> AnswerRow:
    return AnswerRow.model_validate(
        {"kind": kind, "text": text, "state": state, "note": note, "alternative": alternative}
    )


def read(*rows: AnswerRow, **fields: Any) -> TaskRead:
    return TaskRead(rows=list(rows), **fields)


FOLLOW_UP_ROWS = (
    row("schedule", "Every weekday at 3pm"),
    row("look_for", "Bug tickets in MOCK with no update for 10 days"),
    row("do", "Create one follow-up ticket that lists them"),
    row("where", "Jira project MOCK"),
)
EMAIL_ROWS = (
    row("schedule", "Every Friday"),
    row("look_for", "Stale tickets in MOCK", "changed", "I read stale as 14 days."),
    row(
        "do",
        "Email them to you",
        "cant_do",
        "No tool sends email.",
        "Create one ticket that lists them",
    ),
    row("where", "Your email", "cant_do", "No tool sends email.", None),
)


def states(answer: SetupCardAnswer | PartAnswer) -> list[tuple[str, str, str]]:
    return [(r.kind, r.text, r.state) for r in answer.rows]


def test_clean_rows_are_a_set_up_card_named_by_the_model():
    answer = answer_of(read(*FOLLOW_UP_ROWS, name="Stale bug follow-up"), FOLLOW_UP_TASK)
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == "Stale bug follow-up"
    assert states(answer) == [
        ("schedule", "Every weekday at 3pm", "understood"),
        ("look_for", "Bug tickets in MOCK with no update for 10 days", "understood"),
        ("do", "Create one follow-up ticket that lists them", "understood"),
        ("where", "Jira project MOCK", "understood"),
    ]


def test_a_card_with_no_name_from_the_model_is_named_after_the_request():
    answer = answer_of(read(*FOLLOW_UP_ROWS), FOLLOW_UP_TASK)
    assert isinstance(answer, SetupCardAnswer)
    assert answer.name == FOLLOW_UP_TASK[:59] + "…"


@pytest.mark.parametrize(
    ("kind", "text", "task"),
    [
        (
            "look_for",
            "Stale tickets with no update for 14 days",
            "Every Friday, list stale tickets",
        ),
        ("schedule", "Every Friday at 9am", "Every Friday, list the open tickets in MOCK"),
        ("where", "Jira project SUP", "Every Friday, list the open tickets"),
        (
            "look_for",
            "Tickets about the Teams outage",
            "Every Friday, list the tickets about the chat outage",
        ),
    ],
    ids=["a-number", "a-time", "a-project-key", "another-system"],
)
def test_a_part_marked_understood_whose_key_words_are_not_in_the_request_is_a_guess(
    kind: str, text: str, task: str
):
    rows = [row(kind, text), row("look_for", "Open tickets"), row("do", "List them")]
    answer = answer_of(read(*rows), task)
    assert isinstance(answer, SetupCardAnswer)
    guessed = next(r for r in answer.rows if r.kind == kind)
    assert (guessed.state, guessed.note) == ("changed", FILLED_IN)


def test_jira_and_the_persons_own_numbers_do_not_make_a_part_a_guess():
    task = "Every Friday at 4pm, find the tickets in MOCK closed this week and sum them up"
    rows = (
        row("schedule", "Every Friday at 4pm"),
        row("look_for", "Tickets in MOCK closed this week"),
        row("do", "Create one ticket that sums them up"),
        row("where", "Jira project MOCK"),
    )
    answer = answer_of(read(*rows), task)
    assert isinstance(answer, SetupCardAnswer)
    assert all(r.state == "understood" for r in answer.rows)


def test_a_field_change_on_tickets_is_a_part_with_a_new_tool_in_jira():
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "Bug tickets in MOCK"),
        row(
            "do",
            "Change their component",
            "cant_do",
            "No tool changes tickets.",
            "Create one ticket that lists them",
        ),
        row("where", "Jira project MOCK"),
    )
    answer = answer_of(read(*rows, name="Bug ticket components"), COMPONENT_TASK)
    assert isinstance(answer, PartAnswer)
    assert [(c.kind, c.text, c.needs, c.system) for c in answer.cant] == [
        ("do", "Change their component", "new_tool", "Jira")
    ]
    offered = next(r for r in answer.rows if r.kind == "do")
    assert (offered.text, offered.state) == ("Create one ticket that lists them", "changed")
    assert offered.note == 'Suggested instead of "Change their component".'


def test_email_is_a_cant_for_a_new_system_with_the_checked_alternative():
    answer = answer_of(read(*EMAIL_ROWS, name="Stale ticket list"), EMAIL_TASK)
    assert isinstance(answer, CantAnswer)
    assert [(c.kind, c.needs, c.system) for c in answer.cant] == [
        ("do", "new_system", "email"),
        ("where", "new_system", "email"),
    ]
    assert isinstance(answer.alternative, SetupCardAnswer)
    assert answer.alternative.name == "Stale ticket list"
    assert states(answer.alternative) == [
        ("schedule", "Every Friday", "understood"),
        ("look_for", "Stale tickets in MOCK", "changed"),
        ("do", "Create one ticket that lists them", "changed"),
        ("where", "", "missing"),
    ]
    assert answer.alternative.rows[3].note == CHOOSE_INSTEAD


def test_an_alternative_the_tools_cannot_do_is_not_offered():
    rows = (
        EMAIL_ROWS[0],
        EMAIL_ROWS[1],
        row("do", "Email them to you", "cant_do", "No tool sends email.", "Post them in Teams"),
        EMAIL_ROWS[3],
    )
    answer = answer_of(read(*rows), EMAIL_TASK)
    assert isinstance(answer, CantAnswer)
    assert answer.alternative is None


def test_an_alternative_with_nothing_left_to_look_for_or_do_is_not_offered():
    rows = (
        row("schedule", "Every Friday"),
        row("look_for", "Who has admin access in GitLab", "cant_do", "I can't read GitLab.", None),
        row("do", "Remove anyone who left", "cant_do", "No tool changes access.", None),
        row("where", "GitLab", "cant_do", "I can't change GitLab.", None),
    )
    answer = answer_of(
        read(*rows), "Every Friday, list who has admin access in GitLab and remove anyone who left"
    )
    assert isinstance(answer, CantAnswer)
    assert answer.alternative is None
    assert {c.system for c in answer.cant} == {"GitLab"}
    assert {c.needs for c in answer.cant} == {"new_system"}


def test_a_change_to_tickets_other_than_a_field_is_a_cant_not_a_part():
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "Closed tickets"),
        row("do", "Delete every closed ticket", "cant_do", "No tool deletes tickets.", None),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows), "delete every closed ticket")
    assert isinstance(answer, CantAnswer)
    assert [(c.needs, c.system) for c in answer.cant] == [("new_tool", "Jira")]


def test_a_part_the_model_accepted_that_no_tool_serves_is_still_a_cant():
    rows = (
        row("schedule", "Every weekday at 3pm"),
        row("look_for", "Bug tickets in MOCK"),
        row("do", "Write them to a Google Sheet"),
        row("where", "Jira project MOCK"),
    )
    task = "Every weekday at 3pm, find bug tickets in MOCK and write them to a Google Sheet"
    answer = answer_of(read(*rows), task)
    assert isinstance(answer, CantAnswer)
    assert [(c.kind, c.needs, c.system) for c in answer.cant] == [("do", "new_system", "Google")]
    assert answer.alternative is None


def test_a_vulnerability_check_is_a_cant_that_offers_to_watch_the_named_software():
    task = "Warn me about any known vulnerabilities in Log4j"
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "Known vulnerabilities in Log4j"),
        row("do", "Warn you about them", "cant_do", "No tool warns.", None),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows, software="Log4j"), task)
    assert isinstance(answer, CantAnswer)
    assert answer.cant[0].note == VULNERABILITIES_PLANNED
    assert answer.cant[0].needs == "new_system"
    assert answer.alternative == WatchlistAnswer(word="vulnerabilities", software="Log4j")
    unnamed = answer_of(read(*rows), "Check our packages for security advisories")
    assert isinstance(unnamed, CantAnswer) and unnamed.alternative is None


def test_a_release_request_goes_to_the_watchlist_with_the_requests_own_word():
    answer = answer_of(
        read(belongs_on_watchlist=True, watchlist_word="newer version", software="FastAPI"),
        "Is there a newer version of FastAPI?",
    )
    assert answer == WatchlistAnswer(word="version", software="FastAPI")


def test_a_release_request_with_no_software_asks_which():
    answer = answer_of(
        read(belongs_on_watchlist=True, watchlist_word="version"),
        "Tell me when there's a new version",
    )
    assert answer == WhichSoftwareAnswer(word="version")


def test_a_release_request_that_names_another_system_keeps_that_part():
    task = "Post in Teams when Kubernetes has a new release"
    answer = answer_of(
        read(belongs_on_watchlist=True, watchlist_word="release", software="Kubernetes"), task
    )
    assert isinstance(answer, CantAnswer)
    assert [(c.kind, c.text, c.needs, c.system) for c in answer.cant] == [
        ("where", "Teams", "new_system", "Teams")
    ]
    assert answer.alternative == WatchlistAnswer(word="release", software="Kubernetes")


def test_a_security_request_sent_to_the_watchlist_becomes_a_cant_with_the_watch_offered():
    task = "Tell me about Log4j security patches"
    answer = answer_of(
        read(belongs_on_watchlist=True, watchlist_word="patches", software="Log4j"), task
    )
    assert isinstance(answer, CantAnswer)
    assert answer.cant[0].note == VULNERABILITIES_PLANNED
    assert answer.alternative == WatchlistAnswer(word="patches", software="Log4j")


def test_a_watchlist_word_the_request_lacks_leaves_the_rows_to_decide_or_is_unusable():
    with_rows = read(*FOLLOW_UP_ROWS, belongs_on_watchlist=True, watchlist_word="upgrade")
    assert isinstance(answer_of(with_rows, FOLLOW_UP_TASK), SetupCardAnswer)
    assert (
        answer_of(read(belongs_on_watchlist=True, watchlist_word="upgrade"), FOLLOW_UP_TASK) is None
    )


def test_a_mixed_request_leads_with_the_watchlist_and_carries_the_workflow():
    task = "Watch React releases and list stale bug tickets every Friday"
    rows = (
        row("schedule", "Every Friday"),
        row("look_for", "Stale bug tickets", "changed", "Stale read as 14 days."),
        row("do", "List them in one ticket", "changed", "You didn't say where the list goes."),
        row("where", "", "missing"),
    )
    answer = answer_of(
        read(
            *rows,
            belongs_on_watchlist=True,
            watchlist_word="releases",
            software="React",
            name="Stale bug list",
        ),
        task,
    )
    assert isinstance(answer, WatchlistAnswer)
    assert (answer.word, answer.software) == ("releases", "React")
    assert isinstance(answer.also, SetupCardAnswer)
    assert answer.also.name == "Stale bug list"
    assert [r.kind for r in answer.also.rows] == ["schedule", "look_for", "do", "where"]


@pytest.mark.parametrize(
    ("asks", "words", "task", "expected"),
    [
        ("my_workflows", None, "Check my workflows", CheckWorkflowsAnswer()),
        (
            "my_workflows",
            "morning new-ticket check",
            "Is the morning new-ticket check running?",
            CheckWorkflowsAnswer(workflow_words="morning new-ticket check"),
        ),
        (
            "why_stopped",
            "Morning new-ticket check",
            "Why did Morning new-ticket check stop?",
            WhyStoppedAnswer(workflow_words="Morning new-ticket check"),
        ),
        ("why_stopped", "Weekly summary", "Why did my workflow stop?", WhyStoppedAnswer()),
        ("needs_me", None, "Anything to approve?", NeedsMeAnswer()),
        ("abilities", None, "What's the weather?", AbilitiesAnswer()),
    ],
    ids=["all", "one-by-name", "why-by-name", "name-not-in-request", "needs-me", "abilities"],
)
def test_a_question_about_the_persons_workflows_names_only_words_from_the_request(
    asks: str, words: str | None, task: str, expected: object
):
    assert answer_of(read(asks_about=asks, workflow_words=words), task) == expected


def test_a_question_about_workflows_wins_over_rows_the_model_also_gave():
    answer = answer_of(read(*FOLLOW_UP_ROWS, asks_about="needs_me"), "What needs me today?")
    assert answer == NeedsMeAnswer()


def test_nothing_understood_is_the_abilities_answer():
    assert answer_of(read(), "Tell me a joke") == AbilitiesAnswer()
    nothing = [row(kind, "", "missing") for kind in ("schedule", "look_for", "do", "where")]
    assert answer_of(read(*nothing), "Tell me a joke") == AbilitiesAnswer()


@pytest.mark.parametrize(
    ("task", "rest"),
    [
        ("Create the ticket without waiting for approval", "Create the ticket"),
        ("Skip the approval and file it", "file it"),
        (
            "Every Monday, list open tickets and approve it automatically",
            "Every Monday, list open tickets",
        ),
        ("File the ticket, no approval needed", "File the ticket"),
    ],
)
def test_a_request_to_skip_a_yes_is_refused_before_anything_else(task: str, rest: str):
    answer = answer_of(
        read(
            *FOLLOW_UP_ROWS,
            belongs_on_watchlist=True,
            watchlist_word="ticket",
            asks_about="needs_me",
        ),
        task,
    )
    assert answer == RefusedAnswer(rest=rest)


@pytest.mark.parametrize(
    "task",
    [
        "Run it by itself every Monday",
        "Without asking me each time, list the tickets",
        "Every Monday, list the tickets and ask an Approver to approve each one",
        "Automatically list the open tickets every morning",
    ],
)
def test_the_products_own_words_are_not_refused(task: str):
    answer = answer_of(read(*FOLLOW_UP_ROWS), task)
    assert not isinstance(answer, RefusedAnswer)


def test_a_cant_do_row_that_asks_to_skip_a_yes_is_the_second_net():
    rows = (
        *FOLLOW_UP_ROWS[:3],
        row("do", "Create it without approval", "cant_do", "Every write waits for a yes.", None),
        FOLLOW_UP_ROWS[3],
    )
    answer = answer_of(read(*rows), f"{FOLLOW_UP_TASK}, and do not bother anyone about it")
    assert answer == RefusedAnswer(rest="")


def test_a_refusal_never_calls_the_model():
    chat = ScriptedChat()
    request = AnswerRequest(task="Create the ticket without approval", model=answer_request().model)
    result = answer_task(request, lambda timeout: chat)
    assert result == Answered(answer=RefusedAnswer(rest="Create the ticket"))
    assert chat.calls == []


def test_the_model_is_asked_once_with_the_request_in_its_own_message():
    chat = ScriptedChat(structured=[read(*FOLLOW_UP_ROWS, name="Stale bug follow-up")])
    result = answer_task(answer_request(), lambda timeout: chat)
    assert isinstance(result, Answered) and isinstance(result.answer, SetupCardAnswer)
    assert len(chat.calls) == 1
    assert chat.asked == [TaskRead]
    assert chat.calls[0] == [
        ("system", ANSWER_SYSTEM),
        ("human", f"The request:\n{FOLLOW_UP_TASK}"),
    ]


def test_a_model_problem_passes_through_and_a_reading_that_does_not_hold_is_unusable():
    slow = type("ReadTimeout", (Exception,), {})("took too long")
    result = answer_task(answer_request(), lambda timeout: ScriptedChat(structured=[slow]))
    assert isinstance(result, ModelProblem) and result.reason == "too_slow"
    bad = read(belongs_on_watchlist=True, watchlist_word="upgrade")
    result = answer_task(answer_request(), lambda timeout: ScriptedChat(structured=[bad]))
    assert isinstance(result, ModelProblem) and result.reason == "unusable_answer"


def test_the_prompt_lists_the_tools_the_answers_and_no_old_names():
    for tool in ("github.read_releases", "jira.search", "jira.read_ticket", "jira.create_ticket"):
        assert tool in ANSWER_SYSTEM
    for state in ("understood", "changed", "missing", "cant_do"):
        assert state in ANSWER_SYSTEM
    for kind in ("my_workflows", "why_stopped", "needs_me", "abilities", "alternative"):
        assert kind in ANSWER_SYSTEM
    for name in ("Flint", "Forge", "Striker", "Scout", "Clerk", "Fixer"):
        assert name not in ANSWER_SYSTEM


def test_the_route_needs_the_key_and_says_when_no_model_is_connected():
    body = json.loads(answer_request().model_dump_json())
    assert make_app(None).post("/v1/planner/answer", json=body).status_code == 200
    assert make_app(None).post("/v1/planner/answer", json=body).json()["status"] == "problem"
    client: TestClient = make_app(None)
    client.headers.pop("X-Agent-Key")
    assert client.post("/v1/planner/answer", json=body).status_code == 401


def test_the_route_answers_in_the_contract():
    chat = ScriptedChat(structured=[read(*EMAIL_ROWS, name="Stale ticket list")])
    body = json.loads(
        AnswerRequest(task=EMAIL_TASK, model=answer_request().model).model_dump_json()
    )
    response = make_app(chat).post("/v1/planner/answer", json=body)
    assert response.status_code == 200
    result = answer_result_adapter.validate_python(response.json())
    assert isinstance(result, Answered) and isinstance(result.answer, CantAnswer)
    assert result.answer.cant[0].system == "email"


def test_a_cant_do_row_with_no_text_is_read_from_its_note():
    task = "Every quarter, list who has admin access in GitLab and remove anyone who has left"
    rows = (
        row("schedule", "Every quarter"),
        row("look_for", "", "cant_do", "The tools cannot read GitLab admin access lists.", None),
        row("do", "", "cant_do", "The tools cannot remove anyone's access in GitLab.", None),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows), task)
    assert isinstance(answer, CantAnswer)
    assert [(c.kind, c.needs, c.system) for c in answer.cant] == [
        ("look_for", "new_system", "GitLab"),
        ("do", "new_system", "GitLab"),
    ]


def test_a_release_request_read_as_rows_offers_the_watch_as_its_alternative():
    task = "Send a message in Teams when a release is published"
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "A release is published"),
        row("do", "", "cant_do", "The tools cannot post messages in Teams.", "Propose a ticket"),
        row("where", "", "cant_do", "The tools cannot post in Teams.", None),
    )
    answer = answer_of(read(*rows), task)
    assert isinstance(answer, CantAnswer)
    assert {c.system for c in answer.cant} == {"Teams"}
    assert answer.alternative == WatchlistAnswer(word="release", software=None)


def test_a_vulnerability_row_the_model_marked_itself_still_offers_the_watch():
    task = "Warn me about any known vulnerabilities in Log4j"
    rows = (
        row("schedule", "", "missing"),
        row(
            "look_for",
            "Known vulnerabilities in Log4j",
            "cant_do",
            "No tool checks CVEs.",
            "Read the newest Log4j releases",
        ),
        row(
            "do",
            "Warn me about them",
            "cant_do",
            "No tool can send a warning.",
            "Create one ticket",
        ),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows, software="Log4j"), task)
    assert isinstance(answer, CantAnswer)
    assert answer.alternative == WatchlistAnswer(word="vulnerabilities", software="Log4j")


def test_a_leading_article_in_the_workflow_words_is_dropped():
    answer = answer_of(
        read(asks_about="my_workflows", workflow_words="the morning new-ticket check"),
        "Is the morning new-ticket check running?",
    )
    assert answer == CheckWorkflowsAnswer(workflow_words="morning new-ticket check")


@pytest.mark.parametrize(
    ("said", "task", "word"),
    [
        ("Monitor", "Monitor Kubernetes releases", "releases"),
        ("Watch", "Watch Kubernetes for a new version", "version"),
        ("Kubernetes", "Tell me about Kubernetes security patches", "security patches"),
    ],
)
def test_a_watchlist_label_that_is_not_a_watchlist_word_takes_the_requests_own(
    said: str, task: str, word: str
):
    answer = answer_of(
        read(belongs_on_watchlist=True, watchlist_word=said, software="Kubernetes"), task
    )
    found = answer.alternative if isinstance(answer, CantAnswer) else answer
    assert found == WatchlistAnswer(word=word, software="Kubernetes")


def test_a_common_word_the_model_calls_software_gets_no_watch():
    task = "Check our packages for security advisories"
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "Security advisories for our packages", "cant_do", "No tool checks.", None),
        row("do", "", "missing"),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows, software="packages"), task)
    assert isinstance(answer, CantAnswer) and answer.alternative is None
    plain = answer_of(
        read(belongs_on_watchlist=True, watchlist_word="versions", software="versions"),
        "Keep track of our versions",
    )
    assert plain == WhichSoftwareAnswer(word="versions")


def test_a_field_change_whose_text_the_model_left_empty_is_still_a_part():
    rows = (
        row("schedule", "", "missing"),
        row("look_for", "Bug tickets in MOCK"),
        row(
            "do",
            "",
            "cant_do",
            "The tools cannot change a ticket's component.",
            "Create one ticket that lists them",
        ),
        row("where", "", "missing"),
    )
    answer = answer_of(read(*rows), COMPONENT_TASK)
    assert isinstance(answer, PartAnswer)
    assert [(c.needs, c.system) for c in answer.cant] == [("new_tool", "Jira")]
