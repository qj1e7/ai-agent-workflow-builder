import time

import pytest

from agent_runtime.contract import (
    AgentFailedData,
    AgentMessageData,
    AgentStepFinishedData,
    ReleaseCheckInputs,
    TaskError,
    TaskOutput,
)
from agent_runtime.events import Draft
from agent_runtime.summary import TemplateSummarizer
from agent_runtime.version_checker import Release, SourceRejected, VersionChecker
from tests.fakes import FakeClock, FakeSource, langgraph_tags

REPO = "langchain-ai/langgraph"
PLAIN = ReleaseCheckInputs(repo=REPO, tag_pattern=r"^\d+\.\d+\.\d+$")


class Run:
    def __init__(self, source: FakeSource) -> None:
        self.clock = FakeClock()
        self.source = source
        self.drafts: list[Draft] = []
        self.checker = VersionChecker(source, TemplateSummarizer(), sleep=self.clock.sleep)

    def check(self, last: str | None, inputs: ReleaseCheckInputs = PLAIN) -> TaskOutput | TaskError:
        return self.checker.check(inputs, last, self.drafts.append)

    def messages(self) -> list[str]:
        return [d.data.text for d in self.drafts if isinstance(d.data, AgentMessageData)]


def finished(outcome: TaskOutput | TaskError) -> TaskOutput:
    assert isinstance(outcome, TaskOutput), outcome
    return outcome


def failed(outcome: TaskOutput | TaskError) -> TaskError:
    assert isinstance(outcome, TaskError), outcome
    return outcome


def test_new_releases_become_one_create_ticket_proposal():
    run = Run(FakeSource(langgraph_tags()))
    output = finished(run.check("1.2.14"))
    assert output.new_tags == ["1.2.16", "1.2.15"]
    assert output.summary == "2 new releases: 1.2.16, 1.2.15"
    assert output.carry_forward.last_known_tag == "1.2.16"
    [intent] = output.proposed
    assert intent.kind == "create_ticket"
    assert intent.fields == {
        "title": "New LangGraph releases: 1.2.16, 1.2.15",
        "body": "Releases newer than 1.2.14 on langchain-ai/langgraph:\n- 1.2.16\n- 1.2.15\n\n"
        "Proposed by the AI workflow builder.",
    }
    assert intent.reason == "New plain-version releases since 1.2.14"


def test_no_new_releases_finishes_with_no_intents_and_the_same_watermark():
    output = finished(Run(FakeSource(langgraph_tags())).check("1.2.16"))
    assert output.new_tags == []
    assert output.proposed == []
    assert output.carry_forward.last_known_tag == "1.2.16"
    assert output.summary == "No new releases since 1.2.16"


@pytest.mark.parametrize(
    ("last", "said"),
    [
        ("1.2.15", "One release is newer than 1.2.15: 1.2.16. I suggest a ticket for it."),
        (
            "1.2.14",
            "Two releases are newer than 1.2.14: 1.2.16 and 1.2.15. I suggest one ticket for both.",
        ),
        (
            "1.2.13",
            "Three releases are newer than 1.2.13: 1.2.16, 1.2.15 and 1.2.14. "
            "I suggest one ticket for all.",
        ),
        ("1.2.16", "Nothing is newer than 1.2.16. I have nothing to propose."),
    ],
)
def test_the_finding_is_said_in_one_plain_sentence_pair(last: str, said: str):
    run = Run(FakeSource(langgraph_tags()))
    finished(run.check(last))
    assert run.messages()[-1] == said


def test_releases_of_another_family_never_count():
    tags = ["cli==0.9.0", "sdk==1.0.0", *langgraph_tags()]
    assert finished(Run(FakeSource(tags)).check("1.2.15")).new_tags == ["1.2.16"]
    assert finished(Run(FakeSource(tags)).check("cli==0.4.37")).new_tags == []


