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
from platform_api.orchestration.n8n_calls import (
    ExecutionFacts,
    FailedExecution,
    block_failure,
    failure_words,
)
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
HTTP = "n8n-nodes-base.httpRequest"


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
"""A search, which n8n 2.42.6's Jira block sends as a POST (Jira.node.js, /api/2/search/jql)."""


def test_the_per_try_limit_is_thirty_seconds():
    assert REQUEST_LIMIT_SECONDS == 30


def test_github_that_does_not_answer_is_named_with_its_block_the_limit_and_the_tries():
    assert stopped(GITHUB, ABORTED) == (
        'GitHub didn\'t answer within 30 seconds, so "Get releases" stopped after 3 tries. '
        f"{NO_ANSWER_CAUSE}"
    )


def test_a_read_sent_as_a_post_keeps_n8n_s_own_five_minutes():
    """Only GET, HEAD and OPTIONS get the 30 seconds, so nothing that could have landed is sent
    again by Retry On Fail after a short wait."""
    assert stopped(JIRA, ABORTED).startswith(
        'Jira didn\'t answer within 5 minutes, so "Find tickets" stopped.'
    )


def test_a_jira_read_sent_as_a_get_has_the_thirty_seconds():
    ticket = block(
        "Get ticket", "n8n-nodes-base.jira", 1, {"resource": "issue", "operation": "get"}
    )
    assert stopped(ticket, ABORTED).startswith(
        'Jira didn\'t answer within 30 seconds, so "Get ticket" stopped.'
    )


@pytest.mark.parametrize(
    ("node_type", "version", "parameters", "system"),
    [
        ("n8n-nodes-base.slack", 2.3, {"operation": "post"}, "Slack"),
        (
            "n8n-nodes-base.microsoftTeams",
            2,
            {"resource": "channelMessage", "operation": "create"},
            "Teams",
        ),
        ("n8n-nodes-base.gmail", 2.1, {"resource": "message", "operation": "send"}, "Gmail"),
    ],
)
def test_a_post_keeps_n8n_s_own_five_minutes(
    node_type: str, version: float, parameters: dict[str, Any], system: str
):
    post = block("Tell the team", node_type, version, parameters)
    assert stopped(post, ABORTED).startswith(
        f'{system} didn\'t answer within 5 minutes, so "Tell the team" stopped.'
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


@pytest.mark.parametrize(
    ("method", "timeout", "limit"),
    [
        ("POST", None, "5 minutes"),
        ("PUT", None, "5 minutes"),
        ("HEAD", None, "30 seconds"),
        ("GET", 300000, "30 seconds"),
        ("POST", 300000, "5 minutes"),
        ("POST", 20000, "20 seconds"),
    ],
)
def test_an_http_request_s_limit_follows_its_method(method: str, timeout: int | None, limit: str):
    """n8n gives HTTP Request 3 to 4.5 a limit of 300 s when its Timeout is empty
    (HttpRequestV3.node.js), and our image cuts that limit to 30 s only for a read."""
    options = {} if timeout is None else {"timeout": timeout}
    parameters = {"method": method, "url": "https://hooks.example.com/x", "options": options}
    http = block("Send", HTTP, 4.2, parameters)
    assert stopped(http, ABORTED).startswith(
        f'hooks.example.com didn\'t answer within {limit}, so "Send" stopped.'
    )


@pytest.mark.parametrize("version", [1, 2])
def test_an_old_http_request_keeps_its_own_hour(version: int):
    """HTTP Request 1 and 2 wait an hour when their Timeout is empty (HttpRequestV1.node.js)."""
    http = block("Old call", HTTP, version, {"url": "https://old.example.com/a"})
    assert stopped(http, ABORTED).startswith(
        'old.example.com didn\'t answer within 1 hour, so "Old call" stopped.'
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"url": "https://api.example.com/a", "options": {"timeout": "={{ $json.wait }}"}},
        {"url": "https://api.example.com/a", "method": "={{ $json.method }}"},
    ],
)
def test_a_limit_or_method_set_by_an_expression_is_not_said(parameters: dict[str, Any]):
    http = block("Call out", HTTP, 4.2, parameters)
    assert stopped(http, ABORTED) == (
        f'api.example.com didn\'t answer in time, so "Call out" stopped. {NO_ANSWER_CAUSE}'
    )


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://a.example.com\\@b.example.com/x", "The source"),
        ("https://user@b.example.com/x", "The source"),
        ("https://user:pass@b.example.com/x", "The source"),
        ("https://b.example.com:notaport/x", "The source"),
        ("https://b_example.com/x", "The source"),
        ("https://API.Example.com:8443/x", "api.example.com"),
        ("http://10.0.0.5:8080/health", "10.0.0.5"),
        ("http://[fd00::1]:8080/health", "fd00::1"),
    ],
)
def test_only_a_plain_host_name_or_address_is_named(url: str, host: str):
    """n8n reads a.example.com\\@b.example.com as a.example.com, so a parser that reads
    b.example.com would name the wrong system. Anything but a plain host is the source."""
    http = block("Call out", HTTP, 4.2, {"url": url})
    assert stopped(http, ABORTED).startswith(f"{host} didn't answer within 30 seconds,")


