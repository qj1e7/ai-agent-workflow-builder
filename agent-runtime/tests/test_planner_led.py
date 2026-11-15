import logging
from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from agent_runtime.answers import TaskRead
from agent_runtime.api import Settings, SettingsError, create_app
from agent_runtime.contract import (
    AbilitiesAnswer,
    Answered,
    AnswerRequest,
    DidntFollowAnswer,
    EditAnswer,
    FreeReplyAnswer,
    ModelProblem,
    PlannerFacts,
    PreviousTurn,
    RefusedAnswer,
    ScheduleChange,
    SetupCardAnswer,
    WatchlistAnswer,
    WhichSoftwareAnswer,
    WorkflowFact,
)
from agent_runtime.contracts import answer_request
from agent_runtime.planner_led import (
    Front,
    Invalid,
    Led,
    Turn,
    act_on,
    led,
    not_theirs,
    their_words,
)
from agent_runtime.reply_verifier import Verdict
from tests.fakes import ScriptedChat, asks, call
from tests.test_answers import follow_up
from tests.test_api import KEY as API_KEY
from tests.test_api import SETTINGS as API_SETTINGS
from tests.test_free_reply import api_runtime
from tests.test_questions import FACTS, reading

CLEAN = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)
FLAGGED = Verdict(says_it_happened=True, skips_a_yes=False, claims_unbuilt=False)
WORKFLOWS = PlannerFacts(
    watchlist=FACTS.watchlist,
    workflows=[WorkflowFact(name="Morning check", state="on", last_run="Done", last_run_at=None)],
)


def request(task: str, **fields: Any) -> AnswerRequest:
    return AnswerRequest(task=task, model=answer_request().model, **fields)


def run(
    task: str,
    *turns: object,
    read: TaskRead | None = None,
    then: list[object] | None = None,
    **fields: Any,
) -> tuple[Led, ScriptedChat]:
    """The ai_led answer for `task`: `turns` are the model's tool calls, in order, `read` the
    rules' reading beside the first, and `then` each later structured answer, such as the
    verifier's."""
    chat = ScriptedChat(script=list(turns), structured=[read or reading(), *(then or [])])
    return led(request(task, **fields), lambda timeout: chat), chat


def tool(name: str, call_id: str = "c1", **args: Any) -> object:
    return asks(call(name, args, call_id))


def shown(result: Led) -> object:
    assert isinstance(result.result, Answered)
    return result.result.answer


def test_the_word_rule_refuses_before_any_model_call() -> None:
    chat = ScriptedChat()
    result = led(request("Create the ticket without approval"), lambda timeout: chat)

    assert isinstance(shown(result), RefusedAnswer)
    assert chat.calls == []


def test_the_rules_refusal_wins_over_what_the_model_proposes() -> None:
    task = "Make the ticket, Bob can hear about it after"
    skip = reading(
        "none",
        skips_the_yes={
            "whose": "an_approver_or_anyone_else",
            "said": "Bob can hear about it after",
        },
    )

    result, _ = run(task, tool("set_up_workflow", request=task), read=skip)

    assert isinstance(shown(result), RefusedAnswer)
    assert result.tools == ("front_refusal",)


def test_a_request_to_add_software_with_no_name_asks_which() -> None:
    result, chat = run("help me add a software", tool("ask_which_software", word="software"))

    assert shown(result) == WhichSoftwareAnswer(word="software")
    assert chat.offered[0][0] == "set_up_workflow"


def test_the_answer_to_which_software_completes_the_add() -> None:
    before = PreviousTurn(request="help me add a software", kind="which_software")

    result, chat = run(
        "LangChain", tool("watch_software", software="LangChain"), previous=before, facts=FACTS
    )

    assert shown(result) == WatchlistAnswer(word="LangChain", software="LangChain")
    briefing = chat.calls[-1][-1].text
    assert "help me add a software" in briefing and "Which software should I watch?" in briefing


def test_a_software_the_person_never_typed_goes_back_to_the_model_once() -> None:
    result, chat = run(
        "add a tool please",
        tool("watch_software", software="Kubernetes"),
        tool("ask_which_software", call_id="c2", word="tool"),
    )

    assert shown(result) == WhichSoftwareAnswer(word="tool")
    told = chat.calls[-1][-1]
    assert isinstance(told, ToolMessage) and "never typed 'Kubernetes'" in told.text
    assert result.tools == ("watch_software", "ask_which_software")