def test_drafts_and_prereleases_are_skipped():
    run = Run(FakeSource([]))
    run.source.releases = [
        Release(tag="1.2.18", draft=True),
        Release(tag="1.2.17", prerelease=True),
        Release(tag="1.2.16"),
    ]
    assert finished(run.check("1.2.15")).new_tags == ["1.2.16"]


def test_a_first_run_records_a_starting_point_and_proposes_nothing():
    output = finished(Run(FakeSource(langgraph_tags())).check(None))
    assert output.new_tags == []
    assert output.proposed == []
    assert output.carry_forward.last_known_tag == "1.2.16"


def test_retries_a_503_then_succeeds_and_reports_each_failed_try():
    run = Run(FakeSource(langgraph_tags(), failures=[503, 503]))
    output = finished(run.check("1.2.14"))
    assert output.new_tags == ["1.2.16", "1.2.15"]
    assert run.clock.slept == [2.0, 2.0]
    assert run.source.calls == [REPO] * 3
    assert run.messages()[:2] == [
        "GitHub answered 503 Service Unavailable (try 1 of 3). Waiting 2 s before trying again.",
        "GitHub answered 503 Service Unavailable (try 2 of 3). Waiting 2 s before trying again.",
    ]


def test_gives_up_after_three_tries_with_a_retryable_upstream_error():
    run = Run(FakeSource(langgraph_tags(), failures=[503, 503, 503, 503]))
    error = failed(run.check("1.2.14"))
    assert error == TaskError(
        type="UpstreamUnavailable",
        message="GitHub returned 503 Service Unavailable three times",
        retryable=True,
    )
    assert run.clock.slept == [2.0, 2.0]
    assert len(run.source.calls) == 3
    assert (
        run.messages()[-1]
        == "GitHub answered 503 Service Unavailable (try 3 of 3). I am giving up."
    )
    last = run.drafts[-1].data
    assert isinstance(last, AgentFailedData)
    assert (last.step, last.error_type, last.retryable) == (
        "fetch_releases",
        "UpstreamUnavailable",
        True,
    )


def test_a_network_error_is_retried_the_same_way():
    run = Run(FakeSource(langgraph_tags(), failures=[None, None, None]))
    error = failed(run.check("1.2.14"))
    assert error.message == "GitHub could not be reached three times"
    assert error.retryable
    assert run.messages()[0].startswith("GitHub could not be reached (try 1 of 3).")


def test_a_refusal_is_not_retried_and_is_not_retryable():
    run = Run(FakeSource(langgraph_tags()))

    def refuse(repo: str) -> list[Release]:
        raise SourceRejected(404)

    run.source.fetch = refuse
    error = failed(run.check("1.2.14"))
    assert error.type == "UpstreamRejected"
    assert error.message == "GitHub answered 404 Not Found"
    assert not error.retryable
    assert run.clock.slept == []


def test_events_are_emitted_while_the_node_runs_not_after_it():
    run = Run(FakeSource(langgraph_tags(), failures=[503, 503, 503]))
    seen_when_sleeping: list[int] = []
    run.clock.on_sleep = lambda: (time.sleep(0.2), seen_when_sleeping.append(len(run.drafts)))
    run.check("1.2.14")
    assert seen_when_sleeping == [2, 3]


@pytest.mark.parametrize(("last", "message"), [("nightly", "'nightly' is not a version tag")])
def test_input_the_agent_cannot_use_fails_without_retry(last: str, message: str):
    run = Run(FakeSource(langgraph_tags()))
    error = failed(run.check(last))
    assert error.type == "InvalidTask"
    assert message in error.message
    assert not error.retryable
    assert run.source.calls == []


def test_the_fetch_step_reports_the_count_and_the_latest_matching_tag():
    run = Run(FakeSource(["cli==0.4.37", *langgraph_tags()]))
    run.check("1.2.14")
    results = [d.data.result for d in run.drafts if isinstance(d.data, AgentStepFinishedData)]
    assert results[0] == {"release_count": 31, "latest": "1.2.16"}
