from typing import get_args

from platform_api.monitoring.events import RunFailedData
from platform_api.monitoring.troubleshooter import ADVICE, explain, explain_failure
from platform_api.wire import FailureReason


def test_every_failure_reason_has_advice():
    assert set(ADVICE) == set(get_args(FailureReason.__value__))


def failure(reason: FailureReason, retryable: bool) -> RunFailedData:
    return RunFailedData(stage="working", reason=reason, retryable=retryable, message="m")


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
