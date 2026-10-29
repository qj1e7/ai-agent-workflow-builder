import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.api import HttpCallbacks, Runtime, Settings, create_app
from agent_runtime.contract import (
    AgentEvent,
    AgentMessageEvent,
    AgentStepFinishedEvent,
    Finding,
    GithubSource,
    SoftwareToCheck,
    TaskFailed,
    TaskFinished,
    TaskRequest,
    TaskResult,
    WatchlistInputs,
    task_result_adapter,
)
from agent_runtime.contracts import (
    FASTAPI_ID,
    LANGGRAPH_ID,
    REDIS_ID,
    watchlist_finished,
    watchlist_request,
)
from agent_runtime.events import EventLog
from agent_runtime.planner import FixedPlanner, run_task
from agent_runtime.release_source import Release, ReleaseSource
from agent_runtime.summary import ModelSummarizer, Summarizer, TemplateSummarizer
from agent_runtime.version_checker import VersionChecker
from tests.fakes import FakeClock, FakeSource, RepoSource, langgraph_tags

LANGGRAPH = "langchain-ai/langgraph"
REDIS = "redis/redis"
FASTAPI = "fastapi/fastapi"
TAGS = {LANGGRAPH: langgraph_tags(), REDIS: ["8.2.1", "8.2.0", "8.1.0"], FASTAPI: ["0.115.1"]}


class Room:
    def __init__(self, source: ReleaseSource, summarizer: Summarizer | None = None) -> None:
        self.clock = FakeClock()
        self.log = EventLog(self.clock, lambda event: None)
        self.checker = VersionChecker(
            source, summarizer or TemplateSummarizer(), sleep=self.clock.sleep
        )

    def run(self, request: TaskRequest) -> TaskResult:
        return run_task(request, FixedPlanner(), self.checker, self.log)


def request_for(*software: SoftwareToCheck) -> TaskRequest:
    request = watchlist_request("run_01JC2")
    assert isinstance(request.inputs, WatchlistInputs)
    inputs = request.inputs.model_copy(update={"software": list(software)})
    return request.model_copy(update={"inputs": inputs})


def software(
    software_id: str,
    name: str,
    ref: str,
    our_version: str | None,
    open_ticket: str | None = None,
    awaiting_approval: bool = False,
) -> SoftwareToCheck:
    return SoftwareToCheck(
        id=software_id,
        name=name,
        source=GithubSource(ref=ref),
        our_version=our_version,
        open_ticket=open_ticket,
        awaiting_approval=awaiting_approval,
    )


def langgraph(our_version: str | None, **held: Any) -> SoftwareToCheck:
    return software(LANGGRAPH_ID, "LangGraph", LANGGRAPH, our_version, **held)


def redis(our_version: str | None) -> SoftwareToCheck:
    return software(REDIS_ID, "Redis", REDIS, our_version)


def fastapi(our_version: str | None) -> SoftwareToCheck:
    return software(FASTAPI_ID, "FastAPI", FASTAPI, our_version)


def finished(result: TaskResult) -> TaskFinished:
    assert isinstance(result, TaskFinished), result
    return result


def finding(result: TaskFinished, software_id: str) -> Finding:
    return next(f for f in result.output.findings if f.software_id == software_id)


def without_timestamps(result: TaskResult) -> dict[str, Any]:
    dumped = result.model_dump(mode="json")
    for event in dumped["events"]:
        del event["ts"]
    return dumped


def summaries(events: Sequence[AgentEvent]) -> list[str]:
    return [event.summary for event in events]


def test_three_software_tell_the_story_the_contract_fixture_records():
    source = RepoSource(TAGS, refused={FASTAPI: 404})
    result = Room(source).run(watchlist_request("run_01JC2"))
    assert without_timestamps(finished(result)) == without_timestamps(watchlist_finished())


