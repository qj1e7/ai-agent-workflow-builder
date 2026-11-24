"""Simulation mode is Ready only where platform-api says it is set up (ADR 0054, PR 7). The
Planner's briefing, the free reply and its verifier all follow that one rule, never the fixed
registry, so the model never claims simulation works where there is no simulation n8n."""

import pytest
from pydantic import ValidationError

from agent_runtime.contract import AnswerRequest, FreeReplyAnswer
from agent_runtime.contracts import answer_request
from agent_runtime.free_reply import reply_messages
from agent_runtime.planner_led import briefing
from agent_runtime.reply_verifier import verify_messages
from tests.test_free_reply import WEATHER, dead_end_of

PLAIN = "Try each new workflow on practice systems before its test run"
PLANNED = f"- workflows.simulate: {PLAIN}. Planned. Why: Practice systems aren't set up here."
READY = f"- workflows.simulate: {PLAIN}. Ready. Not an offer."
SIMULATE = ["workflows.simulate"]


def request(**fields: object) -> AnswerRequest:
    return AnswerRequest.model_validate(
        {"task": WEATHER, "model": answer_request().model.model_dump(), **fields}
    )


def test_the_planner_s_briefing_says_ready_only_where_the_platform_set_it_up():
    assert PLANNED in briefing(()) and READY not in briefing(())
    assert READY in briefing(SIMULATE) and PLANNED not in briefing(SIMULATE)
    assert briefing(SIMULATE) is briefing(("workflows.simulate",)), "one cached text for each"


def test_the_free_reply_follows_the_same_rule():
    _, nowhere = reply_messages(request(), dead_end_of(WEATHER))
    _, here = reply_messages(request(ready_here=SIMULATE), dead_end_of(WEATHER))
    assert PLANNED in nowhere and READY not in nowhere
    assert READY in here and PLANNED not in here


def test_the_verifier_counts_it_as_built_only_where_it_is_set_up():
    reply = FreeReplyAnswer(form="answer", text="I can try it on practice systems first.")
    _, nowhere = verify_messages(reply)
    _, here = verify_messages(reply, SIMULATE)
    assert f"- {PLAIN}" not in nowhere
    assert f"- {PLAIN}" in here


def test_a_request_says_nothing_is_turned_on_unless_the_platform_says_so():
    assert request().ready_here == []
    assert request(ready_here=SIMULATE).ready_here == SIMULATE
    with pytest.raises(ValidationError):
        request(ready_here=["jira.delete"])