def test_a_second_call_that_does_not_validate_gives_the_fixed_fallback() -> None:
    result, _ = run(
        "add a tool please",
        tool("watch_software", software="Kubernetes"),
        tool("watch_software", call_id="c2", software="Grafana"),
    )

    assert shown(result) == DidntFollowAnswer()
    assert result.fell_back == "invalid"
    assert len(result.errors) == 2


def test_a_software_already_watched_is_answered_not_offered_again() -> None:
    result, _ = run(
        "add LangGraph",
        tool("watch_software", software="LangGraph"),
        tool(
            "reply",
            call_id="c2",
            form="answer",
            text="LangGraph is on your Watchlist.",
            looked_at=["watchlist"],
        ),
        facts=FACTS,
        then=[CLEAN],
    )

    assert isinstance(shown(result), FreeReplyAnswer)
    assert "already on the Watchlist" in result.errors[0]


def test_a_time_the_model_guesses_never_shows() -> None:
    result, _ = run(
        "move the morning check later",
        tool("change_workflow", action="schedule", workflow_words="morning check", at="10:00"),
        facts=WORKFLOWS,
    )

    edit = shown(result)
    assert isinstance(edit, EditAnswer) and edit.schedule is not None
    assert edit.schedule.at is None and edit.schedule.time_unclear


def acted(task: str, name: str, **args: Any) -> object:
    """One tool call checked on its own, where the rules read the message as nothing at all."""
    chat = ScriptedChat()
    turn = Turn(
        request(task, facts=WORKFLOWS),
        Front(reading(), AbilitiesAnswer()),
        lambda timeout: chat,
        lambda timeout: chat,
    )
    outcome, _ = act_on(cast(AIMessage, tool(name, **args)), turn)
    return outcome


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ({"at": "10:00"}, "never guessed"),
        ({"day": "friday"}, "don't name friday"),
        ({"hour": 9}, "don't say 9"),
        ({}, "names no day and no time"),
        ({"workflow_words": "evening check", "at": "07:00"}, "never typed 'evening check'"),
    ],
)
def test_a_schedule_change_holds_only_what_the_person_said(args: dict[str, Any], why: str) -> None:
    outcome = acted(
        "make the morning check run at 7am on mondays",
        "change_workflow",
        action="schedule",
        **{"workflow_words": "morning check", **args},
    )

    assert isinstance(outcome, Invalid) and why in outcome.why


def test_a_time_in_the_persons_words_changes_the_schedule() -> None:
    result, _ = run(
        "move the morning check to 10am",
        tool("change_workflow", action="schedule", workflow_words="morning check", at="10:00"),
        facts=WORKFLOWS,
    )

    assert shown(result) == EditAnswer(
        workflow_words="morning check", schedule=ScheduleChange(at="10:00")
    )


def test_an_approver_cannot_change_a_workflow() -> None:
    result, _ = run(
        "pause the morning check",
        tool("change_workflow", action="pause", workflow_words="morning check"),
        tool("reply", call_id="c2", form="answer", text="An Operator can pause a workflow."),
        changes_workflows=False,
        then=[CLEAN],
    )

    assert isinstance(shown(result), FreeReplyAnswer)
    assert "Approver" in result.errors[0]


def test_a_reply_that_says_something_happened_never_shows() -> None:
    said_it = {"form": "answer", "text": "I set up the workflow for you."}

    result, _ = run("thanks", tool("reply", **said_it), tool("reply", call_id="c2", **said_it))

    assert shown(result) == DidntFollowAnswer()
    assert "claims_done" in result.errors[0]


def test_the_verifier_checks_every_reply_the_code_checks_let_through() -> None:
    greeting = {"form": "answer", "text": "Hello. Type what you want done in the box on Home."}

    flagged, _ = run(
        "hi",
        tool("reply", **greeting),
        tool("reply", call_id="c2", **greeting),
        then=[FLAGGED, FLAGGED],
    )
    clean, _ = run("hi", tool("reply", **greeting), then=[CLEAN])

    assert shown(flagged) == DidntFollowAnswer()
    assert isinstance(shown(clean), FreeReplyAnswer)