def test_a_block_the_registry_does_not_name_is_the_source():
    notion = block("Notion", "n8n-nodes-base.notion", 2.2, {"resource": "page"})
    assert stopped(notion, NOT_FOUND) == (
        'The source could not be reached, so "Notion" stopped. n8n couldn\'t reach it, so it may '
        "be down, or its address may be wrong or blocked."
    )


def test_a_block_whose_method_is_not_known_says_no_limit():
    notion = block("Notion", "n8n-nodes-base.notion", 2.2, {"resource": "page"})
    assert stopped(notion, ABORTED).startswith(
        'The source didn\'t answer in time, so "Notion" stopped.'
    )


def test_a_failure_with_no_record_of_its_block_still_names_the_block():
    assert stopped(None, ABORTED) == (
        f'The source didn\'t answer in time, so "Get releases" stopped. {NO_ANSWER_CAUSE}'
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
    releases = {"resource": "release", "operation": "getAll"}
    github = block("Get releases", "n8n-nodes-base.github", 1.1, releases, **settings)
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


GONE = "zzfake-owner/no-such-repo-xyz"
OUR_READ = block("Read release", "CUSTOM.wabRead", 1, {"source": "github_releases", "place": GONE})
NOT_FOUND_HEADLINE = f'GitHub can\'t find {GONE}, so "Read release" stopped.'
NOT_FOUND_CAUSE = (
    "The workflow may name the wrong one, or it may have been renamed, deleted or made private."
)


def test_a_place_our_read_s_source_does_not_have_is_named_with_the_source_and_the_place():
    """25 Nov walk-through: a release check of a repository GitHub doesn't have stopped with
    '"Read release" failed in n8n: Our platform could not do this step (HTTP 503)'. The Read
    block now shows our platform's words, and the stop names GitHub and the repository."""
    said = f"GitHub can't find {GONE}."
    assert stopped(OUR_READ, said) == f"{NOT_FOUND_HEADLINE} {NOT_FOUND_CAUSE}"
    retried = {**OUR_READ, **RETRIED}
    assert stopped(retried, said, read_anything=False) == (
        f'Stopped before it read anything. GitHub can\'t find {GONE}, so "Read release" '
        f"stopped after 3 tries. {NOT_FOUND_CAUSE}"
    )


def test_n8n_s_own_block_never_speaks_for_our_platform():
    said = f"GitHub can't find {GONE}."
    assert stopped(GITHUB, said) == f'"Get releases" failed in n8n: {said}'


@pytest.mark.parametrize("source", ["Acme", "The repository", "Our platform"])
def test_only_a_source_our_platform_reads_is_named_as_not_finding_a_place(source: str):
    """Review of d7b0b1ac: the source is read from an allow-list, so words of another shape that
    happen to say "can't find" are n8n's words for the block, never a source stop."""
    said = f"{source} can't find {GONE}."
    assert stopped(OUR_READ, said) == f'"Read release" failed in n8n: {said}'
    assert (
        read_stop(f'{source} can\'t find {GONE}, so "Read release" stopped. {NOT_FOUND_CAUSE}')
        is None
    )


def test_the_answers_for_a_place_the_source_does_not_have_say_not_to_retry():
    """Review of d7b0b1ac and re-check of dadc3812: the run can't be retried, and the answers say
    so from that one fact, as the advice does."""
    failure = not_found()
    assert not failure.retryable
    found = answers(failure)
    assert found.safe_to_retry == (
        "No. This kind of stop can't be retried. Check that the workflow names the right one and "
        "that it still exists on GitHub, then start a new run."
    )
    assert (found.retry.possible, found.next) == (False, "report")
    assert what_happened(failure) == NOT_FOUND_HEADLINE


def run_failed(message: str) -> RunFailedData:
    return RunFailedData(
        stage="working", reason="WorkflowNodeError", retryable=True, message=message
    )


def test_the_troubleshooter_explains_a_source_stop_from_its_facts():
    failure = run_failed(stopped(GITHUB, ABORTED))
    headline = 'GitHub didn\'t answer within 30 seconds, so "Get releases" stopped after 3 tries.'
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


def not_found(retryable: bool = False) -> RunFailedData:
    """The run's stop at our Read block whose source has no such place, as the platform fails the
    run (`block_failure`): it can't be retried."""
    failed = FailedExecution(
        N8nExecutionId("45"), FACTS, "Read release", f"GitHub can't find {GONE}.", OUR_READ
    )
    failure = block_failure(failed, read_anything=True)
    return RunFailedData(
        stage="working",
        reason="WorkflowNodeError",
        retryable=failure.retryable and retryable,
        message=failure.message,
    )


@pytest.mark.parametrize("retryable", [False, True], ids=["as now", "an older run"])
def test_the_troubleshooter_explains_a_place_the_source_does_not_have_from_its_facts(
    retryable: bool,
):
    """Re-check of dadc3812: the stop is read whatever `retryable` says, so a run failed before
    this change is explained the same way."""
    failure = run_failed(stopped(OUR_READ, f"GitHub can't find {GONE}."))
    failure = failure.model_copy(update={"retryable": retryable})
    assert what_happened(failure) == NOT_FOUND_HEADLINE
    advice = explain_failure(failure)
    assert advice.explanation == NOT_FOUND_HEADLINE
    assert advice.likely_cause == NOT_FOUND_CAUSE
    assert advice.suggested_action == "ask_maintainer"
    assert advice.suggestion == (
        "Check that the workflow names the right one and that it still exists on GitHub, then "
        "start a new run."
    )


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
        SourceStop("Jira", "no_answer", 300_000, "Find tickets", 3),
        SourceStop("old.example.com", "no_answer", 3_600_000, "Old call", 1),
        SourceStop("api.example.com", "no_answer", None, "Call out", 1),
        SourceStop("Jira", "refused", 30_000, 'The "big" search', 1),
        SourceStop(None, "cut_off", 30_000, "Notion", 5),
        SourceStop("Slack", "unreachable", 30_000, "Post in Slack", 1),
        SourceStop("GitHub", "not_found", None, "Read release", 1, "zzfake-owner/no-such-repo"),
        SourceStop("GitHub", "not_found", None, 'The "old" read', 3, "a/b.c"),
    ],
)
def test_the_words_give_back_the_facts_they_were_made_from(stop: SourceStop):
    assert read_stop(stop_words(stop)) == stop
    assert read_stop(f"Stopped before it read anything. {stop_words(stop)}") == stop