def test_a_software_behind_gets_one_ticket_naming_it():
    result = finished(Room(RepoSource(TAGS)).run(request_for(langgraph("1.2.14"))))
    found = finding(result, LANGGRAPH_ID)
    assert (found.state, found.newest, found.new_versions) == (
        "behind",
        "1.2.16",
        ["1.2.16", "1.2.15"],
    )
    [ticket] = result.output.proposed
    assert ticket.kind == "create_ticket"
    assert ticket.subject == LANGGRAPH_ID
    assert ticket.fields["title"] == "Upgrade LangGraph from 1.2.14 to 1.2.16"
    assert ticket.fields["body"] == (
        "LangGraph has 2 new releases on GitHub (langchain-ai/langgraph) newer than our version "
        "1.2.14:\n- 1.2.16\n- 1.2.15\n\nProposed by the AI workflow builder."
    )
    assert ticket.reason == "LangGraph 1.2.16 is out, and we run 1.2.14"
    assert result.output.new_tags == []


def test_releases_of_another_tag_family_never_count():
    source = RepoSource({**TAGS, LANGGRAPH: ["cli==0.9.0", "sdk==1.0.0", *langgraph_tags()]})
    behind = finished(Room(source).run(request_for(langgraph("1.2.15"))))
    assert finding(behind, LANGGRAPH_ID).new_versions == ["1.2.16"]
    other = finished(Room(source).run(request_for(langgraph("cli==0.4.37"))))
    assert (finding(other, LANGGRAPH_ID).state, finding(other, LANGGRAPH_ID).new_versions) == (
        "up_to_date",
        [],
    )


def test_drafts_and_prereleases_are_skipped():
    source = FakeSource([])
    source.releases = [
        Release(tag="1.2.18", draft=True),
        Release(tag="1.2.17", prerelease=True),
        Release(tag="1.2.16"),
    ]
    result = finished(Room(source).run(request_for(langgraph("1.2.15"))))
    assert finding(result, LANGGRAPH_ID).new_versions == ["1.2.16"]


def test_a_network_error_is_retried_the_same_way_as_a_5xx():
    source = RepoSource(TAGS, down={LANGGRAPH: None})
    room = Room(source)
    result = finished(room.run(request_for(langgraph("1.2.14"), redis("8.2.1"))))
    assert room.clock.slept == [2.0, 2.0]
    assert finding(result, LANGGRAPH_ID).detail == "GitHub could not be reached three times."
    said = [
        e.data.text
        for e in result.events
        if isinstance(e, AgentMessageEvent) and e.agent.id == "version_checker"
    ]
    assert said[0].startswith("GitHub could not be reached (try 1 of 3).")


def test_events_are_emitted_while_the_source_is_read_not_after_it():
    room = Room(RepoSource(TAGS, down={LANGGRAPH: 503}))
    seen_when_sleeping: list[int] = []
    room.clock.on_sleep = lambda: (time.sleep(0.2), seen_when_sleeping.append(len(room.log.events)))
    room.run(request_for(langgraph("1.2.14")))
    assert seen_when_sleeping == [4, 5]


def test_a_software_that_is_up_to_date_gets_no_ticket():
    result = finished(Room(RepoSource(TAGS)).run(request_for(redis("8.2.1"))))
    assert (finding(result, REDIS_ID).state, finding(result, REDIS_ID).newest) == (
        "up_to_date",
        "8.2.1",
    )
    assert result.output.proposed == []
    assert result.output.summary == "Redis is up to date."


def test_no_version_given_makes_the_newest_release_the_starting_point():
    result = finished(Room(RepoSource(TAGS)).run(request_for(redis(None))))
    found = finding(result, REDIS_ID)
    assert (found.state, found.newest, found.new_versions) == ("starting_point", "8.2.1", [])
    assert result.output.proposed == []


@pytest.mark.parametrize(
    "held", [{"open_ticket": "MOCK-7"}, {"awaiting_approval": True}], ids=["open", "awaiting"]
)
def test_a_software_with_a_ticket_already_raised_gets_no_second_one(held: dict[str, Any]):
    result = finished(Room(RepoSource(TAGS)).run(request_for(langgraph("1.2.14", **held))))
    found = finding(result, LANGGRAPH_ID)
    assert (found.state, found.newest, found.new_versions) == (
        "already_raised",
        "1.2.16",
        ["1.2.16", "1.2.15"],
    )
    assert result.output.proposed == []
    assert result.events[-1].summary == "Planner noted that there is nothing to propose."
    assert result.output.summary == (
        "No new tickets are needed, as LangGraph already has a ticket."
    )


