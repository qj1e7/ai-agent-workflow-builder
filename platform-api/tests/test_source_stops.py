"""A block that calls out and gets no usable connection stops the run with words that name the
source, the block, what went wrong and the tries n8n made. The troubleshooter explains the stop
from the same facts (spike S5, docs/evidence/2026-11-24-simulation-spike)."""

from typing import Any

import pytest

from platform_api.monitoring.events import RunFailedData
from platform_api.monitoring.source_stops import (
    REQUEST_LIMIT_SECONDS,
    SourceStop,
    read_stop,
    stop_words,
)
from platform_api.monitoring.troubleshooter import answers, explain_failure, what_happened
from platform_api.orchestration.n8n_calls import ExecutionFacts, FailedExecution, failure_words
from platform_api.shared import N8nExecutionId

# n8n-workflow 2.42.3's own words for each connection error, which n8n 2.42.6 puts on the block
# (dist/cjs/errors/abstract/node.error.js). The spike saw the first and third on real blocks.
ABORTED = "The connection was aborted, perhaps the server is offline"
REFUSED = "The service refused the connection - perhaps it is offline"
RESET = (
    "The connection to the server was closed unexpectedly, perhaps it is offline. You can retry "
    "the request immediately or wait and retry later."
)
NOT_FOUND = (
    "The connection cannot be established, this usually occurs due to an incorrect host (domain) "
    "value"
)
TIMED_OUT = (
    "The connection timed out, consider setting the 'Retry on Fail' option in the node settings"
)
UNREACHABLE = "The host is unreachable, perhaps the server is offline"

FACTS = ExecutionFacts("wf1", "trigger", None, None, "v1")
RETRIED: dict[str, Any] = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
NO_ANSWER_CAUSE = "Nothing came back in that time, so it may be down, busy or out of reach."


def block(
    name: str,
    node_type: str,
    version: float,
    parameters: dict[str, Any] | None = None,
    **settings: Any,
) -> dict[str, Any]:
    """A block as n8n's record of the execution holds it."""
    return {
        "name": name,
        "type": node_type,
        "typeVersion": version,
        "parameters": parameters or {},
        **settings,
    }


def stopped(node: dict[str, Any] | None, message: str, read_anything: bool = True) -> str:
    name = "Get releases" if node is None else str(node["name"])
    failed = FailedExecution(N8nExecutionId("45"), FACTS, name, message, node)
    return failure_words(failed, read_anything)


GITHUB = block(
    "Get releases",
    "n8n-nodes-base.github",
    1.1,
    {"resource": "release", "operation": "getAll", "owner": "langchain-ai"},
    **RETRIED,
)
JIRA = block("Find tickets", "n8n-nodes-base.jira", 1, {"resource": "issue", "operation": "getAll"})


def test_the_per_try_limit_is_thirty_seconds():
    assert REQUEST_LIMIT_SECONDS == 30


def test_github_that_does_not_answer_is_named_with_its_block_the_limit_and_the_tries():
    assert stopped(GITHUB, ABORTED) == (
        "GitHub didn't answer within 30 seconds, so \"Get releases\" stopped after 3 tries. "
        f"{NO_ANSWER_CAUSE}"
    )


def test_jira_that_refuses_the_connection_says_so():
    assert stopped(JIRA, REFUSED) == (
        'Jira refused the connection, so "Find tickets" stopped. It may be down, or the block '
        "may point at the wrong address."
    )


def test_teams_that_closes_the_connection_says_so():
    teams = block(
        "Tell the team",
        "n8n-nodes-base.microsoftTeams",
        2,
        {"resource": "channelMessage", "operation": "create"},
        retryOnFail=True,
        maxTries=2,
    )
    assert stopped(teams, RESET) == (
        'Teams closed the connection, so "Tell the team" stopped after 2 tries. It ended the '
        "connection before a full answer came back, so it may have failed or restarted."
    )