def test_a_limit_is_said_in_minutes_or_hours_when_it_is_whole_ones():
    said = [
        stop_words(SourceStop("X", "no_answer", ms, "B", 1)).split(", so")[0]
        for ms in (60_000, 90_000, 120_000, 3_600_000, 7_200_000)
    ]
    assert said == [
        "X didn't answer within 1 minute",
        "X didn't answer within 90 seconds",
        "X didn't answer within 2 minutes",
        "X didn't answer within 1 hour",
        "X didn't answer within 2 hours",
    ]


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
        (
            "UpstreamUnavailable: Could not check LangGraph: GitHub returned 503 three times",
            "GitHub",
        ),
    ],
)
def test_an_agent_whose_source_did_not_answer_names_that_source(said: str, source: str):
    """An agent reads GitHub, Jira and Confluence through the agent runtime, which gives up after
    10 seconds a try and says which source it was."""
    failure = RunFailedData(stage="working", reason="AgentError", retryable=True, message=said)
    assert what_happened(failure) == f"{source} didn't answer."


@pytest.mark.parametrize(
    "said",
    [
        "UpstreamUnavailable: Could not check LangGraph: Acme could not be reached.",
        "UpstreamUnavailable: The Platform could not be reached.",
        "UpstreamUnavailable: Our Jira could not be reached.",
        "UpstreamUnavailable: GitHubby returned 503 three times",
    ],
)
def test_an_agent_stop_names_only_a_source_the_runtime_s_own_sentences_name(said: str):
    """Only the runtime's fixed sentences, at the start of a sentence, name the source."""
    failure = RunFailedData(stage="working", reason="AgentError", retryable=True, message=said)
    assert what_happened(failure) == explain_failure(failure).explanation