def test_a_version_we_run_that_is_not_a_version_number_cannot_be_checked():
    result = finished(Room(RepoSource(TAGS)).run(request_for(langgraph("latest"), redis("8.2.1"))))
    assert finding(result, LANGGRAPH_ID).state == "cant_check"
    assert finding(result, REDIS_ID).state == "up_to_date"


def test_a_source_with_no_plain_version_cannot_be_checked():
    source = RepoSource({**TAGS, LANGGRAPH: ["nightly", "v2-beta"]})
    result = finished(Room(source).run(request_for(langgraph("1.2.14"), redis("8.2.1"))))
    found = finding(result, LANGGRAPH_ID)
    assert (found.state, found.detail) == ("cant_check", "No release has a plain version number.")


def test_one_source_that_answers_404_is_reported_and_the_rest_carry_on():
    source = RepoSource(TAGS, refused={FASTAPI: 404})
    result = finished(Room(source).run(request_for(fastapi("0.115.0"), langgraph("1.2.14"))))
    broken = finding(result, FASTAPI_ID)
    assert (broken.state, broken.newest) == ("cant_check", None)
    assert broken.detail == "GitHub answered 404 Not Found."
    assert finding(result, LANGGRAPH_ID).state == "behind"
    assert source.calls == [FASTAPI, LANGGRAPH]
    said = [
        e for e in result.events if isinstance(e, AgentMessageEvent) and e.agent.id != "planner"
    ]
    assert [e.data.text for e in said][0] == (
        "I could not read FastAPI's releases: GitHub answered 404 Not Found. "
        "I will carry on with the rest."
    )
    assert result.output.summary.endswith("FastAPI could not be checked.")


def test_a_source_that_stays_down_is_tried_three_times_then_given_up_while_the_rest_carry_on():
    source = RepoSource(TAGS, down={FASTAPI: 503})
    room = Room(source)
    result = finished(room.run(request_for(fastapi("0.115.0"), redis("8.2.0"))))
    assert source.calls == [FASTAPI, FASTAPI, FASTAPI, REDIS]
    assert room.clock.slept == [2.0, 2.0]
    assert (
        finding(result, FASTAPI_ID).detail == "GitHub returned 503 Service Unavailable three times."
    )
    assert finding(result, REDIS_ID).state == "behind"
    tries = [s for s in summaries(result.events) if "(try " in s]
    assert tries == [
        f"Version checker reported that GitHub answered 503 (try {n} of 3)." for n in (1, 2, 3)
    ]


def test_every_software_unreadable_fails_the_task_and_can_be_retried_after_an_outage():
    source = RepoSource(TAGS, refused={FASTAPI: 404}, down={REDIS: 503})
    result = Room(source).run(request_for(fastapi("0.115.0"), redis("8.2.1")))
    assert isinstance(result, TaskFailed)
    assert (result.error.type, result.error.retryable) == ("UpstreamUnavailable", True)
    assert result.error.message == (
        "None of the 2 watched software could be checked. GitHub answered 404 Not Found"
    )
    assert result.events[-1].kind == "agent_failed"


def test_one_software_that_cannot_be_checked_fails_with_its_own_reason_and_no_rest():
    source = RepoSource({**TAGS, LANGGRAPH: ["nightly", "v2-beta"]})
    result = Room(source).run(request_for(langgraph("1.2.14")))
    assert isinstance(result, TaskFailed)
    assert result.error.message == (
        "Could not check LangGraph: No release has a plain version number"
    )
    said = [e.data.text for e in result.events if isinstance(e, AgentMessageEvent)]
    assert said[-1] == "I could not check LangGraph: No release has a plain version number."
    assert result.events[-1].summary == "Version checker failed: LangGraph could not be checked."