@pytest.mark.parametrize("message", [NOT_FOUND, TIMED_OUT, UNREACHABLE])
def test_slack_that_cannot_be_reached_says_so(message: str):
    slack = block("Post in Slack", "n8n-nodes-base.slack", 2.3, {"operation": "post"})
    assert stopped(slack, message) == (
        'Slack could not be reached, so "Post in Slack" stopped. n8n couldn\'t reach it, so it '
        "may be down, or its address may be wrong or blocked."
    )


def test_an_http_request_names_its_host_and_its_own_time_limit():
    http = block(
        "Check status",
        "n8n-nodes-base.httpRequest",
        4.2,
        {"url": "https://status.example.com/api/v2/status.json", "options": {"timeout": 10000}},
        retryOnFail=True,
        maxTries=2,
    )
    assert stopped(http, ABORTED) == (
        'status.example.com didn\'t answer within 10 seconds, so "Check status" stopped after 2 '
        f"tries. {NO_ANSWER_CAUSE}"
    )


def test_an_http_request_with_a_written_host_and_an_expression_after_it_names_the_host():
    http = block(
        "Get item",
        "n8n-nodes-base.httpRequest",
        4.2,
        {"url": "=https://api.example.com/items/{{ $json.id }}"},
    )
    assert stopped(http, ABORTED).startswith(
        'api.example.com didn\'t answer within 30 seconds, so "Get item" stopped.'
    )


@pytest.mark.parametrize(
    "url", ["={{ $json.url }}", "=https://{{ $json.host }}/v1", "", "not a web address"]
)
def test_an_http_request_whose_host_is_not_written_out_is_the_source(url: str):
    http = block("Call out", "n8n-nodes-base.httpRequest", 4.2, {"url": url})
    assert stopped(http, ABORTED).startswith(
        'The source didn\'t answer within 30 seconds, so "Call out" stopped.'
    )


def test_a_block_the_registry_does_not_name_is_the_source():
    notion = block("Notion", "n8n-nodes-base.notion", 2.2, {"resource": "page"})
    assert stopped(notion, NOT_FOUND) == (
        'The source could not be reached, so "Notion" stopped. n8n couldn\'t reach it, so it may '
        "be down, or its address may be wrong or blocked."
    )


def test_a_failure_with_no_record_of_its_block_still_names_the_block():
    assert stopped(None, ABORTED) == (
        'The source didn\'t answer within 30 seconds, so "Get releases" stopped. '
        f"{NO_ANSWER_CAUSE}"
    )


@pytest.mark.parametrize(
    ("settings", "tries"),
    [
        ({"retryOnFail": True, "maxTries": 9}, " after 5 tries"),
        ({"retryOnFail": True}, " after 3 tries"),
        ({"retryOnFail": True, "maxTries": 1}, " after 2 tries"),
        ({"retryOnFail": False, "maxTries": 4}, ""),
        ({}, ""),
    ],
)
def test_the_tries_are_the_ones_n8n_makes_for_the_blocks_settings(
    settings: dict[str, Any], tries: str
):
    github = block("Get releases", "n8n-nodes-base.github", 1.1, {}, **settings)
    assert stopped(github, ABORTED).startswith(
        f'GitHub didn\'t answer within 30 seconds, so "Get releases" stopped{tries}.'
    )


def test_a_run_that_read_nothing_still_says_so_first():
    assert stopped(JIRA, REFUSED, read_anything=False).startswith(
        'Stopped before it read anything. Jira refused the connection, so "Find tickets" stopped.'
    )


@pytest.mark.parametrize(
    "message", ["Bad credentials", "The resource you are requesting could not be found", ""]
)
def test_any_other_failure_keeps_n8n_s_own_words(message: str):
    said = message or "n8n gave no reason"
    assert stopped(GITHUB, message) == f'"Get releases" failed in n8n: {said}.'


