"""The advice after a stop that retrying cannot fix has one source, in platform_api.shared. The
run's failure summary, the retry refusal and the AI troubleshooter must all give it, for every
kind of stop that can happen at the write step and before it. A write refused because Jira's
settings changed after the yes says why first, in the same words on all three (ADR 0041)."""

from typing import cast

import pytest

from platform_api.monitoring import explain_failure
from platform_api.monitoring.events import RunFailedData
from platform_api.orchestration.runs import (
    Failure,
    FailureReason,
    Stage,
    cannot_retry,
    run_failed,
)
from platform_api.shared import BEFORE_WRITE_STOP_ADVICE, JIRA_SITE_CHANGED, WRITE_STOP_ADVICE
from platform_api.wire import FailureReason as WireReason
from platform_api.wire import FailureStage

AT_THE_WRITE_STEP = [FailureReason.WRITE_FAILED, FailureReason.SAFETY_DENIED]
BEFORE_THE_WRITE_STEP = [
    (Stage.WORKING, FailureReason.AGENT_ERROR),
    (Stage.WORKING, FailureReason.UNBOUND_INTENT),
    (Stage.PROPOSED, FailureReason.OUT_OF_ORDER_STEP),
    (Stage.PENDING, FailureReason.OUT_OF_ORDER_STEP),
]


def wire(stage: Stage, reason: FailureReason, message: str = "m") -> RunFailedData:
    return RunFailedData(
        stage=cast(FailureStage, stage.value),
        reason=cast(WireReason, reason.value),
        retryable=False,
        message=message,
    )


@pytest.mark.parametrize("reason", AT_THE_WRITE_STEP, ids=lambda r: r.value)
def test_at_the_write_step_all_three_say_to_look_for_the_ticket_first(reason: FailureReason):
    failure = Failure(reason, "m", retryable=False)
    assert run_failed(Stage.ACTING, failure).summary.endswith(" " + WRITE_STOP_ADVICE)
    assert cannot_retry(Stage.ACTING, failure).endswith(" " + WRITE_STOP_ADVICE)
    assert WRITE_STOP_ADVICE in explain_failure(wire(Stage.ACTING, reason)).suggestion


@pytest.mark.parametrize("stage,reason", BEFORE_THE_WRITE_STEP, ids=lambda x: str(x))
def test_before_the_write_step_all_three_say_to_start_a_new_run(
    stage: Stage, reason: FailureReason
):
    failure = Failure(reason, "m", retryable=False)
    assert run_failed(stage, failure).summary.endswith(" " + BEFORE_WRITE_STOP_ADVICE)
    assert cannot_retry(stage, failure).endswith(" " + BEFORE_WRITE_STOP_ADVICE)
    advice = explain_failure(wire(stage, reason)).suggestion
    assert "start a new run" in advice
    assert WRITE_STOP_ADVICE not in advice


def test_a_write_refused_for_another_jira_says_why_then_the_write_step_advice_on_all_three():
    failure = Failure(FailureReason.SAFETY_DENIED, JIRA_SITE_CHANGED, retryable=False)
    said = f"{JIRA_SITE_CHANGED} {WRITE_STOP_ADVICE}"
    assert run_failed(Stage.ACTING, failure).summary == f"The run failed (SafetyDenied): {said}"
    assert cannot_retry(Stage.ACTING, failure) == f"SafetyDenied cannot be retried: {said}"
    advice = explain_failure(wire(Stage.ACTING, FailureReason.SAFETY_DENIED, JIRA_SITE_CHANGED))
    assert f"{advice.explanation} {advice.suggestion}".startswith(said)
    assert "check Jira's settings" in advice.suggestion


def test_only_that_refusal_sends_people_to_jira_s_settings():
    other = explain_failure(wire(Stage.ACTING, FailureReason.SAFETY_DENIED))
    assert other.explanation != JIRA_SITE_CHANGED
    assert "Jira's settings" not in other.suggestion