def test_every_software_refused_fails_the_task_for_good():
    source = RepoSource(TAGS, refused={FASTAPI: 404, REDIS: 403})
    result = Room(source).run(request_for(fastapi("0.115.0"), redis("8.2.1")))
    assert isinstance(result, TaskFailed)
    assert (result.error.type, result.error.retryable) == ("UpstreamRejected", False)


def test_each_software_reports_its_state_in_a_read_source_step_in_input_order():
    source = RepoSource(TAGS, refused={FASTAPI: 404})
    result = finished(
        Room(source).run(request_for(fastapi("0.115.0"), redis("8.2.1"), langgraph("1.2.14")))
    )
    steps = [
        e.data.result
        for e in result.events
        if isinstance(e, AgentStepFinishedEvent) and e.data.step == "read_source"
    ]
    assert steps == [
        {"software_id": FASTAPI_ID, "state": "cant_check", "newest": None},
        {"software_id": REDIS_ID, "state": "up_to_date", "newest": "8.2.1"},
        {"software_id": LANGGRAPH_ID, "state": "behind", "newest": "1.2.16"},
    ]
    assert [f.software_id for f in result.output.findings] == [FASTAPI_ID, REDIS_ID, LANGGRAPH_ID]


def test_two_tickets_are_agreed_together():
    result = finished(Room(RepoSource(TAGS)).run(request_for(langgraph("1.2.14"), redis("8.2.0"))))
    assert len(result.output.proposed) == 2
    assert result.events[-1].summary == "Planner agreed and will propose 2 tickets for approval."
    assert result.output.summary == (
        "2 of 2 watched software have new releases: LangGraph 1.2.16 and Redis 8.2.1."
    )


def model_saying(*replies: str) -> Callable[[str], BaseChatModel]:
    def factory(name: str) -> BaseChatModel:
        return GenericFakeChatModel(messages=iter(AIMessage(content=r) for r in replies))

    return factory


def test_the_model_writes_the_summary_when_it_answers():
    sentence = "LangGraph has two new versions, and Redis is up to date."
    summarizer = ModelSummarizer("any:model", factory=model_saying(f" {sentence}\n"))
    request = request_for(langgraph("1.2.14"), redis("8.2.1"))
    result = finished(Room(RepoSource(TAGS), summarizer).run(request))
    assert result.output.summary == sentence


@pytest.mark.parametrize("reply", ["", "one\ntwo", "x" * 301])
def test_an_unusable_model_answer_falls_back_to_the_template(reply: str):
    summarizer = ModelSummarizer("any:model", factory=model_saying(reply))
    result = finished(Room(RepoSource(TAGS), summarizer).run(request_for(langgraph("1.2.14"))))
    assert result.output.summary == "LangGraph has a new release: 1.2.16."


def test_a_failing_model_falls_back_to_the_template():
    def broken(name: str) -> BaseChatModel:
        raise RuntimeError("the provider is down")

    summarizer = ModelSummarizer("any:model", factory=broken)
    result = finished(Room(RepoSource(TAGS), summarizer).run(request_for(redis("8.2.1"))))
    assert result.output.summary == "Redis is up to date."


def test_the_tasks_route_runs_a_watchlist():
    clock = FakeClock()
    callbacks = HttpCallbacks(transport=httpx.MockTransport(lambda r: httpx.Response(204)))
    checker = VersionChecker(
        RepoSource(TAGS, refused={FASTAPI: 404}), TemplateSummarizer(), sleep=clock.sleep
    )
    runtime = Runtime(checker=checker, planner=FixedPlanner(), clock=clock, callbacks=callbacks)
    settings = Settings.from_env(
        {"AGENT_API_KEY": "test-key", "CALLBACK_ALLOWED_ORIGINS": "http://platform-api:8000"}
    )
    client = TestClient(create_app(settings, runtime), headers={"X-Agent-Key": "test-key"})
    body = watchlist_request("run_01JC2").model_dump(mode="json")
    response = client.post("/v1/tasks", json=body)
    assert response.status_code == 200
    result = task_result_adapter.validate_python(response.json())
    assert isinstance(result, TaskFinished)
    assert [f.state for f in result.output.findings] == ["behind", "up_to_date", "cant_check"]
