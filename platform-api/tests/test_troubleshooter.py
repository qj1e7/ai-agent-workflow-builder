from typing import get_args

import pytest

from platform_api.monitoring.events import RunFailedData
from platform_api.monitoring.troubleshooter import ADVICE, answers, explain, explain_failure
from platform_api.wire import FailureReason, FailureStage


def test_every_failure_reason_has_advice():
    assert set(ADVICE) == set(get_args(FailureReason.__value__))


def failure(
    reason: FailureReason, retryable: bool, stage: FailureStage = "working", message: str = "m"
) -> RunFailedData:
    return RunFailedData(stage=stage, reason=reason, retryable=retryable, message=message)


def test_a_retryable_agent_error_gets_the_generic_advice():
    assert explain_failure(failure("AgentError", True)) == explain("AgentError")


def test_a_write_jira_refused_is_told_to_check_jira_and_start_again():
    assert explain_failure(failure("WriteFailed", True)) == explain("WriteFailed")
    advice = explain_failure(failure("WriteFailed", False))
    assert advice != explain("WriteFailed")
    assert advice.suggested_action == "ask_maintainer"
    assert "Jira" in advice.likely_cause and "new run" in advice.suggestion


def test_other_reasons_ignore_the_retryable_flag():
    for reason in get_args(FailureReason.__value__):
        if reason in {"AgentError", "WriteFailed"}:
            continue
        assert explain_failure(failure(reason, False)) == explain(reason)
        assert explain_failure(failure(reason, True)) == explain(reason)


AGENTS_STOPPED = "The agents couldn't finish this step."

# Each stop as the platform writes it (orchestration's service.py and runs.py), with what the
# person is told happened. That answer may hold only what the stop itself carries.
STOPS: list[tuple[FailureStage, FailureReason, bool, str, str]] = [
    (
        "working",
        "AgentError",
        True,
        "UpstreamUnavailable: Could not check LangGraph: GitHub returned 503 Service "
        "Unavailable three times",
        "An agent could not finish its work.",
    ),
    (
        "working",
        "AgentError",
        True,
        "ModelUnavailable: The model did not answer in time. Try again, or pick a faster model.",
        "An agent could not finish its work.",
    ),
    (
        "working",
        "AgentError",
        False,
        "ModelNeeded: Connect an AI model in Settings to run agents.",
        "No AI model is connected, so the agents couldn't start.",
    ),
    (
        "working",
        "AgentError",
        False,
        "AgentTooSlow: Release reader ran out of time. A task has 50 seconds.",
        "An agent ran out of time before it finished.",
    ),
    (
        "working",
        "AgentError",
        False,
        "AgentTooLong: Release reader used all 8 steps without finishing.",
        "An agent used all its steps without finishing.",
    ),
    (
        "working",
        "AgentError",
        False,
        "UpstreamRejected: GitHub answered 404 Not Found",
        AGENTS_STOPPED,
    ),
    (
        "working",
        "AgentError",
        False,
        "UpstreamRejected: Could not check LangGraph: No release has a plain version number",
        AGENTS_STOPPED,
    ),
    (
        "working",
        "AgentError",
        False,
        "AgentError: The Version checker stopped because of an unexpected error",
        AGENTS_STOPPED,
    ),
    (
        "working",
        "AgentError",
        False,
        "The agent runtime refused the task (422): bad inputs",
        AGENTS_STOPPED,
    ),
    (
        "working",
        "AgentError",
        False,
        'The agents titled the ticket for LangGraph differently from "Upgrade LangGraph from '
        '1.2.14 to 1.2.16"',
        AGENTS_STOPPED,
    ),
    (
        "working",
        "UnboundIntent",
        False,
        "No connector is bound for create_ticket",
        "The agents proposed an action this use case cannot carry out.",
    ),
    (
        "pending",
        "DispatchFailed",
        True,
        "The workflow engine did not take the work leg: n8n is down",
        "The platform could not hand the run to the workflow engine.",
    ),
    (
        "working",
        "TimedOut",
        True,
        "The workflow engine did not come back while the run was working",
        "The run waited too long for the workflow engine and gave up.",
    ),
    (
        "proposed",
        "WorkflowNodeError",
        True,
        "The n8n workflow 'release-check' failed at its step 'Ask approval': boom",
        "A step in the workflow engine failed.",
    ),
    (
        "proposed",
        "OutOfOrderStep",
        False,
        "The workflow called write_action out of order. Reload it from git and start a new run",
        "The workflow called a step out of order, so the run stopped.",
    ),
    (
        "acting",
        "WriteFailed",
        True,
        "jira create_ticket failed: read timed out",
        "The approved write action could not be completed.",
    ),
    (
        "acting",
        "WriteFailed",
        False,
        "jira create_ticket was refused: Jira answered 400 Bad Request",
        "The approved write was refused.",
    ),
    (
        "acting",
        "WriteFailed",
        False,
        "jira create_ticket was refused: Jira already has MOCK-1 with this write's label, but "
        "the platform did not make it. A person needs to check that ticket, then start a new run.",
        "The approved write was refused.",
    ),
    (
        "acting",
        "SafetyDenied",
        False,
        "the safety checker denied the write: digest_mismatch",
        "The safety checker blocked the write action.",
    ),
    (
        "acting",
        "TimedOut",
        True,
        "The workflow engine did not come back while the run was acting",
        "The run waited too long for the workflow engine and gave up.",
    ),
    (
        "acting",
        "DispatchFailed",
        True,
        "The workflow engine did not take the act leg: n8n is down",
        "The platform could not hand the run to the workflow engine.",
    ),
    (
        "acting",
        "WorkflowNodeError",
        True,
        "The n8n workflow 'release-check' failed at its step 'Write action': boom",
        "A step in the workflow engine failed.",
    ),
    (
        "acting",
        "OutOfOrderStep",
        False,
        "The workflow called run_agents out of order. Reload it from git and start a new run",
        "The workflow called a step out of order, so the run stopped.",
    ),
]


