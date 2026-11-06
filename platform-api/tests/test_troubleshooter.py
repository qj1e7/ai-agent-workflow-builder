from datetime import UTC, datetime
from typing import get_args

from platform_api.monitoring import PLATFORM
from platform_api.monitoring.events import (
    ActivityEvent,
    RunFailedData,
    WriteActionDone,
    WriteActionDoneData,
)
from platform_api.monitoring.troubleshooter import (
    ADVICE,
    AGENT_REFUSED,
    WRITE_REFUSED,
    Advice,
    answers,
    explain,
    explain_failure,
)
from platform_api.shared import RunId, UserId
from platform_api.wire import FailureReason


def test_every_failure_reason_has_advice():
    assert set(ADVICE) == set(get_args(FailureReason.__value__))


def failure(reason: FailureReason, retryable: bool, stage: str = "working") -> RunFailedData:
    return RunFailedData(stage=stage, reason=reason, retryable=retryable, message="m")  # type: ignore[arg-type]


def written(seq: int) -> ActivityEvent:
    return WriteActionDone(
        run_id=RunId("run_01TEST"),
        seq=seq,
        ts=datetime(2026, 11, 7, tzinfo=UTC),
        actor=PLATFORM,
        summary="Created a ticket.",
        data=WriteActionDoneData(
            connector="jira",
            operation="create_issue",
            external_reference="MOCK-1",
            approved_by=[UserId("bob")],
        ),
    )


REASONS = get_args(FailureReason.__value__)


def test_a_retryable_agent_error_gets_the_generic_advice():
    assert explain_failure(failure("AgentError", True)) == explain("AgentError")


def test_an_agent_refused_by_its_source_is_told_to_check_the_use_case():
    advice = explain_failure(failure("AgentError", False))
    assert advice != explain("AgentError")
    assert advice.suggested_action == "ask_maintainer"
    assert "repository" in advice.likely_cause
    assert "new run" in advice.suggestion


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


def test_every_reason_answers_with_its_own_explanation():
    for reason in REASONS:
        for retryable in (True, False):
            got = answers([], failure(reason, retryable))
            assert got.what_happened == explain_failure(failure(reason, retryable)).explanation


def test_the_two_refused_cases_say_a_retry_would_get_the_same_answer():
    cases: list[tuple[FailureReason, Advice]] = [
        ("AgentError", AGENT_REFUSED),
        ("WriteFailed", WRITE_REFUSED),
    ]
    for reason, refused in cases:
        got = answers([], failure(reason, False, "acting"))
        assert got.what_happened == refused.explanation
        assert got.retry.possible is False
        assert got.next == "report"
        assert "same place" in got.can_fix


def test_a_retry_is_possible_exactly_when_the_failure_is_retryable():
    for reason in REASONS:
        assert answers([], failure(reason, True)).retry.possible is True
        assert answers([], failure(reason, False)).retry.possible is False


def test_a_retry_before_the_yes_runs_the_work_again_and_waits_for_a_yes():
    for stage in ("pending", "working", "proposed"):
        got = answers([], failure("AgentError", True, stage))
        assert got.retry.asks_again is True
        assert got.next == "retry"
        assert "still waits for a yes" in got.can_fix


def test_a_write_failure_after_the_yes_retries_without_a_new_yes():
    got = answers([], failure("WriteFailed", True, "acting"))
    assert got.retry.possible is True
    assert got.retry.asks_again is False
    assert "nobody has to approve again" in got.can_fix


def test_a_failure_nobody_can_retry_never_promises_a_safe_retry():
    for reason in REASONS:
        got = answers([], failure(reason, False, "acting"))
        assert got.retry.asks_again is False
        assert got.can_fix.startswith("Not by retrying")


def test_what_was_affected_counts_the_writes_done_before_the_stop():
    stopped = failure("WriteFailed", True, "acting")
    none = answers([], stopped)
    assert (none.written, none.what_affected) == (0, "Nothing was written.")
    one = answers([written(1)], stopped)
    assert (one.written, one.what_affected) == (1, "1 write was done before the stop.")
    three = answers([written(1), written(2), written(3)], stopped)
    assert (three.written, three.what_affected) == (3, "3 writes were done before the stop.")


def test_no_answer_names_a_cause_the_platform_cannot_know():
    for reason in REASONS:
        for retryable in (True, False):
            got = answers([], failure(reason, retryable))
            text = " ".join([got.what_happened, got.what_affected, got.can_fix]).lower()
            assert "maintenance" not in text
