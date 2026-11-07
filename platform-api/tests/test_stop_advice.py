"""The advice after a stop that retrying cannot fix has one source, in platform_api.shared. The
run's failure summary, the retry refusal and the AI troubleshooter must all give it, for every
kind of stop that can happen at the write step and before it."""

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
from platform_api.shared import BEFORE_WRITE_STOP_ADVICE, WRITE_STOP_ADVICE
from platform_api.wire import FailureReason as WireReason
from platform_api.wire import FailureStage

AT_THE_WRITE_STEP = [FailureReason.WRITE_FAILED, FailureReason.SAFETY_DENIED]
BEFORE_THE_WRITE_STEP = [
    (Stage.WORKING, FailureReason.AGENT_ERROR),
    (Stage.WORKING, FailureReason.UNBOUND_INTENT),
    (Stage.PROPOSED, FailureReason.OUT_OF_ORDER_STEP),
    (Stage.PENDING, FailureReason.OUT_OF_ORDER_STEP),
]


def wire(stage: Stage, reason: FailureReason) -> RunFailedData:
    return RunFailedData(
        stage=cast(FailureStage, stage.value),
        reason=cast(WireReason, reason.value),
        retryable=False,
        message="m",
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