def test_our_own_blocks_keep_their_words():
    """Our blocks call only our platform, which reads each source with a limit of its own and
    answers in its own words."""
    read = block("Read release", "CUSTOM.wabRead", 1, {"source": "github_releases"}, **RETRIED)
    assert stopped(read, ABORTED) == f'"Read release" failed in n8n: {ABORTED}.'


def run_failed(message: str) -> RunFailedData:
    return RunFailedData(
        stage="working", reason="WorkflowNodeError", retryable=True, message=message
    )


def test_the_troubleshooter_explains_a_source_stop_from_its_facts():
    failure = run_failed(stopped(GITHUB, ABORTED))
    headline = "GitHub didn't answer within 30 seconds, so \"Get releases\" stopped after 3 tries."
    assert what_happened(failure) == headline
    advice = explain_failure(failure)
    assert advice.explanation == headline
    assert advice.likely_cause == NO_ANSWER_CAUSE
    assert advice.suggested_action == "retry"
    assert advice.suggestion == (
        "Retry the run in a few minutes. If it stops here again, check that GitHub is up and "
        "that n8n can reach it."
    )
    assert answers(failure).safe_to_retry.startswith("Yes.")


def test_the_troubleshooter_names_no_system_it_does_not_know():
    notion = block("Notion", "n8n-nodes-base.notion", 2.2)
    advice = explain_failure(run_failed(stopped(notion, REFUSED, read_anything=False)))
    assert advice.explanation == 'The source refused the connection, so "Notion" stopped.'
    assert advice.likely_cause == "It may be down, or the block may point at the wrong address."
    assert "check that the source is up" in advice.suggestion


def test_the_troubleshooter_keeps_its_advice_for_any_other_block_failure():
    failure = run_failed('"Get releases" failed in n8n: Bad credentials.')
    assert explain_failure(failure).explanation == "A step in the workflow engine failed."


@pytest.mark.parametrize(
    "stop",
    [
        SourceStop("GitHub", "no_answer", 30_000, "Get releases", 3),
        SourceStop("status.example.com", "no_answer", 1_500, "Check status", 2),
        SourceStop("Jira", "refused", 30_000, 'The "big" search', 1),
        SourceStop(None, "cut_off", 30_000, "Notion", 5),
        SourceStop("Slack", "unreachable", 30_000, "Post in Slack", 1),
    ],
)
def test_the_words_give_back_the_facts_they_were_made_from(stop: SourceStop):
    assert read_stop(stop_words(stop)) == stop
    assert read_stop(f"Stopped before it read anything. {stop_words(stop)}") == stop


def test_a_limit_under_a_second_is_said_as_it_is():
    words = stop_words(SourceStop("GitHub", "no_answer", 500, "Get releases", 1))
    assert words.startswith("GitHub didn't answer within 0.5 seconds,")
    one = stop_words(SourceStop("GitHub", "no_answer", 1_000, "Get releases", 1))
    assert one.startswith("GitHub didn't answer within 1 second,")


def test_words_that_are_no_source_stop_give_no_facts():
    assert read_stop('"Get releases" failed in n8n: Bad credentials.') is None
    assert read_stop("GitHub didn't answer.") is None


@pytest.mark.parametrize(
    ("said", "source"),
    [
        ("UpstreamUnavailable: Confluence could not be reached.", "Confluence"),
        ("UpstreamUnavailable: Jira could not be reached.", "Jira"),
        ("UpstreamUnavailable: Could not check LangGraph: GitHub returned 503 three times", "GitHub"),
    ],
)
def test_an_agent_whose_source_did_not_answer_names_that_source(said: str, source: str):
    """An agent reads GitHub, Jira and Confluence through the agent runtime, which gives up after
    10 seconds a try and says which source it was."""
    failure = RunFailedData(stage="working", reason="AgentError", retryable=True, message=said)
    assert what_happened(failure) == f"{source} didn't answer."
