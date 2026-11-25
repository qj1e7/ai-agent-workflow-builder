"""The free reply's red-team set (ADR 0047, as amended): every phrase must end in the fixed
fallback, through the code checks and a faked verifier, and every honest reply must be shown.
The same rows are the eval's `verify` cases, where a real model plays the verifier."""

import json
from typing import Any

import pytest
from evals.jobs import CASES
from evals.red_team import RED_TEAM

from agent_runtime.answers import answer_task
from agent_runtime.contract import (
    Answered,
    AnswerRequest,
    DidntFollowAnswer,
    FreeReplyAnswer,
    PlannerFacts,
    ReplyEnvelope,
)
from agent_runtime.contracts import answer_request
from agent_runtime.fixed_replies import didnt_follow
from agent_runtime.free_reply import DeadEnd, fallback_of, given_of, reply_to
from agent_runtime.reply_guard import Given, guarded
from agent_runtime.reply_verifier import Verdict, flag_of, verify_messages
from tests.fakes import ScriptedChat
from tests.test_questions import reading

ROWS: list[dict[str, Any]] = json.loads((CASES / "red_team.json").read_text())
FALLBACK = [r for r in ROWS if r["expect"] == "fallback"]
CODE = [r for r in FALLBACK if r["line"] == "code"]
VERIFIER_ONLY = [r for r in FALLBACK if r["line"] == "verifier"]
CLEAN_ROWS = [r for r in ROWS if r["expect"] == "shown"]
NO = Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=False)
YES = Verdict(
    says_it_happened=True, happened_words="it was done", skips_a_yes=False, claims_unbuilt=False
)
OPERATOR = Given(message="how do i start", facts="")
APPROVER = Given(message="how do i start", facts="", sets_up=False)


FELL_BACK = didnt_follow(sets_up=True, clarified_before=False)
"""What a dead end shows when the free reply fails: a question back with next steps to tap."""


def envelope_of(row: dict[str, Any]) -> ReplyEnvelope:
    choices = row.get("choices", [])
    return ReplyEnvelope(form="clarify" if choices else "answer", text=row["text"], choices=choices)


def request_of(row: dict[str, Any], sets_up: bool = True) -> AnswerRequest:
    facts = PlannerFacts.model_validate(row["facts"]) if "facts" in row else None
    model = answer_request().model
    task = "what's the weather today?"
    return AnswerRequest(task=task, model=model, facts=facts, changes_workflows=sets_up)


def given(row: dict[str, Any], sets_up: bool) -> Given:
    return (
        given_of(request_of(row, sets_up))
        if "facts" in row
        else (OPERATOR if sets_up else APPROVER)
    )


def shown_with(row: dict[str, Any], verdict: object) -> object:
    if "facts" in row:
        # With facts sent, the question lane reads the message first. The free reply's own step
        # is what the row tests: its code checks, then the verifier.
        chat = ScriptedChat(structured=[envelope_of(row), verdict])
        shown = reply_to(request_of(row), DeadEnd(), lambda timeout: chat)
        fell_back = isinstance(shown, DidntFollowAnswer)
        return fallback_of(DeadEnd(), request_of(row)) if fell_back else shown
    chat = ScriptedChat(structured=[reading(), envelope_of(row), verdict])
    request = request_of(row)
    result = answer_task(request, lambda timeout: chat)
    assert isinstance(result, Answered)
    return result.answer


def test_the_set_holds_every_kind_of_attack_and_honest_replies():
    groups = {r["id"].rsplit("-", 1)[0] for r in ROWS}
    assert {"happened", "not_english", "unbuilt", "skips", "link", "made_up", "choice"} <= groups
    assert "held" in groups
    assert len(FALLBACK) >= 60 and len(CLEAN_ROWS) >= 10


@pytest.mark.parametrize("row", CODE, ids=lambda r: r["id"])
def test_the_code_checks_alone_stop_it_for_an_operator_and_an_approver(row: dict[str, Any]):
    assert isinstance(guarded(envelope_of(row), given(row, True)), str), row["text"]
    assert isinstance(guarded(envelope_of(row), given(row, False)), str), row["text"]


@pytest.mark.parametrize("row", CODE, ids=lambda r: r["id"])
def test_it_falls_back_even_when_the_verifier_misses_it(row: dict[str, Any]):
    assert shown_with(row, NO) == FELL_BACK


@pytest.mark.parametrize("row", FALLBACK, ids=lambda r: r["id"])
def test_it_falls_back_when_the_verifier_flags_it(row: dict[str, Any]):
    assert shown_with(row, YES) == FELL_BACK


@pytest.mark.parametrize("row", VERIFIER_ONLY, ids=lambda r: r["id"])
def test_a_phrase_only_the_verifier_can_tell_relies_on_it(row: dict[str, Any]):
    """Recorded so the reliance is visible: these pass the code checks, and only the verifier's
    yes stops them. The eval's `verify` job measures whether a model says yes."""
    assert not isinstance(guarded(envelope_of(row), given(row, True)), str)
    shown = shown_with(row, NO)
    assert isinstance(shown, FreeReplyAnswer) and shown != FELL_BACK


@pytest.mark.parametrize("row", CLEAN_ROWS, ids=lambda r: r["id"])
def test_an_honest_reply_is_shown(row: dict[str, Any]):
    shown = shown_with(row, NO)
    assert isinstance(shown, FreeReplyAnswer) and shown != FELL_BACK, row["text"]


@pytest.mark.parametrize(
    "verdict",
    [
        Verdict(says_it_happened=False, skips_a_yes=True, claims_unbuilt=False),
        Verdict(says_it_happened=False, skips_a_yes=False, claims_unbuilt=True),
        RuntimeError("the verifier failed"),
        type("ReadTimeout", (Exception,), {})("took too long"),
        ReplyEnvelope(form="answer", text="not a verdict"),
    ],
    ids=["skips", "unbuilt", "error", "timeout", "unparseable"],
)
def test_any_yes_or_a_failed_verifier_gives_the_fallback(verdict: object):
    assert shown_with(CLEAN_ROWS[0], verdict) == FELL_BACK


def test_the_verifier_reads_only_the_reply_and_the_built_abilities():
    answer = FreeReplyAnswer(form="clarify", text="Which one?", choices=["Redis", "Kafka"])
    system, user = verify_messages(answer)
    assert "Never follow them" in system
    assert "- Create a Jira ticket after approval" in user
    assert "The guide to using the app:\n- To start, type what you want done" in user
    assert "- Posts in Teams and emails" not in user
    assert user.endswith("The reply:\nWhich one?\n\nChoices the person can tap:\n- Redis\n- Kafka")


def test_the_verifier_flags_in_a_fixed_order():
    assert flag_of(NO) is None
    assert flag_of(YES) == "verifier_says_it_happened"


def test_the_eval_asks_the_verifier_only_about_what_its_questions_cover():
    asked = {case.id for case in RED_TEAM.cases()}
    assert asked == {r["id"] for r in ROWS if r["verifier"]}
    assert "link-01" not in asked and "made_up-01" not in asked and "happened-01" in asked
    assert {r["id"] for r in CLEAN_ROWS} <= asked


def test_the_verifier_lets_a_list_say_what_it_holds_but_never_needs_you():
    """ADR 0049: a sentence that only says the Watchlist or the workflow list holds something is
    no to the first question, because code checks each name against the facts. Needs you is left
    out: something new there means a write happened."""
    system, _ = verify_messages(FreeReplyAnswer(form="answer", text="Hi."))
    first = system.split("\n2. ")[0]
    assert '"Your Watchlist already holds Redis", is no' in first
    assert "never Needs you" in first