def stopped(row: tuple[FailureStage, FailureReason, bool, str, str]) -> RunFailedData:
    stage, reason, retryable, message, _ = row
    return failure(reason, retryable, stage, message)


def test_the_stops_cover_every_failure_reason():
    assert {reason for _, reason, *_ in STOPS} == set(get_args(FailureReason.__value__))


@pytest.mark.parametrize("row", STOPS, ids=lambda row: f"{row[0]}-{row[3][:30]}")
def test_what_happened_says_only_what_the_stop_carries(
    row: tuple[FailureStage, FailureReason, bool, str, str],
):
    assert answers(stopped(row)).what_happened == row[4]


def test_what_happened_is_the_advice_explanation():
    for row in STOPS:
        assert answers(stopped(row)).what_happened == explain_failure(stopped(row)).explanation


def test_an_agent_stop_with_no_known_reason_gets_one_advice_naming_no_cause():
    first, *others = [explain_failure(stopped(row)) for row in STOPS if row[4] == AGENTS_STOPPED]
    assert len(others) == 4 and all(advice == first for advice in others)
    assert first.suggested_action == "ask_maintainer"
    assert "new run" in first.suggestion


def test_no_model_connected_is_told_to_connect_one():
    advice = explain_failure(
        failure("AgentError", False, message="ModelNeeded: Connect an AI model in Settings.")
    )
    assert "connect an AI model in Settings" in advice.suggestion


def test_nothing_was_written_before_the_write_step():
    for row in STOPS:
        if row[0] != "acting":
            assert answers(stopped(row)).what_affected == "Nothing was written."


def test_at_the_write_step_a_write_may_have_reached_jira_and_no_answer_says_start_a_new_run():
    for row in STOPS:
        if row[0] != "acting":
            continue
        got = answers(stopped(row))
        assert got.what_affected == "The approved write may or may not have reached Jira."
        said = " ".join([got.what_happened, got.what_affected, got.can_fix]).lower()
        assert "nothing was written" not in said
        assert "new run" not in said


def test_the_two_refused_cases_cannot_be_retried_and_go_to_support():
    for stop in (failure("AgentError", False), failure("WriteFailed", False, "acting")):
        got = answers(stop)
        assert got.retry.possible is False and got.retry.asks_again is False
        assert got.next == "report"
        assert got.can_fix == "This kind of stop can't be retried."


def test_a_retry_is_possible_exactly_when_the_failure_is_retryable():
    for row in STOPS:
        got = answers(stopped(row))
        assert got.retry.possible is row[2]
        assert got.next == ("retry" if row[2] else "report")


def test_a_retry_before_the_write_runs_the_work_again_and_waits_for_a_yes():
    for row in STOPS:
        if row[0] == "acting" or not row[2]:
            continue
        got = answers(stopped(row))
        assert got.retry.asks_again is True
        assert "still waits for a yes" in got.can_fix


@pytest.mark.parametrize(
    "reason", ["WriteFailed", "TimedOut", "DispatchFailed", "WorkflowNodeError"]
)
def test_a_retry_at_the_write_step_carries_on_without_a_new_yes(reason: FailureReason):
    got = answers(failure(reason, True, "acting"))
    assert (got.retry.possible, got.retry.asks_again) == (True, False)
    assert got.next == "retry"
    assert "nobody has to approve again" in got.can_fix