def test_a_workflow_is_read_into_the_rules_own_card_without_a_second_reading() -> None:
    task = (
        "Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create "
        "one follow-up ticket that lists them in MOCK"
    )

    result, chat = run(task, tool("set_up_workflow", request=task), read=follow_up())

    assert isinstance(shown(result), SetupCardAnswer)
    assert [shape.__name__ for shape in chat.asked] == ["TaskRead"]


def test_a_request_with_words_the_person_never_typed_is_not_set_up() -> None:
    result, _ = run(
        "list new bugs every monday",
        tool("set_up_workflow", request="list new bugs in MOCK every monday"),
        tool(
            "reply",
            call_id="c2",
            form="clarify",
            text="Which Jira project?",
            choices=["MOCK", "Another project"],
        ),
        then=[CLEAN],
    )

    assert isinstance(shown(result), FreeReplyAnswer)
    assert "MOCK" in result.errors[0]


def test_a_failed_model_turn_gives_the_fixed_fallback() -> None:
    result, _ = run("hi", TimeoutError("slow"))

    assert shown(result) == DidntFollowAnswer()
    assert result.fell_back == "call"


def test_a_failed_reading_is_the_offline_answer_as_in_rules_mode() -> None:
    chat = ScriptedChat(
        script=[tool("reply", form="answer", text="Hello.")], structured=[TimeoutError("slow")]
    )

    result = led(request("hi"), lambda timeout: chat)

    assert isinstance(result.result, ModelProblem)


def test_words_are_theirs_only_when_the_person_typed_them() -> None:
    assert not_theirs("list the new bugs every Monday", "list new bug every mondays") == []
    assert not_theirs("list new bugs in MOCK", "list new bugs") == ["MOCK"]
    assert their_words("node js", "watch Node.js please") == "Node.js"
    assert their_words("Kubernetes", "add a tool") is None


def test_planner_mode_picks_the_ai_led_planner_and_rules_stays_the_default() -> None:
    env = {"AGENT_API_KEY": "k", "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000"}

    assert Settings.from_env(env).planner_mode == "rules"
    assert Settings.from_env({**env, "PLANNER_MODE": "ai_led"}).planner_mode == "ai_led"
    with pytest.raises(SettingsError):
        Settings.from_env({**env, "PLANNER_MODE": "free"})


def test_the_answer_route_runs_the_ai_led_planner_when_the_setting_asks() -> None:
    chat = ScriptedChat(
        script=[tool("ask_which_software", word="software")], structured=[reading("none")]
    )
    runtime = replace(api_runtime(), chat_source=lambda access: lambda timeout: chat)
    settings = replace(API_SETTINGS, planner_mode="ai_led")
    client = TestClient(create_app(settings, runtime), headers={"X-Agent-Key": API_KEY})

    body = request("help me add a software").model_dump(mode="json")
    answered = client.post("/v1/planner/answer", json=body).json()

    assert answered["answer"]["kind"] == "which_software"
    assert chat.offered and chat.offered[0][-1] == "reply"


class ProviderRefused(Exception):
    """A provider's 400, with a key quoted in its free text, as a provider may."""

    status_code = 400
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "bad header x-api-key: sk-ant-api03-FAKEKEYFAKEKEY",
        },
    }

    def __str__(self) -> str:
        return self.body["error"]["message"]


def test_a_failed_turn_logs_the_status_and_the_error_type_never_the_providers_words(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result, _ = run("hi", ProviderRefused())

    assert shown(result) == DidntFollowAnswer()
    assert "status 400, invalid_request_error" in caplog.text
    assert "FAKEKEY" not in caplog.text and "x-api-key" not in caplog.text


def test_a_turn_with_no_tool_call_goes_back_to_the_model_once() -> None:
    result, chat = run(
        "hi",
        AIMessage(content="Hello there."),
        tool("reply", form="answer", text="Hello. Type what you want done in the box on Home."),
        then=[CLEAN],
    )

    assert isinstance(shown(result), FreeReplyAnswer)
    assert "exactly one tool" in result.errors[0]
    retry = next(c for c in chat.calls if any(m.text == "Hello there." for m in c))
    assert retry[-1].type == "human" and "exactly one tool" in retry[-1].text
